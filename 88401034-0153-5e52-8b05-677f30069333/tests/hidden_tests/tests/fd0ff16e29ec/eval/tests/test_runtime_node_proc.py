"""Processes, threads and sockets: child_process (sync/async/fork), cluster, worker_threads, the web
Worker, process.stdin, TypeScript entries, net (TCP/unix), dgram, tls loopback and dns literals."""

from conftest import golden, write_files


def _ok(r):
    assert (r.returncode, r.stderr) == (0, b""), r.stderr


PROG_CP_SYNC = r"""
const cp = require("child_process");
const out = (...a) => console.log(...a);
out("execSync", JSON.stringify(cp.execSync("echo hello; echo err >&2", { encoding: "utf8" })));
out("execSync buf", Buffer.isBuffer(cp.execSync("printf abc")), cp.execSync("printf abc").toString());
out("execSync input", cp.execSync("tr a-z A-Z", { input: "shout" }).toString(), cp.execSync("cat", { input: Buffer.from([0x68, 0x69]) }).toString("hex"));
out("execSync cwd", cp.execSync("cat f.txt", { cwd: "sub", encoding: "utf8" }));
try { cp.execSync("echo partial; echo bad >&2; exit 3"); } catch (e) { out("execSync fail", e.message, e.status, JSON.stringify(e.stderr.toString()), e.stdout); }
out("execFileSync", JSON.stringify(cp.execFileSync("echo", ["a", "b c", "$HOME"], { encoding: "utf8" })), cp.execFileSync("cat", { input: "no args" }).toString());
try { cp.execFileSync("sh", ["-c", "echo so; echo se >&2; exit 4"]); } catch (e) { out("execFileSync fail", e.message, e.status, e.stdout.toString().trim(), e.stderr.toString().trim()); }
const r = cp.spawnSync("sh", ["-c", "echo out; echo err >&2; exit 2"], { encoding: "utf8" });
out("spawnSync", r.status, r.signal, JSON.stringify(r.stdout), JSON.stringify(r.stderr), JSON.stringify(r.output), r.pid);
const r2 = cp.spawnSync("cat", { input: "piped in" });
out("spawnSync input", r2.status, Buffer.isBuffer(r2.stdout), r2.stdout.toString(), JSON.stringify(r2.output.map((x) => x && x.length)));
const r3 = cp.spawnSync("echo $((2+3)) $FOO_UNSET.", { shell: true, encoding: "utf8" });
out("spawnSync shell", JSON.stringify(r3.stdout));
const r4 = cp.spawnSync("echo", ["x"], { shell: "/bin/sh", encoding: "latin1" });
out("spawnSync shell path", JSON.stringify(r4.stdout));
const r5 = cp.spawnSync("sh", ["-c", "exit 0"], { encoding: "buffer" });
out("spawnSync buffer enc", Buffer.isBuffer(r5.stdout), r5.stdout.length);
for (const f of [() => cp.spawnSync("definitely-not-a-command-xyz"), () => cp.execFileSync("definitely-not-a-command-xyz"), () => cp.execSync("definitely-not-a-command-xyz 2>/dev/null")]) {
  try { const v = f(); out("missing ok", JSON.stringify(v)); } catch (e) { out("missing", e.name, e.status, e.message); }
}
out("exports", Object.keys(cp).sort().join(","));
"""


def test_child_process_sync(run, workdir):
    """CATCHES: execSync/execFileSync/spawnSync differences: captured (not inherited) stderr, input
    piping, cwd, encodings, shell option handling, the thrown error's message/status/stdout/stderr on
    non-zero exit, the spawnSync result shape (pid 0, output array) and errors for missing programs."""
    write_files(workdir, {"sub/f.txt": "in sub"})
    r = run(["-e", PROG_CP_SYNC], env_overrides={"PATH": "/usr/bin:/bin"})  # fixed PATH: missing-command errors must be ENOENT
    _ok(r)
    assert r.stdout == golden(__file__, "cp_sync")


