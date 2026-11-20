"""RegExp: the pattern parser (syntax errors), every flag, lastIndex handling, exec/test results
(captures, named groups, /d indices), the String methods that dispatch through Symbol.match /
replace / split / search / matchAll, lookaround, backreferences, case-insensitive Unicode folding,
property escapes, /v class-set operations, inline modifiers, RegExp.escape, the legacy RegExp.$n
statics, and String.prototype.normalize (which shares the Unicode data tables)."""

import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)

# A small value formatter: console.log does not inspect, and JSON.stringify hides `undefined`.
FMT = r'''
const fmt = (v) => v === undefined ? 'undefined' : v === null ? 'null'
  : Array.isArray(v) ? '[' + v.map(fmt).join(', ') + ']'
  : typeof v === 'string' ? JSON.stringify(v)
  : typeof v === 'object' ? '{' + Object.keys(v).map(k => k + ': ' + fmt(v[k])).join(', ') + '}'
  : String(v);
const showMatch = (m) => m === null ? 'null' : fmt([...m]) + ' @' + m.index
  + (m.groups !== undefined ? ' groups=' + fmt(m.groups) : '')
  + (m.indices ? ' indices=' + fmt([...m.indices]) + (m.indices.groups ? ' igroups=' + fmt(m.indices.groups) : '') : '');
const err = (f) => { try { return 'ok ' + fmt(f()); } catch (e) { return e.name + ': ' + e.message; } };
'''

TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
         pytest.param(["--tier=bytecode"], id="bytecode")]


def test_flags_source_and_tostring(run, workdir):
    r"""CATCHES: flags not reported in canonical "dgimsuvy" order, wrong per-flag getters, `source`
    not escaping "/" and line terminators (or escaping "/" inside a class), the empty pattern not
    rendering as (?:), and the %RegExp.prototype% special cases (undefined flags, "(?:)" source)
    versus the TypeError for other receivers; `get flags` must be generic over plain objects."""
    check_script(run, workdir, G, "flags_source_tostring", FMT + r'''
const r = /a/dgimsuy;
console.log(r.flags, r.source, String(r));
console.log([r.hasIndices, r.global, r.ignoreCase, r.multiline, r.dotAll, r.unicode, r.sticky, r.unicodeSets].join());
console.log(new RegExp('a', 'yusmigd').flags, new RegExp('[a]', 'vg').flags, /x/.flags === '');
console.log(String(new RegExp('a/b\nc\r\u2028\u2029')), new RegExp('').source, String(new RegExp('')));
console.log(new RegExp('[/]').source, new RegExp('\\/').source, String(new RegExp('\\\n')), String(/[/]\//));
console.log(fmt([RegExp.prototype.global, RegExp.prototype.source, RegExp.prototype.flags, String(RegExp.prototype)]));
const flagsGet = Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get;
console.log(flagsGet.call({ global: 1, sticky: 'y', unicodeSets: 0, hasIndices: true, dotAll: [] }));
console.log(err(() => Object.getOwnPropertyDescriptor(RegExp.prototype, 'global').get.call({})));
console.log(err(() => Object.getOwnPropertyDescriptor(RegExp.prototype, 'source').get.call({})));
console.log(err(() => flagsGet.call(1)));
console.log(err(() => RegExp.prototype.toString.call(1)));
console.log(RegExp.prototype.toString.call({ source: 'S', flags: 'F' }));
const own = /a/; Object.defineProperty(own, 'flags', { value: 'gi' });
console.log(String(own), own.global);
console.log(Object.prototype.toString.call(/a/), Object.getOwnPropertyNames(/a/).join(),
  JSON.stringify(Object.getOwnPropertyDescriptor(/a/, 'lastIndex')));
''')


def test_constructor_and_compile(run, workdir):
    r"""CATCHES: RegExp(re) not returning the same object when called without new and without flags,
    new RegExp(re, flags) not overriding flags, regexp-like objects (truthy Symbol.match) not having
    their source/flags read, wrong ToString of undefined/null/objects, lastIndex not reset to 0,
    and Annex-B compile() accepting flags with a RegExp argument or subclass instances."""
    check_script(run, workdir, G, "constructor_and_compile", FMT + r'''
const r1 = /ab+c/gi;
console.log(RegExp(r1) === r1, new RegExp(r1) === r1, RegExp(r1, 'm') === r1, String(new RegExp(r1, 'y')), String(RegExp(r1, '')));
const like = { [Symbol.match]: true, source: 'x.y', flags: 'gs', constructor: RegExp };
console.log(RegExp(like) === like, String(new RegExp(like)), String(new RegExp(like, 'i')));
console.log(String(new RegExp(undefined)), String(new RegExp(null)), String(new RegExp(123, undefined)),
  String(new RegExp({ toString() { return 'o'; } }, { toString() { return 'm'; } })));
const c = /a/g; c.lastIndex = 3; const c2 = new RegExp(c);
console.log(c2.lastIndex, c2.global, c2 !== c, c2.source);
console.log(String(r1.compile('q+', 'y')), r1.lastIndex, r1.sticky, r1.global);
console.log(String(r1.compile(/z/m)), String(r1.compile()));
console.log(err(() => r1.compile(/x/, 'g')));
class Sub extends RegExp {}
console.log(err(() => new Sub('a').compile('b')));
console.log(new Sub('a', 'g') instanceof Sub, String(new Sub('k', 'i')));
console.log(RegExp.length, RegExp.name, RegExp[Symbol.species] === RegExp, RegExp.prototype.exec.length,
  RegExp.prototype[Symbol.replace].name, RegExp.prototype[Symbol.split].length, RegExp.prototype[Symbol.matchAll].name);
''')


SYNTAX_ERRORS = r'''
const cases = [
  ['('], [')'], ['a**'], ['*a'], ['a{2,1}'], ['[b-a]'], ['a', 'gg'], ['a', 'x'], ['a', 'uv'], ['a', 'G'],
  ['\\k<x>(?<y>.)', 'u'], ['(?<a>.)(?<a>.)'], ['(?<1a>x)'], ['(?<a'], ['\\p{Foo}', 'u'], ['\\pL', 'u'],
  ['\\p{Lu', 'u'], ['\\p{Script=Foo}', 'u'], ['\\u{110000}', 'u'], ['\\c', 'u'], [']', 'u'], ['{', 'u'],
  ['\\1(a)\\2', 'u'], ['\\01', 'u'], ['\\-', 'u'], ['[\\z]', 'u'], ['\\u{12', 'u'], ['\\xZ', 'u'], ['\\uZZZZ', 'u'],
  ['[a&&&b]', 'v'], ['[a-z&&b]', 'v'], ['[a--b|c]', 'v'], ['[(]', 'v'], ['[a||b]', 'v'], ['[\\q{]', 'v'],
  ['[\\q]', 'v'], ['[a-\\d]', 'v'], ['[^\\p{RGI_Emoji}]', 'v'], ['\\P{RGI_Emoji}', 'v'], ['[\\q{a}]', 'u'],
  ['(?ii:a)'], ['(?-:a)'], ['(?x:a)'], ['(?i'], ['(?i-i:a)'], ['(?i)a'], ['(?<=a)*'], ['(?=a){2}', 'u'], ['a\\'],
  ['[a'], ['(?<n>a)\\k<m>'], ['(a{2})|(b{1001})'], ['(?:ab){1001}'], ['(?:ab){2,1001}'], ['x{2}{3}'],
];
for (const [p, f] of cases) {
  let r;
  try { new RegExp(p, f); r = 'compiles'; } catch (e) { r = e.name + ': ' + e.message; }
  console.log(JSON.stringify(p), f || '', '=>', r);
}
// Patterns that are legal (Annex B leniency without u, or valid in their mode).
for (const [p, f] of [['a{,2}'], ['\\p{Lu}'], ['(?=a){2}'], [']'], ['{'], ['\\c'], ['\\8'], ['(?i:a)(?-m:b)(?s-i:c)'], ['[\\q{a|bc}]', 'v'], ['x{99999999999}']]) {
  try { new RegExp(p, f); console.log('ok', p); } catch (e) { console.log('unexpected', p, e.message); }
}
// Regex literals are parsed at compile time: the error surfaces as a SyntaxError on eval.
try { eval('/(/'); } catch (e) { console.log('literal', e.name + ': ' + e.message); }
try { eval('/a/gg'); } catch (e) { console.log('literal', e.name + ': ' + e.message); }
'''


