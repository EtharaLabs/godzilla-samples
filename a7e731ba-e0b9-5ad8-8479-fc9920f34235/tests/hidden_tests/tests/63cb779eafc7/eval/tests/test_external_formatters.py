"""Embedded/external formatter dispatch: [embedded] config, optional vs strict failures, notebooks, skipping."""

import json
import os

import pytest

from conftest import assert_golden, transcript

FENCES = "Intro   text.\n\n```python\nx=1\n```\n\n```r\ny<-2\n```\n\n```css\na{b:c}\n```\n"


def install(workdir, name, script):
    """Create an executable fake formatter in workdir/bin."""
    path = workdir / "bin" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(script)
    os.chmod(path, 0o755)


def controlled_path(workdir):
    """PATH with only our fake formatters plus the system shell/python directories (no real ruff/air/prettier)."""
    return {"PATH": f"{workdir / 'bin'}:/usr/bin:/bin"}


def config(workdir, text):
    (workdir / "yamark.toml").write_text(text)


def strict(name, script, suffix=".txt"):
    return (f"[embedded.{name}]\nformatter = {{ command = [\"sh\", \"-c\", {json.dumps(script)}, \"{{path}}\"], "
            f"path_suffix = \"{suffix}\" }}\n")


def test_missing_optional_formatters_preserve_source_silently(run, workdir):
    """CATCHES: failing (or printing notes without --diagnostics) when built-in optional formatters such as ruff,
    air and prettier are not installed; the fenced code must stay unchanged while prose still formats."""
    (workdir / "bin").mkdir()
    result = run(["format", "--stdin-file-path", "in.md"], input=FENCES, env_overrides=controlled_path(workdir))
    assert (result.returncode, result.stderr) == (0, b"")
    assert result.stdout == FENCES.replace("Intro   text.", "Intro text.").encode()


def test_missing_optional_formatters_noted_with_diagnostics(run, workdir):
    """CATCHES: missing or misworded 'missing optional embedded formatter' notes (with the fence's line) under
    --diagnostics."""
    (workdir / "bin").mkdir()
    result = run(["format", "--stdin-file-path", "in.md", "--diagnostics"], input=FENCES,
                 env_overrides=controlled_path(workdir))
    assert result.returncode == 0
    assert result.stderr == (b"in.md:4:1: note: missing optional embedded formatter `ruff`; preserved source\n"
                             b"in.md:8:1: note: missing optional embedded formatter `air`; preserved source\n"
                             b"in.md:12:1: note: missing optional embedded formatter `prettier`; preserved source\n")


def test_failing_optional_formatters_are_notes(run, workdir):
    """CATCHES: treating a failing optional formatter as an error, or not extracting the '(line:column)' location
    from its stderr into the note."""
    install(workdir, "ruff", "#!/bin/sh\necho 'error: cannot parse at (3:5)' >&2\nexit 2\n")
    install(workdir, "air", "#!/bin/sh\nexit 4\n")
    install(workdir, "prettier", "#!/bin/sh\necho '[error] x.css: SyntaxError: Unexpected (1:2)' >&2\nexit 2\n")
    result = run(["format", "--stdin-file-path", "in.md", "--diagnostics"], input=FENCES,
                 env_overrides=controlled_path(workdir))
    assert result.returncode == 0
    assert result.stderr == (
        b"in.md:4:1: note: embedded formatter `ruff` failed at formatter input 3:5; left chunk unchanged\n"
        b"in.md:8:1: note: embedded formatter `air` failed; left chunk unchanged\n"
        b"in.md:12:1: note: embedded formatter `prettier` failed at formatter input 1:2; left chunk unchanged\n")
    assert result.stdout == FENCES.replace("Intro   text.", "Intro text.").encode()