PROG_CP_ASYNC = r"""
const cp = require("child_process");
const out = (...a) => console.log(...a);
// Collect a spawned child's output by waiting for both stdio 'end' events and 'exit'.
const collect = (c) => new Promise((res) => {
  let so = "", se = "", code, signal, pending = 1 + (c.stdout ? 1 : 0) + (c.stderr ? 1 : 0);
  const done = () => { if (--pending === 0) res({ so, se, code, signal }); };
  if (c.stdout) { c.stdout.on("data", (d) => (so += d)); c.stdout.on("end", done); }
  if (c.stderr) { c.stderr.on("data", (d) => (se += d)); c.stderr.on("end", done); }
  c.on("exit", (cd, sg) => { code = cd; signal = sg; done(); });
});
(async () => {
  const c1 = cp.spawn("sh", ["-c", "read x; echo got:$x; read y; echo second:$y; echo E >&2; exit 5"]);
  let spawned = false; c1.on("spawn", () => (spawned = true));
  c1.stdin.write("line1\n");
  c1.stdin.end("line2\n");
  const r1 = await collect(c1);
  out("spawn", JSON.stringify(r1), spawned, c1.exitCode, typeof c1.pid, c1.killed, c1.stdio.length, c1.stdio[1] === c1.stdout, c1 instanceof require("events"));
  const r2 = await collect(cp.spawn("echo", ["$HOME", "*", "a b"], { env: { PATH: process.env.PATH } }));
  out("spawn noshell", JSON.stringify(r2.so));
  const r3 = await collect(cp.spawn("sh", ["-c", "echo $ZZ-$PATH_SET"], { env: { ZZ: "custom env", PATH_SET: "p" } }));
  out("spawn env", JSON.stringify(r3.so));
  const r4 = await collect(cp.spawn("echo $((6*7)) | tr 4 X", { shell: true }));
  out("spawn shell", JSON.stringify(r4.so));
  const r5 = await collect(cp.spawn("cat", ["f.txt"], { cwd: "sub" }));
  out("spawn cwd", JSON.stringify(r5.so));
  const r6 = await collect(cp.spawn("sh", ["-c", "i=0; while [ $i -lt 400 ]; do printf 0123456789; i=$((i+1)); done"]));
  out("spawn big", r6.so.length, r6.so.slice(0, 12), r6.code);
  const c7 = cp.spawn("sh", ["-c", "echo visible; echo hidden >&2"], { stdio: ["ignore", "pipe", "ignore"] });
  out("stdio array", c7.stdin, c7.stderr);
  out("stdio array out", JSON.stringify((await collect(c7)).so));
  const c8 = cp.spawn("sleep", ["5"]);
  setTimeout(() => out("kill ret", c8.kill()), 30);
  const r8 = await collect(c8);
  out("killed", r8.code, r8.signal, c8.killed);
  const c9 = cp.spawn("true", [], { stdio: "ignore" });
  out("ignore", c9.stdout, c9.stderr, c9.stdin);
  out("ignore exit", (await collect(c9)).code);
  try { cp.spawn("no-such-binary-zzz"); } catch (e) { out("spawn missing", e.name, e.code, e.message); }
  const r10 = await new Promise((res) => cp.exec("exit 0", (err, so, se) => res([err, so, se])));
  out("exec ok", r10[0], JSON.stringify(r10[1]), JSON.stringify(r10[2]));
  const r11 = await new Promise((res) => cp.exec("exit 7", (err) => res(err)));
  out("exec fail", r11.message, r11.code);
  const r12 = await new Promise((res) => cp.execFile("sh", ["-c", "exit 3"], (err) => res(err)));
  out("execFile fail", r12.message, r12.code);
  const viaExec = cp.exec("echo returned child");
  out("exec returns", viaExec instanceof cp.ChildProcess, JSON.stringify((await collect(viaExec)).so));
  const viaFile = cp.execFile("printf", ["%s|", "a", "b"]);
  out("execFile returns", JSON.stringify((await collect(viaFile)).so));
})().catch((e) => out("outer", e.message));
"""


def test_child_process_async(run, workdir):
    """CATCHES: async spawn/exec/execFile bugs: stdin writes reaching the child, stdout/stderr
    streaming, env replacement, shell option, cwd, stdio 'ignore'/array handling, kill() (reference
    reports exit code null and signal null), missing-binary errors thrown synchronously, exec errors."""
    write_files(workdir, {"sub/f.txt": "in sub"})
    r = run(["-e", PROG_CP_ASYNC], env_overrides={"PATH": "/usr/bin:/bin"})  # fixed PATH: missing-command errors must be ENOENT
    _ok(r)
    assert r.stdout == golden(__file__, "cp_async")


FORK_CHILD = r"""
console.log("ordinary child output");
process.on("message", message => process.send({ value: message.value + 1 }));
"""

FORK_PARENT = r"""
const { fork } = require("node:child_process");
const child = fork(process.argv[2], [], { silent: true });
let stdout = "";
child.stdout.on("data", chunk => { stdout += chunk; });
child.on("spawn", () => child.send({ value: 41 }));
child.on("message", message => {
  console.log("message", message.value);
  child.disconnect();
});
child.on("close", code => console.log("close", code, stdout.trim()));
"""


def test_fork_exchanges_messages(run, workdir):
    """CATCHES: child_process.fork that cannot re-exec the runtime with an IPC channel: the child must
    receive the parent's message, reply via process.send, keep ordinary stdout separate from IPC frames,
    and exit 0 once the parent disconnects."""
    write_files(workdir, {"child.js": FORK_CHILD, "parent.js": FORK_PARENT})
    r = run(["parent.js", "child.js"], timeout=60)
    _ok(r)
    assert r.stdout == b"message 42\nclose 0 ordinary child output\n"


FORK_CHILD2 = r"""
console.log("child argv", JSON.stringify(process.argv.slice(2)), typeof process.send, process.connected);
process.on("message", (m) => {
  if (m.cmd === "echo") process.send({ echo: m.payload, type: typeof m.payload });
  else if (m.cmd === "many") { for (let i = 0; i < 3; i++) process.send({ i }); }
  else if (m.cmd === "exit") { process.send("bye", () => process.exit(m.code)); }
});
"""

FORK_PARENT2 = r"""
const { fork } = require("child_process");
const child = fork("./child2.js", ["a", "b c"], { silent: true });
let stdout = "";
const got = [];
let sendCb = "pending";
child.stdout.on("data", (c) => (stdout += c));
child.on("spawn", () => {
  got.push("connected " + child.connected);
  child.send({ cmd: "echo", payload: { nested: [1, "two", null, true], s: "é\n\"q\"" } });
  child.send({ cmd: "echo", payload: 42 });
  child.send({ cmd: "many" });
  child.send({ cmd: "exit", code: 3 }, (err) => (sendCb = "send cb " + err));
});
child.on("message", (m, handle) => got.push(JSON.stringify(m) + " " + handle));
let pending = 2, exitInfo;
const finish = () => {
  if (--pending > 0) return;
  console.log(got.join("\n"));
  console.log(exitInfo);
  console.log(sendCb);
  console.log("stdout:", JSON.stringify(stdout));
  console.log("parent side", typeof process.send, process.connected);
  try { child.send({ x: 1 }, {}); } catch (e) { console.log("handle", e.message); }
};
child.on("exit", (code, sig) => { exitInfo = `exit ${code} ${sig}`; finish(); });
child.stdout.on("end", finish);
"""


def test_fork_ipc_round_trips(run, workdir):
    """CATCHES: fork IPC that mangles JSON payloads (unicode, quotes, newlines, nested arrays), drops
    or reorders bursts of messages, ignores the child's argv, does not call send callbacks, does not
    propagate the child's exit code, or allows handle transfer."""
    write_files(workdir, {"child2.js": FORK_CHILD2, "parent2.js": FORK_PARENT2})
    r = run(["parent2.js"], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "fork_ipc")


