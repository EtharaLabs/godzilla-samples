"""yamark.toml discovery, precedence, schema validation and error reporting."""

import pytest

from conftest import assert_golden, redact, transcript

CONFIG_ERRORS = {
    "unknown_top_level_key": ("bogus = 1\n", "unknown config key: bogus"),
    "format_not_table": ("format = 1\n", "format config must be a table"),
    "format_unknown_key": ("[format]\nnope = 1\n", "unknown format config key: format.nope"),
    "format_wrap_not_string": ("[format]\nwrap = 3\n", "format.wrap must be a string"),
    "format_wrap_invalid": ("[format]\nwrap = \"bad\"\n",
                            "format.wrap must be none, paragraph, sentence, a positive integer, or "
                            "sentence:<positive integer>"),
    "format_wrap_zero": ("[format]\nwrap = \"0\"\n",
                         "format.wrap must be none, paragraph, sentence, a positive integer, or "
                         "sentence:<positive integer>"),
    "format_compact_not_bool": ("[format]\ncompact = \"yes\"\n", "format.compact must be a boolean"),
    "format_table_widths_not_string": ("[format]\ntable_widths = 1\n", "format.table_widths must be a string"),
    "format_table_widths_invalid": ("[format]\ntable_widths = \"x\"\n",
                                    "format.table_widths must be fit or preserve"),
    "format_rule_invalid": ("[format]\nmarkdown_horizontal_rule = \"___\"\n",
                            "format.markdown_horizontal_rule must be \"---\" or \"***\""),
    "format_rule_not_string": ("[format]\nmarkdown_horizontal_rule = 1\n",
                               "format.markdown_horizontal_rule must be a string"),
    "template_not_table": ("template = 1\n", "template must be a table"),
    "template_unknown_key": ("[template]\nx = 1\n", "unknown template config key: template.x"),
    "template_add_not_array": ("[template]\nadd_delimiters = 1\n", "template.add_delimiters must be an array"),
    "template_replace_not_array": ("[template]\nreplace_delimiters = \"x\"\n",
                                   "template.replace_delimiters must be an array"),
    "template_entry_not_table": ("[template]\nadd_delimiters = [1]\n",
                                 "template.add_delimiters entries must be tables"),
    "template_missing_close": ("[template]\nadd_delimiters = [{open=\"a\"}]\n",
                               "template.add_delimiters.close is required"),
    "template_missing_open": ("[template]\nadd_delimiters = [{close=\"a\"}]\n",
                              "template.add_delimiters.open is required"),
    "template_open_not_string": ("[template]\nadd_delimiters = [{open=1, close=\"b\"}]\n",
                                 "template.add_delimiters.open is required"),
    "template_empty_open": ("[template]\nadd_delimiters = [{open=\"\", close=\"b\"}]\n",
                            "template.add_delimiters.open must not be empty"),
    "template_empty_close": ("[template]\nreplace_delimiters = [{open=\"a\", close=\"\"}]\n",
                             "template.replace_delimiters.close must not be empty"),
    "template_extra_key": ("[template]\nadd_delimiters = [{open=\"a\", close=\"b\", x=1}]\n",
                           "unknown template delimiter key: template.add_delimiters.x"),
    "embedded_not_table": ("embedded = 1\n", "embedded config must be a table"),
    "embedded_untrimmed_name": ("[embedded]\n\" py\" = {formatter=\"ruff\"}\n",
                                "embedded formatter names must be non-empty and trimmed"),
    "embedded_empty_name": ("[embedded]\n\"\" = {formatter=\"ruff\"}\n",
                            "embedded formatter names must be non-empty and trimmed"),
    "embedded_reserved_skip": ("[embedded.skip]\nformatter=\"ruff\"\n", "reserved fmt directive name: skip"),
    "embedded_reserved_skip_file": ("[embedded.\"skip file\"]\nformatter=\"ruff\"\n",
                                    "reserved fmt directive name: skip file"),
    "embedded_reserved_off": ("[embedded.off]\nformatter=\"ruff\"\n", "reserved fmt directive name: off"),
    "embedded_reserved_on": ("[embedded.on]\nformatter=\"ruff\"\n", "reserved fmt directive name: on"),
    "embedded_reserved_table": ("[embedded.table]\nformatter=\"ruff\"\n", "reserved fmt directive name: table"),
    "embedded_entry_not_table": ("[embedded]\npy = 1\n", "embedded formatter entries must be tables"),
    "embedded_missing_formatter": ("[embedded.py]\nother = 1\n", "embedded formatter entries must contain formatter"),
    "embedded_extra_entry_key": ("[embedded.py]\nformatter = \"ruff\"\nx = 1\n",
                                 "unknown embedded formatter entry key: x"),
    "embedded_unknown_shorthand": ("[embedded.py]\nformatter = \"black\"\n",
                                   "unknown embedded formatter shorthand: black"),
    "embedded_formatter_wrong_type": ("[embedded.py]\nformatter = 1\n",
                                      "embedded formatter must be a string or table"),
    "embedded_formatter_extra_key": ("[embedded.py]\nformatter = {command=[\"a\",\"{path}\"], path_suffix=\".py\", z=1}\n",
                                     "unknown embedded formatter key: z"),
    "embedded_missing_command": ("[embedded.py]\nformatter = {path_suffix=\".py\"}\n",
                                 "missing embedded formatter command"),
    "embedded_command_string": ("[embedded.py]\nformatter = {command=\"x {path}\", path_suffix=\".py\"}\n",
                                "missing embedded formatter command"),
    "embedded_command_item_type": ("[embedded.py]\nformatter = {command=[1], path_suffix=\".py\"}\n",
                                   "embedded formatter command entries must be strings"),
    "embedded_command_empty": ("[embedded.py]\nformatter = {command=[], path_suffix=\".py\"}\n",
                               "embedded formatter command must not be empty"),
    "embedded_command_without_path": ("[embedded.py]\nformatter = {command=[\"fmt\"], path_suffix=\".py\"}\n",
                                      "embedded formatter command must contain {path} as an argv item"),
    "embedded_command_embedded_path": (
        "[embedded.py]\nformatter = {command=[\"fmt\",\"--file={path}\", \"{path}\"], path_suffix=\".py\"}\n",
        "{path} must be a complete argv item"),
    "embedded_missing_suffix": ("[embedded.py]\nformatter = {command=[\"fmt\",\"{path}\"]}\n",
                                "missing embedded formatter path_suffix"),
    "embedded_suffix_not_string": ("[embedded.py]\nformatter = {command=[\"fmt\",\"{path}\"], path_suffix=1}\n",
                                   "embedded formatter path_suffix must be a string"),
    "embedded_suffix_empty": ("[embedded.py]\nformatter = {command=[\"fmt\",\"{path}\"], path_suffix=\"\"}\n",
                              "embedded formatter path_suffix must not be empty"),
    "paths_not_table": ("paths = 1\n", "paths config must be a table"),
    "paths_empty_key": ("[paths]\n\"\" = {}\n", "path config keys must not be empty"),
    "paths_absolute_key": ("[paths.\"/abs\"]\n", "path config keys must be relative and must not contain .."),
    "paths_parent_key": ("[paths.\"../up\"]\n", "path config keys must be relative and must not contain .."),
    "paths_inner_parent_key": ("[paths.\"a/../b\"]\n", "path config keys must be relative and must not contain .."),
    "paths_value_not_table": ("[paths]\ndocs = 1\n", "paths.docs must be a table"),
    "paths_unknown_key": ("[paths.docs]\nx = 1\n", "unknown path config key: paths.docs.x"),
    "paths_nested_key_context": ("[paths.\"docs/sub\"]\nx = 1\n", "unknown path config key: paths.docs.sub.x"),
    "paths_backslash_key_context": ("[paths.\"docs\\\\win\"]\nx = 1\n", "unknown path config key: paths.docs.win.x"),
    "paths_template_not_table": ("[paths.docs]\ntemplate = 1\n", "paths.docs.template must be a table"),
    "paths_template_unknown_key": ("[paths.docs.template]\nx = 1\n",
                                   "unknown path template config key: paths.docs.template.x"),
    "paths_template_missing_close": ("[paths.docs.template]\nadd_delimiters = [{open=\"<<\"}]\n",
                                     "paths.docs.template.add_delimiters.close is required"),
    "paths_template_replace_not_array": ("[paths.docs.template]\nreplace_delimiters = 2\n",
                                         "paths.docs.template.replace_delimiters must be an array"),
    "paths_embedded_not_table": ("[paths.docs]\nembedded_markdown = 1\n",
                                 "paths.docs.embedded_markdown must be a table"),
    "paths_embedded_unknown_key": ("[paths.docs.embedded_markdown]\nx = 1\n",
                                   "unknown path config key: paths.docs.embedded_markdown.x"),
    "paths_embedded_template_not_table": ("[paths.docs.embedded_markdown]\ntemplate = 1\n",
                                          "paths.docs.embedded_markdown.template must be a table"),
    "paths_embedded_template_unknown_key": (
        "[paths.docs.embedded_markdown.template]\nx = 1\n",
        "unknown path template config key: paths.docs.embedded_markdown.template.x"),
    "paths_embedded_empty_close": (
        "[paths.docs.embedded_markdown.template]\nadd_delimiters = [{open=\"[[\", close=\"\"}]\n",
        "paths.docs.embedded_markdown.template.add_delimiters.close must not be empty"),
    "paths_embedded_missing_open": (
        "[paths.docs.embedded_markdown.template]\nreplace_delimiters = [{close=\"]]\"}]\n",
        "paths.docs.embedded_markdown.template.replace_delimiters.open is required"),
}