def test_syntax_error_messages(run, workdir):
    r"""CATCHES: accepting malformed patterns (unbalanced groups, bad quantifiers, out-of-order
    ranges, bad/duplicate/conflicting flags, unknown properties, bad escapes under u/v, illegal
    class-set syntax, malformed inline modifiers) or reporting them with different SyntaxError
    messages; also rejecting the Annex-B lenient forms that are legal without the u flag."""
    check_script(run, workdir, G, "syntax_errors", SYNTAX_ERRORS)


def test_uncaught_regexp_syntax_error_in_script(run, workdir):
    r"""CATCHES: an invalid regex literal in a script not being reported as an early SyntaxError
    (nothing before it may run) with the exact message on stderr and exit code 1."""
    check_script(run, workdir, G, "uncaught_literal_error", "console.log('before');\nconst r = /a{3,2}/;\n",
                 rc=1, stderr="Uncaught SyntaxError: numbers out of order in {} quantifier\n")


def test_last_index_semantics(run, workdir):
    r"""CATCHES: global/sticky regexes not advancing or resetting lastIndex (to the end of the match,
    0 on failure, 0 when lastIndex > length), non-global regexes reading lastIndex for the search
    start, sticky matches not anchored at lastIndex, lastIndex ToLength coercion via valueOf, and
    a non-writable lastIndex not throwing on update."""
    check_script(run, workdir, G, "last_index", FMT + r'''
const s = 'foo boo';
const g = /o/g; const out = []; let m;
while ((m = g.exec(s))) out.push(m.index + ':' + g.lastIndex);
console.log(out.join(' '), g.lastIndex);
const y = /o/y; y.lastIndex = 1;
console.log(y.test(s), y.lastIndex, y.test(s), y.lastIndex, y.test(s), y.lastIndex, y.test(s), y.lastIndex);
const ng = /o/; ng.lastIndex = 5; console.log(ng.exec(s).index, ng.lastIndex);
g.lastIndex = 100; console.log(g.exec(s), g.lastIndex);
g.lastIndex = 7; console.log(showMatch(/$/g.exec(s)), g.exec(s), g.lastIndex);
const v = /b/g; v.lastIndex = { valueOf() { console.log('valueOf ran'); return 4.9; } };
console.log(showMatch(v.exec('abcabc')), v.lastIndex);
v.lastIndex = -5; console.log(showMatch(v.exec('abcabc')), v.lastIndex);
v.lastIndex = '2'; console.log(showMatch(v.exec('abcabc')), v.lastIndex);
const sticky = /^a/my; sticky.lastIndex = 2; console.log(sticky.test('b\na'), sticky.lastIndex);
const stickyNoM = /^a/y; stickyNoM.lastIndex = 2; console.log(stickyNoM.test('b\na'), stickyNoM.lastIndex);
const u = /\udc00/gu; console.log(u.exec('\ud800\udc00\udc00')?.index, u.lastIndex);
const uu = /./gu; uu.lastIndex = 1; console.log(showMatch(uu.exec('\u{1F600}x')), uu.lastIndex);
const frozen = Object.defineProperty(/a/g, 'lastIndex', { writable: false, value: 0 });
console.log(err(() => frozen.exec('b')), err(() => frozen.test('a')));
const nonGlobalFrozen = Object.defineProperty(/a/, 'lastIndex', { writable: false, value: 0 });
console.log(err(() => nonGlobalFrozen.test('a')), err(() => nonGlobalFrozen.test('b')));
''')


def test_exec_result_shape_and_indices(run, workdir):
    r"""CATCHES: exec results with wrong index/input, defined values for unmatched captures, a
    groups object that is missing, has a prototype or drops unmatched names, and /d indices
    arrays (and indices.groups) with wrong UTF-16 offsets, especially after astral characters."""
    check_script(run, workdir, G, "exec_shape_indices", FMT + r'''
const m = /(?<y>\d{4})-(?<m>\d\d)(-(?<d>\d\d))?/d.exec('on 2024-05!');
console.log(showMatch(m));
console.log(m.input, Object.getPrototypeOf(m.groups), Object.getPrototypeOf(m.indices.groups), Array.isArray(m.indices), m.length);
console.log(Object.keys(m).join(), 'indices' in /a/.exec('a'), /a/.exec('a').groups);
console.log(showMatch(/(?<e>\u{1F600})(x)/du.exec('ab\u{1F600}x')));
console.log(showMatch(/(a)|(b)/d.exec('xb')));
console.log(showMatch(/(?:)/d.exec('')));
console.log(showMatch(/(?<=(?<pre>\$))\d+/d.exec('cost $42')));
console.log(fmt(/(.)(.)?/.exec('z').slice()), /x/.exec('y'));
console.log(showMatch(RegExp.prototype.exec.call(/b/y, 'abc')), showMatch(/b/.exec({ toString() { return 'xbx'; } })));
console.log(err(() => RegExp.prototype.exec.call({}, 'a')), '|', err(() => RegExp.prototype.test.call(1, 'a')));
''')


def test_replace_substitution_patterns(run, workdir):
    r"""CATCHES: wrong expansion of $1..$99 (two-digit refs falling back to one digit, $0 and
    out-of-range refs left literal), $<name> (unknown names -> empty, no named groups -> literal),
    $&, $`, $', $$ and a trailing lone $; first-only replacement for non-global regexes and
    lastIndex handling after a global replace."""
    check_script(run, workdir, G, "replace_substitutions", r'''
const s = 'John Smith, Jane Doe';
console.log(s.replace(/(\w+) (\w+)/g, '$2 $1'));
console.log(s.replace(/(?<first>\w+) (?<last>\w+)/, '$<last>, $<first> [$&] <$`> <$\'> $$ $0 $3 $10 $01 $<nope>|$'));
console.log('abc'.replace(/(b)/, '$<x>-$1$2'), 'abc'.replace(/b/, "$'$`$&"));
const many = /(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)/;
console.log('abcdefghijk'.replace(many, '$11-$10-$1-$111-$012-$00'));
console.log('abc'.replace('b', '[$&$`$\'$$]'), 'aaa'.replace('a', '$0'), 'x.y.z'.replace('.', '$'));
const re = /a/g; re.lastIndex = 3; console.log('aaaa'.replace(re, 'b'), re.lastIndex);
const st = /a/y; console.log('aab'.replace(st, 'x'), st.lastIndex, 'baa'.replace(st, 'x'), st.lastIndex, 'bba'.replace(st, 'x'), st.lastIndex);
const sg = /a/gy; console.log('aaba'.replace(sg, 'x'), sg.lastIndex);
console.log('xyz'.replace(/(?:)/g, '-'), '\u{1F600}'.replace(/(?:)/gu, '-'), '\u{1F600}'.replace(/(?:)/g, '-').length);
console.log('Price: 10 USD'.replace(/(?<amount>\d+) (?<cur>[A-Z]+)/, '$<cur>$<amount>'), 'ab'.replace(/(?<n>z)?b/, '[$<n>]'));
''')


def test_replace_with_function_and_replace_all(run, workdir):
    r"""CATCHES: replacer functions receiving the wrong arguments (captures, offset, whole string,
    and the groups object only when named groups exist), the return value not being stringified,
    replaceAll not requiring a global regex, replaceAll with a string pattern not replacing every
    occurrence / handling the empty pattern, and matchAll's non-global TypeError."""
    check_script(run, workdir, G, "replace_function_replace_all", FMT + r'''
console.log('aaa'.replace(/a/g, (m, off, str) => `[${m}${off}${str.length}]`));
console.log('x-1 y-22'.replace(/(?<k>\w)-(\d+)/g, (...args) => fmt(args)));
console.log('x-1'.replace(/(\w)-(z)?(\d)/, (...args) => fmt(args)));
console.log('abc'.replace(/b/, () => ({ toString() { return 'OBJ'; } })), 'abc'.replace(/b/, () => undefined), 'abc'.replace('c', (m, o, s) => o + s));
console.log('a.b.c'.replaceAll('.', '$&$&'), 'a.b.c'.replaceAll(/\./g, (m, o) => o), 'abc'.replaceAll('', '_'), 'aaaa'.replaceAll('aa', 'b'));
console.log(err(() => 'a'.replaceAll(/a/, 'b')), '|', err(() => 'a'.matchAll(/a/)));
console.log(err(() => 'a'.replaceAll({ [Symbol.match]: true, flags: 'i', [Symbol.replace]: () => 'x' }, 'b')));
console.log('a'.replaceAll({ [Symbol.match]: true, flags: 'g', [Symbol.replace]: (s, r) => s + r }, '!'));
let calls = 0; const counted = 'banana'.replace(/a/g, () => ++calls); console.log(counted, calls);
console.log('2+3=5'.replace(/(\d)\+(\d)=(\d)/, (m, a, b, c) => +a + +b === +c ? 'ok' : 'bad'));
''')