CLUSTER_PROG = r"""
const cluster = require("node:cluster");
if (cluster.isPrimary) {
  cluster.setupPrimary({ exec: __filename, args: [], silent: true });
  const worker = cluster.fork({ TEST_VALUE: "41" });
  let stdout = "";
  worker.process.stdout.on("data", chunk => { stdout += chunk; });
  worker.on("online", () => worker.send({ value: Number(process.env.START || 1) }));
  worker.on("message", message => {
    console.log("message", worker.id, message.value, !!cluster.workers[worker.id]);
    worker.disconnect();
  });
  worker.on("exit", code => console.log("exit", code, stdout.trim()));
} else {
  console.log("worker", cluster.worker.id, cluster.isWorker, process.env.TEST_VALUE);
  cluster.worker.on("message", message => cluster.worker.send({ value: message.value + 41 }));
}
"""


def test_cluster_fork_runs_real_worker_process(run, workdir):
    """CATCHES: node:cluster without real worker processes: the worker must see isWorker, its id and
    the env passed to fork(), and messages must round-trip primary -> worker -> primary before exit 0."""
    write_files(workdir, {"cluster.js": CLUSTER_PROG})
    r = run(["cluster.js"], timeout=60)
    _ok(r)
    assert r.stdout == b"message 1 42 true\nexit 0 worker 1 true 41\n"


CLUSTER_PROG2 = r"""
const cluster = require("cluster");
if (cluster.isPrimary) {
  const log = [];
  cluster.on("setup", (s) => log.push("setup " + JSON.stringify(s.args) + " " + s.silent + " " + require("path").basename(s.exec)));
  cluster.setupPrimary({ exec: __filename, args: ["x"], silent: true });
  cluster.on("fork", (w) => log.push("fork " + w.id));
  cluster.on("online", (w) => log.push("online " + w.id));
  cluster.on("message", (w, m) => log.push(`cluster message ${w.id} ${JSON.stringify(m)}`));
  cluster.on("exit", (w, code) => {
    log.push(`cluster exit ${w.id} ${code} ${w.exitedAfterDisconnect} ${w.isDead()}`);
    if (Object.keys(cluster.workers).length === 0) {
      console.log(log.sort().join("\n"));
      console.log("primary", cluster.isPrimary, cluster.isMaster, cluster.isWorker, cluster.worker, cluster.schedulingPolicy === cluster.SCHED_RR, typeof cluster.Worker, cluster.setupMaster === cluster.setupPrimary);
      cluster.disconnect(() => console.log("disconnect callback with no workers"));
    }
  });
  for (const n of [1, 2]) {
    const w = cluster.fork({ WORKER_N: String(n) });
    w.on("message", (m) => { if (m.ready) w.send({ n: m.n * 10 }); else w.disconnect(); });
  }
} else {
  const w = cluster.worker;
  w.on("message", (m) => w.send({ result: m.n + 1, id: w.id }));
  process.send({ ready: true, n: Number(process.env.WORKER_N), args: process.argv.slice(2), isWorker: cluster.isWorker, connected: w.isConnected() });
  try { cluster.fork(); } catch (e) { console.error("unreachable stderr is silent:", e.message); }
}
"""


def test_cluster_two_workers_and_events(run, workdir):
    """CATCHES: cluster primary bookkeeping: setup/fork/online/message/exit events, sequential worker
    ids, settings.args forwarded to workers, cluster.workers cleanup, exitedAfterDisconnect, and the
    isPrimary/isMaster/isWorker/SCHED_RR surface."""
    write_files(workdir, {"cl.js": CLUSTER_PROG2})
    r = run(["cl.js"], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "cluster_two")


WT_WORKER = r"""
const { parentPort, workerData, isMainThread, threadId } = require("worker_threads");
parentPort.postMessage({ hello: workerData, isMainThread, tid: typeof threadId, argv: process.argv.slice(2), base: require("path").basename(__filename) });
parentPort.on("message", (m) => {
  if (m === "bye") { parentPort.close(); return; }
  parentPort.postMessage({ echo: m, kinds: [m.date instanceof Date, typeof m.big, m.set instanceof Set, m.re instanceof RegExp, m.u8 instanceof Uint8Array, m.map instanceof Map] });
});
"""

WT_MAIN = r"""
const { Worker, isMainThread, threadId } = require("worker_threads");
const show = (v) => JSON.stringify(v, (k, x) => typeof x === "bigint" ? x + "n" : x instanceof Map ? ["Map", ...x] : x instanceof Set ? ["Set", ...x] : x instanceof RegExp ? String(x) : x instanceof Uint8Array ? ["U8", ...x] : x);
console.log("main", isMainThread, threadId);
const w = new Worker(__dirname + "/w.js", { workerData: { n: 1, list: [1, 2], map: new Map([["k", 1]]) }, argv: ["wa", 7] });
console.log("threadId", typeof w.threadId, w.threadId > 0, w.stdout, w.stdin);
w.on("online", () => console.log("online"));
w.on("message", (m) => {
  console.log("msg", show(m));
  if (m.hello) w.postMessage({ date: new Date(0), big: 5n, set: new Set([1]), re: /x/g, u8: new Uint8Array([1, 2]), map: new Map([[1, 2]]), nested: { undef: undefined, nul: null, arr: [[1], { z: -0 }] } });
  else w.postMessage("bye");
});
w.on("error", (e) => console.log("error", e.message));
w.on("exit", (c) => console.log("exit", c));
"""


def test_worker_threads_file_worker(run, workdir):
    """CATCHES: worker_threads file workers that fail to run as their own main module, lose workerData
    or argv, mis-clone Map/Set/Date/BigInt/RegExp/typed arrays across the thread boundary, or do not
    exit 0 once parentPort is closed (online -> messages -> exit ordering)."""
    write_files(workdir, {"w.js": WT_WORKER, "main.js": WT_MAIN})
    r = run(["main.js"], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "wt_file")


