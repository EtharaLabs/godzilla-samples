"""Embedded external formatters: built-in shorthands (ruff, air, mdformat, prettier-*),
custom commands, optional versus strict failure handling, stderr rules, and Ruff's
notebook-cell JSON protocol.

Fake formatter executables are placed first on a PATH that otherwise holds only Python
and a few POSIX tools; their behaviour is selected with the FAKE_MODE environment
variable so each test pins one protocol branch.
"""

import os
import sys

import pytest

from conftest import format_both_ways, outcome

FAKE_RUFF = r'''
import json, os, sys
mode = os.environ.get("FAKE_MODE", "ok")
data = sys.stdin.read() if mode != "close_stdin" else ""
def out(obj):
    sys.stdout.write(json.dumps(obj))
if mode in ("ok", "close_stdin"):
    nb = json.loads(data) if data else {"cells": [{"source": "x = 'closed'\n"}]}
    src = nb["cells"][0]["source"].replace("x=1", "x = 1")
    nb["cells"][0]["source"] = src
    out(nb)
elif mode == "array":
    src = json.loads(data)["cells"][0]["source"].replace("x=1", "x = 1")
    out({"cells": [{"source": src.splitlines(True)}]})
elif mode == "badjson":
    sys.stdout.write("not json at all")
elif mode == "nocells":
    out({"metadata": {}})
elif mode == "twocells":
    out({"cells": [{"source": "a"}, {"source": "b"}]})
elif mode == "nosource":
    out({"cells": [{"cell_type": "code"}]})
elif mode == "numbersource":
    out({"cells": [{"source": 5}]})
elif mode == "arraynonstring":
    out({"cells": [{"source": ["x = 1\n", 5]}]})
elif mode == "fail_paren":
    sys.stderr.write("error: Failed to parse cell (2:7): unexpected token\n"); sys.exit(2)
elif mode == "fail_colon":
    sys.stderr.write("cell.py:3:4: E999 SyntaxError\n"); sys.exit(1)
elif mode == "fail_plain":
    sys.stderr.write("something went wrong\n"); sys.exit(1)
elif mode == "fail_silent":
    sys.exit(3)
elif mode == "stderr_success":
    sys.stderr.write("warning: deprecated option\n"); out(json.loads(data))
elif mode == "stderr_whitespace":
    sys.stderr.write("   \n"); out(json.loads(data))
elif mode == "invalid_utf8":
    sys.stdout.buffer.write(b"\xff\xfe"); sys.stdout.flush()
'''

FAKE_ECHO_ARGS = r'''
import os, sys
data = sys.stdin.read()
name = os.path.basename(sys.argv[0])
sys.stdout.write(f"{data.rstrip()}\n/* {name} {' '.join(sys.argv[1:])} */\n")
'''

FAKE_FAIL = r'''
import os, sys
mode = os.environ.get("FAKE_MODE", "message")
sys.stdin.read()
if mode == "message":
    sys.stderr.write("strict formatter rejected input (4:2)\n"); sys.exit(1)
sys.exit(5)
'''


@pytest.fixture
def fakes(tmp_path):
    """Directory of fake formatter executables to prepend to PATH."""
    d = tmp_path / "fakes"
    d.mkdir()

    def write(name, body):
        path = d / name
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    write("ruff", FAKE_RUFF)
    for name in ("air", "prettier", "mdformat"):
        write(name, FAKE_ECHO_ARGS)
    write("strictfmt", FAKE_FAIL)
    (d / "noexec").write_text("#!/bin/sh\nexit 0\n")
    return d


def _env(fakes, tool_bin, mode=None):
    env = {"PATH": f"{fakes}{os.pathsep}{tool_bin}"}
    if mode:
        env["FAKE_MODE"] = mode
    return env


PY_MARKDOWN = "Intro.\n\n```python\nx=1\ny=2\n```\n\n```{python}\n#| echo: false\nx=1\n```\n"
PY_YAML = "# fmt: python\ncode: |\n  x=1\n  y=2\nother: [a,b]\n"
PY_SOURCE = '# fmt: python\nSNIPPET = """\nx=1\n"""\n'

RUFF_MODES = [
    "ok", "array", "close_stdin", "badjson", "nocells", "twocells", "nosource", "numbersource",
    "arraynonstring", "fail_paren", "fail_colon", "fail_plain", "fail_silent", "stderr_success",
    "stderr_whitespace", "invalid_utf8",
]


