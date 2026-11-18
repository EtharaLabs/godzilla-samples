"""The point cloud readers behind `point_cloud`: PTS and XYZ text, PLY (text, and binary in either byte order), ASPRS LAS
1.0 to 1.4 and ASTM E57, and why a file each can't read is refused.

What came in is seen in the command's reply and in the scan the saved project holds: its points (little-endian f32 about
its middle, mm) and colours are unpacked here, so the comparison doesn't depend on how they were compressed. The binary
files in test_resources were written from the public specifications by a script, with no scanner's data."""

import base64
import hashlib
import json
import shutil
import struct
import zlib

from conftest import normalize, resources_for

RES = resources_for(__file__)


def scans_of(project):
    """Each scan a saved project holds: its source, stations, origin and the points it read, then its points and colours
    (all of them for a small scan, else the first ten and a digest of the rest)."""
    p = json.loads(project.read_text())
    out = []
    for name, c in p["clouds"].items():
        raw = zlib.decompress(base64.b64decode(c["points"]))
        pts = [struct.unpack_from("<3f", raw, i) for i in range(0, len(raw), 12)]
        cols = None
        if "colours" in c:
            cb = zlib.decompress(base64.b64decode(c["colours"]))
            cols = [tuple(cb[i:i + 3]) for i in range(0, len(cb), 3)]
        out.append(f"scan {name}: source={c['source']} origin={c['origin']} read={c['read']} kept={len(pts)}"
                   f" stations={json.dumps(c.get('stations', []))}")
        shown = pts if len(pts) <= 40 else pts[:10]
        for i, q in enumerate(shown):
            colour = "" if cols is None else f" rgb={list(cols[i])}"
            out.append(f"  {q[0]!r} {q[1]!r} {q[2]!r}{colour}")
        if len(pts) > 40:
            out.append(f"  ... points sha256={hashlib.sha256(raw).hexdigest()}"
                       + ("" if cols is None else f" colours sha256={hashlib.sha256(bytes(b for c3 in cols for b in c3)).hexdigest()}"))
    return "\n".join(out) + "\n"


def outcome(r):
    """A run as `golden.check_run` shows it: its exit code, then its normalised output and errors."""
    return f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{normalize(r.stderr.decode())}"


def check_scans(golden, run, workdir, names, golden_name):
    """Brings each file in, in one run, then saves the project; the golden holds the replies and the scans it keeps."""
    args = [a for name in names for a in cloud(name)]
    r = run(["run", *args, "--save", "p.bimcraft"])
    text = outcome(r)
    if r.returncode == 0:
        text += "--- scans\n" + scans_of(workdir / "p.bimcraft")
    golden.check(text, golden_name)


def check_refusals(golden, run, names, golden_name):
    """Brings each file in, one run each: what each run says, under the file's name."""
    golden.check("".join(f"### {name}\n{outcome(run(['run', *cloud(name)]))}" for name in names), golden_name)


def copy_resources(workdir, names):
    for name in names:
        shutil.copy(RES / name, workdir / name)


def write_all(workdir, files):
    for name, text in files.values():
        (workdir / name).write_bytes(text if isinstance(text, bytes) else text.encode())


def cloud(path, **more):
    return ["--cmd", "point_cloud " + json.dumps({"path": path, **more})]


# ---------------------------------------------------------------------------
# Text: PTS and XYZ
# ---------------------------------------------------------------------------

