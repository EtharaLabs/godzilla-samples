"""Behavioural tests for lumen's from-scratch RegExp engine and the RegExp builtins.

Covers pattern syntax (Annex B leniency and every early error the parser reports), character
classes and escapes, Unicode property escapes, `v`-flag class set expressions and properties of
strings, case folding in legacy and Unicode modes, named/duplicate groups, backreferences,
lookarounds, greedy/lazy quantifiers and the empty-iteration rule, inline modifiers, the `d`/`y`/
`s`/`m`/`u` flags, the generic RegExp.prototype[Symbol.*] algorithms driven by custom `exec`
results, String.prototype integrations, RegExp construction/compile/escape and the legacy
`RegExp.$1` statics (including the dead-result fast paths in hot JIT code).
"""

import pytest

from conftest import err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# Shared JS helpers: `ex` renders an exec result (undefined captures as null), `tryre` reports a
# construction error message.
EXEC_HELPERS = r"""
function ex(re, s) {
  var m = re.exec(s);
  if (!m) return 'null';
  var r = JSON.stringify(Array.from(m, function (x) { return x === undefined ? null : x; })) + '@' + m.index;
  if (m.groups) r += ' groups=' + JSON.stringify(m.groups, function (k, v) { return v === undefined ? '<undef>' : v; });
  return r;
}
function row(re, s) { return String(re).padEnd(34) + ' ' + JSON.stringify(s).padEnd(16) + ' ' + ex(re, s); }
function all(re, s) { var m = s.match(re); return m ? m.join('|') : 'null'; }
"""


