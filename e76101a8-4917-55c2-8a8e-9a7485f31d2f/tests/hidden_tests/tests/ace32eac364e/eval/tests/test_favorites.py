"""The `favorite` command: the user's favorites file (where it is looked for, what it holds, how it is written and
read), saving, listing, loading and deleting favorite materials and families."""

import json
import os

import pytest
from conftest import normalize, resources_for


def transcript(run, env, steps):
    """Each step (`--cmd` values, and environment overrides) run in a process of its own; the outputs together, the
    fixture's temporary HOME shown as <HOME>."""
    out = []
    for cmds, overrides in steps:
        args = []
        for c in cmds:
            args += ["--cmd", c]
        r = run(["run", *args], env_overrides=overrides)
        text = (f"=== {' '.join(cmds)} {json.dumps(overrides, sort_keys=True)}\nexit: {r.returncode}\n--- stdout\n"
                f"{normalize(r.stdout.decode())}--- stderr\n{normalize(r.stderr.decode())}")
        out.append(text.replace(env["HOME"], "<HOME>"))
    return "".join(out)


def test_where_the_favorites_file_is_looked_for(run, workdir, env, golden):
    """CATCHES: a rewrite that looks for the favorites file in another order (BIMCRAFT_FAVORITES, then
    XDG_CONFIG_HOME/bimcraft, then HOME/.config/bimcraft), treats an empty variable as set, lets the environment win
    over `path`, or answers differently when there is no folder for it at all."""
    lst = ['favorite {}']
    steps = [
        (lst, {}),
        (['favorite {"action": "list"}'], {"XDG_CONFIG_HOME": "cfg"}),
        (lst, {"BIMCRAFT_FAVORITES": "favs/mine.json", "XDG_CONFIG_HOME": "cfg"}),
        (lst, {"BIMCRAFT_FAVORITES": "", "XDG_CONFIG_HOME": "cfg"}),
        (lst, {"XDG_CONFIG_HOME": ""}),
        (lst, {"HOME": "", "XDG_CONFIG_HOME": "cfg"}),
        (lst, {"HOME": ""}),
        (lst, {"HOME": "", "XDG_CONFIG_HOME": "", "BIMCRAFT_FAVORITES": ""}),
        (['favorite {"path": "given.json"}'], {"BIMCRAFT_FAVORITES": "favs/mine.json", "XDG_CONFIG_HOME": "cfg"}),
        (['favorite {"path": "given.json"}'], {"HOME": ""}),
        # Saved where each says: the folders are made as need be.
        (['favorite {"action": "save", "name": "Brick"}'], {"BIMCRAFT_FAVORITES": "favs/mine.json", "XDG_CONFIG_HOME": "cfg"}),
        (['favorite {"action": "save", "name": "Timber"}'], {"XDG_CONFIG_HOME": "cfg"}),
        (['favorite {"action": "save", "name": "Glass"}'], {}),
        (lst, {"BIMCRAFT_FAVORITES": "favs/mine.json"}),
        (lst, {"XDG_CONFIG_HOME": "cfg"}),
        (lst, {}),
    ]
    golden.check(transcript(run, env, steps), "search_order.txt")
    home = os.path.join(env["HOME"], ".config", "bimcraft", "favorites.json")
    golden.check((workdir / "favs" / "mine.json").read_text() + "\n---\n" + (workdir / "cfg" / "bimcraft" / "favorites.json").read_text()
                 + "\n---\n" + open(home, encoding="utf-8").read(), "search_order_files.golden")
    # (A coverage-instrumented build may leave its .profraw data behind; that is no file of the program's.)
    assert sorted(n for n in os.listdir(workdir) if not n.endswith(".profraw")) == ["cfg", "favs"]


