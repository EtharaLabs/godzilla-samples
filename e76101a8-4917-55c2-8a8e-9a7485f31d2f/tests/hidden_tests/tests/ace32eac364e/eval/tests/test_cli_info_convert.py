"""`bimcraft-cli info` and `bimcraft-cli convert`: what a file holds, and a file in another format."""

import json

import pytest
from conftest import glb_summary, make_project, normalize, pdf_summary, png_pixels

BOX = 'wall {"points": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]], "closed": true}'


SMALL = ["--cmd", BOX, "--cmd", 'door {"at": [3000, 0]}', "--cmd", 'window {"at": [6000, 2000]}',
         "--cmd", 'room {"point": [3000, 2000], "name": "Office"}']


def _export(run, workdir, args, path):
    """A project made by ARGS, its GUIDs fixed, saved as PATH (a project, or converted to IFC)."""
    if path.endswith(".bimcraft"):
        make_project(run, workdir, path, args)
        return
    make_project(run, workdir, "made.bimcraft", args)
    r = run(["convert", "made.bimcraft", path])
    assert r.returncode == 0, r.stderr
    (workdir / "made.bimcraft").unlink()


def _sample(run, workdir, path):
    _export(run, workdir, ["--sample"], path)


def _small(run, workdir, path):
    _export(run, workdir, SMALL, path)


def test_info_of_the_sample_project(run, workdir, golden):
    """CATCHES: a rewrite whose `info` of a project leaves out or reorders levels, counts, types or warnings, or prints
    compact instead of pretty JSON."""
    _sample(run, workdir, "house.bimcraft")
    golden.check_run(run(["info", "house.bimcraft"]), "info_sample_project.txt")


def test_info_of_an_empty_project(run, golden):
    """CATCHES: a rewrite that reports a new project's starter levels, types or settings differently."""
    assert run(["run", "--save", "empty.bimcraft"]).returncode == 0
    golden.check_run(run(["info", "empty.bimcraft"]), "info_empty_project.txt")


def test_info_of_an_ifc_file(run, workdir, golden):
    """CATCHES: a rewrite whose `info` of an IFC file imports a different set of elements or types than the reference."""
    _sample(run, workdir, "house.ifc")
    golden.check_run(run(["info", "house.ifc"]), "info_sample_ifc.txt")


def test_info_of_a_small_project(run, workdir, golden):
    """CATCHES: a rewrite that counts a project's walls, doors, windows and rooms wrongly in `info`."""
    _small(run, workdir, "office.bimcraft")
    golden.check_run(run(["info", "office.bimcraft"]), "info_small_project.txt")


BAD_FILES = {
    "missing_file": None,
    "not_json": "not json",
    "empty_file": "",
    "json_array": "[1, 2]",
    "newer_format": '{"format": 99}',
    "format_not_a_number": '{"format": "x"}',
    "format_negative": '{"format": -1}',
    "missing_uid": '{"name": "Old", "elements": {}}',
    "empty_object": "{}",
}


@pytest.mark.parametrize("case", sorted(BAD_FILES))
def test_info_refuses_a_file_that_is_no_project(run, workdir, golden, case):
    """CATCHES: a rewrite that opens a damaged, empty or newer project file instead of refusing it, or whose refusal
    does not say the file's name and what is wrong with it."""
    text = BAD_FILES[case]
    if text is not None:
        (workdir / "p.bimcraft").write_text(text)
    golden.check_run(run(["info", "p.bimcraft"]), f"bad_{case}.txt")


def test_info_of_a_folder(run, workdir, golden):
    """CATCHES: a rewrite that reads a folder given as the file as an empty project."""
    (workdir / "dir.bimcraft").mkdir()
    golden.check_run(run(["info", "dir.bimcraft"]), "info_folder.txt")


@pytest.mark.parametrize("text", ["", "ISO-10303-21;\nnothing here\n", "HEADER;\nENDSEC;\n"])
def test_info_refuses_an_ifc_file_that_is_no_step_file(run, workdir, golden, text):
    """CATCHES: a rewrite that imports a damaged IFC file as an empty project instead of saying what is wrong with it."""
    (workdir / "bad.ifc").write_text(text)
    golden.check_run(run(["info", "bad.ifc"]), f"bad_ifc_{len(text)}.txt")


def test_open_leaves_out_what_this_version_does_not_know(run, workdir, golden):
    """CATCHES: a rewrite that refuses a project with keys from a newer version (a file is read kindly), or that does not
    list what it left out in `left_out` and `left_out_count`."""
    _small(run, workdir, "p.bimcraft")
    data = json.loads((workdir / "p.bimcraft").read_text())
    data["future_setting"] = {"a": 1}
    for e in data["elements"].values():
        if e.get("category") == "wall":
            e["sparkle"] = True
    (workdir / "p.bimcraft").write_text(json.dumps(data))
    golden.check_run(run(["run", "p.bimcraft", "--cmd", 'elements {"category": "wall", "limit": 1}']), "left_out.txt")


