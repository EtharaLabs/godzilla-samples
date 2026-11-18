"""`yamark.toml` schema validation and path-scoped template layers.

Unknown keys and invalid values are errors reported against the config file;
`[paths."<dir>"]` layers add or replace template delimiters for matching files,
from the shallowest path to the deepest, and `embedded_markdown` layers apply only
to Markdown embedded in Python/R sources.
"""

import pytest

from conftest import format_both_ways, outcome

MD_INPUT = "A paragraph with << keep   these   spaces >> and [[ other   spacing ]] inside it.\n"

INVALID_CONFIGS = {
    "toml_syntax": "[format\n",
    "unknown_top_level_key": "[colors]\nred = 1\n",
    "template_not_table": "template = 1\n",
    "template_unknown_key": "[template]\nmore_delimiters = []\n",
    "template_replace_not_array": "[template]\nreplace_delimiters = 1\n",
    "template_entry_not_table": "[template]\nadd_delimiters = [1]\n",
    "template_entry_unknown_key": "[template]\nadd_delimiters = [{ open = '<<', close = '>>', style = 'x' }]\n",
    "template_missing_open": "[template]\nadd_delimiters = [{ close = '>>' }]\n",
    "template_missing_close": "[template]\nadd_delimiters = [{ open = '<<' }]\n",
    "template_open_not_string": "[template]\nadd_delimiters = [{ open = 1, close = '>>' }]\n",
    "template_empty_open": "[template]\nreplace_delimiters = [{ open = '', close = '>>' }]\n",
    "template_empty_close": "[template]\nadd_delimiters = [{ open = '<<', close = '' }]\n",
    "format_not_table": "format = 'fast'\n",
    "format_unknown_key": "[format]\nwidth = 80\n",
    "format_compact_not_bool": "[format]\ncompact = 'yes'\n",
    "format_wrap_not_string": "[format]\nwrap = 72\n",
    "format_wrap_invalid": "[format]\nwrap = 'wide'\n",
    "format_wrap_zero": "[format]\nwrap = '0'\n",
    "format_wrap_sentence_zero": "[format]\nwrap = 'sentence:0'\n",
    "format_table_widths_not_string": "[format]\ntable_widths = true\n",
    "format_table_widths_invalid": "[format]\ntable_widths = 'auto'\n",
    "format_rule_not_string": "[format]\nmarkdown_horizontal_rule = 3\n",
    "format_rule_invalid": "[format]\nmarkdown_horizontal_rule = '___'\n",
    "embedded_not_table": "embedded = 'ruff'\n",
    "embedded_name_untrimmed": "[embedded.' py']\nformatter = 'ruff'\n",
    "embedded_name_empty": "[embedded.'']\nformatter = 'ruff'\n",
    "embedded_reserved_skip": "[embedded.skip]\nformatter = 'ruff'\n",
    "embedded_reserved_skip_file": "[embedded.'skip file']\nformatter = 'ruff'\n",
    "embedded_reserved_table": "[embedded.table]\nformatter = 'ruff'\n",
    "embedded_reserved_on": "[embedded.on]\nformatter = 'ruff'\n",
    "embedded_entry_not_table": "[embedded]\npy = 'ruff'\n",
    "embedded_missing_formatter": "[embedded.py]\n",
    "embedded_extra_entry_key": "[embedded.py]\nformatter = 'ruff'\nenabled = true\n",
    "embedded_unknown_shorthand": "[embedded.py]\nformatter = 'black'\n",
    "embedded_formatter_wrong_type": "[embedded.py]\nformatter = 1\n",
    "embedded_formatter_unknown_key": "[embedded.py]\nformatter = { command = ['x', '{path}'], path_suffix = '.py', timeout = 5 }\n",
    "embedded_missing_command": "[embedded.py]\nformatter = { path_suffix = '.py' }\n",
    "embedded_command_not_array": "[embedded.py]\nformatter = { command = 'x {path}', path_suffix = '.py' }\n",
    "embedded_command_entry_not_string": "[embedded.py]\nformatter = { command = ['x', 1, '{path}'], path_suffix = '.py' }\n",
    "embedded_command_empty": "[embedded.py]\nformatter = { command = [], path_suffix = '.py' }\n",
    "embedded_command_without_path": "[embedded.py]\nformatter = { command = ['x', '-'], path_suffix = '.py' }\n",
    "embedded_path_inside_argument": "[embedded.py]\nformatter = { command = ['x', '--file={path}', '{path}'], path_suffix = '.py' }\n",
    "embedded_missing_suffix": "[embedded.py]\nformatter = { command = ['x', '{path}'] }\n",
    "embedded_suffix_not_string": "[embedded.py]\nformatter = { command = ['x', '{path}'], path_suffix = 1 }\n",
    "embedded_suffix_empty": "[embedded.py]\nformatter = { command = ['x', '{path}'], path_suffix = '' }\n",
    "paths_not_table": "paths = 'docs'\n",
    "paths_empty_key": "[paths.'']\n",
    "paths_absolute_key": "[paths.'/etc']\n",
    "paths_parent_key": "[paths.'docs/../..']\n",
    "paths_entry_not_table": "[paths]\ndocs = 1\n",
    "paths_unknown_key": "[paths.docs]\nformat = { wrap = 'none' }\n",
    "paths_template_not_table": "[paths.docs]\ntemplate = 1\n",
    "paths_template_unknown_key": "[paths.'docs/api'.template]\ndelimiters = []\n",
    "paths_template_replace_invalid": "[paths.docs.template]\nreplace_delimiters = [{ open = '' , close = '>>' }]\n",
    "paths_template_add_invalid": "[paths.docs.template]\nadd_delimiters = [{ open = '<<' }]\n",
    "paths_embedded_not_table": "[paths.docs]\nembedded_markdown = 1\n",
    "paths_embedded_unknown_key": "[paths.docs.embedded_markdown]\nwrap = 'none'\n",
    "paths_embedded_template_not_table": "[paths.docs.embedded_markdown]\ntemplate = []\n",
    "paths_embedded_template_unknown_key": "[paths.docs.embedded_markdown.template]\nopen = '<<'\n",
    "paths_embedded_template_replace_invalid": "[paths.docs.embedded_markdown.template]\nreplace_delimiters = 'x'\n",
    "paths_embedded_template_add_invalid": "[paths.docs.embedded_markdown.template]\nadd_delimiters = [{ open = '<<', close = 1 }]\n",
}