@pytest.mark.parametrize("name", sorted(CONFIG_ERRORS))
def test_invalid_config_with_explicit_path(name, run, workdir):
    """CATCHES: accepting unknown keys or wrongly typed values in yamark.toml, validating a different schema
    than documented ([format], [template], [embedded], [paths]), or reporting the error with different
    wording, a different `<config path>:1:1: error:` prefix, the wrong stream, or an exit status other than 1."""
    text, message = CONFIG_ERRORS[name]
    (workdir / "custom.toml").write_text(text)
    result = run(["format", "--stdin-file-path", "x.yaml", "--config", "custom.toml"], input="a:  1\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == f"custom.toml:1:1: error: {message}\n"


@pytest.mark.parametrize("name", ["unknown_top_level_key", "format_wrap_invalid", "embedded_reserved_table",
                                  "paths_parent_key"])
def test_invalid_discovered_config_reports_absolute_path(name, run, workdir):
    """CATCHES: discovered configuration errors that are ignored, or reported with a relative or different path
    (the reference reports the absolute path of the discovered yamark.toml)."""
    text, message = CONFIG_ERRORS[name]
    (workdir / "yamark.toml").write_text(text)
    result = run(["format", "--stdin-file-path", "x.yaml"], input="a:  1\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert redact(result.stderr.decode(), ("{{workdir}}", workdir)) == \
        f"{{{{workdir}}}}/yamark.toml:1:1: error: {message}\n"


def test_toml_syntax_error(run, workdir):
    """CATCHES: invalid TOML not being rejected, or a parse error message without the line/column report."""
    (workdir / "yamark.toml").write_text("[format\n")
    result = run(["format", "--stdin-file-path", "x.yaml", "--config", "yamark.toml"], input="a: 1\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr == (b"yamark.toml:1:1: error: invalid yamark.toml: TOML parse error at line 1, column 8\n"
                             b"  |\n1 | [format\n  |        ^\nunclosed table, expected `]`\n\n")


def test_toml_duplicate_key_error(run, workdir):
    """CATCHES: silently accepting duplicate TOML keys instead of reporting the TOML parse error."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = \"none\"\nwrap = \"sentence\"\n")
    result = run(["format", "--stdin-file-path", "x.md", "--config", "yamark.toml"], input="a\n")
    assert_golden(transcript(result), __file__, "toml_duplicate_key")


@pytest.mark.parametrize("target,message", [
    ("nope.toml", "failed to read config: No such file or directory (os error 2)"),
    ("cdir", "failed to read config: Is a directory (os error 21)"),
    ("latin1.toml", "failed to read config: stream did not contain valid UTF-8"),
])
def test_unreadable_explicit_config(target, message, run, workdir):
    """CATCHES: a missing, directory or non-UTF-8 --config path being ignored instead of failing with exit 1
    and the read error attached to the given config path."""
    (workdir / "cdir").mkdir()
    (workdir / "latin1.toml").write_bytes(b"# \xff\n")
    result = run(["format", "--stdin-file-path", "x.yaml", "--config", target], input="a: 1\n")
    assert (result.returncode, result.stdout) == (1, b"")
    assert result.stderr.decode() == f"{target}:1:1: error: {message}\n"


MD = ("Intro sentence. Next sentence.\n\n***\n\n- - -\n\n___\n\n"
      "Keep <<  render  >> and {{ x   y }} here.\n")


def test_format_wrap_from_config(run, workdir):
    """CATCHES: [format].wrap being ignored for Markdown, or markdown_horizontal_rule not choosing the marker
    emitted for every normalized thematic break."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = \"sentence\"\nmarkdown_horizontal_rule = \"***\"\n")
    result = run(["format", "--stdin-file-path", "a.md"], input=MD)
    assert result.returncode == 0
    assert result.stdout == (b"Intro sentence.\nNext sentence.\n\n***\n\n***\n\n***\n\n"
                             b"Keep <<  render  >> and {{ x   y }} here.\n")


def test_cli_wrap_overrides_config_wrap(run, workdir):
    """CATCHES: an explicit --wrap losing to [format].wrap (the command line must win)."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = \"sentence\"\n")
    result = run(["format", "--stdin-file-path", "a.md", "--wrap", "none"], input=MD)
    assert result.returncode == 0
    assert result.stdout.startswith(b"Intro sentence. Next sentence.\n\n---\n")


def test_default_wrap_flag_value_does_not_override_config(run, workdir):
    """CATCHES: treating the default --wrap value (72) as explicit, which would override [format].wrap; only a
    --wrap typed on the command line overrides the config, even when it equals the default."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = \"sentence\"\n")
    implicit = run(["format", "--stdin-file-path", "a.md"], input="One here. Two here.\n")
    explicit = run(["format", "--stdin-file-path", "a.md", "--wrap", "72"], input="One here. Two here.\n")
    assert (implicit.stdout, explicit.stdout) == (b"One here.\nTwo here.\n", b"One here. Two here.\n")


