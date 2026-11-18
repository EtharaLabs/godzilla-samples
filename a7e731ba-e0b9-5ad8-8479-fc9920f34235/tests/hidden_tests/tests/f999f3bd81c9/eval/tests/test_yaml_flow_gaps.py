"""YAML flow collections, block/flow emission, compact mode, aligned flow tables and layout repair.

Black-box coverage for `yamark format` on `.yaml` input (stdin with
`--stdin-file-path` and path mode), plus YAML in Markdown fences: flow spacing
normalisation, expansion of over-width or multiline flow collections to block
style and the cases that must stay inline or byte-for-byte, compact
block-to-flow collapse and its directive/config switches, `fmt: table`
alignment, unmatched-opener layout hints, and preserved or externally
formatted values inside block collections.
"""

from conftest import as_bytes, read_tree, resources_for, write_tree  # noqa: F401

RES = resources_for(__file__)


def test_flow_trailing_commas_are_dropped(run):
    """CATCHES: an implementation that keeps a trailing comma before `]` or `}` (or rejects it) instead of dropping it while normalising entry spacing to `, `."""
    stdin = (
        'a: [ 1,2, ]\n'
        'b: { x: 1,y: 2, }\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: [1, 2]\n'
        b'b: {x: 1, y: 2}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_empty_flow_collections_lose_inner_spaces(run):
    """CATCHES: an implementation that leaves `[ ]` / `{ }` with inner spaces, or drops empty collections nested inside another flow sequence, instead of emitting `[]` and `{}`."""
    stdin = (
        'a: [ ]\n'
        'b: { }\n'
        'c: [ [ ], { } , [] ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: []\n'
        b'b: {}\n'
        b'c: [[], {}, []]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_flow_mapping_entries_without_values_stay_verbatim(run):
    """CATCHES: an implementation that rewrites a flow mapping containing a value-less key (`{x, ...}`) or an empty value (`{x: , ...}`), e.g. inventing `null`, instead of keeping that collection byte-for-byte while the sibling mapping value is still normalised."""
    stdin = (
        'a: {x,  y: 2}\n'
        'b: {x: ,  y: 2}\n'
        'c:    [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: {x,  y: 2}\n'
        b'b: {x: ,  y: 2}\n'
        b'c: [1, 2]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_implicit_pairs_in_flow_sequence_keep_their_source_spelling(run):
    """CATCHES: an implementation that rebuilds single-pair implicit mappings inside a flow sequence (`[x:  1, 'k':v]`) or wraps them in braces, instead of only normalising the separators between entries and keeping each pair's source text."""
    stdin = 'a: [ x:  1,y: 2 ,  \'k\':  v,"q": w ]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'a: [x:  1, y: 2, \'k\':  v, "q": w]\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_implicit_pair_plain_keys_with_quote_and_bracket_characters(run):
    """CATCHES: an implementation that treats a quote or bracket in the middle of a plain flow key (`x'y':`, `x"y":`, `x{y}:`, including escaped `\"` and doubled `''`) as the start of a quoted scalar or nested collection and so mis-splits the entries, instead of keeping the five pairs intact and normalising only the separators."""
    stdin = 'a: [x\'y\': 1,x"y": 2,  x{y}: 3, x"a\\"b": 4,x\'a\'\'b\': 5]\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'a: [x\'y\': 1, x"y": 2, x{y}: 3, x"a\\"b": 4, x\'a\'\'b\': 5]\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_empty_implicit_key_and_explicit_entries_in_flow_sequence(run):
    """CATCHES: an implementation that drops or rewrites an empty implicit key (`[: v]`) or a `? key` entry inside a flow sequence instead of keeping those collections exactly as written while sibling values still format."""
    stdin = (
        'a: [: 1,  b]\n'
        'c: [? x,  d]\n'
        'e:   [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: [: 1, b]\n'
        b'c: [? x, d]\n'
        b'e: [1, 2]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_alias_entries_inside_flow_collections_are_normalised(run):
    """CATCHES: an implementation that cannot render `*alias` entries inside flow collections (leaving the irregular spacing) or that quotes/expands the alias, instead of emitting `[*b, 2]` and `{k: *b}`."""
    stdin = (
        'base: &b 1\n'
        'a: [ *b,  2 ]\n'
        'm: { k:  *b ,j: 3 }\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'base: &b 1\n'
        b'a: [*b, 2]\n'
        b'm: {k: *b, j: 3}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_anchored_or_custom_tagged_flow_entries_keep_collection_verbatim(run):
    """CATCHES: an implementation that normalises spacing inside a flow collection whose entries carry an anchor or a non-core tag (`&x 1`, `!custom 2`, `&n [..]`, `!t {..}`) instead of keeping that collection byte-for-byte."""
    stdin = (
        'a: [&x 1,  *x]\n'
        'b: [!!str 1,  !custom 2]\n'
        'c: [ &n [1, 2], 3 ]\n'
        'd: [ !t {x: 1} ]\n'
        'f: [ &m {x: 1} ]\n'
        'e:    [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: [&x 1,  *x]\n'
        b'b: [!!str 1,  !custom 2]\n'
        b'c: [ &n [1, 2], 3 ]\n'
        b'd: [ !t {x: 1} ]\n'
        b'f: [ &m {x: 1} ]\n'
        b'e: [1, 2]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_core_tags_on_nested_flow_collections_are_removed(run):
    """CATCHES: an implementation that keeps redundant `!!seq`/`!!map` tags on flow collections nested inside another flow collection (or on a flow value) instead of removing them because the syntax already implies the type."""
    stdin = (
        'a: [ !!seq [1, 2], !!map {x: 1} ]\n'
        'b: !!seq [ 3,4 ]\n'
        'c: !!map { y:  5 }\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: [[1, 2], {x: 1}]\n'
        b'b: [3, 4]\n'
        b'c: {y: 5}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_flow_collection_keys_are_normalised(run):
    """CATCHES: an implementation that mishandles flow collections used as flow-mapping keys (`{[1,2]: x}` / `{{k: v}: y}`), e.g. quoting or splitting them, instead of normalising the key collections' spacing like any other entry."""
    stdin = 'a: { [1,2]: x, {k:  v}: y }\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'a: {[1, 2]: x, {k: v}: y}\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_quoted_flow_scalars_are_requoted_only_when_needed(run):
    """CATCHES: an implementation that strips quotes from flow scalars containing `, ` (which would split the entry) or keeps quotes on keys that are safe as plain flow scalars, or that does not turn `'it''s'` into `"it's"`."""
    stdin = (
        'a: [ "a, b" , \'c: d\', \'e\' ,\'it\'\'s\' ]\n'
        'b: { "a b": 1, \'x:y\': 2, "[k]": 3 }\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: ["a, b", \'c: d\', e, "it\'s"]\n'
        b'b: {a b: 1, x:y: 2, "[k]": 3}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_blank_line_inside_multiline_flow_keeps_it_verbatim(run):
    """CATCHES: an implementation that expands a multiline flow collection containing a blank line (dropping the blank line) instead of keeping it byte-for-byte, while still formatting the neighbouring sequence item and mapping value."""
    stdin = (
        'a: [1,\n'
        '\n'
        '  2]\n'
        'b:\n'
        '  - [3,\n'
        '\n'
        '    4]\n'
        '  -   5\n'
        'c:    [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'blank_line_inside_multiline_flow_keeps_it_verbatim.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_comment_inside_multiline_flow_preserves_whole_yaml_file(run, workdir):
    """CATCHES: an implementation that formats the rest of a plain YAML file (e.g. `x:    1` -> `x: 1`) or expands the flow collection when a comment sits inside a multiline flow collection, instead of leaving the whole file unchanged."""
    write_tree(workdir, {
        'input.yaml': (
            'x:    1\n'
            'a: [1, # first\n'
            '  2]\n'
            'y:   [ 1,2 ]\n'
        ),
    })
    stdin = (
        'x:    1\n'
        'a: [1, # first\n'
        '  2]\n'
        'y:   [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'x:    1\n'
        b'a: [1, # first\n'
        b'  2]\n'
        b'y:   [ 1,2 ]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the file is already formatted.
    result2 = run(['format', '--check', 'input.yaml'])
    assert result2.stdout == b''
    assert result2.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result2.returncode == 0


def test_comment_inside_flow_with_directive_and_tab_indent_formats_siblings(run):
    """CATCHES: an implementation that drops or re-flows comments inside multiline flow collections once the document is parsed (here forced by a `fmt:` directive and a tab-indented block), instead of keeping those collections verbatim and formatting only the untouched sibling value."""
    stdin = (
        'x:\n'
        '\ty: 1\n'
        '# fmt: skip\n'
        'z:   1\n'
        'c: {k: 1, # note\n'
        '  # own line\n'
        '  l: 2}\n'
        's: [alpha #c\n'
        '  , beta]\n'
        'd:    [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'comment_inside_flow_with_directive_and_tab_indent_formats_siblings.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_over_width_flow_with_anchor_or_comment_stays_inline(run):
    """CATCHES: an implementation that expands an over-width flow collection to block style even though it carries an anchor or a trailing comment (which block style cannot keep in place), instead of only normalising its spacing on one line."""
    stdin = (
        'a: &x [ alpha, beta, gamma, delta, epsilon ]\n'
        'b: [ alpha, beta, gamma, delta, epsilon ]   # keep\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a: &x [alpha, beta, gamma, delta, epsilon]\n'
        b'b: [alpha, beta, gamma, delta, epsilon] # keep\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_over_width_flow_with_custom_tag_or_explicit_key_is_preserved(run):
    """CATCHES: an implementation that normalises or expands an over-width flow collection with a custom tag or an explicit `? key` pair instead of keeping it exactly as typed while other values still format."""
    stdin = (
        'a: !foo [ alpha, beta, gamma, delta, epsilon ]\n'
        'b: {? x : 1, y: alphabetagamma, z: deltaepsilon}\n'
        'c:   [ 1,2 ]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a: !foo [ alpha, beta, gamma, delta, epsilon ]\n'
        b'b: {? x : 1, y: alphabetagamma, z: deltaepsilon}\n'
        b'c: [1, 2]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_tab_inside_flow_blocks_block_expansion(run):
    """CATCHES: an implementation that expands a flow collection containing a tab into block style; an over-width one must stay inline with normalised separators and a multiline one must stay byte-for-byte."""
    stdin = (
        'a: [alpha,\tbeta, gamma, delta, epsilon]\n'
        'b: [1,\t2,\n'
        '  3]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a: [alpha, beta, gamma, delta, epsilon]\n'
        b'b: [1,\t2,\n'
        b'  3]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_root_flow_mapping_with_anchor_over_width_stays_inline(run):
    """CATCHES: an implementation that expands an anchored root flow mapping wider than `--line-width` into block style (losing the anchor's placement) instead of keeping it as one normalised line."""
    stdin = '&a {alpha: 1,  beta: 2, gamma: 3}\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '10'], input=stdin)
    assert result.stdout == b'&a {alpha: 1, beta: 2, gamma: 3}\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_over_width_flow_mapping_with_flow_key_expands(run):
    """CATCHES: an implementation that refuses to expand an over-width flow mapping whose key is itself a flow sequence, or that expands the key, instead of emitting block pairs with `[1, 2]:` kept as an inline key."""
    stdin = 'a: {[1,2]: alphabetagamma, b: deltaepsilonzeta}\n'
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b'  [1, 2]: alphabetagamma\n'
        b'  b: deltaepsilonzeta\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_expansion_with_indent_width_eight_reaches_deep_columns(run):
    """CATCHES: an implementation that caps or miscomputes indentation beyond 32 columns when expanding a nested flow mapping under `--indent-width 8`."""
    stdin = (
        'a:\n'
        '  b:\n'
        '    c:\n'
        '      d: {x: [alpha, beta, gamma], y: 1}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '8', '--line-width', '30'], input=stdin)
    assert result.stdout == (RES / 'expansion_with_indent_width_eight_reaches_deep_columns.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_expanded_flow_entries_keep_quoted_scalar_style(run):
    """CATCHES: an implementation that rewrites a single-quoted scalar containing `''` and `"` (or a double-quoted one with an escape) into another style when its over-width flow sequence is expanded, instead of keeping each quoted entry as written on its own `- ` line."""
    stdin = (
        'a: [\'it\'\'s "x" here\', delta]\n'
        'b: ["alpha\\tbeta gamma", delta]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '16'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b'  - \'it\'\'s "x" here\'\n'
        b'  - delta\n'
        b'b:\n'
        b'  - "alpha\\tbeta gamma"\n'
        b'  - delta\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_diagnostics_trace_counts_block_rendered_flow_collections(run):
    """CATCHES: an implementation whose `--diagnostics` YAML trace does not count a flow collection planned for block expansion under `planned_rendered_block_flow_collections` (or counts it as an inline flow collection)."""
    stdin = (
        'a: [alpha, beta, gamma, delta]\n'
        'b: [1, 2]\n'
    )
    result = run(['format', '--diagnostics', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b'  - alpha\n'
        b'  - beta\n'
        b'  - gamma\n'
        b'  - delta\n'
        b'b: [1, 2]\n'
    )
    assert result.stderr.decode() == 'input.yaml:1:1: note: yaml trace: source_scans=1 parse_passes=1 source_lines=2 yaml_scanned_lines=2 yaml_semantic_nodes=11 planned_rendered_scalars=8 planned_rendered_flow_collections=1 planned_rendered_block_flow_collections=1 emitted_bytes=52 emitted_nodes=2\n'
    assert result.returncode == 0


def test_unmatched_opener_too_wide_is_kept_as_typed(run):
    """CATCHES: an implementation that collapses an unmatched-opener hint even when the flow form exceeds `--line-width`, or that fails/errors, instead of keeping the hinted collection exactly as typed and formatting the rest of the file."""
    stdin = (
        'tags: [\n'
        '  - alphabet\n'
        '  - betamax\n'
        '  - gammaray\n'
        'other:    1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'tags: [\n'
        b'  - alphabet\n'
        b'  - betamax\n'
        b'  - gammaray\n'
        b'other: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unmatched_opener_on_sequence_item_too_wide_is_kept(run):
    """CATCHES: an implementation that collapses (or drops the `[` of) a hinted sequence-item collection whose flow form does not fit the width, instead of keeping the item as typed while normalising the sibling item."""
    stdin = (
        'items:\n'
        '  - [\n'
        '    - alphabet\n'
        '    - betamax\n'
        '  -    plain\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'items:\n'
        b'  - [\n'
        b'    - alphabet\n'
        b'    - betamax\n'
        b'  - plain\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unmatched_brace_collapses_mapping_with_nested_sequence(run):
    """CATCHES: an implementation that collapses only the outer mapping of a `{` layout hint, leaving its nested block sequence in block style, instead of emitting the whole subtree in flow style on one line."""
    stdin = (
        'pkg: {\n'
        '  name: yamark\n'
        '  tags:\n'
        '    - a\n'
        '    - b\n'
        'outer:\n'
        '  inner: [\n'
        '    - x\n'
        '    - y\n'
        '  other:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'pkg: {name: yamark, tags: [a, b]}\n'
        b'outer:\n'
        b'  inner: [x, y]\n'
        b'  other: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_unmatched_opener_with_comment_inside_is_kept(run, workdir):
    """CATCHES: an implementation that collapses a hinted collection containing a comment (dropping the comment) instead of keeping the hinted lines as typed."""
    write_tree(workdir, {
        'input.yaml': (
            'tags: [\n'
            '  # first\n'
            '  - a\n'
            '  - b\n'
            'next:    2\n'
        ),
    })
    stdin = (
        'tags: [\n'
        '  # first\n'
        '  - a\n'
        '  - b\n'
        'next:    2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'tags: [\n'
        b'  # first\n'
        b'  - a\n'
        b'  - b\n'
        b'next:    2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the file is already formatted.
    result2 = run(['format', '--check', 'input.yaml'])
    assert result2.stdout == b''
    assert result2.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result2.returncode == 0


def test_unmatched_opener_as_explicit_mapping_value(run):
    """CATCHES: an implementation that ignores an unmatched opener after an explicit `:` value indicator, or collapses it even when too wide, instead of collapsing it when it fits and keeping the typed lines when it does not."""
    stdin = (
        '? a\n'
        ': [\n'
        '  - x\n'
        '  - y\n'
        '? b\n'
        ': [\n'
        '  - alphabetagammadelta\n'
        '  - epsilon\n'
        'c:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '24'], input=stdin)
    assert result.stdout == (RES / 'unmatched_opener_as_explicit_mapping_value.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_pair_with_comment_before_value_is_preserved(run):
    """CATCHES: an implementation that reformats an explicit `? key` pair whose `:` line is separated from the key by a comment line (normalising `:   1`) instead of keeping that pair as written."""
    stdin = (
        '? a\n'
        '# note\n'
        ':   1\n'
        'b:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? a\n'
        b'# note\n'
        b':   1\n'
        b'b: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_explicit_pair_value_with_blank_line_flow_is_preserved(run):
    """CATCHES: an implementation that expands or re-spaces a multiline flow value of an explicit pair that contains a blank line, instead of keeping the pair verbatim while normalising the following pair."""
    stdin = (
        '? a\n'
        ': [1,\n'
        '\n'
        '  2]\n'
        'b:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'? a\n'
        b': [1,\n'
        b'\n'
        b'  2]\n'
        b'b: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_collapses_nested_collections_when_they_fit(run):
    """CATCHES: an implementation whose compact mode collapses only leaf collections (or none) instead of folding a whole nested block subtree into one flow mapping when it fits the width, or that keeps a redundant `!!map` tag instead of dropping it while collapsing."""
    stdin = (
        'pkg:\n'
        '  name: yamark\n'
        '  tags:\n'
        '    - a\n'
        '    - b\n'
        '  empty: []\n'
        '  none: {}\n'
        'meta: !!map\n'
        '  k: v\n'
        '  l: w\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (
        b'pkg: {name: yamark, tags: [a, b], empty: [], none: {}}\n'
        b'meta: {k: v, l: w}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_skips_collections_with_comments_nulls_and_anchors(run):
    """CATCHES: an implementation whose compact mode collapses block collections that contain an own-line comment, a trailing comment, an empty (null) value or an anchor, instead of leaving those collections in block style while still normalising spacing."""
    stdin = (
        'a:\n'
        '  # c\n'
        '  name: yamark\n'
        'b:\n'
        '  - x # c\n'
        '  - y\n'
        'c:\n'
        '  name:\n'
        '  lang:   rust\n'
        'd: &p\n'
        '  k: v\n'
        '  l: w\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'compact_skips_collections_with_comments_nulls_and_anchors.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_sequence_with_leading_comment_stays_block(run):
    """CATCHES: an implementation that compacts a block sequence when a comment line sits between its items (losing or moving the comment) instead of keeping it in block style."""
    stdin = (
        'tags:\n'
        '  - a\n'
        '  # c\n'
        '  - b\n'
        'other:\n'
        '  - x\n'
        '  - y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (
        b'tags:\n'
        b'  - a\n'
        b'  # c\n'
        b'  - b\n'
        b'other: [x, y]\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_root_collections_collapse_only_without_nested_collections(run):
    """CATCHES: an implementation that collapses a root mapping/sequence even when one of its values is itself a collection, or never collapses root collections, instead of `{a: 1, b: 2}` for a flat root and block style for a root holding a nested collection."""
    stdin = (
        'a: 1\n'
        'b: 2\n'
        '---\n'
        '- a\n'
        '- [b, c]\n'
        '---\n'
        '- x\n'
        '- y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'compact_root_collections_collapse_only_without_nested_collections.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_sequence_item_measured_at_item_indent(run):
    """CATCHES: an implementation that compacts a nested sequence item using the source column instead of the emitted `- ` prefix (producing an over-width `- [abc, de]`), instead of keeping it in block style under a bare `-`."""
    stdin = (
        '- - abc\n'
        '  - de\n'
        '-   x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact', '--line-width', '10'], input=stdin)
    assert result.stdout == (
        b'-\n'
        b'  - abc\n'
        b'  - de\n'
        b'- x\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_mode_suppresses_multiline_flow_expansion(run):
    """CATCHES: an implementation that still expands a multiline flow collection to block style in compact mode instead of joining it onto one normalised flow line."""
    stdin = (
        'a: [1,\n'
        '  2]\n'
        'b: {x: 1,\n'
        '  y: 2}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (
        b'a: [1, 2]\n'
        b'b: {x: 1, y: 2}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_with_indent_width_four_respects_line_width(run):
    """CATCHES: an implementation that measures compact eligibility without the emitted `--indent-width 4` indentation, collapsing mappings that then overflow `--line-width`, instead of collapsing only the shallow sequence."""
    stdin = (
        'a:\n'
        '  b:\n'
        '    - alpha\n'
        '    - beta\n'
        '  c:\n'
        '    d:\n'
        '      e: f\n'
        '      g: h\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact', '--indent-width', '4', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b'    b: [alpha, beta]\n'
        b'    c:\n'
        b'        d:\n'
        b'            e: f\n'
        b'            g: h\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_directive_yes_and_one_forms_enable_compaction(run):
    """CATCHES: an implementation that only accepts `compact` / `compact=true` and ignores the documented `compact=yes`, `compact=1` and `compact true` spellings for enabling the next compaction."""
    stdin = (
        '# fmt: compact=yes\n'
        'a:\n'
        '  - x\n'
        '  - y\n'
        '# fmt: compact=1\n'
        'b:\n'
        '  - x\n'
        '  - y\n'
        '# fmt: compact true\n'
        'c:\n'
        '  - x\n'
        '  - y\n'
        'd:\n'
        '  - x\n'
        '  - y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'compact_directive_yes_and_one_forms_enable_compaction.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_directive_no_and_false_forms_disable_next_target(run):
    """CATCHES: an implementation that ignores `compact=no` / `compact false` under `--compact`, or applies them beyond the next collection, instead of keeping only the next collection in block style."""
    stdin = (
        '# fmt: compact=no\n'
        'a:\n'
        '  - x\n'
        '  - y\n'
        '# fmt: compact false\n'
        'b:\n'
        '  - x\n'
        '  - y\n'
        'c:\n'
        '  - x\n'
        '  - y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'compact_directive_no_and_false_forms_disable_next_target.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_scope_from_here_enables_following_collections(run):
    """CATCHES: an implementation that applies `fmt: compact scope=from-here` to collections before the directive, or only to the next one, instead of every following eligible collection."""
    stdin = (
        'a:\n'
        '  - x\n'
        '  - y\n'
        '# fmt: compact scope=from-here\n'
        'b:\n'
        '  - x\n'
        '  - y\n'
        'c:\n'
        '  k: v\n'
        '  l: w\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a:\n'
        b'  - x\n'
        b'  - y\n'
        b'# fmt: compact scope=from-here\n'
        b'b: [x, y]\n'
        b'c: {k: v, l: w}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_false_scope_file_disables_cli_compact_everywhere(run, workdir):
    """CATCHES: an implementation where `fmt: compact=0 scope=file` only affects collections after the directive (or is overridden by `--compact`) instead of disabling compaction for the whole YAML document."""
    write_tree(workdir, {
        'input.yaml': (
            'a:\n'
            '  - x\n'
            '  - y\n'
            '# fmt: compact=0 scope=file\n'
            'b:\n'
            '  - x\n'
            '  - y\n'
        ),
    })
    stdin = (
        'a:\n'
        '  - x\n'
        '  - y\n'
        '# fmt: compact=0 scope=file\n'
        'b:\n'
        '  - x\n'
        '  - y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'compact_false_scope_file_disables_cli_compact_everywhere.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Path mode must agree that the file is already formatted.
    result2 = run(['format', '--check', '--compact', 'input.yaml'])
    assert result2.stdout == b''
    assert result2.stderr.decode() == '1 files scanned, 0 formatted, 1 unchanged, 0 skipped, 0 failed\n'
    assert result2.returncode == 0


def test_compact_directive_invalid_scope_is_an_error(run):
    """CATCHES: an implementation that ignores an unknown `scope=` on a compact directive instead of failing with the documented scope error naming the bad value."""
    stdin = (
        '# fmt: compact scope=everywhere\n'
        'a:\n'
        '  - x\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'input.yaml:1:1: error: invalid fmt directive scope: everywhere\n'
    assert result.returncode == 1


def test_config_compact_true_enables_compaction_in_path_mode(run, workdir):
    """CATCHES: an implementation that ignores `[format].compact = true` from `yamark.toml` when formatting a file in place."""
    write_tree(workdir, {
        'yamark.toml': (
            '[format]\n'
            'compact = true\n'
        ),
        'data.yaml': (
            'a:\n'
            '  - x\n'
            '  - y\n'
            'b:\n'
            '  k: v\n'
            '  l: w\n'
        ),
    })
    result = run(['format', 'data.yaml'])
    assert result.stdout == b'1 files scanned, 1 formatted, 0 unchanged, 0 skipped, 0 failed\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    assert read_tree(workdir) == as_bytes({
        'data.yaml': (
            b'a: [x, y]\n'
            b'b: {k: v, l: w}\n'
        ),
        'yamark.toml': (
            b'[format]\n'
            b'compact = true\n'
        ),
    })


def test_cli_compact_overrides_config_compact_false(run, workdir):
    """CATCHES: an implementation where `[format].compact = false` in yamark.toml wins over the `--compact` flag instead of the flag enabling compact mode."""
    write_tree(workdir, {
        'yamark.toml': (
            '[format]\n'
            'compact = false\n'
        ),
    })
    stdin = (
        'a:\n'
        '  - x\n'
        '  - y\n'
    )
    result = run(['format', '--compact', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b'a: [x, y]\n'
    assert result.stderr.decode() == ''
    assert result.returncode == 0
    # Without the flag the config keeps block style.
    stdin2 = (
        'a:\n'
        '  - x\n'
        '  - y\n'
    )
    result2 = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin2)
    assert result2.stdout == (
        b'a:\n'
        b'  - x\n'
        b'  - y\n'
    )
    assert result2.stderr.decode() == ''
    assert result2.returncode == 0


def test_config_compact_must_be_boolean(run, workdir):
    """CATCHES: an implementation that accepts a string such as `compact = "yes"` in `[format]` instead of rejecting it with `format.compact must be a boolean` and exit status 1."""
    write_tree(workdir, {
        'yamark.toml': (
            '[format]\n'
            'compact = "yes"\n'
        ),
    })
    stdin = (
        'a:\n'
        '  - x\n'
    )
    result = run(['format', '--config', 'yamark.toml', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'yamark.toml:1:1: error: format.compact must be a boolean\n'
    assert result.returncode == 1


def test_table_aligns_rows_with_different_keys_by_position(run):
    """CATCHES: an implementation that aligns `fmt: table` columns by key name (or refuses rows with different keys) instead of padding each field position to the widest field in that position."""
    stdin = (
        '# fmt: table\n'
        '- {name: alpha,type: string}\n'
        '- {id: 7, label: b, extra: zz}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: table\n'
        b'- {name: alpha, type: string}\n'
        b'- {id: 7,       label: b,     extra: zz}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_rows_with_fewer_fields_are_padded_only_where_needed(run):
    """CATCHES: an implementation that pads the last field of a row, or pads rows with fewer fields to the full column count, instead of padding only non-final fields."""
    stdin = (
        '# fmt: table\n'
        '- {name: alpha,type: string, default: x}\n'
        '- { name: b }\n'
        '- {name: ccc, type: int}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: table\n'
        b'- {name: alpha, type: string, default: x}\n'
        b'- {name: b}\n'
        b'- {name: ccc,   type: int}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_nested_flow_values_count_as_single_cells(run):
    """CATCHES: an implementation that splits nested flow collections into separate table columns or leaves their inner spacing unnormalised instead of treating each nested value as one normalised cell."""
    stdin = (
        '# fmt: table\n'
        '- {name: a, opts: {x: 1, y: [1,2]}}\n'
        '- {name: bbb, opts: {}}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: table\n'
        b'- {name: a,   opts: {x: 1, y: [1, 2]}}\n'
        b'- {name: bbb, opts: {}}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_comment_or_blank_line_starts_new_alignment_group(run):
    """CATCHES: an implementation that aligns all rows of a `fmt: table` sequence together across an intervening comment or blank line instead of aligning each separated group independently."""
    stdin = (
        '# fmt: table\n'
        '- {a: 1, b: 2}\n'
        '# group two\n'
        '- {a: 333, b: 4}\n'
        '- {a: 5, b: 66}\n'
        '\n'
        '- {a: 7777, b: 8}\n'
        '- {a: 9, b: 10}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'table_comment_or_blank_line_starts_new_alignment_group.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_trailing_comments_align_closing_braces_and_comments(run):
    """CATCHES: an implementation that leaves row trailing comments where they were instead of padding the last field so closing braces align and starting all comments one space after the widest row."""
    stdin = (
        '# fmt: table\n'
        '- {a: 1, b: 2} # one\n'
        '- {a: 333, b: 4444}   # two\n'
        '- {a: 5, b: 6}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: table\n'
        b'- {a: 1,   b: 2   } # one\n'
        b'- {a: 333, b: 4444} # two\n'
        b'- {a: 5,   b: 6   }\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_with_unsupported_rows_is_preserved(run):
    """CATCHES: an implementation that partially aligns a `fmt: table` sequence that also contains a plain scalar, an empty flow mapping, a tagged/anchored row or a block mapping row, instead of preserving that whole sequence as typed."""
    stdin = (
        'a:\n'
        '  # fmt: table\n'
        '  - {x: 1,  y: 2}\n'
        '  - plain\n'
        'b:\n'
        '  # fmt: table\n'
        '  - {x: 1,  y: 2}\n'
        '  - {}\n'
        'c:\n'
        '  # fmt: table\n'
        '  - &r {x: 1,  y: 2}\n'
        '  - {x: 3, y: 4}\n'
        'd:\n'
        '  # fmt: table\n'
        '  - {x: 1,  y: 2}\n'
        '  - x: 3\n'
        '    y: 4\n'
        'e:    1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'table_with_unsupported_rows_is_preserved.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_rows_with_explicit_keys_or_templates_are_preserved(run):
    """CATCHES: an implementation that aligns `fmt: table` rows containing an explicit `? key` pair or a template expression instead of preserving that sequence byte-for-byte."""
    stdin = (
        '# fmt: table\n'
        '- {? a : 1}\n'
        '- {a:  2}\n'
        '---\n'
        '# fmt: table\n'
        '- {a: {{ x }}, b: 2}\n'
        '- {a: 3,  b: 4}\n'
        '---\n'
        'z:    1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'table_rows_with_explicit_keys_or_templates_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_table_directive_variants_collapse_block_rows(run):
    """CATCHES: an implementation that accepts only `fmt: compact table` and not the equivalent `fmt: table compact` / `fmt: table compact=true`, or that does not collapse block-mapping rows before aligning."""
    stdin = (
        'a:\n'
        '  # fmt: compact table\n'
        '  - k: 1\n'
        '    v: 2\n'
        '  - k: 333\n'
        '    v: 4\n'
        'b:\n'
        '  # fmt: table compact\n'
        '  - {k: 1, v: 2}\n'
        '  - k: 333\n'
        '    v: 4\n'
        'c:\n'
        '  # fmt: table compact=true\n'
        '  - k: 1\n'
        '    vv: 2\n'
        '  - kkk: 3\n'
        '    v: 4\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'compact_table_directive_variants_collapse_block_rows.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_table_rows_with_comments_or_anchors_are_preserved(run):
    """CATCHES: an implementation that collapses block-mapping table rows containing an own-line comment, a trailing comment or an anchor (losing them) instead of preserving the whole sequence."""
    stdin = (
        'a:\n'
        '  # fmt: compact table\n'
        '  - k: 1\n'
        '    # c\n'
        '    v: 2\n'
        '  - k: 3\n'
        '    v:   4\n'
        'b:\n'
        '  # fmt: compact table\n'
        '  - k: 1 # c\n'
        '    v: 2\n'
        '  - k: 3\n'
        '    v:   4\n'
        'c:\n'
        '  # fmt: compact table\n'
        '  - &r\n'
        '    k: 1\n'
        '    v: 2\n'
        '  - k: 3\n'
        '    v:   4\n'
        'd:    1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'compact_table_rows_with_comments_or_anchors_are_preserved.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_table_unquotes_block_keys_and_keeps_nested_block_rows(run):
    """CATCHES: an implementation that keeps unnecessary quotes on block-mapping keys when collapsing table rows, or collapses a row whose value is a nested block sequence, instead of `{a b: 1, c: 2}` rows and preserving the sequence with the nested block value."""
    stdin = (
        'a:\n'
        '  # fmt: compact table\n'
        '  - "a b": 1\n'
        "    'c': 2\n"
        '  - "a b": 3\n'
        "    'c': 44\n"
        'b:\n'
        '  # fmt: compact table\n'
        '  - k: 1\n'
        '    v:\n'
        '      - x\n'
        '      - y\n'
        '  - k: 3\n'
        '    v: [z]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'compact_table_unquotes_block_keys_and_keeps_nested_block_rows.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_same_line_table_directives_on_empty_parents(run):
    """CATCHES: an implementation that only honours own-line table directives and ignores `fmt: table` / `fmt: compact table` written as a same-line comment on an empty-valued parent key."""
    stdin = (
        'items: # fmt: table\n'
        '  - {a: 1, b: 2}\n'
        '  - {a: 333, b: 4}\n'
        'rows: # fmt: compact table\n'
        '  - a: 1\n'
        '    b: 2\n'
        '  - a: 333\n'
        '    b: 4\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'items: # fmt: table\n'
        b'  - {a: 1,   b: 2}\n'
        b'  - {a: 333, b: 4}\n'
        b'rows: # fmt: compact table\n'
        b'  - {a: 1,   b: 2}\n'
        b'  - {a: 333, b: 4}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_same_line_table_directive_on_populated_flow_parent_is_error(run):
    """CATCHES: an implementation that accepts or ignores `# fmt: table` after a populated value instead of failing with the exact position of the unsupported directive."""
    stdin = 'items: [1] # fmt: table\n'
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'input.yaml:1:12: error: fmt directive is not supported in this position\n'
    assert result.returncode == 1


def test_same_line_table_directive_on_scalar_parent_is_error(run):
    """CATCHES: an implementation that accepts `# fmt: table` as a same-line comment on a scalar-valued key instead of reporting `fmt directive is not supported in this position` at the comment column."""
    stdin = (
        'first: 1\n'
        'items: x # fmt: table\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'input.yaml:2:10: error: fmt directive is not supported in this position\n'
    assert result.returncode == 1


def test_table_directive_before_mapping_has_no_target(run):
    """CATCHES: an implementation that silently ignores a `fmt: table` directive followed by a mapping instead of reporting that it has no target at the end of the document."""
    stdin = (
        '# fmt: table\n'
        'a: 1\n'
        'b: 2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == b''
    assert result.stderr.decode() == 'input.yaml:3:5: error: fmt: table has no target\n'
    assert result.returncode == 1


def test_table_alias_cells_and_crlf_rows(run):
    """CATCHES: an implementation that cannot measure alias cells in a table, or that writes LF endings for aligned rows in a CRLF document."""
    stdin = (
        'x: &v 1\r\n'
        't:\r\n'
        '  # fmt: table\r\n'
        '  - {a: *v,b: 2}\r\n'
        '  - {a: 3, bb: 4}\r\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'x: &v 1\r\n'
        b't:\r\n'
        b'  # fmt: table\r\n'
        b'  - {a: *v, b: 2}\r\n'
        b'  - {a: 3,  bb: 4}\r\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_table_in_markdown_yaml_fence_and_indent_width(run):
    """CATCHES: an implementation that skips `fmt: table` inside a YAML fence of a Markdown file, or re-indents the table rows by `--indent-width` instead of keeping the nested sequence at its source indentation."""
    stdin = (
        'Text\n'
        '\n'
        '```yaml\n'
        'outer:\n'
        '    # fmt: table\n'
        '    - {a: 1, b: 2}\n'
        '    - {a: 333, b: 4}\n'
        '```\n'
    )
    result = run(['format', '--stdin-file-path', 'doc.md', '--indent-width', '4'], input=stdin)
    assert result.stdout == (RES / 'table_in_markdown_yaml_fence_and_indent_width.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_skip_directive_inside_sequence_item_preserves_nested_sequence(run):
    """CATCHES: an implementation that formats a nested block sequence targeted by `fmt: skip` below a bare `-` marker (or drops the marker line) instead of emitting `-`, the directive and the nested items verbatim, while the next item is formatted."""
    stdin = (
        '-\n'
        '  # fmt: skip\n'
        '  -   x\n'
        '  -   [ 1,2 ]\n'
        '-   3\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'-\n'
        b'  # fmt: skip\n'
        b'  -   x\n'
        b'  -   [ 1,2 ]\n'
        b'- 3\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_skip_directive_inside_tagged_anchored_value_keeps_anchor(run):
    """CATCHES: an implementation that drops the anchor, or keeps the redundant `!!map` tag, on the parent line of a mapping value preserved by `fmt: skip`, instead of `a: &m` followed by the verbatim body."""
    stdin = (
        'a: !!map &m\n'
        '  # fmt: skip\n'
        '  b:    1\n'
        'd:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: &m\n'
        b'  # fmt: skip\n'
        b'  b:    1\n'
        b'd: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_skip_directive_inside_tagged_anchored_sequence_item(run):
    """CATCHES: an implementation that drops the anchor, or keeps the redundant `!!map` tag, on a sequence item whose mapping value is preserved by `fmt: skip`, instead of `- &m` followed by the verbatim body."""
    stdin = (
        '- !!map &m\n'
        '  # fmt: skip\n'
        '  b:    1\n'
        '-   3\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'- &m\n'
        b'  # fmt: skip\n'
        b'  b:    1\n'
        b'- 3\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_embedded_formatter_on_sequence_item_literal(run, workdir):
    """CATCHES: an implementation that ignores `fmt: python` before a literal block-scalar sequence item, or re-indents its output wrongly, instead of replacing the body with the configured formatter's stdout."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = { command = ["python3", "fmt_script", "{path}"], path_suffix = ".py" }\n'
        ),
        'fmt_script': (
            'import sys\n'
            "sys.stdout.write(sys.stdin.read().replace('=', ' = '))\n"
        ),
    })
    stdin = (
        'steps:\n'
        '  # fmt: python\n'
        '  - |\n'
        '    x=1\n'
        '    y=2\n'
        '  -   z\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'steps:\n'
        b'  # fmt: python\n'
        b'  - |\n'
        b'    x = 1\n'
        b'    y = 2\n'
        b'  - z\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_missing_optional_formatter_preserves_sequence_item_literal(run, workdir, tmp_path):
    """CATCHES: an implementation that errors or rewrites a `fmt: python` sequence-item literal when the optional `ruff` formatter is missing, instead of preserving that item and still formatting its sibling."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = "ruff"\n'
        ),
    })
    (tmp_path / "emptybin").mkdir()
    stdin = (
        'steps:\n'
        '  # fmt: python\n'
        '  - |\n'
        '    x=1\n'
        '  -   z\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin, env_overrides={"PATH": str(tmp_path / "emptybin")})
    assert result.stdout == (
        b'steps:\n'
        b'  # fmt: python\n'
        b'  - |\n'
        b'    x=1\n'
        b'  - z\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_missing_optional_formatter_preserves_mapping_literal(run, workdir, tmp_path):
    """CATCHES: an implementation that errors or rewrites a `fmt: python` mapping-value literal when the optional `ruff` formatter is missing, instead of preserving that pair and still formatting the next pair."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = "ruff"\n'
        ),
    })
    (tmp_path / "emptybin").mkdir()
    stdin = (
        '# fmt: python\n'
        'code: |\n'
        '  x=1\n'
        'other:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin, env_overrides={"PATH": str(tmp_path / "emptybin")})
    assert result.stdout == (
        b'# fmt: python\n'
        b'code: |\n'
        b'  x=1\n'
        b'other: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_embedded_formatter_on_literal_below_commented_key(run, workdir):
    """CATCHES: an implementation that drops the parent comment or the directive when a formatted literal block scalar sits on its own line below `key: # note` or below a bare `-`, instead of keeping both and replacing only the body."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = { command = ["python3", "fmt_script", "{path}"], path_suffix = ".py" }\n'
        ),
        'fmt_script': (
            'import sys\n'
            "sys.stdout.write(sys.stdin.read().replace('=', ' = '))\n"
        ),
    })
    stdin = (
        '# fmt: python\n'
        'code: # note\n'
        '  |\n'
        '    x=1\n'
        'list:\n'
        '  # fmt: python\n'
        '  - # item\n'
        '    |\n'
        '      y=2\n'
        'other:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'embedded_formatter_on_literal_below_commented_key.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_missing_formatter_preserves_literal_below_commented_key(run, workdir, tmp_path):
    """CATCHES: an implementation that rewrites (or errors on) a `fmt: python` literal placed below a commented key when the optional formatter is missing, instead of preserving that entry verbatim."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = "ruff"\n'
        ),
    })
    (tmp_path / "emptybin").mkdir()
    stdin = (
        '# fmt: python\n'
        'code: # note\n'
        '  |\n'
        '    x=1\n'
        'other:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin, env_overrides={"PATH": str(tmp_path / "emptybin")})
    assert result.stdout == (
        b'# fmt: python\n'
        b'code: # note\n'
        b'  |\n'
        b'    x=1\n'
        b'other: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_embedded_formatter_on_explicit_pair_value(run, workdir):
    """CATCHES: an implementation that does not apply `fmt: python` to the literal value of an explicit `? key` pair (including one placed below `: # note`), or loses the `?`/`:` indicator lines or the comment, instead of formatting just the body."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = { command = ["python3", "fmt_script", "{path}"], path_suffix = ".py" }\n'
        ),
        'fmt_script': (
            'import sys\n'
            "sys.stdout.write(sys.stdin.read().replace('=', ' = '))\n"
        ),
    })
    stdin = (
        '# fmt: python\n'
        '? code\n'
        ': |\n'
        '  x=1\n'
        '# fmt: python\n'
        '? more\n'
        ': # note\n'
        '  |\n'
        '    y=2\n'
        'other:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'embedded_formatter_on_explicit_pair_value.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_missing_formatter_preserves_explicit_pair_value(run, workdir, tmp_path):
    """CATCHES: an implementation that errors on or alters an explicit pair whose `fmt: python` literal cannot be formatted because the optional formatter is missing, instead of preserving that pair verbatim."""
    write_tree(workdir, {
        'yamark.toml': (
            '[embedded.python]\n'
            'formatter = "ruff"\n'
        ),
    })
    (tmp_path / "emptybin").mkdir()
    stdin = (
        '# fmt: python\n'
        '? code\n'
        ': |\n'
        '  x=1\n'
        'other:   2\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin, env_overrides={"PATH": str(tmp_path / "emptybin")})
    assert result.stdout == (
        b'# fmt: python\n'
        b'? code\n'
        b': |\n'
        b'  x=1\n'
        b'other: 2\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_sequence_item_mapping_with_preserved_value_keeps_source_key_column(run):
    """CATCHES: an implementation that re-indents the keys of a `-   key:` sequence-item mapping to the normal `- key:` column even though one value (a multiline flow with a blank line, or a tab) is preserved verbatim, which would misalign the preserved lines; the source key column must be kept for that item only."""
    stdin = (
        '-   name:   x\n'
        '    data: [1,\n'
        '\n'
        '      2]\n'
        '-   other:   y\n'
        '-   name:   z\n'
        '    data: [1,\t2,\n'
        '      3]\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (RES / 'sequence_item_mapping_with_preserved_value_keeps_source_key_column.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_over_width_flow_with_long_implicit_pair_stays_inline(run):
    """CATCHES: an implementation that expands an over-width flow collection whose too-long entry is an implicit `key: value` pair (which cannot be expanded) instead of keeping the collection on one normalised line."""
    stdin = (
        'a: [x: alphabetagammadelta,  b]\n'
        'c: {k: [y: alphabetagammadelta]}\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--line-width', '20'], input=stdin)
    assert result.stdout == (
        b'a: [x: alphabetagammadelta, b]\n'
        b'c: {k: [y: alphabetagammadelta]}\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_compact_false_file_scope_does_not_block_layout_repair(run):
    """CATCHES: an implementation that treats unmatched-opener layout hints as compaction, so that `fmt: compact=false scope=file` stops `tags: [` / `pkg: {` from collapsing to flow style."""
    stdin = (
        '# fmt: compact=false scope=file\n'
        'tags: [\n'
        '  - a\n'
        '  - b\n'
        'pkg: {\n'
        '  k: v\n'
        '  l: w\n'
        'x:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'# fmt: compact=false scope=file\n'
        b'tags: [a, b]\n'
        b'pkg: {k: v, l: w}\n'
        b'x: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_empty_markdown_tagged_sequence_items_become_empty_strings(run):
    """CATCHES: an implementation that leaves an empty `!md`-tagged or `fmt: markdown`-targeted sequence item as a bare marker (or drops the tag) instead of emitting an explicit empty string `""`."""
    stdin = (
        '- !md\n'
        '-   x\n'
        '# fmt: markdown\n'
        '- \n'
        '-   y\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'- !md ""\n'
        b'- x\n'
        b'# fmt: markdown\n'
        b'- ""\n'
        b'- y\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_template_values_block_compaction(run):
    """CATCHES: an implementation that compacts (or table-collapses) block collections whose values contain a template expression such as `<% y %>`, instead of leaving them in block style."""
    stdin = (
        'a:\n'
        '  - x\n'
        '  - <% y %>\n'
        'b:\n'
        '  k: <% v %>\n'
        '  l: w\n'
        'c:\n'
        '  # fmt: compact table\n'
        '  - a: <% x %>\n'
        '    b: 2\n'
        '  - a: 3\n'
        '    b:   4\n'
        'd:    1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--compact'], input=stdin)
    assert result.stdout == (RES / 'template_values_block_compaction.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_sequence_item_mapping_keeps_nested_sequence_at_key_column(run):
    """CATCHES: an implementation that indents a block sequence under the first key of a sequence-item mapping by `--indent-width` instead of keeping its `- ` markers at the mapping's key column."""
    stdin = (
        '- key:\n'
        '  - a\n'
        '  - b\n'
        '  other:   1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml', '--indent-width', '4'], input=stdin)
    assert result.stdout == (
        b'- key:\n'
        b'  - a\n'
        b'  - b\n'
        b'  other: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_malformed_flow_lines_are_left_unchanged(run):
    """CATCHES: an implementation that errors, or rewrites, lines whose flow collection cannot be parsed (`[1, 2] junk`, `[{]}`) instead of leaving them unchanged and still formatting the rest of the file."""
    stdin = (
        'a: [1, 2] junk\n'
        'b: [{]}\n'
        'c:    1\n'
    )
    result = run(['format', '--stdin-file-path', 'input.yaml'], input=stdin)
    assert result.stdout == (
        b'a: [1, 2] junk\n'
        b'b: [{]}\n'
        b'c: 1\n'
    )
    assert result.stderr.decode() == ''
    assert result.returncode == 0


def test_front_matter_flow_collections_follow_yaml_rules(run):
    """CATCHES: an implementation that skips YAML flow normalisation, over-width expansion or unmatched-opener repair inside Markdown front matter."""
    stdin = (
        '---\n'
        'title: x\n'
        'tags: [ a,b ,c ]\n'
        'list: [alpha, beta, gamma, delta]\n'
        'repair: [\n'
        '  - a\n'
        '  - b\n'
        '---\n'
        '\n'
        'Body   text.\n'
    )
    result = run(['format', '--stdin-file-path', 'doc.md', '--line-width', '20'], input=stdin)
    assert result.stdout == (RES / 'front_matter_flow_collections_follow_yaml_rules.golden').read_bytes()
    assert result.stderr.decode() == ''
    assert result.returncode == 0