@pytest.mark.parametrize("message,expected", [
    ("line 7:12 bad", b"failed; left chunk unchanged"),
    ("file:7:12 bad", b"failed at formatter input 7:12"),
    ("(4:9) first (5:6)", b"failed at formatter input 4:9"),
    ("x.py:2:3: E999 SyntaxError", b"failed at formatter input 2:3"),
    ("error (0:5)", b"failed; left chunk unchanged"),
    ("at (12:x) or 4:", b"failed; left chunk unchanged"),
    ("(99999999999999999999999:1)", b"failed; left chunk unchanged"),
])
def test_optional_failure_location_parsing(message, expected, run, workdir):
    """CATCHES: wrong extraction of the formatter input location from optional-formatter error messages
    (parenthesized 'l:c', colon-delimited 'l:c:', zero or overflowing numbers)."""
    install(workdir, "ruff", f"#!/bin/sh\necho {json.dumps(message)} >&2\nexit 1\n")
    result = run(["format", "--stdin-file-path", "in.md", "--diagnostics"], input="```python\nx=1\n```\n",
                 env_overrides=controlled_path(workdir))
    assert result.returncode == 0
    assert result.stderr.startswith(b"in.md:2:1: note: embedded formatter `ruff` ")
    assert expected in result.stderr


def test_ruff_receives_notebook_and_virtual_path(run, workdir):
    """CATCHES: not sending Ruff a one-cell notebook on stdin, using a different --stdin-filename virtual path
    (<file>.embedded.<line>.ipynb), or mishandling the source returned as a list of lines."""
    install(workdir, "ruff", "#!/usr/bin/env python3\nimport json, sys\nnb = json.load(sys.stdin)\n"
                             "open('args.txt', 'w').write(' '.join(sys.argv[1:]) + '\\n' + json.dumps(nb, sort_keys=True))\n"
                             "nb['cells'][0]['source'] = nb['cells'][0]['source'].replace('=', ' = ').splitlines(True)\n"
                             "print(json.dumps(nb))\n")
    result = run(["format", "--stdin-file-path", "docs/in.md"], input="```{python}\nx=1\ny=2\n```\n",
                 env_overrides=controlled_path(workdir))
    assert (result.returncode, result.stdout, result.stderr) == (0, b"```{python}\nx = 1\ny = 2\n```\n", b"")
    assert (workdir / "args.txt").read_text() == (
        "format --stdin-filename docs/in.md.embedded.2.ipynb -\n"
        '{"cells": [{"cell_type": "code", "metadata": {}, "outputs": [], "source": "x=1\\ny=2\\n"}], '
        '"metadata": {}, "nbformat": 4, "nbformat_minor": 5}')


@pytest.mark.parametrize("name,output", [
    ("invalid_json", "not json"),
    ("no_cells", "{}"),
    ("two_cells", '{"cells": [{"source": "a"}, {"source": "b"}]}'),
    ("no_source", '{"cells": [{}]}'),
    ("bad_lines", '{"cells": [{"source": ["a", 1]}]}'),
    ("bad_source", '{"cells": [{"source": 5}]}'),
    ("string_source", '{"cells": [{"source": "y = 1\\n"}]}'),
])
def test_ruff_notebook_output_validation(name, output, run, workdir):
    """CATCHES: accepting malformed notebook JSON from Ruff (invalid JSON, missing cells, more than one cell, missing
    or non-string source) instead of failing the file, or rejecting a plain string source."""
    install(workdir, "ruff", f"#!/bin/sh\ncat > /dev/null\nprintf '%s' {json.dumps(output)}\n")
    result = run(["format", "--stdin-file-path", "in.md"], input="```python\nx=1\n```\n",
                 env_overrides=controlled_path(workdir))
    assert_golden(transcript(result), __file__, f"notebook_{name}")


def test_strict_formatter_success(run, workdir):
    """CATCHES: not running a configured formatter for its fence/directive name, or not passing the virtual path."""
    config(workdir, strict("upper", "tr a-z A-Z; echo \"# $0\""))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```upper\nhello\n```\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"```upper\nHELLO\n# doc.md.embedded.2.txt\n```\n", b"")