@pytest.mark.parametrize("mode", RUFF_MODES)
def test_builtin_ruff_in_markdown(mode, run, workdir, tool_bin, fakes, golden):
    """CATCHES: wrong notebook-cell protocol handling for the built-in Ruff formatter: source
    arrays, malformed notebook JSON, cell counts, failure notes with formatter locations,
    stderr-on-success errors, and invalid UTF-8 output."""
    observed = format_both_ways(run, workdir, "doc.md", PY_MARKDOWN, "--diagnostics", env_overrides=_env(fakes, tool_bin, mode))
    assert observed == golden(f"ruff_markdown_{mode}")


@pytest.mark.parametrize("mode", ["ok", "array", "badjson", "fail_paren", "fail_silent", "stderr_success"])
def test_builtin_ruff_in_yaml_scalar(mode, run, workdir, tool_bin, fakes, golden):
    """CATCHES: different optional-failure handling for a YAML literal scalar target than for
    a Markdown fence (the entry must be preserved and noted)."""
    observed = format_both_ways(run, workdir, "doc.yaml", PY_YAML, "--diagnostics", env_overrides=_env(fakes, tool_bin, mode))
    assert observed == golden(f"ruff_yaml_{mode}")


@pytest.mark.parametrize("mode", ["ok", "fail_colon", "nocells"])
def test_builtin_ruff_in_python_string(mode, run, workdir, tool_bin, fakes, golden):
    """CATCHES: mishandling Ruff output for a Python string target marked `# fmt: python`."""
    observed = format_both_ways(run, workdir, "mod.py", PY_SOURCE, "--diagnostics", env_overrides=_env(fakes, tool_bin, mode))
    assert observed == golden(f"ruff_python_{mode}")


def test_skip_embedded_formatters(run, workdir, tool_bin, fakes, golden):
    """CATCHES: running embedded formatters despite `--skip-embedded-formatters`."""
    observed = format_both_ways(run, workdir, "doc.md", PY_MARKDOWN, "--skip-embedded-formatters", env_overrides=_env(fakes, tool_bin))
    assert observed == golden("skip_embedded")


SHORTHAND_FENCES = {
    "air": "r", "mdformat": "mdformat", "prettier-json": "json", "prettier-jsonc": "jsonc",
    "prettier-json5": "json5", "prettier-graphql": "graphql", "prettier-css": "css", "prettier-scss": "scss",
    "prettier-less": "less", "prettier-postcss": "pcss", "prettier-html": "html", "prettier-js": "js",
    "prettier-jsx": "jsx", "prettier-ts": "ts", "prettier-tsx": "tsx",
}


@pytest.mark.parametrize("shorthand", sorted(SHORTHAND_FENCES))
def test_configured_shorthand(shorthand, run, workdir, tool_bin, fakes, golden):
    """CATCHES: a configured built-in shorthand that runs the wrong program, passes the wrong
    arguments, or uses the wrong virtual path suffix."""
    (workdir / "yamark.toml").write_text(f'[embedded.custom]\nformatter = "{shorthand}"\n')
    text = "```custom\ncontent   here\n```\n"
    observed = format_both_ways(run, workdir, "doc.md", text, env_overrides=_env(fakes, tool_bin))
    assert observed == golden(f"shorthand_{shorthand}")


ALIAS_FENCES = ["r", "json", "jsonc", "json5", "graphql", "gql", "graphqls", "css", "scss", "less", "postcss",
                "pcss", "html", "js", "javascript", "jsx", "ts", "typescript", "tsx", "mdformat"]


@pytest.mark.parametrize("fence", ALIAS_FENCES)
def test_default_fence_aliases(fence, run, workdir, tool_bin, fakes, golden):
    """CATCHES: wrong default mapping from Markdown fence languages to built-in formatters and
    their virtual path suffixes."""
    text = f"```{fence}\ncontent   here\n```\n"
    observed = format_both_ways(run, workdir, "doc.md", text, env_overrides=_env(fakes, tool_bin))
    assert observed == golden(f"alias_{fence}")


@pytest.mark.parametrize("mode", ["message", "silent"])
def test_strict_custom_formatter_failure(mode, run, workdir, tool_bin, fakes, golden):
    """CATCHES: treating a failing custom (strict) formatter as optional; its failure must be
    an error with the formatter's message or the exit status and command line."""
    (workdir / "yamark.toml").write_text(
        '[embedded.strict]\nformatter = { command = ["strictfmt", "--input", "{path}"], path_suffix = ".txt" }\n'
    )
    text = "```strict\ncontent\n```\n"
    observed = format_both_ways(run, workdir, "doc.md", text, env_overrides=_env(fakes, tool_bin, mode))
    assert observed == golden(f"strict_failure_{mode}")