@pytest.mark.parametrize("name", sorted(INVALID_CONFIGS))
def test_invalid_config_is_reported(name, run, workdir, golden):
    """CATCHES: accepting unknown keys or wrongly typed values in yamark.toml, or reporting a
    different message, location, or exit status for each schema violation."""
    (workdir / "bad.toml").write_text(INVALID_CONFIGS[name])
    result = run(["format", "--stdin-file-path", "input.md", "--config", "bad.toml"], input=MD_INPUT)
    assert outcome(result) == golden(f"invalid_{name}")


def test_missing_explicit_config(run, golden):
    """CATCHES: silently ignoring a `--config` path that does not exist."""
    result = run(["format", "--stdin-file-path", "input.md", "--config", "nope/yamark.toml"], input=MD_INPUT)
    assert outcome(result) == golden("missing_explicit_config")


def test_explicit_config_is_a_directory(run, workdir, golden):
    """CATCHES: treating a directory passed to `--config` as an empty config."""
    (workdir / "confdir").mkdir()
    result = run(["format", "--stdin-file-path", "input.md", "--config", "confdir"], input=MD_INPUT)
    assert outcome(result) == golden("config_is_directory")


def test_invalid_discovered_config_in_path_mode(run, workdir, golden):
    """CATCHES: path-mode formatting that skips a broken discovered yamark.toml instead of
    failing the file and leaving it unchanged."""
    (workdir / "docs").mkdir()
    (workdir / "docs" / "yamark.toml").write_text("[format]\ncompact = 1\n")
    (workdir / "docs" / "a.yaml").write_text("a:   1\n")
    result = run(["format", "docs/a.yaml"])
    observed = outcome(result, workdir, ["docs/a.yaml"])
    observed["stderr"] = observed["stderr"].replace(str(workdir), "<workdir>")
    assert observed == golden("invalid_discovered_path_mode")