def test_strict_formatter_nonzero_exit_with_stderr(run, workdir):
    """CATCHES: treating a failing non-optional formatter as optional; its trimmed stderr is the error message."""
    config(workdir, strict("lint", "echo '  boom happened  ' >&2; exit 3"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```lint\nx\n```\n")
    assert (result.returncode, result.stdout, result.stderr) == (1, b"", b"doc.md:1:1: error: boom happened\n")


def test_strict_formatter_nonzero_exit_without_stderr(run, workdir):
    """CATCHES: a different message when a strict formatter exits nonzero silently."""
    config(workdir, strict("lint", "exit 3"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```lint\nx\n```\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == (b"doc.md:1:1: error: embedded formatter failed: command `sh -c exit 3 "
                             b"doc.md.embedded.2.txt` exited with exit status 3 for doc.md.embedded.2.txt\n")


def test_strict_formatter_killed_by_signal(run, workdir):
    """CATCHES: mishandling a formatter terminated by a signal (no exit code)."""
    config(workdir, strict("lint", "kill -9 $$"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```lint\nx\n```\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == (b"doc.md:1:1: error: embedded formatter failed: command `sh -c kill -9 $$ "
                             b"doc.md.embedded.2.txt` exited with signal: 9 (SIGKILL) for doc.md.embedded.2.txt\n")


def test_successful_formatter_writing_stderr_is_an_error(run, workdir):
    """CATCHES: ignoring stderr output from a formatter that exits 0 (always an error)."""
    config(workdir, strict("noisy", "cat; echo warning >&2"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```noisy\nx\n```\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"doc.md:1:1: error: embedded formatter wrote to stderr: warning\n")


def test_successful_formatter_writing_blank_stderr(run, workdir):
    """CATCHES: a different message when the stderr output is only whitespace."""
    config(workdir, strict("noisy", "cat; printf '  \\n' >&2"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```noisy\nx\n```\n")
    assert (result.returncode, result.stderr) == (1, b"doc.md:1:1: error: embedded formatter wrote to stderr\n")


def test_optional_formatter_writing_stderr_is_still_an_error(run, workdir):
    """CATCHES: excusing stderr output from a successful optional formatter."""
    install(workdir, "ruff", "#!/bin/sh\ncat\necho note >&2\n")
    result = run(["format", "--stdin-file-path", "in.md"], input="```python\nx=1\n```\n",
                 env_overrides=controlled_path(workdir))
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"in.md:1:1: error: embedded formatter wrote to stderr: note\n")


def test_formatter_invalid_utf8_output(run, workdir):
    """CATCHES: accepting (or lossily decoding) non-UTF-8 bytes written by an embedded formatter."""
    config(workdir, strict("bin", "cat >/dev/null; printf '\\377\\n'"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```bin\nx\n```\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"doc.md:1:1: error: embedded formatter emitted invalid UTF-8: invalid utf-8 sequence of 1 bytes "
                b"from index 0\n")


def test_missing_strict_executable(run, workdir):
    """CATCHES: silently skipping a configured formatter whose executable does not exist."""
    config(workdir, "[embedded.sql]\nformatter = { command = [\"no-such-sqlfmt\", \"{path}\"], path_suffix = \".sql\" }\n")
    result = run(["format", "--stdin-file-path", "doc.md"], input="```sql\nselect 1\n```\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"doc.md:1:1: error: failed to run embedded formatter: No such file or directory (os error 2)\n")


def test_configured_prettier_command_is_optional(run, workdir):
    """CATCHES: treating a configured command whose first argv item is exactly 'prettier' as strict."""
    (workdir / "bin").mkdir()
    config(workdir, "[embedded.vue]\nformatter = { command = [\"prettier\", \"--stdin-filepath\", \"{path}\"], "
                    "path_suffix = \".vue\" }\n")
    result = run(["format", "--stdin-file-path", "doc.md", "--diagnostics"], input="```vue\n<a/>\n```\n",
                 env_overrides=controlled_path(workdir))
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"```vue\n<a/>\n```\n", b"doc.md:2:1: note: missing optional embedded formatter `prettier`; preserved source\n")


def test_configured_prettier_path_is_strict(run, workdir):
    """CATCHES: treating '/usr/bin/prettier' (not exactly 'prettier') as optional."""
    config(workdir, "[embedded.vue]\nformatter = { command = [\"/nonexistent/prettier\", \"{path}\"], "
                    "path_suffix = \".vue\" }\n")
    result = run(["format", "--stdin-file-path", "doc.md"], input="```vue\n<a/>\n```\n")
    assert (result.returncode, result.stderr) == (
        1, b"doc.md:1:1: error: failed to run embedded formatter: No such file or directory (os error 2)\n")


def test_configured_entry_replaces_builtin_alias(run, workdir):
    """CATCHES: still using the built-in Ruff mapping for 'python' after [embedded.python] replaces it."""
    config(workdir, strict("python", "sed 's/=/ = /'", ".py"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```python\nx=1\n```\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"```python\nx = 1\n```\n", b"")


@pytest.mark.parametrize("shorthand", ["ruff", "air", "mdformat", "prettier-json", "prettier-ts", "prettier-html"])
def test_builtin_shorthands_in_config(shorthand, run, workdir):
    """CATCHES: rejecting a documented built-in shorthand, or not treating it as optional when missing."""
    (workdir / "bin").mkdir()
    config(workdir, f"[embedded.thing]\nformatter = \"{shorthand}\"\n")
    result = run(["format", "--stdin-file-path", "doc.md", "--diagnostics"], input="```thing\ncode\n```\n",
                 env_overrides=controlled_path(workdir))
    executable = shorthand.split("-")[0]
    assert (result.returncode, result.stdout) == (0, b"```thing\ncode\n```\n")
    assert result.stderr.decode() == f"doc.md:2:1: note: missing optional embedded formatter `{executable}`; preserved source\n"


@pytest.mark.parametrize("lang", ["json", "jsonc", "json5", "graphql", "gql", "graphqls", "scss", "less", "postcss",
                                  "pcss", "html", "js", "javascript", "jsx", "ts", "typescript", "tsx", "mdformat",
                                  "prettier-css"])
def test_fence_language_aliases_use_prettier_paths(lang, run, workdir):
    """CATCHES: wrong built-in alias table (fence language -> formatter and virtual path suffix)."""
    install(workdir, "prettier", "#!/bin/sh\nprintf '%s\\n' \"$*\" > args.txt\ncat\n")
    install(workdir, "mdformat", "#!/bin/sh\nprintf '%s\\n' \"$*\" > args.txt\ncat\n")
    result = run(["format", "--stdin-file-path", "d.md"], input=f"```{lang}\ncode\n```\n",
                 env_overrides=controlled_path(workdir))
    assert (result.returncode, result.stdout, result.stderr) == (0, f"```{lang}\ncode\n```\n".encode(), b"")
    assert_golden((workdir / "args.txt").read_text(), __file__, f"alias_{lang}")


def test_skip_embedded_formatters(run, workdir):
    """CATCHES: --skip-embedded-formatters still running external formatters (configured or built-in), or
    disabling Yamark's own Markdown/YAML formatting."""
    config(workdir, strict("upper", "tr a-z A-Z"))
    install(workdir, "ruff", "#!/bin/sh\nexit 9\n")
    doc = "Some   text.\n\n```upper\nhello\n```\n\n```yaml\na:   1\n```\n\n```python\nx=1\n```\n"
    result = run(["format", "--stdin-file-path", "doc.md", "--skip-embedded-formatters", "--diagnostics"], input=doc,
                 env_overrides=controlled_path(workdir))
    assert (result.returncode, result.stderr) == (0, b"")
    assert result.stdout == b"Some text.\n\n```upper\nhello\n```\n\n```yaml\na: 1\n```\n\n```python\nx=1\n```\n"


def test_yaml_literal_embedded_directive(run, workdir):
    """CATCHES: `# fmt: <name>` before a YAML literal scalar not sending the decoded block to the formatter, or
    re-indenting the formatted result incorrectly."""
    config(workdir, strict("upper", "tr a-z A-Z", ".sh"))
    doc = "steps:\n  # fmt: upper\n  run: |\n    echo hi\n      nested\n  other:   1\n"
    result = run(["format", "--stdin-file-path", "ci.yaml"], input=doc)
    assert (result.returncode, result.stderr) == (0, b"")
    assert result.stdout == b"steps:\n  # fmt: upper\n  run: |\n    ECHO HI\n      NESTED\n  other: 1\n"


def test_yaml_embedded_keyword_directive(run, workdir):
    """CATCHES: rejecting the long `fmt: embedded <name>` form."""
    config(workdir, strict("upper", "tr a-z A-Z", ".sh"))
    result = run(["format", "--stdin-file-path", "ci.yaml"], input="# fmt: embedded upper\nrun: |\n  x\n")
    assert (result.returncode, result.stdout) == (0, b"# fmt: embedded upper\nrun: |\n  X\n")


def test_yaml_embedded_formatter_output_reindented(run, workdir):
    """CATCHES: wrong handling of formatter output that adds lines, blank lines or drops the final newline."""
    config(workdir, strict("grow", "cat; printf '\\n\\nadded line'", ".txt"))
    result = run(["format", "--stdin-file-path", "a.yaml"], input="k:\n  # fmt: grow\n  v: |-\n    one\n")
    assert_golden(transcript(result), __file__, "yaml_grow")


def test_yaml_embedded_directive_on_non_literal(run, workdir):
    """CATCHES: running a formatter on a non-literal scalar instead of reporting the unsupported target."""
    config(workdir, strict("upper", "tr a-z A-Z", ".sh"))
    result = run(["format", "--stdin-file-path", "a.yaml"], input="# fmt: upper\nrun: plain text\n")
    assert_golden(transcript(result), __file__, "yaml_non_literal")


def test_unknown_formatter_directive(run):
    """CATCHES: accepting `fmt: <unknown>` as a formatter target in YAML."""
    result = run(["format", "--stdin-file-path", "a.yaml"], input="# fmt: nosuch\nrun: |\n  x\n")
    assert (result.returncode, result.stderr) == (1, b"a.yaml:1:1: error: unknown embedded formatter: nosuch\n")


def test_python_string_embedded_target(run, workdir):
    """CATCHES: not formatting a marked Python triple-quoted string with the named formatter, or touching other code."""
    config(workdir, strict("upper", "tr a-z A-Z", ".sql"))
    src = "x  =  1\nquery = (\n    # fmt: upper\n    \"\"\"\n    select *\n    from t\n    \"\"\"\n)\n"
    result = run(["format", "--stdin-file-path", "q.py"], input=src)
    assert_golden(transcript(result), __file__, "python_string")


def test_r_string_embedded_target(run, workdir):
    """CATCHES: not formatting a marked R string with the named formatter."""
    config(workdir, strict("upper", "tr a-z A-Z", ".sql"))
    src = "x <- 1\n# fmt: upper\nq <- \"\nselect *\nfrom t\n\"\n"
    result = run(["format", "--stdin-file-path", "q.R"], input=src)
    assert_golden(transcript(result), __file__, "r_string")


def test_formatter_closing_stdin_early_is_fine(run, workdir):
    """CATCHES: failing when a successful formatter does not read its (large) input."""
    config(workdir, strict("early", "exec 0<&-; echo formatted"))
    body = "line of input text\n" * 20000
    result = run(["format", "--stdin-file-path", "doc.md"], input=f"```early\n{body}```\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"```early\nformatted\n```\n", b"")


def test_formatter_output_breaking_fence_is_rejected(run, workdir):
    """CATCHES: accepting formatter output that would close the Markdown fence early."""
    config(workdir, strict("bad", "cat >/dev/null; printf 'x\\n```\\ny\\n'"))
    result = run(["format", "--stdin-file-path", "doc.md"], input="```bad\nx\n```\n")
    assert_golden(transcript(result), __file__, "fence_breaking_output")


def test_formatter_errors_leave_file_unchanged(run, workdir):
    """CATCHES: writing a file whose embedded formatter failed (errors happen before writing)."""
    config(workdir, strict("lint", "echo broken >&2; exit 1"))
    (workdir / "doc.md").write_text("Some   text.\n\n```lint\nx\n```\n")
    result = run(["format", "doc.md"])
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"1 files scanned, 0 formatted, 0 unchanged, 0 skipped, 1 failed\n", b"doc.md:1:1: error: broken\n")
    assert (workdir / "doc.md").read_text() == "Some   text.\n\n```lint\nx\n```\n"


def test_quarto_header_promotion_requires_formatter_success(run, workdir):
    """CATCHES: promoting long Quarto chunk options to #| lines when the delegated formatter is missing, or not
    promoting them when it succeeds."""
    long = "```{python, echo=FALSE, warning=FALSE, message=FALSE, fig.width=10, fig.height=5}\nx=1\n```\n"
    (workdir / "bin").mkdir()
    missing = run(["format", "--stdin-file-path", "d.qmd"], input=long, env_overrides=controlled_path(workdir))
    install(workdir, "ruff", "#!/bin/sh\ncat\n")
    present = run(["format", "--stdin-file-path", "d.qmd"], input=long, env_overrides=controlled_path(workdir))
    assert missing.stdout == long.encode()
    assert_golden(transcript(present), __file__, "quarto_promotion")
