"""The compile command's I/O contract: inputs (file, stdin, odd encodings),
outputs (stdout, -o files, html), the diagnostic flags and the exit codes."""

import subprocess

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

TWO_BOXES = '|box#a| "Alpha"\n|box#b| "Beta"\na -> b "calls"\n'
WARNS = '{ .hot { fill: red; } }\n|box| "x"\n'
BROKEN = '|box#a| "x" { colr: red; }\n'


def test_file_input_to_stdout(run, workdir):
    """CATCHES: wrong default SVG for a small linked diagram read from a file argument (layout, link routing, marker, label)."""
    write_files(workdir, {"two.lini": TWO_BOXES})
    r = run(["two.lini"])
    assert outcome(r) == G("file_two_boxes")


def test_stdin_matches_file_output(run, workdir):
    """CATCHES: stdin ('-') read differently from a file: the SVG must be byte-identical to the file compile."""
    write_files(workdir, {"two.lini": TWO_BOXES})
    from_file = run(["two.lini"])
    from_stdin = run(["-"], input=TWO_BOXES)
    assert outcome(from_stdin) == outcome(from_file)
    assert outcome(from_stdin) == G("file_two_boxes")


def test_output_flag_writes_file_and_nothing_to_stdout(run, workdir):
    """CATCHES: -o that still prints to stdout, writes a different document than stdout would, or fails to create the file."""
    write_files(workdir, {"two.lini": TWO_BOXES})
    r = run(["two.lini", "-o", "out.svg"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    assert (workdir / "out.svg").read_text() == G("file_two_boxes").split("--- stdout ---\n", 1)[1].split("--- stderr ---\n")[0]


def test_long_output_flag_overwrites_existing_file(run, workdir):
    """CATCHES: --output appending to, or refusing to replace, an existing file."""
    write_files(workdir, {"in.lini": '|oval| "o"\n', "out.svg": "stale content that must disappear\n" * 50})
    r = run(["--output", "out.svg", "in.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    assert (workdir / "out.svg").read_text() == G("oval_svg")


def test_output_into_missing_directory_is_io_error(run, workdir):
    """CATCHES: a failed write not reported as 'error: write PATH: ...' with exit code 2."""
    r = run(["-", "-o", "nodir/x.svg"], input='|box| "x"\n')
    assert outcome(r) == G("write_missing_dir")
    assert not (workdir / "nodir").exists()


def test_html_format_to_file(run, workdir):
    """CATCHES: a wrong HTML wrapper (doctype, head, body) around the SVG when --format html is combined with -o."""
    write_files(workdir, {"in.lini": TWO_BOXES})
    r = run(["--format", "html", "-o", "page.html", "in.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    assert (workdir / "page.html").read_text() == G("html_page")


def test_html_static_combination(run):
    """CATCHES: --format html losing --static baking/outlining, or --static ignoring the html wrapper."""
    r = run(["--format", "html", "--static", "-"], input='|box| "Hi" { fill: --accent; }\n')
    assert outcome(r) == G("html_static")


def test_explicit_svg_format_equals_default(run):
    """CATCHES: '--format svg' producing anything other than the default output."""
    r = run(["--format", "svg", "-"], input=TWO_BOXES)
    assert outcome(r) == G("file_two_boxes")


def test_invalid_format_is_cli_error(run):
    """CATCHES: an unknown --format accepted, or rejected with the wrong message or an exit code other than 3."""
    r = run(["--format", "pdf", "-"], input='|box|\n')
    assert outcome(r) == "exit: 3\n--- stdout ---\n--- stderr ---\nerror: invalid --format 'pdf' (expected svg|html)\n"


def test_missing_input_file(run):
    """CATCHES: a missing input not reported as 'error: PATH: <os error>' with exit code 2."""
    r = run(["nope.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: nope.lini: No such file or directory (os error 2)\n"


def test_directory_as_input(run, workdir):
    """CATCHES: a directory input not rejected as an I/O error (exit 2) with the OS message."""
    (workdir / "d").mkdir()
    r = run(["d"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: d: Is a directory (os error 21)\n"


def test_invalid_utf8_file(run, workdir):
    """CATCHES: non-UTF-8 input decoded lossily instead of failing with exit 2 and the stream message."""
    write_files(workdir, {"bad.lini": b'|box| "\xff\xfe"\n'})
    r = run(["bad.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: bad.lini: stream did not contain valid UTF-8\n"


def test_invalid_utf8_stdin(run):
    """CATCHES: non-UTF-8 stdin accepted, or reported with a different message or exit code."""
    r = run(["-"], input=b'|box| "caf\xe9"\n')
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: failed to read stdin: stream did not contain valid UTF-8\n"


def test_empty_input_is_an_empty_figure(run):
    """CATCHES: empty input treated as an error, or a different empty-scene document (viewBox 40x40, defaults block)."""
    r = run(["-"], input="")
    assert outcome(r) == G("empty")


def test_blank_and_comment_only_input_equals_empty(run):
    """CATCHES: blank lines or comments producing output different from an empty file."""
    r = run(["-"], input="\n\n   \n// only a comment\n\t\n")
    assert outcome(r) == G("empty")


def test_crlf_line_endings(run):
    """CATCHES: CRLF newlines breaking statement separation or leaking '\\r' into text."""
    r = run(["-"], input=TWO_BOXES.replace("\n", "\r\n"))
    assert outcome(r) == G("file_two_boxes")


def test_utf8_bom_is_ignored(run):
    """CATCHES: a leading UTF-8 byte-order mark rejected as an unexpected character or rendered as text."""
    r = run(["-"], input=b"\xef\xbb\xbf" + TWO_BOXES.encode())
    assert outcome(r) == G("file_two_boxes")


def test_unicode_labels_live_output(run):
    """CATCHES: wrong measurement or escaping of non-ASCII text (accents, CJK, emoji, XML specials) in labels."""
    src = '|box#a| "Café & Crème"\n|box#b| "你好世界"\n|box#c| "<tag> \\"q\\""\n|oval#d| "🙂 ok"\na -> b -> c -> d "→ ünïcödé"\n'
    r = run(["-"], input=src)
    assert outcome(r) == G("unicode_live")


def test_unicode_static_warns_and_keeps_text(run):
    """CATCHES: --static silently dropping glyphs it cannot outline instead of keeping <text> and warning (O001) per run."""
    src = '|box| "Plain"\n|box| "你好"\n|box| "mixed ü 😀"\n'
    r = run(["--static", "-"], input=src)
    assert outcome(r) == G("unicode_static")


def test_large_input(run):
    """CATCHES: wrong grid flow or performance collapse on a 240-node grid with many links."""
    lines = ["{ layout: grid; columns: repeat(12); gap: 10; }"]
    for i in range(240):
        lines.append(f'|box#n{i}| "N{i}"')
    for i in range(0, 228, 7):
        lines.append(f"n{i} -> n{i + 12}")
    r = run(["-"], input="\n".join(lines) + "\n")
    assert outcome(r) == G("large_grid")


def test_two_inputs_rejected(run, workdir):
    """CATCHES: accepting several input files instead of the clap 'cannot be used with' error (exit 3)."""
    write_files(workdir, {"a.lini": '|box| "a"\n', "b.lini": '|box| "b"\n'})
    r = run(["a.lini", "b.lini"])
    assert outcome(r) == G("two_inputs")


def test_no_arguments(run):
    """CATCHES: running with no input not failing with the required-argument usage error and exit 3."""
    r = run([])
    assert outcome(r) == G("no_args")


def test_unknown_flag(run):
    """CATCHES: unknown options accepted or reported with an exit code other than 3."""
    r = run(["--bogus", "x.lini"])
    assert outcome(r) == G("unknown_flag")


def test_version(run):
    """CATCHES: a wrong program name or version string for -V/--version."""
    assert outcome(run(["-V"])) == "exit: 0\n--- stdout ---\nlini 1.1.0\n--- stderr ---\n"
    assert outcome(run(["--version"])) == "exit: 0\n--- stdout ---\nlini 1.1.0\n--- stderr ---\n"


def test_help(run):
    """CATCHES: missing or reworded options in the top-level help text."""
    r = run(["--help"])
    assert outcome(r) == G("help")


def test_check_clean_writes_nothing(run, workdir):
    """CATCHES: --check that prints the SVG or creates the -o file for a clean input."""
    write_files(workdir, {"in.lini": TWO_BOXES})
    r = run(["--check", "-o", "out.svg", "in.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    assert sorted(p.name for p in workdir.iterdir()) == ["in.lini"]
    r = run(["-o", "out.svg", "in.lini"])
    assert sorted(p.name for p in workdir.iterdir()) == ["in.lini", "out.svg"]
    assert (workdir / "out.svg").read_text() == G("file_two_boxes").split("--- stdout ---\n", 1)[1].split("--- stderr ---\n")[0]


def test_check_reports_warning_exit_zero(run, workdir):
    """CATCHES: --check not printing a warning in file:line:col form, or failing on a mere warning."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--check", "w.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\nw.lini:1:3: warning: class '.hot' is never worn\n"


def test_check_strict_fails_on_warning(run, workdir):
    """CATCHES: --strict not promoting a warning to exit 1 under --check."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--check", "--strict", "w.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\nw.lini:1:3: warning: class '.hot' is never worn\n"


def test_check_no_warn_silences(run, workdir):
    """CATCHES: --no-warn still printing warnings under --check."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--check", "--no-warn", "w.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    r = run(["--check", "w.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\nw.lini:1:3: warning: class '.hot' is never worn\n"


def test_check_error_exit_one(run, workdir):
    """CATCHES: --check not failing (exit 1) on a validation error, or printing it differently from a normal compile."""
    write_files(workdir, {"e.lini": BROKEN})
    r = run(["--check", "e.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\ne.lini:1:15: error: unknown property 'colr'; did you mean 'color'?\n"
    assert outcome(run(["e.lini"])) == outcome(r)


def test_strict_svg_still_written_but_fails(run, workdir):
    """CATCHES: --strict suppressing the SVG, or exiting 0, when the compile only warns."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--strict", "w.lini", "-o", "w.svg"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\nw.lini:1:3: warning: class '.hot' is never worn\n"
    assert (workdir / "w.svg").read_text() == G("warns_svg")


def test_warning_printed_with_svg(run, workdir):
    """CATCHES: a default compile hiding warnings, failing on them, or mixing them into stdout."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["w.lini"])
    assert r.stdout.decode() == G("warns_svg")
    assert outcome(r) == "exit: 0\n--- stdout ---\n" + G("warns_svg") + "--- stderr ---\nw.lini:1:3: warning: class '.hot' is never worn\n"


def test_no_warn_compile(run, workdir):
    """CATCHES: --no-warn changing the SVG or still printing warnings."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--no-warn", "w.lini"])
    assert outcome(r) == "exit: 0\n--- stdout ---\n" + G("warns_svg") + "--- stderr ---\n"


def test_no_warn_conflicts_with_strict(run):
    """CATCHES: accepting --no-warn together with --strict instead of a clap conflict error (exit 3)."""
    r = run(["--no-warn", "--strict", "x.lini"])
    assert outcome(r) == G("nowarn_strict_conflict")


def test_json_warning_document(run, workdir):
    """CATCHES: --json emitting SVG, writing to -o, or a wrong warning record (code V004, span offsets)."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--json", "-o", "x.svg", "w.lini"])
    assert outcome(r) == G("json_warning")
    assert not (workdir / "x.svg").exists()


def test_json_strict_fails_on_warning(run, workdir):
    """CATCHES: --json ignoring --strict (must exit 1 when any warning fires)."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--json", "--strict", "w.lini"])
    assert outcome(r) == G("json_warning").replace("exit: 0", "exit: 1")


def test_json_no_warn_keeps_document(run, workdir):
    """CATCHES: --json --no-warn changing the JSON document or the exit status."""
    write_files(workdir, {"w.lini": WARNS})
    r = run(["--json", "--no-warn", "w.lini"])
    assert outcome(r) == G("json_warning")


def test_json_error_with_suggestion(run, workdir):
    """CATCHES: a JSON error record missing its machine-applicable suggestion, or exit 0 on an error."""
    write_files(workdir, {"e.lini": BROKEN})
    r = run(["--json", "e.lini"])
    assert outcome(r) == G("json_error_suggestion")


def test_json_stdin_filename(run):
    """CATCHES: --json naming stdin anything other than '<stdin>' or a clean file producing diagnostics."""
    r = run(["--json", "-"], input='|box| "ok"\n')
    assert outcome(r) == 'exit: 0\n--- stdout ---\n{\n  "file": "<stdin>",\n  "diagnostics": []\n}\n--- stderr ---\n'


def test_stdin_errors_name_stdin(run):
    """CATCHES: diagnostics for stdin input not labelled '<stdin>'."""
    r = run(["-"], input='|box| "x"\n|nosuch| "y"\n')
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\n<stdin>:2:1: error: unknown type 'nosuch'\n"


def test_input_in_subdirectory_keeps_relative_name(run, workdir):
    """CATCHES: diagnostics that print an absolute or normalised path instead of the argument as given."""
    write_files(workdir, {"sub/dir/e.lini": BROKEN})
    r = run(["./sub/dir/e.lini"])
    assert outcome(r) == "exit: 1\n--- stdout ---\n--- stderr ---\n./sub/dir/e.lini:1:15: error: unknown property 'colr'; did you mean 'color'?\n"


def test_watch_requires_output(run):
    """CATCHES: --watch accepted without -o (clap must demand --output, exit 3)."""
    r = run(["--watch", "x.lini"])
    assert outcome(r) == G("watch_no_output")


def test_watch_rejects_stdin(run):
    """CATCHES: --watch trying to watch stdin instead of failing with exit 3."""
    r = run(["--watch", "-o", "out.svg", "-"], input="|box|\n")
    assert outcome(r) == "exit: 3\n--- stdout ---\n--- stderr ---\nerror: --watch cannot read from stdin\n"


def test_watch_compiles_once_then_keeps_running(run, workdir):
    """CATCHES: --watch that exits immediately, does not write the first compile to -o, or prints a different banner."""
    write_files(workdir, {"in.lini": TWO_BOXES})
    with pytest.raises(subprocess.TimeoutExpired) as info:
        run(["--watch", "in.lini", "-o", "out.svg"], timeout=2)
    import re
    stderr = re.sub(r"ok \(\d+ ms\)", "ok (N ms)", info.value.stderr.decode())
    assert stderr == "watching in.lini → out.svg\nok (N ms) → out.svg\n"
    assert (workdir / "out.svg").read_text() == G("file_two_boxes").split("--- stdout ---\n", 1)[1].split("--- stderr ---\n")[0]


def test_watch_check_mode_banner(run, workdir):
    """CATCHES: --watch --check writing the output file or printing the svg banner instead of 'check passed'."""
    write_files(workdir, {"in.lini": TWO_BOXES})
    with pytest.raises(subprocess.TimeoutExpired) as info:
        run(["--watch", "--check", "in.lini", "-o", "out.svg"], timeout=2)
    import re
    stderr = re.sub(r"ok \(\d+ ms\)", "ok (N ms)", info.value.stderr.decode())
    assert stderr == "watching in.lini → out.svg\nok (N ms) — check passed\n"
    assert not (workdir / "out.svg").exists()


def test_watch_error_reported_without_ok(run, workdir):
    """CATCHES: --watch printing 'ok' for a failing compile, or not printing the located error."""
    write_files(workdir, {"in.lini": BROKEN})
    with pytest.raises(subprocess.TimeoutExpired) as info:
        run(["--watch", "in.lini", "-o", "out.svg"], timeout=2)
    assert info.value.stderr.decode() == "watching in.lini → out.svg\nin.lini:1:15: error: unknown property 'colr'; did you mean 'color'?\n"
    assert not (workdir / "out.svg").exists()


def test_static_and_embed_font_together(run):
    """CATCHES: --static and --embed-font interfering (outlined text needs no @font-face; the pair must still produce the reference document)."""
    r = run(["--static", "--embed-font", "-"], input='|box| "Hi" { font-weight: bold; }\n')
    assert outcome(r) == G("static_embed")


def test_embed_font_mono_and_weights(run):
    """CATCHES: --embed-font embedding the wrong set of family x weight subsets for mixed text."""
    src = '|box| "regular" { font-weight: normal; }\n|box| "code" { font-family: "Google Sans Code"; font-weight: bold; }\n'
    r = run(["--embed-font", "-"], input=src)
    assert outcome(r) == G("embed_mixed")


def test_short_help_matches_long(run):
    """CATCHES: -h printing a different text than --help."""
    assert outcome(run(["-h"])) == G("help")


@pytest.mark.parametrize("sub", ["fmt", "serve", "desugar", "highlight", "theme"])
def test_subcommand_help(run, sub):
    """CATCHES: a subcommand whose --help lists different arguments/options or wording, or that is not reachable via 'help SUB' too."""
    r = run([sub, "--help"])
    assert outcome(r) == G(f"help_{sub}")
    assert outcome(run(["help", sub])) == G(f"help_{sub}")


def test_help_subcommand_without_argument(run):
    """CATCHES: 'help' alone not printing the top-level help."""
    assert outcome(run(["help"])) == G("help")
