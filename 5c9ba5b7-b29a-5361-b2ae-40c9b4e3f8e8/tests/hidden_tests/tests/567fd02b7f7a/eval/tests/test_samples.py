"""The bundled samples (one per feature area, README: `samples/`) driven through
every output form of the CLI: SVG, --static, --format html, --json, desugar,
fmt --stdout and highlight. Inputs live in test_resources/test_samples/."""

import pytest

from conftest import RESOURCES, Case

SRC_DIR = RESOURCES / "test_samples"
SAMPLES = sorted(p.name for p in SRC_DIR.glob("*.lini"))
ASSETS = {f"assets/{p.name}": p.read_bytes() for p in (SRC_DIR / "assets").iterdir()}


def _files(sample):
    return {sample: (SRC_DIR / sample).read_text(encoding="utf-8"), **ASSETS}


def _stem(sample):
    return sample[: -len(".lini")]


SVG_CASES = {f"svg_{_stem(s)}": Case((s,), files=_files(s)) for s in SAMPLES}
STATIC_CASES = {f"static_{_stem(s)}": Case(("--static", s), files=_files(s)) for s in SAMPLES}
JSON_CASES = {f"json_{_stem(s)}": Case(("--json", "--strict", s), files=_files(s)) for s in SAMPLES}
DESUGAR_CASES = {f"desugar_{_stem(s)}": Case(("desugar", s), files=_files(s)) for s in SAMPLES}
FMT_CASES = {f"fmt_{_stem(s)}": Case(("fmt", "--stdout", s), files=_files(s)) for s in SAMPLES}
HIGHLIGHT_CASES = {f"highlight_{_stem(s)}": Case(("highlight", s), files=_files(s)) for s in SAMPLES}
HTML_CASES = {
    f"html_{_stem(s)}": Case(("--format", "html", "--theme", "dark", s), files=_files(s))
    for s in ("hello.lini", "charts.lini", "sequence.lini", "floorplan.lini")
}


@pytest.mark.parametrize("name", sorted(SVG_CASES))
def test_sample_svg(run_case, golden, name):
    """CATCHES: any change in the default SVG a sample compiles to — layout,
    routing, CSS rules and variables, element order or number formatting."""
    assert run_case(SVG_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(STATIC_CASES))
def test_sample_static(run_case, golden, name):
    """CATCHES: --static not inlining var() values, not outlining text to glyph
    paths, or outlining with different glyph geometry than the reference."""
    assert run_case(STATIC_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(JSON_CASES))
def test_sample_json(run_case, golden, name):
    """CATCHES: spurious diagnostics on a clean sample (or a missing empty
    `diagnostics` array), which --strict turns into exit 1."""
    assert run_case(JSON_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(DESUGAR_CASES))
def test_sample_desugar(run_case, golden, name):
    """CATCHES: `lini desugar` lowering a template, chart, table, drawing or
    schematic to different primitives, classes or generated rules."""
    assert run_case(DESUGAR_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(FMT_CASES))
def test_sample_fmt(run_case, golden, name):
    """CATCHES: `lini fmt --stdout` printing a different canonical form for a
    real-world file (comments, alignment, wrapping) or touching the file."""
    assert run_case(FMT_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(HIGHLIGHT_CASES))
def test_sample_highlight(run_case, golden, name):
    """CATCHES: `lini highlight` classifying a token into a different
    `lini-tok-*` class, escaping differently, or not preserving bytes."""
    assert run_case(HIGHLIGHT_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(HTML_CASES))
def test_sample_html(run_case, golden, name):
    """CATCHES: the --format html wrapper or a themed compile differing from the
    reference for a full figure."""
    assert run_case(HTML_CASES[name]) == golden(name)
