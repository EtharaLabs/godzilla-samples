"""`lini highlight` (lexical HTML spans, `--css` palette) and `lini desugar`
(the file lowered to primitives) — their inputs, outputs and failure modes."""

import html
import re

import pytest

from conftest import Case

TOKENS = (
    "// a comment with <angle> & \"quotes\"\n"
    "{\n"
    "  layout: grid; columns: repeat(2, 80);\n"
    "  --brand: #ff6600;\n"
    "  w = (8 * 2 + 1.5);\n"
    "  |svc::box| { fill: --teal-wash; my-prop: 3; }\n"
    "  .hot { stroke: --red; stroke-width: 2; }\n"
    "}\n"
    '|svc#api| "API <v2> & co" .hot { width: w; opacity: 50%; }\n'
    "|oval#db| \"DB\"\n"
    "api -> db { along: 0.5; } [ \"reads\" ]\n"
    "api --> db\napi ~> db\napi -o< db\n"
    "a:left (-) b:right\n"
)
MID_EDIT = '|box#a| "unterminated\n|oval| { fill: @@ ; }\n\t\'single\' 12abc\r\n'

HIGHLIGHT_CASES = {
    "css_palette": Case(("highlight", "--css")),
    "css_ignores_input": Case(("highlight", "--css", "missing.lini")),
    "every_token_kind": Case(("highlight", "t.lini"), files={"t.lini": TOKENS}),
    "stdin": Case(("highlight", "-"), stdin=TOKENS),
    "mid_edit_still_highlights": Case(("highlight", "m.lini"), files={"m.lini": MID_EDIT}),
    "empty_file": Case(("highlight", "e.lini"), files={"e.lini": "\n"}),
    "unicode_text": Case(("highlight", "u.lini"), files={"u.lini": '|box| "héllo — 你好 🎉"  // ünï\n'}),
    "missing_file": Case(("highlight", "missing.lini")),
    "not_utf8": Case(("highlight", "b.lini"), files={"b.lini": b"\xff\n"}),
    "directory": Case(("highlight", "d"), files={"d/.keep": ""}),
}

DESUGAR_INPUTS = {
    "flow_with_define": '{ |svc::box| { fill: --teal-wash; } }\n|group| "Services" [ |svc#api| "API"; |svc#auth| "Auth" ]\napi -> auth "calls"\n',
    "table": '|table#t| { columns: 80, 80; } [\n"A" "Qty"\n"Apple" { color: red; } "3"\n]\n',
    "entity": '|entity#users| "Users" [\n"id" "int"\n"name" "text"\n]\n',
    "chart": '|chart| { categories: "a", "b"; } [ |bars| { data: 1, 2; } ]\n',
    "sequence": '{ layout: sequence; }\n|box#a| "A"\n|box#b| "B"\na -> b "call"\nb --> a "ret"\n|note| "n" { place: over a b; }\n',
    "tree": '|group| { layout: tree; } [ |topic| "root" [ |topic| "a"; |topic| "b" ] ]\n',
    "capsules": 'cat -> |cyl#db| "watches"\na -> |box| -> c\n',
    "icons_and_signs": '|icon| "star"\n|sign| "warning" [ "Hot" ]\n',
    "expressions": '{ w = 10; scale(n) = (w * n); }\n|box| { width: scale(3); height: (w + 5); }\n',
    "schematic": '{ layout: schematic; }\n|R#r1| "10k"\n|C#c1| "1u"\n|gnd#g|\nr1.p2 - c1 - g\nr1.p1 - "VIN"\n',
    "drawing": '{ layout: drawing; }\n|sketch#a| { draw: move(0,0) right(20):base up(10) left(20) close(); }\na:left (-) a:right { side: bottom; }\na:base <- "FACE"\n',
    "floorplan": '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#w| { draw: move(0,0) right(4):south up(3):east; } [ |door| { on: south; at: 1; } ]\n|bed| { translate: 1 1; }\n',
    "comments_dropped": '// gone\n|box#a| "A"  // also gone\n',
}
DESUGAR_CASES = {f"desugar_{k}": Case(("desugar", "in.lini"), files={"in.lini": v}) for k, v in DESUGAR_INPUTS.items()}
DESUGAR_CASES.update({
    "desugar_stdin": Case(("desugar", "-"), stdin=DESUGAR_INPUTS["flow_with_define"]),
    "desugar_parse_error": Case(("desugar", "p.lini"), files={"p.lini": '|box#a| {\n'}),
    "desugar_parse_error_stdin": Case(("desugar", "-"), stdin='|box| "open\n'),
    "desugar_unknown_type": Case(("desugar", "u.lini"), files={"u.lini": '|nosuch#a| "x"\n'}),
    "desugar_unknown_property_kept": Case(("desugar", "u.lini"), files={"u.lini": "|box#a| { colr: red; }\n"}),
    "desugar_missing_file": Case(("desugar", "missing.lini")),
    "desugar_empty_file": Case(("desugar", "e.lini"), files={"e.lini": ""}),
})


@pytest.mark.parametrize("name", sorted(HIGHLIGHT_CASES))
def test_highlight(run_case, golden, name):
    """CATCHES: a token put in the wrong `lini-tok-*` class, different HTML
    escaping, highlighting that fails on a half-written file (it never parses),
    a changed --css palette, or I/O errors with the wrong message/exit code."""
    assert run_case(HIGHLIGHT_CASES[name]) == golden(name)


@pytest.mark.parametrize("src", [TOKENS, MID_EDIT, '|box| "a&amp;b" // <x>\n'], ids=["tokens", "mid_edit", "entities"])
def test_highlight_is_byte_preserving(run, workdir, src):
    """CATCHES: a highlighter that drops, reorders or normalises source bytes
    (tabs, CR, unknown characters) — stripping the tags and undoing the four
    entity escapes must give back the exact input."""
    (workdir / "in.lini").write_bytes(src.encode())
    r = run(["highlight", "in.lini"])
    assert r.returncode == 0
    out = r.stdout.decode()
    assert set(re.findall(r'class="([^"]+)"', out)) <= {
        f"lini-tok-{k}" for k in ("comment", "string", "number", "const", "keyword", "type", "type-user",
                                  "prop", "prop-user", "var", "op", "class", "punct")}
    stripped = re.sub(r"</?span[^>]*>", "", out)
    unescaped = stripped.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")
    assert unescaped == src
    assert html.unescape(stripped) == src


@pytest.mark.parametrize("name", sorted(DESUGAR_CASES))
def test_desugar(run_case, golden, name):
    """CATCHES: desugar lowering a construct to different primitives, classes or
    generated stylesheet rules, keeping comments, or failing with the wrong
    message/exit code on bad input."""
    assert run_case(DESUGAR_CASES[name]) == golden(name)


@pytest.mark.parametrize("key", ["flow_with_define", "table", "chart", "sequence", "schematic", "drawing"])
def test_desugared_form_rerenders_identically(run, workdir, key):
    """CATCHES: a desugar output that is not the engine's true input — compiling
    the lowered form must give byte-identical SVG to compiling the original."""
    (workdir / "orig.lini").write_text(DESUGAR_INPUTS[key])
    lowered = run(["desugar", "orig.lini"])
    assert lowered.returncode == 0
    (workdir / "low.lini").write_bytes(lowered.stdout)
    original_svg = run(["orig.lini"])
    lowered_svg = run(["low.lini"])
    assert original_svg.returncode == 0
    assert lowered_svg.stdout == original_svg.stdout
    assert lowered_svg.stdout.startswith(b'<svg xmlns="http://www.w3.org/2000/svg"')