TEXT = {
    # Two scans, each after its count; an intensity and a colour; comments and blank lines between.
    "pts_counts_intensity_colour": ("scan.pts", "2\n0 0 0 -2048 255 0 0\n1 0 0 2047 0 255 0\n\n# the second scan\n1\n"
                                                "0 1 0.5 0 0 0 255\n// a note\n"),
    "pts_intensity_only": ("grey.pts", "3\n0 0 0 -2048\n1 0 0 0\n2 0 0 2047\n"),
    "pts_one_flat_intensity": ("flat.pts", "0 0 0 5\n1 1 1 5\n"),
    "xyz_spaces_tabs_commas_crlf": ("mixed.xyz", "0 0 0\n1\t2\t3\r\n4,5,6\n  7 ,8, 9  \n"),
    "xyz_sixteen_bit_colour": ("deep.xyz", "0 0 0 65535 0 32896\n1 1 1 0 65535 0\n"),
    "xyz_colour_from_nought_to_one": ("unit.xyz", "0 0 0 1 0 0.5\n1 0 0 0.25 0.75 1\n"),
    "xyz_eight_bit_colour_with_fractions": ("eight.xyz", "0 0 0 255 0 0.5\n1 0 0 10 20 30\n"),
    "txt_is_xyz": ("points.txt", "0 0 0\n1 2 3\n"),
    "xyz_survey_far_off": ("utm.xyz", "500000.001 7000000.002 12.003\n504000.004 7003000.005 52.006\n"),
    "xyz_upper_case_extension": ("UP.XYZ", "0 0 0\n0.5 0.5 0.5\n"),
    # Rows of three, four, six and seven columns in one file: the missing shades are grey.
    "xyz_mixed_columns": ("mixed_columns.xyz", "0 0 0\n1 0 0 10\n2 0 0 255 0 0\n3 0 0 20 0 255 0\n4 0 0 30\n"),
}


def test_pts_scans_come_in(run, workdir, golden):
    """CATCHES: a rewrite that reads a PTS count line as a point, skips its comments wrongly, or shades by intensity
    differently (grey from the darkest the file holds to the lightest; one flat intensity is the middle grey)."""
    write_all(workdir, TEXT)
    check_scans(golden, run, workdir, [n for k, (n, _) in sorted(TEXT.items()) if k.startswith("pts")], "text_pts.txt")


def test_xyz_scans_come_in(run, workdir, golden):
    """CATCHES: a rewrite that splits XYZ columns differently (spaces, tabs, commas, CRLF), reads colours in 16 bits or
    from 0 to 1 wrongly, takes .txt (or an upper-case extension) for anything but XYZ, or keeps a survey's far
    coordinates without its middle."""
    write_all(workdir, TEXT)
    check_scans(golden, run, workdir, [n for k, (n, _) in sorted(TEXT.items()) if not k.startswith("pts")], "text_xyz.txt")


TEXT_ERRORS = {
    "empty": ("e.xyz", ""),
    "only_comments": ("c.pts", "# nothing but this\n// and this\n"),
    "not_a_number": ("n.xyz", "0 0 zero\n"),
    "nan": ("nan.xyz", "0 0 0\n0 0 nan\n"),
    "overflow": ("inf.xyz", "0 0 1e400\n"),
    "overflow_in_mm": ("huge.xyz", "1e308 0 0\n"),
    "too_far": ("far.xyz", "0 0 1e20\n"),
    "five_columns": ("five.xyz", "0 0 0 1 2\n"),
    "two_columns": ("two.xyz", "0 0\n"),
    "too_wide": ("wide.xyz", "0 0 0\n30000 0 0\n"),
    "not_text": ("bin.xyz", b"0 0 0\n\xff\xfe 1 1\n"),
    "pts_count_then_bad_row": ("bad.pts", "1\n0 0\n"),
}


def test_a_text_scan_whose_numbers_it_cant_take_says_why(run, workdir, golden):
    """CATCHES: a rewrite that takes a word for a number, NaN, a number past f64 (or past it once in mm), a point past
    1e12 mm, or a scan wider than 20 km, or refuses it without the line and the reason."""
    write_all(workdir, TEXT_ERRORS)
    cases = ["not_a_number", "nan", "overflow", "overflow_in_mm", "too_far", "too_wide"]
    check_refusals(golden, run, [TEXT_ERRORS[c][0] for c in cases], "text_number_errors.txt")


