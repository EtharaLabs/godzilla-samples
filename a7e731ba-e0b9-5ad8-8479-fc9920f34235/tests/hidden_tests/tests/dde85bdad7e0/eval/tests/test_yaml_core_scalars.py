"""YAML core scalars inside flow and block collections: implicit booleans/nulls, explicitly
tagged quoted core values (`!!bool "TRUE"`, `!!int '42'`, escaped forms), invalid or
non-ASCII tagged content that must stay quoted, anchors and tags in either order, and the
width accounting that decides whether a normalised flow collection still fits.
"""

import pytest

from conftest import format_both_ways

DOCUMENTS = {
    'block_tagged_number_spellings': 'f0: !!float ".inf"\nf1: !!float "-.Inf"\nf2: !!float "+.INF"\nf3: !!float ".NaN"\nf4: !!float ".nan"\nf5: !!float "1_000.5"\nf6: !!float "1e5"\nf7: !!float "+1.5E-3"\nf8: !!float "5"\nf9: !!float "."\nf10: !!float "1e"\nf11: !!float "1.e3"\nf12: !!float ".5e-2"\nf13: !!float "1__0"\nf14: !!float "abc"\nf15: !!float "0x1F"\nf16: !!float "-0"\nf17: !!float "1.5.5"\nf18: !!float \'12\'\ni0: !!int ".inf"\ni1: !!int "-.Inf"\ni2: !!int "+.INF"\ni3: !!int ".NaN"\ni4: !!int ".nan"\ni5: !!int "1_000.5"\ni6: !!int "1e5"\ni7: !!int "+1.5E-3"\ni8: !!int "5"\ni9: !!int "."\ni10: !!int "1e"\ni11: !!int "1.e3"\ni12: !!int ".5e-2"\ni13: !!int "1__0"\ni14: !!int "abc"\ni15: !!int "0x1F"\ni16: !!int "-0"\ni17: !!int "1.5.5"\ni18: !!int \'12\'\n',
    'flow_tagged_number_spellings': 'f: [!!float ".inf", !!float "-.Inf", !!float "+.INF", !!float ".NaN", !!float ".nan", !!float "1_000.5", !!float "1e5", !!float "+1.5E-3", !!float "5", !!float ".", !!float "1e", !!float "1.e3", !!float ".5e-2", !!float "1__0", !!float "abc", !!float "0x1F", !!float "-0", !!float "1.5.5", !!float \'12\']\n',
    'flow_control_character_strings': 'g: [ "a\\x01b" , "c\\ufeffd" , "e\\x85f" , "tab\\tx" , "\\u2028" ]\nh: [ x ]\n',

    'implicit_core': 'f: [ True , FALSE , Null , ~ , NULL , true ]\n',
    'implicit_core_mapping': 'm: { a : True , b : NULL , c : ~ }\n',
    'explicit_quoted_core': 'f: [ !!bool "TRUE" , !!int "42" , !!null "~" , !!float "1.5" , !!str "yes" ]\n',
    'explicit_single_quoted_core': "f: [ !!bool 'False' , !!int '-7' , !!null 'Null' , !!float '.5' ]\n",
    'explicit_escaped_core': 'f: [ !!bool "\\x54RUE" , !!int "\\x34\\x32" , !!null "\\u007e" ]\n',
    'explicit_invalid_core': 'f: [ !!bool "maybe" , !!int "4.2" , !!null "none" , !!float "abc" ]\n',
    'explicit_nonascii_core': 'f: [ !!bool "trüe" , !!int "４２" ]\n',
    'explicit_long_core': 'f: [ !!int "1111111111111111111111111111111111111111111111111111111111111111111111" , x ]\n',
    'tag_anchor_orders': 'f: [ !t &a x , &b !u y , !v z , &c w ]\n',
    'tag_anchor_orders_wide': 'f: [ !tagname &anchor1 value_one , &anchor2 !tagname value_two , !onlytag v3 , &onlyanchor v4 ]\n',
    'anchored_core': 'f: [ &a True , &b ~ , !!str &c 1 ]\n',
    'quoted_core_strings': 'f: [ \'true\' , "null" , \'1.5\' , "~" ]\n',
    'block_explicit_core': 'a: !!bool "TRUE"\nb: !!int \'42\'\nc: !!null "~"\nd: !!float "1.5"\ne: !!str yes\nf: !!bool maybe\n',
    'block_explicit_core_compact': 'list:\n  - !!bool "TRUE"\n  - !!int \'42\'\n  - !!null "~"\n  - !!float "1.5"\n',
    'wide_flow_core': 'f: [!!bool "TRUE", !!bool "TRUE", !!bool "TRUE", !!bool "TRUE", !!bool "TRUE", !!bool "TRUE", !!bool "TRUE", !!bool "TRUE"]\n',
    'wide_flow_tagged': 'f: [!t &a0 val, !t &a1 val, !t &a2 val, !t &a3 val, !t &a4 val, !t &a5 val, !t &a6 val, !t &a7 val]\n',
}

MODES = {"default": [], "compact": ["--compact"], "narrow": ["--line-width", "30"], "verify": ["--verify"]}


@pytest.mark.parametrize("mode", sorted(MODES))
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_core_scalar_rendering(name, mode, run, workdir, golden):
    """CATCHES: wrong YAML 1.2 spelling normalisation (True->true, NULL->null, `~` kept),
    unquoting tagged values whose content is not a valid core value, reordering tag and
    anchor, or a width computation that expands/keeps flow collections differently."""
    observed = format_both_ways(run, workdir, "doc.yaml", DOCUMENTS[name], *MODES[mode])
    assert observed == golden(f"{name}__{mode}")
