"""Markdown code fences and Quarto chunk headers.

Long `{lang, key=value, ...}` openings in `.qmd` files are promoted to `#| key: value`
option lines when every option is simple (no quotes, braces, spaces or invalid keys),
no positional label precedes them, and a delegated language's formatter succeeds;
otherwise the opening is kept. Also covers raw `{=html}` attributes, empty braces,
spacing before the language, `fmt: skip` fence attributes and attribute spellings.
"""

import pytest

from conftest import format_both_ways

PASS_THROUGH_R = '[embedded.r]\nformatter = { command = ["python3", "-c", "import sys; sys.stdout.write(sys.stdin.read())", "{path}"], path_suffix = ".R" }\n'

FENCES = {
    'promote_simple': '```{r label, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\nplot(1)\n```\n',
    'promote_quoted_value': '```{r label, fig.cap="A caption with words", echo=FALSE, message=FALSE, warning=FALSE}\nplot(1)\n```\n',
    'promote_no_commas': '```{r xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx_label_without_any_commas_at_all_in_it}\nplot(1)\n```\n',
    'promote_bad_key': '```{r label, bad key=FALSE, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10}\nplot(1)\n```\n',
    'promote_value_with_brace': '```{r label, fig.dim=c(1,{2}), echo=FALSE, message=FALSE, warning=FALSE, fig.width=10}\nplot(1)\n```\n',
    'promote_value_with_space': '```{r label, echo= FALSE extra, message=FALSE, warning=FALSE, fig.width=10, x=1}\nplot(1)\n```\n',
    'promote_eof_no_newline': '```{r label, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}',
    'promote_language_hash': '```{#id .class, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\nx\n```\n',
    'promote_language_equals': '```{=html, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8, a=1}\nx\n```\n',
    'promote_only_language': '```{r, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8, dpi=300}\nplot(1)\n```\n',
    'promote_bash': '```{bash label, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8, x=1}\nls\n```\n',
    'promote_sentence_wrap': '```{r label, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\nplot(1)\n```\n',
    'raw_attribute': '```{=html}\n<b>x</b>\n```\n',
    'empty_braces': '```{}\ncode\n```\n',
    'space_before_language': '```   python\nx=1\n```\n',
    'info_fmt_skip_token': '```yaml {fmt:skip}\na:   1\n```\n',
    'info_fmt_skip_braced': '```{yaml fmt: skip}\na:   1\n```\n',
    'info_fmt_skip_trailing': '```yaml fmt: skip extra\na:   1\n```\n',
    'tilde_fence_yaml': '~~~yaml\na:   1\n~~~\n',
    'indented_fence': '   ```yaml\n   a:   1\n   ```\n',
    'fence_attributes_normalize': '```  {.python   #id   key=value}\nx=1\n```\n',
    'fence_attributes_quotes': '```{.python key="a b"}\nx=1\n```\n',
}

PROMOTIONS = {
    'promote_r': '```{r, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\nplot(1)\n```\n',
    'promote_r_quoted_value': '```{r, fig.cap="A caption with words", echo=FALSE, message=FALSE, warning=FALSE}\nplot(1)\n```\n',
    'promote_r_bad_key': '```{r, bad key=FALSE, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, x=1}\nplot(1)\n```\n',
    'promote_r_value_brace': '```{r, fig.dim=c(1,{2}), echo=FALSE, message=FALSE, warning=FALSE, fig.width=10}\nplot(1)\n```\n',
    'promote_r_value_space': '```{r, echo= FALSE extra, message=FALSE, warning=FALSE, fig.width=10, x=1, y=2}\nplot(1)\n```\n',
    'promote_r_eof': '```{r, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}',
    'promote_r_label_option': '```{r, label=my-chunk, echo=TRUE, message=FALSE, warning=FALSE, fig.width=10}\nplot(1)\n```\n',
    'promote_r_values_kinds': '```{r, echo=T, eval=F, cache=TRUE, dpi=300, out.width=50%, fig.align=center, x=-1.5}\nplot(1)\n```\n',
    'promote_bash': '```{bash, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8, x=1}\nls\n```\n',
    'promote_python_missing': '```{python, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8, x=1}\nx=1\n```\n',
    'promote_yaml': '```{yaml, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8, x=1}\na:   1\n```\n',
    'promote_unknown_language': '```{brainfuck, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\n+++\n```\n',
    'promote_crlf': '```{r, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\r\nplot(1)\r\n```\r\n',
    'promote_existing_hashpipe': '```{r, echo=FALSE, message=FALSE, warning=FALSE, fig.width=10, fig.height=8}\n#| label: x\nplot(1)\n```\n',
    'short_header_not_promoted': '```{r, echo=FALSE}\nplot(1)\n```\n',
}

WRAPS = {"default": [], "sentence": ["--wrap", "sentence"], "none": ["--wrap", "none"], "col30": ["--wrap", "30"]}


@pytest.mark.parametrize("suffix", ["md", "qmd"])
@pytest.mark.parametrize("name", sorted(FENCES))
def test_fence_openings(name, suffix, run, workdir, tool_bin, golden):
    """CATCHES: rewriting fence info strings that must be kept, promoting headers whose
    delegated formatter is missing, or mishandling `fmt: skip` fence attributes."""
    observed = format_both_ways(run, workdir, f"doc.{suffix}", FENCES[name], env_overrides={"PATH": str(tool_bin)})
    assert observed == golden(f"fence_{name}__{suffix}")


@pytest.mark.parametrize("wrap", sorted(WRAPS))
@pytest.mark.parametrize("name", sorted(PROMOTIONS))
def test_quarto_header_promotion(name, wrap, run, workdir, tool_bin, golden):
    """CATCHES: promoting headers with quoted, braced or spaced values or invalid keys, not
    promoting simple long headers (or doing so with `--wrap none`), wrong YAML spellings of
    promoted values (FALSE -> false, T kept), or lost CRLF line endings."""
    (workdir / "yamark.toml").write_text(PASS_THROUGH_R)
    observed = format_both_ways(run, workdir, "doc.qmd", PROMOTIONS[name], *WRAPS[wrap], env_overrides={"PATH": str(tool_bin)})
    assert observed == golden(f"promote_{name}__{wrap}")