def test_save_list_load_and_delete(run, workdir, env, golden):
    """CATCHES: a rewrite whose favorites file differs from the reference's (its version, keys, a family's forms and the
    materials it is made of), whose `as` and `replace` work differently, that overwrites a project's material or family
    without `replace`, or whose replies and refusals differ."""
    f = {"BIMCRAFT_FAVORITES": "fav.json"}
    steps = [
        (['material {"name": "Oak", "color": "#a07040", "cut": "diagonal", "texture": {"kind": "boards", "size": [600, 300]}}',
          'favorite {"action": "save", "kind": "material", "name": "Oak"}',
          'favorite {"action": "save", "name": "Oak", "as": "  Oak Boards  "}',
          'family {"name": "Crate", "parameters": [{"name": "M", "kind": "material", "value": "Oak"}], "types": {"A": {}},'
          ' "forms": [{"profile": [[0, 0], [500, 0], [500, 500], [0, 500]], "to": 500, "material": "M"},'
          ' {"profile": [[0, 0], [100, 0], [100, 100], [0, 100]], "from": 500, "to": 600, "material": "Metal"}]}',
          'favorite {"action": "save", "kind": "family", "name": "Crate"}',
          'favorite {"action": "save", "kind": "family", "name": "Crate", "as": "Box"}',
          'favorite {}'], f),
        # Into a project of its own: a family brings the materials it's made of, the project's own of a name staying.
        (['favorite {"action": "load", "kind": "family", "name": "Crate"}', 'family {"name": "Crate"}', 'material {"name": "Oak"}',
          'undo', 'material {"name": "Oak", "color": "#000000"}', 'favorite {"action": "load", "kind": "family", "name": "Box", "as": "Kist"}',
          'material {"name": "Oak"}', 'family {}'], f),
        (['favorite {"action": "load", "name": "Oak Boards"}', 'favorite {"action": "load", "name": "Oak Boards", "as": "Plank"}',
          'material {"name": "Plank"}', 'library {"kind": "material", "name": "Plank"}'], f),
        (['favorite {"action": "load", "name": "Oak", "as": "Brick"}'], f),
        (['favorite {"action": "load", "name": "Oak", "as": "Brick", "replace": true}', 'material {"name": "Brick"}'], f),
        (['favorite {"action": "load", "kind": "family", "name": "Crate", "as": "Table"}'], f),
        (['favorite {"action": "load", "kind": "family", "name": "Crate", "as": "Table", "replace": true}', 'family {"name": "Table"}'], f),
        (['favorite {"action": "load", "name": "Nope"}'], f),
        (['favorite {"action": "load", "kind": "family", "name": "Nope"}'], f),
        (['favorite {"action": "load"}'], f),
        (['favorite {"action": "save", "kind": "family"}'], f),
        (['favorite {"action": "save", "name": "Nope"}'], f),
        (['favorite {"action": "save", "kind": "family", "name": "Nope"}'], f),
        (['favorite {"action": "save", "name": "   "}'], f),
        (['favorite {"action": "delete", "name": "Nope"}'], f),
        (['favorite {"action": "delete", "kind": "family", "name": "Oak"}'], f),
        (['favorite {"kind": "texture"}'], f),
        (['favorite {"action": "export"}'], f),
        (['favorite {"action": "list", "replace": "yes"}'], f),
        (['favorite {"action": "delete", "name": "Oak"}', 'favorite {"action": "delete", "kind": "family", "name": "Box"}', 'favorite {}'], f),
    ]
    golden.check(transcript(run, env, steps), "save_list_load_delete.txt")
    golden.check(normalize((workdir / "fav.json").read_text()), "fav.json.golden")


def test_a_material_is_kept_with_its_picture(run, workdir, env, golden):
    """CATCHES: a rewrite that keeps a favorite material without the picture its texture is made of, writes the picture
    differently, or brings the picture into a project twice."""
    (workdir / "grass.png").write_bytes((resources_for(__file__) / "grass.png").read_bytes())  # a 4 x 2 green PNG
    f = {"BIMCRAFT_FAVORITES": "pics.json"}
    steps = [
        (['material {"name": "Lawn", "texture": {"kind": "image", "path": "grass.png"}}', 'favorite {"action": "save", "name": "Lawn"}',
          'favorite {"action": "list"}'], f),
        (['favorite {"action": "load", "name": "Lawn"}', 'favorite {"action": "load", "name": "Lawn", "as": "Meadow"}',
          'library {"kind": "picture"}', 'material {"name": "Meadow"}'], f),
    ]
    golden.check(transcript(run, env, steps), "picture.txt")
    golden.check((workdir / "pics.json").read_text(), "pics.json.golden")


BAD_FILES = {
    "not_json": "not json",
    "unknown_field": '{"extra": 1}',
    "empty_name": '{"materials": {"": {"material": {"color": [1, 2, 3]}}}}',
    "blank_family_name": '{"families": {" ": {"family": {"types": {"A": {}}}}}}',
    "missing_picture": '{"materials": {"X": {"material": {"color": [1, 2, 3], "texture": {"kind": "image", "size": [10, 10], "image": "nope"}}}}}',
    "tile_of_no_size": '{"materials": {"X": {"material": {"color": [1, 2, 3], "texture": {"kind": "brick", "size": [0, 10]}}}}}',
    "family_without_types": '{"families": {"F": {"family": {"types": {}}}}}',
    "family_that_does_not_build": '{"families": {"F": {"family": {"types": {"A": {}}, "forms": [{"profile": [[0, 0], [1, 0], [1, 1]], "to": 1}]},'
                                    ' "materials": {"": {"material": {"color": [1, 2, 3]}}}}}}',
    "a_list": "[1, 2, 3]",
    "wrong_version_type": '{"version": "one"}',
    "too_many": json.dumps({"materials": {f"M{i}": {"material": {"color": [1, 2, 3]}} for i in range(501)}}),
    "foreign_project": None,  # a .bimcraft project given as the favorites file
}