def test_dash_horizontal_rule_config(run, workdir):
    """CATCHES: markdown_horizontal_rule = \"---\" not normalizing *** and ___ breaks to ---."""
    (workdir / "yamark.toml").write_text("[format]\nmarkdown_horizontal_rule = \"---\"\n")
    result = run(["format", "--stdin-file-path", "a.md"], input="a\n\n***\n\n* * *\n\n___\n")
    assert result.stdout == b"a\n\n---\n\n---\n\n---\n"


TABLE = "| a | b |\n|---|:-:|\n| long cell | x |\n"
TABLE_DOC = "Intro   text.\n\n" + TABLE


@pytest.mark.parametrize("config,flag", [("fit", None), ("preserve", None), ("preserve", "fit"), ("fit", "preserve")])
def test_table_widths_config_and_flag(config, flag, run, workdir):
    """CATCHES: [format].table_widths being ignored, or an explicit --table-widths not overriding it."""
    (workdir / "yamark.toml").write_text(f"[format]\ntable_widths = \"{config}\"\n")
    args = ["format", "--stdin-file-path", "a.md"] + (["--table-widths", flag] if flag else [])
    result = run(args, input=TABLE_DOC)
    effective = flag or config
    expected = "Intro text.\n\n" + (TABLE if effective == "preserve" else "| a         |   b   |\n| --------- | :---: |\n| long cell |   x   |\n")
    assert (result.returncode, result.stdout.decode()) == (0, expected)


