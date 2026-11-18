"""The default (compile) invocation: input from a file or stdin, -o/--output,
--format, --static, --embed-font, --check, --json, --no-warn/--strict, I/O
errors and the documented exit codes (0 ok, 1 error, 2 I/O, 3 bad CLI)."""

import re

import pytest

from conftest import Case

HELLO = '|box| "x"\n'
FLOW = (
    '{ |svc::box| { fill: --teal-wash; stroke: --teal-ink } }\n\n'
    '|group| "Services" [ |svc#api| "API"; |svc#auth| "Auth" ]\n'
    '|svc#db| "Postgres"\n\n'
    'api  -> db "read"\n'
    'auth -> db "write"\n'
)
# Two warnings: a class defined but never worn, and an auto-created near-miss endpoint.
WARN = '{ .hot { fill: red; } }\n|box#a| "A"\n|box#cat| "Cat"\na -> cta\n'
# One error with a machine-applicable suggestion.
ERROR = '|box#a| { colr: red; }\n'
# An error and a warning together.
MIXED = '{ .cold { fill: blue; } }\n|box#a| "A" { opacity: 3; }\n'

COMPILE_CASES = {
    "stdout_default": Case(("a.lini",), files={"a.lini": FLOW}),
    "explicit_svg_format": Case(("--format", "svg", "a.lini"), files={"a.lini": FLOW}),
    "html_format": Case(("--format", "html", "a.lini"), files={"a.lini": FLOW}),
    "html_format_to_file": Case(("--format", "html", "-o", "page.html", "a.lini"),
                                files={"a.lini": HELLO}, outputs=("page.html",)),
    "output_short": Case(("a.lini", "-o", "out.svg"), files={"a.lini": FLOW}, outputs=("out.svg",)),
    "output_long": Case(("--output", "out.svg", "a.lini"), files={"a.lini": HELLO}, outputs=("out.svg",)),
    "output_overwrites_existing": Case(("-o", "out.svg", "a.lini"),
                                       files={"a.lini": HELLO, "out.svg": "stale contents\n" * 50},
                                       outputs=("out.svg",)),
    "output_into_subdirectory": Case(("-o", "build/out.svg", "a.lini"),
                                     files={"a.lini": HELLO, "build/.keep": ""}, outputs=("build/out.svg",)),
    "stdin_input": Case(("-",), stdin=FLOW),
    "stdin_to_output_file": Case(("-", "-o", "out.svg"), stdin=HELLO, outputs=("out.svg",)),
    "input_in_subdirectory": Case(("src/a.lini",), files={"src/a.lini": HELLO}),
    "empty_input_file": Case(("empty.lini",), files={"empty.lini": ""}),
    "comment_only_input": Case(("c.lini",), files={"c.lini": "// nothing drawn yet\n"}),
    "static_mode": Case(("--static", "a.lini"), files={"a.lini": FLOW}),
    "static_html": Case(("--static", "--format", "html", "a.lini"), files={"a.lini": HELLO}),
    "static_to_file": Case(("--static", "-o", "s.svg", "a.lini"), files={"a.lini": HELLO}, outputs=("s.svg",)),
    "embed_font": Case(("--embed-font", "a.lini"), files={"a.lini": HELLO}),
    "embed_font_with_static": Case(("--embed-font", "--static", "a.lini"), files={"a.lini": HELLO}),
    "embed_font_no_text": Case(("--embed-font", "a.lini"), files={"a.lini": "|box| { width: 30; height: 20; }\n"}),
    "flags_after_input": Case(("a.lini", "--static", "--format", "html"), files={"a.lini": HELLO}),
}

