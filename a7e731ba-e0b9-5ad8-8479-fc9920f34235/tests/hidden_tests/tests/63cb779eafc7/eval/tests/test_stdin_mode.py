"""`yamark format --stdin-file-path`: stdin formatting, file-type selection and input errors."""

import pytest

from conftest import assert_golden, transcript


def test_stdin_with_paths_is_rejected(run):
    """CATCHES: accepting PATHS together with --stdin-file-path, or reporting it with exit 1 / clap wording."""
    result = run(["format", "--stdin-file-path", "a.md", "other.md"], input="x\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        2, b"", b"error: --stdin-file-path cannot be used with PATHS\n")


@pytest.mark.parametrize("flag", ["--check", "--diff"])
def test_stdin_with_check_or_diff_is_rejected(flag, run):
    """CATCHES: allowing --check/--diff in stdin mode instead of exiting 2 with the documented message."""
    result = run(["format", flag, "--stdin-file-path", "a.md"], input="x\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        2, b"", b"error: --stdin-file-path cannot be used with --check or --diff\n")


def test_paths_error_takes_precedence_over_check_error(run):
    """CATCHES: checking the --check conflict before the PATHS conflict (the PATHS message comes first)."""
    result = run(["format", "--check", "--stdin-file-path", "a.md", "b.md"], input="x\n")
    assert (result.returncode, result.stderr) == (2, b"error: --stdin-file-path cannot be used with PATHS\n")


@pytest.mark.parametrize("path", ["a.json", "noext", "a.txt", "a.markdown", "dir/.yaml"])
def test_unsupported_stdin_path_is_an_error(path, run):
    """CATCHES: silently echoing or skipping stdin for an unsupported --stdin-file-path (path mode skips such
    files, but stdin mode must fail with 'unsupported file type' and exit 1)."""
    result = run(["format", "--stdin-file-path", path], input="a: 1\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == f"{path}:1:1: error: unsupported file type\n"


@pytest.mark.parametrize("bom", [b"\xff\xfe", b"\xfe\xff"], ids=["le", "be"])
@pytest.mark.parametrize("path", ["a.md", "a.yaml", "a.txt"])
def test_utf16_stdin_is_rejected(bom, path, run):
    """CATCHES: decoding or echoing UTF-16 input instead of rejecting a UTF-16 byte order mark (checked before the
    file type)."""
    result = run(["format", "--stdin-file-path", path], input=bom + b"a\x00:\x00")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == f"{path}:1:1: error: unsupported encoding: UTF-16 BOM\n"


def test_invalid_utf8_stdin_is_rejected(run):
    """CATCHES: lossy decoding of invalid UTF-8 stdin, or a different error text/byte index."""
    result = run(["format", "--stdin-file-path", "docs/a.md"], input=b"ab\xe9\n")
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"docs/a.md:1:1: error: invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 2\n")


def test_truncated_utf8_stdin(run):
    """CATCHES: a different message for an incomplete multi-byte sequence at the end of input."""
    result = run(["format", "--stdin-file-path", "a.yaml"], input=b"a: \xe2\x82")
    assert result.returncode == 1
    assert result.stderr == b"a.yaml:1:1: error: invalid UTF-8: incomplete utf-8 byte sequence from index 3\n"


def test_stdin_path_is_not_read_or_written(run, workdir):
    """CATCHES: reading the --stdin-file-path file instead of stdin, or writing the result back to it."""
    (workdir / "a.yaml").write_text("on_disk:   true\n")
    result = run(["format", "--stdin-file-path", "a.yaml"], input="from_stdin:   1\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"from_stdin: 1\n", b"")
    assert (workdir / "a.yaml").read_text() == "on_disk:   true\n"


@pytest.mark.parametrize("data,expected", [
    (b"", b""),
    (b"\n\n", b"\n\n"),
    (b"# t", b"# t\n"),
    (b"\xef\xbb\xbf", b"\xef\xbb\xbf\n"),
    (b"text \n", b"text\n"),
    (b"text  \n", b"text \\\n"),
], ids=["empty", "blank_lines", "no_final_newline", "bom_only", "trailing_space", "trailing_hard_break"])
def test_markdown_edge_inputs(data, expected, run, workdir):
    """CATCHES: mishandling empty input, input without a final newline, a lone byte order mark or trailing
    spaces in Markdown stdin, or a path-mode --check that disagrees with stdin mode about whether it changes."""
    result = run(["format", "--stdin-file-path", "a.md"], input=data)
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, b"")
    (workdir / "a.md").write_bytes(data)
    check = run(["format", "--check", "a.md"])
    changed = int(expected != data)
    assert (check.returncode, check.stderr.decode()) == (
        changed, f"1 files scanned, {changed} formatted, {1 - changed} unchanged, 0 skipped, 0 failed\n")


@pytest.mark.parametrize("data,expected", [
    (b"", b""),
    (b"a:  1", b"a: 1"),
    (b"a:  1\r\nb:  2\r\n", b"a: 1\r\nb: 2\r\n"),
    (b"a:  1\rb:  2\r", b"a: 1\rb: 2\r"),
    (b"# only a comment\n", b"# only a comment\n"),
    (b"---\na:  1\n...\n", b"---\na: 1\n...\n"),
], ids=["empty", "no_final_newline", "crlf", "cr", "comment", "document_markers"])
def test_yaml_edge_inputs(data, expected, run, workdir):
    """CATCHES: adding a final newline YAML did not have, or converting CRLF/CR line endings, or dropping
    comments and explicit document markers, or a path-mode --check that disagrees with stdin mode."""
    result = run(["format", "--stdin-file-path", "a.yaml"], input=data)
    assert (result.returncode, result.stdout, result.stderr) == (0, expected, b"")
    (workdir / "a.yaml").write_bytes(data)
    check = run(["format", "--check", "a.yaml"])
    changed = int(expected != data)
    assert (check.returncode, check.stderr.decode()) == (
        changed, f"1 files scanned, {changed} formatted, {1 - changed} unchanged, 0 skipped, 0 failed\n")


SAMPLES = {
    "md": "#   Title\n\nSome   *text*  here.\n\n```yaml\nk:   [1,2]\n```\n",
    "qmd": "---\ntitle:   \"Doc\"\n---\n\n```{r}\n#| echo:   false\nx <- 1\n```\n",
    "Rmd": "Text   here.\n\n```{r, echo=FALSE}\nx\n```\n",
    "rmd": "*   item\n*   other\n",
    "yaml": "k:   {a: 1,  b: [x,y]}\n",
    "yml": "- a\n-   b\n",
    "py": "#| label:   fig\n#| echo:   false\nx = 1\n",
    "R": "#| label:   fig\nx <- 1\n",
    "r": "#|   a: [1,2]\nx <- 1\n",
}


@pytest.mark.parametrize("ext", sorted(SAMPLES))
def test_file_type_selected_by_stdin_path(ext, run):
    """CATCHES: selecting the wrong formatter for a --stdin-file-path suffix (Markdown/Quarto/R Markdown,
    YAML, Python and R hashpipe blocks), or formatting surrounding source code."""
    result = run(["format", "--stdin-file-path", f"doc.{ext}"], input=SAMPLES[ext])
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"filetype_{ext}" + ("_capitalized" if ext != ext.lower() else ""))


def test_same_input_differs_by_suffix(run):
    """CATCHES: ignoring the suffix: the same text is Markdown prose for .md but a YAML mapping for .yaml."""
    text = "key:   value\n"
    as_md = run(["format", "--stdin-file-path", "a.md"], input=text)
    as_yaml = run(["format", "--stdin-file-path", "a.yaml"], input=text)
    assert (as_md.stdout, as_yaml.stdout) == (b"key: value\n", b"key: value\n")
    text = "- a\n-  b\n"
    as_md = run(["format", "--stdin-file-path", "a.md"], input=text)
    as_py = run(["format", "--stdin-file-path", "a.py"], input=text)
    assert (as_md.stdout, as_py.stdout) == (b"- a\n- b\n", b"- a\n-  b\n")


DIRECTIVE_ERRORS = {
    "yaml_skip_without_target": ("x.yaml", "a: 1\n# fmt: skip\n", "x.yaml:2:12: error: fmt: skip has no target"),
    "yaml_stray_on": ("x.yaml", "# fmt: on\na: 1\n", "x.yaml:1:1: error: fmt: on without active fmt: off"),
    "yaml_unterminated_off": ("x.yaml", "# fmt: off\na: 1\n", "x.yaml:2:5: error: unterminated fmt: off"),
    "yaml_nested_off": ("x.yaml", "# fmt: off\n# fmt: off\na: 1\n# fmt: on\n", "x.yaml:2:1: error: nested fmt: off"),
    "yaml_unknown_formatter": ("x.yaml", "# fmt: bogus\na: 1\n", "x.yaml:1:1: error: unknown embedded formatter: bogus"),
    "yaml_bad_scope": ("x.yaml", "# fmt: skip scope=everywhere\na: 1\n",
                       "x.yaml:1:1: error: fmt: skip does not support scope=everywhere"),
    "yaml_markdown_on_collection": ("x.yaml", "# fmt: markdown\na: [1, 2]\n",
                                    "x.yaml:2:4: error: fmt: markdown targets a scalar value"),
    "md_invalid_directive": ("x.md", "<!-- fmt: bogus -->\ntext\n", "x.md:1:6: error: invalid fmt directive: bogus"),
    "md_invalid_wrap": ("x.md", "<!-- fmt: wrap=banana -->\ntext\n",
                        "x.md:1:6: error: fmt: wrap must be none, paragraph, sentence, a positive integer, or "
                        "sentence:<positive integer>"),
    "md_on_with_scope": ("x.md", "<!-- fmt: on scope=file -->\ntext\n",
                         "x.md:1:6: error: fmt: on does not support explicit scope"),
    "py_formatter_without_target": ("x.py", "# fmt: python\nx = 1\n",
                                    "x.py:2:6: error: fmt embedded formatter has no target"),
    "py_markdown_without_target": ("x.py", "# fmt: markdown\nx = 1\n", "x.py:2:6: error: fmt: markdown has no target"),
}


@pytest.mark.parametrize("name", sorted(DIRECTIVE_ERRORS))
def test_directive_errors_in_stdin_mode(name, run):
    """CATCHES: accepting invalid or targetless fmt directives, or reporting them without the
    `path:line:column: error:` location, on stdout, or with an exit status other than 1."""
    path, text, message = DIRECTIVE_ERRORS[name]
    result = run(["format", "--stdin-file-path", path], input=text)
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == message + "\n"


def test_stdin_diagnostics_go_to_stderr(run):
    """CATCHES: --diagnostics notes mixed into stdout (which must contain only formatted content) or missing for
    YAML input."""
    result = run(["format", "--diagnostics", "--stdin-file-path", "cfg.yaml"], input="a:   1\nb: [1,2]\n")
    assert result.returncode == 0
    assert result.stdout == b"a: 1\nb: [1, 2]\n"
    assert result.stderr == (b"cfg.yaml:1:1: note: yaml trace: source_scans=1 parse_passes=1 source_lines=2 "
                             b"yaml_scanned_lines=2 yaml_semantic_nodes=7 planned_rendered_scalars=5 "
                             b"planned_rendered_flow_collections=1 planned_rendered_block_flow_collections=0 "
                             b"emitted_bytes=15 emitted_nodes=3\n")


def test_stdin_diagnostics_quiet_for_markdown(run):
    """CATCHES: emitting YAML trace notes for plain Markdown input without YAML regions."""
    result = run(["format", "--diagnostics", "--stdin-file-path", "doc.md"], input="Some   text.\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"Some text.\n", b"")


def test_stdin_diagnostics_with_front_matter(run):
    """CATCHES: missing the trace note for YAML front matter inside Markdown when --diagnostics is given."""
    result = run(["format", "--diagnostics", "--stdin-file-path", "doc.md"],
                 input="---\ntitle:   x\n---\n\nBody   text.\n")
    assert_golden(transcript(result), __file__, "diagnostics_front_matter")


def test_stdin_virtual_path_in_messages_is_verbatim(run):
    """CATCHES: normalizing or absolutizing the --stdin-file-path in error messages."""
    result = run(["format", "--stdin-file-path", "./a/../b/x.yaml"], input="# fmt: on\n")
    assert (result.returncode, result.stderr) == (1, b"./a/../b/x.yaml:1:1: error: fmt: on without active fmt: off\n")


@pytest.mark.parametrize("args,stdin,path", [
    (["format", "--stdin-file-path", "a.md"], "x\n", "a.md"),
    (["git-filter", "clean", "--stdin-filename", "b.md"], "One. Two.\n", "b.md"),
    (["to-yaml", "--stdin-file-path", "c.json"], '{"a": 1}', "c.json"),
], ids=["format", "clean", "to_yaml"])
def test_closed_stdout_reports_write_error(args, stdin, path, workdir, env):
    """CATCHES: panicking or exiting 0 when formatted output cannot be written to stdout; the reference reports
    `<path>:1:1: error: failed to write stdout: ...` and exits 1."""
    from conftest import run_with_closed_stdout
    result = run_with_closed_stdout(args, input=stdin, cwd=workdir, env=env)
    assert result.returncode == 1
    assert result.stderr.decode() == f"{path}:1:1: error: failed to write stdout: Broken pipe (os error 32)\n"