def test_split_with_captures_and_limits(run, workdir):
    r"""CATCHES: split dropping captured separators (or not inserting undefined for unmatched
    captures), ignoring/miscounting the limit (including captures in the count and ToUint32 of
    limit), splitting astral characters into surrogates under /u, wrong results for empty input
    and empty regexes, and a sticky flag leaking into split's matching."""
    check_script(run, workdir, G, "split_captures_limits", FMT + r'''
console.log(fmt('a1b2c3'.split(/\d/)), fmt('a1b2c3'.split(/(\d)/)), fmt('a1b2c3'.split(/(\d)/, 3)));
console.log(fmt('a,b;;c'.split(/([,;])(x)?/)));
console.log(fmt('abc'.split(/(?:)/)), fmt(''.split(/x/)), fmt(''.split(/(?:)/)), fmt('abc'.split(/(?:)/, 0)));
console.log(fmt('\u{1D7D8}\u{1D7D9}'.split(/(?:)/u)), fmt('\u{1D7D8}'.split(/(?:)/)));
console.log(fmt('aXbxc'.split(/x/i, 2)), fmt('test'.split(/(t)/)), fmt('a  b   c'.split(/\s+/)), fmt(' a '.split(/ /)));
console.log(fmt('a1b2'.split(/\d/y)), fmt('a1b2'.split(/(?=\d)/)), fmt('one two'.split(/(?<sep> )/)));
console.log(fmt('a,b,c'.split(/,/, -1)), fmt('a,b,c'.split(/,/, 2 ** 32 + 1)), fmt('a,b,c'.split(/,/, undefined)));
console.log(fmt('abc'.split(/b/g)), fmt('abcabc'.split(/(b)(c)/, 4)), fmt('aaa'.split(/a*/)), fmt('aaa'.split(/a*?/)));
''')


def test_match_matchall_search(run, workdir):
    r"""CATCHES: global match not collecting all matches (or returning [] instead of null), empty
    matches not advancing (infinite loop) or advancing by code unit instead of code point under
    /u, matchAll results lacking index/groups, search not ignoring the global flag and not
    restoring lastIndex, and String-argument coercion into a RegExp."""
    check_script(run, workdir, G, "match_matchall_search", FMT + r'''
console.log(fmt('a1b22c333'.match(/\d+/g)), 'abc'.match(/z/g), showMatch('abc'.match(/(b)(c)/)), showMatch('a.c'.match('.')));
console.log(fmt('aaa'.match(/a*?/g)), fmt('aaa'.match(/a*/g)), fmt('a\nb'.match(/^\w/gm)));
console.log(fmt('\u{1F600}\u{1F600}'.match(/(?:)/gu)), fmt('\u{1F600}\u{1F600}'.match(/(?:)/g)), fmt('\u{1F600}'.match(/./g).map(c => c.length)));
const all = [...'k1=v1;k22=v22'.matchAll(/(?<k>\w+)=(?<v>\w+)/g)];
for (const m of all) console.log(showMatch(m));
const it = 'xx'.matchAll(/x/g); console.log(Object.prototype.toString.call(it), typeof it.next, it[Symbol.iterator]() === it);
console.log(fmt([...'aXbX'.matchAll('X')].map(m => m.index)), fmt([...'\u{1F600}'.matchAll(/(?:)/gu)].map(m => m.index)));
const re = /x/g; re.lastIndex = 2; const copy = [...'x.x.x'.matchAll(re)].map(m => m.index); console.log(fmt(copy), re.lastIndex);
const sr = /b/g; sr.lastIndex = 2;
console.log('xAbcAbc'.search(/abc/i), 'abc'.search(/z/), 'abc'.search('c'), 'a.c'.search('.'), 'abab'.search(sr), sr.lastIndex, 'x'.search(), 'null'.search(null));
''')


def test_named_groups_and_backreferences(run, workdir):
    r"""CATCHES: duplicate group names not being allowed across alternatives (or the groups value
    coming from the wrong branch), \k<name> backreferences (also forward/self references that
    match empty), numbered backrefs to unmatched groups matching empty, case-insensitive backrefs,
    and \1-style escapes that are octal when no such group exists (Annex B)."""
    check_script(run, workdir, G, "named_groups_backrefs", FMT + r'''
console.log(showMatch(/(?<a>x)|(?<a>y)/.exec('zy')));
console.log(showMatch(/(?:(?<v>\d+)px|(?<v>\d+)em)-(?<unit>.)/.exec('12em-!')));
console.log(showMatch(/(?<n>a|b)\k<n>/.exec('xabba')), showMatch(/\k<n>(?<n>a)/.exec('a')));
console.log(showMatch(/(?<q>['"]).*?\k<q>/.exec(`say "hi 'x'" now`)));
console.log(showMatch(/(a)|\1b/.exec('b')), showMatch(/\1(a)/.exec('aa')), showMatch(/(?:(a)|b)\1/.exec('b')), showMatch(/(a)?\1x/.exec('x')));
console.log(showMatch(/(a)\1/i.exec('aA')), showMatch(/(\u03c3)\1/iu.exec('\u03c3\u03c2')), showMatch(/(k)\1/iu.exec('k\u212a')), /(k)\1/i.test('k\u212a'));
console.log(showMatch(/(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)\10/.exec('abcdefghijj')), showMatch(/(a)\10/.exec('a\x08')));
console.log(showMatch(/\1/.exec('\x01')), showMatch(/\8/.exec('8')), showMatch(/[\1]/.exec('\x01')), showMatch(/\k<x>/.exec('k<x>')));
console.log(Object.keys(/(?<\u{1D4D0}x>.)/u.exec('z').groups)[0].length, err(() => new RegExp('(?<\\u{1F600}>.)', 'u')), Object.keys(/(?<\u0061b>.)/.exec('z').groups)[0], Object.keys(/(?<$_\u200c>.)/.exec('z').groups)[0].length);
console.log(showMatch(/^(?:(a)|b)+$/.exec('ab')), showMatch(/(z)((a+)?(b+)?(c))*/.exec('zaacbbbcac')));
''')


def test_lookaround(run, workdir):
    r"""CATCHES: lookbehind restricted to fixed length, lookbehind captures not using right-to-left
    greedy semantics, negative lookarounds leaking captures, lookahead captures not being
    reusable by later backreferences, and assertions being quantifiable when they must not be."""
    check_script(run, workdir, G, "lookaround", FMT + r'''
console.log(showMatch(/(?<=\$)\d+(\.\d+)?/.exec('cost $42.50')), showMatch(/(?<!\$)\b\d+/.exec('$4 7')));
console.log(showMatch(/(?<=(\d+)(\d+))$/.exec('1053')), showMatch(/(?<=(\d+?)(\d+?))$/.exec('1053')));
console.log(showMatch(/(?<=\b[a-z]{2,5}\s+)\w+/.exec('so alpha beta')), showMatch(/(?<=^|,)\w+(?=,|$)/g.exec(',ab,cd')));
console.log(showMatch(/(?<=(?<!b)a)c/.exec('bac ac')), showMatch(/(?<=\1(a))b/.exec('aab')), showMatch(/(?<=([abc])+)x/.exec('abcx')));
console.log(showMatch(/(?=(a+))a*b\1/.exec('baaabac')), showMatch(/(?!(a))\1b/.exec('b')), showMatch(/(.*?)a(?!(a+)b\2c)\2(.*)/.exec('baaabaac')));
console.log(fmt('1234567.891'.replace(/\B(?<!\.\d*)(?=(\d{3})+(?!\d))/g, ',')), fmt('price: 30 EUR, 40 USD'.match(/\d+(?= USD)/g)));
console.log(fmt('xaxbxc'.match(/(?<=x)[a-z](?!b)/g)), fmt('\u{1F600}a'.match(/(?<=\u{1F600})./u)), fmt('ab'.match(/(?<=a)(?=b)/)));
console.log(showMatch(/(?<=a(?=b)b)c/.exec('abc')), showMatch(/(?<!^)x/.exec('xx')), showMatch(/(?<=[^\d])\d/i.exec('12a3')));
''')