def test_flag_group_and_quantifier_syntax_errors(js, golden):
    """CATCHES: a RegExp parser that accepts duplicate/unknown/conflicting flags, unbalanced groups,
    unknown group kinds, malformed inline modifiers, duplicate group names in one alternative,
    dangling quantifiers or oversized repeat counts, or reports them with different messages."""
    code = r"""
var cases = [
  ['a', 'gig'], ['a', 'z'], ['a', 'uv'], ['a)', ''], ['(?:a', ''], ['(a', ''], ['\\k<nope>(?<x>a)', ''],
  ['(?<x>a)(?<x>b)', ''], ['(?<x>a)|(?<x>b)(?<x>c)', ''], ['(?:(?<x>a)|b)(?<x>c)', ''], ['(?<x>a)|(?<x>b)', ''],
  ['(a)\\2', 'u'], ['(?<a>.)\\k<b>', 'u'], ['*a', ''], ['a**', ''], ['a+*', ''], ['{2}', ''], ['|?', ''], ['(*)', ''],
  ['a{3,2}', ''], ['a{', 'u'], ['}', 'u'], [']', 'u'], ['(?x)', ''], ['(?', ''], ['(?ii:a)', ''], ['(?i-x:a)', ''],
  ['(?i', ''], ['(?-:a)', ''], ['(?i-i:a)', ''], ['(?m-sm:a)', ''], ['(?s-s:a)', ''], ['(?<=a)*', ''], ['(?<!a)?', ''],
  ['(?=a)+', 'u'], ['(?!a){2}', 'u'], ['(?:ab){1001}', ''], ['(ab){2,1001}', ''], ['x{1001}', ''], ['\\', ''], ['[a-', ''], ['(?<a>(?<a>x))', ''], ['(?<a>x)(?i:(?<a>y))', ''],
];
for (var k = 0; k < cases.length; k++) {
  var c = cases[k];
  try { var re = new RegExp(c[0], c[1]); console.log(JSON.stringify(c[0]) + '/' + c[1] + ' ok ' + re.source + ' ' + re.flags); }
  catch (e) { console.log(JSON.stringify(c[0]) + '/' + c[1] + ' ' + e.name + ': ' + e.message); }
}
['/a**/', '/(?<n>a)\\k<m>/', 'x = /[b-a]/;', '/a/gg', '/(?<=x)+/', '/a{2,1}/u'].forEach(function (src) {
  try { eval(src); console.log(src, 'ok'); } catch (e) { console.log('eval ' + src + ' ' + e.name + ': ' + e.message); }
});
"""
    r = js(code)
    assert out(r) == golden("flag_group_and_quantifier_syntax_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_escape_and_class_syntax_errors(js, golden):
    """CATCHES: a parser whose Unicode-mode identity-escape, hex/code-point escape, \\c, octal,
    property-escape, capture-group-name or v-mode ClassSetExpression validation is missing or
    wrong (e.g. accepting `[a&&b c]`, `[(]` or `\\P{RGI_Emoji}`), or whose error text differs."""
    code = r"""
var cases = [
  ['[a&&&b]', 'v'], ['[ab&&c]', 'v'], ['[a--b--]', 'v'], ['[ab--c]', 'v'], ['[a-\\d]', 'v'], ['[z-a]', 'v'], ['[abc', 'v'], ['[', 'v'],
  ['[\\qabc]', 'v'], ['[\\q{abc', 'v'], ['[(]', 'v'], ['[)]', 'v'], ['[{]', 'v'], ['[/]', 'v'], ['[|]', 'v'], ['[a-]', 'v'],
  ['[&&a]', 'v'], ['[a!!b]', 'v'], ['[##]', 'v'], ['[\\', 'v'], ['[\\c1]', 'v'], ['[\\z]', 'v'], ['[\\xZZ]', 'v'], ['[\\u{110000}]', 'v'],
  ['[\\pL]', 'v'], ['[\\p{L!}]', 'v'], ['[\\p{L', 'v'], ['\\P{RGI_Emoji}', 'v'], ['[^\\p{Emoji_Keycap_Sequence}]', 'v'],
  ['[\\p{Nope}]', 'v'], ['[^\\q{ab}]', 'v'], ['[^[\\q{xy}a]]', 'v'],
  ['[z-a]', ''], ['[a', ''], ['[\\d-z]', 'u'], ['[a-\\p{L}]', 'u'], ['[\\01]', 'u'], ['[\\c1]', 'u'], ['[\\z]', 'u'], ['[\\', ''],
  ['[\\x4]', 'u'], ['[\\u12]', 'u'], ['\\01', 'u'], ['\\c1', 'u'], ['\\c', 'u'], ['\\k', 'u'], ['\\k<a', 'u'], ['\\k<1>', 'u'],
  ['\\z', 'u'], ['\\-', 'u'], ['\\xZ', 'u'], ['\\u{110000}', 'u'], ['\\u{}', 'u'], ['\\u{12x}', 'u'], ['\\u12', 'u'], ['\\uD83D\\u12', 'u'], ['\\uD83D\\u', 'u'],
  ['(?<a\\x41>b)', ''], ['(?<1a>b)', ''], ['(?<ab', ''], ['(?<>b)', ''], ['(?<a-b>c)', ''], ['(?<a\\u0020>c)', ''],
  ['\\p', 'u'], ['\\p{', 'u'], ['\\pL', 'u'], ['\\p{Script=Nope}', 'u'], ['\\p{ L }', 'u'], ['\\p{Lowercase_Letter=x}', 'u'],
  ['\\p{letter}', 'u'], ['\\p{gc=lu}', 'u'], ['\\p{IsGreek}', 'u'], ['\\p{General_Category}', 'u'], ['\\p{Script}', 'u'],
  ['\\p{=L}', 'u'], ['\\p{L=}', 'u'], ['\\p{RGI_Emoji}', 'u'], ['\\P{Basic_Emoji}', 'v'],
];
for (var k = 0; k < cases.length; k++) {
  var c = cases[k];
  try { var re = new RegExp(c[0], c[1]); console.log(JSON.stringify(c[0]) + '/' + c[1] + ' ok ' + re.source); }
  catch (e) { console.log(JSON.stringify(c[0]) + '/' + c[1] + ' ' + e.name + ': ' + e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("escape_and_class_syntax_errors")
    assert (r.returncode, r.stderr) == (0, b"")


def test_invalid_regex_literal_is_an_early_error(js, run):
    """CATCHES: an engine that compiles regex literals lazily (running code before reporting the
    error, or never reporting it for an uncalled function) instead of rejecting the whole script
    with an early SyntaxError and exit status 1."""
    code = r"""console.log("before");
function never() { return /(?<a>x)(?<a>y)/; }
console.log("after");
"""
    r = js(code)
    assert (r.returncode, out(r), err(r)) == (1, "", "Uncaught SyntaxError: duplicate group name a\n")
    r2 = run(["-e", "var ok = 1;\nvar r = /[\\d-z]/u;"])
    assert (r2.returncode, out(r2), err(r2)) == (1, "", "SyntaxError: invalid character class range (line 2)\n")


def test_annex_b_lenient_escapes(js, golden):
    """CATCHES: a non-Unicode parser that rejects Annex B patterns (`\\k` without named groups,
    `\\8`, lone `{`/`]`, `\\c` without a letter, `\\u{12}` as a quantified `u`, legacy octal escapes
    and decimal escapes above the group count) or decodes them to the wrong characters."""
    code = EXEC_HELPERS + r"""
var R = [
  [/\k/, 'ak'], [/\8\9/, '89'], [/{/, 'a{'], [/a{,2}/, 'a{,2}'], [/x{1/, 'x{1'], [/x{1,/, 'x{1,'], [/x{a}/, 'x{a}'], [/\c/, 'a\\c'],
  [/[\c]/, 'c'], [/[\c]/, '\\'], [/\u{3}/, 'uuu'], [/\x4/, 'x4'], [/\xg1/, 'xg1'], [/\u12/, 'u12'], [/(?=a)*/, 'b'], [/(?=a){2}b/, 'ab'], [/]/, ']'], [/}/, '}'],
  [/\p{L}/, 'p{L}'], [/[\p{L}]/, '{'], [/\q/, 'q'], [/\-/, '-'], [/[\c_]/, '\x1f'], [/[\c1]/, '\x11'], [/\0123/, '\n3'], [/[\0123]/, '3'],
  [/\567/, '.7'], [/[\-]/, '-'], [/\cJ/, '\n'], [/[\cj]/, '\n'], [/\c1/, '\\c1'], [/\0/, 'a\0'], [/[\0]/, '\0'], [/[\08]/, '8'], [/[\07]/, '\x07'],
  [/[\1]/, '\x01'], [/[\8]/, '8'], [/[\9a]/, 'a'], [/[\47]/, "'"], [/[\377]/, '\xff'], [/[\400]/, ' 0'],
  [/(a)\1\2/, 'aa\x02'], [/(a)\10/, 'a\b'], [/\11(a)/, '\ta'], [/\18(a)/, '8a'], [/[\b]/, '\b'], [/\x41B/, 'AB'], [/\u0041\u{41}/, 'Au{41}'],
  [/\uD83D\uDE00/, '\u{1F600}'], [/\uD83D/, '\u{1F600}'], [/^.$/, '\u{1F600}'], [/^..$/, '\u{1F600}'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
"""
    r = js(code)
    assert out(r) == golden("annex_b_lenient_escapes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_character_class_escapes_and_ranges(js, golden):
    """CATCHES: wrong membership for \\d\\w\\s and their negations (JS whitespace includes U+FEFF and
    NBSP but not U+0085), mishandled control escapes and \\x/\\u forms inside classes, class escapes
    used as range bounds in legacy mode, empty `[]`/`[^]`, or \\b/\\B boundary logic."""
    code = EXEC_HELPERS + r"""
var R = [
  [/\d\D\w\W\s\S/, '1a_ \tx'], [/[\d\s]+/, 'ab1 2\u3000c'], [/[\D]/, '12a'], [/[\W\d]/, 'ab_9'], [/[\S]/, ' \ufeffz'],
  [/\s/, '\u0085'], [/\s+/, '\u00a0\u1680\u2000\u200a\u2028\u2029\u202f\u205f\u3000\ufeff!'], [/[\s]/, '\u180e'], [/\S/u, '\u{1F600}'],
  [/[\n\r\t\f\v]+/, 'a\n\r\t\f\vb'], [/\t\r\f\v/, '\t\r\f\v'], [/[\x41-\x43]+/, 'ABCD'], [/[\x41-\x43]+/u, 'ABCD'], [/[\u0061-\u0063]+/, 'abcd'],
  [/[\u{61}-\u{63}]+/u, 'abcd'], [/[\u{1F600}-\u{1F602}]/u, 'x\u{1F601}'], [/[\uD83D\uDE00]/u, '\u{1F600}'], [/[\uD83D\uDE00]/, '\u{1F600}'],
  [/\uD83D\uDE00/u, '\u{1F600}'], [/\uD83D\u0041/u, '\uD83DA'], [/\uD83D/u, '\u{1F600}'], [/\uDE00/u, '\uDE00'], [/^[^a]$/u, '\u{1F600}'],
  [/\0/u, '\0'], [/[\0]/u, '\0'], [/[\/\-]+/u, '/-'], [/\//, 'a/b'], [/[\cA-\cC]+/, '\x01\x02\x03'], [/[\b-\n]+/, '\b\t\n'],
  [/a|/, 'b'], [/|a/, 'a'], [/[]/, 'a'], [/[^]/, '\n'], [/[^]+/u, '\u{1F600}\n'], [/[]?x/, 'x'],
  [/\bfoo\b/, 'a foo.'], [/\Boo\B/, 'foods'], [/\b/, '   '], [/\B/, ''], [/^\b$/, ''], [/\b\w+$/, 'one two'], [/\B\w+/, 'one'],
  [/[a-c-e]/, '-'], [/[\w-z]/, '-'], [/[%-\d]/, '-'], [/[\s-\d]/, '5'], [/[\d-]/, '-'], [/[-a]/, '-'], [/[a-]/, '-'], [/[\--\/]+/, '-./'],
  [/[^\d\s]+/, '12 ab 3'], [/[^\W]+/, '..ab_1..'], [/[.]/, 'a.'], [/[$^]+/, 'x^$'], [/[\]]/, ']'], [/[\[]/, '['], [/[a\]b]+/, 'a]b'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
"""
    r = js(code)
    assert out(r) == golden("character_class_escapes_and_ranges")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unicode_property_escapes(js, golden):
    """CATCHES: \\p{...}/\\P{...} support with wrong General_Category, Script, Script_Extensions or
    binary-property tables, broken negation inside classes, missing case-insensitive closure, or
    treating \\p literally in Unicode mode / as a property without the u flag."""
    code = r"""
function all(re, s) { return JSON.stringify((s.match(re) || []).join('|')); }
var sample = 'aZ9_ \u03b1\u03a9 \u0416\u0436 \u0663 \u4e2d\u6587 \u3072\u3089 \u30ab\u30bf \u{1F600} \ufb01 \u216b \u203f \u2028 \u00a0x\u0301 \u00a2 \u00bd \u02b0 \u{10400}';
['\\p{L}', '\\p{Lu}', '\\p{Ll}', '\\p{Letter}', '\\p{Uppercase_Letter}', '\\p{gc=Nd}', '\\p{General_Category=Number}', '\\p{N}', '\\P{L}',
 '\\p{Script=Greek}', '\\p{sc=Cyrl}', '\\p{Script=Latin}', '\\p{Script_Extensions=Hira}', '\\p{scx=Kana}', '\\p{sc=Han}', '\\p{Alphabetic}',
 '\\p{White_Space}', '\\p{Emoji_Presentation}', '\\p{ASCII}', '\\p{ASCII_Hex_Digit}', '\\p{Any}', '\\P{Any}', '\\p{Assigned}', '\\p{Mn}',
 '\\p{Sc}', '\\p{Lm}', '\\p{Pc}', '\\p{Nl}', '\\p{No}', '\\p{Zs}', '\\p{Zl}', '\\p{Uppercase}', '\\p{Lowercase}', '\\p{ID_Start}',
 '\\p{ID_Continue}', '[\\p{L}\\d]', '[^\\p{L}\\s]', '[\\p{Lu}\\p{Nd}]', '[^\\P{Lu}]', '\\p{Ideographic}', '\\p{Extended_Pictographic}',
 '\\p{Diacritic}', '\\p{Script=Deseret}', '\\P{ASCII}'].forEach(function (p) {
  console.log(p.padEnd(30) + ' ' + all(new RegExp(p, 'gu'), sample));
});
console.log('iu closure:', /\p{Lu}/iu.test('a'), /\P{Lu}/iu.test('A'), /[^\P{Lu}]/iu.test('a'), /\p{Lowercase}/iu.test('Q'), /\p{Ll}/iu.test('\u{10400}'));
console.log('without u, \\p is literal:', /\p{L}/.test('p{L}'), /[\p{L}]/.test('{'), /\P{L}/.test('a'));
console.log('astral in class', /^[\p{Script=Deseret}a]+$/u.test('a\u{10400}\u{10428}'), /^[^\p{Script=Deseret}]$/u.test('\u{10400}'));
"""
    r = js(code)
    assert out(r) == golden("unicode_property_escapes")
    assert (r.returncode, r.stderr) == (0, b"")


def test_unicode_sets_v_flag_operations(js, golden):
    """CATCHES: a v-flag implementation whose intersection (&&), subtraction (--), nested and
    negated nested classes, \\q{...} string literals (longest string first), escapes inside class
    sets or v-mode \\d\\s\\w operands compute the wrong set."""
    code = r"""
function all(re, s) { var m = s.match(re); return m ? JSON.stringify(m.join('|')) : 'null'; }
var s = 'abcxyz0129 \u0391\u0392\u03b3\u03b4_-';
console.log('intersect', all(/[\w&&[a-f]]/gv, s), all(/[\p{L}&&\p{Script=Greek}&&\p{Lu}]/gv, s), all(/[[a-z]&&[^aeiou]]/gv, s), all(/[\d&&[^0-1]&&[^9]]/gv, s));
console.log('subtract', all(/[\w--\d]/gv, s), all(/[\p{L}--[a-z]--[\u0391-\u03a9]]/gv, s), all(/[[0-9]--[1-8]]/gv, s), all(/[\w--_--[x-z]]/gv, s));
console.log('nested', all(/[[a-c][x-z]\d]/gv, s), all(/[^[a-y][0-8]]/gv, s), all(/[a-c[^\s\w]]/gv, s), all(/[[[a]b]c]/gv, s), all(/[[^\W]&&[^\d]]/gv, '1a_.'));
console.log('empty', all(/[]/gv, 'ab'), all(/[^]/gv, 'ab'), all(/[[]a]/gv, 'ab'), all(/[a&&[]]/gv, 'a'));
console.log('escapes', all(/[\-\&\!\#\%\,\:\;\<\=\>\@\`\~]/gv, 'a-&!#%,:;<=>@`~b'), all(/[\(\)\[\]\{\}\/\|\\\^\$\.\*\+\?]+/gv, '()[]{}/|\\^$.*+?'), all(/[\cJ\t\0\n\r\f\v\b]/gv, '\n\t\0\r\f\v\b'));
console.log('code points', all(/[\x41\u0042\u{43}\u{1F600}\u{1F601}]/gv, 'ABC\u{1F600}\u{1F601}'), all(/[\uD83D\uDE00]/gv, '\u{1F600}'), all(/[[\u{1F600}-\u{1F602}]--\u{1F601}]/gv, '\u{1F600}\u{1F601}\u{1F602}'));
console.log('q strings', all(/[\q{abc|x}z]/gv, 'abcxz'), all(/[\q{a|ab|abc}]/gv, 'abcab a'), /^[\q{abc|ab}d]+$/v.test('abcabd'), all(/[\q{A\x42|\n|\u{1F600}x}]/gv, 'AB\n\u{1F600}x'));
console.log('q set ops', all(/[\q{ab|cd|e}--\q{cd}]/gv, 'abcde'), all(/[\q{ab|cd}&&\q{cd|ef}]/gv, 'abcdef'), all(/[[\q{ab}x]--x]/gv, 'abx'), all(/[\q{\|\}}]/gv, '|}'), /[\q{}]/v.exec('x')[0] === '', /^[\q{}]$/v.test(''));
console.log('v classes', all(/[\D&&[a-c]]/gv, 'a1b'), all(/[\s--[\n]]/gv, ' \n\t'), all(/[\S&&\d]/gv, 'x5'), all(/[\W&&[!-#]]/gv, '!a#'), all(/[\w&&\W]/gv, 'a!'));
console.log('v icase', all(/[\q{AB}a-c]/giv, 'ab C'), /[\p{Lu}--[A-Z]]/iv.test('a'), /[[a-z]&&[^x]]/iv.test('X'), all(/\p{Ll}/giv, 'aB'));
console.log('v dot and astral', all(/./gv, '\u{1F600}a'), '\u{1F600}'.match(/[^a]/v)[0].length, all(/[\p{L}--\p{Ll}]/gv, 'aBc'), all(/\P{Ll}/gv, 'aB1'));
console.log('v source/flags', /[a&&b]/v.source, /x/v.flags, /x/v.unicodeSets, /x/u.unicodeSets, /x/v.unicode, new RegExp('[\\q{a}]', 'vg').flags);
"""
    r = js(code)
    assert out(r) == golden("unicode_sets_v_flag_operations")
    assert (r.returncode, r.stderr) == (0, b"")


def test_v_flag_properties_of_strings(js, golden):
    """CATCHES: missing or wrong Unicode properties of strings in v mode (keycaps, flags, modifier,
    ZWJ and tag sequences, Basic_Emoji) such as matching only the first code point of a sequence,
    or breaking set operations that combine string sets with \\q{...}."""
    code = r"""
var text = '1\ufe0f\u20e3 #\ufe0f\u20e3 \u{1F1EB}\u{1F1F7} \u{1F44D}\u{1F3FD} \u{1F469}\u200d\u{1F4BB} \u00a9\ufe0f \u{1F600} \u231a \u{1F3F4}\u{E0067}\u{E0062}\u{E0077}\u{E006C}\u{E0073}\u{E007F} x';
['Emoji_Keycap_Sequence', 'RGI_Emoji_Flag_Sequence', 'RGI_Emoji_Modifier_Sequence', 'RGI_Emoji_ZWJ_Sequence', 'RGI_Emoji_Tag_Sequence'].forEach(function (p) {
  var m = text.match(new RegExp('\\p{' + p + '}', 'gv'));
  console.log(p, JSON.stringify(m), m ? m.map(function (x) { return x.length; }).join() : '');
});
console.log('Basic_Emoji', JSON.stringify('\u{1F600} \u00a9\ufe0f \u231a x \u00a9'.match(/\p{Basic_Emoji}/gv)));
console.log('anchored sequence', /^\p{RGI_Emoji_Flag_Sequence}$/v.test('\u{1F1EB}\u{1F1F7}'), /^\p{RGI_Emoji_Flag_Sequence}$/v.test('\u{1F1EB}'), /^\p{Emoji_Keycap_Sequence}$/v.test('1\u20e3'));
console.log('in class with other members', JSON.stringify('a#\ufe0f\u20e3b'.match(/[\p{Emoji_Keycap_Sequence}a]/gv)));
console.log('subtract strings', JSON.stringify('\u{1F1EB}\u{1F1F7}\u{1F1E9}\u{1F1EA}'.match(/[\p{RGI_Emoji_Flag_Sequence}--\q{\u{1F1EB}\u{1F1F7}}]/gv)));
console.log('intersect strings', JSON.stringify('1\ufe0f\u20e32\ufe0f\u20e3'.match(/[\p{Emoji_Keycap_Sequence}&&\q{1\ufe0f\u20e3|x}]/gv)));
console.log('modifier count', (' \u{1F44B}\u{1F3FB} \u{1F44B}\u{1F3FF} \u{1F44B} '.match(/\p{RGI_Emoji_Modifier_Sequence}/gv) || []).length);
"""
    r = js(code)
    assert out(r) == golden("v_flag_properties_of_strings")
    assert (r.returncode, r.stderr) == (0, b"")


def test_case_insensitive_folding_legacy_vs_unicode(js, golden):
    """CATCHES: case-insensitive matching that folds non-ASCII onto ASCII without the u flag
    (U+017F/U+212A matching s/k), lacks simple case folding with u (sharp s, sigma, Deseret), or
    ignores the iu word-character rule for \\w, \\W and \\b."""
    code = r"""
function t(re, s) { return re.test(s) ? 'T' : 'F'; }
var rows = [
  ['long s vs s', [/s/i, /s/iu, /\u017f/i, /\u017f/iu, /[a-z]/i, /[a-z]/iu, /\w/i, /\w/iu, /\W/iu, /[^\W]/iu, /[\W]/iu], '\u017f'],
  ['kelvin vs k', [/k/i, /k/iu, /K/i, /K/iu, /[k]/i, /[^k]/iu, /\bK\b/iu, /[a-z]/iu], '\u212a'],
  ['k vs kelvin', [/\u212a/i, /\u212a/iu, /[\u212a]/i, /[\u212a]/iu, /[\u2100-\u2130]/i, /[\u2100-\u2130]/iu], 'k'],
  ['sharp s', [/\u00df/i, /\u00df/iu, /\u1e9e/i, /\u1e9e/iu, /[\u00df]/iu, /ss/iu], '\u1e9e'],
  ['sigma', [/\u03c3/i, /\u03c2/i, /\u03a3/i, /\u03c3/iu, /\u03c2/iu, /[\u03c3]/i, /[\u03c2]/iu], '\u03a3'],
  ['final sigma', [/\u03a3/i, /\u03c3/i, /\u03a3/iu, /[\u03a3]/i], '\u03c2'],
  ['dotless i', [/i/i, /I/i, /i/iu, /I/iu, /\u0131/i, /\u0130/i, /\u0130/iu], '\u0131'],
  ['dotted I', [/i/i, /i/iu, /\u0130/i, /\u0130/iu, /\u0131/iu], '\u0130'],
  ['micro sign', [/\u00b5/i, /\u03bc/i, /\u00b5/iu, /\u03bc/iu, /[\u00b5]/iu], '\u039c'],
  ['ohm sign', [/\u03c9/i, /\u03a9/i, /\u03c9/iu, /[\u03c9]/iu, /\u2126/i], '\u2126'],
  ['deseret', [/\u{10400}/iu, /\u{10428}/iu, /[\u{10400}-\u{10410}]/iu, /\u{10400}/i, /^.$/iu, /^[^\u{10400}]$/iu], '\u{10428}'],
  ['latin-1', [/\u00e9/i, /[\u00e0-\u00ff]/i, /\u00ff/i, /\u0178/i, /\u0178/iu], '\u00c9'],
  ['backref fold', [/(a)\1/i, /(s)\1/iu, /(s)\1/i, /(?<x>s)\k<x>/iu, /(K)\1/i, /(k)\1/iu], 'a\u0041 s\u017f k\u212a'],
  ['boundary iu', [/\b\u017f/iu, /a\b/iu, /\B\u017f/iu, /a\b/i, /\w\b/i], 'a\u017f'],
];
rows.forEach(function (r) { console.log(r[0].padEnd(14), r[1].map(function (re) { return String(re) + '=' + t(re, r[2]); }).join(' ')); });
console.log('global icase replace', 'xXxX'.replace(/x/gi, '_'), '\u00c0\u00e0\u00c1\u00e1'.replace(/\u00e0/gi, '.'), '\u212akK'.replace(/k/giu, '#'), '\u212akK'.replace(/k/gi, '#'));
console.log('first-char prescan with i', /QZ/i.exec('aaaaqz').index, /[q-r]z/i.exec('aaaaRz').index, /\u212az/iu.exec('aakZ').index, /\u017ft/iu.exec('aaST').index, /\u00e9t\u00e9/i.exec('L\u2019\u00c9T\u00c9').index);
"""
    r = js(code)
    assert out(r) == golden("case_insensitive_folding_legacy_vs_unicode")
    assert (r.returncode, r.stderr) == (0, b"")


def test_named_groups_and_duplicate_names(js, golden):
    """CATCHES: named capture groups with wrong `groups` objects, duplicate names across alternatives
    that report the unmatched copy, \\k<name> resolving to the wrong duplicate, or group names
    written with \\u escapes / surrogate pairs / astral identifier characters being rejected."""
    code = EXEC_HELPERS + r"""
var R = [
  [/(?<year>\d{4})-(?<month>\d\d)(?:-(?<day>\d\d))?/, 'on 2024-07 ok'],
  [/(?<a>x)|(?<a>y)/, 'y'], [/(?:(?<a>x)|(?<a>y))\k<a>/, 'yy'], [/(?:(?<a>x)|(?<a>y))\k<a>/, 'yx'], [/(?:(?<a>x)|(?<a>y))\k<a>/, 'xx'],
  [/(?:(?<n>a)|(?<n>b))+/, 'ab'], [/(?:(?<n>a)|(?<n>b))\k<n>{2}/i, 'bBb'], [/(?<=(?:(?<d>1)|(?<d>2))\k<d>)x/, '22x'],
  [/(?:(?<n>a)|(?<n>b))?\k<n>c/, 'c'], [/(?<ab>c)\k<ab>/, 'cc'], [/\k<a>(?<a>b)/, 'b'],
  [/(?<\u{1d453}>z)/u, 'z'], [/(?<\ud835\udc53>z)/, 'z'], [/(?<\ud835\udc53>z)/u, 'z'], [/(?<\u0061\u0062>z)/, 'z'], [/(?<\u{62}c>z)/, 'z'],
  [/(?<\u{1d453}>z)/, 'z'], [new RegExp('(?<\ud835\udc53>z)'), 'z'], [/(?<$_\u03b6\u200d>.)/, '!'],
  [/(?<a>.)(?<b>.)(?<c>.)(?<d>.)(?<e>.)/, 'vwxyz'], [/(?<=\k<d>(?:(?<d>ab)|(?<d>c)))x/, 'abx'], [/(?<=\k<d>(?:(?<d>ab)|(?<d>c)))x/, 'ccx'],
  [/(?<=\k<d>(?:(?<d>ab)|(?<d>c)))x/, 'ababx'], [/(?i:(?<n>a))\k<n>/, 'Aa AA'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
var m = /(?<first>\w+) (?<last>\w+)/.exec('Ada Lovelace');
console.log(Object.getPrototypeOf(m.groups) === null, Object.keys(m.groups).join(), 'Ada Lovelace'.replace(/(?<first>\w+) (?<last>\w+)/, '$<last>, $<first>'));
console.log(JSON.stringify('x1y2'.replace(/(?<d>\d)|(?<d>[xy])/g, function () { var g = arguments[arguments.length - 1]; return '[' + g.d + ']'; })));
['(?<\ud800>a)', '(?<\\ud835x>z)', '(?<\\ud835\\u0041>z)', '(?<a\\u{110000}>z)', '(?<\\u0x>a)'].forEach(function (p) { try { new RegExp(p); console.log('ok', p); } catch (e) { console.log(e.name + ': ' + e.message.length + ' ' + e.message.slice(0, 26)); } });
"""
    r = js(code)
    assert out(r) == golden("named_groups_and_duplicate_names")
    assert (r.returncode, r.stderr) == (0, b"")


def test_backreferences_forward_unset_and_case(js, golden):
    """CATCHES: backreferences that fail instead of matching empty when the group is unset or is a
    forward reference, that do not reset per quantifier iteration, compare case-sensitively under
    /i, or mis-handle more than nine groups (\\10)."""
    code = EXEC_HELPERS + r"""
var R = [
  [/(a)|\1b/, 'b'], [/\1(a)/, 'a'], [/(a)?\1b/, 'b'], [/(?:(a)|b)\1c/, 'bc'], [/(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)\10/, 'abcdefghijj'],
  [/(\w)\1{2}/, 'abbbc'], [/(?<w>\w)\k<w>+/u, 'xyyyz'], [/(a)\1/i, 'aA'], [/(\u00e9)\1/i, '\u00e9\u00c9'], [/(.)\1/u, '\u{1F600}\u{1F600}'],
  [/(?:(a)|b)*\1/, 'aba'], [/(?:(a)|(b))+\1\2/, 'abb'], [/(a*)b\1/, 'aabaa'], [/(a*)b\1/, 'aaba'], [/^(?:(a)|b)(?:\1|c)$/, 'bc'],
  [/(?=(\w+))\1:/, 'abc:'], [/(\d+)\s\1/, '12 123'], [/((a)\2)+/, 'aaaa'], [/(x)(?:\1|y)+/, 'xxyx'], [/\2(a)(b)/, 'ab'],
  [/(?<=\1(a))b/, 'aab'], [/(?<=(a)\1)b/, 'aab'], [/(?<=(\w)\1)c/, 'xxc'], [/(?<!(a)\1)b/, 'aab ab'], [/(?<=(b)|a\1)c/, 'ac'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
"""
    r = js(code)
    assert out(r) == golden("backreferences_forward_unset_and_case")
    assert (r.returncode, r.stderr) == (0, b"")


def test_lookahead_and_lookbehind(js, golden):
    """CATCHES: lookarounds that leak or lose captures, a lookbehind that matches left-to-right
    instead of backwards (wrong greedy split of `(\\d+)(\\d+)`), nested lookahead inside lookbehind
    running in the wrong direction, or negative lookarounds keeping inner captures."""
    code = EXEC_HELPERS + r"""
var R = [
  [/(.*?)a(?!(a+)b\2c)\2(.*)/, 'baaabaac'], [/(?=(a+))a*b\1/, 'baaabac'], [/(?=(a+))/, 'baaabac'], [/(?!(a))b\1/, 'b'],
  [/a(?=b)/, 'acab'], [/a(?!b)/, 'abac'], [/(?=.*\d)(?=.*[a-z]).{4}/, 'ab1!'], [/(?=(\w))(?!\1\1)\w\w/, 'aabc'],
  [/(?<=(\d+)(\d+))$/, '1053'], [/(?<=\$)\d+(?:\.\d*)?/, 'cost $10.53'], [/(?<!\$)\b\d+/, '$10 20'], [/(?<=(a+)?)b/, 'aab'],
  [/(?<=(?=a)..)c/, 'xac'], [/(?<=(?=x).)c/, 'xc'], [/(?<=a(?<!b.)c)d/, 'acd bcd'], [/(?<=^|,)\w+/, 'a,b'], [/(?<=a|bc)d/, 'bcd'],
  [/(?<=(?:ab|b){2})c/, 'abbc'], [/(?<=a*?)b/, 'aab'], [/(?<=([ab])+)c/, 'abc'], [/(?<=([ab]+?))c/, 'abc'], [/(?<!a{2})b/, 'aab ab'],
  [/(?<=\b)x/, '.x'], [/(?<=\B)x/, 'ax'], [/(?<=(?i:A))b/, 'ab'], [/(?<=[^\d])\d/, '1a2'], [/(?<=.)/su, '\n'], [/(?<=^.)x/m, 'a\nbx'],
  [/(?<=\u{1F600})x/u, '\u{1F600}x'], [/(?<=\uDE00)x/, '\u{1F600}x'], [/(?<=.)x/u, '\u{1F600}x'], [/(?<=..)x/, '\u{1F600}x'],
  [/(?<=(?<n>\w)\d)z/, 'a1z'], [/(?<!(?<n>\w)\d)z/, 'a1z z'], [/(?<=$)/, 'ab'], [/(?<=a(?:b|c)?)d/, 'acd'], [/(?<=a.{2,3})x/, 'abcdx'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
console.log(JSON.stringify('a1b2c3'.match(/(?<=[a-z])\d/g)), JSON.stringify('ab12cd'.split(/(?<=\d)(?=[a-z])/)), '$1 \u20ac2 $3'.replace(/(?<=\$)\d/g, 'N'));
"""
    r = js(code)
    assert out(r) == golden("lookahead_and_lookbehind")
    assert (r.returncode, r.stderr) == (0, b"")


def test_quantifiers_greedy_lazy_and_empty_checks(js, golden):
    """CATCHES: quantifier bugs: wrong lazy/greedy preference for `{n,m}?`/`??`, captures not reset
    on each iteration (`/(z)((a+)?(b+)?(c))*/`), the empty-iteration rule (`/(a*)*/`, `/(?:a|)*b/`)
    looping or mis-capturing, or large single-character repeat counts being rejected."""
    code = EXEC_HELPERS + r"""
var R = [
  [/a{2,3}?/, 'aaaa'], [/a{2,}?b/, 'aaab'], [/a??b/, 'ab'], [/(a+?)(a*)/, 'aaa'], [/<(.+?)>/, '<a><b>'], [/<(.+)>/, '<a><b>'], [/x*?$/, 'xx'],
  [/\d{3,5}/, '12345678'], [/\d{3,5}?/, '12345678'], [/(?:ab){2}/, 'ababab'], [/(?:ab){2,}?/, 'ababab'], [/(ab|a){0,2}c/, 'abac'],
  [/(?:a{2}){2}/, 'aaaaa'], [/a{0}/, 'a'], [/(a){0}/, 'a'], [/a{1,1}b/, 'aab'], [/.{0,100000}/, 'abc'], [/a{2147483647,}/, 'aaa'],
  [/x{9007199254740991}/, 'x'], [/[a-c]{2,}?d/, 'abcabd'], [/(?:x|y){3}?/, 'xyxy'], [/(?:(?:a)|(?:b))*?c/, 'ababc'], [/(a|b)*?c/, 'abac'],
  [/(?:a*?)*?b/, 'aab'], [/(?:a?)+?b/, 'ab'], [/(a?)??b/, 'ab'], [/((a)|b)+/, 'ab'], [/(z)((a+)?(b+)?(c))*/, 'zaacbbbcac'],
  [/(a*)*/, 'b'], [/(a*)+/, 'b'], [/(?:a|)*b/, 'aab'], [/(a|ab)(c|bcd)(d*)/, 'abcd'], [/^(?:(a)|b)*$/, 'ab'], [/(a|b)*/, 'abab'],
  [/(?:(a)|b){2}/, 'ab'], [/(?:(a)|(b)){1,2}?c/, 'abc'], [/([ab]){3}/, 'abba'], [/(?:a(b)?)+/, 'aba'], [/(\d)*\d/, '123'], [/(?:()|a)+b/, 'aab'],
  [/a+b/, 'a'.repeat(5000) + 'b'], [/(?:ab)*c/, 'abababc'], [/(?:a|b){2,4}/, 'ababab'], [/\w{2}?\d/, 'ab1'], [/.?.??/, 'xy'],
];
R.forEach(function (r) { var line = row(r[0], r[1]); console.log(line.length > 200 ? line.slice(0, 60) + '...' + line.slice(-40) : line); });
"""
    r = js(code)
    assert out(r) == golden("quantifiers_greedy_lazy_and_empty_checks")
    assert (r.returncode, r.stderr) == (0, b"")


def test_lazy_quantifier_continuation_shortcuts(js, golden):
    """CATCHES: a lazy-quantifier optimisation that skips retry positions it cannot rule out: lazy
    runs followed by backreferences (numbered and duplicate-named), anchors, word boundaries,
    alternations, optional quantified groups or lookarounds must still find the leftmost match."""
    code = EXEC_HELPERS + r"""
var R = [
  [/.*?\d/, 'ab12'], [/.*?\b/, 'ab cd'], [/x.*?\b/, 'xab cd'], [/x.*?\B/, 'xab'], [/.*?(?=c)/, 'abc'], [/.*?(?!a)/, 'aab'], [/.+?\1(x)/, 'abx'],
  [/(['"]).*?\1/, 'say "hi" now'], [/(['"])[^]*?\1/, "a 'b\nc' d"], [/\w+?\s/, 'hello world'], [/[^,]*?,/, 'aa,b,'], [/a.*?$/m, 'ab\ncd'],
  [/a.*?^c/m, 'ab\ncd'], [/a[^]*?^c/m, 'ab\ncd'], [/a.*?^/, 'ab'], [/.*?c|b/, 'abc'], [/\s*?x/, '   x'], [/(?<q>['"]).*?\k<q>/, "x 'y' z"],
  [/(?:(?<q>')|(?<q>")).*?\k<q>/, 'a "b\'c" d'], [/(?:(?<q>')|(?<q>"))?.*?\k<q>z/, 'abz'], [/\w*?(?:,|$)/, 'ab'], [/a*?(?:b|c)/, 'aac'],
  [/a*?(?:b|c|)/, 'aa'], [/x.*?(?:(y)|z)/, 'x--z'], [/.*?(?:(a)b)*c/, 'zabc'], [/q.*?(?:ab)+/, 'q-abab'], [/.*?(?:x{0,2}y)/, 'axxy'],
  [/a.*?.b/, 'acxb'], [/a.*?\sb/, 'a c b'], [/a.*?[bc]/, 'axc'], [/a.*?\d+x/, 'a12x'], [/(a).*?\1/, 'abca'], [/(a)?.*?\1b/, 'xb'],
  [/a.*?(?:)b/, 'axb'], [/a.*?(?=b)b/, 'axb'], [/a.*?(?<=x)b/, 'axb'], [/a.*?(?i:B)/, 'axb'], [/a\s*?$/, 'a  '], [/^.*?$/, ''],
  [/a.*?(?:(?<n>)|(?<n>b))\k<n>c/, 'axc'], [/x.*?(?:|a)b/, 'xab'], [/x.*?(?:(?=a)|(?=b))./, 'x-b'], [/a.*?()\1b/, 'axb'], [/a.*?(){17}b/, 'axb'],
  [/(?:ab)*?c/, 'ababc'], [/a.*?(b)*c/, 'abbc'], [/(?:a|b)*?(?:\2|c)(.)?/, 'abc'], [/<.*?>$/, '<a><b>'], [/a.{0,3}?$/, 'abcd'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
[new RegExp('()'.repeat(128) + 'a.*?(b)c'), new RegExp('()'.repeat(128) + 'a.*?(?:(b))+c')].forEach(function (re) { var m = re.exec('--axbbc'); console.log('128 groups', m ? m.index + ' ' + m[0] + ' ' + m[129] + ' ' + m.length : 'null'); });
"""
    r = js(code)
    assert out(r) == golden("lazy_quantifier_continuation_shortcuts")
    assert (r.returncode, r.stderr) == (0, b"")


def test_inline_modifier_groups(js, golden):
    """CATCHES: `(?ims-ims:...)` modifier groups that leak their flags outside the group, ignore
    removal (`(?-i:...)` under /i), apply to backreferences outside the group, or are not honoured
    inside lookbehind bodies and quantified repetitions."""
    code = EXEC_HELPERS + r"""
var R = [
  [/(?i:a)b/, 'Ab'], [/(?i:a)b/, 'AB'], [/(?-i:a)b/i, 'aB'], [/(?-i:a)b/i, 'AB'], [/(?i:a(?-i:b)c)/, 'AbC'], [/(?i:a(?-i:b)c)/, 'ABC'],
  [/(?m:^b)/, 'a\nb'], [/^b/, 'a\nb'], [/(?-m:^b)/m, 'a\nb'], [/(?s:.)/, '\n'], [/(?-s:.)/s, '\n'], [/(?s-m:a.$)/m, 'a\n\nb'],
  [/(?ims:^A.b$)/, 'x\na\nB'], [/(?i:(\w))\1/, 'aA'], [/(?i:(\w)\1)/, 'aA'], [/(?i:\w)\b/u, '\u212a '], [/(?i:[a-z]+)\d/, 'ABC1'],
  [/(?i:k)/u, '\u212a'], [/(?i:k)/, '\u212a'], [/x(?i:y)*z/, 'xYyYz'], [/(?<=(?i:a)b)c/, 'Abc'], [/(?<=(?-i:a)b)c/i, 'ABC aBc'],
  [/(?i:a|b)c/, 'Bc'], [/(?i-s:.)x/s, '\nx Ax'], [/(?s:a.)|b./, 'b\n a\n'], [/(?m:$)\n/, 'a\nb'], [/(?i:\u00e9)/, '\u00c9'],
  [/(?i:[^a])/, 'Ab'], [/(?i:a)+?b/, 'AaAb'], [/(?i:a{2})/, 'aA'],
];
R.forEach(function (r) { console.log(row(r[0], r[1])); });
"""
    r = js(code)
    assert out(r) == golden("inline_modifier_groups")
    assert (r.returncode, r.stderr) == (0, b"")


def test_has_indices_flag(js, golden):
    """CATCHES: a `d` flag implementation whose `indices` array has wrong UTF-16 offsets for astral
    text, omits undefined entries for unmatched groups, lacks `indices.groups` (or reports the
    unmatched duplicate), or is attached when the flag is absent."""
    code = r"""
function idx(m) { return m ? JSON.stringify(m.indices) + (m.indices.groups ? ' g=' + JSON.stringify(m.indices.groups) : ' g=none') : 'null'; }
console.log('basic', idx(/(?<a>b)(x)?(?<c>c)/d.exec('abcd')));
console.log('unicode', idx(/(?<e>\u{1F600})(.)/du.exec('a\u{1F600}b')), idx(/(.)(.)/d.exec('\u{1F600}')), idx(/\u{1F600}(.)/dgu.exec('\u{1F600}\u{1F601}x')));
console.log('duplicate names', idx(/(?<n>a)|(?<n>b)/d.exec('xb')), idx(/(?<n>a)|(?<n>b)/d.exec('xa')));
console.log('lookbehind', idx(/(?<=(\d))x/d.exec('1x')), idx(/(?=(\w+))a/d.exec('ab')));
console.log('many groups', idx(/(a)(b)(c)(d)(e)/d.exec('zabcde')));
console.log('no d flag', /a/.exec('a').indices, 'indices' in /a/d.exec('a'), Array.isArray(/a/d.exec('a').indices));
console.log('matchAll with d', [...'a1b22'.matchAll(/\d+/dg)].map(function (m) { return m.indices[0].join('-'); }).join(' '));
console.log('replace keeps working', 'abc'.replace(/(?<x>b)/d, '[$<x>]'), /x/d.hasIndices, /x/.hasIndices, /x/dg.flags);
"""
    r = js(code)
    assert out(r) == golden("has_indices_flag")
    assert (r.returncode, r.stderr) == (0, b"")


def test_sticky_global_and_last_index(js, golden):
    """CATCHES: sticky matching that scans ahead instead of anchoring at lastIndex (including the
    literal fast path), `^` under /my, ToLength coercion of lastIndex, lastIndex landing inside a
    surrogate pair under /u, or exec/test not resetting lastIndex to 0 after a failed global match."""
    code = r"""
var out = [];
var st = /foo/y;
[0, 1, 3, 4, 7, 10].forEach(function (li) { st.lastIndex = li; var m = st.exec('foofoo foo'); out.push(li + ':' + (m ? m.index + '/' + st.lastIndex : 'null/' + st.lastIndex)); });
console.log('sticky literal', out.join(' '));
var sc = /[a-c]+/y; out = [];
[0, 2, 3].forEach(function (li) { sc.lastIndex = li; out.push(li + ':' + sc.test('ab-cd') + '/' + sc.lastIndex); });
console.log('sticky class', out.join(' '));
var sy = /^a/my; sy.lastIndex = 2; console.log('sticky ^ multiline', sy.test('b\na'), sy.lastIndex, (sy.lastIndex = 1, sy.test('b\na')), sy.lastIndex);
var sg = /\d/gy; console.log('gy', JSON.stringify('12a3'.match(sg)), '12a3'.replace(sg, '#'), JSON.stringify('1a2'.split(/\d/y)), '12a3'.search(/a/y), 'a12'.search(/1/y));
var su = /./gu; su.lastIndex = 1; var mu = su.exec('\u{1F600}x'); console.log('u lastIndex mid-pair', mu[0], mu.index, su.lastIndex);
var sn = /./g; sn.lastIndex = 1; var mn = sn.exec('\u{1F600}x'); console.log('non-u lastIndex mid-pair', JSON.stringify(mn[0]), mn.index, sn.lastIndex);
var sy2 = /x/uy; sy2.lastIndex = 1; console.log('sticky u mid-pair', sy2.exec('\u{1F600}x'), sy2.lastIndex);
var sy3 = /x/uy; sy3.lastIndex = 2; console.log('sticky u after pair', JSON.stringify(sy3.exec('\u{1F600}x')), sy3.lastIndex);
var g = /o/g, walk = [], m; while ((m = g.exec('foo boo')) !== null) walk.push(m.index + ':' + g.lastIndex); console.log('global walk', walk.join(' '), g.lastIndex);
var r = /a/g; r.lastIndex = -4; var m1 = r.exec('aa'); r.lastIndex = 1.9; var m2 = r.exec('aa'); r.lastIndex = '1'; var m3 = r.exec('xa');
r.lastIndex = Infinity; var m4 = r.exec('aaa'); console.log('ToLength', m1.index, m2.index, m3.index, m4, r.lastIndex);
var t = /b/g; t.lastIndex = 5; console.log('test past end', t.test('abc'), t.lastIndex, /b/y.test('abc'), 'abc'.replace(/b/y, 'X'), 'bbc'.replace(/b/gy, 'X'));
var frozen = /a/y; Object.defineProperty(frozen, 'lastIndex', { value: 0, writable: false });
try { frozen.exec('b'); } catch (e) { console.log('frozen sticky miss', e.name); }
try { console.log('frozen non-sticky ok', /a/.exec.call(Object.defineProperty(/a/, 'lastIndex', { writable: false }), 'a')[0]); } catch (e) { console.log(e.name); }
"""
    r = js(code)
    assert out(r) == golden("sticky_global_and_last_index")
    assert (r.returncode, r.stderr) == (0, b"")


def test_dotall_multiline_and_unicode_advance(js, golden):
    """CATCHES: `.` matching line terminators without /s (or U+0085 being treated as one), `^`/`$`
    under /m ignoring \\r, U+2028 and U+2029, or empty global matches advancing by code unit instead
    of by code point in Unicode mode (replace, match, matchAll, split)."""
    code = r"""
console.log('dotAll', /^.$/.test('\u2028'), /^.$/s.test('\u2028'), /^.$/.test('\r'), /^.$/.test('\u0085'), /^.$/.test('\n'), /^.$/s.test('\n'), /x.y/s.dotAll);
console.log('multiline terms', /a$/m.test('a\u2028b'), /^b/m.test('a\rb'), /^b/m.test('a\u2029b'), 'a\r\nb'.split(/$/m).length, /a$/.test('a\n'));
console.log('anchors', JSON.stringify('l1\nl2\r\nl3'.match(/^l\d$/gm)), JSON.stringify('x\ny'.match(/^/gm)), JSON.stringify('ab'.match(/$/g)), JSON.stringify('a\nb\n'.match(/$/gm)));
console.log('empty advance', '\u{1F600}\u{1F600}'.replace(/(?:)/g, '-').length, '\u{1F600}\u{1F600}'.replace(/(?:)/gu, '-'), JSON.stringify('\u{1F600}'.match(/(?:)/g)), JSON.stringify('\u{1F600}'.match(/(?:)/gu)));
console.log('matchAll empty', [...'a\u{1F600}'.matchAll(/(?:)/gu)].map(function (m) { return m.index; }).join(), [...'a\u{1F600}'.matchAll(/(?:)/g)].map(function (m) { return m.index; }).join(), [...'a\u{1F600}'.matchAll(/(?:)/gv)].length);
console.log('split unicode', JSON.stringify('a\u{1F600}b'.split(/(?:)/u)), JSON.stringify('a\u{1F600}b'.split(/(?:)/)), JSON.stringify('\u{1F600}'.split('')));
console.log('lone surrogates', JSON.stringify('\ud800\udc00\ud800'.match(/./gu)), JSON.stringify('\udc00\ud800'.match(/[\ud800-\udfff]/gu)), /^[^x]{2}$/u.test('\ud800\udc00'), /\udc00/u.test('\ud800\udc00'), /\udc00/.test('\ud800\udc00'));
console.log('replace empty global u', 'ab'.replace(/(?:)/gu, '|'), '\u00e9\u{1F600}'.replace(/(?:)/gv, '.'), '\u{1F600}x'.replace(/x*/gu, '_'));
"""
    r = js(code)
    assert out(r) == golden("dotall_multiline_and_unicode_advance")
    assert (r.returncode, r.stderr) == (0, b"")


def test_pathological_patterns_terminate_quickly(js, golden):
    """CATCHES: a backtracking matcher without a step budget or iterative repetition, which hangs on
    nested quantifiers like `^(a+)+b` or overflows the stack on long single-character runs instead of
    returning the (null or long) result promptly."""
    code = r"""
console.log('budgeted', /^(a+)+b/.test('a'.repeat(28)), /^(?:a|aa)+c/.test('a'.repeat(30)), /(?:a*)*b/y.test('a'.repeat(40)), /^(\w+\s?)*$/.test('aaaa aaaa aaaa aaaa!'));
console.log('long runs', /a+b/.test('a'.repeat(8000) + 'b'), /x*y/.exec('x'.repeat(8000) + 'y')[0].length, /(?:ab)*c/.exec('ab'.repeat(300) + 'c')[0].length, /[^,]+$/.exec('q,' + 'z'.repeat(8000))[0].length);
console.log('lazy runs', /a+?b/.exec('a'.repeat(8000) + 'b')[0].length, /.*?x/.exec('.'.repeat(8000) + 'x')[0].length, /\s*$/.exec('a' + ' '.repeat(3000))[0].length);
console.log('wide subject', /\u00e9+z/.exec('\u00e9'.repeat(8000) + 'z')[0].length, /\p{L}+!/u.exec('\u{10400}'.repeat(3000) + '!')[0].length);
"""
    r = js(code)
    assert out(r) == golden("pathological_patterns_terminate_quickly")
    assert (r.returncode, r.stderr) == (0, b"")


def test_replace_with_custom_exec_results(js, golden):
    """CATCHES: a RegExp.prototype[Symbol.replace] that trusts the internal matcher instead of the
    observable exec result: wrong clamping of `index`, overlapping results not skipped, `length`
    and captures not coerced, `groups` null/primitive handling, or wrong replacer-function args."""
    code = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function fake(results) { var re = /./g; var k = 0; re.exec = function () { var r = results[k++]; if (r) re.lastIndex = r.next; return r ? r.res : null; }; return re; }
show('odd results', function () {
  var re = fake([{ res: { 0: 'bc', index: 1, length: 3, 1: 'B', 2: undefined }, next: 3 }, { res: { 0: 'x', index: 0, length: 1 }, next: 4 }, { res: { 0: 'ef', index: 4.7, length: 1 }, next: 6 }]);
  return 'abcdefg'.replace(re, '[$1|$2|$&|$`|$\']');
});
show('index clamps', function () { var re = fake([{ res: { 0: 'z', index: -5, length: 1 }, next: 1 }, { res: { 0: 'q', index: 99, length: 1 }, next: 2 }]); return 'abc'.replace(re, '<$&>'); });
show('index NaN', function () { var re = fake([{ res: { 0: 'ab', index: 'nope', length: 1 }, next: 2 }]); return 'abc'.replace(re, '_'); });
show('groups coercion', function () { var re = fake([{ res: { 0: 'b', index: 1, length: 1, groups: { n: 42 } }, next: 2 }]); return 'abc'.replace(re, '($<n>|$<m>)'); });
show('groups null', function () { var re = fake([{ res: { 0: 'b', index: 1, length: 1, groups: null }, next: 2 }]); return 'abc'.replace(re, '$<n>'); });
show('groups primitive', function () { var re = fake([{ res: { 0: 'b', index: 1, length: 1, groups: 'str' }, next: 2 }]); return 'abc'.replace(re, '[$<length>]'); });
show('fn args with groups', function () { var re = fake([{ res: { 0: 'b', index: 1, length: 2, 1: 7, groups: { g: 1 } }, next: 2 }]); return 'abc'.replace(re, function () { return JSON.stringify(Array.prototype.slice.call(arguments)); }); });
show('fn args null groups', function () { var re = fake([{ res: { 0: 'b', index: 1, length: 1, groups: null }, next: 2 }]); return 'abc'.replace(re, function () { return arguments.length + ':' + arguments[4]; }); });
show('length getter', function () { var re = fake([{ res: { 0: 'b', index: 1, get length() { return '3'; }, 1: 'x', 2: 'y' }, next: 2 }]); return 'abc'.replace(re, '$2$1'); });
show('matched toString', function () { var re = fake([{ res: { 0: { toString: function () { return 'BC'; } }, index: 1, length: 1 }, next: 3 }]); return 'abcd'.replace(re, '<$&>'); });
show('empty match advances', function () { var n = 0; var re = /x/g; re.exec = function () { n++; if (n > 3) return null; return { 0: '', index: this.lastIndex, length: 1 }; }; var r = 'abc'.replace(re, '-'); return r + ' lastIndex=' + re.lastIndex; });
show('unicode empty advance', function () { var n = 0; var re = /x/gu; re.exec = function () { if (n++ > 1) return null; return { 0: '', index: this.lastIndex, length: 1 }; }; 'a\u{1F600}'.replace(re, '-'); return re.lastIndex; });
show('exec returns primitive', function () { var re = /a/; re.exec = function () { return 'str'; }; return 'a'.replace(re, 'b'); });
show('exec not callable', function () { var re = /a/; re.exec = 5; return 'xa'.replace(re, 'b') + ' ' + re.test('a'); });
show('non-global stops after one', function () { var calls = 0; var re = /a/; re.exec = function () { calls++; return { 0: 'a', index: 0, length: 1 }; }; return 'aaa'.replace(re, 'b') + ' calls=' + calls; });
show('flags read once', function () { var log = []; var re = /a/g; Object.defineProperty(re, 'flags', { get: function () { log.push('flags'); return 'g'; } }); 'aa'.replace(re, 'b'); return log.join(); });
show('huge expansion', function () { var s = 'x'.repeat(1 << 20); return s.replace(/(x+)/, '$1'.repeat(70)).length; });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("replace_with_custom_exec_results")
    assert (r.returncode, r.stderr) == (0, b"")


def test_symbol_protocol_dispatch(js, golden):
    """CATCHES: String.prototype.match/replace/search/split/matchAll/replaceAll not delegating to
    user Symbol.* methods, the generic RegExp.prototype[Symbol.*] methods not working on plain
    objects with exec/flags, or missing TypeErrors for non-object receivers and non-global regexps."""
    code = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('symbol methods on non-objects', function () { return ['match', 'replace', 'search', 'split', 'matchAll'].map(function (n) { try { RegExp.prototype[Symbol[n]].call('x', 'y'); return n + ':ok'; } catch (e) { return n + ':' + e.message; } }).join(' / '); });
show('generic match on plain object', function () { var o = { flags: '', exec: function (s) { return { 0: s.toUpperCase(), index: 0 }; } }; return JSON.stringify(RegExp.prototype[Symbol.match].call(o, 'hey')); });
show('generic global match on plain object', function () { var n = 0; var o = { flags: 'g', lastIndex: 9, exec: function () { return n++ < 2 ? { 0: 'm' + n } : null; } }; return JSON.stringify(RegExp.prototype[Symbol.match].call(o, 'zz')) + ' li=' + o.lastIndex; });
show('generic replace on plain object', function () { var calls = 0; var o = { flags: 'g', lastIndex: 7, exec: function (s) { if (calls++ > 1) return null; return { 0: 'e', index: calls, length: 1 }; } }; return RegExp.prototype[Symbol.replace].call(o, 'hey', '_') + ' lastIndex=' + o.lastIndex; });
show('generic search on plain object', function () { var o = { lastIndex: -0, exec: function () { return { index: 4 }; } }; var r = RegExp.prototype[Symbol.search].call(o, 'x'); return r + ' ' + Object.is(o.lastIndex, -0); });
show('generic split species', function () { var o = { constructor: { [Symbol.species]: function (rx, fl) { this.lastIndex = 0; this.flags = fl; this.exec = function (s) { return this.lastIndex === 1 ? (this.lastIndex = 2, { length: 1 }) : null; }; } }, flags: 'i' }; return JSON.stringify(RegExp.prototype[Symbol.split].call(o, 'abc')); });
show('string methods dispatch', function () {
  var log = [];
  var o = { flags: 'g' };
  ['match', 'replace', 'search', 'split', 'matchAll'].forEach(function (n) { o[Symbol[n]] = function (s, x) { log.push(n + '(' + s + (x === undefined ? '' : ',' + x) + ')'); return n + '!'; }; });
  return ['abc'.match(o), 'abc'.replace(o, 'r'), 'abc'.search(o), 'abc'.split(o, 2), 'abc'.matchAll(o), 'abc'.replaceAll(o, 'z')].join() + ' ' + log.join(' ');
});
show('null/undefined Symbol.replace falls back', function () { var o = { [Symbol.replace]: null, toString: function () { return 'b'; } }; return 'abc'.replace(o, 'X') + ' ' + 'abc'.split({ [Symbol.split]: undefined, toString: function () { return 'b'; } }).join('|'); });
show('non-callable Symbol.match', function () { return 'a'.match({ [Symbol.match]: 1 }); });
show('replaceAll/matchAll flag checks', function () { var r = []; var o = { [Symbol.match]: true, flags: 'i' }; try { 'a'.replaceAll(o, ''); } catch (e) { r.push(e.message); } try { 'a'.matchAll(o); } catch (e) { r.push(e.message); } var g = { [Symbol.match]: true, flags: undefined }; try { 'a'.matchAll(g); } catch (e) { r.push(e.name); } return r.join(' | '); });
show('replaceAll with global regexp', function () { return 'a.b.c'.replaceAll(/\./g, function (m, i) { return '[' + i + ']'; }) + ' ' + 'aaa'.replaceAll(/a/gy, 'b'); });
show('startsWith rejects regexp', function () { var r = []; ['startsWith', 'endsWith', 'includes'].forEach(function (n) { try { 'a'[n](/a/); } catch (e) { r.push(n + ':' + e.name); } }); return r.join(' '); });
show('match on subclass with exec', function () { class R extends RegExp { exec(s) { var m = super.exec(s); if (m) m[0] = m[0].toUpperCase(); return m; } } return JSON.stringify('a1b2'.match(new R('[a-z]', 'g'))) + ' ' + 'a1'.replace(new R('[a-z]'), '<$&>') + ' ' + new R('\\d').test('x9'); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("symbol_protocol_dispatch")
    assert (r.returncode, r.stderr) == (0, b"")


def test_split_and_match_all_semantics(js, golden):
    """CATCHES: RegExp split that ignores the species constructor or the `y` splitter flag, mis-
    coerces the limit with ToUint32, drops undefined captures, mishandles empty inputs, or a
    matchAll iterator that mutates the original lastIndex or keeps going for a non-global regexp."""
    code = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('species', function () { var log = []; class R extends RegExp { constructor(p, f) { log.push('ctor ' + (p instanceof RegExp ? p.source : p) + ' ' + f); super(p, f); } } var parts = 'a1b22c'.split(new R('\\d+', 'g'), 2); return JSON.stringify(parts) + ' ' + log.join(';'); });
show('limit coercion', function () { return [JSON.stringify('a,b,c'.split(/,/, -1)), JSON.stringify('a,b,c'.split(/,/, 4294967297)), JSON.stringify('a,b,c'.split(/,/, NaN)), JSON.stringify('a,b,c'.split(/(,)/, 2)), JSON.stringify('a,b,c'.split(/,/, 2.9)), JSON.stringify('ab'.split(/(?:)/y)), JSON.stringify('a,b'.split(/,/, Infinity))].join(' '); });
show('empty input', function () { return JSON.stringify(''.split(/a?/)) + JSON.stringify(''.split(/b/)) + JSON.stringify(''.split(/(?:)/)) + JSON.stringify(''.split(/x/, 0)); });
show('captures', function () { return JSON.stringify('a1b'.split(/(\d)(x)?/)) + ' ' + JSON.stringify('a1b2c'.split(/(\d)/, 3)) + ' ' + JSON.stringify('abc'.split(/(b)|(z)/)); });
show('edges', function () { return [JSON.stringify(',a,'.split(/,/)), JSON.stringify('aXbxc'.split(/x/i)), JSON.stringify('ab'.split(/$/)), JSON.stringify('a\u{1F600}'.split(/(?=\u{1F600})/u)), JSON.stringify('abc'.split(/b*/))].join(' '); });
show('sticky separator', function () { return JSON.stringify('x1y2'.split(/\d/y)) + ' ' + JSON.stringify('11a'.split(/1/gy)); });
show('matchAll iterator', function () { var re = /(\d)(?<l>[a-z])?/g; re.lastIndex = 2; var it = 'x1a2b3'.matchAll(re); var r = []; for (var m of it) r.push(m[0] + '@' + m.index + ':' + m.groups.l); return r.join(' ') + ' orig.lastIndex=' + re.lastIndex + ' ' + Object.prototype.toString.call(it) + ' ' + JSON.stringify(it.next()); });
show('matchAll non-global stops', function () { var it2 = RegExp.prototype[Symbol.matchAll].call(/a/y, 'aab'); return [it2.next().value[0], it2.next().done, it2.next().done].join(); });
show('matchAll species and flags', function () { var log = []; var re = /a/g; re.constructor = { [Symbol.species]: function (r, f) { log.push(f); return /b/g; } }; return [...'abab'.matchAll(re)].map(function (m) { return m[0] + m.index; }).join() + ' ' + log.join(); });
show('matchAll string arg', function () { return [...'a.b.c'.matchAll('.')].map(function (m) { return m.index; }).join() + ' ' + [...'aXa'.matchAll(/a/gi)].length; });
show('match non-global groups', function () { var m = 'k=v'.match(/(?<k>\w)=(?<v>\w)/); return m.groups.k + m.groups.v + ' ' + m.input + ' ' + Object.getPrototypeOf(m.groups); });
show('match global resets', function () { var re = /o/g; re.lastIndex = 5; var r = 'foo'.match(re); return JSON.stringify(r) + ' ' + re.lastIndex + ' ' + 'x'.match(/y/g); });
show('search', function () { var re = /b/g; re.lastIndex = 2; return ['abc'.search(re), re.lastIndex, 'abc'.search('c'), 'abc'.search(), 'a.c'.search('.'), 'a\u{1F600}b'.search(/b/u)].join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("split_and_match_all_semantics")
    assert (r.returncode, r.stderr) == (0, b"")


def test_replacement_templates(js, golden):
    """CATCHES: GetSubstitution errors: `$0`/`$00` and out-of-range `$n` not left literal, two-digit
    `$nn` not falling back to one digit, `$<name>` scanning, `$\\``/`$'` with astral text, or a
    trailing `$` being dropped."""
    code = r"""
console.log('abc'.replace(/b/, '$0$00$1$01$10$$$'));
console.log('abc'.replace(/(b)/, '$01$10$11$2'));
console.log('abcdefghijk'.replace(/(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)/, '$11$10$1$011$110$12'));
console.log('abc'.replace(/b/, '$'), 'abc'.replace(/b/, 'x$'), 'abc'.replace(/(?<x>b)/, '$<x$<x>'), 'abc'.replace(/(?<x>b)/, '$<x'), 'abc'.replace(/(b)/, '$<x>'));
console.log('\u{1F600}a\u{1F600}'.replace(/a/, '[$`|$\'|$&]'), '\u{1F600}a\u{1F600}'.replace(/\u{1F600}/gu, 'E'), 'x\u{1F600}y'.replace(/(?<=\u{1F600})y/u, 'Y'));
console.log('John Smith'.replace(/(?<first>\w+)\s(?<last>\w+)/, '$<last>, $<first> [$2 $1] $$ $& ($`|$\') $0 $9 $<none>.'));
console.log('aaa'.replace(/a/g, '$&$&'), 'abc'.replace(/(?:)/g, '$`'), 'x-y'.replace(/(\w)-(\w)/, '$2-$1'), 'abc'.replace('b', '$&$`$\''));
console.log('tab'.replace(/(t)(a)?(z)?/, '[$1|$2|$3]'), 'q'.replace(/(z)?q/, '$1!'), 'abc'.replace(/b/, function (m, i, s) { return i + s; }));
"""
    r = js(code)
    assert out(r) == golden("replacement_templates")
    assert (r.returncode, r.stderr) == (0, b"")


def test_regexp_constructor_and_source(js, golden):
    """CATCHES: a RegExp constructor that ignores IsRegExp/Symbol.match, returns a copy instead of
    the argument when called as a function, coerces pattern/flags in the wrong order, or a `source`
    getter that fails to escape `/` (outside classes) and line terminators so toString re-parses."""
    code = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('source escaping', function () { return [new RegExp('a/b[/]c'), new RegExp('\\/'), new RegExp('[\\]/]'), new RegExp('a\u2028b\u2029c\rd\ne'), new RegExp('\\\n'), RegExp('x\\\\/y'), new RegExp('[\\[/]/'), new RegExp('\\\u2028')].map(function (r) { return r.source; }).join('  '); });
show('toString re-parses', function () { var r = new RegExp('a/b\n[/]', 'gi'); return String(r) + ' ' + eval(String(r)).test('a/b\n/'); });
show('prototype getters', function () { var P = RegExp.prototype; return [P.source, P.flags, P.global, P.sticky, P.hasIndices, P.unicodeSets, String(P)].join(','); });
show('getter on non-regexp', function () { var r = []; ['source', 'global', 'flags', 'dotAll', 'unicode', 'multiline', 'ignoreCase'].forEach(function (k) { try { r.push(k + '=' + Object.getOwnPropertyDescriptor(RegExp.prototype, k).get.call({})); } catch (e) { r.push(k + ':' + e.message); } }); return r.join(' | '); });
show('flags getter on primitive', function () { return Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get.call(1); });
show('flags getter order and coercion', function () { var log = []; var o = {}; ['hasIndices', 'global', 'ignoreCase', 'multiline', 'dotAll', 'unicode', 'unicodeSets', 'sticky'].forEach(function (k, i) { Object.defineProperty(o, k, { get: function () { log.push(k[0]); return i % 2 ? 1 : ''; } }); }); return Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get.call(o) + ' ' + log.join(''); });
show('IsRegExp via Symbol.match', function () { var o = { [Symbol.match]: true, source: 'q+', flags: 'g', constructor: RegExp }; var r = RegExp(o); var r2 = new RegExp(o, 'i'); return [r === o, r instanceof RegExp, r.source, r.flags, r2.flags, r2.source].join(','); });
show('regexp with Symbol.match false', function () { var re = /ab/g; re[Symbol.match] = false; var r = RegExp(re); return [r === re, r.source, r.flags].join(','); });
show('call with other constructor', function () { var re = /x/; re.constructor = Object; var re5 = /y/; re5.constructor = 5; return [RegExp(re) === re, RegExp(re5) === re5, RegExp(/y/) instanceof RegExp, RegExp(/z/, 'g').flags].join(); });
show('new.target prototype', function () { function F() {} F.prototype = Object.create(RegExp.prototype); var r = Reflect.construct(RegExp, ['z'], F); return [Object.getPrototypeOf(r) === F.prototype, r.test('z')].join(); });
show('subclass', function () { class R extends RegExp { exec(s) { var m = super.exec(s); if (m) m.extra = true; return m; } } var r = new R('b', 'g'); return [r instanceof R, r.test('abc'), r.lastIndex, 'abcb'.replace(r, 'X'), JSON.stringify('abcb'.match(r)), r[Symbol.split]('abc').join('|')].join(' '); });
show('coercion order', function () { var log = []; var p = { toString: function () { log.push('pattern'); return 'p'; } }; var f = { toString: function () { log.push('flags'); return 'g'; } }; new RegExp(p, f); return log.join(','); });
show('regexp-like reads', function () { var log = []; var o = { get [Symbol.match]() { log.push('@@match'); return true; }, get source() { log.push('source'); return 's'; }, get flags() { log.push('flags'); return 'm'; }, get constructor() { log.push('constructor'); return Object; } }; var r = RegExp(o); return r.source + r.flags + ' ' + log.join(','); });
show('undefined pattern/flags', function () { return [new RegExp().source, new RegExp(undefined, undefined).flags, new RegExp(null).source, new RegExp(123, 'm').source, String(new RegExp(''))].join(' '); });
show('throwing pattern coercion', function () { return new RegExp({ toString: function () { throw new EvalError('nope'); } }); });
show('exec result shape', function () { var m = /(?<x>a)(b)?/.exec('zab'); return Object.keys(m).join() + ' ' + Object.getOwnPropertyNames(m).length + ' ' + typeof m.groups + ' ' + m.input; });
show('test/toString receivers', function () { var r = []; try { RegExp.prototype.test.call(1, 'a'); } catch (e) { r.push(e.message); } try { RegExp.prototype.toString.call('x'); } catch (e) { r.push(e.message); } r.push(RegExp.prototype.toString.call({ source: 'S', flags: 'F' })); try { RegExp.prototype.exec.call({}, 'a'); } catch (e) { r.push(e.name); } return r.join(' | '); });
show('test uses exec', function () { var re = /q/; re.exec = function (s) { return s === 'yes' ? {} : null; }; return re.test('yes') + ' ' + re.test('no') + ' ' + re.test({ toString: function () { return 'yes'; } }); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("regexp_constructor_and_source")
    assert (r.returncode, r.stderr) == (0, b"")


def test_compile_and_escape(js, golden):
    """CATCHES: Annex B RegExp.prototype.compile that copies flags wrongly, does not reset lastIndex,
    allows a flags argument with a RegExp pattern, works on subclasses, or loses the old pattern on
    error; and a RegExp.escape that does not hex-escape leading alphanumerics and punctuators."""
    code = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('compile', function () { var r = /a/g; r.lastIndex = 2; var r2 = r.compile(/x+/im); return [r2 === r, r.source, r.flags, r.lastIndex, r.test('XX')].join(','); });
show('compile string', function () { var r = /a/; r.compile('b+', 'gy'); return [r.source, r.flags, r.global, r.sticky, 'bbb'.replace(r, '!')].join(','); });
show('compile undefined', function () { var r = /a/g; r.compile(); return JSON.stringify(r.source) + r.flags + ' ' + r.compile(undefined, 'y').flags; });
show('compile regexp+flags', function () { return /a/.compile(/b/, 'g'); });
show('compile bad pattern', function () { var r = /keep/; try { r.compile('('); } catch (e) { return e.name + ' ' + e.message + ' kept=' + r.source; } });
show('compile bad flags', function () { var r = /keep/; try { r.compile('a', 'q'); } catch (e) { return e.name + ' ' + e.message + ' kept=' + r.source; } });
show('compile on subclass', function () { class R extends RegExp {} return new R('a').compile('b'); });
show('compile on non-regexp', function () { return RegExp.prototype.compile.call({}, 'a'); });
show('compile frozen lastIndex', function () { var r = /a/; Object.defineProperty(r, 'lastIndex', { writable: false }); return r.compile('b'); });
show('compile flags coercion', function () { var r = /a/; r.compile('c', { toString: function () { return 'i'; } }); return r.test('C'); });
show('escape', function () { return [RegExp.escape('foo.bar'), RegExp.escape('9 lives'), RegExp.escape('_x$^'), RegExp.escape('\t\n\v\f\r'), RegExp.escape(',-=<>#&!%:;@~\'`"'), RegExp.escape('\u00a0\u2028\ufeff'), RegExp.escape('\ud800x'), RegExp.escape('x\udfff'), RegExp.escape('\u{1F600}\u00e9'), RegExp.escape(''), RegExp.escape('\u3000\u2029'), RegExp.escape('A'), RegExp.escape('()[]{}|/\\*+?')].join(' ~ '); });
show('escape non-string', function () { var r = []; [42, undefined, { toString: function () { return 'x'; } }].forEach(function (v) { try { r.push(RegExp.escape(v)); } catch (e) { r.push(e.name); } }); return r.join(','); });
show('escape roundtrip', function () { var s = 'a.b*c(d)[e]{f}|g/h\\i^j$k+l?m-n'; return new RegExp('^' + RegExp.escape(s) + '$', 'v').test(s) + ' ' + new RegExp(RegExp.escape(s), 'u').test(s) + ' ' + new RegExp('[' + RegExp.escape('a-z') + ']', 'v').test('b'); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("compile_and_escape")
    assert (r.returncode, r.stderr) == (0, b"")


def test_legacy_static_properties(js, golden):
    """CATCHES: legacy RegExp statics ($1-$9, lastMatch, lastParen, leftContext, rightContext, input)
    that are not updated by test/search/split/replace, are clobbered by failed matches, accept a
    foreign receiver, or mis-report unmatched groups and astral contexts."""
    code = r"""
var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('brand', function () { class R extends RegExp {} var r = []; try { r.push(R.$1); } catch (e) { r.push(e.message); } try { Object.getOwnPropertyDescriptor(RegExp, 'input').set.call({}, 'x'); } catch (e) { r.push(e.name); } try { Object.getOwnPropertyDescriptor(RegExp, 'lastMatch').get.call(undefined); } catch (e) { r.push(e.name); } return r.join(' | '); });
show('$1-$9', function () { /(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)/.exec('abcdefghij'); return [RegExp.$1, RegExp.$2, RegExp.$3, RegExp.$4, RegExp.$5, RegExp.$6, RegExp.$7, RegExp.$8, RegExp.$9, RegExp.lastParen, RegExp['$+']].join(''); });
show('unmatched paren', function () { /(x)|(y)/.exec('y'); return JSON.stringify([RegExp.$1, RegExp.$2, RegExp.lastParen, RegExp.$3]); });
show('no groups', function () { /b/.exec('abc'); return JSON.stringify([RegExp.$1, RegExp.lastParen, RegExp.lastMatch, RegExp['$`'], RegExp["$'"]]); });
show('after test/search/split', function () { /(\d)/.test('a5'); var a = RegExp.$1; 'q7'.search(/(\d)/); var b = RegExp.$1; 'x8y'.split(/(\d)/); var c = RegExp.$1 + RegExp.leftContext + RegExp.rightContext; return a + b + ' ' + c; });
show('after global replace', function () { 'a1b2c3'.replace(/(\d)/g, '-'); return RegExp.$1 + RegExp.lastMatch + RegExp.leftContext + '|' + RegExp.rightContext + '|' + RegExp.input; });
show('after matchAll', function () { [...'k1k2'.matchAll(/k(\d)/g)]; return RegExp.$1 + RegExp.leftContext; });
show('failed match keeps', function () { /(z)/.exec('qz'); /(y)/.test('qqq'); 'abc'.replace(/(w)/, ''); return RegExp.$1 + RegExp.leftContext; });
show('astral contexts', function () { /(\u{1F601})/u.exec('a\u{1F600}\u{1F601}b'); return RegExp.leftContext.length + ' ' + RegExp.rightContext + ' ' + RegExp.$1.length; });
show('input setter coercion', function () { RegExp.input = 99; var a = RegExp.input + typeof RegExp.input; RegExp.$_ = { toString: function () { return 'obj'; } }; return a + ' ' + RegExp.input; });
show('input after setter then match', function () { RegExp.input = 'manual'; /x/.exec('xyz'); return RegExp.input + ' ' + RegExp.$_; });
show('descriptors', function () { var d = Object.getOwnPropertyDescriptor(RegExp, '$1'); var i = Object.getOwnPropertyDescriptor(RegExp, 'input'); return [typeof d.get, d.set, d.enumerable, d.configurable, typeof i.set].join(); });
console.log(out.join('\n'));
"""
    r = js(code)
    assert out(r) == golden("legacy_static_properties")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_dead_result_replace_and_split_update_statics(js, golden, tier):
    """CATCHES: a JIT fast path for `s.replace(re, str)` / `s.split(re)` whose result is unused that
    skips the observable side effects: lastIndex updates for sticky/global regexps, empty-match
    advancement and the legacy RegExp statics must match an ordinary call in every tier."""
    code = r"""
var log = [];
function rep(s, re) { s.replace(re, 'x'); return re.lastIndex; }
function spl(s, re) { s.split(re); return 0; }
function ex(s, re) { re.exec(s); return re.lastIndex; }
var cases = [['a1b22c333', /(\d+)/g], ['a1b22c333', /(\d)/], ['xyz', /(?:)/g], ['\u{1F600}a\u{1F600}', /(?:)/gu], ['aaa', /a/y], ['baaa', /a/y], ['no digits', /(\d)/g], ['k1k2', /k(\d)/gy], ['\u00e9t\u00e9', /(\u00e9)/g]];
for (var c = 0; c < cases.length; c++) {
  var s = cases[c][0], re = cases[c][1], li;
  for (var k = 0; k < 30; k++) { re.lastIndex = 0; li = rep(s, re); }
  log.push('replace ' + re + ' on ' + s + ': lastIndex=' + li + ' $1=' + RegExp.$1 + ' lastMatch=' + JSON.stringify(RegExp.lastMatch) + ' left=' + RegExp.leftContext + ' right=' + RegExp.rightContext);
}
var custom = /(c)/g; custom.exec = function (s) { log.push('custom exec'); return null; };
for (var k = 0; k < 12; k++) rep('abc', custom);
var scases = [['a1b22c333', /(\d+)/], ['a1b2', /(\d)/y], ['abc', /(?:)/], ['', /x?/], ['', /x/], ['\u{1F600}\u{1F600}', /(?:)/u], ['a,b,,c', /,/g], ['zzz', /q/], ['xay', /(a)/i]];
for (var c = 0; c < scases.length; c++) {
  var s = scases[c][0], re = scases[c][1];
  RegExp.input = 'reset'; /(-)/.exec('-');
  for (var k = 0; k < 30; k++) spl(s, re);
  log.push('split ' + re + ' on ' + JSON.stringify(s) + ': lastIndex=' + re.lastIndex + ' $1=' + RegExp.$1 + ' lastMatch=' + JSON.stringify(RegExp.lastMatch) + ' input=' + JSON.stringify(RegExp.input));
}
var re2 = /(o)/g;
for (var k = 0; k < 30; k++) { re2.lastIndex = 0; ex('foo', re2); ex('foo', re2); }
log.push('exec ' + re2.lastIndex + ' ' + RegExp.$1 + RegExp.leftContext);
function splStr(s) { s.split(','); return 0; }
for (var k = 0; k < 30; k++) splStr('a,b');
var ownFlags = /(\d)/; Object.defineProperty(ownFlags, 'flags', { value: '' });
for (var k = 0; k < 30; k++) spl('x7y', ownFlags);
log.push('own flags $1=' + RegExp.$1);
Object.defineProperty(RegExp, Symbol.species, { value: RegExp, configurable: true });
for (var k = 0; k < 30; k++) spl('q8r', /(\d)/);
log.push('species data $1=' + RegExp.$1);
delete RegExp.prototype.unicodeSets;
for (var k = 0; k < 30; k++) { spl('m9n', /(\d)/); rep('m5n', /(\d)/g); }
log.push('after delete $1=' + RegExp.$1 + ' flags=' + JSON.stringify(/a/v.flags));
console.log(log.length + '\n' + log.filter(function (l) { return l !== 'custom exec'; }).join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("dead_result_replace_and_split_update_statics")
    assert (r.returncode, r.stderr) == (0, b"")


def test_non_ascii_subject_offsets(js, golden):
    """CATCHES: index/lastIndex/capture offsets computed in code points or bytes instead of UTF-16
    units for BMP and astral subjects (in both u and non-u mode), wrong slicing of captures, or
    broken results for patterns with many capture groups over wide subjects."""
    code = r"""
function info(re, s) { var m = re.exec(s); return m ? m.index + ':' + JSON.stringify(Array.from(m, function (x) { return x === undefined ? null : x; })) + ':' + re.lastIndex : 'null'; }
var bmp = '\u00e9t\u00e9 \u00e0 Z\u00fcrich';
console.log(info(/(Z)(\u00fc)(r)(i)(c)(h)/g, bmp), info(/\w+/g, bmp), info(/[^\x00-\x7f]+/g, bmp));
var astral = 'a\u{1F600}b\u{1F601}c\u{10400}d';
console.log(info(/b(.)c/gu, astral), info(/b(..)c/g, astral), info(/\u{10400}(d)/gu, astral), info(/(c)(.)(d)/gu, astral));
var r = /\p{L}/gu, seen = [], m; while ((m = r.exec(astral)) !== null) seen.push(m[0] + '@' + m.index + '/' + r.lastIndex); console.log(seen.join(' '));
var r2 = /./gu; r2.lastIndex = 2; console.log(info(r2, astral), JSON.stringify(astral.split(/(?:)/u).length), astral.replace(/[\u{1F600}-\u{1F64F}]/gu, '#'));
console.log(JSON.stringify('\u4e2d\u6587abc\u65e5\u672c'.match(/[a-z]+|[\u4e00-\u9fff]+/g)), '\u03b1\u03b2\u03b3'.search(/\u03b3/), '\u0436\u0416'.replace(/\u0436/gi, 'z'));
console.log(info(/(\u00e9)(t)(\u00e9)(.)(\u00e0)/, bmp), info(/(?<a>.)(?<b>.)(?<c>.)(?<d>.)/u, '\u{1F600}\u{1F601}xy'));
console.log(JSON.stringify(/(a)|(b)|(c)|(d)|(e)/.exec('d')), JSON.stringify(/(\u00e9)|(b)|(c)|(d)|(e)/.exec('\u00e9')));
"""
    r = js(code)
    assert out(r) == golden("non_ascii_subject_offsets")
    assert (r.returncode, r.stderr) == (0, b"")


def test_first_character_prescan_paths(js, golden):
    """CATCHES: a start-position prescan (first-byte/first-atom lookup tables, anchored `^`, literal
    search) that skips viable positions: case-insensitive first atoms, classes with non-ASCII
    members, optional leading atoms, multiline anchors, sticky starts and start offsets."""
    code = r"""
var pad = '-'.repeat(40);
var R = [
  [/needle/, pad + 'need needle'], [/needle/g, 'needle' + pad + 'needle'], [/needle/y, 'needle'], [/e/, pad], [/^abc/, 'abc'], [/^abc/, 'xabc'],
  [/^b/m, 'a\nb'], [/^b|c/, 'abc'], [/(?:^|x)b/, 'xb'], [/a?b/, pad + 'b'], [/a*b/, pad + 'aab'], [/[xy]+z/, pad + 'yyz'], [/[^-]z/, pad + 'qz'],
  [/\u00e9z/, pad + '\u00e9z'], [/[\u00e9\u0101]z/, pad + '\u0101z'], [/\u0101/i, pad + '\u0100'], [/[\u0100-\u017f]{2}/, pad + '\u0101\u0102'],
  [/\Sz/, pad + ' kz'], [/.z/s, pad + '\nz'], [/.z/, '\nz'], [/(a|b)c/, pad + 'bc'], [/(?:a|)c/, pad + 'c'], [/\bword/, pad + 'word'], [/(?=w)wo/, pad + 'wo'],
  [/\p{Lu}x/u, pad + 'Ax'], [/K/iu, pad + '\u212a'], [/[k]x/iu, pad + '\u212ax'], [/s/iu, pad + '\u017f'], [/ab/i, pad + 'AB'], [/\u212a/i, pad + 'k'],
  [/(?:|)a/, pad + 'a'], [/abc/, 'xxxab'], [/abc/, 'abd abd'], [/q/, '\u00e9\u00e8\u00ea'], [/\ud83d/i, '\ud83e'], [/(?:(?<=(a))b)+/, 'abab'],
  [/x\d/, pad + 'x9'], [/\d+/, 'abc'], [/z/, ''], [/(?:)/, ''], [/a{0}b/, pad + 'b'], [/(?:a+)?b/, pad + 'ab'], [/(a)?b\1/, pad + 'b'],
];
R.forEach(function (r) { var m = r[0].exec(r[1]); console.log(String(r[0]).padEnd(22) + (m ? m.index + ' ' + JSON.stringify(m[0]) : 'null')); });
console.log('lone surrogate patterns', new RegExp('\ud83d').test('\u{1F600}'), new RegExp('\ud83d', 'u').test('\u{1F600}'), new RegExp('[\ud83d]', 'u').test('\ud83d!'), new RegExp('\ud83d', 'u').test('x\ud83d'), new RegExp('\ud83d').exec('a\u{1F600}').index);
var g = /needle/g; g.lastIndex = 3; console.log('offset literal', g.exec('needle--needle').index, g.lastIndex, (g.lastIndex = 20, g.exec('needle--needle')), g.lastIndex);
var y = /needle/y; y.lastIndex = 8; console.log('sticky literal', y.exec('needle--needle').index, y.lastIndex, (y.lastIndex = 7, y.test('needle--needle')));
console.log('counts', ('ab'.repeat(300).match(/b/g) || []).length, ('Ab'.repeat(300).match(/a/gi) || []).length, ('x\u00e9'.repeat(200).match(/\u00e9/g) || []).length);
"""
    r = js(code)
    assert out(r) == golden("first_character_prescan_paths")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_regexp_hot_loops_agree_across_tiers(js, golden, tier):
    """CATCHES: JIT/bytecode specialisations of regexp exec/test/match/replace/split inside hot loops
    (literal regexps re-created per evaluation, shared lastIndex state, callbacks) that produce
    different results or lastIndex values than the tree-walking interpreter."""
    code = r"""
function tokenize(src) { var re = /\s*(?:(\d+)|(\w+)|(.))/y, toks = []; re.lastIndex = 0; var m; while (re.lastIndex < src.length && (m = re.exec(src))) toks.push(m[1] ? 'n' + m[1] : m[2] ? 'w' + m[2] : 'p' + m[3]); return toks.join(' '); }
function count(s) { var n = 0; var re = /[aeiou]/g; while (re.exec(s)) n++; return n; }
function fresh(i) { var r = /x/g; var a = r.test('xx'); return a + ':' + r.lastIndex; }
function camel(s) { return s.replace(/-(\w)/g, function (m, c) { return c.toUpperCase(); }); }
function words(s) { return s.split(/\W+/).filter(Boolean).length; }
var acc = [];
for (var i = 0; i < 120; i++) {
  var t = tokenize('let x' + i + ' = ' + i + ' + 42;');
  var c = count('the quick brown fox ' + i);
  var f = fresh(i);
  var cc = camel('a-b-c' + (i % 3 ? '-d' : ''));
  var w = words('one, two; three ' + i);
  if (i % 40 === 0 || i === 119) acc.push([t, c, f, cc, w].join(' | '));
}
var shared = /o/g, pos = [];
for (var j = 0; j < 20; j++) { pos.push(shared.test('foo') ? shared.lastIndex : 'F'); }
acc.push(pos.join(','));
var dates = []; for (var k = 0; k < 50; k++) { var m = /^(\d{4})-(\d\d)$/.exec('20' + (10 + (k % 20)) + '-0' + (1 + k % 9)); if (k % 10 === 0) dates.push(m[1] + '/' + m[2]); }
acc.push(dates.join(' '));
console.log(acc.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("regexp_hot_loops_agree_across_tiers")
    assert (r.returncode, r.stderr) == (0, b"")
