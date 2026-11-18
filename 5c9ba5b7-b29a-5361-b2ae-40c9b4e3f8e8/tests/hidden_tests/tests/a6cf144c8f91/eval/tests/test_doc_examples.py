"""Every Lini example the user documentation shows, compiled by the reference.

`spec_*` / `skill_*` / `readme_*` are the fenced examples of SPEC.md, SKILL.md
and README.md (fed on stdin, so diagnostics name `<stdin>`); `prop_*` are the
one-per-property compiled examples of schema/lini.schema.json (compiled from a
file). Fragments that do not compile pin the exact diagnostic instead.
"""

import shutil

import pytest

from conftest import Goldens, outcome, resources_for

R = resources_for(__file__)
G = Goldens(__file__)

DOC_BLOCKS = sorted(p.stem for p in R.glob("*.lini") if not p.stem.startswith("prop_"))
PROPERTY_EXAMPLES = sorted(p.stem for p in R.glob("prop_*.lini"))
FRAGMENTS = ["spec_03", "spec_04", "spec_15", "spec_18", "spec_23", "spec_26", "spec_29", "spec_32",
             "spec_33", "spec_36", "spec_39", "spec_41", "spec_43", "spec_46"]


@pytest.mark.parametrize("name", DOC_BLOCKS)
def test_doc_block_on_stdin(run, name):
    """CATCHES: a compiler that renders a documented example differently (layout, routing, paint, warnings) or reports a fragment's error with a different message, position or exit code."""
    r = run(["-"], input=(R / f"{name}.lini").read_bytes())
    assert outcome(r) == G(f"svg_{name}")


@pytest.mark.parametrize("name", PROPERTY_EXAMPLES)
def test_property_example_from_file(run, workdir, name):
    """CATCHES: a property whose documented example renders differently — wrong default, wrong value parsing, wrong SVG for that property."""
    shutil.copy(R / f"{name}.lini", workdir / "example.lini")
    shutil.copytree(R / "assets", workdir / "assets")
    r = run(["example.lini"])
    assert outcome(r) == G(f"svg_{name}")


@pytest.mark.parametrize("name", FRAGMENTS)
def test_doc_fragment_json_diagnostics(run, name):
    """CATCHES: --json diagnostics with a wrong code, family, severity, byte span, line/col or suggestion for a documented fragment."""
    r = run(["--json", "-"], input=(R / f"{name}.lini").read_bytes())
    assert outcome(r) == G(f"json_{name}")
