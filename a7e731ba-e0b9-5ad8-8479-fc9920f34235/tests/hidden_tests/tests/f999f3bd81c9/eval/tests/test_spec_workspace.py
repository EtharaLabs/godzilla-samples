"""Spec workspace behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_command_line_wrap_overrides_format_config(run, workdir):
    """CATCHES: reimplementations that break "command line wrap overrides format config" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "none"\n'
        ),
    }
    write_tree(workdir, files)
    stdin = 'First sentence. Second sentence.\n'
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml', '--wrap', 'sentence'],
        input=stdin,
    )
    assert result.stdout == (RES / 'command_line_wrap_overrides_format_config.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_directory_diagnostics_are_deterministic_for_multiple_yaml_failures(run, workdir):
    """CATCHES: reimplementations that break "directory diagnostics are deterministic for multiple yaml failures" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'a.yaml': (
            '# fmt: markdown\n'
            'items: [one, two]\n'
        ),
        'b.yaml': (
            '# fmt: markdown\n'
            'items: [one, two]\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', '--diagnostics', '.'])
    assert result.stdout == b'2 files scanned, 0 formatted, 0 unchanged, 0 skipped, 2 failed\n'
    assert result.stderr.decode() == (
        './a.yaml:2:8: error: fmt: markdown targets a scalar value\n'
        './b.yaml:2:8: error: fmt: markdown targets a scalar value\n'
    )
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_discovered_format_config_sets_markdown_wrap(run, workdir):
    """CATCHES: reimplementations that break "discovered format config sets markdown wrap" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "sentence"\n'
        ),
        'input.md': 'First sentence. Second sentence.\n',
    }
    write_tree(workdir, files)
    result = run(['format', 'input.md'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'input.md': (
            'First sentence.\n'
            'Second sentence.\n'
        ),
    }))
    assert read_tree(workdir) == expected


def test_embedded_config_must_be_a_table(run, workdir):
    """CATCHES: reimplementations that break "embedded config must be a table" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': 'embedded = true\n',
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: embedded config must be a table\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_discovered_nested_config_path_configs_match_relative_to_config_dir(run, workdir):
    """CATCHES: reimplementations that break "discovered nested config path configs match relative to config dir" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'sub/yamark.toml': (
            '[paths."docs".template]\n'
            'add_delimiters = [{ open = "%%", close = "%%" }]\n'
        ),
        'sub/docs/a.md': 'This %% keep   this %% paragraph.\n',
    }
    write_tree(workdir, files, dirs=['sub', 'sub/docs'])
    result = run(['format', 'sub/docs/a.md'])
    assert result.stdout == b'1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_directory_formatting_starts_before_later_config_discovery_fails(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "directory formatting starts before later config discovery fails" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'formatter.py': (
            'import pathlib, sys\n'
            'pathlib.Path(sys.argv[1]).touch()\n'
            'sys.stdout.buffer.write(sys.stdin.buffer.read())\n'
        ),
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "./formatter.py", "./formatter-ran", "{path}"], path_suffix = ".txt" }\n'
        ),
        'a.md': (
            '```txt\n'
            'abc\n'
            '```\n'
        ),
        'z/yamark.toml': (
            '[format]\n'
            'unknown = true\n'
        ),
        'z/b.md': '# Title\n',
    }
    write_tree(workdir, files, dirs=['z'])
    result = run(['format', '.'])
    tmp = str(tmp_path).encode()
    assert result.stdout.replace(tmp, b"{TMP}") == b""
    assert result.stderr.replace(tmp, b"{TMP}").decode() == '{TMP}/work/z/yamark.toml:1:1: error: unknown format config key: format.unknown\n'
    assert result.returncode == 1
    expected = as_bytes(files)
    expected.update(as_bytes({
        'formatter-ran': "",
    }))
    assert read_tree(workdir) == expected


def test_explicit_config_path_configs_match_relative_to_config_dir(run, workdir):
    """CATCHES: reimplementations that break "explicit config path configs match relative to config dir" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'configs/yamark.toml': (
            '[paths."docs".template]\n'
            'add_delimiters = [{ open = "%%", close = "%%" }]\n'
        ),
        'docs/a.md': 'This %% keep   this %% paragraph.\n',
    }
    write_tree(workdir, files, dirs=['configs', 'docs'])
    result = run(['format', '--config', 'configs/yamark.toml', 'docs/a.md'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'docs/a.md': 'This %% keep this %% paragraph.\n',
    }))
    assert read_tree(workdir) == expected


def test_explicit_parent_symlink_directory_walk_does_not_recurse_through_nested_symlink(run, workdir):
    """CATCHES: reimplementations that break "explicit parent symlink directory walk does not recurse through nested symlink" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'parent/parent.md': '#   Parent ##\n',
        'parent/child/child.md': '#   Child ##\n',
    }
    write_tree(workdir, files, dirs=['parent', 'parent/child'])
    (workdir / 'parent/child/up').parent.mkdir(parents=True, exist_ok=True)
    (workdir / 'parent/child/up').symlink_to('..')
    result = run(['format', 'parent/child/up'])
    assert result.stdout == b'2 files scanned, 2 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'parent/parent.md': '# Parent\n',
        'parent/child/child.md': '# Child\n',
    }))
    assert read_tree(workdir) == expected


