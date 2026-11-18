"""Examples taken from the user documentation — the fenced Lini blocks of
SPEC.md / SKILL.md / README.md and the per-property `example` of
schema/lini.schema.json — compiled through the CLI, plus every built-in
template instantiated in a scope where it belongs."""

import json

import pytest

from conftest import RESOURCES, Case

RES = RESOURCES / "test_doc_examples"
LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect id="m" width="8" height="8"/></svg>\n'

BLOCK_CASES = {
    f"block_{p.stem}": Case(("in.lini",), files={"in.lini": p.read_text(encoding="utf-8")})
    for p in sorted((RES / "blocks").glob("*.lini"))
}
BLOCK_STATIC_CASES = {
    f"block_static_{p.stem}": Case(("--static", "in.lini"), files={"in.lini": p.read_text(encoding="utf-8")})
    for p in sorted((RES / "blocks").glob("*.lini"))[::4]
}

PROPERTY_EXAMPLES = json.loads((RES / "property_examples.json").read_text(encoding="utf-8"))
PROPERTY_CASES = {
    f"property_{name}": Case(("in.lini",), files={"in.lini": src + "\n", "assets/logo.svg": LOGO})
    for name, src in sorted(PROPERTY_EXAMPLES.items())
}

STANDALONE = ["box", "rect", "group", "caption", "footnote", "sheet-caption", "badge", "row", "column", "table",
              "cell", "header", "footer", "entity", "note", "balloon", "mindmap", "page", "title-block",
              "field", "frame", "zone", "stack", "schematic"]
SCHEMATIC_PARTS = ["R", "C", "L", "D", "LED", "Q", "Y", "F", "FB", "SW", "BT", "V", "I", "M", "BZ", "TP",
                   "J", "opamp", "gnd", "nc", "junction", "label", "component", "space"]
FLOORPLAN_FURNITURE = ["bed", "sofa", "dining", "bath", "appliance"]

TEMPLATE_CASES = {f"template_{t}": Case(("in.lini",), files={"in.lini": f'|{t}| "Label"\n'}) for t in STANDALONE}
TEMPLATE_CASES.update({
    f"template_schematic_{t}": Case(("in.lini",), files={"in.lini": f'{{ layout: schematic; }}\n|{t}#x1| "Part"\n'})
    for t in SCHEMATIC_PARTS
})
TEMPLATE_CASES.update({
    f"template_floorplan_{t}": Case(("in.lini",), files={
        "in.lini": f"{{ layout: floorplan; unit: m; scale: 0.02; }}\n|{t}| {{ translate: 1 1; }}\n"})
    for t in FLOORPLAN_FURNITURE
})


@pytest.mark.parametrize("name", sorted(BLOCK_CASES))
def test_documented_block(run_case, golden, name):
    """CATCHES: a documented example that no longer compiles, or compiles to a
    different SVG than the reference (layout, routing, styling, numbers)."""
    assert run_case(BLOCK_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(BLOCK_STATIC_CASES))
def test_documented_block_static(run_case, golden, name):
    """CATCHES: --static output of a documented example differing (inlined
    values, outlined glyph paths)."""
    assert run_case(BLOCK_STATIC_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(PROPERTY_CASES))
def test_property_example(run_case, golden, name):
    """CATCHES: a property from the published schema whose example is rejected
    or renders differently from the reference."""
    assert run_case(PROPERTY_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(TEMPLATE_CASES))
def test_template_instance(run_case, golden, name):
    """CATCHES: a built-in template with different defaults, geometry, symbol or
    generated classes, or one that errors (or not) outside its scope."""
    assert run_case(TEMPLATE_CASES[name]) == golden(name)