WT_LIFECYCLE = r"""
const { Worker, setEnvironmentData, getEnvironmentData, receiveMessageOnPort, MessageChannel, SHARE_ENV, markAsUntransferable, isMarkedAsUntransferable } = require("worker_threads");
const out = (...a) => console.log(...a);
const run = (src, opts) => new Promise((res) => {
  const w = new Worker(src, { eval: true, ...opts });
  const log = [];
  w.on("message", (m) => log.push("message:" + JSON.stringify(m)));
  w.on("error", (e) => log.push("error:" + e.constructor.name + ":" + e.message));
  w.on("exit", (c) => { log.push("exit:" + c); res(log.join(" | ")); });
});
(async () => {
  setEnvironmentData("cfg", { mode: "test" });
  out("env data", JSON.stringify(getEnvironmentData("cfg")));
  out("A", await run(`const wt = require("worker_threads"); wt.parentPort.postMessage([wt.isMainThread, wt.workerData, wt.getEnvironmentData("cfg"), process.argv.slice(2), process.env.WK_VAR, typeof process.env.PATH]);`, { workerData: "wd", argv: ["a1", 2], env: { WK_VAR: "v" } }));
  out("B", await run(`throw new TypeError("worker threw")`));
  out("C", await run(`require("worker_threads").parentPort.postMessage("before"); process.exit(7); `));
  out("D", await run(`Promise.reject(new RangeError("rej in worker"))`));
  out("E", await run(`setTimeout(() => require("worker_threads").parentPort.postMessage("late"), 5)`));
  out("F", await run(`throw "plain string"`));
  out("G", await run(`process.exitCode = 3; require("worker_threads").parentPort.postMessage(typeof __filename)`));
  out("H", await run(`const { parentPort } = require("worker_threads"); parentPort.postMessage(1); parentPort.close(); parentPort.postMessage(2);`));
  out("I", await run(`class CustomError extends Error {}; throw new SyntaxError("named")`));
  setEnvironmentData("cfg", undefined);
  out("env cleared", getEnvironmentData("cfg"));
  const w = new Worker(`require("worker_threads").parentPort.on("message", () => {}); setInterval(() => {}, 1000);`, { eval: true });
  w.on("exit", (c) => out("terminated exit", c));
  await new Promise((r) => w.on("online", r));
  const code = await w.terminate();
  out("terminate resolved", code, await w.terminate());
  const { port1, port2 } = new MessageChannel();
  port1.postMessage({ q: 1 });
  port1.postMessage("second");
  await new Promise((r) => setTimeout(r, 5));
  out("receive", JSON.stringify(receiveMessageOnPort(port2)), JSON.stringify(receiveMessageOnPort(port2)), receiveMessageOnPort(port2));
  port1.close();
  try { receiveMessageOnPort({}); } catch (e) { out("receive bad", e.name, e.message); }
  try { new Worker("w.js"); } catch (e) { out("relative", e.name, e.message); }
  try { new Worker("x", { eval: true, env: SHARE_ENV }); } catch (e) { out("share env", e.message); }
  try { new Worker("x", { eval: true, stdout: true }); } catch (e) { out("stdout opt", e.message); }
  try { new Worker("x", { eval: true, workerData: { f() {} } }); } catch (e) { out("workerData clone", e.name); }
  out("untransferable", markAsUntransferable({}), isMarkedAsUntransferable({}));
  const w2 = new Worker(`require("worker_threads").parentPort.once("message", (m) => require("worker_threads").parentPort.postMessage(m * 2))`, { eval: true });
  try { w2.postMessage(1, [new ArrayBuffer(1)]); } catch (e) { out("transfer", e.message); }
  try { w2.postMessage(() => {}); } catch (e) { out("clone fn", e.name, e.message); }
  w2.postMessage(21);
  w2.on("message", (m) => out("w2", m));
  w2.on("exit", (c) => out("w2 exit", c));
  out("unref", w2.unref() === w2, w2.ref() === w2);
  w2.getHeapSnapshot().catch((e) => out("heap", e.message));
})();
"""


def test_worker_threads_lifecycle(run, workdir):
    """CATCHES: eval workers: workerData/argv/env/environmentData snapshots, uncaught throws and
    unhandled rejections becoming 'error' + exit 1 (with revived error classes), process.exit codes,
    terminate() promises, receiveMessageOnPort, the unsupported-option errors and DataCloneError."""
    r = run(["-e", WT_LIFECYCLE], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "wt_lifecycle")


WEB_WORKER = r"""
self.onmessage = (e) => {
  if (e.data === "throw") throw new Error("web worker boom");
  if (e.data === "close") { postMessage("closing"); close(); return; }
  postMessage({ got: e.data, type: typeof self, hasWindow: typeof window, hasRequire: typeof require, isEvent: e instanceof MessageEvent });
};
addEventListener("message", (e) => { if (e.data === "listener") postMessage("via addEventListener"); });
"""

WEB_WORKER_MJS = r"""
import { basename } from "node:path";
postMessage("module worker " + basename("/a/b.c") + " " + (typeof require));
"""

WEB_MAIN = r"""
const out = (...a) => console.log(...a);
const w = new Worker(__dirname + "/ww.js");
w.onmessage = (e) => {
  out("message", JSON.stringify(e.data), e instanceof MessageEvent, e.type);
  if (e.data && e.data.got === "hi") w.postMessage("listener");
  else if (e.data === "via addEventListener") w.postMessage("throw");
  else if (e.data === "closing") {
    const m = new Worker("file://" + __dirname + "/ww.mjs", { type: "module" });
    m.addEventListener("message", (ev) => { out("module", ev.data); m.terminate(); next(); });
  }
};
w.onerror = (e) => { out("onerror", e.message, e instanceof ErrorEvent, e.type); w.postMessage("close"); };
w.postMessage("hi");
function next() {
  const bad = new Worker(__dirname + "/missing-worker.js");
  bad.onerror = (e) => { out("load error", e.message.replace(__dirname, "<dir>")); bad.terminate(); last(); };
}
function last() {
  try { new Worker(); } catch (e) { out("noarg", e.name, e.message); }
  const w3 = new Worker(__dirname + "/ww.js");
  try { w3.postMessage(Symbol("x")); } catch (e) { out("dataclone", e.name); }
  w3.terminate();
  w3.postMessage("ignored after terminate");
  out("done", typeof Worker.prototype.onmessage, "onmessageerror" in Worker.prototype);
}
"""


