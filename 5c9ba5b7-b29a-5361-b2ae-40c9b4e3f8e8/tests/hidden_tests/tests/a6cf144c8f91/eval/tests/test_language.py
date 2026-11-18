"""Core language: primitives, box model, pin/translate/layer, text, colour
and gradients, expressions, the cascade, defines, icons, flex/grid/stack,
tables, trees, mindmaps and sequences."""

import pytest

from conftest import Goldens, outcome

G = Goldens(__file__)

CASES = {
    'prim_all_shapes': '|block| "block"\n|box| "box"\n|rect| "rect"\n|oval| "oval"\n|hex| "hex"\n|slant| "slant"\n|cyl| "cyl"\n|diamond| "diamond"\n',
    'prim_sized_shapes': '|oval| { width: 40; }\n|oval| { width: 60; height: 30; }\n|hex| { width: 80; height: 40; }\n|slant| { skew: -30; width: 90; height: 40; }\n|cyl| { width: 50; height: 80; }\n|diamond| { width: 70; height: 70; }\n',
    'prim_poly_path_line': '|poly| { points: 0 -30, 30 20, -30 20; fill: --amber-soft; }\n|path| { path: "M 0 0 L 40 0 L 40 30 Z"; stroke: --blue-deep; }\n|line| { points: 0 0, 40 20, 80 0; stroke-width: 3; radius: 8; }\n',
    'prim_parametric_line': '{ wave(a, f) = (u * 320, a * sin(2 * pi * f * u)); }\n|line| { points: wave(18, 2); samples: 48; stroke: --teal-deep; }\n|line| { points: (u * 200, 24 * cos(2 * pi * 3 * u)); samples: 16; }\n',
    'prim_modifiers': '|box| "multi" { multiple: 6; }\n|box| "multi2" { multiple: 4 8; }\n|box| "shadow" { shadow: 3; }\n|box| "shadow2" { shadow: 2 4 6 --purple-deep; }\n|box| "turned" { rotate: 30; }\n|box| "faint" { opacity: 0.4; }\n',
    'prim_stroke_styles': '|rect| "solid" { stroke-style: solid; }\n|rect| "dashed" { stroke-style: dashed; }\n|rect| "dotted" { stroke-style: dotted; }\n|rect| "center" { stroke-style: center; }\n|rect| "phantom" { stroke-style: phantom; }\n|line| { points: 0 0, 80 0; stroke-style: center; }\n',
    'box_model_padding': '|box| "asym" { padding: 4 4 20 4; }\n|box| "vh" { padding: 2 30; }\n|box| "trbl" { padding: 1 2 3 4; }\n|box| { width: 120; height: 30; } [ "floor grows" ]\n|box|\n|block|\n',
    'box_model_strokes_count': '|rect| { width: 100; height: 50; stroke-width: 4; }\n|rect| { width: 100; height: 50; stroke: none; stroke-width: 9; }\n',
    'pin_overlays': '|box#card| "Card" { width: 160; height: 90; } [\n  |badge| "NEW"\n  |block| "TL" { pin: top left; }\n  |block| "BR" { pin: bottom right; }\n  |block| "C" { pin: center; translate: 20 -10; }\n  |block| "B" { pin: bottom; layer: -1; }\n]\n',
    'translate_rotate_text': '|box| "a"\n"floating text" { translate: 10 -20; rotate: -15; }\n|box| "b" { translate: 0 30; }\n',
    'layer_order': '|box| "first" { layer: 2; fill: --rose-soft; }\n|box| "second" { translate: -40 10; fill: --sky-soft; }\n',
    'text_wrap': '|box| "A long sentence that will need to wrap across several lines to fit" { max-width: 120; }\n|box| "Supercalifragilisticexpialidocious" { max-width: 80; }\n',
    'text_properties': '|box| "Bold italic" { font-weight: bold; font-style: italic; }\n|box| "underline" { text-decoration: underline; }\n|box| "struck" { text-decoration: line-through; }\n|box| "shout" { text-transform: uppercase; }\n|box| "WHISPER" { text-transform: lowercase; }\n|box| "title case words" { text-transform: capitalize; }\n',
    'text_spacing': '|box| "S P A C E" { letter-spacing: 3; }\n|box| "line one\\nline two\\nline three" { line-spacing: 6; }\n|box| "shadowed" { text-shadow: 1 1 2 --gray-deep; }\n',
    'text_weights_and_mono': '|box| "normal" { font-weight: normal; }\n|box| "medium" { font-weight: medium; }\n|box| "semibold" { font-weight: 600; }\n|box| "code()" { font-family: "Google Sans Code"; }\n|box| "monospace" { font-family: "Fira Mono"; font-size: 12; }\n',
    'text_align_knobs': '|box| { direction: column; align: start; width: 200; } [ "left aligned\\nsecond longer line" ]\n|box| { justify: end; width: 200; } [ "right\\nlines" ]\n|box| [ |block| { justify: start; } [ "split\\nintent" ] ]\n',
    'text_root_font_size': '{ font-size: 20; color: --blue-ink; }\n|group#g| "Caption scales" [ |box#a| "A"; |box#b| "B" ]\na -> c "label scales"\n',
    'text_escapes_and_trim': '|box| "  trimmed  "\n|box| "tab\\there"\n|box| "quote \\" and backslash \\\\"\n|box| ""\n',
    'text_leaf_classed': '{ .card-title { font-size: 17; color: --teal-ink; } }\n|box| [ "Starter" .card-title { font-weight: bold; } "plain line" ]\n',
    'colour_palette_tiers': '{ direction: column; gap: 4; }\n|row| { gap: 4; } [ |box| { fill: --teal-wash; }; |box| { fill: --teal-soft; }; |box| { fill: --teal; }; |box| { fill: --teal-deep; }; |box| { fill: --teal-ink; } ]\n|row| { gap: 4; } [ |box| { fill: --yellow; }; |box| { fill: --pink-soft; }; |box| { fill: --indigo-deep; }; |box| { fill: --cyan-ink; } ]\n',
    'colour_literals': '|box| { fill: #f80; }\n|box| { fill: #ff880080; }\n|box| { fill: rebeccapurple; }\n|box| { fill: rgb(10, 20, 30); }\n|box| { fill: rgba(10, 20, 30, 0.5); }\n|box| { fill: hsl(280, 55%, 50%); }\n|box| { fill: oklch(0.72, 0.16, 25); }\n|box| { fill: oklch(0.5, 0.1, 200, 0.5); }\n|box| { fill: transparent; stroke: currentColor; }\n',
    'colour_roles': '{ fill: --bg; }\n|box| { fill: --fill; stroke: --stroke; }\n|box| { stroke: --stroke-dark; }\n|box| { stroke: --stroke-light; }\n|box| "a" { fill: --accent; color: --accent-text; }\n|box| "m" { color: --muted; }\n|box| "d" { stroke: --danger; }\n|box| "w" { stroke: --warn; }\n',
    'colour_user_variables': '{ --brand: #ff6600; --brand-soft: oklch(0.9, 0.05, 50); --alias: --brand; }\n|box| "brand" { fill: --brand-soft; stroke: --brand; color: --alias; }\n',
    'colour_gradients': '|box| "g" { fill: gradient(--rose, --sky); }\n|box| "lin" { fill: linear-gradient(90, --amber, --teal, --purple); }\n|box| "rad" { fill: radial-gradient(--lime, --green-deep); }\n|box| "st" { stroke: gradient(--red, --blue); stroke-width: 4; }\n|box| "same" { fill: gradient(--rose, --sky); }\n',
    'colour_hatch': '|rect| { width: 60; height: 40; fill: hatch(45); }\n|rect| { width: 60; height: 40; fill: hatch(-30, 6, --gray-deep); }\n|grid| { columns: 40, 40; gap: 2; gap-fill: gradient(--rose, --sky); } [ |box|; |box| ]\n',
    'colour_static_bakes': '{ --brand: #ff6600; }\n|box| "x" { fill: gradient(--rose, --sky); stroke: --brand; color: --teal-ink; }\n',
    'expr_math': '{ w = 120; r = 40; scale(n) = (100 * 1.2^n); }\n|box| { width: scale(3); height: (w / 2); }\n|box| { width: (max(10, min(80, r * 3))); height: (sqrt(1600) + abs(-5)); }\n|box| { width: (r > 30 ? 90 : 10); height: (round(33.6) + floor(2.9) + clamp(500, 0, 20)); }\n|box| { width: (exp(1) * 10 + ln(e) + log(1000)); height: (pow(2, 5) + 2 ^ 3); }\n|box| { width: (t = 3; t * t * 5); height: (sin(pi / 2) * 40 + cos(0) + tan(0)); }\n',
    'expr_scientific_literals': '|box| { width: (1e2 + 2.5e1); height: (1e-6 * 4e7); }\n',
    'expr_division_by_zero': '|box| { width: (1 / 0); }\n',
    'expr_unknown_function': '|box| { width: (frob(2)); }\n',
    'selectors_cascade': '{\n  |box| { fill: --gray-wash; }\n  |group| |box| { fill: --sky-wash; }\n  .hot { fill: --rose-wash; }\n  #hero { fill: --amber-wash; }\n  .hot.loud { stroke: --red-deep; stroke-width: 3; }\n}\n|box| "plain"\n|group#g| [ |box| "in group"; |box| "classed" .hot ]\n|box#hero| "hero" .hot\n|box| "own" .hot { fill: --lime-wash; }\n|box| "chain" .hot.loud\n',
    'defines_and_bodies': '{\n  |svc::box| { fill: --teal-wash; stroke: --teal-ink; }\n  |db::cyl| { fill: --rose-wash; }\n  |room::group| { gap: 10; } [ |box#in| "in"; |box#out| "out"; in -> out "flows" ]\n  |deep::svc| { radius: 0; }\n}\n|svc#api| "API"\n|db#pg| "Postgres"\n|room#garden| "Garden"\n|deep#d| "deep"\napi -> pg\ngarden.out -> api\n',
    'inheritance_depth_limit': '{\n  |t1::box| {}\n  |t2::t1| {}\n  |t3::t2| {}\n  |t4::t3| {}\n  |t5::t4| {}\n  |t6::t5| {}\n  |t7::t6| {}\n  |t8::t7| {}\n  |t9::t8| {}\n  |t10::t9| {}\n  |t11::t10| {}\n  |t12::t11| {}\n  |t13::t12| {}\n  |t14::t13| {}\n  |t15::t14| {}\n  |t16::t15| {}\n  |t17::t16| {}\n}\n|t17|\n',
    'implicit_nodes_near_miss': '|box#cat| "Cat"\n|box#Dog| "Dog"\ncta -> cat\ndog -> cat\n',
    'hint_and_href': '|box| "docs" { href: "https://example.com/?q=a&b=<c>"; hint: "Open the \\"docs\\""; }\n|oval| "tip" { hint: "just a tooltip"; }\n',
    'icons_basic': '|icon| "bell"\n|icon| { symbol: warning-circle; stroke: --amber-ink; }\n|icon| "heart" { fill: --rose-wash; stroke: --rose-ink; }\n|icon#tag| "bell" [ "3" ]\n|sign| "cloud"\n|box#cdn| "CDN" [ |icon| { symbol: cloud; } ]\n',
    'icons_fit_modes': '|icon| { symbol: user; fit: auto; width: 60; }\n|icon| { symbol: user; fit: contain; width: 60; }\n|icon| { symbol: user; fit: cover; width: 60; }\n|icon| { symbol: user; fit: stretch; width: 80; height: 40; }\n|icon| { symbol: house; stroke-width: 4; fill: none; }\n',
    'icons_unknown': '|icon| "belll"\n',
    'icons_missing_symbol': '|icon|\n',
    'image_url_and_data': '|image| { src: "https://example.com/logo.png"; width: 40; height: 30; }\n|image| { src: "data:image/png;base64,iVBORw0KGgo="; width: 20; height: 20; fit: cover; }\n',
    'image_requires_size': '|image| { src: "https://example.com/a.png"; }\n',
    'flex_align_justify': '|box| { direction: row; width: 300; height: 120; align: start; justify: evenly; } [ |box| "a"; |box| "bb" { height: 70; }; |box| "c" ]\n|box| { direction: column; width: 160; align: stretch; } [ |box| "x"; |box| "longer item" ]\n|box| { direction: row; width: 260; justify: end; align: end; height: 90; } [ |box| "p"; |box| "q" ]\n',
    'flex_gap_forms': '|row| { gap: 4; } [ |box|; |box|; |box| ]\n|column| { gap: 30; } [ |box|; |box| ]\n|box| { gap: 0 50; direction: row; } [ |box|; |box| ]\n',
    'grid_tracks': '|grid| { columns: 80, auto, repeat(2, 50); rows: 40, auto; gap: 6; } [\n  |box| "a"; |box| "b"; |box| "c"; |box| "d"\n  |box| "e" { span: 2; }; |box| "f" { cell: 4 2; }\n  ""\n  |box| "g" { span: 2 1; }\n]\n',
    'grid_align_per_column': '|grid| { columns: 100, 100, 100; align: start, center, end; gap: 4; } [ |box| "s"; |box| "c"; |box| "e"; |box| "start"; |box| "center"; |box| "end" ]\n',
    'grid_root_layout': '{ layout: grid; columns: repeat(3); gap: 20; }\n|box| "1"\n|box| "2"\n|box| "3"\n|box| "4"\n|box| "5" { cell: 3 3; }\n',
    'stack_layout': '{ layout: stack; padding: 10; }\n|oval| { width: 80; fill: --sky-soft; }\n|oval| { width: 50; fill: --sky; }\n|box| "off" { translate: 60 0; }\n|block| "pinned?" { translate: -60 -30; }\n',
    'stack_mm_units': '{ layout: stack; unit: mm; density: 10; padding: 25; cap = 0.9; bowl = 2.5; }\n|sketch#n| { draw: move(0, -3.4) arc(3.4, 3.4, 3.4) down(bowl) arc(cap, 180) up(bowl); mirror: y-axis; }\n|sketch#dots| { draw: move(11, -9) down(1) arc(cap, -180) up(1) arc(cap, -180) close(); pattern: grid(1, 3, 0, 3); }\n',
    'stack_node_form': '|stack| [ |oval| { width: 40; }; |rect| { width: 20; height: 20; } ]\n|box#a| "a"\n',
    'tables_basic': '|table#basket| { columns: 80, 140, 80; align: start, center, end; } [\n  "Fruit" "Quantity" "Notes"\n  "Apple" "12"       "fresh"\n  "Mango" "3" { color: --red-ink; }  "ripe"\n]\n',
    'tables_styled': '{\n  |table| |cell| { padding: 2 4; }\n  |table| |header| { fill: --teal-wash; }\n}\n|table| "Caption" { columns: 2; } [\n  "K" "V"\n  |cell#uid| "user_id"; "int"\n  |footer| "total"; "9"\n]\n',
    'entity_er': '|entity#users| "Users" { columns: auto, auto, auto; } [\n  "PK" "id"    "int"\n  ""   "email" "varchar"\n]\n|entity#orders| "Orders" [ "id" "int"; "user_id" "int" ]\nusers -o< orders\n',
    'note_and_caption_templates': '|note| "A folded note card"\n|group| "Region" [ |box| "inside"; |footnote| "foot" ]\n|box| "x" [ |caption| "Cap" ]\n',
    'tree_column': '{ layout: tree; }\n|topic#ceo| "CEO" [\n  |topic| "CTO" [ |topic| "Eng"; |topic| "Ops" ]\n  |topic| "CFO"\n]\n',
    'tree_row_outline': '{ layout: tree; direction: row; }\n|topic| "Root" [ |topic| "A" [ |topic| "A1"; |topic| "A2" ]; |topic| "B" ]\n',
    'tree_bilateral_sides': '{ layout: tree; direction: bilateral; }\n|topic#r| "Hub" [ |topic| "L1" { side: left; }; |topic| "R1"; |topic| "R2" { side: right; }; |topic| "L2" { side: left; } ]\n',
    'mindmap_preset': '|mindmap| "Launch" [\n  |topic#ship| "Shipping" [ |topic| "Weekly train"; |topic| "Hotfix lane" ]\n  |topic| "Quality" [ |topic| "Fuzzing" ]\n  |topic| "Docs"\n  |topic| "Community" [ |topic| "Forum"; |topic| "Meetups" ]\n]\n',
    'mindmap_cross_link_styled': '{\n  #ship |-| { stroke: --green-deep; }\n  .lini-level-2 { font-size: 12; }\n}\n|mindmap#m| "Root" [ |topic#ship| "Ship" [ |topic#x| "x" ]; |topic#y| "Y" [ |topic#z| "z" ] ]\nm.ship.x:right --- m.y.z:right "relates" { along: 0.8; }\n',
    'sequence_basic': '{ layout: sequence; }\n|box#user| "Customer" { fill: --rose-wash; stroke: --rose-deep; } [ |icon| { symbol: user; fill: none; stroke: --rose-deep; } ]\n|box#shop| "Storefront"\n|cyl#db| "Orders"\nuser -> shop "place order"\n|loop| "each item" [\n  shop -> db "reserve stock"\n  db --> shop "in stock"\n]\n|note| "rate-limited" { place: over shop db; }\nshop ~> user "email"\nshop -> shop "audit"\n',
    'sequence_frames': '{ layout: sequence; gap: 30 60; }\n|box#a| "A"\n|box#b| "B"\n|alt| "ok?" [\n  a -> b "yes"\n  |else| "no"\n  a -> b "retry"\n]\n|opt| "maybe" [ b --> a "cached" ]\n|note| "left" { place: left a; }\n|note| "right" { place: right b; }\n|note| "over" { place: over a; }\n',
    'sequence_auto_participants': '{ layout: sequence; }\nalice -> bob "hi"\nbob --> alice "hey"\nalice -> |cyl#store| "save"\n',
    'sequence_node_form': '|sequence| "Handshake" [ |box#c| "C"; |box#s| "S"; c -> s "SYN"; s --> c "SYN-ACK"; c -> s "ACK" ]\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_compile(run, name):
    """CATCHES: a compiler that sizes, places, paints or serialises any of these core constructs differently from the reference (or diagnoses them differently)."""
    r = run(["-"], input=CASES[name])
    assert outcome(r) == G(name)
