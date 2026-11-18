"""The bundled showroom samples, compiled end to end through every output form.

Each sample is a realistic multi-feature figure (charts, drawings, schematics,
sequences, floor plans, ...); the whole stdout/stderr/exit is compared against
the reference compiler's output.
"""

import shutil

import pytest

from conftest import Goldens, outcome, resources_for

R = resources_for(__file__)
G = Goldens(__file__)

SAMPLES = sorted(p.stem for p in R.glob("*.lini"))


def stage(workdir, name):
    """Copy one sample (and the shared assets/ folder its images point at) into the workdir."""
    shutil.copy(R / f"{name}.lini", workdir / f"{name}.lini")
    shutil.copytree(R / "assets", workdir / "assets")
    return f"{name}.lini"


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_compiles_to_live_svg(run, workdir, name):
    """CATCHES: any divergence in parsing, layout, routing, palette or SVG serialisation of the default (live, var()-based) output for a realistic sample file."""
    r = run([stage(workdir, name)])
    assert outcome(r) == G(f"svg_{name}")


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_compiles_to_static_svg(run, workdir, name):
    """CATCHES: wrong var() baking, wrong glyph outlining or glyph dedup in --static output, which must be self-contained and literal."""
    r = run(["--static", stage(workdir, name)])
    assert outcome(r) == G(f"static_{name}")


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_desugars(run, workdir, name):
    """CATCHES: a desugar pass that lowers templates, sugar or classes differently, or prints the lowered form with different formatting."""
    r = run(["desugar", stage(workdir, name)])
    assert outcome(r) == G(f"desugar_{name}")


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_desugared_rerenders_identically(run, workdir, name):
    """CATCHES: a desugared form that is not the engine's true input — compiling `lini desugar` output must give the byte-identical SVG."""
    lowered = run(["desugar", stage(workdir, name)]).stdout
    (workdir / "lowered.lini").write_bytes(lowered)
    r = run(["lowered.lini"])
    assert outcome(r) == G(f"svg_{name}")


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_fmt_stdout(run, workdir, name):
    """CATCHES: a formatter that is not canonical on the shipped samples (indentation, declaration grouping, comment placement, table alignment)."""
    src = stage(workdir, name)
    before = (workdir / src).read_text()
    r = run(["fmt", "--stdout", src])
    assert outcome(r) == G(f"fmt_{name}")
    assert (workdir / src).read_text() == before


INDENTED_SAMPLES = [n for n in SAMPLES if n != "hello"]  # hello.lini has no indentation to strip


@pytest.mark.parametrize("name", INDENTED_SAMPLES)
def test_sample_fmt_restores_indentation(run, name):
    """CATCHES: a formatter that echoes its input instead of re-deriving the layout — every sample with all indentation stripped must format back to its canonical form."""
    stripped = "".join(line.lstrip(" \t") for line in (R / f"{name}.lini").read_text().splitlines(keepends=True))
    r = run(["fmt", "-"], input=stripped)
    assert outcome(r) == G(f"fmt_{name}")


@pytest.mark.parametrize("name", ["hello", "layout", "charts", "drawing_sheet", "schematic", "sequence", "floorplan", "expr", "templates", "paint"])
def test_sample_highlights(run, workdir, name):
    """CATCHES: a highlighter that classifies tokens differently (types, user types, properties, vars, constants, operators) or fails to be byte-preserving."""
    r = run(["highlight", stage(workdir, name)])
    assert outcome(r) == G(f"highlight_{name}")


@pytest.mark.parametrize("name", ["hello", "shapes", "charts", "mindmap", "sequence"])
def test_sample_html_wrapper(run, workdir, name):
    """CATCHES: a wrong HTML document wrapper around the SVG for --format html."""
    r = run(["--format", "html", stage(workdir, name)])
    assert outcome(r) == G(f"html_{name}")


@pytest.mark.parametrize("name", ["hello", "logo", "expr"])
def test_sample_embed_font(run, workdir, name):
    """CATCHES: embedding the wrong font family/weight subset, or a wrong base64 @font-face block, under --embed-font."""
    r = run(["--embed-font", stage(workdir, name)])
    assert outcome(r) == G(f"embed_{name}")


@pytest.mark.parametrize("name", ["hero", "drawing_sheet", "schematic_hero", "chart_advanced"])
def test_sample_json_clean(run, workdir, name):
    """CATCHES: --json emitting spurious diagnostics, or the wrong document shape, for a clean file."""
    r = run(["--json", stage(workdir, name)])
    assert outcome(r) == G(f"json_{name}")
