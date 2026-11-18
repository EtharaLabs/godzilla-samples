"""`--watch -o FILE`: recompile on every change to the input, report each turn
on stderr, keep the last good output on an error, and honour --check/--json."""

import os
import re
import time

from conftest import wait_for

ONE = '|box| "one"\n'
TWO = '|box| "two, a longer label"\n'
BAD = '|box#a| { colr: red; }\n'


class Watch:
    """A running `lini --watch` whose stdout/stderr are logged to files outside workdir."""

    def __init__(self, spawn, tmp_path, args):
        self.out_log, self.err_log = tmp_path / "watch.out", tmp_path / "watch.err"
        self.proc = spawn(args, stdout=self.out_log, stderr=self.err_log)

    def stderr(self):
        return re.sub(r"ok \(\d+ ms\)", "ok (N ms)", self.err_log.read_text())

    def stdout(self):
        return self.out_log.read_text()

    def wait_lines(self, n):
        """Block until stderr holds at least n lines; returns the normalised text."""
        assert wait_for(lambda: self.stderr().count("\n") >= n), self.stderr()
        return self.stderr()

    def stop(self):
        self.proc.kill()
        self.proc.wait(timeout=10)


def edit(path, text):
    """Replace the file atomically, so the watcher never sees a half-written save."""
    time.sleep(0.25)  # step past the watcher's 200 ms poll and the mtime tick
    tmp = path.parent.parent / (path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def test_watch_recompiles_on_change(spawn, run, workdir, tmp_path):
    """CATCHES: --watch compiling only once, not rewriting -o after an edit, or
    writing something other than what a one-shot compile of the new source
    writes."""
    src, out = workdir / "a.lini", workdir / "out.svg"
    src.write_text(ONE)
    w = Watch(spawn, tmp_path, ["--watch", "-o", "out.svg", "a.lini"])
    assert w.wait_lines(2) == "watching a.lini → out.svg\nok (N ms) → out.svg\n"
    assert out.read_bytes() == run(["a.lini"]).stdout
    edit(src, TWO)
    assert w.wait_lines(3) == "watching a.lini → out.svg\nok (N ms) → out.svg\nok (N ms) → out.svg\n"
    assert out.read_bytes() == run(["a.lini"]).stdout
    assert b"two, a longer label" in out.read_bytes()
    w.stop()
    assert w.stdout() == ""


def test_watch_keeps_last_good_output_on_error(spawn, workdir, tmp_path):
    """CATCHES: a watcher that exits on a compile error, truncates/overwrites the
    last good output, or does not report the error in `file:line:col` form and
    then recover on the next good save."""
    src, out = workdir / "a.lini", workdir / "out.svg"
    src.write_text(ONE)
    w = Watch(spawn, tmp_path, ["--watch", "-o", "out.svg", "a.lini"])
    w.wait_lines(2)
    good = out.read_bytes()
    edit(src, BAD)
    assert w.wait_lines(3) == (
        "watching a.lini → out.svg\nok (N ms) → out.svg\n"
        "a.lini:1:11: error: unknown property 'colr'; did you mean 'color'?\n"
    )
    assert w.proc.poll() is None
    assert out.read_bytes() == good
    edit(src, TWO)
    assert w.wait_lines(4).endswith("did you mean 'color'?\nok (N ms) → out.svg\n")
    assert b"two, a longer label" in out.read_bytes()
    w.stop()


def test_watch_waits_for_missing_input_and_reports_deletion(spawn, run, workdir, tmp_path):
    """CATCHES: a watcher that crashes or reports an error while the watched file
    does not exist yet, that never compiles it once it appears, or that does not
    report the read error (and keep running) when the file is deleted."""
    src, out = workdir / "late.lini", workdir / "out.svg"
    w = Watch(spawn, tmp_path, ["--watch", "-o", "out.svg", "late.lini"])
    assert w.wait_lines(1) == "watching late.lini → out.svg\n"
    time.sleep(0.5)
    assert w.proc.poll() is None
    assert not out.exists()
    edit(src, ONE)
    w.wait_lines(2)
    assert out.read_bytes() == run(["late.lini"]).stdout
    time.sleep(0.25)
    src.unlink()
    assert w.wait_lines(3) == ("watching late.lini → out.svg\nok (N ms) → out.svg\n"
                               "error: read late.lini: No such file or directory (os error 2)\n")
    assert w.proc.poll() is None
    w.stop()


def test_watch_with_check_writes_nothing(spawn, workdir, tmp_path):
    """CATCHES: --watch --check writing the -o file, or not reporting each turn
    as `ok (N ms) — check passed`."""
    src = workdir / "a.lini"
    src.write_text(ONE)
    w = Watch(spawn, tmp_path, ["--watch", "--check", "-o", "out.svg", "a.lini"])
    w.wait_lines(2)
    edit(src, TWO)
    assert w.wait_lines(3) == "watching a.lini → out.svg\nok (N ms) — check passed\nok (N ms) — check passed\n"
    w.stop()
    assert not (workdir / "out.svg").exists()


def test_watch_with_warnings_and_strict(spawn, run, workdir, tmp_path):
    """CATCHES: a watch turn under --strict that prints `ok` despite warnings, or
    warnings not printed on each turn (the SVG is still written)."""
    src = workdir / "w.lini"
    src.write_text('{ .hot { fill: red; } }\n|box#a| "A"\n')
    w = Watch(spawn, tmp_path, ["--watch", "--strict", "-o", "out.svg", "w.lini"])
    w.wait_lines(2)
    edit(src, '{ .hot { fill: red; } }\n|box#a| "AB"\n')
    assert w.wait_lines(3) == ("watching w.lini → out.svg\nw.lini:1:3: warning: class '.hot' is never worn\n"
                               "w.lini:1:3: warning: class '.hot' is never worn\n")
    time.sleep(0.3)
    assert w.stderr().count("\n") == 3
    assert (workdir / "out.svg").read_bytes() == run(["--no-warn", "w.lini"]).stdout
    w.stop()


def test_watch_with_json_prints_each_turn(spawn, workdir, tmp_path):
    """CATCHES: --watch --json not printing the diagnostics document on stdout for
    each compile, or writing the SVG file in JSON mode."""
    src = workdir / "a.lini"
    src.write_text(BAD)
    w = Watch(spawn, tmp_path, ["--watch", "--json", "-o", "out.svg", "a.lini"])
    assert wait_for(lambda: w.stdout().endswith("]\n}\n"))
    edit(src, ONE)
    assert w.wait_lines(2) == "watching a.lini → out.svg\nok (N ms) → out.svg\n"
    w.stop()
    assert w.stdout() == (
        '{\n  "file": "a.lini",\n  "diagnostics": [\n    {\n      "code": "V001",\n'
        '      "family": "unknown-property",\n      "severity": "error",\n'
        '      "message": "unknown property \'colr\'; did you mean \'color\'?",\n'
        '      "span": {\n        "start": 10,\n        "end": 19,\n        "line": 1,\n'
        '        "col": 11,\n        "endLine": 1,\n        "endCol": 20\n      },\n'
        '      "suggestion": {\n        "span": {\n          "start": 10,\n          "end": 14,\n'
        '          "line": 1,\n          "col": 11,\n          "endLine": 1,\n          "endCol": 15\n'
        '        },\n        "replacement": "color",\n        "applicability": "machine-applicable"\n'
        '      }\n    }\n  ]\n}\n'
        '{\n  "file": "a.lini",\n  "diagnostics": []\n}\n'
    )
    assert not (workdir / "out.svg").exists()