def test_web_worker_global(run, workdir):
    """CATCHES: the web-style global Worker: MessageEvent delivery to onmessage and addEventListener,
    worker-side uncaught errors surfacing as ErrorEvent on onerror, close(), module workers with
    imports, load failures reported via onerror, DataCloneError and post-terminate no-ops."""
    write_files(workdir, {"ww.js": WEB_WORKER, "ww.mjs": WEB_WORKER_MJS, "wmain.js": WEB_MAIN})
    r = run(["wmain.js"], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "web_worker")


STDIN_STREAM = r"""const chunks=[]; process.stdin.on("data", c => chunks.push(c)); process.stdin.on("end", () => console.log(Buffer.concat(chunks).toString()))"""


def test_process_stdin_streams_piped_input(run):
    """CATCHES: process.stdin that does not deliver piped bytes as 'data' Buffers followed by 'end'
    (the -e program must read the whole pipe and print it)."""
    r = run(["-e", STDIN_STREAM], input=b"streamed input")
    _ok(r)
    assert r.stdout == b"streamed input\n"


STDIN_VARIANTS = r"""
const out = (...a) => console.log(...a);
const fs = require("fs");
let s = "";
const types = new Set();
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => { s += c; types.add(typeof c); });
process.stdin.on("end", () => {
  out("utf8 stdin", JSON.stringify(s), [...types].join(), process.stdin.isTTY, typeof process.stdin.on);
  out("dev stdin after end", JSON.stringify(fs.readFileSync("/dev/stdin", "utf8")));
});
"""


def test_process_stdin_encoding_and_dev_stdin(run):
    """CATCHES: process.stdin.setEncoding not producing string chunks, multi-byte UTF-8 split across
    reads, or wrong isTTY for a pipe; and reading /dev/stdin after the stream was drained."""
    r = run(["-e", STDIN_VARIANTS], input="héllo\nwörld €\n".encode())
    _ok(r)
    assert r.stdout == golden(__file__, "stdin_variants")


def test_stdin_async_iteration_and_fd0(run):
    """CATCHES: for-await iteration over process.stdin, and the reference's rejection of
    fs.readFileSync(0) (a numeric fd 0 is not a valid lumen handle; the async rejection is reported on
    stderr but the process still exits 0)."""
    r = run(["-e", '(async () => { let s = ""; for await (const c of process.stdin) s += c; console.log(JSON.stringify(s)); '
                   'require("fs").readFileSync(0, "utf8"); })()'], input=b"x\ny\n")
    assert (r.returncode, r.stdout, r.stderr) == (0, b'"x\\ny\\n"\n', b"Uncaught (in promise) TypeError: bad file descriptor 0\n")


def test_typescript_commonjs_entry_and_dependency(run, workdir):
    """CATCHES: .cts entries or required .ts dependencies that are not type-stripped and run as
    CommonJS (module.exports from value.ts must be visible to require('./value'))."""
    write_files(workdir, {"value.ts": "const value: number = 41; module.exports = value;\n",
                          "main.cts": "const value: number = require('./value'); console.log(value + 1);\n"})
    r = run(["main.cts"])
    _ok(r)
    assert r.stdout == b"42\n"


TS_FEATURES = r"""
import type { Nothing } from "./nothing";
interface Point { x: number; y?: number }
interface Ext extends Point { z: string[] }
type Pair<T> = [T, T];
type Union = "a" | "b";
type Fn = (a: number, b?: string) => void;
const p = { x: 1 } as Point;
const pair: Pair<string> = ["l", "r"];
const u: Union = "a";
const cfg = { a: 1 } satisfies Record<string, number>;
let maybe: string | undefined;
function opt(a?: number, ...rest: number[]): number { return (a ?? 0) + rest.length; }
const typed = (a: number, b: string = "d"): string => b.repeat(a);
const obj: { [k: string]: number } = { k: 2 };
const nested: Array<Map<string, Set<number>>> = [new Map([["s", new Set([1])]])];
class Box {
  value = 3;
  static count = 0;
  get doubled(): number { return this.value * 2; }
  method(x: number): Box { this.value += x; return this; }
}
console.log(JSON.stringify(p), pair.join("+"), u, JSON.stringify(cfg), maybe, opt(), opt(1, 2, 3), typed(2), typed(1, "q"), obj.k, nested[0].get("s").has(1), new Box().method(2).doubled, Box.count, typeof module, typeof require);
module.exports = { ok: true };
"""


def test_typescript_feature_stripping(run, workdir):
    """CATCHES: a TypeScript stripper that mishandles interfaces, type aliases, generics in type
    positions, `as`/`satisfies`, optional/default/rest parameters, return types, class field types or
    `import type`, or that runs a .ts entry as ESM instead of CommonJS."""
    write_files(workdir, {"feat.ts": TS_FEATURES})
    r = run(["feat.ts"])
    _ok(r)
    assert r.stdout == golden(__file__, "ts_features")


