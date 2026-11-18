"""Themes: `lini theme` listing/printing and `--theme` on a compile (built-in
names, light/dark pairs, CSS files) in live and --static output."""

import pytest

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

BUILTINS = ["default", "light", "dark", "high-contrast", "blueprint"]

SCENE = """{ fill: --bg; padding: 24; }
|box#api| "API" { fill: --teal-wash; stroke: --teal-ink; color: --teal-ink; }
|cyl#db| "DB" { fill: --accent; color: --accent-text; }
|group#g| "Edge" [ |box#cdn| "CDN" { stroke: --muted; } ]
api -> db "reads" { stroke: --danger; }
g.cdn --> api { color: --warn; }
"""

THEME_FILE = """/* my overrides */
:root, .lini {
  --lini-accent: hotpink;
  --lini-bg: #fdf6e3;
  --lini-teal-wash: rgb(200, 240, 230);
}
"""


def test_theme_list(run):
    """CATCHES: a theme listing with missing/renamed themes, different descriptions or column padding."""
    r = run(["theme"])
    assert outcome(r) == G("theme_list")


@pytest.mark.parametrize("name", BUILTINS)
def test_theme_print(run, name):
    """CATCHES: a built-in theme printed with different --lini-* variables, values, ordering or comments."""
    r = run(["theme", name])
    assert outcome(r) == G(f"theme_{name}")


def test_theme_unknown(run):
    """CATCHES: an unknown theme name not failing with exit 3 and the list of valid names."""
    r = run(["theme", "solarized"])
    assert outcome(r) == "exit: 3\n--- stdout ---\n--- stderr ---\nerror: unknown theme 'solarized' (try one of: default, light, dark, high-contrast, blueprint)\n"


@pytest.mark.parametrize("name", BUILTINS)
def test_compile_with_builtin_theme_live(run, name):
    """CATCHES: --theme NAME not layering the theme's variables into the live @layer lini.defaults block (or changing layout)."""
    r = run(["--theme", name, "-"], input=SCENE)
    assert outcome(r) == G(f"live_{name}")


@pytest.mark.parametrize("name", BUILTINS)
def test_compile_with_builtin_theme_static(run, name):
    """CATCHES: --static --theme NAME baking the wrong literal colours for that theme."""
    r = run(["--static", "--theme", name, "-"], input=SCENE)
    assert outcome(r) == G(f"static_{name}")


@pytest.mark.parametrize("pair", ["light/dark", "dark/light", "light/high-contrast", "blueprint/dark", " light / dark "])
def test_compile_with_theme_pair(run, pair):
    """CATCHES: a light/dark theme pair not combined into light-dark() values (or not trimmed around the slash)."""
    r = run(["--theme", pair, "-"], input=SCENE)
    assert outcome(r) == G("pair_" + pair.strip().replace(" ", "").replace("/", "_"))


def test_compile_with_theme_file(run, workdir):
    """CATCHES: a CSS theme file not read, or its --lini-* overrides not applied in the live output."""
    write_files(workdir, {"mine.css": THEME_FILE})
    r = run(["--theme", "mine.css", "-"], input=SCENE)
    assert outcome(r) == G("file_live")


def test_compile_with_theme_file_static(run, workdir):
    """CATCHES: --static not baking a file theme's overrides into literal colours."""
    write_files(workdir, {"mine.css": THEME_FILE})
    r = run(["--static", "--theme", "mine.css", "-"], input=SCENE)
    assert outcome(r) == G("file_static")


def test_printed_theme_round_trips(run, workdir):
    """CATCHES: `lini theme NAME` output that, fed back as --theme FILE, does not reproduce the built-in's static colours."""
    printed = run(["theme", "blueprint"]).stdout
    write_files(workdir, {"bp.css": printed})
    from_file = run(["--static", "--theme", "bp.css", "-"], input=SCENE)
    assert outcome(from_file) == G("static_blueprint")


def test_theme_missing_file(run):
    """CATCHES: an unknown theme that is not a readable file not failing with exit 2 and the combined message."""
    r = run(["--theme", "nosuch.css", "-"], input=SCENE)
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: theme 'nosuch.css': not a built-in (try: default, light, dark, high-contrast, blueprint), and reading it as a file failed: No such file or directory (os error 2)\n"


def test_theme_bad_pair_falls_back_to_file(run):
    """CATCHES: a pair with an unknown half accepted, instead of being tried as a file path and failing with exit 2."""
    r = run(["--theme", "dark/nosuch", "-"], input=SCENE)
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: theme 'dark/nosuch': not a built-in (try: default, light, dark, high-contrast, blueprint), and reading it as a file failed: No such file or directory (os error 2)\n"


def test_no_fs_refuses_theme_file(run, workdir):
    """CATCHES: --no-fs still reading a theme file from disk (must exit 3 without reading it)."""
    write_files(workdir, {"mine.css": THEME_FILE})
    r = run(["--no-fs", "--theme", "mine.css", "-"], input=SCENE)
    assert outcome(r) == "exit: 3\n--- stdout ---\n--- stderr ---\nerror: theme 'mine.css' is not a built-in (try: default, light, dark, high-contrast, blueprint), and --no-fs reads no theme file\n"


def test_no_fs_allows_builtin_theme(run):
    """CATCHES: --no-fs wrongly rejecting a built-in theme name or pair."""
    r = run(["--no-fs", "--theme", "light/dark", "-"], input=SCENE)
    assert outcome(r) == G("pair_light_dark")


def test_theme_does_not_change_layout_vars(run, workdir):
    """CATCHES: a theme file whose layout-looking variables (--lini-gap) move boxes; only visual vars are themeable."""
    write_files(workdir, {"gap.css": ":root { --lini-gap: 90; --lini-accent: red; }\n"})
    r = run(["--theme", "gap.css", "-"], input='{ direction: row; }\n|box| { width: 40; height: 40; }\n|box| { width: 40; height: 40; fill: --accent; }\n')
    assert outcome(r) == G("gap_theme")