def test_quantifiers_and_empty_iterations(run, workdir):
    r"""CATCHES: greedy/lazy quantifier mix-ups, wrong {n}/{n,}/{n,m} bounds, the ECMAScript
    empty-iteration rule (an optional iteration that matches empty fails), captures not reset at
    the start of each iteration, leftmost-alternative (not longest) semantics, and Annex-B literal
    braces such as a{,2}."""
    check_script(run, workdir, G, "quantifiers", FMT + r'''
console.log(showMatch(/a{2}/.exec('aaa')), showMatch(/a{2,}?/.exec('aaaa')), showMatch(/a{,2}/.exec('a{,2}')), showMatch(/x{2,3}?y/.exec('xxxy')));
console.log(showMatch(/<.+?>/.exec('<a><b>')), showMatch(/<.+>/.exec('<a><b>')), showMatch(/(a|ab)(c|bcd)(d*)/.exec('abcd')));
console.log(showMatch(/((a)|b)+/.exec('ab')), showMatch(/(a*)*b/.exec('aab')), showMatch(/(a*)+?/.exec('aa')), showMatch(/(?:a?)*?$/.exec('aa')));
console.log(showMatch(/(a*?)*/.exec('aa')), showMatch(/(?:a|())*/.exec('aab')), showMatch(/(?:()|a)*/.exec('aab')), showMatch(/(a|b)*?c/.exec('abac')));
console.log(showMatch(/(\d{1,3})(?:,(\d{3}))*/.exec('1,234,567')), showMatch(/^(?:(\w)(\d)?)+$/.exec('a1b')), showMatch(/x*y+$/.exec('xxyyz yy')));
console.log(showMatch(/a{0}b/.exec('ab')), showMatch(/a{3,3}/.exec('aa')), showMatch(/(?:ab){2,}/.exec('abababx')), showMatch(/a??b/.exec('ab')), showMatch(/[a-c]{2,}?d/.exec('abcd')));
console.log(showMatch(/a{1/.exec('a{1')), showMatch(/a{1,2/.exec('a{1,2')), showMatch(/}/.exec('}')), showMatch(/]/.exec(']')), showMatch(/x{2}{/.exec('xx{')));
console.log('x'.repeat(2000).match(/x{2,1500}/)[0].length, /^(?:ab){1000}$/.test('ab'.repeat(1000)), /^a{3,}$/.test('a'.repeat(100000)));
''')


def test_pathological_patterns_finish(run, workdir):
    r"""CATCHES: a naive exponential backtracker that hangs (or stack-overflows) on nested
    quantifiers that cannot match, long single-character runs, and alternations whose first
    branch is a prefix of the second; every result here is the spec-correct answer and must be
    computed well within the test timeout."""
    check_script(run, workdir, G, "pathological", FMT + r'''
console.log(/(a+)+b/.exec('a'.repeat(22) + 'c'));
console.log(/^(\w+\s?)*$/.test('a few words to make this slow without memoization!'));
console.log(/(x+x+)+y/.test('x'.repeat(18)));
console.log(/^(a|aa)+$/.test('a'.repeat(40) + 'b'));
const hit = /(a+)+b/.exec('a'.repeat(22) + 'b'); console.log(hit[0].length, hit[1].length, hit.index);
console.log(/\s+$/.test('a' + ' '.repeat(3000) + 'a'), /\s+$/.test('a' + ' '.repeat(3000)));
console.log('ab'.repeat(5000).replace(/b/g, '').length, 'x'.repeat(50000).split(/(?:)/).length, /^[\s\S]*z$/.test('y'.repeat(100000) + 'z'));
console.log(/(?:a|b)*c/.test('ab'.repeat(200) + 'c'), /((ab)*)*c/.test('ab'.repeat(200) + 'c'));
''')


def test_backtracking_budget_gives_up(run, workdir):
    r"""CATCHES: an engine without the reference's bounded backtracking budget: the classic
    exponential (?:a?){n}a{n} pattern succeeds for small n, but once the step budget is exhausted
    the reference reports NO match (null/false) quickly instead of hanging or finding the match
    (surprising, non-spec behaviour pinned deliberately)."""
    check_script(run, workdir, G, "backtracking_budget", r'''
for (const n of [5, 10, 15]) console.log(n, new RegExp('^(?:a?){' + n + '}a{' + n + '}$').test('a'.repeat(n)));
console.log(25, /^(?:a?){25}a{25}$/.test('a'.repeat(25)));
console.log('ok' + 'a'.repeat(25).replace(/^(?:a?){25}a{25}$/, 'X').length);
''')


def test_case_insensitive_unicode_folding(run, workdir):
    r"""CATCHES: case-insensitive matching that uses toLowerCase or full case folding instead of the
    spec's Canonicalize: without u it uses toUpperCase and never maps non-ASCII to ASCII (Kelvin
    sign, long s), with u it uses simple case folding (K~k~Kelvin, s~long s, sharp s ~ capital
    sharp s, all three sigmas, Deseret), Turkish dotted/dotless i never fold to i, and \w/\b
    under /iu."""
    check_script(run, workdir, G, "case_folding", r'''
const t = (re, s) => re.test(s) ? 1 : 0;
console.log('kelvin', t(/\u212a/i, 'k'), t(/\u212a/iu, 'k'), t(/\u212a/iu, 'K'), t(/k/i, '\u212a'), t(/[a-z]/iu, '\u212a'), t(/[a-z]/i, '\u212a'), t(/[^k]/iu, '\u212a'));
console.log('sigma', t(/\u03c3/i, '\u03a3'), t(/\u03c3/i, '\u03c2'), t(/\u03c2/iu, '\u03a3'), t(/\u03a3/i, '\u03c2'), 'ΣΑΣ σας'.replace(/σ/gi, 'x'));
console.log('turkish', t(/i/i, '\u0130'), t(/i/iu, '\u0130'), t(/\u0131/i, 'I'), t(/\u0131/iu, 'I'), t(/I/iu, '\u0131'), t(/\u0130/iu, '\u0069\u0307'));
console.log('sharp s', t(/\u00df/i, '\u1e9e'), t(/\u00df/iu, '\u1e9e'), t(/\u00df/iu, 'ss'), t(/\u017f/i, 's'), t(/\u017f/iu, 's'), t(/\u017f/iu, 'S'));
console.log('titlecase', t(/\u01c5/iu, '\u01c4'), t(/\u01c5/iu, '\u01c6'), t(/\u01c5/i, '\u01c6'), t(/\u01c6/i, '\u01c5'), t(/\u00b5/i, '\u03bc'), t(/\u00b5/iu, '\u039c'));
console.log('astral', t(/\u{10400}/iu, '\u{10428}'), t(/[\u{10400}-\u{10410}]/iu, '\u{10430}'), t(/\u{10400}/i, '\u{10428}'), t(/\u{1E900}/iu, '\u{1E922}'));
console.log('classes', t(/\w/iu, '\u017f'), t(/\w/i, '\u017f'), t(/\W/iu, '\u017f'), t(/\W/iu, '\u212a'), t(/[\W]/iu, 'S'), t(/\bK/iu, '\u212a'));
console.log('ranges', t(/[\u00e0-\u00fe]/i, '\u00c0'), t(/[A-Z]/i, '\u00ff'), t(/[\u0390-\u03a0]/i, '\u03b2'), t(/[^a-z]/i, 'Q'), 'ΆΈ'.match(/[ά-έ]/giu).length);
console.log('latin', t(/\u00e9/i, '\u00c9'), t(/\u0101/i, '\u0100'), t(/\u1e9b/i, '\u1e60'), t(/\u1e9b/iu, '\u1e61'), t(/\u2126/iu, '\u03c9'), t(/\u2126/i, '\u03c9'));
''')


