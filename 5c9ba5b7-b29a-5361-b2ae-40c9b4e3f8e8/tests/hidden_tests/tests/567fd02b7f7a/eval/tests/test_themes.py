"""`lini theme [NAME]` and the `--theme NAME|FILE|A/B` flag: built-in names,
light/dark pairs, CSS override files, --no-fs, and their error messages."""

import pytest

from conftest import Case, transcript

SRC = (
    '{ |svc::box| { fill: --teal-wash; stroke: --teal-ink; } }\n'
    '|svc#api| "API"\n'
    '|box#db| "DB" { fill: --accent; color: --accent-text; }\n'
    'api -> db "query"\n'
)
FILES = {"a.lini": SRC}
OVERRIDES = (
    "/* my palette */\n"
    ":root, .lini {\n"
    "  --lini-accent: hotpink;\n"
    "  --lini-fill: #123456; --lini-teal-wash: rgb(10, 20, 30);\n"
    "  --other-var: 1px;\n"
    "  --lini-stroke: light-dark(#111, #eee)\n"
    "}\n"
)

THEME_CMD_CASES = {
    "theme_list": Case(("theme",)),
    "theme_print_default": Case(("theme", "default")),
    "theme_print_light": Case(("theme", "light")),
    "theme_print_dark": Case(("theme", "dark")),
    "theme_print_high_contrast": Case(("theme", "high-contrast")),
    "theme_print_blueprint": Case(("theme", "blueprint")),
    "theme_unknown_name": Case(("theme", "solarized")),
    "theme_empty_name": Case(("theme", "")),
    "theme_pair_not_printable": Case(("theme", "light/dark")),
    "theme_name_is_case_sensitive": Case(("theme", "Dark")),
}

THEME_FLAG_CASES = {
    "flag_default": Case(("--theme", "default", "a.lini"), files=FILES),
    "flag_light": Case(("--theme", "light", "a.lini"), files=FILES),
    "flag_dark": Case(("--theme", "dark", "a.lini"), files=FILES),
    "flag_high_contrast": Case(("--theme", "high-contrast", "a.lini"), files=FILES),
    "flag_blueprint": Case(("--theme", "blueprint", "a.lini"), files=FILES),
    "flag_blueprint_static": Case(("--theme", "blueprint", "--static", "a.lini"), files=FILES),
    "flag_dark_static": Case(("--theme", "dark", "--static", "a.lini"), files=FILES),
    "flag_pair_light_dark": Case(("--theme", "light/dark", "a.lini"), files=FILES),
    "flag_pair_dark_light": Case(("--theme", "dark/light", "a.lini"), files=FILES),
    "flag_pair_spaced": Case(("--theme", "light / high-contrast", "a.lini"), files=FILES),
    "flag_pair_blueprint_dark": Case(("--theme", "blueprint/dark", "a.lini"), files=FILES),
    "flag_pair_static": Case(("--theme", "light/dark", "--static", "a.lini"), files=FILES),
    "flag_pair_unknown_arm": Case(("--theme", "dark/nope", "a.lini"), files=FILES),
    "flag_file_overrides": Case(("--theme", "my.css", "a.lini"), files={**FILES, "my.css": OVERRIDES}),
    "flag_file_overrides_static": Case(("--theme", "my.css", "--static", "a.lini"),
                                       files={**FILES, "my.css": OVERRIDES}),
    "flag_file_in_subdirectory": Case(("--theme", "themes/my.css", "--static", "a.lini"),
                                      files={**FILES, "themes/my.css": OVERRIDES}),
    "flag_file_without_lini_vars": Case(("--theme", "plain.css", "a.lini"),
                                        files={**FILES, "plain.css": "body { color: red; }\n"}),
    "flag_file_missing": Case(("--theme", "missing.css", "a.lini"), files=FILES),
    "flag_unknown_name": Case(("--theme", "solarized", "a.lini"), files=FILES),
    "flag_file_is_directory": Case(("--theme", "themes", "a.lini"), files={**FILES, "themes/x.css": ""}),
    "flag_theme_html": Case(("--theme", "dark", "--format", "html", "a.lini"), files=FILES),
    "flag_theme_with_check": Case(("--theme", "dark", "--check", "w.lini"),
                                  files={"w.lini": "{ .unused { fill: red; } }\n|box#a| \"A\"\n"}),
    "flag_theme_with_json": Case(("--theme", "dark", "--json", "a.lini"), files=FILES),
    "flag_theme_error_before_input": Case(("--theme", "missing.css", "missing.lini")),
}