YAML = "a:\n  -   1\n  - 2\nb:\n    c:  d\n"


@pytest.mark.parametrize("config,flag,expected", [
    ("true", False, "a: [1, 2]\nb: {c: d}\n"),
    ("false", False, "a:\n  - 1\n  - 2\nb:\n  c: d\n"),
    ("false", True, "a: [1, 2]\nb: {c: d}\n"),
    ("true", True, "a: [1, 2]\nb: {c: d}\n"),
])
def test_compact_config_and_flag(config, flag, expected, run, workdir):
    """CATCHES: [format].compact not enabling compaction, or compact = false disabling an explicit --compact
    (the flag still enables compact mode when the config says false)."""
    (workdir / "yamark.toml").write_text(f"[format]\ncompact = {config}\n")
    args = ["format", "--stdin-file-path", "a.yaml"] + (["--compact"] if flag else [])
    result = run(args, input=YAML)
    assert (result.returncode, result.stdout.decode(), result.stderr) == (0, expected, b"")


def test_nearest_config_wins_without_merging(run, workdir):
    """CATCHES: merging ancestor configs or using the outermost one: only the nearest yamark.toml applies, so the
    ancestor's wrap=sentence must not leak into a directory whose own config only sets templates."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = \"sentence\"\n")
    (workdir / "docs" / "deep").mkdir(parents=True)
    (workdir / "docs" / "yamark.toml").write_text("[template]\nadd_delimiters = [{open=\"<<\", close=\">>\"}]\n")
    nested = run(["format", "--stdin-file-path", "docs/deep/a.md", "--wrap", "20"], input=MD)
    top = run(["format", "--stdin-file-path", "a.md", "--wrap", "20"], input=MD)
    assert nested.stdout == (b"Intro sentence. Next\nsentence.\n\n---\n\n---\n\n---\n\nKeep <<  render  >>\n"
                             b"and {{ x   y }}\nhere.\n")
    assert top.stdout == (b"Intro sentence. Next\nsentence.\n\n---\n\n---\n\n---\n\n"
                          b"Keep <<  render  >> and {{ x   y }} here.\n")


def test_explicit_config_replaces_discovery(run, workdir):
    """CATCHES: --config being merged with, or overridden by, a discovered yamark.toml."""
    (workdir / "docs").mkdir()
    (workdir / "docs" / "yamark.toml").write_text("bogus = 1\n")
    (workdir / "explicit.toml").write_text("[format]\nwrap = \"sentence\"\n")
    result = run(["format", "--stdin-file-path", "docs/a.md", "--config", "explicit.toml"], input="A b. C d.\n")
    assert (result.returncode, result.stdout, result.stderr) == (0, b"A b.\nC d.\n", b"")


def test_stdin_config_discovery_uses_virtual_path_directory(run, workdir):
    """CATCHES: discovering config from the working directory instead of the --stdin-file-path directory (the
    virtual path need not exist)."""
    (workdir / "a" / "b").mkdir(parents=True)
    (workdir / "a" / "yamark.toml").write_text("[format]\nwrap = \"sentence\"\n")
    inside = run(["format", "--stdin-file-path", "a/b/missing/doc.md"], input="A b. C d.\n")
    outside = run(["format", "--stdin-file-path", "doc.md"], input="A b. C d.\n")
    assert (inside.stdout, outside.stdout) == (b"A b.\nC d.\n", b"A b. C d.\n")


def test_stdin_config_discovery_with_parent_components(run, workdir):
    """CATCHES: failing to walk past the working directory for relative virtual paths that climb with `..`."""
    (workdir / "proj" / "sub").mkdir(parents=True)
    (workdir / "proj" / "yamark.toml").write_text("[format]\nwrap = \"sentence\"\n")
    result = run(["format", "--stdin-file-path", "../doc.md"], input="A b. C d.\n", cwd=workdir / "proj" / "sub")
    assert result.stdout == b"A b.\nC d.\n"


TEMPLATE_YAML = "a: \"<< x >>\"\nb: \"x [[ y ]]\"\nc: \"<% z %>\"\nd: \"w {{ v }}\"\n"


@pytest.mark.parametrize("name,config", [
    ("defaults", ""),
    ("add", "[template]\nadd_delimiters = [{open=\"<<\", close=\">>\"}]\n"),
    ("replace", "[template]\nreplace_delimiters = [{open=\"[[\", close=\"]]\"}]\n"),
    ("replace_then_add", "[template]\nreplace_delimiters = [{open=\"[[\", close=\"]]\"}]\n"
                         "add_delimiters = [{open=\"<<\", close=\">>\"}]\n"),
])
def test_template_delimiters_config(name, config, run, workdir):
    """CATCHES: [template] add_delimiters/replace_delimiters not changing which quoted YAML scalars are treated
    as templates (templated scalars keep their quotes, others are simplified), or replace not discarding the
    default {{ }} delimiters."""
    (workdir / "yamark.toml").write_text(config)
    result = run(["format", "--stdin-file-path", "a.yaml"], input=TEMPLATE_YAML)
    assert result.returncode == 0
    assert_golden(transcript(result), __file__, f"template_{name}")


def test_path_scoped_template_layers(run, workdir):
    """CATCHES: [paths.<dir>.template] layers applying outside their directory, not applying inside it, or deeper
    layers not being applied after shallower ones (replace discards earlier layers)."""
    (workdir / "yamark.toml").write_text(
        "[paths.docs.template]\nadd_delimiters = [{open=\"<<\", close=\">>\"}]\n"
        "[paths.\"docs/deep\".template]\nreplace_delimiters = [{open=\"[[\", close=\"]]\"}]\n")
    outputs = {}
    for path in ["top.yaml", "docs/a.yaml", "docs/deep/a.yaml", "docsx/a.yaml"]:
        result = run(["format", "--stdin-file-path", path], input=TEMPLATE_YAML)
        outputs[path] = result.stdout.decode()
    assert outputs == {
        "top.yaml": "a: << x >>\nb: x [[ y ]]\nc: \"<% z %>\"\nd: \"w {{ v }}\"\n",
        "docs/a.yaml": "a: \"<< x >>\"\nb: x [[ y ]]\nc: \"<% z %>\"\nd: \"w {{ v }}\"\n",
        "docs/deep/a.yaml": "a: << x >>\nb: \"x [[ y ]]\"\nc: <% z %>\nd: w {{ v }}\n",
        "docsx/a.yaml": "a: << x >>\nb: x [[ y ]]\nc: \"<% z %>\"\nd: \"w {{ v }}\"\n",
    }


def test_explicit_config_path_layers_are_relative_to_config_dir(run, workdir):
    """CATCHES: resolving [paths] keys relative to the working directory instead of the directory that contains
    the explicit --config file."""
    (workdir / "conf").mkdir()
    (workdir / "conf" / "y.toml").write_text("[paths.docs.template]\nadd_delimiters = [{open=\"<<\", close=\">>\"}]\n")
    in_conf = run(["format", "--stdin-file-path", "conf/docs/a.yaml", "--config", "conf/y.toml"], input=TEMPLATE_YAML)
    in_cwd = run(["format", "--stdin-file-path", "docs/a.yaml", "--config", "conf/y.toml"], input=TEMPLATE_YAML)
    assert in_conf.stdout.startswith(b"a: \"<< x >>\"\n")
    assert in_cwd.stdout.startswith(b"a: << x >>\n")


def test_config_error_aborts_directory_run_without_writing(run, workdir):
    """CATCHES: continuing (or writing earlier files) after a yamark.toml discovered during traversal fails to
    parse; the reference reports only the config error, prints no summary and exits 1."""
    (workdir / "a").mkdir()
    (workdir / "b").mkdir()
    (workdir / "a" / "one.yaml").write_text("x:  1\n")
    (workdir / "b" / "two.yaml").write_text("x:  1\n")
    (workdir / "b" / "yamark.toml").write_text("bogus = 1\n")
    result = run(["format"])
    assert (result.returncode, result.stdout) == (1, b"")
    assert redact(result.stderr.decode(), ("{{workdir}}", workdir)) == \
        "{{workdir}}/b/yamark.toml:1:1: error: unknown config key: bogus\n"
    assert (workdir / "a" / "one.yaml").read_text() == "x:  1\n"


def test_explicit_config_error_in_path_mode(run, workdir):
    """CATCHES: an invalid explicit --config being ignored in directory mode."""
    (workdir / "a").mkdir()
    (workdir / "a" / "one.yaml").write_text("x:  1\n")
    (workdir / "bad.toml").write_text("[format]\ncompact = 1\n")
    result = run(["format", "--config", "bad.toml", "a"])
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b"", b"bad.toml:1:1: error: format.compact must be a boolean\n")
    assert (workdir / "a" / "one.yaml").read_text() == "x:  1\n"


def test_unsupported_files_do_not_load_config(run, workdir):
    """CATCHES: loading (and failing on) a broken yamark.toml for files that are skipped as unsupported."""
    (workdir / "yamark.toml").write_text("bogus = 1\n")
    (workdir / "notes.txt").write_text("plain\n")
    result = run(["format", "--check", "notes.txt"])
    assert (result.returncode, result.stdout, result.stderr) == (
        0, b"", b"1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n")


def test_per_directory_configs_in_one_run(run, workdir):
    """CATCHES: using one discovered config for every file in a directory run instead of each file's nearest."""
    for sub, wrap in [("s", "sentence"), ("n", "none")]:
        (workdir / sub).mkdir()
        (workdir / sub / "yamark.toml").write_text(f"[format]\nwrap = \"{wrap}\"\n")
        (workdir / sub / "doc.md").write_text("One here. Two here.\n")
    result = run(["format", "s", "n"])
    assert (result.returncode, result.stdout) == (0, b"4 files scanned, 1 formatted, 1 unchanged, 2 skipped, 0 failed\n")
    assert (workdir / "s" / "doc.md").read_text() == "One here.\nTwo here.\n"
    assert (workdir / "n" / "doc.md").read_text() == "One here. Two here.\n"


