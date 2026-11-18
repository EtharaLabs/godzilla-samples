"""Point clouds as elements: `point_cloud`'s placing (centre or file origin, at, offset, angle, level), units, spacing,
a survey's stations brought in as one scan, a held scan placed again, edits, the project file, and the plan drawing.

What a scan keeps is read from the saved project: its points (little-endian f32 about its middle, mm) and colours are
unpacked here, so the comparison doesn't depend on how they were compressed."""

import base64
import hashlib
import json
import re
import struct
import zlib

from conftest import normalize, png_pixels

# A box 4 m by 3 m by 2.5 m in survey coordinates, metres, its corners coloured.
BOX = "500000 7000000 10 255 0 0\n500004 7000000 10 0 255 0\n500004 7000003 10 0 0 255\n500000 7000003 12.5 255 255 255\n"
LONG_FLOAT = re.compile(r"-?\d+\.\d{7,}")


def rounded(text):
    """Long decimals (sines and cosines) rounded to six places, which every machine agrees on."""
    return LONG_FLOAT.sub(lambda m: repr(round(float(m.group(0)), 6)), text)


def result(r):
    return (f"exit: {r.returncode}\n--- stdout\n{normalize(rounded(r.stdout.decode()))}"
            f"--- stderr\n{normalize(r.stderr.decode())}")


def scans_of(project):
    """Each scan a saved project holds: its source, stations, origin, the points it read, then its points and colours."""
    p = json.loads(project.read_text())
    out = []
    for name, c in p["clouds"].items():
        raw = zlib.decompress(base64.b64decode(c["points"]))
        pts = [struct.unpack_from("<3f", raw, i) for i in range(0, len(raw), 12)]
        cols = None
        if "colours" in c:
            cb = zlib.decompress(base64.b64decode(c["colours"]))
            cols = [list(cb[i:i + 3]) for i in range(0, len(cb), 3)]
        out.append(f"scan {name}: source={c['source']} origin={c['origin']} read={c['read']} kept={len(pts)}"
                   f" stations={json.dumps(c.get('stations', []))}")
        for i, q in enumerate(pts[:40]):
            out.append(f"  {q[0]!r} {q[1]!r} {q[2]!r}" + ("" if cols is None else f" rgb={cols[i]}"))
        if len(pts) > 40:
            out.append(f"  ... points sha256={hashlib.sha256(raw).hexdigest()}")
    return "\n".join(out) + "\n"


def script(workdir, *lines):
    (workdir / "script.txt").write_text("\n".join(lines) + "\n")
    return ["--script", "script.txt"]


def test_a_scan_comes_in_with_its_middle_on_the_origin_and_its_foot_on_the_level(run, workdir, golden):
    """CATCHES: a rewrite whose point_cloud reply or element differs (its name from the file's stem, the points kept and
    read, where its middle was in the file), that doesn't stand its lowest point on the level (offset), or that keeps
    other points or colours about another middle."""
    (workdir / "box.xyz").write_text(BOX)
    r = run(["run", *script(workdir, 'point_cloud {"path": "box.xyz"}', 'elements {"category": "pointcloud"}',
                            'point_cloud {"cloud": "box", "level": "Level 2"}', 'elements {"category": "pointcloud"}'),
             "--save", "p.bimcraft"])
    golden.check(result(r) + "--- scans\n" + scans_of(workdir / "p.bimcraft"), "default_placing.txt")


def test_origin_to_origin_keeps_the_files_coordinates_where_a_model_can_hold_them(run, workdir, golden):
    """CATCHES: a rewrite whose `origin: file` doesn't place the scan where its coordinates put it (at its middle, its
    height over the level), places a survey's far coordinates instead of refusing them, or takes another word."""
    (workdir / "near.xyz").write_text("1 2 0\n3 4 1\n")
    (workdir / "box.xyz").write_text(BOX)
    r = run(["run", *script(workdir,
                            'point_cloud {"path": "near.xyz", "origin": "file"}',
                            'point_cloud {"cloud": "near", "origin": "file", "level": "Level 2"}',
                            'point_cloud {"cloud": "near", "origin": "centre"}',
                            'point_cloud {"cloud": "near", "origin": "center", "at": [10000, 0], "offset": 3000, "angle": 90}',
                            'point_cloud {"cloud": "near", "origin": "file", "at": [0, 0], "offset": 0}',
                            'elements {"category": "pointcloud"}')])
    golden.check(result(r), "origin_file.txt")
    r = run(["run", "--cmd", 'point_cloud {"path": "box.xyz", "origin": "file"}'])
    golden.check(result(r), "origin_file_too_far.txt")
    r = run(["run", "--cmd", 'point_cloud {"path": "near.xyz", "origin": "nowhere"}'])
    golden.check(result(r), "origin_unknown.txt")