def test_a_text_scan_whose_rows_it_cant_take_says_why(run, workdir, golden):
    """CATCHES: a rewrite that takes a text scan with no points (or only comments), rows of two or five columns, or
    bytes that aren't text, or refuses it without the line and the reason."""
    write_all(workdir, TEXT_ERRORS)
    cases = ["empty", "only_comments", "five_columns", "two_columns", "not_text", "pts_count_then_bad_row"]
    check_refusals(golden, run, [TEXT_ERRORS[c][0] for c in cases], "text_row_errors.txt")


# ---------------------------------------------------------------------------
# PLY
# ---------------------------------------------------------------------------

PLY_HEAD = "ply\nformat ascii 1.0\n"
PLY_TEXT = {
    "normals.ply": "ply\r\nformat ascii 1.0\ncomment made by hand\nobj_info scanner x\nelement vertex 3\n"
                                     "property float x\nproperty float y\nproperty float z\nproperty float nx\n"
                                     "property uchar red\nproperty uchar green\nproperty uchar blue\nelement face 0\n"
                                     "property list uchar int vertex_indices\nend_header\n"
                                     "0 0 0 0.5 255 0 0\n1.5 -2 3.25 0.5 10 20 30\n100 0 7 0.5 0 0 255\n",
    "intensity.ply": PLY_HEAD + "element camera 1\nproperty float k\nelement vertex 2\nproperty double x\n"
                                              "property double y\nproperty double z\nproperty int8 scalar_intensity\n"
                                              "end_header\n9\n0 0 0 -5\n2 2 2 5\n",
    "diffuse.ply": PLY_HEAD + "element vertex 2\nproperty float x\nproperty float y\nproperty float z\n"
                                       "property float diffuse_red\nproperty float diffuse_green\nproperty float diffuse_blue\n"
                                       "end_header\n0 0 0 1 0 0.5\n1 1 1 0 1 0\n",
}


def test_text_ply_comes_in(run, workdir, golden):
    """CATCHES: a rewrite whose PLY reader takes the wrong properties for position, colour (red/diffuse_red, floats from
    0 to 1) or intensity, doesn't step over the elements before the vertices, or stops at a CRLF header line."""
    for name, text in PLY_TEXT.items():
        (workdir / name).write_text(text)
    check_scans(golden, run, workdir, sorted(PLY_TEXT), "ply_text.txt")


def test_binary_ply_comes_in_as_the_text_one_does(run, workdir, golden):
    """CATCHES: a rewrite that reads binary PLY in the wrong byte order, with the wrong property sizes, without
    stepping over fixed-size elements before the vertices, reads integer types (int, uint, short, char) wrongly, or
    scales 16-bit or float colours wrongly."""
    names = ["le.ply", "be.ply", "ushort.ply", "floatcolour.ply", "skip.ply", "types.ply"]
    copy_resources(workdir, names)
    check_scans(golden, run, workdir, names, "ply_binary.txt")


PLY_ERRORS = {  # file name: its text
    "not_ply": "PLX\nformat ascii 1.0\nend_header\n",
    "no_end_header": PLY_HEAD + "element vertex 3\nproperty float x\n",
    "no_x": PLY_HEAD + "element vertex 1\nproperty float y\nproperty float z\nend_header\n0 0\n",
    "no_z": PLY_HEAD + "element vertex 1\nproperty float x\nproperty float y\nend_header\n0 0\n",
    "bad_count": PLY_HEAD + "element vertex -1\nproperty float x\nproperty float y\nproperty float z\nend_header\n",
    "cut_short": PLY_HEAD + "element vertex 5\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n",
    "cut_short_before": PLY_HEAD + "element camera 3\nproperty float k\nelement vertex 1\nproperty float x\n"
                                   "property float y\nproperty float z\nend_header\n1\n",
    "unknown_type": PLY_HEAD + "element vertex 1\nproperty quaternion x\nend_header\n0\n",
    "list_in_vertex": PLY_HEAD + "element vertex 1\nproperty list uchar float x\nend_header\n",
    "unknown_format": "ply\nformat ebcdic 1.0\nend_header\n",
    "no_format": "ply\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n",
    "property_first": "ply\nformat ascii 1.0\nproperty float x\nend_header\n",
    "not_ply_header_line": PLY_HEAD + "hello world\nend_header\n",
    "no_vertex": PLY_HEAD + "element face 1\nproperty float k\nend_header\n1\n",
    "word_for_number": PLY_HEAD + "element vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 a 0\n",
    "too_few_values": PLY_HEAD + "element vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0\n",
    "binary_too_many": "ply\nformat binary_little_endian 1.0\nelement vertex 99999999999\nproperty float x\n"
                       "property float y\nproperty float z\nend_header\n",
}


