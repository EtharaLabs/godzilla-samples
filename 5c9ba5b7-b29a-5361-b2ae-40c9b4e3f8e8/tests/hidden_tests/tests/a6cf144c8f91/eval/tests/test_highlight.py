"""`lini highlight`: lexical, byte-preserving HTML token spans, and the --css palette."""

import html
import re

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

CASES = {
    "every_token_kind": '{ --x: #fff; w = 2; |svc::box| { fill: --teal-wash; } }\n|svc#a| "x" .hot { fill: --red; width: (w * 2); stroke-style: dashed; }\n// a comment\na -> b "lbl"\n|chart| { categories: "a", "b"; } [ |bars| { data: 1.5, -2e3; } ]\n',
    "entities": '|box| "x <&> \\"y\\" \'z\'"\na <-> b\na <> c\n',
    "unterminated": '|box| "never closed\n|oval| { fill: red\n',
    "unknown_words": '|wizard#w| { sparkle: 11; } [ ??? ]\n@@@ %%%\n',
    "link_ops": 'a -> b\nc --> d\ne ---> f\ng ~> h\ni -o< j\nk >o-o< l\nm *-* n\np (-) q\nr (o)\ns <- "t"\nu || v { gap: 2 }\n',
    "drawing_pen": '{ layout: drawing; }\n|sketch#s| { draw: move(0, -3.4) arc(3.4, 3.4, 3.4) down(2) close():west; mirror: y-axis; }\ns:west (o)\n',
    "unicode": '|box| "你好 — ünïcödé 🙂"\n// ✓ comment\n',
    "crlf_tabs": '|box#a|\t"A"\r\n\ta -> b\r\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_highlight_stdin(run, name):
    """CATCHES: wrong token classification (type vs type-user, prop vs prop-user, var, const, keyword, op, class, punct) or wrong HTML escaping."""
    r = run(["highlight", "-"], input=CASES[name])
    assert outcome(r) == G(f"hl_{name}")


@pytest.mark.parametrize("name", sorted(CASES))
def test_highlight_is_byte_preserving(run, name):
    """CATCHES: a highlighter that drops, reorders or rewrites source bytes: stripping the tags and unescaping must give the input back exactly, and the spans must be the reference ones."""
    r = run(["highlight", "-"], input=CASES[name])
    assert outcome(r) == G(f"hl_{name}")
    assert html.unescape(re.sub(r"</?span[^>]*>", "", r.stdout.decode())) == CASES[name]


def test_highlight_file(run, workdir):
    """CATCHES: highlighting a file argument differently from stdin."""
    write_files(workdir, {"h.lini": CASES["every_token_kind"]})
    r = run(["highlight", "h.lini"])
    assert outcome(r) == G("hl_every_token_kind")


def test_highlight_css(run):
    """CATCHES: a token palette with different role variables, light-dark() pairs, layer or class rules."""
    r = run(["highlight", "--css"])
    assert outcome(r) == G("hl_css")


def test_highlight_css_ignores_input(run, workdir):
    """CATCHES: --css reading or highlighting the input instead of printing only the palette."""
    write_files(workdir, {"h.lini": '|box| "x"\n'})
    r = run(["highlight", "--css", "h.lini"])
    assert outcome(r) == G("hl_css")


def test_highlight_requires_input(run):
    """CATCHES: highlight without an input or --css not failing with exit 3 and its own message."""
    r = run(["highlight"])
    assert outcome(r) == "exit: 3\n--- stdout ---\n--- stderr ---\nerror: an input file is required — or '--css' for the palette\n"


def test_highlight_missing_file(run):
    """CATCHES: highlight of a missing file not failing with exit 2 and the OS message."""
    r = run(["highlight", "nope.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: nope.lini: No such file or directory (os error 2)\n"


def test_highlight_empty(run):
    """CATCHES: highlight emitting anything for empty input."""
    r = run(["highlight", "-"], input="")
    assert outcome(r) == "exit: 0\n--- stdout ---\n--- stderr ---\n"
    r = run(["highlight", "-"], input="|box|")
    assert outcome(r) == 'exit: 0\n--- stdout ---\n<span class="lini-tok-punct">|</span><span class="lini-tok-type">box</span><span class="lini-tok-punct">|</span>--- stderr ---\n'