def test_unicode_property_escapes(run, workdir):
    r"""CATCHES: missing or wrong Unicode property tables for General_Category (long/short names
    and gc=/General_Category=), Script and Script_Extensions, binary properties (ASCII, Any,
    Assigned, Emoji, White_Space, ...), \P negation and negated classes under /i, and accepting
    non-canonical or misspelled property names (properties are case-sensitive)."""
    check_script(run, workdir, G, "property_escapes", r'''
const t = (re, s) => re.test(s) ? 1 : 0;
console.log('gc', t(/\p{Lu}/u, 'É'), t(/\p{Lu}/u, 'é'), t(/\P{Lu}/u, 'é'), t(/\p{L}/u, '中'), t(/\p{N}/u, '٣'), t(/\p{Nd}/u, 'Ⅷ'), t(/\p{Nl}/u, 'Ⅷ'), t(/\p{General_Category=Decimal_Number}/u, '5'), t(/\p{gc=Pd}/u, '-'), t(/\p{Uppercase_Letter}/u, 'Ω'), t(/\p{Cn}/u, '\u0378'), t(/\p{Co}/u, '\ue000'), t(/\p{Cs}/u, '\ud800'), t(/\p{Zs}/u, '\u3000'), t(/\p{Sm}/u, '+'), t(/\p{Sc}/u, '€'));
console.log('script', t(/\p{Script=Greek}/u, 'λ'), t(/\p{sc=Cyrillic}/u, 'ж'), t(/\p{sc=Han}/u, '字'), t(/\p{Script=Hiragana}/u, 'ア'), t(/\p{sc=Arab}/u, 'ب'), t(/\p{Script=Latin}/u, '·'), t(/\p{Script_Extensions=Latin}/u, 'a'), t(/\p{scx=Deva}/u, '।'), t(/\p{sc=Deva}/u, '।'), t(/\p{sc=Zyyy}/u, '1'));
console.log('binary', t(/\p{Emoji}/u, '😀'), t(/\p{Emoji_Presentation}/u, '#'), t(/\p{Emoji}/u, '#'), t(/\p{ASCII}/u, '~'), t(/\p{ASCII}/u, '\x80'), t(/\p{Any}/u, '\u{10ffff}'), t(/\p{Assigned}/u, '\u0378'), t(/^\p{White_Space}+$/u, ' \t\u00a0\u2028'), t(/\p{Lowercase}/u, 'ª'), t(/\p{ID_Start}/u, '$'), t(/\p{ID_Continue}/u, '\u200c'), t(/\p{Alphabetic}/u, 'ⓐ'), t(/\p{Extended_Pictographic}/u, '©'), t(/\p{Regional_Indicator}/u, '🇦'));
console.log('case-insensitive', t(/\p{Lu}/iu, 'a'), t(/\P{Lu}/iu, 'A'), t(/[^\P{Lu}]/iu, 'a'), t(/\p{Ll}/iu, 'A'), t(/^\p{Lu}+$/iv, 'abc'), t(/[\p{Lu}--[a-z]]/iv, 'q'));
console.log('without u', t(/\p{Lu}/, 'p{Lu}'), t(/\pL/, 'pL'), t(/\P{L}/, 'P{L}'));
console.log('classes', '\u0391b\u03b3D'.match(/[\p{Lu}\d]/gu).join(), 'a1٢३'.replace(/\p{Nd}/gu, '#'), 'Hello Мир 世界'.match(/\p{sc=Cyrl}+|\p{sc=Hani}+/gu).join('|'));
for (const p of ['\\p{Script=Foo}', '\\p{sc}', '\\p{Lu=x}', '\\p{General_Category}', '\\p{ascii}', '\\p{lu}', '\\p{gc=Lu', '\\p{Script_Extensions}', '\\p{RGI_Emoji}', '\\p{Block=Basic_Latin}', '\\p{ General_Category=Lu}']) {
  try { new RegExp(p, 'u'); console.log('ok', p); } catch (e) { console.log(p, '=>', e.message); }
}
''')


def test_unicode_mode_escapes_and_code_points(run, workdir):
    r"""CATCHES: \u{...} escapes not decoding (or meaning u-repeat without the u flag), surrogate
    pairs not being one element under /u (dot, classes, ranges, lone-surrogate matching), legacy
    escapes (\x, \c, \0, octal, identity) decoding wrongly, \s missing a JS whitespace code point,
    and \d/\w becoming Unicode-aware under /u (they must stay ASCII)."""
    check_script(run, workdir, G, "unicode_escapes", FMT + r'''
const t = (re, s) => re.test(s) ? 1 : 0;
console.log(t(/\u{61}/u, 'a'), t(/^\u{2}$/, 'uu'), t(/\u{1F600}/u, '\u{1F600}'), t(/^\u{1F600}$/u, '\ud83d\ude00'), t(/^\ud83d\ude00$/u, '\u{1F600}'), t(/^[\ud83d\ude00]$/u, '\u{1F600}'), t(/^[\ud83d\ude00]$/, '\u{1F600}'));
console.log(t(/\x41/, 'A'), t(/\x4/, 'x4'), t(/\cJ/, '\n'), t(/\c1/, '\\c1'), t(/[\c1]/, '\x11'), t(/[\c_]/, '\x1f'), t(/\0/, '\0'), t(/\01/, '\x01'), t(/\101/, 'A'), t(/\8/, '8'), t(/\a/, 'a'), t(/\-/, '-'), t(/[\-]/u, '-'));
console.log('\u{1F600}'.match(/./u)[0].length, '\u{1F600}'.match(/./)[0].length, t(/^.$/u, '\u{1F600}'), t(/^.$/, '\u{1F600}'), t(/^[\u{1F600}-\u{1F64F}]$/u, '\u{1F60A}'), t(/\ud83d/u, '\u{1F600}'), t(/\ud83d/, '\u{1F600}'), t(/^[^x]$/u, '\ud800'), t(/\udc00/u, '\ud800\udc00'), t(/^\S$/u, '\u{1F600}'));
console.log(showMatch(/[\u{1F600}-\u{1F602}]+/u.exec('x\u{1F600}\u{1F601}\u{1F602}\u{1F603}')), showMatch(/\udc00/u.exec('\ud800\udc00\udc00')), showMatch(/^[^a]/.exec('\u{1F600}')));
console.log(fmt(' \t\n\v\f\r\u00a0\u1680\u2000\u200a\u2028\u2029\u202f\u205f\u3000\ufeff\u180e\u200b'.match(/\s/g).map(c => c.charCodeAt(0).toString(16))));
console.log(t(/\d/u, '\u0663'), t(/\w/u, '\u00e9'), t(/\b/u, '\u00e9'), t(/[\d]/v, '\u0663'), fmt('a_1é'.match(/\w/g)));
console.log(showMatch(/[^]/.exec('\n')), showMatch(/[]/.exec('a')), showMatch(/[-a]/.exec('-')), showMatch(/[\d-x]/.exec('-')), showMatch(/[\w-]+/.exec('a-b_c!')), showMatch(/[\b]/.exec('a\bc')), showMatch(/\bfoo\B/.exec('foo foox')));
''')


def test_dotall_multiline_anchors(run, workdir):
    r"""CATCHES: `.` matching line terminators without /s (or missing \r, U+2028, U+2029), ^/$
    matching at line boundaries without /m, $ matching before a trailing newline (it must not),
    empty multiline matches advancing incorrectly, and \b/\B at string edges."""
    check_script(run, workdir, G, "dotall_multiline", FMT + r'''
console.log(showMatch(/^.$/su.exec('\n')), showMatch(/^.$/.exec('\u2028')), showMatch(/^.$/.exec('\u2029')), showMatch(/^.$/s.exec('\r')), showMatch(/^.$/.exec('\r')), showMatch(/^.$/.exec('\v')));
console.log(showMatch(/^b$/m.exec('a\nb\nc')), showMatch(/^b$/.exec('a\nb\nc')), showMatch(/a$/.exec('a\n')), showMatch(/a$/m.exec('a\u2028')), showMatch(/^$/gm.exec('a\n\nb')));
console.log(fmt('a\r\nb\u2028c'.split(/^/m)), fmt('l1\nl2\r\nl3'.match(/^l\d$/gm)), fmt('ab\ncd'.match(/.$/gm)), fmt('\n\n'.match(/^/gm)));
console.log(fmt('x y'.match(/\b/g)), fmt('ab cd'.replace(/\B/g, '-')), fmt(''.match(/\b/)), fmt(''.match(/\B/)), fmt('!'.replace(/\B/g, '_')));
const re = /^.+$/gms; console.log(fmt('one\ntwo'.match(re)), re.dotAll, re.multiline);
''')


