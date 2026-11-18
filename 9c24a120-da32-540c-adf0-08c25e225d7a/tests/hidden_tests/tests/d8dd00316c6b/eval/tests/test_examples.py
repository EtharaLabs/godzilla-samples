"""The repository's documented example programs (examples/hello.pyfun and the
examples/interop/ cookbook), compiled under every target, checked, parsed and run.

The example sources are verbatim copies kept in test_resources/test_examples/inputs/.
"""

import pytest

from conftest import golden_name, read_golden, resources_for, run_case, transcript

INPUTS = resources_for(__file__) / "inputs"


def src(name):
    return (INPUTS / name).read_text(encoding="utf-8")


def _check(run, workdir, case):
    proc, written = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
    for rel, text in written.items():
        assert text == read_golden(__file__, golden_name(case["id"], rel))


HELLO = {"hello.pyfun": src("hello.pyfun")}
# libm's cbrt is not correctly rounded and may differ in the last bit between CPU
# architectures, so the run uses the tour with its one cube root swapped for a square root
# (same unit, same printed 4.0); the compile cases keep the verbatim file.
HELLO_RUN_SRC = src("hello.pyfun").replace("let edge = cbrt 64.0<m^3>", "let edge = sqrt 16.0<m^2>")
HELLO_RUN_CASE = {"id": "hello_run", "files": {"hello.pyfun": HELLO_RUN_SRC}, "args": ["run", "hello.pyfun"]}
HELLO_COMPILE_CASE = {"id": "hello_compile", "files": HELLO, "args": ["compile", "hello.pyfun"]}
HELLO_311_CASE = {"id": "hello_compile_311", "files": HELLO, "args": ["compile", "hello.pyfun", "--target", "3.11"]}
HELLO_NATIVE_CASE = {"id": "hello_compile_native", "files": HELLO, "args": ["compile", "--native", "hello.pyfun"]}
HELLO_CHECK_CASE = {"id": "hello_check", "files": HELLO, "args": ["check", "hello.pyfun"]}
HELLO_PARSE_CASE = {"id": "hello_parse", "files": HELLO, "args": ["parse", "hello.pyfun"]}


def test_hello_tour_runs(run, workdir):
    """CATCHES: any regression across the exhaustive language tour: a wrong value or repr in
    the long stream of printed results (ADTs, records, units, CEs, collections, strings)."""
    _check(run, workdir, HELLO_RUN_CASE)


def test_hello_tour_compiles(run, workdir):
    """CATCHES: different readable Python for the language tour (helpers, classes, matches,
    closures, comprehension-free lowering of every stdlib member it uses)."""
    _check(run, workdir, HELLO_COMPILE_CASE)


def test_hello_tour_compiles_for_311(run, workdir):
    """CATCHES: a `--target 3.11` that leaves PEP 701 f-strings (nested quotes, backslashes,
    braces) in place, or rewrites code that needs no rewriting."""
    _check(run, workdir, HELLO_311_CASE)


def test_hello_tour_compiles_natively(run, workdir):
    """CATCHES: `--native` output that keeps `match` statements on user types, omits or
    misspells inferred annotations, or changes code that is not a match."""
    _check(run, workdir, HELLO_NATIVE_CASE)


def test_hello_tour_type_checks(run, workdir):
    """CATCHES: a checker that rejects (or warns about) the documented tour."""
    _check(run, workdir, HELLO_CHECK_CASE)


def test_hello_tour_parses_canonically(run, workdir):
    """CATCHES: pretty-printer differences on every construct the tour uses."""
    _check(run, workdir, HELLO_PARSE_CASE)


def _interop(name, *, run_it=True):
    files = {name: src(name)}
    stem = name.removesuffix(".pyfun")
    cases = [{"id": f"{stem}_compile", "files": files, "args": ["compile", name]},
             {"id": f"{stem}_compile_native", "files": files, "args": ["compile", name, "--native"]}]
    if run_it:
        cases.append({"id": f"{stem}_run", "files": files, "args": ["run", name]})
    return cases


JSON_DECODE_CASES = _interop("json_decode.pyfun")
JSON_TO_ADT_CASES = _interop("json_to_adt.pyfun")
READ_FILES_CASES = _interop("read_files.pyfun")
SQLITE_CASES = _interop("sqlite_query.pyfun")
CONCURRENCY_CASES = _interop("structured_concurrency.pyfun")
DATETIME_CASES = _interop("datetime.pyfun")
HTTP_CASES = _interop("http_fetch.pyfun")
WRAP_FACADE_CASES = _interop("wrap.pyfun", run_it=False)


@pytest.mark.parametrize("case", JSON_DECODE_CASES, ids=[c["id"] for c in JSON_DECODE_CASES])
def test_json_decode_example(run, workdir, case):
    """CATCHES: wrong Python for (or wrong results from) the Decode-module JSON example."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", JSON_TO_ADT_CASES, ids=[c["id"] for c in JSON_TO_ADT_CASES])
def test_json_to_adt_example(run, workdir, case):
    """CATCHES: decoding JSON into records/ADTs with different error kinds or messages."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", READ_FILES_CASES, ids=[c["id"] for c in READ_FILES_CASES])