def test_typescript_unsupported_constructs(run, workdir):
    """CATCHES: rewrites that silently accept (or mis-report) TypeScript constructs the reference
    refuses: enums and namespaces need transformation, parameter properties and typed class fields are
    rejected with syntax errors."""
    write_files(workdir, {"en.ts": "enum E { A }\nconsole.log(1)\n",
                          "ns.ts": "namespace N { export const a = 1 }\n",
                          "pp.ts": "class P { constructor(private x: number) {} }\n",
                          "cf.ts": "class F { value: number = 3; }\n"})
    res = [run([f]) for f in ("en.ts", "ns.ts", "pp.ts", "cf.ts")]
    assert [(r.returncode, r.stdout, r.stderr) for r in res] == [
        (1, b"", b"Uncaught SyntaxError: TypeScript enum declarations require transformation\n"),
        (1, b"", b"Uncaught SyntaxError: TypeScript namespace declarations require transformation\n"),
        (1, b"", b"Uncaught SyntaxError: 'private' cannot be used as a binding in strict mode\n"),
        (1, b"", b"Uncaught SyntaxError: expected ';'\n"),
    ]


PROG_NET_TCP = r"""
const net = require("net");
const out = (...a) => console.log(...a);
out("isIP", net.isIP("127.0.0.1"), net.isIP("::1"), net.isIP("nope"), net.isIPv4("1.2.3.4"), net.isIPv6("1.2.3.4"), net.isIP("256.1.1.1"), net.isIPv6("::ffff:1.2.3.4"), net.isIP("1::2::3"), net.isIP("fe80::1"));
const bl = new net.BlockList();
bl.addAddress("10.0.0.1"); bl.addRange("192.168.0.10", "192.168.0.20"); bl.addSubnet("172.16.0.0", 12); bl.addAddress("::1", "ipv6");
out("blocklist", bl.check("10.0.0.1"), bl.check("10.0.0.2"), bl.check("192.168.0.15"), bl.check("192.168.0.21"), bl.check("172.31.255.255"), bl.check("172.32.0.0"), bl.check("::1", "ipv6"), bl.check("::2", "ipv6"));
const sa = new net.SocketAddress({ address: "127.0.0.1", port: 8080 });
out("socketaddress", sa.address, sa.port, sa.family, sa.flowlabel);
out("autoselect", net.getDefaultAutoSelectFamily(), typeof net.getDefaultAutoSelectFamilyAttemptTimeout());
const srvLog = [], cliLog = [];
let port;
const server = net.createServer((sock) => {
  srvLog.push(`conn ${sock.remoteAddress} ${sock.remoteFamily} ${typeof sock.remotePort} ${sock.localAddress}`);
  sock.setEncoding("utf8");
  let buf = "";
  sock.on("data", (d) => {
    buf += d;
    if (buf.endsWith("\n")) { sock.write("echo:" + buf.toUpperCase()); sock.end("[eof]"); }
  });
  sock.on("end", () => srvLog.push("server saw end"));
  sock.on("close", () => {
    srvLog.push("server sock close");
    server.getConnections((err, n) => {
      srvLog.push(`connections ${err} ${n}`);
      server.close(() => { srvLog.push("server closed " + server.listening); finish(); });
    });
  });
});
server.on("listening", () => srvLog.push("listening event"));
server.listen(0, "127.0.0.1", () => {
  const addr = server.address();
  port = addr.port;
  out("address", addr.address, addr.family, typeof addr.port, addr.port > 0, server.listening);
  const client = net.connect({ port, host: "127.0.0.1" }, () => {
    cliLog.push(`connected ${client.remoteAddress} ${client.remotePort === port} ${client.remoteFamily}`);
    const la = client.address();
    cliLog.push(`local ${la.address} ${la.family}`);
    client.setNoDelay(true);
    client.setKeepAlive(true, 1000);
    client.write("hello ");
    client.write(Buffer.from("tcp\n"));
  });
  let got = "";
  client.on("data", (d) => (got += d));
  client.on("end", () => cliLog.push("client end " + JSON.stringify(got)));
  client.on("close", (hadErr) => cliLog.push("client close " + hadErr));
});
function finish() {
  out("client log", cliLog.join(" | "));
  out("server log", srvLog.join(" | "));
}
"""


def test_net_tcp_loopback(run):
    """CATCHES: node:net loopback TCP: server listen(0) address shape, client connect callback and
    remote/local addresses, echo with end(), half-close and close ordering, getConnections, server
    close, plus isIP/BlockList/SocketAddress helpers."""
    r = run(["-e", PROG_NET_TCP])
    _ok(r)
    assert r.stdout == golden(__file__, "net_tcp")


PROG_NET_UNIX_UDP = r"""
const net = require("net");
const dgram = require("dgram");
const out = (...a) => console.log(...a);
const srvLog = [], cliLog = [];
const server = net.createServer({ allowHalfOpen: false }, (sock) => {
  srvLog.push("conn");
  sock.on("data", (d) => { srvLog.push("data:" + d); sock.end("bye"); });
  sock.on("close", () => { srvLog.push("close"); server.close(); });
});
server.listen("sock.unix", () => {
  out("unix address", JSON.stringify(server.address()));
  const c = net.createConnection("sock.unix");
  c.on("connect", () => { cliLog.push("connect"); c.write("over unix"); });
  c.on("data", (d) => cliLog.push("data:" + d));
  c.on("end", () => cliLog.push("end"));
  c.on("close", () => { cliLog.push("close"); setTimeout(() => { out("server", srvLog.join(",")); out("client", cliLog.join(",")); udp(); }, 20); });
});
function udp() {
  const a = dgram.createSocket("udp4");
  const b = dgram.createSocket({ type: "udp4" });
  const got = new Promise((res) => a.on("message", (msg, rinfo) => res(`${msg} ${rinfo.address} ${rinfo.family} ${rinfo.size} ${typeof rinfo.port}`)));
  a.on("listening", () => out("udp listening event"));
  a.bind(0, "127.0.0.1", async () => {
    const pa = a.address();
    out("udp bound", pa.address, pa.family, typeof pa.port);
    const sent = new Promise((res) => b.send("datagram!", pa.port, "127.0.0.1", (err, n) => res(`${err} ${n}`)));
    const [s, m] = await Promise.all([sent, got]);
    out("udp sent", s);
    out("udp got", m);
    const closed = [];
    a.on("close", () => closed.push("a"));
    a.close();
    b.close(() => { closed.push("b"); setTimeout(() => out("udp closed", closed.sort().join(",")), 10); });
  });
}
"""