DIAGNOSTIC_CASES = {
    "warnings_printed_with_svg": Case(("w.lini",), files={"w.lini": WARN}),
    "warnings_strict_still_writes_svg": Case(("--strict", "-o", "out.svg", "w.lini"),
                                             files={"w.lini": WARN}, outputs=("out.svg",)),
    "warnings_no_warn_silent": Case(("--no-warn", "-o", "out.svg", "w.lini"),
                                    files={"w.lini": WARN}, outputs=("out.svg",)),
    "error_writes_no_svg": Case(("e.lini",), files={"e.lini": ERROR}),
    "error_leaves_output_absent": Case(("-o", "out.svg", "e.lini"), files={"e.lini": ERROR},
                                       outputs=("out.svg",)),
    "error_keeps_existing_output": Case(("-o", "out.svg", "e.lini"),
                                        files={"e.lini": ERROR, "out.svg": "previous build\n"},
                                        outputs=("out.svg",)),
    "error_from_stdin_names_stdin": Case(("-",), stdin=ERROR),
    "error_in_subdirectory_path": Case(("src/e.lini",), files={"src/e.lini": ERROR}),
    "error_not_silenced_by_no_warn": Case(("--no-warn", "e.lini"), files={"e.lini": ERROR}),
    "mixed_error_and_warning": Case(("m.lini",), files={"m.lini": MIXED}),
    "check_reports_warnings": Case(("--check", "w.lini"), files={"w.lini": WARN}),
    "check_strict_fails_on_warnings": Case(("--check", "--strict", "w.lini"), files={"w.lini": WARN}),
    "check_reports_errors": Case(("--check", "e.lini"), files={"e.lini": ERROR}),
    "check_writes_no_output_file": Case(("--check", "-o", "out.svg", "w.lini"), files={"w.lini": WARN},
                                        outputs=("out.svg",)),
    "check_from_stdin": Case(("--check", "-"), stdin=WARN),
    "check_mixed": Case(("--check", "m.lini"), files={"m.lini": MIXED}),
}

JSON_CASES = {
    "json_clean": Case(("--json", "a.lini"), files={"a.lini": FLOW}),
    "json_stdin_clean": Case(("--json", "-"), stdin=HELLO),
    "json_warnings": Case(("--json", "w.lini"), files={"w.lini": WARN}),
    "json_warnings_strict": Case(("--json", "--strict", "w.lini"), files={"w.lini": WARN}),
    "json_warnings_no_warn": Case(("--json", "--no-warn", "w.lini"), files={"w.lini": WARN}),
    "json_error_with_suggestion": Case(("--json", "e.lini"), files={"e.lini": ERROR}),
    "json_error_from_stdin": Case(("--json", "-"), stdin=ERROR),
    "json_mixed": Case(("--json", "m.lini"), files={"m.lini": MIXED}),
    "json_ignores_output_flag": Case(("--json", "-o", "out.svg", "e.lini"), files={"e.lini": ERROR},
                                     outputs=("out.svg",)),
    "json_wins_over_check": Case(("--check", "--json", "w.lini"), files={"w.lini": WARN}),
    "json_parse_error": Case(("--json", "p.lini"), files={"p.lini": '|box| "unterminated\n'}),
    "json_subdirectory_file_name": Case(("--json", "src/e.lini"), files={"src/e.lini": ERROR}),
    "json_multibyte_spans": Case(("--json", "u.lini"),
                                 files={"u.lini": '|box#a| "héllo — ünïcode" { colr: red; }\n'}),
}

IO_CASES = {
    "missing_input_file": Case(("missing.lini",)),
    "missing_input_with_check": Case(("--check", "missing.lini")),
    "missing_input_with_json": Case(("--json", "missing.lini")),
    "input_is_directory": Case(("d",), files={"d/.keep": ""}),
    "input_not_utf8": Case(("bad.lini",), files={"bad.lini": b"|box| \"\xff\xfe\"\n"}),
    "stdin_not_utf8": Case(("-",), stdin=b"\xff\xfe\n"),
    "output_directory_missing": Case(("-o", "nope/out.svg", "a.lini"), files={"a.lini": HELLO}),
    "output_is_directory": Case(("-o", "d", "a.lini"), files={"a.lini": HELLO, "d/.keep": ""}),
    "invalid_format_checked_before_input": Case(("--format", "png", "missing.lini")),
}