def test_units_scale_the_files_coordinates(run, workdir, golden):
    """CATCHES: a rewrite that reads a scan's coordinates in another unit than metres by default, or scales mm, cm, in or
    ft wrongly (case-blind), or takes a unit it doesn't know."""
    (workdir / "s.xyz").write_text("0 0 0\n10 0 1\n")
    lines = [f'point_cloud {{"path": "s.xyz", "name": "{u}", "units": "{u}"}}' for u in ["mm", "cm", "m", "in", "ft", "FT"]]
    r = run(["run", *script(workdir, *lines)])
    golden.check(result(r), "units.txt")
    r = run(["run", "--cmd", 'point_cloud {"path": "s.xyz", "units": "furlong"}'])
    golden.check(result(r), "units_unknown.txt")


def test_spacing_keeps_one_point_in_each_cube(run, workdir, golden):
    """CATCHES: a rewrite that thins a scan differently (one point in each cube `spacing` mm wide, the first met, from
    the scan's lowest corner), or takes a spacing that is negative or not a number."""
    (workdir / "grid.xyz").write_text("".join(f"{i % 10} {i // 10 % 10} {i // 100}\n" for i in range(1000)))
    r = run(["run", *script(workdir, 'point_cloud {"path": "grid.xyz", "spacing": 2000}',
                            'point_cloud {"path": "grid.xyz", "name": "fine", "spacing": 0}',
                            'point_cloud {"path": "grid.xyz", "name": "coarse", "spacing": 4500}'),
             "--save", "p.bimcraft"])
    golden.check(result(r) + "--- scans\n" + scans_of(workdir / "p.bimcraft"), "spacing.txt")
    for value, name in [(-1, "negative"), ('"x"', "text")]:
        r = run(["run", "--cmd", f'point_cloud {{"path": "grid.xyz", "spacing": {value}}}'])
        golden.check(result(r), f"spacing_{name}.txt")


def test_a_surveys_stations_come_in_as_one_scan(run, workdir, golden):
    """CATCHES: a rewrite that brings several station files in as several scans, centres them apart, doesn't grey a
    file with no colours among ones with, keeps points twice where stations overlap under a spacing, doesn't list
    the stations in the element and the file, or keeps a list of one as stations."""
    (workdir / "east.xyz").write_text("0 0 0 255 0 0\n4 0 0 255 0 0\n")
    (workdir / "west.xyz").write_text("4 0 0\n8 0 2\n")
    r = run(["run", *script(workdir,
                            'point_cloud {"path": ["east.xyz", "west.xyz"]}',
                            'point_cloud {"path": ["east.xyz", "west.xyz"], "name": "thinned", "spacing": 100}',
                            'point_cloud {"path": ["west.xyz"], "name": "alone"}',
                            'elements {"category": "pointcloud"}'), "--save", "p.bimcraft"])
    golden.check(result(r) + "--- scans\n" + scans_of(workdir / "p.bimcraft"), "stations.txt")


def test_station_lists_it_cant_take(run, workdir, golden):
    """CATCHES: a rewrite that takes an empty list of stations, a list holding something other than paths, more than
    256 files, one file of a list it can't read, or stations wider together than a scan may be (20 km), instead of
    refusing it with the reference's words."""
    (workdir / "east.xyz").write_text("0 0 0\n4 0 0\n")
    (workdir / "far.xyz").write_text("30000 0 0\n30001 0 0\n")
    (workdir / "x.laz").write_text("")
    out = []
    for path in [[], ["east.xyz", 3], ["east.xyz"] * 257, ["east.xyz", "missing.xyz"], ["east.xyz", "x.laz"], 5,
                 {"a": 1}, ["east.xyz", "far.xyz"]]:
        r = run(["run", "--cmd", "point_cloud " + json.dumps({"path": path})])
        shown = json.dumps(path) if len(json.dumps(path)) < 60 else f"[{len(path)} files]"
        out.append(f"{shown} -> exit {r.returncode}: {r.stderr.decode()}")
    golden.check("".join(out), "stations_refused.txt")