def test_class_set_operations_v_flag(run, workdir):
    r"""CATCHES: /v class sets without difference (--), intersection (&&), nested classes, \q{...}
    string alternatives (longest string must win, regardless of listed order), multi-code-point
    matches under /g, case-insensitive \q strings, and negation of classes containing only single
    code points."""
    check_script(run, workdir, G, "class_sets_v", FMT + r'''
const t = (re, s) => re.test(s) ? 1 : 0;
console.log(t(/^[\p{L}--[a-z]]$/v, 'a'), t(/^[\p{L}--[a-z]]$/v, 'A'), t(/^[\p{Script=Greek}&&\p{Ll}]$/v, 'λ'), t(/^[\p{Script=Greek}&&\p{Ll}]$/v, 'Λ'));
console.log(t(/[[a-z]--[aeiou]]/v, 'e'), t(/[[a-z]--[aeiou]]/v, 'f'), t(/[\w&&\d]/v, 'a'), t(/[\w&&\d]/v, '3'), t(/[^\d]/v, '3'), t(/[[abc][def]]/v, 'e'), t(/[\p{ASCII}--\p{L}--\p{N}]/v, 'a'), t(/[\p{ASCII}--\p{L}--\p{N}]/v, '!'), t(/[[a-z]&&[k-p]&&[^m]]/v, 'm'), t(/[[a-z]&&[k-p]&&[^m]]/v, 'n'));
console.log(t(/^[\q{abc|d}x]$/v, 'abc'), t(/^[\q{abc|d}x]$/v, 'ab'), t(/^[\q{abc|d}x]+$/v, 'abcxd'), t(/[\q{KK}]/vi, 'kk'), t(/[^\q{a}]/v, 'b'), t(/^[\q{}]$/v, ''), t(/^[\p{Lu}&&\p{Script=Latin}]$/vi, 'é'));
console.log(fmt('xabcy'.match(/[\q{a|abc|ab}]/v)), fmt('xabcyab'.match(/[\q{a|abc|ab}]/gv)), fmt('xyzxy'.match(/[\q{xy|xyz}--\q{xyz}]/gv)), fmt('aab'.match(/[\q{aa|b}&&\q{aa}]/gv)));
console.log(fmt('a-b.c'.split(/[\p{P}--[.]]/v)), fmt('\u{1F600}x'.match(/[^x]/v)), fmt('café'.match(/[\p{L}--\p{ASCII}]/gv)));
''')


def test_emoji_string_properties_v_flag(run, workdir):
    r"""CATCHES: missing /v properties of strings (RGI_Emoji, Basic_Emoji, Emoji_Keycap_Sequence,
    RGI_Emoji_Flag/Modifier/Tag/ZWJ_Sequence) or matching them code point by code point instead
    of as whole sequences (ZWJ families, flags, skin tones, keycaps, tag sequences)."""
    check_script(run, workdir, G, "emoji_properties_v", FMT + r'''
const t = (re, s) => re.test(s) ? 1 : 0;
const fam = '\u{1F468}\u200d\u{1F469}\u200d\u{1F467}';
const all = (re, s) => fmt(s.match(re));
console.log(t(/^\p{RGI_Emoji}$/v, fam), t(/^\p{RGI_Emoji}$/v, '❤\ufe0f'), t(/^\p{RGI_Emoji}$/v, '\u{1F1EB}\u{1F1F7}'), all(/\p{RGI_Emoji}/gv, 'a' + fam + 'b'), all(/\p{RGI_Emoji}/gv, 'plain text'));
console.log(t(/^\p{Basic_Emoji}$/v, '\u{1F600}'), t(/^\p{Basic_Emoji}$/v, '⌚'), t(/^\p{Basic_Emoji}$/v, '❤\ufe0f'), t(/^\p{Basic_Emoji}$/v, '❤'), t(/^\p{Basic_Emoji}$/v, 'a'), all(/\p{Basic_Emoji}/gv, '⌚ ❤\ufe0f ❤ #'));
console.log(t(/^\p{Emoji_Keycap_Sequence}$/v, '1\ufe0f\u20e3'), t(/^\p{Emoji_Keycap_Sequence}$/v, '1\u20e3'), all(/\p{Emoji_Keycap_Sequence}/gv, '#\ufe0f\u20e3 *\ufe0f\u20e3 2\u20e3 9'));
console.log(t(/^\p{RGI_Emoji_Flag_Sequence}$/v, '\u{1F1EF}\u{1F1F5}'), t(/^\p{RGI_Emoji_Flag_Sequence}$/v, '\u{1F1E6}\u{1F1E6}'), all(/\p{RGI_Emoji_Flag_Sequence}/gv, '\u{1F1EF}\u{1F1F5}\u{1F1E6}\u{1F1E6}\u{1F1FA}\u{1F1F8}'));
console.log(t(/^\p{RGI_Emoji_Modifier_Sequence}$/v, '\u{1F44D}\u{1F3FD}'), t(/^\p{RGI_Emoji_Modifier_Sequence}$/v, '\u{1F44D}'), all(/\p{RGI_Emoji_Modifier_Sequence}/gv, 'a\u{1F44D}\u{1F3FD}\u{1F44D}\u{1F3FF}'));
console.log(t(/^\p{RGI_Emoji_Tag_Sequence}$/v, '\u{1F3F4}\u{E0067}\u{E0062}\u{E0073}\u{E0063}\u{E0074}\u{E007F}'), t(/^\p{RGI_Emoji_Tag_Sequence}$/v, '\u{1F3F4}'));
console.log(t(/^\p{RGI_Emoji_ZWJ_Sequence}$/v, '\u{1F469}\u200d\u{1F4BB}'), t(/^\p{RGI_Emoji_ZWJ_Sequence}$/v, fam), all(/\p{RGI_Emoji_ZWJ_Sequence}/gv, '\u{1F469}\u200d\u{1F4BB} \u{1F469}'));
console.log(fmt('I ❤\ufe0f \u{1F1EB}\u{1F1F7} and \u{1F469}\u{1F3FE}\u200d\u{1F680}! #\ufe0f\u20e3'.match(/\p{RGI_Emoji}/gv)));
console.log(fmt(('x' + fam + 'y').replace(/\p{RGI_Emoji}/gv, '<E>')), ('x' + fam).match(/\p{RGI_Emoji}/v)[0].length, ('x' + fam).search(/\p{RGI_Emoji}/v), /\p{RGI_Emoji}/v.test('plain text'));
console.log(fmt(('a' + fam).match(/[\p{RGI_Emoji_ZWJ_Sequence}\q{a}]/gv).map(s => s.length)), fmt(('a' + fam).match(/[\p{Basic_Emoji}&&\p{Emoji_Presentation}]/gv)), fmt(('\u{1F600}' + fam).match(/[\p{Basic_Emoji}--\q{\u{1F600}}]/gv)));
''')


def test_inline_modifiers(run, workdir):
    r"""CATCHES: missing support for (?i:...), (?-i:...), (?m:...), (?s:...) and combinations,
    modifiers leaking outside their group (into later backreferences or atoms), and accepting
    malformed modifier groups."""
    check_script(run, workdir, G, "inline_modifiers", FMT + r'''
const t = (re, s) => re.test(s) ? 1 : 0;
console.log(t(/a(?i:b)c/, 'aBc'), t(/a(?i:b)c/, 'aBC'), t(/(?i:a(?-i:b))/, 'Ab'), t(/(?i:a(?-i:b))/, 'AB'), t(/(?-i:a)b/i, 'aB'), t(/(?-i:a)b/i, 'AB'));
console.log(t(/(?m:^b)/, 'a\nb'), t(/^b/, 'a\nb'), t(/(?s:.)/, '\n'), t(/(?-s:.)/s, '\n'), t(/(?i-m:^A)/m, 'x\na'), t(/(?ims:x)/, 'X'), t(/(?m-s:.$)/s, 'a\nb'));
console.log(t(/(?i:\u212a)/u, 'k'), t(/(?i:[a-c])/, 'B'), t(/(?i:\b)/, ''), t(/(?i:(a))\1/, 'Aa'), t(/(?i:(a))\1/, 'AA'), t(/(?i:(a)\1)/, 'Aa'), t(/(?i:\p{Lu})/u, 'q'));
console.log(showMatch(/(?i:(?<w>[a-z]+))-\k<w>/.exec('ABC-ABC abc-ABC')), fmt('aAbB'.match(/(?i:a)|b/g)));
''')


def test_regexp_escape(run, workdir):
    r"""CATCHES: RegExp.escape missing or escaping the wrong characters: a leading ASCII
    alphanumeric must become \xNN, syntax characters get a backslash, other punctuation and
    whitespace use \xNN/\uNNNN, lone surrogates are \u-escaped, and non-strings throw."""
    check_script(run, workdir, G, "regexp_escape", FMT + r'''
console.log(RegExp.escape('foo.bar*baz?'));
console.log(RegExp.escape('1+1=2'), RegExp.escape('a-b c\n\t,'), RegExp.escape('_x'), RegExp.escape(''));
console.log(RegExp.escape('^$\\.*+?()[]{}|/'), RegExp.escape(',-=<>#&!%:;@~\'`"'));
console.log(RegExp.escape('\u2028\u00e9\u{1F600}\ud800\ufeff\u00a0\v\f\r'));
console.log(RegExp.escape('Zebra9'), RegExp.escape('9lives'), RegExp.escape('\u00e9t\u00e9'));
const re = new RegExp('^' + RegExp.escape('(1+2)*3=[x]') + '$'); console.log(re.test('(1+2)*3=[x]'), re.source);
console.log(err(() => RegExp.escape(1)), '|', err(() => RegExp.escape(new String('a'))), RegExp.escape.length);
''')