def test_net_unix_socket_and_udp(run, workdir):
    """CATCHES: unix-domain socket servers/clients (path address, data both ways, end/close) and dgram
    UDP over loopback (bind(0) address, send callback byte count, rinfo shape, close callbacks)."""
    r = run(["-e", PROG_NET_UNIX_UDP])
    _ok(r)
    assert r.stdout == golden(__file__, "net_unix_udp")






PROG_DNS = r"""
const dns = require("dns");
const out = (...a) => console.log(...a);
const lookup = (...a) => new Promise((res) => dns.lookup(...a, (err, addr, fam) => res([err && err.code, JSON.stringify(addr), fam])));
(async () => {
  out("lookup ip", ...(await lookup("127.0.0.1")));
  out("lookup ip6 all", ...(await lookup("::1", { all: true })));
  out("lookup family num", ...(await lookup("10.1.2.3", 4)));
  out("lookup localhost v4", ...(await lookup("localhost", { family: 4 })));
  out("promises", JSON.stringify(await dns.promises.lookup("127.0.0.2")), JSON.stringify(await require("dns/promises").lookup("::2", { all: true })));
  out("consts", dns.NOTFOUND, dns.ADDRCONFIG, dns.V4MAPPED, dns.ALL, typeof dns.Resolver, Array.isArray(dns.getServers()), typeof dns.setServers);
  out("order", typeof dns.getDefaultResultOrder(), typeof dns.setDefaultResultOrder);
})();
"""


def test_dns_lookup_literals(run):
    """CATCHES: dns.lookup/dns.promises.lookup that do not short-circuit IP literals (address/family,
    all:true arrays, numeric family argument), fail to resolve localhost to 127.0.0.1 for family 4,
    or lack the exported constants/Resolver surface."""
    r = run(["-e", PROG_DNS])
    _ok(r)
    assert r.stdout == golden(__file__, "dns")


PROG_DGRAM_OPTIONS = r"""
const dgram = require("dgram");
const out = (...a) => console.log(...a);
const a = dgram.createSocket("udp4"), b = dgram.createSocket({ type: "udp4", reuseAddr: true });
const tryit = (label, f) => { try { const v = f(); out(label, "ok", v === b ? "this" : JSON.stringify(v)); } catch (e) { out(label, e.name, e.code, e.message); } };
tryit("remoteAddress unbound", () => b.remoteAddress());
a.bind(0, "127.0.0.1", () => {
  b.bind(0, "127.0.0.1", () => {
    tryit("setBroadcast", () => b.setBroadcast(true));
    tryit("setTTL", () => b.setTTL(64));
    tryit("setTTL bad", () => b.setTTL(0));
    tryit("setMulticastTTL", () => b.setMulticastTTL(2));
    tryit("setMulticastLoopback", () => b.setMulticastLoopback(true));
    tryit("recvBuf", () => typeof b.getRecvBufferSize());
    tryit("sendBuf", () => typeof b.getSendBufferSize());
    tryit("setRecvBuf", () => b.setRecvBufferSize(65536));
    tryit("setSendBuf", () => b.setSendBufferSize(65536));
    tryit("ref", () => b.ref());
    tryit("unref", () => b.unref());
    tryit("ref again", () => b.ref());
    b.connect(a.address().port, "127.0.0.1", () => {
      out("connected", b.remoteAddress().address, b.remoteAddress().family, b.remoteAddress().port === a.address().port);
      a.on("message", (m, r) => {
        out("got", String(m), r.port === b.address().port, r.size);
        b.disconnect();
        tryit("after disconnect", () => b.remoteAddress());
        a.close(); b.close(() => out("closed"));
      });
      b.send(Buffer.from("conn-send"));
    });
  });
});
"""


def test_dgram_options_and_connect(run):
    """CATCHES: dgram socket option setters/getters (broadcast, TTL validation, multicast TTL/loopback,
    buffer sizes, ref/unref chaining), connected UDP sockets (remoteAddress, send without address,
    disconnect) and ERR_SOCKET_DGRAM_NOT_CONNECTED errors."""
    r = run(["-e", PROG_DGRAM_OPTIONS])
    _ok(r)
    assert r.stdout == golden(__file__, "dgram_options")


def test_child_unref_lets_process_exit(run):
    """CATCHES: ChildProcess.unref()/ref() that do not toggle the event loop's keep-alive: after the
    final unref() the parent must exit immediately (well before the 3 s child finishes) with exit 0."""
    r = run(["-e", 'const c = require("child_process").spawn("sleep", ["3"]); c.unref(); c.ref(); c.unref();'
                   ' console.log("unrefd", typeof c.pid, c.exitCode);'], timeout=60)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"unrefd number null\n", b"")


PROG_CHILD_EPIPE = r"""
const cp = require("child_process");
const c = cp.spawn("true");
c.on("exit", (code) => {
  console.log("exited", code);
  setTimeout(() => {
    c.stdin.on("error", (e) => console.log("stdin error", e.code, e.message));
    c.stdin.write("data after exit\n", (err) => console.log("write cb", err && err.code));
  }, 50);
});
"""


def test_child_stdin_write_after_exit(run):
    """CATCHES: writes to an exited child's stdin pipe that are silently dropped or crash the parent
    instead of surfacing the EPIPE ('write: Broken pipe (os error 32)') as a stdin 'error' event."""
    r = run(["-e", PROG_CHILD_EPIPE], timeout=60)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == b"exited 0\nstdin error undefined write: Broken pipe (os error 32)\nwrite cb undefined\n"