def test_a_held_scan_is_placed_again_by_name_and_names_are_checked(run, workdir, golden):
    """CATCHES: a rewrite that brings a file in twice under one name, doesn't place a held scan again by `cloud`, lists
    the held scans differently when a name isn't found, or takes `path` and `cloud` together, neither, or an empty name."""
    (workdir / "box.xyz").write_text(BOX)
    r = run(["run", *script(workdir, 'point_cloud {"path": "box.xyz"}', 'point_cloud {"cloud": "box", "at": [10000, 0]}',
                            'point_cloud {"path": "box.xyz", "name": "box 2"}')])
    golden.check(result(r), "placed_again.txt")
    out = []
    for params, before in [({"path": "box.xyz"}, True), ({"cloud": "nope"}, True), ({"cloud": "nope"}, False),
                           ({"path": "box.xyz", "cloud": "box"}, True), ({}, False), ({"path": "box.xyz", "name": " "}, False),
                           ({"path": "box.xyz", "level": "Roof"}, False), ({"path": "box.xyz", "at": [1]}, False),
                           ({"path": "box.xyz", "angle": "x"}, False), ({"path": "box.xyz", "offset": "x"}, False)]:
        first = ["--cmd", 'point_cloud {"path": "box.xyz"}', "--cmd", 'point_cloud {"path": "box.xyz", "name": "b"}'] if before else []
        r = run(["run", *first, "--cmd", "point_cloud " + json.dumps(params)])
        out.append(f"{json.dumps(params)} (after two: {before}) -> exit {r.returncode}: {r.stderr.decode()}")
    golden.check("".join(out), "names_refused.txt")


def test_a_project_holds_at_most_16_scans(run, workdir, golden):
    """CATCHES: a rewrite with no cap on the scans a project holds, another cap, or another refusal; placing a held scan
    again is still taken."""
    (workdir / "s.xyz").write_text("0 0 0\n1 0 0\n")
    lines = [f'point_cloud {{"path": "s.xyz", "name": "s{i}"}}' for i in range(16)]
    r = run(["run", *script(workdir, *lines), "--cmd", 'point_cloud {"cloud": "s15"}',
             "--cmd", 'point_cloud {"path": "s.xyz", "name": "one too many"}'])
    out = r.stdout.decode().splitlines()
    assert len(out) == 17, out[-2:]
    golden.check(f"exit: {r.returncode}\nlast: {out[-1]}\n--- stderr\n{r.stderr.decode()}", "max_clouds.txt")


def test_a_scan_moves_turns_copies_is_modified_and_refuses_to_mirror(run, workdir, golden):
    """CATCHES: a rewrite whose move, rotate, copy or modify of a point cloud changes other fields than the reference's,
    that mirrors a scan, that keeps a scan nothing places after a delete, or whose undo doesn't bring it back."""
    (workdir / "box.xyz").write_text(BOX)
    r = run(["run", *script(workdir,
                            'point_cloud {"path": "box.xyz"}',
                            'move {"ids": [100002], "by": [1000, 500]}',
                            'rotate {"ids": [100002], "about": [0, 0], "angle": 90}',
                            'copy {"ids": [100002], "by": [0, 10000]}',
                            'modify {"id": 100002, "offset": 100, "level": "Level 2", "angle": 10}',
                            'elements {"category": "pointcloud"}',
                            'delete {"ids": [100002]}',
                            'point_cloud {"cloud": "box"}',
                            'delete {"ids": [100003, 100004]}',
                            'elements {"category": "pointcloud"}',
                            'undo',
                            'elements {"category": "pointcloud"}'),
             "--cmd", 'mirror {"ids": [100004], "axis": [[0, 0], [0, 1000]]}'])
    golden.check(result(r), "edits.txt")
    out = []
    for params in [{"id": 100002, "cloud": "nope"}, {"id": 100002, "at": [2e9, 0]}, {"id": 100002, "level": "Roof"}]:
        r = run(["run", "--cmd", 'point_cloud {"path": "box.xyz"}', "--cmd", "modify " + json.dumps(params)])
        out.append(f"{json.dumps(params)} -> exit {r.returncode}: {r.stderr.decode()}")
    golden.check("".join(out), "modify_refused.txt")