def test_open_a_file_from_format_zero(run, workdir, golden):
    """CATCHES: a rewrite that does not migrate a project with no `format` (the first file format) and its low ids."""
    _small(run, workdir, "p.bimcraft")
    data = json.loads((workdir / "p.bimcraft").read_text())
    del data["format"]
    (workdir / "p.bimcraft").write_text(json.dumps(data))
    golden.check_run(run(["run", "p.bimcraft", "--cmd", "inspect"]), "format_zero.txt")


# convert: the reply line, then the file it wrote, compared in a form that does not depend on random ids or compression.
def _file_summary(path):
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".png":
        return png_pixels(data)
    if suffix == ".glb":
        return glb_summary(data)
    if suffix == ".pdf":
        return pdf_summary(data)
    return normalize(data.decode("utf-8"))


@pytest.mark.parametrize("target", ["out.ifc", "out.svg", "out.png", "out.glb", "out.pdf", "out.bimcraft"])
def test_convert_the_sample_project(run, workdir, golden, target):
    """CATCHES: a rewrite whose conversion writes a different IFC, SVG, PNG, glTF, PDF or project file from the same project
    (after normalising random ids), or replies with a different line."""
    _sample(run, workdir, "house.bimcraft")
    r = run(["convert", "house.bimcraft", target])
    golden.check_run(r, f"convert_sample_{target}.txt")
    golden.check(_file_summary(workdir / target), f"convert_sample_{target}.golden")


@pytest.mark.parametrize("target", ["out.ifc", "out.svg", "out.png", "out.glb", "out.bimcraft"])
def test_convert_a_small_project(run, workdir, golden, target):
    """CATCHES: a rewrite that draws, exports or saves a simple four-wall office differently from the reference."""
    _small(run, workdir, "office.bimcraft")
    r = run(["convert", "office.bimcraft", target])
    golden.check_run(r, f"convert_small_{target}.txt")
    golden.check(_file_summary(workdir / target), f"convert_small_{target}.golden")


def test_convert_an_ifc_file_to_a_project(run, workdir, golden):
    """CATCHES: a rewrite whose IFC import loses walls, openings, rooms or levels on the way to a project."""
    _small(run, workdir, "office.ifc")
    r = run(["convert", "office.ifc", "back.bimcraft"])
    golden.check_run(r, "convert_ifc_to_project.txt")
    golden.check(normalize((workdir / "back.bimcraft").read_text()), "convert_ifc_to_project.bimcraft")


def test_convert_the_sample_ifc_back_to_ifc(run, workdir, golden):
    """CATCHES: a rewrite whose IFC import and export do not round-trip the sample house to the same entities."""
    _sample(run, workdir, "house.ifc")
    r = run(["convert", "house.ifc", "again.ifc"])
    golden.check_run(r, "convert_ifc_to_ifc.txt")
    golden.check(normalize((workdir / "again.ifc").read_text()), "convert_ifc_to_ifc.golden")


def test_run_imports_an_ifc_file(run, workdir, golden):
    """CATCHES: a rewrite whose `run FILE.ifc` reply (format, name, counts, skipped, moved) differs from the reference."""
    _sample(run, workdir, "house.ifc")
    golden.check_run(run(["run", "house.ifc", "--cmd", 'elements {"category": "door"}']), "run_ifc.txt")


CONVERT_ERRORS = {
    "missing_input": ["convert", "nothing.bimcraft", "out.ifc"],
    "missing_ifc_input": ["convert", "nothing.ifc", "out.bimcraft"],
    "output_into_missing_folder": ["convert", "p.bimcraft", "no/where.ifc"],
    "pdf_of_a_project_without_sheets": ["convert", "p.bimcraft", "sheets.pdf"],
    "missing_revit_input": ["convert", "nothing.rvt", "out.ifc"],
}


@pytest.mark.parametrize("case", sorted(CONVERT_ERRORS))
def test_convert_errors(run, workdir, golden, case):
    """CATCHES: a rewrite that reports a failed conversion with a different message or exit code, or writes a partial file."""
    _small(run, workdir, "p.bimcraft")
    golden.check_run(run(CONVERT_ERRORS[case]), f"convert_error_{case}.txt")
    assert sorted(p.name for p in workdir.iterdir()) == ["p.bimcraft"]


def test_convert_to_an_unknown_extension_saves_a_project(run, workdir, golden):
    """CATCHES: a rewrite that refuses an unknown output extension instead of writing the project as .bimcraft JSON."""
    _small(run, workdir, "p.bimcraft")
    golden.check_run(run(["convert", "p.bimcraft", "copy.data"]), "convert_unknown_extension.txt")
    assert normalize((workdir / "copy.data").read_text()) == normalize((workdir / "p.bimcraft").read_text())