PLY_HEADER_ERRORS = ["not_ply", "no_end_header", "no_x", "no_z", "bad_count", "unknown_type", "list_in_vertex",
                     "unknown_format", "no_format", "property_first", "not_ply_header_line"]


def test_a_ply_whose_header_it_cant_read_says_why(run, workdir, golden):
    """CATCHES: a rewrite whose PLY reader takes a header that isn't PLY, a type or format PLY doesn't have, a list in a
    vertex, or vertices without x, y or z, or refuses them with other words."""
    for case in PLY_HEADER_ERRORS:
        (workdir / f"{case}.ply").write_text(PLY_ERRORS[case])
    check_refusals(golden, run, [f"{case}.ply" for case in PLY_HEADER_ERRORS], "ply_header_errors.txt")


def test_a_ply_whose_body_it_cant_read_says_why(run, workdir, golden):
    """CATCHES: a rewrite that reads past the end of a PLY cut short (text or binary), steps over a list it can't size
    before a binary file's vertices, or takes a word for a number or a row of too few values."""
    cases = [c for c in PLY_ERRORS if c not in PLY_HEADER_ERRORS]
    for case in cases:
        (workdir / f"{case}.ply").write_text(PLY_ERRORS[case])
    copy_resources(workdir, ["bad_list_first.ply", "bad_cut.ply"])
    check_refusals(golden, run, sorted(f"{c}.ply" for c in cases) + ["bad_list_first.ply", "bad_cut.ply"],
                   "ply_body_errors.txt")


# ---------------------------------------------------------------------------
# LAS
# ---------------------------------------------------------------------------

def test_las_comes_in(run, workdir, golden):
    """CATCHES: a rewrite that doesn't apply a LAS file's scale and offset, starts reading at the header's end instead of
    its point data offset, takes colour from the wrong bytes of a point format (2, 3, 7), shades by intensity wrongly,
    or reads 1.4's 64-bit count from the legacy field."""
    names = ["survey12.las", "intensity13.las", "plain10.las", "colour14.las", "format6.las", "format3.las"]
    copy_resources(workdir, names)
    check_scans(golden, run, workdir, names, "las.txt")