def test_a_scan_is_saved_with_the_project_opens_as_it_was_and_inserts_with_its_element(run, workdir, golden):
    """CATCHES: a rewrite whose project file holds a scan's points, colours, origin, read count or element differently,
    that opens it differently, or whose Insert from File doesn't bring the scan with the point cloud that places it."""
    (workdir / "box.xyz").write_text(BOX)
    r = run(["run", "--cmd", 'point_cloud {"path": "box.xyz", "angle": 30, "at": [100, 200], "offset": 50}', "--save", "p.bimcraft"])
    assert r.returncode == 0, r.stderr
    p = json.loads((workdir / "p.bimcraft").read_text())
    held = {"elements": {k: e for k, e in p["elements"].items() if e["category"] in ("level", "pointcloud")},
            "library": {k: e for k, e in p["library"].items() if e["kind"] == "cloud"},
            "keys": sorted(p["clouds"]["box"])}
    golden.check(normalize(json.dumps(held, indent=1)) + "\n" + scans_of(workdir / "p.bimcraft"), "saved.txt")
    r = run(["run", "p.bimcraft", "--cmd", 'elements {"category": "pointcloud"}', "--save", "again.bimcraft"])
    golden.check(result(r) + "--- scans\n" + scans_of(workdir / "again.bimcraft"), "opened.txt")
    r = run(["run", "--cmd", 'insert {"path": "p.bimcraft", "ids": [100002]}', "--cmd", 'elements {"category": "pointcloud"}'])
    golden.check(result(r), "inserted.txt")


def _packed(data: bytes) -> str:
    return base64.b64encode(zlib.compress(data)).decode()


DAMAGED = {
    "points_not_base64": ("points", "!!!"),
    "points_not_zlib": ("points", base64.b64encode(b"not zlib").decode()),
    "points_cut_short": ("points", _packed(bytes(13))),
    "no_points": ("points", _packed(b"")),
    "point_not_a_number": ("points", _packed(struct.pack("<6f", float("nan"), 0, 0, 0, 0, 0))),
    "point_too_far": ("points", _packed(struct.pack("<6f", 1e9, 0, 0, 0, 0, 0))),
    "colours_too_few": ("colours", _packed(bytes([1, 2, 3]))),
    "read_fewer_than_kept": ("read", 1),
    "origin_too_far": ("origin", [1e13, 0, 0]),
    "unknown_field": ("extra", 1),
    "stations_dont_add_up": ("stations", [{"source": "a", "points": 1}, {"source": "b", "points": 2}]),
    "too_many_stations": ("stations", [{"source": "a", "points": 0}] * 257),
    "one_station_is_none": ("stations", [{"source": "only.xyz", "points": 2}]),
}


DATA_CASES = ["points_not_base64", "points_not_zlib", "points_cut_short", "no_points", "point_not_a_number",
              "point_too_far", "colours_too_few"]


def _damaged(run, workdir, cases, whole=()):
    """A project of one scan of two points, saved, then opened again with each case's field of the scan (or, for
    WHOLE, the project's `clouds`) replaced: what each open says."""
    (workdir / "two.xyz").write_text("0 0 0 255 0 0\n1 0 0 0 255 0\n")
    assert run(["run", "--cmd", 'point_cloud {"path": "two.xyz"}', "--save", "p.bimcraft"]).returncode == 0
    report = []
    for case in cases:
        p = json.loads((workdir / "p.bimcraft").read_text())
        key, value = DAMAGED[case]
        p["clouds"]["two"][key] = value
        (workdir / "bad.bimcraft").write_text(json.dumps(p))
        report.append(f"### {case}\n{result(run(['run', 'bad.bimcraft', '--cmd', 'elements {\"category\": \"pointcloud\"}']))}")
    for case, value in whole:
        p = json.loads((workdir / "p.bimcraft").read_text())
        p["clouds"] = value
        (workdir / "bad.bimcraft").write_text(json.dumps(p))
        report.append(f"### {case}\n{result(run(['run', 'bad.bimcraft']))}")
    return "".join(report)


def test_a_scan_whose_data_is_damaged_is_refused(run, workdir, golden):
    """CATCHES: a rewrite that opens a project whose scan data isn't base64 or zlib, is cut short, holds no point, a
    point that isn't a number or lies too far, or colours that don't match its points."""
    golden.check(_damaged(run, workdir, DATA_CASES), "damaged_scan_data.txt")


