"""Web Worker / worker_threads entry evaluation: how worker entry errors are reported and how a worker's event loop runs."""

import pytest

from conftest import write_files

MODULE_HOST = ("const w = new Worker(new URL('./wk.mjs', import.meta.url), { type: 'module' });\n"
               "w.onerror = (e) => { console.log('worker error:', e.message); w.terminate(); };\n")
CLASSIC_HOST = ("const w = new Worker(new URL('./wk.js', import.meta.url));\n"
                "w.onerror = (e) => { console.log('worker error:', e.message); w.terminate(); };\n")


def _res(r):
    return r.returncode, r.stdout, r.stderr


@pytest.mark.parametrize("body, out, err", [
    ("throw null\n", b"worker error: null\n", b"Uncaught (in promise) null\n"),
    ("let x = ;\n", b'worker error: SyntaxError: unexpected token Punct(";")\n', b""),
    ("throw new RangeError('in worker')\n", b"worker error: RangeError: in worker\n", b"Uncaught (in promise) RangeError: in worker\n"),
], ids=["throw-null", "syntax-error", "range-error"])
def test_module_worker_entry_errors(run, workdir, body, out, err):
    """CATCHES: module-worker entry failures not surfaced to the parent's onerror with the same rendering as ES module entries."""
    write_files(workdir, {"host.mjs": MODULE_HOST, "wk.mjs": body})
    r = run(["host.mjs"], timeout=15)
    assert (r.returncode, r.stdout) == (0, out)
    # The worker's own "(in promise)" report races with the parent's terminate(): it may or may not be printed,
    # but nothing else may appear on stderr.
    assert r.stderr.replace(err, b"") == b""


@pytest.mark.parametrize("body, out", [
    ("let y = ;\n", b'worker error: SyntaxError: unexpected token Punct(";") (line 1)\n'),
    ("throw undefined\n", b"worker error: undefined\n"),
    ("throw new TypeError('classic')\n", b"worker error: TypeError: classic\n"),
], ids=["syntax-error", "throw-undefined", "type-error"])
def test_classic_worker_entry_errors(run, workdir, body, out):
    """CATCHES: classic-script worker failures rendered like module ones (classic syntax errors carry a '(line N)' suffix)."""
    write_files(workdir, {"host.mjs": CLASSIC_HOST, "wk.js": body})
    assert _res(run(["host.mjs"], timeout=15)) == (0, out, b"")


def test_module_worker_event_loop(run, workdir):
    """CATCHES: worker event loops that never run setImmediate callbacks, timers, or thread-pool completions (fs.promises)."""
    write_files(workdir, {
        "host.mjs": "const w = new Worker(new URL('./wk.mjs', import.meta.url), { type: 'module' });\nconst got = [];\n"
                    "w.onmessage = (e) => { got.push(e.data); if (e.data === 'done') { console.log(got.sort().join(' | ')); w.terminate(); } };\n",
        "wk.mjs": "import { promises as fsp } from 'node:fs';\nsetImmediate(() => postMessage('immediate'));\n"
                  "setTimeout(() => postMessage('timeout'), 5);\nconst t = await fsp.readFile(new URL('./wk.mjs', import.meta.url), 'utf8');\n"
                  "postMessage('read ' + t.split('\\n').length);\nsetTimeout(() => postMessage('done'), 30);\n"})
    assert _res(run(["host.mjs"], timeout=15)) == (0, b"done | immediate | read 7 | timeout\n", b"")


def test_worker_threads_eval_worker_loop(run, workdir):
    """CATCHES: worker_threads eval workers without workerData, setImmediate or async fs inside the worker, or that do not exit (code 0) once idle."""
    write_files(workdir, {"data.txt": "twelve bytes", "main.js": (
        "const { Worker } = require('node:worker_threads');\n"
        "const w = new Worker(`\n"
        "  const { parentPort, workerData } = require('node:worker_threads');\n"
        "  setImmediate(() => parentPort.postMessage('imm ' + workerData.n));\n"
        "  require('fs').promises.readFile('data.txt', 'utf8').then(t => parentPort.postMessage('len ' + t.length));\n"
        "`, { eval: true, workerData: { n: 7 } });\n"
        "const got = [];\n"
        "w.on('message', m => { got.push(m); if (got.length === 2) console.log(got.sort().join(' | ')); });\n"
        "w.on('exit', c => console.log('exit', c));\n")})
    assert _res(run(["main.js"], timeout=15)) == (0, b"imm 7 | len 12\nexit 0\n", b"")