@pytest.mark.parametrize("name", sorted(COMPILE_CASES))
def test_compile_outputs(run_case, golden, name):
    """CATCHES: a compile that writes to the wrong place (stdout vs -o file), ignores
    --format html / --static / --embed-font, mishandles stdin '-', or changes the
    emitted SVG bytes for the same input."""
    assert run_case(COMPILE_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(DIAGNOSTIC_CASES))
def test_compile_diagnostics(run_case, golden, name):
    """CATCHES: wrong `file:line:col: severity: message` diagnostics, a warning that
    sets a non-zero exit without --strict, --strict not failing on warnings,
    --no-warn not silencing them (or silencing errors), an output written despite
    an error, or --check writing an artefact."""
    assert run_case(DIAGNOSTIC_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(JSON_CASES))
def test_json_diagnostics(run_case, golden, name):
    """CATCHES: a --json document with a different shape (file, code, family,
    severity, message, span byte/line/col fields, suggestion), wrong byte offsets
    for multibyte text, wrong exit code under --strict, or SVG leaking out."""
    assert run_case(JSON_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(IO_CASES))
def test_io_errors(run_case, golden, name):
    """CATCHES: I/O failures reported with the wrong message or with an exit code
    other than 2, or CLI validation (exit 3) running after the input is read."""
    assert run_case(IO_CASES[name]) == golden(name)


def test_check_writes_nothing_that_compile_would(run, workdir):
    """CATCHES: a --check that still emits the SVG to stdout or the -o file, or a
    --check that skips the compile entirely (the plain compile must still work)."""
    (workdir / "a.lini").write_text(FLOW)
    checked = run(["--check", "-o", "out.svg", "a.lini"])
    assert (checked.returncode, checked.stdout, checked.stderr) == (0, b"", b"")
    assert not (workdir / "out.svg").exists()
    built = run(["-o", "out.svg", "a.lini"])
    assert (built.returncode, built.stdout, built.stderr) == (0, b"", b"")
    plain = run(["a.lini"])
    assert (workdir / "out.svg").read_bytes() == plain.stdout
    assert plain.stdout.startswith(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="')


def test_output_file_matches_stdout(run, workdir):
    """CATCHES: -o writing different bytes than the stdout form (an extra newline,
    a BOM, a different wrapper) for the same input and flags."""
    (workdir / "a.lini").write_text(FLOW)
    for flags in ([], ["--static"], ["--format", "html"]):
        to_stdout = run([*flags, "a.lini"])
        to_file = run([*flags, "-o", "f.out", "a.lini"])
        assert to_file.stdout == b""
        assert (workdir / "f.out").read_bytes() == to_stdout.stdout
        assert to_stdout.stdout.rstrip().endswith(b"</svg>" if flags != ["--format", "html"] else b"</html>")


def test_stdin_matches_file_input(run, workdir):
    """CATCHES: stdin input compiling differently from the same file (e.g. a base
    directory or file name leaking into the SVG)."""
    (workdir / "a.lini").write_text(FLOW)
    from_file = run(["a.lini"])
    from_stdin = run(["-"], input=FLOW)
    assert from_stdin.returncode == 0
    assert from_stdin.stdout == from_file.stdout
    assert from_stdin.stdout.endswith(b"</svg>\n")


def test_embed_font_embeds_each_used_weight(run, workdir, golden):
    """CATCHES: --embed-font embedding a different font subset, a different
    @font-face structure, or a non-base64 payload (exact bytes compared)."""
    (workdir / "a.lini").write_text('|box| "Bold" { font-weight: bold; }\n|box| "Regular" { font-weight: normal; }\n')
    r = run(["--embed-font", "a.lini"])
    assert r.returncode == 0
    assert r.stderr == b""
    out = r.stdout.decode()
    faces = re.findall(r"@font-face \{[^}]*\}", out)
    assert len(faces) == 2
    assert out == golden("embed_font_two_weights")