def test_symbol_protocol_overrides(run, workdir):
    r"""CATCHES: String.prototype.match/replace/split/search/matchAll/replaceAll not dispatching to
    a custom Symbol.* method, subclass `exec` overrides being bypassed by the built-in
    algorithms, IsRegExp (Symbol.match) not being honoured by startsWith/includes, and the
    regexp-protocol methods not working on plain objects with an `exec` method."""
    check_script(run, workdir, G, "symbol_overrides", FMT + r'''
const fake = { [Symbol.match](s) { return ['M:' + s]; }, [Symbol.replace](s, r) { return 'R:' + s + r; }, [Symbol.split](s, l) { return ['S', s, l]; }, [Symbol.search](s) { return 42; } };
console.log('abc'.match(fake)[0], 'abc'.replace(fake, '!'), 'abc'.split(fake, 3).join('|'), 'abc'.search(fake));
console.log('abc'.replaceAll({ [Symbol.replace]: (s, r) => s + r + r }, '?'), 'abc'.matchAll({ [Symbol.matchAll]: s => 'MA' }));
class MyRe extends RegExp { exec(s) { const r = super.exec(s); if (r) r[0] = r[0].toUpperCase(); return r; } }
console.log('a-b-c'.replace(new MyRe('[a-c]', 'g'), '<$&>'), new MyRe('b').test('abc'), 'xbx'.match(new MyRe('b'))[0], fmt('a1b2'.split(new MyRe('\\d'))));
const nomatch = /x/; nomatch[Symbol.match] = false; console.log('/x/'.startsWith(nomatch), '/x/'.includes(nomatch), '/x/'.endsWith(nomatch));
console.log(err(() => 'a'.startsWith(/a/)), '|', err(() => 'a'.includes({ [Symbol.match]: 1 })));
const obj = { exec(s) { return { 0: 'zz', length: 1, index: 0 }; } }; console.log(RegExp.prototype.test.call(obj, 'q'), RegExp.prototype[Symbol.match].call({ exec: () => null, flags: '' }, 'q'));
console.log(err(() => RegExp.prototype[Symbol.match].call({ exec: () => 5 }, 'q')));
const log = []; const spy = new Proxy(/b/g, { get(tg, k) { const v = Reflect.get(tg, k); if (typeof k === 'string') log.push(k); return typeof v === 'function' ? v.bind(tg) : v; } });
RegExp.prototype[Symbol.replace].call(spy, 'abcb', 'X'); console.log(log.join(','));
let n = 0; class Counting extends RegExp { exec(s) { n++; return super.exec(s); } }
'aaa'.replace(new Counting('a', 'g'), 'b'); 'a,b'.split(new Counting(',')); console.log('exec calls', n);
''')


def test_legacy_static_properties(run, workdir):
    r"""CATCHES: missing Annex-B RegExp.$1-$9, lastMatch/$&, lastParen/$+, leftContext/$`,
    rightContext/$', input/$_ statics, not updating them after replace/test/split, a settable
    input, and the receiver brand check on the accessors."""
    check_script(run, workdir, G, "legacy_statics", FMT + r'''
/(\d+)-(\d+)/.exec('tel 555-1234 ok');
console.log(fmt([RegExp.$1, RegExp.$2, RegExp.$3, RegExp.lastMatch, RegExp['$&'], RegExp.leftContext, RegExp['$`'], RegExp.rightContext, RegExp["$'"], RegExp.lastParen, RegExp['$+'], RegExp.input, RegExp['$_']]));
'xyz'.replace(/y/, '');
console.log(fmt([RegExp.lastMatch, RegExp.leftContext, RegExp.rightContext, RegExp.$1, RegExp.lastParen]));
/(a)|(b)/.test('b'); console.log(fmt([RegExp.$1, RegExp.$2, RegExp.lastParen]));
/nomatch/.test('zzz'); console.log(fmt([RegExp.lastMatch, RegExp.input]));
RegExp.input = 'set'; console.log(RegExp.input, RegExp.$_);
console.log(err(() => Object.getOwnPropertyDescriptor(RegExp, '$1').get.call({})));
const d = Object.getOwnPropertyDescriptor(RegExp, '$1'); console.log(typeof d.get, d.set, d.enumerable, d.configurable);
console.log(typeof Object.getOwnPropertyDescriptor(RegExp, 'input').set, 'lastMatch' in RegExp, Object.keys(RegExp).length);
''')


@pytest.mark.parametrize("cli", TIERS)
def test_regexp_results_identical_across_tiers(run, workdir, cli):
    r"""CATCHES: a JIT/bytecode fast path for exec/test/replace/split in hot loops (including
    discarded results) that skips updating lastIndex or the legacy RegExp statics, or produces
    different matches from the reference interpreter tier."""
    src = r'''
function run() {
  const re = /(\d+)([a-z])/g;
  const out = [];
  for (let i = 0; i < 300; i++) {
    re.lastIndex = 0;
    re.exec('x' + i + 'q tail');
    if (i % 100 === 7) out.push(RegExp.$1 + RegExp.$2 + ':' + RegExp.lastMatch + ':' + RegExp.rightContext + ':' + re.lastIndex);
    'a-b-c'.replace(/-/g, '+');
    if (i % 100 === 8) out.push(RegExp.lastMatch + RegExp.leftContext);
    'k1=v1;k2=v2'.split(/[=;]/);
    /z(\w)/.test('az' + (i % 10));
    if (i % 100 === 9) out.push(RegExp.$1 + RegExp.input);
    const m = /(?<w>[a-z])(\d)/.exec('..b' + (i % 7));
    if (i % 150 === 0) out.push(m.groups.w + m[2] + m.index);
    'a1b22c'.split(/(\d+)/y);
    if (i % 100 === 11) out.push('sticky-split ' + RegExp.lastMatch + ' ' + RegExp.$1 + ' ' + RegExp.leftContext);
    ''.split(/(x?)/);
    if (i % 100 === 12) out.push('empty-split ' + JSON.stringify(RegExp.lastMatch) + ' ' + JSON.stringify(RegExp.input));
    'q-r'.split(/(-)/, 1);
    if (i % 100 === 13) out.push('limited ' + RegExp.lastMatch + RegExp.rightContext);
    'mississippi'.split(/s+/);
    if (i % 100 === 14) out.push('plain ' + RegExp.leftContext + '|' + RegExp.rightContext);
    'aXbX'.replace(/x/gi, 'y');
    if (i % 100 === 15) out.push('replace ' + RegExp.leftContext + '|' + RegExp.lastMatch);
    'a\u{1F600}'.replace(/(?:)/gu, '');
    if (i % 100 === 16) out.push('empty-replace ' + JSON.stringify(RegExp.leftContext));
  }
  let total = 0;
  for (let i = 0; i < 500; i++) total += 'aXbXc'.split(/x/i).length + 'hello world'.replace(/o/g, '0').length + (/l+/.test('hello') ? 1 : 0);
  out.push(total);
  return out;
}
console.log(run().join('\n'));
'''
    check_script(run, workdir, G, "tier_consistency", src, cli=cli)


def test_string_normalize(run, workdir):
    r"""CATCHES: String.prototype.normalize missing composition/decomposition data (canonical
    reordering of combining marks, Hangul syllable algorithmic (de)composition, compatibility
    mappings for NFKC/NFKD, composition exclusions), a wrong default form, and the RangeError
    for unknown forms."""
    check_script(run, workdir, G, "normalize", FMT + r'''
const cps = (s) => [...s].map(c => c.codePointAt(0).toString(16)).join(' ');
for (const s of ['\u00e9', 'e\u0301', '\u1e9b\u0323', '\u212b', '\u00c5', 'a\u0323\u0302', 'a\u0302\u0323', '\ufb01', '\u2460', '\u1100\u1161\u11a8', '\ud55c', '\u0958', '\u2126', '\u00bd', 'x\u0300\u0301', '\u0344', '\u{1D15E}', '\u3060']) {
  console.log(cps(s), '|', ['NFC', 'NFD', 'NFKC', 'NFKD'].map(f => cps(s.normalize(f))).join(' | '));
}
console.log('\u00e9'.normalize() === '\u00e9'.normalize('NFC'), 'e\u0301'.normalize().length, ''.normalize('NFKD') === '', 'abc'.normalize(undefined));
console.log(err(() => 'a'.normalize('nfc')), '|', err(() => 'a'.normalize(null)), '|', err(() => String.prototype.normalize.call(null)));
''')