def test_a_las_whose_header_it_cant_take_says_why(run, workdir, golden):
    """CATCHES: a rewrite that reads compressed LAZ points, another version, an unknown point format, records shorter
    than their format, a scale of 0 or an offset that isn't a number, or a file that isn't LAS."""
    names = [f"bad_{c}.las" for c in ["laz", "short_records", "format_11", "zero_scale", "nan_offset", "version_2",
                                      "version_1_5", "not_las"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "las_header_errors.txt")


def test_a_las_cut_short_says_why(run, workdir, golden):
    """CATCHES: a rewrite that reads past the end of a LAS file (a header cut short, a count or a point data offset past
    its end, its last byte missing) instead of refusing it with the sizes it found."""
    names = [f"bad_{c}.las" for c in ["too_many_points", "points_past_the_end", "header_too_small", "cut_short",
                                      "last_byte_missing"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "las_size_errors.txt")


# ---------------------------------------------------------------------------
# E57
# ---------------------------------------------------------------------------

def test_e57_comes_in(run, workdir, golden):
    """CATCHES: a rewrite whose E57 reader doesn't read bit-packed streams across packets and pages, place each scan by
    its pose, decode scaled integers, single and double floats and constants of no bits, leave out points marked
    invalid (cartesian or spherical), turn spherical coordinates into cartesian, or scale colours by the colour limits."""
    names = ["coloured.e57", "posed.e57", "scaled.e57", "spherical.e57", "limits.e57", "double.e57", "constant.e57",
             "invalid_spherical.e57", "offset_only.e57", "float_colour.e57"]
    copy_resources(workdir, names)
    check_scans(golden, run, workdir, names, "e57.txt")


def test_an_e57_file_it_cant_read_says_why(run, workdir, golden):
    """CATCHES: a rewrite whose E57 reader takes another version or page size, a file that isn't E57 or is cut short,
    a file with no data3D, or two scans reading one section, instead of refusing it with the reference's words."""
    names = [f"bad_{c}.e57" for c in ["version_2", "page_2048", "not_e57", "header_cut", "half", "no_data3d",
                                      "same_section", "too_many_points"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "e57_file_errors.txt")


def test_an_e57_whose_xml_is_broken_says_why(run, workdir, golden):
    """CATCHES: a rewrite whose E57 XML reader takes an element closed by another, an end tag that closes nothing, a
    tag, comment or CDATA left open, an element with no name, or XML nested past 64 deep."""
    names = [f"bad_{c}.e57" for c in ["broken_xml", "xml_unclosed_cdata", "xml_unclosed_comment", "xml_closes_nothing",
                                      "xml_tag_not_closed", "xml_empty_tag", "xml_not_closed", "xml_too_deep"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "e57_xml_errors.txt")


def test_an_e57_scan_it_cant_read_says_why(run, workdir, golden):
    """CATCHES: a rewrite whose E57 reader takes a scan packed by a codec, a count its section can't hold or its packets
    don't, a field type it doesn't read, points that aren't a CompressedVector or have no count or coordinates, or
    doesn't name the scan."""
    names = [f"bad_{c}.e57" for c in ["codec", "count_past_the_section", "count_one_more", "string_field", "no_points",
                                      "not_compressed", "no_count", "no_coordinates", "no_data"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "e57_scan_errors.txt")


def test_an_e57_scan_whose_fields_are_described_wrongly_says_why(run, workdir, golden):
    """CATCHES: a rewrite that takes a field whose scale or minimum isn't a number, a scale of 0, a maximum under its
    minimum, more than 32 fields, or points with no prototype or file offset."""
    names = [f"bad_{c}.e57" for c in ["bad_scale", "bad_minimum", "scale_zero", "max_under_min", "too_many_fields",
                                      "no_prototype", "no_file_offset"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "e57_field_errors.txt")


def test_an_e57_scan_placed_or_packed_wrongly_says_why(run, workdir, golden):
    """CATCHES: a rewrite that takes an offset that isn't a section or falls on a checksum, a packet of an unknown type
    or with the wrong number of streams, or a pose that isn't a rotation or a place."""
    names = [f"bad_{c}.e57" for c in ["offset_zero", "offset_on_checksum", "packet_type", "packet_streams",
                                      "bad_rotation", "bad_translation"]]
    copy_resources(workdir, names)
    check_refusals(golden, run, names, "e57_packing_errors.txt")


# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

def test_files_it_doesnt_read_say_what_to_do(run, workdir, golden):
    """CATCHES: a rewrite that tries to read LAZ, ReCap's RCP/RCS or another file as points instead of saying what to
    export or convert it to, or that doesn't name a missing file."""
    names = ["scan.laz", "scan.rcp", "scan.rcs", "plan.dwg", "noext"]
    for name in names:
        (workdir / name).write_text("0 0 0\n")
    check_refusals(golden, run, names + ["missing.xyz"], "extensions.txt")