def test_explicit_symlink_directories_are_walked(run, workdir):
    """CATCHES: reimplementations that break "explicit symlink directories are walked" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'target/a.md': '#   Title ##\n',
    }
    write_tree(workdir, files, dirs=['target'])
    (workdir / 'link').parent.mkdir(parents=True, exist_ok=True)
    (workdir / 'link').symlink_to('target')
    result = run(['format', 'link'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'target/a.md': '# Title\n',
    }))
    assert read_tree(workdir) == expected


def test_explicit_symlink_targets_are_deduplicated_by_canonical_path(run, workdir):
    """CATCHES: reimplementations that break "explicit symlink targets are deduplicated by canonical path" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'a.md': '#   Title ##\n',
    }
    write_tree(workdir, files)
    (workdir / 'link.md').parent.mkdir(parents=True, exist_ok=True)
    (workdir / 'link.md').symlink_to('a.md')
    result = run(['format', 'a.md', 'link.md'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'a.md': '# Title\n',
    }))
    assert read_tree(workdir) == expected


def test_file_contents_are_valid_utf8(run, workdir):
    """CATCHES: reimplementations that break "file contents are valid utf8" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'bad.md': b'\xff\xfe\x00\x00',
    }
    write_tree(workdir, files)
    result = run(['format', 'bad.md'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 0 skipped, 1 failed\n'
    assert result.stderr.decode() == 'bad.md:1:1: error: failed to read file: unsupported encoding: UTF-16 BOM\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_format_config_rejects_invalid_markdown_wrap(run, workdir):
    """CATCHES: reimplementations that break "format config rejects invalid markdown wrap" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "wide"\n'
        ),
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: format.wrap must be none, paragraph, sentence, a positive integer, or sentence:<positive integer>\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_format_skips_cmd_files(run, workdir):
    """CATCHES: reimplementations that break "format skips cmd files" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'build.cmd': (
            'Title\n'
            '=====\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', 'build.cmd'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_format_skips_json_family_files_without_rewriting_them_1(run, workdir):
    """CATCHES: reimplementations that break "format skips json family files without rewriting them" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    files = {
        'input.json': '{"unformatted":[1,2]}\n',
    }
    write_tree(workdir, files)
    result = run(['format', 'input.json'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_format_skips_json_family_files_without_rewriting_them_2(run, workdir):
    """CATCHES: reimplementations that break "format skips json family files without rewriting them" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    files = {
        'input.json': '{"unformatted":[1,2]}\n',
        'input.jsonc': (
            '{// comment\n'
            '"unformatted":[1,2,],}\n'
        ),
    }
    write_tree(workdir, files)
    result = run(['format', 'input.jsonc'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_format_skips_json_family_files_without_rewriting_them_3(run, workdir):
    """CATCHES: reimplementations that break "format skips json family files without rewriting them" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    files = {
        'input.json': '{"unformatted":[1,2]}\n',
        'input.jsonc': (
            '{// comment\n'
            '"unformatted":[1,2,],}\n'
        ),
        'input.json5': '{unformatted:[1,2,],}\n',
    }
    write_tree(workdir, files)
    result = run(['format', 'input.json5'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_format_skips_json_family_files_without_rewriting_them_4(run, workdir):
    """CATCHES: reimplementations that break "format skips json family files without rewriting them" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    files = {
        'input.json': '{"unformatted":[1,2]}\n',
        'input.jsonc': (
            '{// comment\n'
            '"unformatted":[1,2,],}\n'
        ),
        'input.json5': '{unformatted:[1,2,],}\n',
        'input.jsonl': '{"unformatted":[1,2]}\n',
    }
    write_tree(workdir, files)
    result = run(['format', 'input.jsonl'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_format_skips_json_family_files_without_rewriting_them_5(run, workdir):
    """CATCHES: reimplementations that break "format skips json family files without rewriting them" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    files = {
        'input.json': '{"unformatted":[1,2]}\n',
        'input.jsonc': (
            '{// comment\n'
            '"unformatted":[1,2,],}\n'
        ),
        'input.json5': '{unformatted:[1,2,],}\n',
        'input.jsonl': '{"unformatted":[1,2]}\n',
        'input.ndjson': '{"unformatted":[1,2]}\n',
    }
    write_tree(workdir, files)
    result = run(['format', 'input.ndjson'])
    assert result.stdout == b'1 files scanned, 0 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_git_filter_wrap_ignores_format_config(run, workdir):
    """CATCHES: reimplementations that break "git filter wrap ignores format config" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'wrap = "none"\n'
        ),
    }
    write_tree(workdir, files)
    stdin = 'First sentence. Second sentence.\n'
    result = run(['git-filter', 'clean', '--stdin-filename', 'input.md'], input=stdin)
    assert result.stdout == (RES / 'git_filter_wrap_ignores_format_config.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_invalid_config_keys_fail(run, workdir):
    """CATCHES: reimplementations that break "invalid config keys fail" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'unknown = true\n'
        ),
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: unknown format config key: format.unknown\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_non_spec_hard_break_space_config_is_rejected(run, workdir):
    """CATCHES: reimplementations that break "non spec hard break space config is rejected" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'preserve_markdown_hard_break_spaces = true\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        'line with hard break  \n'
        'next line\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: unknown format config key: format.preserve_markdown_hard_break_spaces\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_path_specific_embedded_markdown_template_config_preserves_targets(run, workdir):
    """CATCHES: reimplementations that break "path specific embedded markdown template config preserves targets" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[paths."docs".embedded_markdown.template]\n'
            'add_delimiters = [{ open = "[[", close = "]]" }]\n'
        ),
        'docs/a.py': (
            '# fmt: markdown\n'
            '# This [[ keep   spacing ]] paragraph.\n'
        ),
    }
    write_tree(workdir, files, dirs=['docs'])
    result = run(['format', 'docs/a.py'])
    assert result.stdout == b'1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_path_specific_template_config_applies_during_relative_directory_scan(run, workdir):
    """CATCHES: reimplementations that break "path specific template config applies during relative directory scan" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[paths."docs".template]\n'
            'add_delimiters = [{ open = "<<", close = ">>" }]\n'
        ),
        'docs/a.md': 'This << keep   this >> paragraph.\n',
    }
    write_tree(workdir, files, dirs=['docs'])
    result = run(['format', '.'])
    assert result.stdout == b'2 files scanned, 0 formatted, 1 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_path_specific_template_config_preserves_matching_blocks(run, workdir):
    """CATCHES: reimplementations that break "path specific template config preserves matching blocks" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[paths."docs".template]\n'
            'add_delimiters = [{ open = "<<", close = ">>" }]\n'
        ),
        'docs/a.md': 'This << keep   this >> paragraph.\n',
    }
    write_tree(workdir, files, dirs=['docs'])
    result = run(['format', 'docs/a.md'])
    assert result.stdout == b'1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_path_template_delimiter_entries_reject_unknown_fields(run, workdir):
    """CATCHES: reimplementations that break "path template delimiter entries reject unknown fields" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[paths."docs".template]\n'
            'add_delimiters = [{ open = "<<", close = ">>", extra = true }]\n'
        ),
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'docs/input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: unknown template delimiter key: paths.docs.template.add_delimiters.extra\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_paths_modes_config_and_skips_are_deterministic_1(run, workdir):
    """CATCHES: reimplementations that break "paths modes config and skips are deterministic" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'markdown_horizontal_rule = "***"\n'
        ),
        'a.md': (
            '#   Title ##\n'
            '\n'
            '---\n'
        ),
        'ignored.txt': '#   Title ##\n',
    }
    write_tree(workdir, files)
    result = run(['format', 'a.md', 'ignored.txt'])
    assert result.stdout == b'2 files scanned, 1 formatted, 0 unchanged, 1 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    expected = as_bytes(files)
    expected.update(as_bytes({
        'a.md': (
            '# Title\n'
            '\n'
            '***\n'
        ),
    }))
    assert read_tree(workdir) == expected