def test_read_files_example(run, workdir, case):
    """CATCHES: pathlib externs or `try` lowering that changes the file round-trip result or
    the caught FileNotFoundError, or leaves the example's scratch file behind."""
    _check(run, workdir, case)
    assert sorted(p.name for p in workdir.iterdir()) == ["read_files.pyfun"]


@pytest.mark.parametrize("case", SQLITE_CASES, ids=[c["id"] for c in SQLITE_CASES])
def test_sqlite_query_example(run, workdir, case):
    """CATCHES: instance-method externs on an opaque sqlite3 handle lowered wrongly."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", CONCURRENCY_CASES, ids=[c["id"] for c in CONCURRENCY_CASES])
def test_structured_concurrency_example(run, workdir, case):
    """CATCHES: `Task.scope`/`Task.start`/async CE lowering that loses messages, reorders the
    agent's output or leaks a task."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", DATETIME_CASES, ids=[c["id"] for c in DATETIME_CASES])
def test_datetime_example(run, workdir, case):
    """CATCHES: class-constructor, property and method externs (`= .attr`, `= .attr()`) and
    `extern import` handled differently, changing the printed dates."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", HTTP_CASES, ids=[c["id"] for c in HTTP_CASES])
def test_http_fetch_example(run, workdir, case):
    """CATCHES: urllib externs, `try` around io, or the `->{async}` extern arrow lowered
    differently (the run only fetches a `data:` URL, so it needs no network)."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", WRAP_FACADE_CASES, ids=[c["id"] for c in WRAP_FACADE_CASES])
def test_textwrap_facade_module_compiles(run, workdir, case):
    """CATCHES: the shipped façade's `extern` + pipe-friendly wrapper lowering differently."""
    _check(run, workdir, case)


BROWSER_FILES = {"counter.pyfun": src("counter.pyfun"), "dom.pyfun": src("dom.pyfun"), "counter.html": src("counter.html")}
BROWSER_COMPILE_CASE = {"id": "browser_counter_compile", "files": BROWSER_FILES, "args": ["compile", "counter.pyfun"]}
BROWSER_BUNDLE_CASE = {
    "id": "browser_counter_bundle", "files": BROWSER_FILES,
    "args": ["bundle", "counter.pyfun", "-o", "site", "--page", "counter.html"],
    "outputs": ["site/index.html", "site/pyfun-bundle.js", "site/counter.py", "site/dom.py"],
}


def test_browser_counter_compiles(run, workdir):
    """CATCHES: the `extern import js` DOM project lowering differently."""
    _check(run, workdir, BROWSER_COMPILE_CASE)


def test_browser_counter_bundles(run, workdir):
    """CATCHES: the documented browser bundle missing the page fragment or a module."""
    _check(run, workdir, BROWSER_BUNDLE_CASE)


NR_DIR = "examples/interop/network-rail/"
NR_PURE_CASE = {
    "id": "network_rail_pure",
    "files": {"chippenham.pyfun": src("chippenham.pyfun"), NR_DIR + "sample.ndjson": src("sample.ndjson")},
    "args": ["run", "chippenham.pyfun"],
    "outputs": [NR_DIR + "chippenham-routes.md"],
}
NR_FAST_CASE = {
    "id": "network_rail_fast",
    "files": {"chippenham_fast.pyfun": src("chippenham_fast.pyfun"), NR_DIR + "sample.ndjson": src("sample.ndjson"),
              NR_DIR + "nr_stream.py": src("nr_stream.py")},
    "env": {"PYTHONPATH": "{workdir}/" + NR_DIR},
    "args": ["run", "chippenham_fast.pyfun"],
    "outputs": [NR_DIR + "chippenham-routes.md"],
}
NR_COMPILE_CASES = [
    {"id": "network_rail_pure_compile", "files": {"c.pyfun": src("chippenham.pyfun")}, "args": ["compile", "c.pyfun"]},
    {"id": "network_rail_fast_compile_native", "files": {"c.pyfun": src("chippenham_fast.pyfun")},
     "args": ["compile", "c.pyfun", "--native"]},
]


def test_network_rail_pure_streaming_report(run, workdir):
    """CATCHES: a `Seq.fold` streaming pipeline whose Markdown report (written to a file the
    program creates) differs in grouping, ordering, durations or counts."""
    _check(run, workdir, NR_PURE_CASE)


def test_network_rail_fast_variant_writes_the_same_report(run, workdir):
    """CATCHES: the native-Python streaming variant producing a different report from the
    pure one (the README promises identical output)."""
    _check(run, workdir, NR_FAST_CASE)
    assert (workdir / NR_DIR / "chippenham-routes.md").read_text() == read_golden(
        __file__, golden_name("network_rail_pure", NR_DIR + "chippenham-routes.md"))


@pytest.mark.parametrize("case", NR_COMPILE_CASES, ids=[c["id"] for c in NR_COMPILE_CASES])
def test_network_rail_programs_compile(run, workdir, case):
    """CATCHES: different Python for the two large network-rail programs."""
    _check(run, workdir, case)