@pytest.mark.parametrize("case", sorted(BAD_FILES))
def test_a_favorites_file_that_is_not_one_is_refused(run, workdir, golden, case):
    """CATCHES: a rewrite that reads a broken, foreign or overfull favorites file instead of refusing it, refuses a
    sound one, or words the refusal (and the path it names) differently from the reference; and that writes over the
    bad file when saving."""
    if BAD_FILES[case] is None:
        assert run(["run", "--cmd", 'wall {"points": [[0, 0], [1000, 0]]}', "--save", "bad.json"]).returncode == 0
    else:
        (workdir / "bad.json").write_text(BAD_FILES[case])
    before = (workdir / "bad.json").read_bytes()
    r1 = run(["run", "--cmd", 'favorite {"path": "bad.json"}'])
    r2 = run(["run", "--cmd", 'favorite {"action": "save", "name": "Brick", "path": "bad.json"}'])
    text = "".join(f"exit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}" for r in (r1, r2))
    golden.check(text, f"bad_{case}.txt")
    assert (workdir / "bad.json").read_bytes() == before


def test_a_favorites_file_too_large_or_unreadable(run, workdir, golden):
    """CATCHES: a rewrite that reads a favorites file of 256 MiB or more instead of refusing it by its size, or that
    reports a folder given as the file, or a file it can't write, differently."""
    with open(workdir / "huge.json", "wb") as f:
        f.truncate(256 << 20)  # sparse: takes no room on disk
    (workdir / "folder.json").mkdir()
    (workdir / "plain").write_text("a file, not a folder")
    out = []
    for cmd in ['favorite {"path": "huge.json"}', 'favorite {"path": "folder.json"}',
                'favorite {"action": "save", "name": "Brick", "path": "plain/favorites.json"}',
                'favorite {"action": "save", "name": "Brick", "path": "folder.json"}']:
        r = run(["run", "--cmd", cmd])
        out.append(f"=== {cmd}\nexit: {r.returncode}\n--- stdout\n{r.stdout.decode()}--- stderr\n{r.stderr.decode()}")
    golden.check("".join(out), "too_large_or_unreadable.txt")
    assert os.path.getsize(workdir / "huge.json") == 256 << 20


def _png(rgb):
    """A 2 x 2 PNG of one colour."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * 2 for _ in range(2))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_pictures_beyond_what_a_project_or_a_favorite_holds(run, workdir, golden):
    """CATCHES: a rewrite that loads a favorite material's picture into a project that holds 24 pictures already, or
    reads a favorite holding more than 24 pictures, instead of refusing with the reference's words."""
    import base64
    (workdir / "grass.png").write_bytes((resources_for(__file__) / "grass.png").read_bytes())
    f = {"BIMCRAFT_FAVORITES": "fav.json"}
    r1 = run(["run", "--cmd", 'material {"name": "Lawn", "texture": {"kind": "image", "path": "grass.png"}}',
              "--cmd", 'favorite {"action": "save", "name": "Lawn"}'], env_overrides=f)
    for k in range(24):
        (workdir / f"c{k}.png").write_bytes(_png((k * 10, 100, 50)))
    args = []
    for k in range(24):
        args += ["--cmd", f'material {{"name": "M{k}", "texture": {{"kind": "image", "path": "c{k}.png"}}}}']
    r2 = run(["run", *args, "--cmd", 'favorite {"action": "load", "name": "Lawn"}'], env_overrides=f)
    png = base64.b64encode(_png((1, 2, 3))).decode()
    images = {f"img-{k}": {"name": f"p{k}", "png": png} for k in range(25)}
    (workdir / "many.json").write_text(json.dumps({"materials": {"X": {"material": {"color": [1, 2, 3]}, "images": images}}}))
    r3 = run(["run", "--cmd", 'favorite {"path": "many.json"}'])
    text = "".join(f"exit: {r.returncode}\n--- stdout\n{normalize(r.stdout.decode())}--- stderr\n{r.stderr.decode()}" for r in (r1, r2))
    text += f"exit: {r3.returncode}\n--- stdout\n{r3.stdout.decode()}--- stderr\n{r3.stderr.decode()}"
    golden.check(text, "too_many_pictures.txt")