def test_paths_modes_config_and_skips_are_deterministic_2(run, workdir):
    """CATCHES: reimplementations that break "paths modes config and skips are deterministic" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'markdown_horizontal_rule = "***"\n'
        ),
        'a.md': '#   Title ##\n',
        'ignored.txt': '#   Title ##\n',
    }
    write_tree(workdir, files)
    result = run(['format', '--check', 'a.md'])
    assert result.stdout == b""
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_paths_modes_config_and_skips_are_deterministic_3(run, workdir):
    """CATCHES: reimplementations that break "paths modes config and skips are deterministic" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    files = {
        'yamark.toml': (
            '[format]\n'
            'markdown_horizontal_rule = "***"\n'
        ),
        'a.md': '#   Title ##\n',
        'ignored.txt': '#   Title ##\n',
    }
    write_tree(workdir, files)
    result = run(['format', '--diff', 'a.md'])
    assert result.stdout == (RES / 'paths_modes_config_and_skips_are_deterministic_3.golden').read_bytes()
    assert result.stderr.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_relative_explicit_config_applies_path_config_to_absolute_paths(run, workdir):
    """CATCHES: reimplementations that break "relative explicit config applies path config to absolute paths" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[paths."docs".template]\n'
            'add_delimiters = [{ open = "<<", close = ">>" }]\n'
        ),
        'docs/a.md': 'This << keep   this >> paragraph.\n',
    }
    write_tree(workdir, files, dirs=['docs'])
    result = run(['format', '--config', 'yamark.toml', 'docs/a.md'])
    assert result.stdout == b'1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_template_delimiter_entries_reject_unknown_fields(run, workdir):
    """CATCHES: reimplementations that break "template delimiter entries reject unknown fields" (workspace); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[template]\n'
            'add_delimiters = [{ open = "<<", close = ">>", extra = true }]\n'
        ),
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: unknown template delimiter key: template.add_delimiters.extra\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)