def test_path_scoped_embedded_markdown_template(run, workdir):
    """CATCHES: [paths.<dir>.embedded_markdown.template] not replacing the delimiters used for Markdown embedded in
    source strings under that directory (a string containing an active template is preserved, others wrap)."""
    (workdir / "yamark.toml").write_text(
        "[paths.\"prompts\".embedded_markdown.template]\nreplace_delimiters = [{open=\"[[\", close=\"]]\"}]\n")
    outputs = []
    for path, token in [("prompts/a.py", "{{ this one }}"), ("prompts/b.py", "[[ this one ]]"),
                        ("other/a.py", "{{ this one }}"), ("other/b.py", "[[ this one ]]")]:
        src = f"# fmt: markdown\nx = \"\"\"\nKeep {token} and that one words.\n\"\"\"\n"
        result = run(["format", "--stdin-file-path", path, "--wrap", "12"], input=src)
        outputs.append(result.stdout.decode())
    assert outputs == [
        "# fmt: markdown\nx = \"\"\"\nKeep\n{{ this one }}\nand that one\nwords.\n\"\"\"\n",
        "# fmt: markdown\nx = \"\"\"\nKeep [[ this one ]] and that one words.\n\"\"\"\n",
        "# fmt: markdown\nx = \"\"\"\nKeep {{ this one }} and that one words.\n\"\"\"\n",
        "# fmt: markdown\nx = \"\"\"\nKeep\n[[ this one ]]\nand that one\nwords.\n\"\"\"\n",
    ]


def test_path_layers_match_absolute_and_dotted_virtual_paths(run, workdir):
    """CATCHES: path-scoped layers not matching absolute --stdin-file-path values or virtual paths that contain
    `.`/`..` components and do not exist on disk."""
    (workdir / "yamark.toml").write_text("[paths.docs.template]\nadd_delimiters = [{open=\"<<\", close=\">>\"}]\n")
    absolute = run(["format", "--stdin-file-path", str(workdir / "docs" / "a.yaml")], input=TEMPLATE_YAML)
    dotted = run(["format", "--stdin-file-path", "other/../docs/./missing/a.yaml"], input=TEMPLATE_YAML)
    escaped = run(["format", "--stdin-file-path", "docs/../other/a.yaml"], input=TEMPLATE_YAML)
    assert absolute.stdout.startswith(b"a: \"<< x >>\"\n")
    assert dotted.stdout.startswith(b"a: \"<< x >>\"\n")
    assert escaped.stdout.startswith(b"a: << x >>\n")