PROG_NET_EDGES = r"""const net = require("net");
const dgram = require("dgram");
const out = (...a) => console.log(...a);
const steps = [];
const next = () => { const f = steps.shift(); if (f) f(); };
steps.push(() => {
  const s1 = net.createServer();
  s1.listen(0, "127.0.0.1", () => {
    const port = s1.address().port;
    const s2 = net.createServer();
    s2.on("error", (e) => { out("addrinuse", e.code, e.syscall, e.address, e.port === port, e.message.replace(String(port), "PORT")); s1.close(next); });
    s2.listen(port, "127.0.0.1", () => out("unexpected listen"));
  });
});
steps.push(() => {
  const c = net.connect("missing.sock");
  c.on("error", (e) => { out("unix connect missing", e.code, e.syscall, e.address, e.message); });
  c.on("close", (h) => { out("unix connect close", h); next(); });
});
steps.push(() => {
  const s = net.createServer();
  s.on("error", (e) => { out("unix listen bad dir", e.code, e.syscall, e.message); next(); });
  s.listen("no/such/dir/x.sock", () => out("unexpected"));
});
steps.push(() => {
  const server = net.createServer((sock) => { sock.end("bye"); });
  server.listen("u.sock", () => {
    const c = net.connect("u.sock", () => {
      out("unix nodelay", c.setNoDelay(true) === c, c.setKeepAlive(true, 10) === c, JSON.stringify(c.address()), c.remoteAddress, c.remotePort);
      c.unref(); c.ref();
    });
    c.on("data", (d) => out("unix data", String(d)));
    c.on("close", () => server.close(() => { out("unix server closed", require("fs").existsSync("u.sock")); next(); }));
  });
});
steps.push(() => {
  const u = dgram.createSocket("udp4");
  u.bind(0, "127.0.0.1", () => {
    for (const [l, f] of [["iface ok", () => u.setMulticastInterface("127.0.0.1")], ["iface bad", () => u.setMulticastInterface("not-an-ip")], ["add bad", () => u.addMembership("not-mcast")], ["drop bad", () => u.dropMembership("1.2.3")], ["ssm bad", () => u.addSourceSpecificMembership("x", "y")], ["ssm bad group", () => u.addSourceSpecificMembership("127.0.0.1", "nope")]]) {
      try { const v = f(); out(l, "ok", v === u ? "this" : v); } catch (e) { out(l, e.name, e.code, e.message); }
    }
    u.close(() => {
      try { u.send("x", 1, "127.0.0.1"); } catch (e) { out("send after close", e.name, e.code, e.message); }
      try { u.address(); } catch (e) { out("address after close", e.name, e.code, e.message); }
      next();
    });
  });
});
steps.push(() => {
  const s = net.createServer(); s.listen(0, "127.0.0.1", () => { s.unref(); out("server unref'd; loop may exit"); });
  const u = dgram.createSocket("udp4"); u.bind(0, "127.0.0.1", () => { u.unref(); out("udp unref'd"); });
});
next();
"""


def test_net_errors_multicast_and_unref(run, workdir):
    """CATCHES: net error shapes (EADDRINUSE on a held port, ENOENT for unix connect/listen paths),
    unix-socket setNoDelay/setKeepAlive/address on a path socket and socket-file cleanup on close,
    dgram multicast interface selection and membership argument errors, use-after-close
    errors, and server/socket unref() letting the process exit while still listening."""
    r = run(["-e", PROG_NET_EDGES])
    _ok(r)
    assert r.stdout == golden(__file__, "net_edges")




WEB_HARVEST_FILES = {
    "echo.mjs": r"""onmessage = (e) => {
  const d = e.data;
  postMessage({ sum: d.nums.reduce((a, b) => a + b, 0), ts: d.when.getTime(), tag: d.meta.get("tag"), set: [...d.set], typed: Array.from(d.typed), nested: d.deep.a.b.c });
  close();
};
""",
    "counter.mjs": r"""let total = 0;
onmessage = (e) => { total += e.data; postMessage(total); if (total >= 6) close(); };
""",
    "boom.mjs": r"""onmessage = (e) => { throw new RangeError("bad: " + e.data); };
""",
    "ticker.mjs": r"""let n = 0;
setInterval(() => { n++; postMessage(n); }, 3);
""",
    "main.js": r"""const out = (...a) => console.log(...a);
const steps = [];
const next = () => { const f = steps.shift(); if (f) f(); };
steps.push(() => {
  const w = new Worker(__dirname + "/echo.mjs", { type: "module" });
  w.onmessage = (e) => { out("reply", JSON.stringify(e.data)); next(); };
  w.postMessage({ nums: [1, 2, 3, 4], when: new Date(1000), meta: new Map([["tag", "hi"]]), set: new Set(["s"]), typed: new Int16Array([-1, 2]), deep: { a: { b: { c: [null, true] } } } });
});
steps.push(() => {
  const w = new Worker(__dirname + "/counter.mjs", { type: "module" });
  const send = [1, 2, 3];
  let i = 0;
  w.onmessage = (e) => { out("running total", e.data); if (i < send.length) w.postMessage(send[i++]); else next(); };
  w.postMessage(send[i++]);
});
steps.push(() => {
  const w = new Worker(__dirname + "/boom.mjs", { type: "module" });
  w.onerror = (e) => { out("onerror", e.message, e instanceof ErrorEvent); w.terminate(); next(); };
  w.postMessage(42);
});
steps.push(() => {
  const w = new Worker(__dirname + "/ticker.mjs", { type: "module" });
  let count = 0;
  w.onmessage = (e) => {
    count++;
    if (count === 3) { w.terminate(); out("terminated at", e.data); }
  };
});
next();
""",
}


def test_web_worker_module_scenarios(run, workdir):
    """CATCHES: module web workers that lose structured-clone fidelity (Date/Map/Set/typed arrays/
    nested data), reorder a multi-message conversation, fail to surface worker exceptions as
    ErrorEvents on onerror, or cannot be terminated while posting on an interval."""
    write_files(workdir, WEB_HARVEST_FILES)
    r = run(["main.js"], timeout=60)
    _ok(r)
    assert r.stdout == golden(__file__, "web_worker_modules")