NO_FS_CASES = {
    "no_fs_builtin_ok": Case(("--no-fs", "--theme", "high-contrast", "a.lini"), files=FILES),
    "no_fs_pair_ok": Case(("--no-fs", "--theme", "dark/light", "a.lini"), files=FILES),
    "no_fs_rejects_theme_file": Case(("--no-fs", "--theme", "my.css", "a.lini"),
                                     files={**FILES, "my.css": OVERRIDES}),
    "no_fs_rejects_unknown_name": Case(("--no-fs", "--theme", "nope", "a.lini"), files=FILES),
    "no_fs_plain_compile": Case(("--no-fs", "a.lini"), files=FILES),
    "no_fs_stdin": Case(("--no-fs", "-"), stdin=SRC),
}

SERVE_THEME_CASES = {
    "serve_theme_unknown": Case(("serve", "--theme", "nope", "a.lini"), files=FILES),
    "serve_missing_path": Case(("serve", "missing.lini")),
    "serve_missing_dir": Case(("serve", "nowhere/")),
    "serve_missing_path_before_theme": Case(("serve", "--theme", "nope", "missing.lini")),
}


@pytest.mark.parametrize("name", sorted(THEME_CMD_CASES))
def test_theme_subcommand(run_case, golden, name):
    """CATCHES: a changed theme list or descriptions, a printed palette with wrong
    `--lini-*` values or ordering, the font family not commented out, or unknown
    names accepted / exiting with a code other than 3."""
    assert run_case(THEME_CMD_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(THEME_FLAG_CASES))
def test_theme_flag(run_case, golden, name):
    """CATCHES: --theme not reaching the emitted CSS variables, a light/dark pair
    composed in the wrong order or not trimmed, override files parsed wrongly
    (comments, non-lini vars, several declarations per line), --static not baking
    the themed values, or the wrong error/exit code for an unreadable theme."""
    assert run_case(THEME_FLAG_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(NO_FS_CASES))
def test_theme_no_fs(run_case, golden, name):
    """CATCHES: --no-fs still reading a theme file from disk, rejecting built-in
    names or pairs, or reporting the refusal with the wrong message/exit code."""
    assert run_case(NO_FS_CASES[name]) == golden(name)


@pytest.mark.parametrize("name", sorted(SERVE_THEME_CASES))
def test_serve_startup_errors(run_case, golden, name):
    """CATCHES: `lini serve` binding a port (or hanging) when its path is missing or
    its theme is unreadable, instead of failing fast with exit 2 and a message."""
    assert run_case(SERVE_THEME_CASES[name]) == golden(name)


def test_printed_theme_round_trips_as_a_file(run, workdir, golden):
    """CATCHES: `lini theme NAME` printing CSS that, fed back through --theme FILE,
    does not reproduce the built-in's look (a lossy or reformatted palette)."""
    (workdir / "a.lini").write_text(SRC)
    printed = run(["theme", "blueprint"])
    assert printed.returncode == 0
    (workdir / "blueprint.css").write_bytes(printed.stdout)
    via_file = run(["--static", "--theme", "blueprint.css", "a.lini"])
    via_name = run(["--static", "--theme", "blueprint", "a.lini"])
    assert via_file.returncode == 0
    assert via_file.stdout == via_name.stdout
    assert transcript(via_file, workdir) == golden("flag_blueprint_static")
