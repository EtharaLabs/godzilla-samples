"""`lini desugar`: the file lowered to primitives + generated `.lini-*` classes
(templates, defines, capsules, chains, schematic parts, poses, sheets)."""

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

CASES = [
    '|box#cat| "cat"\n',
    '|group#g| [\n  |box#a|\n]\n',
    '{ |box| { radius: 4; } }\n|box#x|\n',
    '{ |group| |box| { fill: gray; } }\n|group#g| [\n  |box#a|\n]\n',
    'a -> b "w"\n',
    'a -> b "flows"\n',
    'a -> b\n',
    '|icon#home| { symbol: house }\n',
    '|group#g| "Boost" { layout: schematic } [ |gnd#x| ]\n',
    '|group#g| "Boost" [ |box#x| ]\n',
    '|J#J| { pins: 3; mirror: y-axis }\n',
    '|J#J| { pins: 3; rotate: 180 }\n',
    '|Q#Q| { mirror: x-axis }\n',
    '|R#r1| { mirror: 45 }\n',
    '{ layout: drawing }\n|rect#r| { width: 10; height: 5 }\n',
    '|page#p| { sheet: a5 }\n',
    '|page#p| { sheet: a3; sheet: a5 }\n',
    '|box#a|\n|box#b|\n|box#c|\na -> b -> c\n',
    '|box#a|\n|box#b|\n|box#c|\na -> b -> c "step"\n',
    '|box#a|\n|box#b|\n|box#c|\na - b <-> c\n',
    '|box#a|\n|box#b|\n|box#c|\n|box#d|\na -> b -> c & d\n',
    'x -> y -> z\n',
    '|box#a|\n|box#b|\n|box#c|\na -> b (-) c\n',
    '|mindmap#m| "M" { routing: orthogonal } [\n  |topic#a| "A"\n]\n',
    '|mindmap#m| "M" { direction: row } [\n  |topic#a| "A"\n]\n',
    'cat -> |cyl#db| "watches" { stroke: red }\n',
    '|cyl#db| -> cat\n',
    'a -> |box| -> c\n',
    'a & b -> |cyl#store|\n',
    '|group#g| [\n  a -> |cyl#db|\n]\n',
    '{ layout: drawing }\n|rect#r| { width: 4; height: 2 }\nr -> |box|\n',
    'a -> |cyl#db|\ndb -> c\n',
    '|J#J3| "header" { pins: 3 }\n',
    '|J#J4| { pins: 4 }\n',
    '|J#J4| { pins: 4; rotate: 180 }\n',
    '|R#R5| "470"\n',
    '|Q#q1| { symbol: nfet }\n',
    '|D#d1| { symbol: zenr }\n',
    '|gnd|\n',
    '|label#run| "RUN" { shape: round }\n',
    '|label#x| "X" { symbol: gnb }\n',
    '{ |vm::label| { symbol: power } [ "VM" ] }\n|vm#v1|\n',
    '|label#v1| { symbol: power } [ "VM" ]\n',
    '|R#R2| "a"\n|R| "b"\n|R| "c"\n',
    '|component| "x" { prefix: "IC" }\n',
    '|R| "a"\n|R| "b"\n',
    '|R#r1| "a"\n',
    '|component#U7| { rotate: 90 } [\n  |pin#a| { side: top }\n]\n',
    '|R#r1| "1k"\n',
    '|R#r1| "1k" { rotate: 90 }\n',
    '|gnd#g1|\n',
    '|gnd#g1| { rotate: 180 }\n',
    '{ |vert::R| { rotate: 90 } }\n|vert#r1|\n',
    '{ |vert::R| { rotate: 90 } }\n|vert#r1| { rotate: 90 }\n',
    '|R#r1| { rotate: 45 }\n',
    '|box#b| { rotate: 45 }\n',
    '|component#U7| [ |pin#a| { translate: 0 6 } ]\n',
    '|component#U7| { rotate: 90 } [ |pin#a| { translate: 0 6 } ]\n',
    '|component#U7| [ |pin#a| { translate: 4 0 } ]\n',
    '|component#U7| { rotate: 90 } [ |pin#a| { translate: 4 0 } ]\n',
    '|component#U7| { rotate: 90 } [ |pin#a| { side: top } ]\n',
    '{ |up::pin| { side: top } }\n|component#U7| { rotate: 180 } [ |up#a| ]\n',
    '|component#U7| [ |pin#a| { side: top } ]\n',
    '{ |amp::opamp| { prefix: "A" } }\n|schematic#s| [ |amp| ]\n',
    '|group#g| [\n  x -> y\n]\n',
]


@pytest.mark.parametrize("index", range(len(CASES)))
def test_desugar_stdin(run, index):
    """CATCHES: a desugar pass that lowers a construct differently (class chain order, generated class bundles, explicit labels/along, chain splitting, capsule hoisting, schematic symbol paths and poses) or reports its errors differently."""
    r = run(["desugar", "-"], input=CASES[index])
    assert outcome(r) == G(f"desugar_{index:02d}")


def test_desugar_file_argument(run, workdir):
    """CATCHES: desugar of a file differing from stdin, or diagnostics not naming the file."""
    write_files(workdir, {"a.lini": CASES[0], "bad.lini": "|R#r1| { rotate: 45 }\n"})
    assert outcome(run(["desugar", "a.lini"])) == G("desugar_00")
    r = run(["desugar", "bad.lini"])
    assert outcome(r) == G("desugar_file_error")


def test_desugar_missing_file(run):
    """CATCHES: desugar of a missing file not failing with exit 2."""
    r = run(["desugar", "nope.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: nope.lini: No such file or directory (os error 2)\n"


def test_desugar_is_a_fixed_point(run):
    """CATCHES: lowered output that is not itself fully lowered — desugaring it again keeps every statement and only separates the node and link phases with a blank line."""
    once = run(["desugar", "-"], input='{ |svc::box| { fill: --teal-wash; } }\n|svc#api| "API"\n|table#t| { columns: 2; } [ "a" "b"\n"c" "d" ]\nusers -> api "x"\n')
    assert outcome(once) == G("desugar_fixed_point")
    twice = run(["desugar", "-"], input=once.stdout)
    lowered = once.stdout.decode()
    assert twice.stdout.decode() == lowered.replace('[ "users" ]\nusers ->', '[ "users" ]\n\nusers ->')


def test_desugar_drops_comments(run):
    """CATCHES: desugar preserving comments (the lowered view never carries them) or failing on them."""
    r = run(["desugar", "-"], input='// title\n|box#a| "A"  // trailing\n')
    assert outcome(r) == G("desugar_comments")