def _write_layers(workdir):
    (workdir / "yamark.toml").write_text(
        "[template]\n"
        "replace_delimiters = [{ open = '((', close = '))' }]\n"
        "add_delimiters = [{ open = '<<', close = '>>' }]\n"
        "[paths.docs.template]\n"
        "add_delimiters = [{ open = '[[', close = ']]' }]\n"
        "[paths.'docs/api'.template]\n"
        "replace_delimiters = [{ open = '{{', close = '}}' }]\n"
        "[paths.src.embedded_markdown.template]\n"
        "replace_delimiters = [{ open = '%%', close = '%%' }]\n"
        "add_delimiters = [{ open = '<<', close = '>>' }]\n"
    )


LAYER_TEXT = "Top (( a   b )) then << c   d >> then [[ e   f ]] then {{ g   h }} end of the line here.\n"


@pytest.mark.parametrize(
    "path",
    ["top.md", "docs/guide.md", "docs/api/ref.md", "docs/../docs/new.md", "./docs/api/../api/x.md", "other/x.md"],
)
def test_path_template_layers(path, run, workdir, golden):
    """CATCHES: applying path layers in the wrong order, letting a deeper `replace_delimiters`
    keep earlier delimiters, failing to normalise `.`/`..` in a not-yet-existing stdin path,
    or applying `docs` layers to files outside it."""
    _write_layers(workdir)
    observed = format_both_ways(run, workdir, path, LAYER_TEXT, "--wrap", "40")
    assert observed == golden("layers_" + path.replace("/", "_").replace(".", "-"))


def test_embedded_markdown_layer_applies_to_python_strings(run, workdir, golden):
    """CATCHES: applying `embedded_markdown` template layers to the source file itself or
    ignoring them for Markdown strings inside Python sources under that path."""
    _write_layers(workdir)
    (workdir / "src").mkdir()
    text = '# fmt: markdown\ndoc = """\nKeep %% a   b %% and << c   d >> but (( e   f )) reflows.\n"""\n'
    assert format_both_ways(run, workdir, "src/mod.py", text) == golden("embedded_markdown_layer")


def test_template_replace_then_add_in_same_layer(run, workdir, golden):
    """CATCHES: applying `add_delimiters` before `replace_delimiters` within one layer (the
    replace must not discard the additions)."""
    (workdir / "yamark.toml").write_text(
        "[template]\nadd_delimiters = [{ open = '<<', close = '>>' }]\nreplace_delimiters = [{ open = '((', close = '))' }]\n"
    )
    text = "items: [ << a , b >> , (( c , d )) , {{ e , f }} ]\n"
    assert format_both_ways(run, workdir, "input.yaml", text) == golden("replace_then_add")


def test_config_compact_false_does_not_override_cli_compact(run, workdir, golden):
    """CATCHES: letting `[format] compact = false` disable an explicit `--compact` flag."""
    (workdir / "yamark.toml").write_text("[format]\ncompact = false\n")
    text = "a:\n  - 1\n  - 2\n"
    result = run(["format", "--stdin-file-path", "input.yaml", "--compact"], input=text)
    assert outcome(result) == golden("compact_false_vs_flag")


def test_config_wrap_and_rule_apply(run, workdir, golden):
    """CATCHES: ignoring `[format] wrap`, `table_widths` or `markdown_horizontal_rule` from config."""
    (workdir / "yamark.toml").write_text(
        "[format]\nwrap = 'sentence:30'\ntable_widths = 'preserve'\nmarkdown_horizontal_rule = '***'\n"
    )
    text = "One sentence here. Another sentence that is long.\n\n---\n\n| a | b |\n|---|---|\n| long cell | x |\n"
    result = run(["format", "--stdin-file-path", "input.md"], input=text)
    assert outcome(result) == golden("format_layer_applies")


def test_cli_wrap_overrides_config_wrap(run, workdir, golden):
    """CATCHES: preferring `[format] wrap` over an explicit `--wrap` argument."""
    (workdir / "yamark.toml").write_text("[format]\nwrap = 'none'\n")
    text = "One sentence here. Another sentence that is long enough to wrap at twenty.\n"
    result = run(["format", "--stdin-file-path", "input.md", "--wrap", "20"], input=text)
    assert outcome(result) == golden("cli_wrap_overrides")