def test_strict_custom_formatter_missing(run, workdir, tool_bin, fakes, golden):
    """CATCHES: silently skipping a missing executable for a custom formatter whose command
    is not one of the optional tool names."""
    (workdir / "yamark.toml").write_text(
        '[embedded.gone]\nformatter = { command = ["no-such-formatter", "{path}"], path_suffix = ".txt" }\n'
    )
    observed = format_both_ways(run, workdir, "doc.md", "```gone\ncontent\n```\n", env_overrides=_env(fakes, tool_bin))
    assert observed == golden("strict_missing")


def test_formatter_not_executable(run, workdir, tool_bin, fakes, golden):
    """CATCHES: treating a permission error when spawning a formatter like a missing one."""
    (workdir / "yamark.toml").write_text(
        f'[embedded.noexec]\nformatter = {{ command = ["{fakes}/noexec", "{{path}}"], path_suffix = ".txt" }}\n'
    )
    observed = format_both_ways(run, workdir, "doc.md", "```noexec\ncontent\n```\n", env_overrides=_env(fakes, tool_bin))
    observed = {k: {**v, "stderr": v["stderr"].replace(str(fakes), "<fakes>")} for k, v in observed.items()}
    assert observed == golden("not_executable")


def test_optional_custom_command_named_ruff(run, workdir, tool_bin, fakes, golden):
    """CATCHES: treating a configured command whose argv[0] is exactly `ruff` as strict; its
    failure must be a note only (shown with --diagnostics)."""
    (workdir / "yamark.toml").write_text(
        '[embedded.python]\nformatter = { command = ["ruff", "format", "{path}"], path_suffix = ".py" }\n'
    )
    observed = format_both_ways(run, workdir, "doc.md", PY_MARKDOWN, "--diagnostics", env_overrides=_env(fakes, tool_bin, "fail_silent"))
    assert observed == golden("optional_custom_ruff")


def test_unknown_formatter_name_is_error(run, workdir, golden):
    """CATCHES: ignoring `# fmt: <name>` for a name that is neither built in nor configured."""
    observed = format_both_ways(run, workdir, "doc.yaml", "# fmt: mystery\ncode: |\n  x\n")
    assert observed == golden("unknown_name")


def test_config_name_overrides_builtin_alias(run, workdir, tool_bin, fakes, golden):
    """CATCHES: preferring the built-in mapping over an `[embedded.<name>]` entry with the
    same name as a fence alias."""
    (workdir / "yamark.toml").write_text('[embedded.css]\nformatter = "mdformat"\n')
    observed = format_both_ways(run, workdir, "doc.md", "```css\na{b:c}\n```\n", env_overrides=_env(fakes, tool_bin))
    assert observed == golden("config_overrides_alias")


def test_yaml_scalar_embedded_formatter_errors(run, workdir, tool_bin, fakes, golden):
    """CATCHES: wrong errors when an embedded formatter directive targets something other than
    a literal block scalar (plain scalar, folded scalar, collection)."""
    docs = {
        "plain": "# fmt: python\ncode: x=1\n",
        "folded": "# fmt: python\ncode: >\n  x=1\n",
        "mapping": "# fmt: python\ncode:\n  a: 1\n",
        "eof": "a: 1\n# fmt: python\n",
    }
    observed = {
        name: outcome(run(["format", "--stdin-file-path", "doc.yaml"], input=text, env_overrides=_env(fakes, tool_bin)))
        for name, text in docs.items()
    }
    assert observed == golden("yaml_target_errors")


NESTED_STRICT = {
    "front_matter_scalar": "---\n# fmt: strict\ncode: |\n  x\n---\n\nBody.\n",
    "markdown_fence": "````markdown\n```strict\nx\n```\n````\n",
    "fenced_div": "::: note\n```strict\nx\n```\n:::\n",
    "yaml_fence_scalar": "```yaml\n# fmt: strict\ncode: |\n  x\n```\n",
    "list_item_fence": "- item\n\n  ```strict\n  x\n  ```\n",
}


@pytest.mark.parametrize("name", sorted(NESTED_STRICT))
def test_strict_failure_inside_nested_region(name, run, workdir, tool_bin, fakes, golden):
    """CATCHES: swallowing a strict formatter's failure when its target sits inside front
    matter, a Markdown fence, a fenced div, a YAML fence or a list item; the whole file must
    fail with the formatter's message and stay unchanged."""
    (workdir / "yamark.toml").write_text(
        '[embedded.strict]\nformatter = { command = ["strictfmt", "{path}"], path_suffix = ".txt" }\n'
    )
    observed = format_both_ways(run, workdir, "doc.md", NESTED_STRICT[name], env_overrides=_env(fakes, tool_bin, "message"))
    assert observed == golden(f"nested_strict_{name}")
