"""YAML with tab characters in indentation or content.

Tab-indented YAML is preserved unless an active `fmt:` directive requires parsing it;
tabs elsewhere (after a sequence dash, inside quoted scalars, in comments or block
scalars) follow separate rules. The documents also carry tags, verbatim tags, anchors,
aliases, quotes with escapes and document markers, so the full line scanner sees them.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'tab_nested_rich': 'a: !tag \'quoted \'\'x\'\' value\' # c\nb: &anc "esc \\" q"\nc: *anc\nd: !<tag:x> v\ng: [x, {y: z}]\nh: - not seq\n? k\n: v\n--- # doc\nlast: \'v\'\ne:\n\tf: 1\n',
    'tab_nested_rich_directive': '# fmt: compact\nlist:\n  - 1\na: !tag \'quoted \'\'x\'\' value\' # c\nb: &anc "esc \\" q"\nc: *anc\nd: !<tag:x> v\ng: [x, {y: z}]\nh: - not seq\n? k\n: v\n--- # doc\nlast: \'v\'\ne:\n\tf: 1\n',
    'tab_in_flow': 'a: [1,\n\t2]\nb:  1\n',
    'tab_after_dash': '-\t a\n- b:  1\n',
    'tab_in_scalar_only': 'a: "x\ty"\nb:   2\n',
    'tab_indented_comment': 'a:  1\n\t# comment\nb:  2\n',
    'tab_block_scalar': 'a: |\n\tliteral\nb:   2\n',
    'tab_markdown_target': '# fmt: markdown\nbody: "Some   text."\nother:\n\tx: 1\n',
    'tab_skip_directive': '# fmt: skip\na:   [1,2]\nb:\n\tc: 1\n',
    'tab_document_markers': '---\na:\n\tb: 1\n...\n---\nc:   2\n',
    'tab_mixed_indent': 'a:\n  b:\n  \tc: 1\n',
}

MODES = {"default": [], "compact": ["--compact"], "verify": ["--verify"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_tab_handling(name, mode, run, workdir, golden):
    """CATCHES: reformatting tab-indented YAML that has no active target, failing to
    format it when a directive is active, or treating tabs inside scalars, comments and
    after `-` like indentation."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
