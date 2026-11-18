"""Links (SPEC 9 + ROUTING): operators and markers, chains and fans, labels,
sides, capsules, dot-paths, routing strategies and routing-law diagnostics."""

import pytest

from conftest import Goldens, outcome

G = Goldens(__file__)

CASES = {
    'link_arrow_family': '{ direction: column; gap: 20; }\n|row| [ |box#a| "a"; |box#b| "b" ]\n|row| [ |box#c| "c"; |box#d| "d" ]\n|row| [ |box#e| "e"; |box#f| "f" ]\na -> b\nc <- d\ne <-> f\n',
    'link_line_styles': '{ direction: column; gap: 16; }\n|row#r1| [ |box#a| "a"; |box#b| "b"; a -- b ]\n|row#r2| [ |box#c| "c"; |box#d| "d"; c --- d ]\n|row#r3| [ |box#e| "e"; |box#f| "f"; e ~ f ]\n|row#r4| [ |box#g| "g"; |box#h| "h"; g ~> h ]\n|row#r5| [ |box#i| "i"; |box#j| "j"; i ---> j ]\n',
    'link_dot_diamond': '{ direction: column; gap: 16; }\n|row#r1| [ |box#a| "a"; |box#b| "b"; a *-* b ]\n|row#r2| [ |box#c| "c"; |box#d| "d"; c -<> d ]\n|row#r3| [ |box#e| "e"; |box#f| "f"; e <>-<> f ]\n|row#r4| [ |box#g| "g"; |box#h| "h"; g *- h ]\n',
    'link_er_cardinality': '{ direction: column; gap: 16; }\n|row#r1| [ |box#a| "a"; |box#b| "b"; a -+ b ]\n|row#r2| [ |box#c| "c"; |box#d| "d"; c -< d ]\n|row#r3| [ |box#e| "e"; |box#f| "f"; e -o+ f ]\n|row#r4| [ |box#g| "g"; |box#h| "h"; g -+< h ]\n|row#r5| [ |box#i| "i"; |box#j| "j"; i -o< j ]\n|row#r6| [ |box#k| "k"; |box#l| "l"; k -++ l ]\n|row#r7| [ |box#m| "m"; |box#n| "n"; m >o-o< n ]\n|row#r8| [ |box#o| "o"; |box#p| "p"; o +-< p ]\n',
    'link_marker_overrides': '|box#a| "a"\n|box#b| "b"\na -> b { marker-start: diamond; marker-end: zero-or-many; stroke-style: dotted; }\n',
    'link_marker_all': '{ direction: column; gap: 12; }\n|line| { points: 0 0, 60 0; marker-end: arrow; }\n|line| { points: 0 0, 60 0; marker: dot; }\n|line| { points: 0 0, 60 0; marker-start: circle; marker-end: diamond; }\n|line| { points: 0 0, 60 0; marker-end: one; }\n|line| { points: 0 0, 60 0; marker-end: crow; }\n|line| { points: 0 0, 60 0; marker-end: exactly-one; }\n|line| { points: 0 0, 60 0; marker-end: zero-or-one; }\n|line| { points: 0 0, 60 0; marker-end: one-or-many; }\n|line| { points: 0 0, 60 0; marker-end: datum; }\n|line| { points: 0 0, 60 0, 60 30; marker-end: none; radius: 6; }\n',
    'link_chain_and_fans': '|box#a| "a"\n|box#b| "b"\n|box#c| "c"\n|box#d| "d"\na -> b -> c\na -> b & c\na & b -> d\na & b -> c & d\n',
    'link_fan_out_trunk': '{ direction: column; gap: 60; }\n|box#src| "Source"\n|row| { gap: 30; } [ |box#x| "X"; |box#y| "Y"; |box#z| "Z" ]\nsrc -> x & y & z\n',
    'link_self_loop': '|box#a| "Self"\na -> a "again"\n',
    'link_forced_sides': '|box#a| "A"\n|box#b| "B"\na:top -> b:top "over"\na:bottom -> b:bottom "under"\nb:right -> a:left\n',
    'link_labels_along': '{ direction: column; gap: 80; }\n|box#a| "A"\n|box#b| "B"\na -> b { along: 0.2, 0.5, 0.8; } [ "near a" "mid" "near b" ]\n',
    'link_label_styled': '|box#a| "A"\n|box#b| "B"\na -> b [ "styled" { color: --red-ink; font-size: 18; translate: 0 -6; } ]\n',
    'link_split_labels_warn': '|box#a| "A"\n|box#b| "B"\na -> b "x" [ "y" ]\n',
    'link_styles_cascade': '{\n  |-| { stroke: #888; stroke-width: 1.5; font-size: 12; }\n  #g |-| { stroke: --blue; }\n  .flow { stroke: --teal; }\n  clearance: 12;\n}\n|group#g| [ |box#a| "a"; |box#b| "b"; a -> b "inner" ]\n|box#c| "c"\ng.b -> c "flow" .flow\ng.a -> c "own" { stroke: red; stroke-style: dashed; }\n',
    'link_routing_natural': '{ routing: natural; direction: column; gap: 50; }\n|box#a| "A"\n|row| { gap: 80; } [ |box#b| "B"; |box#c| "C" ]\na -> b\na -> c\nb -> c\n',
    'link_routing_straight': '{ routing: straight; }\n|box#a| "A"\n|oval#b| "B" { translate: 0 60; }\n|diamond#c| "C"\na -> b\nb -> c\na -> c\n',
    'link_routing_per_group': '|group#g| { routing: natural; } [ |box#a| "a"; |box#b| "b" { translate: 0 50; }; a -> b ]\n|box#c| "c"\ng.a -> c\n',
    'link_obstacle_detour': '|box#a| "A"\n|box#mid| "Middle obstacle"\n|box#b| "B"\na -> b "around"\n',
    'link_capsules': 'cat -> |cyl#db| "watches" { stroke: red; }\na -> |box| -> c\na & b -> |cyl#store|\n',
    'link_dot_paths': '{\n  |room::group| { gap: 10; } [\n    |box#inlet| "Inlet"\n    |box#outlet| "Outlet"\n    inlet -> outlet "flows"\n  ]\n}\n|room#garden| "Garden"\n|room#kitchen| "Kitchen"\ngarden.outlet -> kitchen.inlet "carries"\n',
    'link_anonymous_scope': '|group| [ |box#a| "a"; |box#b| "b" ]\na -> b\n',
    'link_auto_create': 'users -> api -> db\napi -> cache "hit"\n',
    'link_clearance_wide': '{ clearance: 40; }\n|box#a| "A"\n|box#b| "B" { translate: 0 80; }\n|box#c| "C"\na -> b\n',
    'link_unroutable_stray': '{ gap: 0; clearance: 30; }\n|box#a| "A"\n|box#b| "B"\n|box#c| "C"\na:right -> c:left\n',
    'link_many_parallel': '{ direction: column; gap: 70; }\n|row| { gap: 20; } [ |box#a| "a"; |box#b| "b"; |box#c| "c"; |box#d| "d" ]\n|row| { gap: 20; } [ |box#w| "w"; |box#x| "x"; |box#y| "y"; |box#z| "z" ]\na -> z\nb -> y\nc -> x\nd -> w\na -> w\n',
    'link_label_cuts_wires': '{ direction: column; gap: 60; }\n|box#a| "A"\n|row| { gap: 10; } [ |box#b| "B"; |box#c| "C" ]\na -> b "a fairly long label"\na -> c "another long label"\n',
    'link_wavy_styled': '|box#a| "A"\n|box#b| "B"\na ~> b { stroke: --purple-deep; stroke-width: 3; }\n',
    'link_to_nested_child': '|group#outer| [ |group#inner| [ |box#leaf| "Leaf" ] ]\n|box#x| "X"\nx -> outer.inner.leaf:left\n',
    'link_hint_href': '|box#a| "A"\n|box#b| "B"\na -> b "go" { hint: "a tooltip"; href: "https://example.com/x?a=1&b=2"; }\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_compile(run, name):
    """CATCHES: a different link expansion, marker glyph geometry, orthogonal/natural/straight route, label placement or knockout mask, or a different routing warning."""
    r = run(["-"], input=CASES[name])
    assert outcome(r) == G(name)