def test_a_scan_whose_fields_dont_hold_together_is_refused(run, workdir, golden):
    """CATCHES: a rewrite that opens a project whose scan read fewer points than it keeps, lies past what a model holds,
    has stations that don't add up to its points or more than 256 of them, or whose `clouds` isn't a map; and one that
    refuses an unknown field instead of leaving it out as a file is read kindly, or keeps a list of one station."""
    cases = sorted(c for c in DAMAGED if c not in DATA_CASES)
    golden.check(_damaged(run, workdir, cases, [("clouds_not_a_map", []), ("clouds_null", None)]), "damaged_scan_fields.txt")


def _project_with_one_scan(run, workdir):
    (workdir / "two.xyz").write_text("0 0 0\n1 0 0\n")
    assert run(["run", "--cmd", 'point_cloud {"path": "two.xyz"}', "--save", "p.bimcraft"]).returncode == 0
    return json.loads((workdir / "p.bimcraft").read_text())


def test_a_project_file_holds_no_more_than_16_scans(run, workdir, golden):
    """CATCHES: a rewrite that opens a project file holding more scans than a project may (16)."""
    p = _project_with_one_scan(run, workdir)
    for i in range(17):
        p["clouds"][f"copy {i}"] = p["clouds"]["two"]
    (workdir / "many.bimcraft").write_text(json.dumps(p))
    golden.check(result(run(["run", "many.bimcraft"])), "project_file_too_many_scans.txt")


def test_a_scan_in_a_project_file_unpacks_no_further_than_a_scan_may_hold(run, workdir, golden):
    """CATCHES: a rewrite that unpacks a project file's scan data past the five million points a scan may hold (60 MB
    of f32) instead of refusing it."""
    p = _project_with_one_scan(run, workdir)
    p["clouds"]["two"] = {**p["clouds"]["two"], "read": 6_000_000,
                          "points": base64.b64encode(zlib.compress(bytes(12 * 5_000_001), 1)).decode()}
    (workdir / "huge.bimcraft").write_text(json.dumps(p))
    golden.check(result(run(["run", "huge.bimcraft"])), "project_file_scan_too_big.txt")


# ---------------------------------------------------------------------------
# Drawn in a plan
# ---------------------------------------------------------------------------

IMAGE_RE = re.compile(r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"')


def svg_with_pictures_digested(text):
    """The SVG with each embedded PNG replaced by a summary of its pixels (independent of how it was compressed)."""
    return IMAGE_RE.sub(lambda m: 'href="' + png_pixels(base64.b64decode(m.group(1))).strip() + '"', text)


def sheet():
    """Points every 100 mm over 4 m by 3 m, at heights 0.2 m to 2.2 m, metres, coloured by place."""
    rows = []
    for i in range(41):
        for k in range(31):
            rows.append(f"{i * 0.1:.1f} {k * 0.1:.1f} {0.2 + (i % 5) * 0.5:.1f} {i * 6} {k * 8} 128")
    return "\n".join(rows) + "\n"


def test_a_plan_draws_what_its_view_range_sees_of_a_scan(run, workdir, golden):
    """CATCHES: a rewrite whose plan doesn't draw a scan's points under the model as a picture, draws the points above
    its cut plane, in other colours, in the wrong place, or still draws them when the view hides the point cloud
    category or fills it with one colour."""
    (workdir / "sheet.xyz").write_text(sheet())
    r = run(["run", *script(workdir,
                            'wall {"points": [[-3000, -2500], [3000, -2500], [3000, 2500], [-3000, 2500]], "closed": true}',
                            'point_cloud {"path": "sheet.xyz"}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "plan.svg"}',
                            'graphics {"view": "Level 1", "categories": {"pointcloud": {"projection": {"fill": [200, 0, 40]}}}}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "filled.svg"}',
                            'graphics {"view": "Level 1", "hide": ["pointcloud"]}',
                            'render {"view": "Level 1", "width": 400, "height": 300, "path": "hidden.svg"}')])
    golden.check(result(r), "plan_drawing.txt")
    for name in ["plan", "filled", "hidden"]:
        golden.check(svg_with_pictures_digested((workdir / f"{name}.svg").read_text()), f"plan_{name}.svg")
