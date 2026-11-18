"""Charts and pies (SPEC 14): series kinds, bar modes, directions, scales
(linear, log, time), formats, bands, marks, tooltips and colour walks."""

import pytest

from conftest import Goldens, outcome

G = Goldens(__file__)

CASES = {
    'chart_format_decimal': '|chart| { format: decimal 2; } [ |line| { data: 0 0.125, 1 1234.5, 2 0.00042; } ]\n',
    'chart_format_significant': '|chart| { format: significant 3; } [ |line| { data: 0 0.125, 1 1234.5, 2 0.00042; } ]\n',
    'chart_format_scientific': '|chart| { format: scientific 2; } [ |line| { data: 0 0.125, 1 1234.5, 2 0.00042; } ]\n',
    'chart_format_engineering': '|chart| { format: engineering 1; } [ |line| { data: 0 0.125, 1 1234.5, 2 0.00042; } ]\n',
    'chart_format_percent': '|chart| [ |axis#v| { side: left; format: percent 0; }; |line| { data: 0 0.1, 1 0.45, 2 0.9; axis: v; } ]\n',
    'chart_format_fraction': '|chart| { format: fraction 8; } [ |line| { data: 0 0.125, 1 0.75, 2 2.375; } ]\n',
    'chart_bars_stacked': '|chart| "Stacked" { categories: "Q1", "Q2", "Q3"; bars: stacked; } [\n  |bars| "A" { data: 3, 5, 2; }\n  |bars| "B" { data: 1, 2, 4; }\n  |bars| "C" { data: 2, 2, 2; }\n]\n',
    'chart_bars_overlay': '|chart| { categories: "x", "y"; bars: overlay; } [\n  |bars| "Plan" { data: 10, 12; }\n  |bars| "Actual" { data: 8, 14; radius: 3; }\n]\n',
    'chart_bars_row': '|chart| { categories: "alpha", "beta", "gamma"; direction: row; } [\n  |bars| { data: 4, -2, 7; }\n]\n',
    'chart_per_datum_fill': '|chart| { categories: "a", "b", "c", "d"; } [\n  |bars| { data: 4, 8, 6, 2; fill: auto, auto, --red, auto; }\n  |dots| { data: 3, 5, 9, 1; stroke: auto, --blue, auto, auto; }\n]\n',
    'chart_radial_radar': '|chart| "Skills" { categories: "Speed", "Power", "Range", "Armor", "Luck"; direction: radial; } [\n  |line| "Hero" { data: 8, 6, 7, 3, 9; }\n  |area| "Foe" { data: 5, 9, 4, 8, 2; }\n]\n',
    'chart_radial_bars': '|chart| { categories: "N", "E", "S", "W"; direction: radial; } [ |bars| { data: 3, 5, 2, 4; } ]\n',
    'chart_curves': '|chart| { categories: "1", "2", "3", "4", "5"; } [\n  |line| "linear" { data: 1, 4, 2, 5, 3; }\n  |line| "smooth" { data: 2, 5, 3, 6, 4; curve: smooth; marker: dot; }\n  |line| "step" { data: 0, 3, 1, 4, 2; curve: step; marker: diamond; }\n]\n',
    'chart_area_baseline': '|chart| { categories: "a", "b", "c", "d"; } [ |area| { data: 50, 70, 45, 80; baseline: 40; curve: smooth; } ]\n',
    'chart_fn_samples': '{ ramp(s) = min(100, 25 + 1.572*(x/s) + 0.0142*(x/s)^2); }\n|chart| { samples: 12; } [\n  |axis| { side: bottom; range: 0 200; }\n  |area| "Steel" { fn: ramp(1); }\n  |line| "Aluminum" { fn: ramp(1/0.7); }\n]\n',
    'chart_log_axis': '|chart| [\n  |axis#y| "Count" { side: left; scale: log; }\n  |line| { data: 1 3, 2 40, 3 900, 4 25000; axis: y; marker: circle; }\n]\n',
    'chart_log_ticks_explicit': '|chart| [\n  |axis#y| { side: left; scale: log; ticks: 1, 10, 100, 1000; }\n  |dots| { data: 1 2, 2 30, 3 700; axis: y; }\n]\n',
    'chart_time_axis_auto': '|chart| [ |line| { data: "2026-01-01" 18, "2026-02-01" 25, "2026-03-15" 21, "2026-06-30" 30; } ]\n',
    'chart_time_axis_step': '|chart| [\n  |axis#t| { side: bottom; scale: time; step: 2 week; }\n  |line| { data: "2026-03-01" 1, "2026-03-20" 4, "2026-04-15" 2; }\n]\n',
    'chart_time_hours': '|chart| [ |line| { data: "2026-05-04T08:00" 3, "2026-05-04T12:30Z" 7, "2026-05-04T18:15+02:00" 5; } ]\n',
    'chart_time_format_preset': '|chart| { format: month; } [ |line| { data: "2025-11-01" 1, "2026-02-01" 2, "2026-07-01" 3; } ]\n',
    'chart_range_reverse': '|chart| [\n  |axis#rank| "Rank" { side: left; range: 50 1; }\n  |line| { data: 1 40, 2 22, 3 5; axis: rank; }\n]\n',
    'chart_range_auto_end': '|chart| { categories: "a", "b", "c"; } [\n  |axis#v| { side: left; range: 0 auto; step: 25; unit: "%"; }\n  |bars| { data: 20, 55, 90; axis: v; }\n]\n',
    'chart_dual_axis': '|chart| { categories: "Jan", "Feb", "Mar"; } [\n  |axis#rev| "Revenue" { side: left; }\n  |axis#cnt| "Orders" { side: right; gridlines: none; }\n  |bars| "Revenue" { data: 120, 180, 150; axis: rev; }\n  |line| "Orders" { data: 3, 7, 5; axis: cnt; marker: dot; }\n]\n',
    'chart_gridline_colour': '|chart| { categories: "a", "b"; } [\n  |axis| { side: left; gridlines: --amber; stroke: --gray-deep; color: --gray-ink; }\n  |bars| { data: 2, 3; }\n]\n',
    'chart_band_and_mark': '|chart| [\n  |axis#t| "Time (s)" { side: bottom; }\n  |axis#temp| "Temp" { side: left; }\n  |band| "Inject" { range: 1.4 3.1; axis: t; fill: --rose; }\n  |band| "Hold" { range: 3.1 5; axis: t; fill: none; }\n  |line| { data: 0 20, 2 80, 4 120, 6 60; axis: temp; }\n  |mark| "100 C" { at: 100; axis: temp; stroke: --amber-deep; stroke-style: dashed; color: --amber-ink; }\n  |mark| "peak" { at: 4 120; axis: temp; }\n  |mark| "safe" { at: 5 40; axis: temp; marker: none; }\n]\n',
    'chart_band_segments': '|chart| [\n  |axis#t| { side: bottom; range: 0 6; }\n  |band| "Ramp" { range: 0 2; axis: t; }\n  |band| "Hold" { range: 2 4; axis: t; }\n  |band| "Cool" { range: 4 6; axis: t; }\n  |line| { fn: (u * 10), 10, (10 - 8 * u^2); }\n]\n',
    'chart_labels_tooltips': '|chart| [\n  |line| "GLM" { data: 35 63, 42 72, 84 75; labels: "Non-Thinking", "High", "Max"; marker: circle; tooltip: always; }\n  |dots| "Other" { data: 40 60, 70 66; labels: "A", "B"; tooltip: hover; }\n]\n',
    'chart_tooltip_none': '|chart| { tooltip: none; categories: "a", "b"; } [ |bars| "S" { data: 1, 2; labels: "one", "two"; } ]\n',
    'chart_bubbles': '|chart| [\n  |bubble| "Alpha" { at: 10 20; value: 30; }\n  |bubble| "Beta" { at: 30 40; value: 120; fill: --sky-soft; }\n  |bubble| "G" { at: 20 10; value: 5; }\n]\n',
    'chart_size_and_gap': '|chart| "Sized" { width: 500; height: 160; gap: 30; clearance: 10; categories: "a", "b", "c"; } [ |bars| "x" { data: 1, 2, 3; }; |bars| "y" { data: 3, 2, 1; } ]\n',
    'chart_negative_values': '|chart| { categories: "a", "b", "c", "d"; } [ |bars| { data: -5, 3, -1.5, 8; }; |line| { data: -2, -4, 6, 1; } ]\n',
    'chart_dots_markers': '|chart| [ |dots| { data: 1 1, 2 4, 3 9; marker: diamond; width: 12; }; |dots| { data: 1 2, 2 3, 3 5; marker: dot; } ]\n',
    'pie_basic': '|pie| "Spend" [\n  |slice| "Ads" { value: 40; }\n  |slice| "SEO" { value: 30; }\n  |slice| "Direct" { value: 30; }\n]\n',
    'pie_donut_paint': '|pie| { hole: 0.5; width: 200; } [\n  |slice| "A" { value: 1; fill: --teal; }\n  |slice| "B" { value: 2; stroke: none; }\n  |slice| "C" { value: 0; }\n  |slice| "D" { value: 3.5; }\n]\n',
    'pie_zero_total': '|pie| [ |slice| { value: 0; }; |slice| { value: 0; } ]\n',
    'chart_categories_default': '|chart| [ |bars| { data: 5, 3, 8, 1, 4, 6; } ]\n',
    'chart_styled_chrome': '|chart| "Styled" { fill: --gray-wash; stroke: --gray-deep; font-size: 12; categories: "a", "b"; } [ |bars| "one" { data: 1, 2; }; |bars| "two" { data: 2, 1; } ]\n',
    'chart_step_number': '|chart| { categories: "a", "b", "c"; } [ |axis#y| { side: left; step: 0.5; }; |line| { data: 0.2, 1.7, 1.1; axis: y; } ]\n',
    'chart_radial_band_error': '|chart| { direction: radial; categories: "a", "b", "c"; } [ |axis#v|; |band| { range: 1 2; axis: v; }; |line| { data: 1, 2, 3; } ]\n',
    'chart_time_step_number_error': '|chart| [ |axis#t| { side: bottom; scale: time; step: 7; }; |line| { data: "2026-01-01" 1, "2026-02-01" 2; } ]\n',
    'chart_invalid_date': '|chart| [ |line| { data: "2026-13-45" 1, "2026-02-01" 2; } ]\n',
    'chart_log_nonpositive': '|chart| [ |axis#y| { side: left; scale: log; }; |line| { data: 1 0, 2 5; axis: y; } ]\n',
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_compile(run, name):
    """CATCHES: a chart engine that computes a different domain, nice ticks, tick text (format/unit/calendar), plot inset, palette walk, series geometry, legend or tooltip markup — or reports a chart error differently."""
    r = run(["-"], input=CASES[name])
    assert outcome(r) == G(name)
