"""Spec external formatters behaviour.

Converted from the project's own CLI specifications: each test runs one
recorded invocation in an empty workdir and compares stdout, stderr, exit
status and any files on disk with the reference binary's results.
"""

import os  # noqa: F401

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_code_fence_formatter_output_cannot_close_original_fence_with_cr_only_lines(run, workdir):
    """CATCHES: reimplementations that break "code fence formatter output cannot close original fence with cr only lines" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'formatter': (
            '#!/bin/sh\n'
            "printf 'ok\\r```\\r'\n"
        ),
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["./formatter", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files, executable=['formatter'])
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: formatted code fence would contain closing fence\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_code_fence_formatter_output_cannot_close_the_original_fence(run, workdir):
    """CATCHES: reimplementations that break "code fence formatter output cannot close the original fence" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'```\\\\n\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: formatted code fence would contain closing fence\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_embedded_formatter_nonzero_with_empty_stderr_reports_context(run, workdir):
    """CATCHES: reimplementations that break "embedded formatter nonzero with empty stderr reports context" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.exit(7)", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:1: error: embedded formatter failed: command `python3 -c import sys; sys.exit(7) input.md.embedded.2.txt` exited with exit status 7 for input.md.embedded.2.txt\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_default_embedded_formatter_mappings_run_for_yaml_scalars_and_code_fences_1(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "default embedded formatter mappings run for yaml scalars and code fences" (external formatters); any difference in the stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    write_tree(tmp_path, {
        'bin0/prettier': (
            '#!/bin/sh\n'
            'tr a-z A-Z\n'
        ),
    }, executable=['bin0/prettier'])
    stdin = (
        '# fmt: json\n'
        'body: |\n'
        '  {"name":"yamark"}\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.yaml'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'default_embedded_formatter_mappings_run_for_yaml_scalars_and_code_fences_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_default_embedded_formatter_mappings_run_for_yaml_scalars_and_code_fences_2(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "default embedded formatter mappings run for yaml scalars and code fences" (external formatters); any difference in the stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    write_tree(tmp_path, {
        'bin0/prettier': (
            '#!/bin/sh\n'
            'tr a-z A-Z\n'
        ),
    }, executable=['bin0/prettier'])
    stdin = (
        '```json\n'
        '{"name":"yamark"}\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'default_embedded_formatter_mappings_run_for_yaml_scalars_and_code_fences_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_embedded_formatter_entries_require_formatter_key(run, workdir):
    """CATCHES: reimplementations that break "embedded formatter entries require formatter key" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.custom]\n'
            'command = ["tool", "{path}"]\n'
        ),
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: embedded formatter entries must contain formatter\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_expanded_embedded_formatter_requires_path_suffix(run, workdir):
    """CATCHES: reimplementations that break "expanded embedded formatter requires path suffix" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.custom]\n'
            'formatter = { command = ["tool", "{path}"] }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = '# Title\n'
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'yamark.toml:1:1: error: missing embedded formatter path_suffix\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_explicit_embedded_formatters_run_for_yaml_scalars_and_code_fences_1(run, workdir):
    """CATCHES: reimplementations that break "explicit embedded formatters run for yaml scalars and code fences" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 3."""
    files = {
        'yamark.toml': (
            '[embedded.upper]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
            '\n'
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: upper\n'
        'body: |\n'
        '  abc\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'explicit_embedded_formatters_run_for_yaml_scalars_and_code_fences_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_explicit_embedded_formatters_run_for_yaml_scalars_and_code_fences_2(run, workdir):
    """CATCHES: reimplementations that break "explicit embedded formatters run for yaml scalars and code fences" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 3."""
    files = {
        'yamark.toml': (
            '[embedded.upper]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
            '\n'
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'explicit_embedded_formatters_run_for_yaml_scalars_and_code_fences_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_explicit_embedded_formatters_run_for_yaml_scalars_and_code_fences_3(run, workdir):
    """CATCHES: reimplementations that break "explicit embedded formatters run for yaml scalars and code fences" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 3."""
    files = {
        'yamark.toml': (
            '[embedded.upper]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
            '\n'
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml', '--skip-embedded-formatters'],
        input=stdin,
    )
    assert result.stdout == (RES / 'explicit_embedded_formatters_run_for_yaml_scalars_and_code_fences_3.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--config', 'yamark.toml', '--skip-embedded-formatters', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_embedded_formatter_stderr_on_success_is_an_error(run, workdir):
    """CATCHES: reimplementations that break "embedded formatter stderr on success is an error" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'formatted\'); sys.stderr.buffer.write(b\'warning\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:1: error: embedded formatter wrote to stderr: warning\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_output_without_trailing_newline_stays_line_delimited_1(run, workdir):
    """CATCHES: reimplementations that break "external formatter output without trailing newline stays line delimited" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 2."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'X\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'body: |\n'
        '  y\n'
        'next: 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_formatter_output_without_trailing_newline_stays_line_delimited_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_output_without_trailing_newline_stays_line_delimited_2(run, workdir):
    """CATCHES: reimplementations that break "external formatter output without trailing newline stays line delimited" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 2."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'X\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_formatter_output_without_trailing_newline_stays_line_delimited_2.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_early_stdin_close_preserves_output_and_error_contracts_1(run, workdir):
    """CATCHES: reimplementations that break "external formatter early stdin close preserves output and error contracts" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 1 of 5."""
    files = {
        'yamark.toml': (
            '[embedded.early]\n'
            'formatter = { command = ["python3", "-c", "import os, sys; os.close(sys.stdin.fileno()); sys.stdout.buffer.write(b\'formatted\\\\n\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = "```early\n" + "a" * (4 << 20) + "\n```\n"  # 4 MiB fenced body
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_formatter_early_stdin_close_preserves_output_and_error_contracts_1.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_early_stdin_close_preserves_output_and_error_contracts_2(run, workdir):
    """CATCHES: reimplementations that break "external formatter early stdin close preserves output and error contracts" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 2 of 5."""
    files = {
        'yamark.toml': (
            '[embedded.early]\n'
            'formatter = { command = ["python3", "-c", "import os, sys; os.close(sys.stdin.fileno()); sys.stdout.buffer.write(b\'formatted\\\\n\'); sys.stderr.buffer.write(b\'warning\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = "```early\n" + "a" * (4 << 20) + "\n```\n"  # 4 MiB fenced body
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:1: error: embedded formatter wrote to stderr: warning\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_early_stdin_close_preserves_output_and_error_contracts_3(run, workdir):
    """CATCHES: reimplementations that break "external formatter early stdin close preserves output and error contracts" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 3 of 5."""
    files = {
        'yamark.toml': (
            '[embedded.early]\n'
            'formatter = { command = ["python3", "-c", "import os, sys; os.close(sys.stdin.fileno()); sys.stdout.buffer.write(b\'\\\\xff\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = "```early\n" + "a" * (4 << 20) + "\n```\n"  # 4 MiB fenced body
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:1: error: embedded formatter emitted invalid UTF-8: invalid utf-8 sequence of 1 bytes from index 0\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_early_stdin_close_preserves_output_and_error_contracts_4(run, workdir):
    """CATCHES: reimplementations that break "external formatter early stdin close preserves output and error contracts" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 4 of 5."""
    files = {
        'yamark.toml': (
            '[embedded.early]\n'
            'formatter = { command = ["python3", "-c", "import os, sys; os.close(sys.stdin.fileno()); sys.stdout.buffer.write(b\'ok\\\\r```\\\\r\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = "```early\n" + "a" * (4 << 20) + "\n```\n"  # 4 MiB fenced body
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:2:1: error: formatted code fence would contain closing fence\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_early_stdin_close_preserves_output_and_error_contracts_5(run, workdir):
    """CATCHES: reimplementations that break "external formatter early stdin close preserves output and error contracts" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails. Variant 5 of 5."""
    files = {
        'yamark.toml': (
            '[embedded.early]\n'
            'formatter = { command = ["python3", "-c", "import os, sys; os.close(sys.stdin.fileno()); sys.exit(7)", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = "```early\n" + "a" * (4 << 20) + "\n```\n"  # 4 MiB fenced body
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.md:1:1: error: embedded formatter failed: command `python3 -c import os, sys; os.close(sys.stdin.fileno()); sys.exit(7) input.md.embedded.2.txt` exited with exit status 7 for input.md.embedded.2.txt\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_preamble_split_supports_cr_only_code_fences(run, workdir):
    """CATCHES: reimplementations that break "external formatter preamble split supports cr only code fences" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.argv[1].encode() + b\'\\\\n\' + sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\r'
        '#| label: fig\r'
        'abc\r'
        '```\r'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_formatter_preamble_split_supports_cr_only_code_fences.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_formatter_receives_source_based_virtual_path_and_not_renderer_preamble(run, workdir):
    """CATCHES: reimplementations that break "external formatter receives source based virtual path and not renderer preamble" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.argv[1].encode() + b\'\\\\n\' + sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '```txt\n'
        '#| label: fig\n'
        'abc\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_formatter_receives_source_based_virtual_path_and_not_renderer_preamble.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_yaml_scalar_formatter_output_is_reindented(run, workdir):
    """CATCHES: reimplementations that break "external yaml scalar formatter output is reindented" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'x\\\\n\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'body: |\n'
        '  y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_yaml_scalar_formatter_output_is_reindented.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_yaml_scalar_formatter_output_updates_strip_chomp_for_final_newline(run, workdir):
    """CATCHES: reimplementations that break "external yaml scalar formatter output updates strip chomp for final newline" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'x\\\\n\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'body: |-\n'
        '  y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_yaml_scalar_formatter_output_updates_strip_chomp_for_final_newline.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_yaml_scalar_formatter_output_uses_explicit_block_indent_indicator(run, workdir):
    """CATCHES: reimplementations that break "external yaml scalar formatter output uses explicit block indent indicator" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'x\\\\n\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'body: |4\n'
        'next: 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_yaml_scalar_formatter_output_uses_explicit_block_indent_indicator.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_yaml_scalar_formatter_preserves_renderer_preamble(run, workdir):
    """CATCHES: reimplementations that break "external yaml scalar formatter preserves renderer preamble" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.argv[1].encode() + b\'\\\\n\' + sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'script: |\n'
        '  #| echo: false\n'
        '  #@ trace\n'
        '  abc\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_yaml_scalar_formatter_preserves_renderer_preamble.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_failing_optional_embedded_formatter_preserves_code_fence_silently(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "failing optional embedded formatter preserves code fence silently" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    write_tree(tmp_path, {
        'bin0/ruff': (
            '#!/bin/sh\n'
            'cat >/dev/null\n'
            "printf 'error: Failed to parse input.md.embedded.2.ipynb:7:9: Unexpected indentation\\n' >&2\n"
            "printf '> 7 |     x=1\\n' >&2\n"
            "printf '    |         ^\\n' >&2\n"
            'exit 2\n'
        ),
    }, executable=['bin0/ruff'])
    stdin = (
        '```python\n'
        '    x=1\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'failing_optional_embedded_formatter_preserves_code_fence_silently.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(
        ['format', '--check', 'input.md'],
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_external_yaml_scalar_formatter_preserves_block_header_comments(run, workdir):
    """CATCHES: reimplementations that break "external yaml scalar formatter preserves block header comments" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'x\\\\n\')", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'body: | # markdown\n'
        '  y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_yaml_scalar_formatter_preserves_block_header_comments.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_external_yaml_scalar_formatter_receives_dedented_block_content(run, workdir):
    """CATCHES: reimplementations that break "external yaml scalar formatter receives dedented block content" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(b\'\'.join(b\'seen:\' + line for line in sys.stdin.buffer.read().splitlines(keepends=True)))", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt\n'
        'body: |\n'
        '    value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'external_yaml_scalar_formatter_receives_dedented_block_content.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_failing_optional_embedded_formatter_reports_diagnostic_when_requested(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "failing optional embedded formatter reports diagnostic when requested" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    write_tree(tmp_path, {
        'bin0/ruff': (
            '#!/bin/sh\n'
            'cat >/dev/null\n'
            "printf 'error: Failed to parse input.md.embedded.2.ipynb:7:9: Unexpected indentation\\n' >&2\n"
            "printf '> 7 |     x=1\\n' >&2\n"
            "printf '    |         ^\\n' >&2\n"
            'exit 2\n'
        ),
    }, executable=['bin0/ruff'])
    stdin = (
        '```python\n'
        '    x=1\n'
        '```\n'
    )
    result = run(
        ['format', '--diagnostics', '--stdin-file-path', 'input.md'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'failing_optional_embedded_formatter_reports_diagnostic_when_requested.golden').read_bytes()
    assert result.stderr.decode() == 'input.md:2:1: note: embedded formatter `ruff` failed at formatter input 7:9; left chunk unchanged\n'
    assert result.returncode == 0


def test_skipped_external_code_fence_preserves_entire_target_span(run, workdir):
    """CATCHES: reimplementations that break "skipped external code fence preserves entire target span" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '```{.python .python #cell}\n'
        "print('x')\n"
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'input.md', '--skip-embedded-formatters'], input=stdin)
    assert result.stdout == (RES / 'skipped_external_code_fence_preserves_entire_target_span.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--skip-embedded-formatters', 'input.md'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_skipped_external_yaml_scalar_preserves_entire_target_span(run, workdir):
    """CATCHES: reimplementations that break "skipped external yaml scalar preserves entire target span" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: json\n'
        'body:    |\n'
        '  {"name":"yamark"}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--skip-embedded-formatters'], input=stdin)
    assert result.stdout == (RES / 'skipped_external_yaml_scalar_preserves_entire_target_span.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.yaml').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(['format', '--check', '--skip-embedded-formatters', 'input.yaml'])
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_ordinary_python_code_fence_still_formats_through_ruff(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "ordinary python code fence still formats through ruff" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    write_tree(tmp_path, {
        'bin0/ruff': (
            '#!/usr/bin/env python3\n'
            'import json\n'
            'import sys\n'
            '\n'
            'if sys.argv[1:3] != ["format", "--stdin-filename"] or sys.argv[4:] != ["-"]:\n'
            '    sys.stderr.write(f"unexpected argv: {sys.argv[1:]!r}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'if not sys.argv[3].endswith(".ipynb"):\n'
            '    sys.stderr.write(f"expected ipynb path, got {sys.argv[3]}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'try:\n'
            '    notebook = json.load(sys.stdin)\n'
            'except Exception as err:\n'
            '    sys.stderr.write(f"stdin was not notebook json: {err}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'cells = notebook.get("cells")\n'
            'if not isinstance(cells, list) or len(cells) != 1:\n'
            '    sys.stderr.write("expected exactly one notebook cell\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'cell = cells[0]\n'
            'if cell.get("cell_type") != "code":\n'
            '    sys.stderr.write("expected a code cell\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'source = cell.get("source")\n'
            'if isinstance(source, list):\n'
            '    source = "".join(source)\n'
            'elif not isinstance(source, str):\n'
            '    sys.stderr.write("expected string or array cell source\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'if source.startswith("%%tab pytorch\\n"):\n'
            '    formatted = source\n'
            'else:\n'
            '    formatted = source.replace("x= 1", "x = 1")\n'
            '\n'
            'if "%load_ext d2lbook.tab" in source:\n'
            '    cell["source"] = formatted.splitlines(True)\n'
            'else:\n'
            '    cell["source"] = formatted\n'
            '\n'
            'json.dump(notebook, sys.stdout)\n'
        ),
    }, executable=['bin0/ruff'])
    stdin = (
        '```python\n'
        'x= 1\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'ordinary_python_code_fence_still_formats_through_ruff.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_python_code_fence_with_cell_magic_is_preserved_by_ruff_notebook_cell(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "python code fence with cell magic is preserved by ruff notebook cell" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    write_tree(tmp_path, {
        'bin0/ruff': (
            '#!/usr/bin/env python3\n'
            'import json\n'
            'import sys\n'
            '\n'
            'if sys.argv[1:3] != ["format", "--stdin-filename"] or sys.argv[4:] != ["-"]:\n'
            '    sys.stderr.write(f"unexpected argv: {sys.argv[1:]!r}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'if not sys.argv[3].endswith(".ipynb"):\n'
            '    sys.stderr.write(f"expected ipynb path, got {sys.argv[3]}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'try:\n'
            '    notebook = json.load(sys.stdin)\n'
            'except Exception as err:\n'
            '    sys.stderr.write(f"stdin was not notebook json: {err}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'cells = notebook.get("cells")\n'
            'if not isinstance(cells, list) or len(cells) != 1:\n'
            '    sys.stderr.write("expected exactly one notebook cell\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'cell = cells[0]\n'
            'if cell.get("cell_type") != "code":\n'
            '    sys.stderr.write("expected a code cell\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'source = cell.get("source")\n'
            'if isinstance(source, list):\n'
            '    source = "".join(source)\n'
            'elif not isinstance(source, str):\n'
            '    sys.stderr.write("expected string or array cell source\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'if source.startswith("%%tab pytorch\\n"):\n'
            '    formatted = source\n'
            'else:\n'
            '    formatted = source.replace("x= 1", "x = 1")\n'
            '\n'
            'if "%load_ext d2lbook.tab" in source:\n'
            '    cell["source"] = formatted.splitlines(True)\n'
            'else:\n'
            '    cell["source"] = formatted\n'
            '\n'
            'json.dump(notebook, sys.stdout)\n'
        ),
    }, executable=['bin0/ruff'])
    stdin = (
        '```python\n'
        '%%tab pytorch\n'
        'x= 1\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'python_code_fence_with_cell_magic_is_preserved_by_ruff_notebook_cell.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    # Path mode must agree that the input is already formatted.
    (workdir / 'input.md').write_bytes(stdin.encode() if isinstance(stdin, str) else stdin)
    checked = run(
        ['format', '--check', 'input.md'],
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert checked.stdout == b""
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_python_code_fence_with_line_magic_formats_through_ruff_notebook_cell(run, workdir, tmp_path):
    """CATCHES: reimplementations that break "python code fence with line magic formats through ruff notebook cell" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    write_tree(tmp_path, {
        'bin0/ruff': (
            '#!/usr/bin/env python3\n'
            'import json\n'
            'import sys\n'
            '\n'
            'if sys.argv[1:3] != ["format", "--stdin-filename"] or sys.argv[4:] != ["-"]:\n'
            '    sys.stderr.write(f"unexpected argv: {sys.argv[1:]!r}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'if not sys.argv[3].endswith(".ipynb"):\n'
            '    sys.stderr.write(f"expected ipynb path, got {sys.argv[3]}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'try:\n'
            '    notebook = json.load(sys.stdin)\n'
            'except Exception as err:\n'
            '    sys.stderr.write(f"stdin was not notebook json: {err}\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'cells = notebook.get("cells")\n'
            'if not isinstance(cells, list) or len(cells) != 1:\n'
            '    sys.stderr.write("expected exactly one notebook cell\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'cell = cells[0]\n'
            'if cell.get("cell_type") != "code":\n'
            '    sys.stderr.write("expected a code cell\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'source = cell.get("source")\n'
            'if isinstance(source, list):\n'
            '    source = "".join(source)\n'
            'elif not isinstance(source, str):\n'
            '    sys.stderr.write("expected string or array cell source\\n")\n'
            '    sys.exit(2)\n'
            '\n'
            'if source.startswith("%%tab pytorch\\n"):\n'
            '    formatted = source\n'
            'else:\n'
            '    formatted = source.replace("x= 1", "x = 1")\n'
            '\n'
            'if "%load_ext d2lbook.tab" in source:\n'
            '    cell["source"] = formatted.splitlines(True)\n'
            'else:\n'
            '    cell["source"] = formatted\n'
            '\n'
            'json.dump(notebook, sys.stdout)\n'
        ),
    }, executable=['bin0/ruff'])
    stdin = (
        '```python\n'
        '%load_ext d2lbook.tab\n'
        'x= 1\n'
        '```\n'
    )
    result = run(
        ['format', '--stdin-file-path', 'input.md'],
        input=stdin,
        env_overrides={"PATH": os.pathsep.join([str(tmp_path / 'bin0'), os.environ["PATH"]])},
    )
    assert result.stdout == (RES / 'python_code_fence_with_line_magic_formats_through_ruff_notebook_cell.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0


def test_source_files_run_external_formatter_directives_for_string_targets(run, workdir):
    """CATCHES: reimplementations that break "source files run external formatter directives for string targets" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.r]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b\'function(x)x+1\', b\'function(x) x + 1\'))", "{path}"], path_suffix = ".R" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '"""Module docstring."""\n'
        '\n'
        'def read_source() -> str:\n'
        '    return run(\n'
        '        # fmt: r\n'
        '        stdin="""\n'
        '            f <- function(x)x+1\n'
        '        """,\n'
        '    )\n'
    )
    result = run(['format', '--stdin-file-path', 'input.py', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'source_files_run_external_formatter_directives_for_string_targets.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_yaml_embedded_formatter_directive_accepts_explicit_scope_next(run, workdir):
    """CATCHES: reimplementations that break "yaml embedded formatter directive accepts explicit scope next" (external formatters); any difference in the resulting files, stdout, stderr or exit status from the reference fails."""
    files = {
        'yamark.toml': (
            '[embedded.txt]\n'
            'formatter = { command = ["python3", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().upper())", "{path}"], path_suffix = ".txt" }\n'
        ),
    }
    write_tree(workdir, files)
    stdin = (
        '# fmt: txt scope=next\n'
        'body: |\n'
        '  abc\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--config', 'yamark.toml'], input=stdin)
    assert result.stdout == (RES / 'yaml_embedded_formatter_directive_accepts_explicit_scope_next.golden').read_bytes()
    assert result.stderr.decode() == ""
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes(files)


def test_yaml_embedded_formatter_directive_rejects_explicit_block_scalar_keys(run, workdir):
    """CATCHES: reimplementations that break "yaml embedded formatter directive rejects explicit block scalar keys" (external formatters); any difference in the stdout, stderr or exit status from the reference fails."""
    stdin = (
        '# fmt: json\n'
        '? |\n'
        '  key\n'
        ': value\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b""
    assert result.stderr.decode() == 'input.yaml:2:1: error: fmt: json targets a literal block scalar\n'
    assert result.returncode == 1