def test_custom_exec_results_drive_replace(run, workdir):
    r"""CATCHES: RegExp.prototype[Symbol.replace] trusting the shape of a user `exec` result: the
    position must be clamped (negative/NaN -> 0, past the end -> end), out-of-order results are
    skipped, captures and `0` are ToString'ed, `groups: null` is a TypeError for string
    replacements while a primitive groups value is boxed, and functional replacers get the groups
    object as their last argument."""
    check_script(run, workdir, G, "custom_exec_replace", r"""
const fmt = (v) => JSON.stringify(v);
const err = (f) => { try { return 'ok ' + fmt(f()); } catch (e) { return e.name + ': ' + e.message; } };
const mk = (results) => { let k = 0; return { flags: 'g', set lastIndex(v) {}, get lastIndex() { return 0; }, exec() { return k < results.length ? results[k++] : null; } }; };
const R = (re, s, r) => err(() => RegExp.prototype[Symbol.replace].call(re, s, r));
console.log(R(mk([{ 0: 'bc', index: 1, length: 1 }]), 'abcd', '[$&]'));
console.log(R(mk([{ 0: 'b', index: -5, length: 1 }]), 'abcd', '[$&]'));
console.log(R(mk([{ 0: 'b', index: NaN, length: 1 }]), 'abcd', '[$&]'));
console.log(R(mk([{ 0: 'b', index: 99, length: 1 }]), 'abcd', '[$&]'));
console.log(R(mk([{ 0: 'c', index: 2, length: 1 }, { 0: 'a', index: 0, length: 1 }]), 'abcd', '[$&]'));
console.log(R(mk([{ 0: 'b', index: 1, length: 3, 1: 42, 2: undefined }]), 'abcd', '<$1|$2|$3>'));
console.log(R(mk([{ 0: 'b', index: 1, length: 1, groups: null }]), 'abcd', '<$<x>>'));
console.log(R(mk([{ 0: 'b', index: 1, length: 1, groups: 'str' }]), 'abcd', '<$<length>>'));
console.log(R(mk([{ 0: 'b', index: 1, length: 1, groups: { x: undefined, y: 7 } }]), 'abcd', '<$<x>$<y>$<z>>'));
console.log(R(mk([{ 0: 'b', index: 1, length: 2, 1: 'q', groups: { x: 'X' } }]), 'abcd', (...a) => fmt(a)));
console.log(R(mk([{ 0: { toString() { return 'zz'; } }, index: '1', length: 1 }]), 'abcd', '[$&]'));
console.log(err(() => RegExp.prototype[Symbol.replace].call(1, 'a', 'b')), '|', err(() => RegExp.prototype[Symbol.split].call(1, 'a')));
""")


def test_class_escapes_all_modes(run, workdir):
    r"""CATCHES: wrong decoding of escapes inside character classes in legacy, u and v modes (\b
    as backspace, Annex-B octal and \c digit/underscore forms, a dangling \c meaning a literal
    backslash, v-mode punctuator escapes), wrong error messages for invalid class escapes and
    group-name escapes, and the reference's v-mode [\s] which also matches U+0085 (NEL) unlike
    \s and the u-mode class (pinned as observed)."""
    check_script(run, workdir, G, "class_escapes", r"""
const fmt = (v) => JSON.stringify(v);
const t = (re, s) => re.test(s) ? 1 : 0;
console.log(t(/^[\n\t\r\f\v\b\0]+$/v, '\n\t\r\f\v\b\0'), t(/[\x41]/v, 'A'), t(/[B]/v, 'B'), t(/[\u{1F600}]/v, '\u{1F600}'), t(/[\cA]/v, '\x01'), t(/^[\-\&\!\#\%\,\:\;\<\=\>\@\`\~\"\'\/\(\)\[\]\{\}\|\^\$\.\*\+\?\\]+$/v, '-&!#%,:;<=>@`~"\'/()[]{}|^$.*+?\\'));
console.log(t(/[\s]/v, '\x85'), t(/\s/, '\x85'), t(/[\s]/u, '\x85'), t(/[\S]/v, '\x85'), t(/[\w]/v, '_'), t(/[\W]/v, '_'), t(/[\d]/v, '5'), t(/[\D]/v, '5'), t(/[^\s]/v, ' '), t(/[\s]/v, ' '));
console.log(t(/[\0]/, '\0'), t(/[\01]/, '\x01'), t(/[\101]/, 'A'), t(/[\477]/, '\x277'), t(/[\8]/, '8'), t(/[\b]/, '\b'), t(/[\cA]/, '\x01'), t(/[\c1]/, '\x11'), t(/[\c_]/, '\x1f'), t(/[\c]/, '\\'), t(/[\c]/, 'c'), t(/[\c!]/, '!'));
console.log(t(/[\x41]/, 'A'), t(/[\x4]/, 'x'), t(/[A]/, 'A'), t(/[\u{41}]/u, 'A'), t(/[\u{41}]/, 'u'), t(/[\u{1F600}]/u, '\u{1F600}'), t(/[\z]/, 'z'), t(/[\-]/, '-'), t(/[\0]/u, '\0'), t(/[😀]/u, '\u{1F600}'), t(/^[😀]$/, '\uDE00'));
for (const [p, f] of [['[\\x4]', 'u'], ['[\\u12]', 'u'], ['[\\cA\\c]', 'v'], ['[\\z]', 'v'], ['[\\', 'v'], ['[\\x4]', 'v'], ['[\\c1]', 'u'], ['[\\00]', 'u'], ['[\\8]', 'u'], ['\\k', 'u'], ['(?<a>.)\\k', ''], ['(?<a>.)\\ka', ''], ['(?<\\u0030>.)', ''], ['(?<a\\x41>.)', ''], ['[\\d-z]', 'u'], ['[a-\\d]', 'u'], ['\\u{FFFFFFFFF}', 'u']]) {
  try { new RegExp(p, f); console.log('ok', p, f); } catch (e) { console.log(p, f, '=>', e.message); }
}
console.log(fmt(Object.keys(/(?<a\u{62}>.)/u.exec('z').groups)), fmt(Object.keys(/(?<𝒜>.)/.exec('z').groups)), fmt(Object.keys(/(?<\u{1D49C}b>.)/u.exec('z').groups)), fmt(Object.keys(/(?<a\u{62}>.)/.exec('z').groups)));
""")


def test_lazy_quantifier_continuations(run, workdir):
    r"""CATCHES: lazy single-character repetitions that skip a viable shorter match when the next
    atom is a class, dot, another repetition, a backreference (numbered or a duplicated named
    group), an anchor, a word boundary, an alternation or a lookaround; and duplicate-named-group
    backreferences resolving to the wrong (unmatched) branch."""
    check_script(run, workdir, G, "lazy_continuations", r"""
const m = (re, s) => JSON.stringify(re.exec(s));
console.log(m(/a.*?./, 'abc'), m(/a.*?[xc]/, 'abcxc'), m(/a*?b*c/, 'aabbc'), m(/(a)x*?\1/, 'axxa'), m(/(?<q>')x*?\k<q>/, "'xx'"), m(/a*?$/, 'aaa'));
console.log(m(/a*?\b/, 'aa b'), m(/a*?(?:b|c)/, 'aac'), m(/x.*?(y)/, 'xaay'), m(/x*?(?=y)/, 'xxy'), m(/^a*?^/m, 'aa'), m(/a+?(?:)/, 'aa'), m(/a*?(a)?b/, 'aab'), m(/.*?\B/, 'ab'));
console.log(m(/(?:(?<n>x)|(?<n>y))\k<n>+/, 'yyy'), m(/(?:(?<n>x)|(?<n>y))?\k<n>/, 'z'), m(/(?<=\k<n>(?:(?<n>x)|(?<n>y)))z/, 'yyz'), m(/(?:(?<n>a)|(?<n>b))\k<n>/i, 'bB'));
console.log(m(/[a-z]*?\d/, 'ab1'), m(/\w*?\s*?!/, 'ab  !'), m(/a{2,}?(b)\1/, 'aaabb'), m(/.*?(?:a|b)*c/, 'xabc'), m(/a*?(?!b)/, 'aab'), m(/a*?(?<=a)/, 'aa'), m(/a*?(?i:B)/, 'aB'), m(/(a)*?\1/, 'aa'));
console.log(m(/<(\w+?)>.*?<\/\1>/, '<b>x</i></b>'), m(/".*?(?<!\\)"/, '"a\\"b" c'), m(/\d+?(?=(\d{3})+$)/, '1234567'), m(/(?:a|b)*?\k<z>(?<z>c)?/, 'abc'));
""")
