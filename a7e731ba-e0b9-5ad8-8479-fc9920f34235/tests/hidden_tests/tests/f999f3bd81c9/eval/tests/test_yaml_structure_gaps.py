"""YAML stream structure, explicit keys, tab indentation, and YAML directive lifecycle.

Black-box tests for `yamark format` on `.yaml` input (stdin with `--stdin-file-path` and path
mode): multi-document streams and markers, `%YAML`/`%TAG` streams, explicit `?` keys and their
values, complex keys, properties on collections, comments, indentation width, line endings,
BOM, tab-indented regions next to active `fmt:` comments, whole-stream preservation of
unsupported syntax, and exact directive / embedded-target error messages. Expected outputs were
recorded from the reference binary.
"""

import pytest

from conftest import as_bytes, read_tree, resources_for, write_tree

RES = resources_for(__file__)


def test_consecutive_start_markers_keep_empty_documents(run, workdir):
    """CATCHES: an implementation that drops or merges the empty documents created by back-to-back `---` markers (and by a trailing `---`) instead of keeping every marker while formatting `a:   1`."""
    stdin = (
        '---\n'
        '---\n'
        'a:   1\n'
        '---\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'---\n'
        b'---\n'
        b'a: 1\n'
        b'---\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_start_marker_closed_by_end_marker_is_an_empty_document(run, workdir):
    """CATCHES: an implementation that treats `---` immediately followed by `...` as malformed or deletes the empty document, instead of keeping both markers and formatting the following document."""
    stdin = (
        '---\n'
        '...\n'
        '---\n'
        'b:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'---\n'
        b'...\n'
        b'---\n'
        b'b: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_leading_end_marker_before_any_content(run, workdir):
    """CATCHES: an implementation that rejects or strips a `...` document-end marker that appears before any document content, instead of keeping it and formatting the mapping after it."""
    stdin = (
        '...\n'
        'a:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'...\n'
        b'a: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_comments_before_between_and_after_documents(run, workdir):
    """CATCHES: an implementation that loses or relocates comments placed before the first `---`, inside a document, after a `...` end marker, or before the next document start."""
    stdin = (
        '# before doc\n'
        '---\n'
        '# in doc\n'
        'a:   1\n'
        '...\n'
        '# after end\n'
        '---\n'
        'b:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# before doc\n'
        b'---\n'
        b'# in doc\n'
        b'a: 1\n'
        b'...\n'
        b'# after end\n'
        b'---\n'
        b'b: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_file_scope_compact_in_later_document_applies_to_whole_stream(run, workdir):
    """CATCHES: an implementation that limits a `fmt: compact scope=file` directive in the second YAML document to that document; at top level the file scope is the physical file, so the first document's sequence is collapsed too."""
    stdin = (
        'a:\n'
        '  - 1\n'
        '---\n'
        '# fmt: compact scope=file\n'
        'b:\n'
        '  - 2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: [1]\n'
        b'---\n'
        b'# fmt: compact scope=file\n'
        b'b: [2]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_skip_before_document_marker_targets_next_document_root(run, workdir):
    """CATCHES: an implementation that reports `fmt: skip has no target` (or formats `b:   2`) when the skip comment is the last line of one document; the reference applies it to the next document's root."""
    stdin = (
        'a: 1\n'
        '# fmt: skip\n'
        '---\n'
        'b:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: 1\n'
        b'# fmt: skip\n'
        b'---\n'
        b'b:   2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    write_tree(workdir, {'input.yaml': stdin})
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


def test_unclosed_flow_after_document_marker_is_kept_while_rest_formats(run, workdir):
    """CATCHES: an implementation that fails, or rewrites the unclosed `--- [a, b` line, instead of keeping the unterminated flow text after the document marker verbatim while still formatting `c:   1`."""
    stdin = (
        '--- [a, b\n'
        'c:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'--- [a, b\n'
        b'c: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_fmt_off_region_spanning_documents_without_on_is_rejected_at_stream_end(run, workdir):
    """CATCHES: an implementation that closes an open `fmt: off` region at a `---` document boundary instead of reporting `unterminated fmt: off` at the end of the whole stream."""
    stdin = (
        '# fmt: off\n'
        'a:   1\n'
        '---\n'
        'b:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'input.yaml:4:7: error: unterminated fmt: off\n'
    assert result.returncode == 1


def test_yaml_version_directive_with_tab_and_fmt_comment_formats_untabbed_mapping(run, workdir):
    """CATCHES: an implementation that mishandles a `%YAML` directive line once tab indentation plus an active fmt comment force a full parse: the directive and `---` must be kept, `a:   1` formatted, and the tab-indented value preserved."""
    stdin = (
        '%YAML 1.2\n'
        '---\n'
        '# fmt: compact false\n'
        'a:   1\n'
        'b:\n'
        '\tc: 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'%YAML 1.2\n'
        b'---\n'
        b'# fmt: compact false\n'
        b'a: 1\n'
        b'b:\n'
        b'\tc: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_key_without_value_at_end_of_stream(run, workdir):
    """CATCHES: an implementation that appends a `:` value indicator (or drops the key) for a trailing `? a` explicit key with no value line."""
    stdin = (
        'x:   1\n'
        '? a\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'x: 1\n'
        b'? a\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_value_header_with_nested_mapping(run, workdir):
    """CATCHES: an implementation that fails to parse a block mapping nested under a bare `:` explicit-value line, leaving `a:   1` unformatted or re-indenting it to the wrong column."""
    stdin = (
        '? k\n'
        ':\n'
        '  a:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? k\n'
        b':\n'
        b'  a: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_empty_value_followed_by_sibling_key(run, workdir):
    """CATCHES: an implementation that absorbs the following `z:   1` pair into an empty explicit value, or emits `: null`, instead of keeping `:` empty and formatting the sibling."""
    stdin = (
        '? k\n'
        ':\n'
        'z:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? k\n'
        b':\n'
        b'z: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_value_with_only_an_anchor(run, workdir):
    """CATCHES: an implementation that drops a property-only explicit value `: &a` or attaches the anchor to the next key."""
    stdin = (
        '? k\n'
        ': &a\n'
        'z:  1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? k\n'
        b': &a\n'
        b'z: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_value_compact_sequence_is_expanded(run, workdir):
    """CATCHES: an implementation that keeps the compact `: - a` form instead of moving the sequence below a bare `:` line with normal indentation."""
    stdin = (
        '? k\n'
        ': - a\n'
        '  - b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? k\n'
        b':\n'
        b'  - a\n'
        b'  - b\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_value_inline_mapping_is_expanded(run, workdir):
    """CATCHES: an implementation that keeps `: x:   1` inline on the explicit-value line instead of emitting the mapping as an indented block below `:`."""
    stdin = (
        '? k\n'
        ': x:   1\n'
        '  y: 2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? k\n'
        b':\n'
        b'  x: 1\n'
        b'  y: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_value_multiline_double_quoted_scalar_is_kept(run, workdir):
    """CATCHES: an implementation that joins or re-folds a multi-line double-quoted explicit value instead of keeping it while formatting the following pair."""
    stdin = (
        '? k\n'
        ': "a\n'
        '  b"\n'
        'z:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? k\n'
        b': "a\n'
        b'  b"\n'
        b'z: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_block_scalar_key_is_kept(run, workdir):
    """CATCHES: an implementation that cannot parse a literal block scalar used as an explicit key (`? |`) and fails or rewrites it, instead of keeping it and formatting later pairs."""
    stdin = (
        '? |\n'
        '  lit\n'
        ': v\n'
        'z:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? |\n'
        b'  lit\n'
        b': v\n'
        b'z: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_empty_explicit_key(run, workdir):
    """CATCHES: an implementation that rejects a bare `?` (empty explicit key) or turns it into `? null`."""
    stdin = (
        '?\n'
        ': v\n'
        'z:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'?\n'
        b': v\n'
        b'z: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_alias_key(run, workdir):
    """CATCHES: an implementation that treats `? *x` as a plain scalar key to be quoted, or drops the alias."""
    stdin = (
        'a: &x 1\n'
        '? *x\n'
        ':   v\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: &x 1\n'
        b'? *x\n'
        b': v\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_sequence_item_explicit_mapping_with_continuation_pairs(run, workdir):
    """CATCHES: an implementation that stops a `- ? [a,  b]` sequence-item mapping after its first pair, losing or mis-indenting the following explicit and implicit pairs of the same item."""
    stdin = (
        '- ? [a,  b]\n'
        '  : v\n'
        '  ? [c]\n'
        '  :   w\n'
        '  e:   f\n'
        '- x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'- ? [a,  b]\n'
        b'  : v\n'
        b'  ? [c]\n'
        b'  : w\n'
        b'  e: f\n'
        b'- x\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_nested_explicit_mapping_then_dedented_key(run, workdir):
    """CATCHES: an implementation that keeps the dedented `next:` key inside the nested explicit mapping."""
    stdin = (
        'top:\n'
        '  ? a\n'
        '  :   b\n'
        'next:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'top:\n'
        b'  ? a\n'
        b'  : b\n'
        b'next: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_directive_collapses_explicit_key_mapping(run, workdir):
    """CATCHES: an implementation that refuses to compact a mapping written with explicit `?`/`:` pairs under a `fmt: compact` parent, instead of emitting `top: {a: b, c: d}`."""
    stdin = (
        '# fmt: compact\n'
        'top:\n'
        '  ? a\n'
        '  : b\n'
        '  ? c\n'
        '  : d\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: compact\n'
        b'top: {a: b, c: d}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_skip_directive_preserves_only_the_next_explicit_pair(run, workdir):
    """CATCHES: an implementation that extends `fmt: skip` past the explicit pair it targets, leaving the following `c:   [ d ]` unformatted, or that formats the skipped `[ b ]` value."""
    stdin = (
        '# fmt: skip\n'
        '? a\n'
        ':   [ b ]\n'
        'c:   [ d ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: skip\n'
        b'? a\n'
        b':   [ b ]\n'
        b'c: [d]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_key_followed_by_implicit_key_with_tab_and_fmt_comment(run, workdir):
    """CATCHES: an implementation that, once tabs plus an active fmt comment force a full parse, merges a value-less `? a` with the following `b:  c` pair instead of formatting `b: c` separately."""
    stdin = (
        '# fmt: compact false\n'
        '? a\n'
        'b:  c\n'
        'd:\n'
        '\te: 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: compact false\n'
        b'? a\n'
        b'b: c\n'
        b'd:\n'
        b'\te: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_complex_explicit_keys_are_kept_verbatim_with_tab_and_fmt_comment(run, workdir):
    """CATCHES: an implementation that rewrites compact-sequence, inline-mapping, or nested-block explicit keys (`? - a`, `? c:   1`, `?` + indented mapping); the reference keeps those keys verbatim and only formats `z:   1`."""
    stdin = (
        '# fmt: compact false\n'
        '? - a\n'
        '  - b\n'
        ': v\n'
        '? c:   1\n'
        '  d: 2\n'
        ': w\n'
        '?\n'
        '  e:   1\n'
        ': x\n'
        'z:   1\n'
        'y:\n'
        '\tt: 1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'complex_explicit_keys_are_kept_verbatim_with_tab_and_fmt_comment.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(('stdin', 'stdout', 'stderr', 'returncode'), [
    pytest.param(
        '- &x\n  [\n  - 1\n  - 2\n-   z\n',
        b'- &x\n  [\n  - 1\n  - 2\n- z\n',
        '',
        0,
        id='sequence-item-anchor-bracket',
    ),
    pytest.param(
        '? k\n: &x\n  [\n  - 1\n  - 2\nd:   1\n',
        b'? k\n: &x\n  [\n  - 1\n  - 2\nd: 1\n',
        '',
        0,
        id='explicit-value-anchor-bracket',
    ),
])
def test_property_only_parent_with_standalone_opener_is_preserved(run, stdin, stdout, stderr, returncode):
    """CATCHES: an implementation that collapses (or drops) a standalone `[`/`{` opener below a property-only parent such as `a: &x`; the reference keeps that collection as typed while formatting siblings."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdout
    assert result.stderr.decode() == stderr
    assert result.returncode == returncode


@pytest.mark.parametrize(('stdin', 'stdout', 'stderr', 'returncode'), [
    pytest.param(
        '? k\n: [\n  - a\n  - b\n',
        b'? k\n: [a, b]\n',
        '',
        0,
        id='bracket-sequence',
    ),
    pytest.param(
        '? k\n: {\n  a: 1\n  b: 2\n',
        b'? k\n: {a: 1, b: 2}\n',
        '',
        0,
        id='brace-mapping',
    ),
])
def test_explicit_value_unmatched_opener_collapses_to_flow(run, stdin, stdout, stderr, returncode):
    """CATCHES: an implementation that ignores an unmatched `[` or `{` layout hint on an explicit-value line instead of collapsing the block collection below it to flow style."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdout
    assert result.stderr.decode() == stderr
    assert result.returncode == returncode


def test_empty_implicit_key_line(run, workdir):
    """CATCHES: an implementation that rejects or rewrites a `: v` line (an empty key followed by a value indicator) instead of keeping it and formatting the next pair."""
    stdin = (
        ': v\n'
        'z:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b': v\n'
        b'z: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_triple_dash_prefix_without_space_is_a_plain_key(run, workdir):
    """CATCHES: an implementation that treats `---a:` as a document start marker instead of an ordinary mapping key that gets normal value spacing."""
    stdin = '---a:   1\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'---a: 1\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_plain_scalar_document_after_start_marker(run, workdir):
    """CATCHES: an implementation that drops, quotes, or moves the `text` root scalar written on the `---` line, or stops formatting the following documents."""
    stdin = (
        '--- text\n'
        '---\n'
        'a:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'--- text\n'
        b'---\n'
        b'a: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_hash_inside_quoted_scalars_with_escapes_is_not_a_comment(run, workdir):
    """CATCHES: an implementation that starts a comment at a `#` inside a double-quoted scalar containing an escaped quote, or inside a single-quoted scalar containing a doubled quote, instead of only treating the later ` # note` text as the trailing comment."""
    stdin = (
        'a: "q\\"#x"   # note\n'
        "b: 'it''s #'   # n2\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: q"#x # note\n'
        b'b: "it\'s #" # n2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_flow_collection_mapping_keys_keep_source_spacing(run, workdir):
    """CATCHES: an implementation that normalises spacing inside `[a,  b]` / `{x:  1}` used as implicit mapping keys; only the value side is normalised."""
    stdin = (
        '[a,  b]: c\n'
        '{x:  1}:   y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'[a,  b]: c\n'
        b'{x:  1}: y\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_single_quoted_keys_with_escaped_quotes(run, workdir):
    """CATCHES: an implementation that mis-detects the mapping colon inside `'a: ''b'''` or unquotes `'it''s'` keys instead of only normalising the spacing after the colon."""
    stdin = (
        "'it''s':   v\n"
        "'a: ''b''':   c\n"
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b"'it''s': v\n"
        b"'a: ''b''': c\n"
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_nested_sequence_with_directive_between_items(run, workdir):
    """CATCHES: an implementation that lets a `fmt: skip` between compact `- - a` items apply to the wrong item, or keeps the compact `- -` layout instead of expanding the nested sequences."""
    stdin = (
        '- - a\n'
        '  # fmt: skip\n'
        '  - [ b ]\n'
        '- - [ c ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'-\n'
        b'  - a\n'
        b'  # fmt: skip\n'
        b'  - [ b ]\n'
        b'-\n'
        b'  - [c]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_sequence_item_mapping_before_document_marker(run, workdir):
    """CATCHES: an implementation that continues a `- a:` sequence-item mapping across a `---` marker."""
    stdin = (
        '- a:   1\n'
        '---\n'
        '- b\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'- a: 1\n'
        b'---\n'
        b'- b\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_keep_chomping_block_scalar_headers(run, workdir):
    """CATCHES: an implementation that rewrites `|+` or `>+1` block headers or trims the kept trailing blank lines while formatting the following pair."""
    stdin = (
        'a: |+\n'
        '  x\n'
        '\n'
        'b: >+1\n'
        '  y\n'
        '\n'
        'c:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: |+\n'
        b'  x\n'
        b'\n'
        b'b: >+1\n'
        b'  y\n'
        b'\n'
        b'c: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_duplicate_keys_are_kept_and_their_values_formatted(run, workdir):
    """CATCHES: an implementation that rejects, deduplicates, or reorders duplicate keys instead of formatting each value in place."""
    stdin = (
        'a: 1\n'
        'a:   2\n'
        'b:\n'
        '  c: 1\n'
        '  c:   [ 2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: 1\n'
        b'a: 2\n'
        b'b:\n'
        b'  c: 1\n'
        b'  c: [2]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_anchors_tags_and_aliases_on_collections(run, workdir):
    """CATCHES: an implementation that loses anchors or custom tags on block collections, keeps redundant `!!map`/`!!seq` tags, or reorders `&a !bar`."""
    stdin = (
        'base: &base\n'
        '  a:   1\n'
        'der:\n'
        '  <<: *base\n'
        '  b: 2\n'
        'list: &l\n'
        '  -   1\n'
        'tagged: !!map\n'
        '  x:   1\n'
        'seq_tagged: !!seq\n'
        '  - 1\n'
        'custom: !foo\n'
        '  -   a\n'
        'both: &a !bar\n'
        '  k:   v\n'
        'flow: &f [ 1,2 ]\n'
        'ref: *f\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'anchors_tags_and_aliases_on_collections.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_empty_values_and_null_spellings(run, workdir):
    """CATCHES: an implementation that rewrites `~` to `null`, fills empty values with `null`, keeps `Null` / `NULL` spellings, or keeps trailing spaces after an empty value."""
    stdin = (
        'a:\n'
        'b: ~\n'
        'c: null\n'
        'd: Null\n'
        'e: NULL\n'
        'f:   \n'
        'g:\n'
        '  -\n'
        '  - ~\n'
        '  -   null\n'
        'h: {}\n'
        'i: []\n'
        "j: ''\n"
        'k:\n'
        '  l:\n'
        'm:   []\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'empty_values_and_null_spellings.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_comments_in_every_position(run, workdir):
    """CATCHES: an implementation that drops, re-indents, or re-attaches head, trailing, between-entry, inside-collection, and tail comments, or keeps multiple spaces before a trailing comment."""
    stdin = (
        '# head comment\n'
        '\n'
        '# attached to a\n'
        'a:   1   # trailing a\n'
        '# between a and b\n'
        'b:\n'
        '  # inside b before items\n'
        '  - x  # trailing x\n'
        '  # between items\n'
        '  - y\n'
        '  # after last item\n'
        '# before c\n'
        'c:\n'
        '  d:   2 # trailing d\n'
        '  # end of c\n'
        '\n'
        '# tail comment\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'comments_in_every_position.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_indent_width_one_reindents_nested_collections(run, workdir):
    """CATCHES: an implementation that ignores `--indent-width 1` for nested mappings, sequences inside mappings (including indentless ones), or continuation keys of a sequence-item mapping."""
    stdin = (
        'a:\n'
        '  b:\n'
        '    - c\n'
        '    - d:   1\n'
        '      e: [1,  2]\n'
        'f:\n'
        '- g\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '1'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b' b:\n'
        b'  - c\n'
        b'  - d: 1\n'
        b'    e: [1, 2]\n'
        b'f:\n'
        b' - g\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_indent_width_three_reindents_nested_collections(run, workdir):
    """CATCHES: an implementation that only supports even indentation widths, or mis-aligns sequence-item mapping continuation keys with `--indent-width 3`."""
    stdin = (
        'a:\n'
        '  b:\n'
        '    - c\n'
        '    - d:   1\n'
        '      e: [1,  2]\n'
        'f:\n'
        '- g\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '3'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b'   b:\n'
        b'      - c\n'
        b'      - d: 1\n'
        b'        e: [1, 2]\n'
        b'f:\n'
        b'   - g\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_cr_only_line_endings_are_preserved(run, workdir):
    """CATCHES: an implementation that converts classic-Mac CR-only line endings to LF or CRLF (or fails to split lines on a bare CR) while formatting."""
    stdin = (
        'a:   1\r'
        'b:\r'
        '  - [ x,y ]\r'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: 1\r'
        b'b:\r'
        b'  - [x, y]\r'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize(('stdin', 'stdout', 'stderr', 'returncode'), [
    pytest.param(
        'a: [1,\r\n  2]\r\nb:   2\n',
        b'a:\r\n  - 1\r\n  - 2\r\nb: 2\n',
        '',
        0,
        id='crlf-collection-in-mostly-crlf',
    ),
    pytest.param(
        'a: [1,\n  2]\r\nb:   2\r\nc: 3\r\n',
        b'a:\n  - 1\n  - 2\nb: 2\r\nc: 3\r\n',
        '',
        0,
        id='lf-collection-in-mostly-crlf',
    ),
])
def test_expanded_flow_lines_use_the_collection_line_ending(run, stdin, stdout, stderr, returncode):
    """CATCHES: an implementation that emits the new lines of an expanded flow collection with a fixed LF, or always with the file's dominant ending, instead of the line ending the collection itself used."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdout
    assert result.stderr.decode() == stderr
    assert result.returncode == returncode


@pytest.mark.parametrize(('stdin', 'stdout', 'stderr', 'returncode'), [
    pytest.param(
        '# fmt: compact false\n\'q\': \'it\'\'s\'\n"d": "a\\"b"\nz:\n\tw: 1\n',
        b'# fmt: compact false\n\'q\': it\'s\n"d": a"b\nz:\n\tw: 1\n',
        '',
        0,
        id='quoted-scalars',
    ),
    pytest.param(
        '# fmt: compact false\nt: !!str 5\nv: !<tag:yaml.org,2002:str> w\nan: &a1 1\nal: *a1\nm: {a:  1, b: [2,  3]}\nz:\n\tw: 1\n',
        b"# fmt: compact false\nt: !!str '5'\nv: !<tag:yaml.org,2002:str> w\nan: &a1 1\nal: *a1\nm: {a: 1, b: [2, 3]}\nz:\n\tw: 1\n",
        '',
        0,
        id='tags-anchors-aliases',
    ),
    pytest.param(
        '# fmt: compact false\na:   1\n--- # second\nlit: |\n  body\nz:\n\tw: 1\n...\n',
        b'# fmt: compact false\na: 1\n--- # second\nlit: |\n  body\nz:\n\tw: 1\n...\n',
        '',
        0,
        id='multiple-documents',
    ),
    pytest.param(
        '# fmt: compact false\n- &x\n\tb: 1\n- c:   2\n',
        b'# fmt: compact false\n- &x\n\tb: 1\n- c: 2\n',
        '',
        0,
        id='anchored-sequence-item',
    ),
    pytest.param(
        '# fmt: compact false\n? k\n: &x\n\tb: 1\nc:   2\n',
        b'# fmt: compact false\n? k\n: &x\n\tb: 1\nc: 2\n',
        '',
        0,
        id='anchored-explicit-value',
    ),
    pytest.param(
        '\ufeff# fmt: compact false\na:\n\tb: 1\nc:   2\n',
        b'\xef\xbb\xbf# fmt: compact false\na:\n\tb: 1\nc: 2\n',
        '',
        0,
        id='bom',
    ),
    pytest.param(
        '# fmt: compact false\n- |\n  x\n-   y\n- z:\n\tw: 1\n',
        b'# fmt: compact false\n- |\n  x\n- y\n- z:\n\tw: 1\n',
        '',
        0,
        id='sequence-item-block-scalar',
    ),
    pytest.param(
        '# fmt: compact false\na: \'x\n  y\'\nb: "x\n  y"\nc:   1\nz:\n\tw: 1\n',
        b'# fmt: compact false\na: \'x\n  y\'\nb: "x\n  y"\nc: 1\nz:\n\tw: 1\n',
        '',
        0,
        id='multiline-quoted-scalars',
    ),
])
def test_tab_indented_regions_are_kept_while_active_fmt_comment_formats_the_rest(run, stdin, stdout, stderr, returncode):
    """CATCHES: an implementation that, when a file has tab indentation and an active `fmt:` comment, either preserves the whole file or tries to re-indent the tab-indented lines; the reference keeps only the tab-indented region verbatim and formats every other node."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdout
    assert result.stderr.decode() == stderr
    assert result.returncode == returncode


def test_tab_after_block_scalar_indentation_is_content(run, workdir):
    """CATCHES: an implementation that treats a tab that follows a block scalar's space indentation as unsupported tab indentation and preserves the whole file, instead of keeping it as content and formatting `b:   1`."""
    stdin = (
        'a: |\n'
        '  x\n'
        '  \ty\n'
        'b:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: |\n'
        b'  x\n'
        b'  \ty\n'
        b'b: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


@pytest.mark.parametrize('stdin', [
    pytest.param('a: |2\n \tx\nb:   1\n', id='tab-before-explicit-block-indent'),
    pytest.param('- |\n  # fmt: skip\n- b:\n\tc: 1\n-   d\n', id='fmt-text-inside-sequence-block-scalar'),
])
def test_tab_indentation_without_active_directive_preserves_whole_file(run, workdir, stdin):
    """CATCHES: an implementation that formats the untabbed parts of a tab-indented file with no active fmt comment, that counts a `# fmt:` line inside a block scalar body as a directive, or that accepts a tab before an explicit block indentation boundary."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    write_tree(workdir, {'input.yaml': stdin})
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


@pytest.mark.parametrize('stdin', [
    pytest.param("a: ['x''s\n  y']\nb:   1\n", id='multiline-single-quote-in-flow'),
    pytest.param('&a b:   1\nc:   2\n', id='anchored-key'),
    pytest.param("a: 'abc\nb:   1\n", id='unclosed-single-quote'),
    pytest.param('%YAML 1.2\n---\na:   1\n', id='yaml-version-directive'),
    pytest.param('%TAG !e! tag:example.com,2000:\n---\na:   !e!x 1\n', id='tag-directive'),
    pytest.param('? a\nb:   c\n', id='explicit-key-then-implicit-key'),
    pytest.param('? a\n# c\n:   b\n', id='comment-between-explicit-key-and-value'),
])
def test_unsupported_syntax_preserves_whole_stream(run, workdir, stdin):
    """CATCHES: an implementation that formats the supported lines (for example `b:   1`) of a stream that also contains syntax Yamark cannot safely rewrite (a multi-line quote inside a flow collection, an anchored key, an unclosed quote, `%YAML`/`%TAG` directives, a value-less explicit key followed by an implicit key, or a comment between `? a` and its `:` value), instead of leaving the whole stream byte-for-byte unchanged."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdin.encode()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    write_tree(workdir, {'input.yaml': stdin})
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0


@pytest.mark.parametrize(('stdin', 'stdout', 'stderr', 'returncode'), [
    pytest.param(
        '# fmt: off\na:   1\n',
        b'',
        'input.yaml:2:7: error: unterminated fmt: off\n',
        1,
        id='unterminated-off',
    ),
    pytest.param(
        '# fmt: off\na:   1',
        b'',
        'input.yaml:2:6: error: unterminated fmt: off\n',
        1,
        id='unterminated-off-no-final-newline',
    ),
    pytest.param(
        'a: 1\n# fmt: on\n',
        b'',
        'input.yaml:2:1: error: fmt: on without active fmt: off\n',
        1,
        id='stray-on',
    ),
    pytest.param(
        'a: 1\n# fmt: skip\n',
        b'',
        'input.yaml:2:12: error: fmt: skip has no target\n',
        1,
        id='targetless-skip',
    ),
    pytest.param(
        '# fmt: table scope=file\n- {a: 1}\n',
        b'',
        'input.yaml:1:1: error: fmt: table does not support scope=file\n',
        1,
        id='table-scope-file',
    ),
    pytest.param(
        '# fmt: markdown scope=file\na: x\n',
        b'',
        'input.yaml:1:1: error: fmt: markdown with scope=file requires at least one option\n',
        1,
        id='markdown-scope-file-without-options',
    ),
    pytest.param(
        '# fmt: python scope=file\na: |\n  x=1\n',
        b'',
        'input.yaml:1:1: error: fmt: python does not support scope=file\n',
        1,
        id='embedded-scope-file',
    ),
    pytest.param(
        '# fmt: compact scope=everywhere\na:\n  - 1\n',
        b'',
        'input.yaml:1:1: error: invalid fmt directive scope: everywhere\n',
        1,
        id='invalid-scope-value',
    ),
    pytest.param(
        'a:   1\n# fmt: template.delimiters "<<" ">>"\n',
        b'',
        'input.yaml:2:1: error: fmt: template.delimiters needs explicit scope\n',
        1,
        id='template-delimiters-need-scope',
    ),
])
def test_yaml_directive_errors(run, stdin, stdout, stderr, returncode):
    """CATCHES: an implementation that accepts, or reports with a different message or `line:col`, YAML `fmt:` lifecycle and scope errors: unterminated `off` (reported at the last byte of the stream, with or without a final newline), stray `on`, targetless `skip`, `scope=file` on `table`, on an option-less `markdown`, or on an embedded formatter, an unknown scope value, and a bare template delimiter directive with no target and no isolating blank line."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdout
    assert result.stderr.decode() == stderr
    assert result.returncode == returncode


@pytest.mark.parametrize(('stdin', 'stdout', 'stderr', 'returncode'), [
    pytest.param(
        '# fmt: python\na: >\n  x = 1\n',
        b'',
        'input.yaml:2:4: error: fmt: python targets a literal block scalar\n',
        1,
        id='folded-block',
    ),
    pytest.param(
        '# fmt: python\na: [1,  2]\n',
        b'',
        'input.yaml:2:4: error: fmt: python targets a literal block scalar\n',
        1,
        id='flow-sequence',
    ),
    pytest.param(
        '# fmt: python\n? k\n: x = 1\n',
        b'',
        'input.yaml:3:3: error: fmt: python targets a literal block scalar\n',
        1,
        id='explicit-value-inline',
    ),
    pytest.param(
        '# fmt: python\na: &x\nb: 1\n',
        b'',
        'input.yaml:2:4: error: fmt: python targets a literal block scalar\n',
        1,
        id='property-only-value',
    ),
    pytest.param(
        '# fmt: python\n- &x\n- b\n',
        b'',
        'input.yaml:2:3: error: fmt: python targets a literal block scalar\n',
        1,
        id='property-only-sequence-item',
    ),
    pytest.param(
        '# fmt: python\n? k\n: &x\nb: 1\n',
        b'',
        'input.yaml:3:3: error: fmt: python targets a literal block scalar\n',
        1,
        id='property-only-explicit-value',
    ),
    pytest.param(
        '# fmt: python\n--- x = 1\n',
        b'',
        'input.yaml:2:5: error: fmt: python targets a literal block scalar\n',
        1,
        id='document-marker-inline',
    ),
    pytest.param(
        '# fmt: python\na: [\n  - 1\n',
        b'',
        'input.yaml:3:5: error: fmt: python targets a literal block scalar\n',
        1,
        id='opener-hint-on-value-line',
    ),
    pytest.param(
        '# fmt: python\na:\n  [\n  - 1\n',
        b'',
        'input.yaml:4:5: error: fmt: python targets a literal block scalar\n',
        1,
        id='opener-hint-on-next-line',
    ),
    pytest.param(
        '# fmt: python\na: [b, # c\n  d]\nx:\n\ty: 1\n',
        b'',
        'input.yaml:2:4: error: fmt: python targets a literal block scalar\n',
        1,
        id='unsupported-flow-with-tabs',
    ),
])
def test_embedded_formatter_directive_requires_literal_block_scalar(run, stdin, stdout, stderr, returncode):
    """CATCHES: an implementation that silently ignores, or reports at a different `line:col`, an embedded formatter directive (`fmt: python`) whose next target is not a literal block scalar: a folded block, a flow sequence, an inline explicit value, a property-only value, an inline scalar after `---`, property-only sequence items and explicit values, layout-hint collections on the value line or the next line, and unsupported multi-line flow syntax."""
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == stdout
    assert result.stderr.decode() == stderr
    assert result.returncode == returncode


def test_unterminated_off_in_path_mode_leaves_file_unchanged(run, workdir):
    """CATCHES: an implementation that writes a partially formatted file, or exits 0, when a YAML file has `fmt: off` without a later `fmt: on`; the error must name the file and position and the file must stay byte-identical."""
    write_tree(workdir, {'input.yaml': '# fmt: off\na:   1\n'})
    result = run(['format', 'input.yaml'])
    assert result.stdout.decode() == '1 files scanned, 0 formatted, 0 unchanged, 0 skipped, 1 failed\n'
    assert result.stderr.decode() == 'input.yaml:2:7: error: unterminated fmt: off\n'
    assert result.returncode == 1
    assert read_tree(workdir) == as_bytes({'input.yaml': '# fmt: off\na:   1\n'})


@pytest.mark.parametrize('content', [
    pytest.param('', id='empty'),
    pytest.param('   \n\n  \n', id='whitespace-only'),
    pytest.param('#  c\n   # d\n', id='comment-only'),
    pytest.param('\ufeff', id='bom-only'),
])
def test_trivial_yaml_files_are_unchanged(run, workdir, content):
    """CATCHES: an implementation that writes `null`, `{}`, a `---` marker, a newline, or strips the BOM / comments / whitespace for an empty, whitespace-only, comment-only, or BOM-only YAML file."""
    write_tree(workdir, {'input.yaml': content})
    checked = run(['format', '--check', 'input.yaml'])
    assert checked.stdout == b''
    assert checked.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert checked.returncode == 0
    result = run(['format', 'input.yaml'])
    assert result.stdout.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({'input.yaml': content})


def test_large_mapping_is_formatted_in_path_mode(run, workdir):
    """CATCHES: an implementation with quadratic or truncated handling of large inputs, or one that stops normalising spacing, indentless sequences, or flow mappings after the first entries of a 2100-entry mapping."""
    content = ''.join(f'k{i}:   v{i}\nl{i}:\n- {i}\n-   x\nm{i}: {{ a: {i},b: [ 1,2 ] }}\n' for i in range(700))
    write_tree(workdir, {'big.yaml': content})
    result = run(['format', 'big.yaml'])
    assert result.stdout.decode() == '1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    assert read_tree(workdir) == {'big.yaml': (RES / 'large_mapping_path_mode.golden').read_bytes()}


def test_large_multi_document_stream(run, workdir):
    """CATCHES: an implementation that only formats the first document of a stream, merges documents, or drops `---`/`...` markers in a 2000-document stream."""
    stdin = ''.join(f'---\nid:   {i}\ntags: [ a{i},b ]\n...\n' for i in range(2000))
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'large_multi_document_stream.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
