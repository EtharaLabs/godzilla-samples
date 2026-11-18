"""Engineering drawings, floor plans and schematics (SPEC 15/16): dimensions,
leaders, mates, the pen, patterns, threads, breaks, sheets, GD&T, walls,
openings, fixtures, parts, pins, wires and labels."""

import pytest

from conftest import Goldens, outcome

G = Goldens(__file__)

CASES = {
    'drw_plate_holes': '{ layout: drawing; }\n|rect#plate| { width: 120; height: 70; } [\n  |hole#pin| { width: 10; translate: -35 20; pattern: grid(2, 1, 70, 0); }\n  |hidden#bore| { draw: move(-20, -35) down(70); }\n]\nplate:left (-) plate:right { side: bottom; }\nplate:left (-) plate.pin { side: top; }\nplate.pin (o)\nplate.pin.2 <- "THRU"\n',
    'drw_revolve_dims': '{ layout: drawing; }\n|sketch#body| {\n  draw: move(-80, 0)\n        up(14) right(50):neck fillet(3):r1 up(8) right(60):mid fillet(3) down(8) right(50) down(14);\n  revolve: x-axis;\n}\nbody:left (-) body:right { side: bottom; }\nbody:neck (o) { side: left; tol: h6; }\nbody:r1 (o)\nbody:mid (o) { tol: +0.2 -0.05; }\n',
    'drw_tolerance_forms': '{ layout: drawing; }\n|rect#r| { width: 80; height: 40; }\nr:left (-) r:right { tol: 0.1; }\nr:top (-) r:bottom { side: left; tol: +0.2 -0.05; }\nr:top-left (-) r:bottom-right\n',
    'drw_project_axes': '{ layout: drawing; }\n|rect#a| { width: 30; height: 30; }\n|oval#b| { width: 20; translate: 70 40; }\na:center (-) b { project: horizontal; side: top; }\na:center (-) b { project: vertical; side: right; }\na:center (-) b\n',
    'drw_angle_dim': '{ layout: drawing; }\n|sketch#w| { draw: move(0, 0) right(60):base angle(45, 50):slope; }\nw:base (<) w:slope\n',
    'drw_radial_pattern': '{ layout: drawing; }\n|oval#flange| { width: 120; } [\n  |hole#bolt| { width: 10; pattern: radial(6, 40); }\n  |hole#bore| { width: 30; thread: 2; }\n]\nflange.bolt (o)\nflange.bore (o)\nflange:top (o)\nflange.bolt.3 <- "TAP"\n',
    'drw_leaders': '{ layout: drawing; }\n|rect#plate| { width: 100; height: 50; } [ |hole#h| { width: 12; } ]\nplate.h <- "THRU"\nplate *- "Ra 1.6"\nplate:top >- "A"\nplate:bottom <- [ "styled" { translate: 30 24; } ]\n',
    'drw_mates': '{ layout: drawing; }\n|rect#barrel| { width: 80; height: 30; }\n|rect#nozzle| { width: 20; height: 14; }\n|rect#cap| { width: 10; height: 40; }\nnozzle:left || barrel:right { gap: 4; }\ncap:right || barrel:left { gap: -2; }\nbarrel:left (-) nozzle:right\n',
    'drw_mirror_forms': '{ layout: drawing; }\n|sketch#half| { draw: move(0, -20) right(30) down(40) left(30); mirror: y-axis; }\n|sketch#ear| { draw: move(40, -10) right(10) down(10) close(); mirror: y-axis x-axis; translate: 0 60; }\n|sketch#ang| { draw: move(0, 0) right(20) down(20) close(); mirror: 45; translate: 0 120; }\n',
    'drw_pen_calls': '{ layout: drawing; }\n|sketch#p| { draw: move(0, 0) right(40) chamfer(4) down(30) fillet(6) left(40) line(-10, -15) curve(0, -5, 5, -10, 10, -15) close() move(15, 10) circle(5):bore point():c; }\np:bore (o)\np:left (-) p:right\n',
    'drw_pen_arcs': '{ layout: drawing; }\n|sketch#a| { draw: move(0, 0) right(20) arc(10, 90) down(10) arc(20, 20, 20) arc(-10, 0, -12) close(); }\n',
    'drw_break': '{ layout: drawing; }\n|sketch#shaft| { draw: move(-150, 0) up(10) right(300) down(10); revolve: x-axis; break: -100 100; }\nshaft:left (-) shaft:right\n',
    'drw_thread_callout': '{ layout: drawing; }\n|sketch#bar| { draw: move(-60, 0) up(10) chamfer(1.5) right(40):m20 point():a right(60) chamfer(1.5) down(10); revolve: x-axis; thread: m20 1.5; }\nbar:m20 <-\nbar:m20 <- "LH" { side: top; }\n',
    'drw_scale_units': '{ layout: drawing; unit: cm; scale: 2; }\n|rect#r| { width: 10; height: 4; }\nr:left (-) r:right { format: decimal 1; }\n',
    'drw_format_fraction_dim': '{ layout: drawing; unit: in; }\n|rect#r| { width: 2.375; height: 1.5; }\nr:left (-) r:right { format: fraction 8; }\nr:top (-) r:bottom { format: decimal 3; }\n',
    'drw_huge_scale_hint': '{ layout: drawing; }\n|rect#beam| { width: 5000; height: 100; }\n',
    'drw_page_sheet': '|page| { sheet: a5; align: origin; } [\n  |drawing#side| "SIDE" { scale: 2; } [ |rect#b| { width: 30; height: 12; }; b:left (-) b:right ]\n  |drawing#end| "END" [ |oval#c| { width: 12; }; c:top (o) ]\n  |title-block| "Bracket" { drawing-number: "D-1"; revision: "B"; sheet-number: "1/1"; date: "2026-01-02"; author: "AB"; approved: "CD"; status: "draft"; }\n]\nside.b:right - end.c:left\n',
    'drw_page_landscape_ansi': '|page| { sheet: b; } [ |drawing| [ |rect| { width: 40; height: 20; } ] ]\n',
    'drw_page_custom_size': '|page| { sheet: a4 landscape; width: 250; } [ |drawing| [ |oval| { width: 30; } ]; |title-block| { columns: 60, auto; } [ "Title" "plain"; "Scale" "1:1" ] ]\n',
    'drw_section_and_detail': '|row| { align: origin; gap: 30; } [\n  |drawing#base| "BASE" [\n    |rect#p| { width: 80; height: 40; } [ |hole#h| { width: 10; translate: 20 0; } ]\n    |plane#a| "A" { at: 10; }\n    |magnifier#c| "C" { width: 24; translate: 20 0; }\n  ]\n  |drawing#sec| { of: a; } [ |rect| { width: 40; height: 30; fill: hatch(45); } ]\n  |drawing#det| { of: c; scale: 3; } [ p.h (o) ]\n]\n',
    'drw_gdt': '{ layout: drawing; }\n|sketch#body| { draw: move(-50, 0) up(15) right(100):seat down(15); revolve: x-axis; }\nbody:seat >- "A"\n|surface-finish#sf| "Ra 1.6" { symbol: machined; }\nsf || body:top\n|surface-finish#sf2| "Ra 3.2" { symbol: prohibited; translate: 60 -40; }\nbody:left (-) body:right [ |feature-control| "circular-runout" { tol: 0.05; datums: A; } ]\n|feature-control#fc| "position" { tol: 0.05; datums: A; zone: diameter; material: maximum; modifiers: projected 10; translate: 0 70; }\n|feature-control#fc2| { translate: 0 110; } [ |control| "position" { tol: 0.2; datums: A; }; |control| "position" { tol: 0.05; datums: A; } ]\n|datum| "B" { translate: -70 50; }\n',
    'drw_gdt_errors': '{ layout: drawing; }\n|rect#r| { width: 40; height: 20; }\n|feature-control| "flatness" { tol: 0.1; datums: A; }\n',
    'drw_balloon_note': '{ layout: drawing; }\n|rect#housing| { width: 80; height: 50; }\n|balloon#b1| "1" { translate: 70 -40; }\n|note#n| "Deburr all edges" { translate: -80 50; }\nb1 -* housing:top-right\nhousing:bottom-left <- n\nhousing -> b1\n',
    'drw_chrome_removed': '{\n  layout: drawing;\n  |sketch| |centerline| { stroke: none; fill: none; }\n  |hole| { stroke: --red-deep; }\n}\n|sketch#s| { draw: move(-30, 0) up(10) right(60) down(10); revolve: x-axis; } [ |hole| { width: 6; } ]\n',
    'drw_errors_fan_blocked': '{ layout: drawing; }\n|rect#plate| { width: 100; height: 50; }\nplate:left & plate:right <- "2x EDGE"\n',
    'drw_leader_fan': '{ layout: drawing; }\n|rect#plate| { width: 100; height: 50; } [ |hole#a| { width: 6; translate: -30 0; }; |hole#b| { width: 6; translate: 30 0; } ]\nplate.a & plate.b <- "2x THRU"\n',
    'drw_errors_unknown_anchor': '{ layout: drawing; }\n|rect#r| { width: 40; height: 20; }\nr:topleft (-) r:right\n',
    'drw_errors_segment': '{ layout: drawing; }\n|sketch#s| { draw: move(0, 0) right(10):edge down(10); }\ns:egde (-) s:right\n',
    'drw_errors_perpendicular': '{ layout: drawing; }\n|rect#r| { width: 40; height: 20; }\nr:left (-) r:top\n',
    'drw_errors_mate_cycle': '{ layout: drawing; }\n|rect#a| { width: 10; height: 10; }\n|rect#b| { width: 10; height: 10; }\na:right || b:left\nb:right || a:left\n',
    'drw_errors_pen': '|sketch| { draw: move(0, 0) arc(5, 90); }\n',
    'drw_errors_pen_fillet': '|sketch| { draw: move(0, 0) fillet(3) right(10); }\n',
    'drw_errors_pattern_index': '{ layout: drawing; }\n|rect#p| { width: 60; height: 20; } [ |hole#h| { width: 4; pattern: grid(2, 1, 20, 0); } ]\np.h.5 <- "x"\n',
    'drw_errors_empty': '|drawing|\n',
    'drw_errors_leader_no_text': '{ layout: drawing; }\n|rect#r| { width: 40; height: 20; }\nr <-\n',
    'drw_errors_dim_gap': '{ layout: drawing; }\n|rect#r| { width: 40; height: 20; }\nr:left (-) r:right { gap: 4; }\n',
    'fp_studio': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#outer| {\n  draw: move(0, 0) right(7.2):north down(4.8):east left(7.2):south close():west;\n} [\n  |window| { on: north; at: 2.7; width: 1.6; }\n  |door#entry| "D1" { on: south; at: 1.05; width: 0.95; swing: right; }\n]\n|partition#bathwall| { draw: move(4.9, 0) down(2.3):face right(2.3):side; } [ |door| { on: side; at: 0.15; width: 0.8; } ]\n|bed| { rotate: 90; translate: 1.15 1.05; }\n|sofa| { symbol: two; rotate: 90; translate: 0.6 3.4; }\n|dining| { symbol: round; translate: 3.3 3.3; }\n|appliance| "F" { symbol: fridge; translate: 6.8 2.8; }\n|bath| { symbol: shower; translate: 6.6 0.6; }\n|bath| { symbol: toilet; rotate: 90; translate: 5.35 0.5; }\n"STUDIO 27 m2" { translate: 2.2 2.2; }\nouter:west-in (-) bathwall:face-out { side: top; }\nbathwall:face-in (-) outer:east-in { side: top; }\nouter:north-in (-) outer:south-in { side: right; }\n',
    'fp_wall_joins': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#a| { draw: move(0, 0) right(5):north; }\n|wall#b| { draw: move(5, 0) down(4):east; }\n|wall#c| { draw: move(2.5, 0) down(4):mid; thickness: 0.1; }\n|wall#d| { draw: move(0, 4) right(5); fill: hatch(45); }\n|wall#e| { draw: move(0, 0) down(4); fill: --bg; stroke: --stroke-dark; }\n',
    'fp_curved_wall': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#bay| { draw: move(0, 0) right(3) arc(2, 0, 1.2) right(3):run; } [ |window| { on: run; at: 0.5; width: 1; } ]\n',
    'fp_openings_variety': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#w| { draw: move(0, 0) right(10):long down(3):short; } [\n  |door| { on: long; at: 0.5; width: 0.9; hinge: end; swing: left; }\n  |door| { on: long; at: 2.5; width: 1.6; symbol: double; }\n  |door| { on: long; at: 5; width: 1.8; symbol: sliding; }\n  |window| { on: long; at: 8; width: 1.2; }\n  |window| { on: short; at: 1; width: 1; }\n]\n',
    'fp_fixtures': '{ layout: floorplan; unit: m; scale: 0.02; }\n|bed| { symbol: king; translate: 1 1; }\n|bed| { symbol: single; translate: 4 1; }\n|sofa| { symbol: corner; translate: 7 1; }\n|sofa| { symbol: stool; translate: 9 1; }\n|dining| { symbol: six; translate: 1 4; }\n|bath| { symbol: tub; translate: 4 4; }\n|bath| { symbol: double-sink; translate: 6 4; }\n|appliance| "W/D" { symbol: washer; translate: 8 4; }\n|appliance| "DW" { symbol: dishwasher; translate: 9 4; }\n|appliance| { symbol: stove; translate: 10 4; }\n|stairs| { steps: 12; translate: 1 7; }\n|bed| { width: 2.5; translate: 5 7; }\n',
    'fp_errors': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#w| { draw: move(0, 0) right(4):a; } [ |door| { on: a; at: 3.5; width: 1; } ]\n',
    'fp_errors_curve': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#w| { draw: move(0, 0) curve(1, 0, 2, 1, 3, 1); }\n',
    'fp_errors_door_outside': '{ layout: floorplan; unit: m; scale: 0.02; }\n|door| { width: 1; }\n',
    'fp_errors_stairs': '{ layout: floorplan; unit: m; scale: 0.02; }\n|stairs| { steps: 1; }\n',
    'fp_errors_face_name': '{ layout: floorplan; unit: m; scale: 0.02; }\n|wall#w| { draw: move(0, 0) right(4):a-in; }\n',
    'sch_basic': '{ layout: schematic; |vcc::label| { symbol: power; } [ "5V" ] }\n|component#u1| "AMS1117-3.3" [\n  |pin#vin| { side: left; number: 3; }\n  |space| { span: 2; }\n  |pin#en| "EN/~SHDN" { side: left; number: 4; }\n  |pin#gnd| { side: bottom; number: 1; }\n  |pin#vout| { side: right; number: 2; }\n]\n|J#j1| "3V3 OUT" { pins: 4; rotate: 180; }\n|C#c1| "22u"\n|label#tach| "TACH"\nu1.vin - |vcc|\nu1.vout - c1 - |gnd|\nu1.vout - j1.p3 "3V3"\nj1.p1 -> "NSTDBY"\nu1.en - "EN"\nj1.p2 - tach; tach - j1.p4\n',
    'sch_discretes': '{ layout: schematic; columns: 4; }\n|R#r1| "10k"\n|C#c1| "100n" { symbol: polarized; }\n|L#l1| "4u7"\n|D#d1| { symbol: zener; }\n|LED#led1| "red"\n|Q#q1| { symbol: npn; }\n|Q#q2| { symbol: nfet; }\n|Y#y1| "8MHz"\n|F#f1| "1A"\n|FB#fb1|\n|SW#sw1|\n|BT#bt1| "3V"\n|V#v1| "5V"\n|I#i1| "1mA"\n|M#m1|\n|BZ#bz1|\n|TP#tp1|\n|opamp#a1|\n',
    'sch_wires_chains': '{ layout: schematic; }\n|component#u2| "REG" [ |pin#vin| { side: left; }; |pin#en| { side: left; }; |pin#out| { side: right; }; |pin#gnd| { side: bottom; } ]\n|R#r5| "100k"\n|R#r6| "10k" { rotate: 270; }\n|Q#q1| { symbol: nfet; }\n|D#d1|\nu2.en - r5 - u2.vin\nu2.out - r6 - |gnd|\nq1.s - d1.k - |gnd|\nu2.gnd - |gnd|\nu2.out - |nc|\n',
    'sch_labels_shapes': '{ layout: schematic; }\n|J#j| { pins: 6; mirror: y-axis; }\n|label#a| "LEFT" { shape: left; }\n|label#b| "RIGHT" { shape: right; }\n|label#c| "BOTH" { shape: both; }\n|label#d| "ROUND" { shape: round; }\n|label#e| { symbol: earth; }\n|label#f| { symbol: chassis; }\nj.p1 - a\nj.p2 - b\nj.p3 - c\nj.p4 - d\nj.p5 - e\nj.p6 - f\n',
    'sch_label_wire_markers': '{ layout: schematic; }\n|J#j| { pins: 5; }\nj.p1 - "PLAIN" { width: 60; }\nj.p2 -> "OUT"\nj.p3 -< "IN"\nj.p4 -<> "BIDI"\nj.p5 -* "DOT"\n',
    'sch_regions_on_page': '{ |region::group| { layout: schematic; } }\n|page| { sheet: a4 landscape; layout: grid; columns: 2; } [\n  |region#pwr| "Power" [ |R#r1| "1k"; |C#c1| "1u"; r1.p2 - c1.p1; c1.p2 - |gnd| ]\n  |region#io| "IO" [ |J#j1| { pins: 2; }; j1.p1 - |gnd| ]\n]\n',
    'sch_cell_tracks': '{ layout: schematic; gap: 120; }\n|component#u1| { cell: 1 1; } [ |pin#a| { side: right; }; |pin#b| { side: right; } ]\n|component#u2| { cell: 3 1; } [ |pin#a| { side: left; }; |pin#b| { side: left; } ]\nu1.a - u2.a\nu1.b - u2.b "BUS"\n',
    'sch_prefix_define': '{ |amp::opamp| { prefix: "A"; } }\n|schematic#s| [ |amp|; |amp|; |R|; |R| ]\n',
    'sch_errors_unknown': '{ layout: schematic; }\n|R#r1|\nr1.p1 - r2.p1\n',
    'sch_errors_side_terminal': '{ layout: schematic; }\n|R#r1|\n|R#r2|\nr1.p1:left - r2.p1\n',
    'sch_errors_rotate': '|R#r1| { rotate: 45; }\n',
    'sch_errors_variant': '|D#d1| { symbol: zenr; }\n',
    'sch_errors_pin_inline': 'x - |component#U9|.p4\n',
    'sch_errors_clearance': '{ layout: schematic; clearance: 30; }\n|R#r1|\n|R#r2|\nr1.p2 - r2.p1\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_compile(run, name):
    """CATCHES: a drawing/floorplan/schematic engine that measures, composes dimension text, packs rows, folds pen paths, places parts or routes wires differently — or reports their errors differently."""
    r = run(["-"], input=CASES[name])
    assert outcome(r) == G(name)
