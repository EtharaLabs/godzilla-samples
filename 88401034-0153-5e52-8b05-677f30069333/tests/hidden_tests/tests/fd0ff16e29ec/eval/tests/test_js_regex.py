"""Regular expressions: the RegExp constructor/prototype, the pattern compiler and backtracking matcher
(groups, lookaround, backreferences, quantifiers, Annex B syntax, u/v/i/m/s/y/d flags, Unicode
properties, set notation, inline modifiers), the String methods that dispatch to RegExp symbols
(replace/replaceAll/split/match/matchAll/search), RegExp.escape, the legacy RegExp.$N statics and the
exact SyntaxError messages for invalid patterns."""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

# Shared output helpers: p() joins values with " | " (strings raw, everything else JSON);
# fm() renders a match array distinguishing undefined ('u') from null; E() captures an error.
PRELUDE = r"""
const p = (...a) => console.log(a.map(x => typeof x === 'string' ? x : x === undefined ? 'undefined' : JSON.stringify(x)).join(' | '));
const fm = (m) => m === null ? 'null' : '[' + Array.from(m, x => x === undefined ? 'u' : JSON.stringify(x)).join(',') + ']';
const E = (f) => { try { const v = f(); return 'ok ' + (typeof v === 'string' ? v : JSON.stringify(v)); } catch (e) { return e.name + ': ' + e.message; } };
"""


def _ok(run, prog, name, tier=()):
    r = run([*tier, "-e", PRELUDE + prog])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


# ---------------------------------------------------------------- RegExp objects

PROG_FLAGS_SOURCE = r"""
for (const f of ['', 'g', 'dgimsuy', 'ymigsd', 'v', 'sd', 'iv']) {
  const r = new RegExp('a/b', f);
  p(JSON.stringify(f), r.flags, r.source, String(r),
    [r.hasIndices, r.global, r.ignoreCase, r.multiline, r.dotAll, r.unicode, r.unicodeSets, r.sticky].map(Number).join(''));
}
p(new RegExp('').source, String(new RegExp('')), String(/(?:)/), String(new RegExp('', 'g')));
p(new RegExp('\n\r\u2028\u2029').source);
p(new RegExp('[/]/\\/').source, String(new RegExp('[/]/')), new RegExp('\\[/').source);
p(new RegExp('a\\\nb').source);
p(eval('/' + new RegExp('x/y\n').source + '/').test('x/y\n'));
p(RegExp.prototype.source, RegExp.prototype.flags, String(RegExp.prototype.global), String(RegExp.prototype));
const get = (n) => Object.getOwnPropertyDescriptor(RegExp.prototype, n).get;
p(E(() => get('global').call({})), E(() => get('sticky').call(/x/y)));
p(E(() => get('source').call({})), E(() => get('flags').call(1)));
p(get('flags').call({ global: 1, sticky: 'x', unicode: 0, hasIndices: true, dotAll: [], unicodeSets: null }));
const order = [];
get('flags').call(new Proxy({}, { get(t, k) { order.push(String(k)); } }));
p(order.join(','));
p(RegExp.prototype.toString.call({ source: 'S', flags: 'F' }), E(() => RegExp.prototype.toString.call(1)));
const r = /x/g;
p(r.lastIndex, JSON.stringify(Object.getOwnPropertyDescriptor(r, 'lastIndex')), Object.keys(r).length);
p(Object.getOwnPropertyNames(RegExp.prototype).sort().join(','));
p(RegExp.length, RegExp.name, RegExp.prototype.exec.length, RegExp.prototype[Symbol.replace].name,
  RegExp.prototype[Symbol.split].length, get('flags').name);
p(Object.prototype.toString.call(/x/), typeof /x/, /x/ instanceof RegExp, /x/.constructor === RegExp);
"""


def test_flags_source_and_tostring(run):
    """CATCHES: flags not reported in canonical dgimsuvy order, source not escaping '/' and line terminators, prototype getters that throw on RegExp.prototype or accept non-RegExp receivers, or a flags getter that reads the component flags in the wrong order."""
    _ok(run, PROG_FLAGS_SOURCE, "flags_source")


PROG_CONSTRUCTOR = r"""
const r1 = /ab/gi;
p(RegExp(r1) === r1, new RegExp(r1) === r1, String(new RegExp(r1)), String(new RegExp(r1, 'y')), RegExp(r1, 'm') === r1);
const like = { [Symbol.match]: true, source: 'q+', flags: 'g', constructor: RegExp };
p(RegExp(like) === like, String(new RegExp(like)), String(new RegExp(like, 'i')));
const notSame = { [Symbol.match]: true, source: 'z', flags: 's', constructor: Object };
p(RegExp(notSame) === notSame, String(RegExp(notSame)));
const weird = { [Symbol.match]: true, source: 'w', flags: 'm', constructor: 5 }; p(RegExp(weird) === weird, String(RegExp(weird)));
p(String(new RegExp(undefined)), String(new RegExp(undefined, undefined)), String(new RegExp(null)), String(new RegExp(123, 'g')), String(RegExp()));
p(String(new RegExp({ toString() { return 'x|y'; } })), String(new RegExp('a', { toString() { return 'gm'; } })));
const off = /a/; off[Symbol.match] = false; p(String(new RegExp(off)), RegExp(off) === off);
p(E(() => new RegExp('a', 'z')), E(() => new RegExp('(')), E(() => new RegExp(Symbol())));
const rc = /a/g; rc.lastIndex = 3;
const ret = rc.compile('b+', 'i');
p(ret === rc, String(rc), rc.lastIndex, rc.test('xBBy'));
rc.compile(/zz/m); p(String(rc));
p(E(() => rc.compile(/zz/, 'g')), String(rc));
rc.compile(); p(String(rc), rc.source);
p(E(() => rc.compile('(')), String(rc));
class R extends RegExp {}
p(E(() => new R('a').compile('b')), E(() => RegExp.prototype.compile.call({})));
p(RegExp.prototype.compile.length, typeof RegExp.prototype.compile);
"""


def test_constructor_and_compile(run):
    """CATCHES: RegExp() not returning a regexp argument unchanged, ignoring Symbol.match / source / flags of regexp-like objects, wrong ToString coercions, or an Annex B compile() that does not reset lastIndex or refuses/accepts the wrong receivers."""
    _ok(run, PROG_CONSTRUCTOR, "constructor")


PROG_EXEC_SHAPE = r"""
const r = /(?<year>\d{4})-(?<mon>\d{2})(?:-(?<day>\d{2}))?/dg;
const s = 'on 2024-03-15 and 1999-12 end';
let m;
while ((m = r.exec(s)) !== null) {
  p(fm(m), m.index, m.input === s, m.length, JSON.stringify(m.groups), 'day' in m.groups);
  p(fm(m.indices), JSON.stringify(m.indices.groups), r.lastIndex);
}
p(r.lastIndex);
const m2 = /(a)|(b)/d.exec('xb');
p(fm(m2), m2.indices.length, m2.indices[1] === undefined, JSON.stringify(m2.indices[2]), m2.indices.groups, m2.groups);
const m3 = /x(?<n>y)?/.exec('x');
p(fm(m3), Object.keys(m3).join(','), Object.getPrototypeOf(m3.groups), m3.groups.n);
const m4 = /b/.exec('abc');
p(Array.isArray(m4), Object.keys(m4).join(','), m4.groups, 'indices' in m4);
const m5 = /\u{1F600}(.)/du.exec('a\u{1F600}b');
p(fm(m5), m5.index, JSON.stringify([...m5.indices]));
p(fm(/(?:)/.exec('')), fm(/$/.exec('ab')), /$/.exec('ab').index, fm(/a|ab/.exec('abc')), fm(/((a)|(ab))((c)|(bc))/.exec('abc')));
p(fm(/[^]/.exec('\n')), fm(/a(?:b|c)d/.exec('xacd')), fm(RegExp.prototype.exec.call(/x/, { toString() { return 'yx'; } })));
p(E(() => RegExp.prototype.exec.call({}, 'a')), fm(/u/.exec()), fm(/null/.exec(null)));
"""


def test_exec_result_shape_and_indices(run):
    """CATCHES: exec results missing index/input/groups, groups objects with a prototype or wrong keys, unmatched groups reported as empty strings instead of undefined, or wrong `d`-flag indices (including astral input and named indices.groups)."""
    _ok(run, PROG_EXEC_SHAPE, "exec_shape")


PROG_LASTINDEX = r"""
const g = /o/g; const s = 'foo boo';
const res = []; let m; while ((m = g.exec(s))) res.push(m.index + ':' + g.lastIndex); p(res.join(' '), g.lastIndex);
const y = /o/y; y.lastIndex = 1;
p(y.test(s), y.lastIndex, y.test(s), y.lastIndex, y.test(s), y.lastIndex);
y.lastIndex = 5; p(y.exec(s).index, y.lastIndex);
const g2 = /a/g;
g2.lastIndex = 100; p(g2.test('aaa'), g2.lastIndex);
g2.lastIndex = -5; p(g2.test('aaa'), g2.lastIndex);
g2.lastIndex = '2'; p(g2.exec('aaa').index, g2.lastIndex);
g2.lastIndex = 1.9; p(g2.exec('aaa').index, g2.lastIndex);
g2.lastIndex = 3; p(fm(g2.exec('aaa')), g2.lastIndex);
const n = /a/; n.lastIndex = 2; p(n.exec('aaa').index, n.lastIndex);
const ny = /a/y; ny.lastIndex = 0; p(fm(ny.exec('ba')), ny.lastIndex);
p(/^b/y.test('ab'), (() => { const r = /^b/my; r.lastIndex = 2; return r.test('a\nb'); })(), (() => { const r = /b$/y; r.lastIndex = 1; return [r.test('abc'), r.lastIndex]; })());
p('aaba'.match(/a/gy), 'aaba'.replace(/a/gy, 'X'), 'a-b-c'.split(/-/y), 'xaa'.replace(/a/y, 'Y'));
const yy = /a/y; yy.lastIndex = 1; p('aaa'.replace(yy, 'Z'), yy.lastIndex);
const fr = /a/g; Object.defineProperty(fr, 'lastIndex', { writable: false, value: 0 });
p(E(() => fr.exec('a')), E(() => 'aa'.replace(fr, 'b')), E(() => fr.exec('b')));
const fr2 = /a/; Object.defineProperty(fr2, 'lastIndex', { writable: false, value: 0 });
p(E(() => fr2.exec('a')[0]), E(() => fr2.test('b')));
let reads = 0; const vi = /a/g; vi.lastIndex = { valueOf() { reads++; return 1; } };
p(vi.exec('aba').index, vi.lastIndex, reads);
p('abc'.replace(/(?:)/g, '-'), 'aaa'.match(/a*?/g), 'abc'.match(/x*/g), 'aXbX'.replace(/x*/gi, '.'));
const mg = /a/g; mg.lastIndex = 7; p('aaa'.match(mg).length, mg.lastIndex);
const rg = /a/g; rg.lastIndex = 2; p('aXa'.replace(rg, 'b'), rg.lastIndex);
"""


def test_lastindex_global_and_sticky(run):
    """CATCHES: lastIndex not read with ToLength/ToIntegerOrInfinity, not reset to 0 on failure, honoured by non-global regexps, sticky matches that scan forward instead of failing, or non-writable lastIndex not throwing TypeError from exec/replace."""
    _ok(run, PROG_LASTINDEX, "lastindex")


PROG_UNICODE_MODE = r"""
const s = 'a\u{1F600}b\uD83Dc\uDE00d';
p(s.match(/./g).length, s.match(/./gu).length, JSON.stringify(s.match(/./gu)));
p(JSON.stringify(s.match(/[^a-d]/gu)), JSON.stringify(s.match(/[^a-d]/g)));
p(/^.$/.test('\u{1F600}'), /^.$/u.test('\u{1F600}'), /^..$/.test('\u{1F600}'), /^[\u{1F600}]$/u.test('\u{1F600}'), new RegExp('^[\u{1F600}]$').test('\u{1F600}'));
p(/\uD83D/.test('\u{1F600}'), /\uD83D/u.test('\u{1F600}'), /\uDE00/u.test('\u{1F600}'), /\uDE00/u.test('\uDE00'), /\uD83D\uDE00/u.test('\u{1F600}'), /\u{1F600}/u.test('\u{1F600}'));
p('\u{1F600}\u{1F601}\u{1F602}'.match(/[\u{1F600}-\u{1F601}]/gu).length, '\u{1F600}\u{1F601}\u{1F602}'.replace(/\u{1F601}/u, 'X').length, /[\uD83D\uDE00-\uD83D\uDE4F]/u.test('\u{1F610}'));
p(/^\S$/u.test('\u{1F600}'), /^\W$/u.test('\u{1F600}'), /^\D{1}$/u.test('\u{1F600}'), /^\D{2}$/.test('\u{1F600}'), /^[^x]$/u.test('\u{1F600}'));
p(JSON.stringify('x\u{1F600}y'.split(/(?:)/u)), JSON.stringify('x\u{1F600}y'.split('')));
p('\u{1F600}'.search(/\uDE00/), '\u{1F600}'.search(/\uDE00/u));
p(/(?<=\u{1F600})x/u.exec('\u{1F600}x').index, /(?<=.)x/u.exec('\u{1F600}x').index, /(?<=^.)x/u.test('\u{1F600}x'), /(?<=^.)x/.test('\u{1F600}x'));
const u = /./gu; u.lastIndex = 1; const mu = u.exec('\u{1F600}x'); p(mu.index, mu[0].length, u.lastIndex);
const nu = /./g; nu.lastIndex = 1; const mnu = nu.exec('\u{1F600}x'); p(mnu.index, JSON.stringify(mnu[0]), nu.lastIndex);
const pairRe = /\uDE00/gu; pairRe.lastIndex = 1; p(fm(pairRe.exec('\u{1F600}')), pairRe.lastIndex);
p('\u{1F600}\u{1F600}'.replace(/(?:)/gu, '-'), JSON.stringify('\u{1F600}'.replace(/(?:)/g, '-')));
p([...'\u{1F600}\u{1F600}'.matchAll(/(?:)/gu)].map(m => m.index).join(), [...'\u{1F600}'.matchAll(/(?:)/g)].map(m => m.index).join());
p(/\u{41}/.test('A'), /\u{2}/.test('uu'), /^\u{2}$/.test('uu'), /\u{41}/u.test('A'), /\x41\u0042\103/.test('ABC'));
p(/(\u{1F600})\1/u.test('\u{1F600}\u{1F600}'), /(.)\1/u.exec('\u{1F600}\u{1F600}x')[0].length, /(.)\1/.exec('\uD83D\uD83D')[0].length);
p(/\uD83D\u0041/u.test('\uD83DA'), /[\x41]/u.test('A'), /\uD83D\u0041/u.test('\u{1F600}A'), /^[\uD83D\uDE00]$/u.test('\u{1F600}'), /^[\uD83D\uDE00]$/.test('\u{1F600}'));
p(/[\u{10000}-\u{10FFFF}]/u.test('\u{10FFFF}'), /^[\0-\u{FFFF}]$/u.test('\u{10000}'), /[\uD800-\uDBFF]/u.test('\u{10000}'), /[\uD800-\uDBFF]/u.test('\uD800'));
"""


def test_unicode_mode_surrogates(run):
    """CATCHES: u-mode matchers that iterate code units instead of code points (splitting astral characters), that let lastIndex land mid-surrogate-pair, or that fail to treat lone surrogates as distinct from paired ones; also non-u mode that wrongly treats pairs as one character."""
    _ok(run, PROG_UNICODE_MODE, "unicode_mode")


PROG_NAMED_GROUPS = r"""
const re = /(?<a>x)|(?<a>y)/;
p(JSON.stringify(re.exec('y').groups), Object.keys(re.exec('x').groups).join(','), fm(re.exec('y')));
const dup = /(?:(?<n>a)|(?<n>b))\k<n>/;
p(dup.test('aa'), dup.test('bb'), dup.test('ab'), dup.test('ba'));
const d2 = /(?<y>\d{4})-\d{2}|\d{2}-(?<y>\d{4})/;
p(d2.exec('12-2020').groups.y, d2.exec('2021-05').groups.y, '12-2020'.replace(d2, '[$<y>]'), '2021-05'.replace(d2, (...a) => a.at(-1).y));
p(JSON.stringify(/(?<z>a)|(?<z>b)/d.exec('b').indices.groups), JSON.stringify(/(?<z>a)|(?<z>b)/d.exec('a').indices.groups));
const g3 = /(?:(?<n>a)|(?<n>b)|c)/.exec('c').groups; p(Object.keys(g3).join(','), g3.n, 'n' in g3);
p('2020-01'.replace(/(?<y>\d+)-(?<m>\d+)/, '$<m>/$<y>|$<nope>|$<y'));
p(Object.getPrototypeOf(/(?<a>.)/.exec('z').groups), JSON.stringify(/(?<\u03C0>p)(?<\u0041b>q)(?<$_>r)(?<\u{1D49C}>s)/.exec('pqrs').groups));
p(/\k<a>(?<a>b)/.test('b'), /(?<a>a)\k<a>/.test('aa'), /(?<a>a)\k<a>/i.test('aA'), /(?<a>.)(?<b>.)\k<b>\k<a>/.test('abba'));
p(/\k/.test('k'), /\k<a>/.test('k<a>'), /\k<1>/.test('k<1>'));
p(JSON.stringify(Object.keys(/(?<b>.)(?<a>.)(?<c>.)/.exec('xyz').groups)), Object.hasOwn(/(?<b>.)(?<a>.)/.exec('xy').groups, 'a'));
const nested = /(?<outer>a(?<inner>b)?c)/.exec('ac'); p(fm(nested), JSON.stringify(nested.groups), 'inner' in nested.groups);
p(/(?<a>x)\1/.test('xx'), fm(/(?<first>\w+)\s(?<last>\w+)/.exec('Ada Lovelace')), '\u{1F600}'.replace(/(?<e>.)/u, '[$<e>]'));
p(JSON.stringify([...'a1b2'.matchAll(/(?<l>[a-z])(?<d>\d)/g)].map(m => m.groups)));
p(JSON.stringify(new RegExp('(?<\u{1D49C}>.)').exec('z').groups), JSON.stringify(new RegExp('(?<\\uD835\\uDC9C>.)').exec('q').groups), JSON.stringify(/(?<\u{1D49C}>.)\k<\u{1D49C}>/u.exec('ww').groups));
"""


def test_named_groups_and_duplicates(run):
    """CATCHES: groups objects that are not null-prototype or not in pattern order, duplicate named groups (ES2025) that report the wrong alternative or break \\k<name>, named backreferences resolved incorrectly, or \\k treated as an error in patterns without named groups."""
    _ok(run, PROG_NAMED_GROUPS, "named_groups")


PROG_LOOKAROUND = r"""
p(JSON.stringify('price: $42, $7, 17'.match(/(?<=\$)\d+/g)), JSON.stringify('price: $42, $7, 17'.match(/(?<!\$)\b\d+/g)));
p('abcabc'.replace(/(?<=a)b/g, 'B'), 'abcabc'.replace(/(?<!a)c/g, '_'), 'aaa'.replace(/(?<=a)/g, '|'));
p(fm(/(?<=(\d+)(\d+))$/.exec('1053')), fm(/(?<=(\d+?)(\d+?))$/.exec('1053')));
p(fm(/(?<=\1(a))b/.exec('aab')), fm(/(?<=(a)\1)b/.exec('aab')), fm(/(?<=(?:(a)|b)\1)c/.exec('xbc')));
p(fm(/(?=(a+))a*b\1/.exec('baaabac')), fm(/(?=(a+))/.exec('baaabac')));
p(fm(/(.*?)a(?!(a+)b\2c)\2(.*)/.exec('baaabaac')));
p(fm(/(?<!a|bc)d/.exec('bcd ad xd')), /(?<!a|bc)d/.exec('bcd ad xd').index);
p(JSON.stringify('a,bb,ccc'.match(/(?<=^|,)\w+/g)), fm('xay'.match(/(?<=x(?=a))a/)), /(?<=\b)foo/.test('a foo'), /(?<=\B)foo/.test('a foo'));
p(/(?<=[a-c]{2,3})d/.exec('abcd').index, JSON.stringify(/(?<=a(?<n>.)c)d/.exec('abcd').groups), fm(/(?<=([ab])+)c/.exec('abc')));
p(/(?!a)+b/.test('b'), /(?=a){2}a/.test('a'), /(?=a)*/.test('x'), fm(/(?=(a))?a/.exec('a')), fm(/(?!(a))b/.exec('b')));
p(fm(/(?<=(?<!x)a)b/.exec('xab ab')), /(?<=(?<!x)a)b/.exec('xab ab').index, fm(/(?<=a(?=b)b)c/.exec('abc')));
p(fm(/(?<=^(?:\d{3})*)\d/.exec('12345')), '1234567'.replace(/\B(?=(\d{3})+(?!\d))/g, ','), 'x'.replace(/(?<=x)$/, '!'));
p(fm(/(?<=(?:a|ab))c/.exec('abc')), fm(/(?<=(a|ab))c/.exec('abc')), fm(/(?<=\1(a|b))c/.exec('bbc')));
p(fm(/(?<=\u{1F600}{2})!/u.exec('\u{1F600}\u{1F600}!')), fm(/(?<=[\u{1F600}x])!/u.exec('\u{1F600}!')), fm(/(?<=\uDE00)!/.exec('\u{1F600}!')));
"""


def test_lookahead_and_lookbehind(run):
    """CATCHES: lookbehind matched left-to-right (wrong greedy captures and backreference direction), negative lookarounds that leak captures, Annex B quantified lookaheads rejected, or nested lookarounds that lose their own direction."""
    _ok(run, PROG_LOOKAROUND, "lookaround")


PROG_BACKREFS = r"""
p(fm(/(a)\1/.exec('aa')), fm(/\1(a)/.exec('aa')), fm(/(a)?\1b/.exec('b')), fm(/(a)|\1b/.exec('b')), fm(/(?:(a)|b)\1/.exec('b')));
p(fm(/((a)|b)+/.exec('ab')), fm(/(z)((a+)?(b+)?(c))*/.exec('zaacbbbcac')), fm(/(a*)*/.exec('b')), fm(/(a*)+/.exec('b')));
p(fm(/(a)|b/i.exec('B')), /(A)\1/i.test('aA'), /(a)\1/.test('aA'), fm(/(\w+)\s\1/.exec('hello hello world')), fm(/(\d)(\d)\2\1/.exec('x1221')));
p(fm(/(a)\2(b)/.exec('ab')), fm(/(?:(x)|y)+\1/.exec('xyx')), fm(/^(?:(a)|b)*$/.exec('ab')), fm(/(.)(?:(?!\1).)*\1/.exec('abcab')));
p(fm(/(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)\10/.exec('abcdefghijj')), fm(/(a)\10/.exec('a\b0')), fm(/(a)\10/.exec('a\x080')));
p(fm(/((((((((((a))))))))))\10/.exec('aa')), fm(/(a)(?:\1)*/.exec('aaaa')), fm(/(?:(a)\1)+/.exec('aaaa')), fm(/(a\1)/.exec('aa')));
p(fm(/([ab])\1+/.exec('cabbbb')), fm(/(?<q>['"]).*?\k<q>/.exec(`say "hi 'x'" ok`)), fm(/(\u{1F600}|x)\1/u.exec('x\u{1F600}\u{1F600}')));
p(fm(/(?:a|(b))+?c/.exec('abac')), fm(/(?:(a)|(b))*/.exec('ab')), fm(/(?:(a)|(b)){2}/.exec('ab')), fm(/(?:(a)|b)*c/.exec('abc')));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_backreferences_and_capture_reset(run, tier):
    """CATCHES: backreferences to unset/forward groups that fail instead of matching empty, captures not cleared at the start of each quantifier iteration, case-insensitive backreferences, or \\10 misparsed when fewer than 10 groups exist."""
    _ok(run, PROG_BACKREFS, "backrefs", tier)


PROG_QUANTIFIERS = r"""
p(fm(/a{2}/.exec('aaa')), fm(/a{2,}/.exec('aaaa')), fm(/a{1,2}?/.exec('aaa')), fm(/a{0}b/.exec('ab')), fm(/x{2,3}?y/.exec('xxxy')), fm(/a{3}/.exec('aa')));
p(fm(/a+?b/.exec('aaab')), fm(/a*?/.exec('aaa')), fm(/(a+?)(a*)/.exec('aaa')), fm(/(a|ab)(c|bcd)(d*)/.exec('abcd')), fm(/a??b/.exec('ab')));
p(fm(/(?:a|b)*?c/.exec('abc')), fm(/(a+)+b/.exec('aaab')), fm(/(?:)*/.exec('x')), fm(/(?:a?)*?b/.exec('aab')), fm(/(?:a*)*b/.exec('aab')));
p(fm(/(a?)*/.exec('aa')), fm(/(a?)+?/.exec('aa')), fm(/(?:(a)|b|)*/.exec('ab')), fm(/(?:x|(?:))+y/.exec('xxy')), fm(/(\2a?(b?))*/.exec('ab')));
p(fm(/a{1,3}/g.exec('aaaa')), 'aaaa'.match(/a{1,3}/g).join(','), 'aaaaa'.match(/a{2}?/g).join(','), fm(/.{0,2}c/.exec('abcc')));
p(fm(/x{3,5}/.exec('x'.repeat(9))), fm(/\d{2,4}?$/.exec('123456')), fm(/(ab){2}/.exec('ababab')), fm(/(ab){1,}?/.exec('ababab')));
p(/a{99999}/.test('a'.repeat(99999)), /^a{0,100000}$/.test('a'.repeat(5000)), /^(?:ab){999}$/.test('ab'.repeat(999)), /x{4294967295}/.test('x'));
p(fm(/(?:ab){1,3}?/.exec('ababab')), fm(/(ab){0,2}?c/.exec('ababc')), fm(/(?:(?<=(a))b)+/.exec('abab')), fm(/(?:|)a/.exec('ba')), fm(/(?:x?|y?)z/.exec('wz')), fm(/(?:a|ab)(?:c|bcd){0,3}?d/.exec('abcd')));
p(/[a-z]{3,}?\d/.exec('abcd1')[0], fm(/^(\w+?)(\d*)$/.exec('abc123')), fm(/^(?:(\d)|x){3}$/.exec('1x2')), fm(/(a{2})*/.exec('aaaaa')));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_quantifiers(run, tier):
    """CATCHES: wrong greedy/lazy backtracking order, empty-iteration rule violations (infinite loops or extra empty captures), brace quantifiers with wrong bounds, or huge single-character repetition counts that fail to compile or match."""
    _ok(run, PROG_QUANTIFIERS, "quantifiers", tier)


PROG_LAZY_CONTINUATIONS = r"""
const cases = [
  ["a.*?b", "", "xaxxbxb"],
  ["x.*?.y", "", "x12y3y"],
  ["x\\d*?[a-c]", "", "x123b"],
  ["x.*?\\d+y", "", "xab12y"],
  ["x.*?\\d*y", "", "xab12y"],
  ["x\\w*?\\d", "", "xab1c2"],
  ["(a)x*?\\1", "", "zaxxa"],
  ["()x*?\\1y", "", "xxy"],
  ["(?:(a)|b)x*?\\1c", "", "bxxc"],
  [".*?(a)\\1", "", "xyaa"],
  ["(?:(?<n>a)|(?<n>b))x*?\\k<n>", "", "bxxb"],
  ["(?:(?<n>a)|(?<n>b))x*?\\k<n>!", "", "cxx!"],
  ["x*?^a", "m", "xx\na"],
  ["a.*?$", "m", "ab\ncd"],
  ["a.*?$", "", "ab\ncd"],
  ["a.*?\\bc", "", "ab c"],
  ["a.*?\\Bc", "", "a cbc"],
  ["a.*?(?:b|c)", "", "axxcb"],
  ["a.*?(?:b|c)?d", "", "axbd"],
  ["a.*?", "", "abc"],
  ["a.*?(b)", "", "axxb"],
  ["a.*?(?:(b)c)+", "", "axbcbc"],
  ["a.*?(?:bc)*d", "", "axbcd"],
  ["a.*?(?=b)", "", "axxb"],
  ["a.*?(?<=b)c", "", "axbc"],
  ["a.*?(?i:b)", "", "axB"],
  ["a.*?((((((((((((((((((b))))))))))))))))))", "", "axxb"],
  ["(?<=a.*?b)c", "", "axbc"],
  ["(?<=^.*?b)c", "", "xbc"],
  ["(?<=\\b.*?x)y", "", " axy"],
  ["(?<=(\\d).*?\\1)z", "", "1a1z"],
  ["a+?b", "", "aaab"],
  ["a{2,}?a", "", "aaaa"],
  ["[a-z]*?\\d", "i", "ABC1"],
  ["\u212a*?k", "iu", "\u212a\u212ak"],
  ["<.+?>", "g", "<a><bb><>"],
  ["\\d*?(?:5|$)", "g", "125"],
  ["(?:a|b)*?\\1", "", "ab"],
  ["x[^y]*?y\\b", "", "xaay xyy"],
  [".*?(?:\\b|x)", "", "  ab"],
  ["\\s*?^\\S", "m", "  \n x"],
  ["o*?\\B", "", "oo"]];
for (const [src, flags, subject] of cases) {
  const re = new RegExp(src, flags);
  p(src, flags, JSON.stringify(subject), flags.includes('g') ? JSON.stringify(subject.match(re)) : fm(re.exec(subject)));
}
const brief = (m) => m === null ? 'null' : JSON.stringify([m[0], m.index, m.length, m[m.length - 1] === undefined ? 'u' : m[m.length - 1]]);
p(brief(/x*?()\1y/.exec('xxy')), brief(/(?:x*?(?<n>)\k<n>y|(?<n>b))/.exec('xxy')), brief(/(?:(?<n>)|(?<n>b))x*?\k<n>y/.exec('xxy')), brief(/a.*?(?:(?=b)|c)d/.exec('axbd')), brief(/a.*?(?:(?=b)|c)d/.exec('axcd')));
p(brief(new RegExp('()'.repeat(127) + 'x*?(y)').exec('xxy')), brief(new RegExp('()'.repeat(127) + 'x*?(?:(y)z)+').exec('xxyzyz')), brief(/(?:(?<n>a)|(?<n>b))?\k<n>c/.exec('c')));
p(brief(/(?<=\k<n>(?:(?<n>a)|(?<n>b)))c/.exec('aac')), brief(/(?<=\k<n>(?:(?<n>ab)|(?<n>b)))c/.exec('abc')), brief(/(?<=\k<n>(?:(?<n>ab)|(?<n>b)))c/.exec('ababc')), brief(/(?<=\1(a+))b/.exec('aaab')), brief(/(?<=\1(ab))c/.exec('abc')));
"""


def test_lazy_quantifier_continuations(run):
    """CATCHES: lazy single-character loops (.*?, x*?, \\d*?, a+?) whose look-ahead pruning of the continuation (literal, class, backreference, anchors, word boundaries, alternation, captures, lookarounds, inline flags, lookbehind direction) skips a position where the match actually succeeds, or accepts one where it fails."""
    _ok(run, PROG_LAZY_CONTINUATIONS, "lazy_continuations")

PROG_ANNEXB = r"""
p(/a{,2}/.test('a{,2}'), /a{2/.test('a{2'), /{/.test('{'), /}/.test('}'), /]/.test(']'), fm(/a{1,2/.exec('a{1,2')), /x{a}/.test('x{a}'), /\{1}/.test('{1}'));
p(fm(/(a)\2/.exec('a\x02')), /\8/.test('8'), /[\8]/.test('8'), /\9a/.test('9a'), /\0/.test('\0'), /\012/.test('\n'), /[\012]/.test('\n'), /\377/.test('\xff'), fm(/\400/.exec('\x200')));
p(/\1/.test('\x01'), /\18/.test('\x018'), /[\1]/.test('\x01'), /[\00]/.test('\0'), /[\08]/.exec('8')[0], /[\777]/.exec('\x3f7')[0].length, /\08/.test('\x008'));
p(/\cA/.test('\x01'), /\cz/.test('\x1a'), /\c1/.test('\\c1'), /[\c1]/.test('\x11'), /[\c_]/.test('\x1f'), fm(/[\c*]/.exec('c')), fm(/[\c*]/.exec('\\')), /\c/.test('\\c'));
p(/\x4/.test('x4'), /\x4g/.test('x4g'), /\u12/.test('u12'), /\u{2}/.test('uu'), /[\x]/.test('x'), /[\u]/.test('u'), /\q\e\y/.test('qey'), /\-\//.test('-/'));
p(/[a-\d]/.test('-'), /[\d-a]/.test('-'), /[\w-\s]/.test('-'), /[%--]/.test(','), /[\b]/.test('\b'), /\b/.test('\b'));
p(/\k/.test('k'), /\p{L}/.test('p{L}'), /\P{L}/.test('P{L}'), /[\p{L}]/.test('{'), /\a/.test('a'), /[\a]/.test('a'), /\_/.test('_'));
p(/[\cJ]/.test('\n'), /[\v]/.test('\v'), /\t\f\v\r\n/.test('\t\f\v\r\n'), /[\t\f\r\n]{4}/.test('\t\f\r\n'), /[\cj]/.test('\n'));
p(String(new RegExp('\\u{41}')), new RegExp('\\u{41}').test('u'.repeat(41)), new RegExp('[\\u{41}]').test('{'));
"""


def test_annex_b_legacy_syntax(run):
    """CATCHES: non-unicode patterns that reject Annex B constructs (lone braces, octal escapes, \\8/\\9 identity escapes, \\c without a letter, incomplete \\x/\\u escapes, class escapes as range bounds) or give them the wrong meaning."""
    _ok(run, PROG_ANNEXB, "annexb")


PROG_CASE_FOLDING = r"""
const t = (src, flags, s) => new RegExp(src, flags).test(s) ? 1 : 0;
const esc = (s) => [...s].map(c => 'U+' + c.codePointAt(0).toString(16).toUpperCase()).join(' ');
const pairs = [['\u212A', 'k'], ['K', '\u212A'], ['\u017F', 's'], ['S', '\u017F'], ['\u00DF', '\u1E9E'], ['\u1E9E', '\u00DF'],
  ['\u03C3', '\u03C2'], ['\u03A3', '\u03C2'], ['\u0130', 'i'], ['\u0131', 'I'], ['\u0131', 'i'], ['i', '\u0130'], ['\u03BC', '\u039C'],
  ['\u1F80', '\u1F88'], ['\u2126', '\u03C9'], ['\u{10400}', '\u{10428}'], ['\u00E5', '\u212B'], ['\uFB00', 'ff'], ['a', 'A'], ['\u00E9', '\u00C9']];
for (const [a, b] of pairs) {
  p(esc(a), esc(b), t(a, 'i', b), t(a, 'iu', b), t(a, 'iv', b), t('[' + a + ']', 'iu', b), t(`(${a})\\1`, 'i', a + b), t(`(${a})\\1`, 'iu', a + b));
}
p(t('\\w', 'iu', '\u017F'), t('\\w', 'iu', '\u212A'), t('\\w', 'i', '\u017F'), t('\\W', 'iu', '\u017F'), t('[\\W]', 'iu', 'S'), t('[^\\W]', 'iu', '\u212A'), t('\\b', 'iu', '\u017F'), t('\\b', 'i', '\u017F'));
p(t('[a-z]', 'i', 'K'), t('[a-z]', 'i', '\u212A'), t('[a-z]', 'iu', '\u212A'), t('[^a-z]', 'iu', '\u212A'), t('[^k]', 'iu', '\u212A'), t('[\\u0100-\\u017F]', 'i', 'S'), t('[A-Z]', 'i', 'z'));
p(t('\\p{Lu}', 'iu', 'a'), t('\\P{Lu}', 'iu', 'A'), t('[^\\P{Lu}]', 'iu', 'a'), t('\\p{Ll}', 'iu', 'Z'), t('[\\p{Lu}]', 'iv', 'q'));
p('\u03A3\u0391\u03A3 \u03C3\u03B1\u03C2'.replace(/\u03C3/gi, '_'), '\u0130stanbul'.replace(/i/gi, '_'), '\u01C5\u01C4\u01C6'.match(/\u01C6/gi).length);
p(t('[\\u{10400}]', 'iu', '\u{10428}'), t('[\\u{10400}-\\u{10410}]', 'iu', '\u{10430}'), t('\\u{1E900}', 'iu', '\u{1E922}'), t('[^\\u{10400}]', 'iu', '\u{10428}'));
p('ABCabc'.replace(/[b-c]/gi, '.'), 'xAx'.split(/a/i).join('|'), 'Hello HELLO hello'.match(/hello/gi).length, /\u00e0/i.test('\u00c0'));
"""


def test_case_insensitive_folding(run):
    """CATCHES: case-insensitive matching that ignores the u-flag distinction (simple case folding vs legacy toUpperCase canonicalization), folds non-ASCII onto ASCII without /u (Kelvin sign, long s), mishandles Greek sigma forms, \\w/\\b under /iu, or astral case pairs."""
    _ok(run, PROG_CASE_FOLDING, "case_folding")


PROG_PROPERTIES = r"""
p(JSON.stringify('a\u00E9\u{1D49C}\u0416\u0663'.match(/\p{L}/gu)), JSON.stringify('a\u0663 5\u{1D7D8}'.match(/\p{Nd}/gu)), JSON.stringify('a\u00E9\u0416'.match(/\P{ASCII}/gu)));
p(JSON.stringify('\u03B1\u03B2\u03B3 abc \u0416\u0417'.match(/\p{Script=Greek}+/gu)), JSON.stringify('\u03B1\u03B2 abc \u0416\u0417'.match(/\p{sc=Cyrl}+/gu)), JSON.stringify('\u03B1 abc'.match(/\p{Script_Extensions=Latin}+/gu)));
p('A b1_ \t\u00A0\u3000'.match(/\p{White_Space}/gu).length, /\p{Any}/u.test('\uD800'), /^\p{Assigned}$/u.test('\u0378'), /^\p{Cn}$/u.test('\u0378'), /^\P{Assigned}$/u.test('\u0378'));
p(/\p{General_Category=Decimal_Number}/u.test('\u0663'), /\p{gc=Lu}/u.test('a'), /\p{Lowercase}/u.test('a'), /\p{Alphabetic}/u.test('\u4E2D'), /\p{Ideographic}/u.test('\u4E2D'), /\p{Ideo}/u.test('a'));
p(JSON.stringify('$\u20AC\u00A3\u00A5'.match(/\p{Sc}/gu)), JSON.stringify('([{'.match(/\p{Ps}/gu)), /\p{Emoji_Modifier}/u.test('\u{1F3FD}'), /\p{Regional_Indicator}/u.test('\u{1F1EF}'), /\p{RI}/u.test('J'));
p(JSON.stringify('\u01C4\u01C5\u01C6'.match(/\p{Lt}/gu)), JSON.stringify('\u00BD\u00B2'.match(/\p{No}/gu)), /\p{Hex_Digit}/u.test('\uFF26'), /\p{ASCII_Hex_Digit}/u.test('\uFF26'), /\p{AHex}/u.test('f'));
p(/[\p{L}\p{N}]+/u.exec('--abc123--')[0], /[^\p{L}]+/u.exec('abc 123 def')[0], /[\P{L}]+/u.exec('abc 123 def')[0], /\P{L}+/u.exec('ab12cd')[0]);
p(/\p{Script=Hira}+/u.exec('\u3072\u3089\u304C\u306A\u30AB\u30BF')[0].length, /\p{scx=Hira}+/u.exec('\u3072\u3089\u30FC\u30AB')[0].length, /\p{sc=Hira}+/u.exec('\u3072\u3089\u30FC\u30AB')[0].length);
p(/\p{Script=Zyyy}/u.test('1'), /\p{sc=Inherited}/u.test('\u0300'), /\p{sc=Zinh}/u.test('a'), /\p{Script=Arabic}/u.test('\u0627'), /\p{scx=Arab}/u.test('\u060C'), /\p{sc=Arab}/u.test('\u060C'));
p(/\p{Emoji}/u.test('#'), /\p{Emoji_Presentation}/u.test('#'), /\p{Extended_Pictographic}/u.test('\u00A9'), /\p{EPres}/u.test('\u{1F600}'), /\p{Emoji_Component}/u.test('\u200D'));
p(/\p{Uppercase}/u.test('\u2160'), /\p{Lu}/u.test('\u2160'), /\p{Math}/u.test('+'), /\p{Dash}/u.test('\u2014'), /\p{Pd}/u.test('-'), /\p{Quotation_Mark}/u.test('\u00AB'), /\p{Pi}/u.test('\u00AB'));
p(/\p{ID_Start}/u.test('_'), /\p{ID_Continue}/u.test('_'), /\p{XIDS}/u.test('a'), /\p{Noncharacter_Code_Point}/u.test('\uFFFE'), /\p{Cs}/u.test('\uDC00'), /\p{Co}/u.test('\uE000'), /\p{Cc}/u.test('\x7F'));
p(/\p{Cased_Letter}/u.test('\u01C5'), /\p{LC}/u.test('\u02B0'), /\p{Lm}/u.test('\u02B0'), /\p{Mn}/u.test('\u0301'), /\p{M}/u.test('\u0903'), /\p{Mc}/u.test('\u0903'), /\p{Zs}/u.test('\u2003'), /\p{Zl}/u.test('\u2028'), /\p{Zp}/u.test('\u2029'));
p(/\p{Default_Ignorable_Code_Point}/u.test('\u00AD'), /\p{Variation_Selector}/u.test('\uFE0F'), /\p{Join_Control}/u.test('\u200C'), /\p{Bidi_Mirrored}/u.test('('), /\p{Soft_Dotted}/u.test('i'), /\p{Diacritic}/u.test('^'));
const props = ['L', 'Lu', 'Ll', 'N', 'P', 'S', 'Z', 'C', 'M', 'Letter', 'Number', 'Punctuation', 'Symbol', 'Separator', 'Other', 'Mark', 'Alpha', 'Upper', 'Lower', 'space', 'digit', 'punct', 'cntrl'];
const sample = 'aZ5_!+ \u00A0\u0301\x01\u4E2D\u{1F600}';
p(props.map(n => n + '=' + [...sample].filter(c => new RegExp(`\\p{${n}}`, 'u').test(c)).length).join(' '));
"""


def test_unicode_property_escapes(run):
    """CATCHES: missing or wrong Unicode property tables for General_Category (long and short names), Script vs Script_Extensions, binary properties (Alphabetic, White_Space, Emoji*, ID_Start, ...), Any/ASCII/Assigned, or \\P complement handling."""
    _ok(run, PROG_PROPERTIES, "properties")


PROG_VFLAG_SETS = r"""
const all = (re, s) => JSON.stringify([...s.matchAll(re)].map(m => m[0]));
p(all(/[\p{L}&&\p{ASCII}]/gv, 'a\u00E9 Z\u00DF1'), all(/[\w--\d]/gv, 'a1_b2'), all(/[\w--\d--_]/gv, 'a1_b2'), all(/[[a-z]--[aeiou]]/gv, 'hello world'));
p(all(/[\q{abc|ab|a}x]/gv, 'abcabaxq'), all(/[\q{abc|ab|a}--\q{ab}]/gv, 'abcabaxq'), all(/[\q{abc|ab|a}&&\q{ab|zz}]/gv, 'abcabaxq'));
p(all(/[^[^a-c]]/gv, 'abcd'), [...'ab'.matchAll(/[\q{}]/gv)].length, all(/[[\d\s]--\s]/gv, 'a1 2'), all(/[\p{ASCII}--\p{L}--\p{N}--\s]/gv, 'a!b?1 #'));
p(/[\p{Lu}--[A-Z]]/v.test('\u00C1'), /[\p{Lu}--[A-Z]]/v.test('A'), all(/[a-c\q{xy}]/giv, 'AxYbZ'), all(/[^\d]/gv, '1a2b'), all(/[^\p{L}&&\p{ASCII}]/gv, 'a\u00E91'));
p(all(/[\q{\u{1F600}|\x41\n}]/gv, 'A\n\u{1F600}'), /[\-\&\!]/v.test('&'), /[\n\t\r\f\v\b\0\x41\u0042\u{43}\cJ]/v.test('C'), '\u{1F600}'.match(/[\u{1F600}]/v)[0].length, '\u{1F600}'.match(/./v)[0].length);
p(all(/[[a-z]&&[^aeiou]&&[^xyz]]/gv, 'quixotic'), all(/[\p{L}--[a-z]--[A-Z]]/gv, 'aB\u00E7\u0416'), all(/[[[a-f]--[c]]&&[b-e]]/gv, 'abcdef'));
p(all(/[\q{ab|c}&&[a-z]]/gv, 'abc'), all(/[\q{ab|c}--[a-z]]/gv, 'abc'), all(/[\q{xy}\q{x}]/gv, 'xyx'), all(/[\q{a\|b}]/gv, 'a|b'));
p(all(/[\s--\n]/gv, ' \n\t'), all(/[\S&&\W]/gv, 'a !b?'), all(/[\D--\W]/gv, 'a1_!'), all(/[\w&&\p{Lu}]/giv, 'aZ_'), /[\d--[0-4]]/v.test('3'));
p(/^[\q{\u{1F468}\u200D\u{1F469}}]$/v.test('\u{1F468}\u200D\u{1F469}'), all(/[\q{abc}]+/gv, 'abcabcab'), all(/x[\q{a|bc}]y/gv, 'xay xbcy xby'));
"""


def test_vflag_set_operations(run):
    """CATCHES: v-mode classes without correct intersection (&&), subtraction (--), nested classes, complemented nested classes, or \\q{...} string alternatives (which must be tried longest first and survive set operations)."""
    _ok(run, PROG_VFLAG_SETS, "vflag_sets")


PROG_VFLAG_STRINGS = r"""
const all = (re, s) => s.match(re) || [];
const cps = (arr) => JSON.stringify(arr.map(s => [...s].length));
const mixed = 'a\u{1F600}b\u{1F44D}\u{1F3FD}c\u{1F1EF}\u{1F1F5}d1️⃣e\u{1F468}‍\u{1F469}‍\u{1F467}f#️⃣';
const rgi = mixed.match(/\p{RGI_Emoji}/gv);
p(cps(rgi), rgi.join('').length, mixed.replace(/\p{RGI_Emoji}/gv, '_'));
const noKeycap = '1️⃣\u{1F600}#️⃣\u{1F1EF}\u{1F1F5}'.match(/[\p{RGI_Emoji}--\p{Emoji_Keycap_Sequence}]/gv);
p(cps(noKeycap));
p(all(/\p{Emoji_Keycap_Sequence}/gv, '1️⃣\u{1F600}#️⃣*️⃣').length, all(/\p{RGI_Emoji_Flag_Sequence}/gv, '\u{1F1EF}\u{1F1F5}\u{1F1FA}\u{1F1F8}\u{1F1E6}').length);
p(cps(all(/\p{RGI_Emoji_Modifier_Sequence}/gv, '\u{1F44D}\u{1F3FD}\u{1F44D}')), cps(all(/\p{RGI_Emoji_ZWJ_Sequence}/gv, '\u{1F468}‍\u{1F469}‍\u{1F467}x\u{1F468}')));
p(cps(all(/\p{Basic_Emoji}/gv, '\u{1F600}a⌚')), all(/\p{RGI_Emoji_Tag_Sequence}/gv, '\u{1F3F4}\u{E0067}\u{E0062}\u{E0065}\u{E006E}\u{E0067}\u{E007F}\u{1F3F4}').length);
p(/^[\p{RGI_Emoji}]$/v.test('\u{1F468}‍\u{1F469}‍\u{1F467}'), /^\p{RGI_Emoji}$/v.test('\u{1F468}‍\u{1F469}'), /^\p{RGI_Emoji}$/v.test('❤️'), /^\p{RGI_Emoji}$/v.test('❤'));
p(/^[\p{Emoji_Keycap_Sequence}&&\q{1️⃣|x}]$/v.test('1️⃣'), /^[\p{RGI_Emoji_Flag_Sequence}--\q{\u{1F1EF}\u{1F1F5}}]$/v.test('\u{1F1EF}\u{1F1F5}'), /^[\p{RGI_Emoji_Flag_Sequence}--\q{\u{1F1EF}\u{1F1F5}}]$/v.test('\u{1F1FA}\u{1F1F8}'));
p('I ❤️ JS \u{1F468}\u{1F3FB}‍\u{1F4BB}!'.replace(/\p{RGI_Emoji}/gv, '<e>'), '\u{1F600}\u{1F600}'.split(/\p{RGI_Emoji}/v).length, '\u{1F1EF}\u{1F1F5}'.search(/\p{RGI_Emoji}/v));
p(/\p{RGI_Emoji}/v.unicodeSets, /\p{RGI_Emoji}/v.flags, /\p{L}/v.test('é'), /\P{L}/v.test('1'), /[\P{L}]/v.test('a'));
"""


def test_vflag_properties_of_strings(run):
    """CATCHES: missing v-mode properties of strings (RGI_Emoji, Emoji_Keycap_Sequence, flag/modifier/ZWJ/tag sequences, Basic_Emoji), matching only the first code point of a multi-code-point emoji, or set operations that drop string members."""
    _ok(run, PROG_VFLAG_STRINGS, "vflag_strings")


PROG_MODIFIERS_ANCHORS = r"""
const s = 'Line1\nline2\r\nLINE3\u2028line4\u2029end';
p(JSON.stringify(s.match(/^l\w+/gim)), JSON.stringify(s.match(/^l\w+/gi)), JSON.stringify(s.match(/\w+$/gm)), JSON.stringify(s.match(/\w+$/g)));
p(JSON.stringify(s.match(/(?m:^l\w+)/gi)), JSON.stringify(s.match(/(?i:^l)\w+/gm)), JSON.stringify(s.match(/(?-m:^)\w+/gm)), JSON.stringify(s.match(/(?-m:\w+$)/gm)));
p(/a.b/.test('a\nb'), /a.b/s.test('a\nb'), /a.b/.test('a\u2028b'), /a.b/.test('a\u0085b'), /a.b/.test('a\rb'), /(?s:a.b)/.test('a\nb'), /(?-s:a.b)/s.test('a\nb'), /a[^]b/.test('a\nb'), /a[]b/.test('ab'), /a[^]b/.test('ab'));
p(/(?i:a(?-i:b)c)/.test('AbC'), /(?i:a(?-i:b)c)/.test('ABC'), /(?ims:^a.b$)/.test('x\nA\nB\ny'), /(?i:\u212A)/u.test('k'), /(?i:\u212A)/.test('k'), /(?i:[a-z])/.test('Q'), /(?i-ms:a.)/ms.test('A\n'));
p(fm(/(?i:a)\1?(b)/.exec('Ab')), /(?<=(?i:a))b/.test('Ab'), /(?i:(?<x>a))\k<x>/.test('AA'), /(?i:(a))\1/.test('aA'), /(a)(?i:\1)/.test('aA'), /(?i:a|b)+c/.test('ABAc'), /(?i:a)+/.exec('aAAb')[0]);
p(/(?m:a$)\n/.test('a\n'), /(?s-i:.)/i.test('\n'), /(?-i:a)/i.test('A'), /x(?i:y)z/.test('xYz'), /x(?i:y)z/.test('xYZ'), /(?i:\w+)(?-i:Q)/.test('abcQ'), /(?i:[^a])/.test('A'));
p(JSON.stringify('foo bar_baz qux'.match(/\b\w/g)), JSON.stringify('foo bar'.match(/\B\w/g)), 'é a'.match(/\b/g).length, /\bé/u.test(' é'), /\Bé/.test(' é'), /a\b/.test('a\u00E9'));
p(/^$/.test(''), /^$/m.test('a\n'), JSON.stringify('a\n\nb'.match(/^$/gm)), 'ab'.replace(/$/g, '!'), JSON.stringify('a\nb'.replace(/$/gm, '!')), JSON.stringify('a\r\nb'.replace(/^/gm, '>')));
p(/\s+/.exec(' \t\n\v\f\r\u00a0\u1680\u2000\u200a\u2028\u2029\u202f\u205f\u3000\ufeff')[0].length, /\s/.test('\u180e'), /\s/.test('\u200b'), /\S/.test('\u0085'), /\d/.test('\u0663'), /\d/u.test('\u0663'), /\w/u.test('\u00E9'));
p(JSON.stringify('aBc'.match(/[A-Z]/gi)), JSON.stringify('a-b_c'.match(/[\w-]/g)), JSON.stringify('a]b'.match(/[\]]/)), '\\'.match(/[\\]/)[0].length, 'a^b'.match(/[\^]/)[0], JSON.stringify('ab-'.match(/[a\-z]/g)), JSON.stringify('-a'.match(/[-a]/g)));
"""


def test_inline_modifiers_anchors_dotall(run):
    """CATCHES: inline modifier groups (?i:...)/(?-i:...)/(?m:...)/(?s:...) that leak or ignore scope, ^/$ not honouring every line terminator under /m, '.' matching line terminators without /s, wrong \\s/\\d/\\w sets, or [] / [^] class edge cases."""
    _ok(run, PROG_MODIFIERS_ANCHORS, "modifiers_anchors")


# ---------------------------------------------------------------- syntax errors

PROG_ERRORS_LEGACY = r"""
const cases = ['(', ')', 'a)', '[', '[a', '\\', 'a**', 'a+*', 'a??+', '?', '+a', 'a|*', '{2}', 'x|{1,2}', 'a{3,2}',
  '(?', '(?x)', '(?<', '(?<a', '(?<1a>x)', '(?<a-b>x)', '(?<>x)', '(?<\\x41>x)', '(?<a>x)(?<a>y)', '(?<a>x)|(?<a>y)(?<a>z)',
  '((?<a>x)|(?<a>y))(?<a>z)', '(?<a>x)\\k<b>', '(?<a>x)\\k', '(?<a>x)\\k<a', '(?<=a)*', '(?<!a){2}', '(?<=a)?', '[b-a]', '[\\u0062-a]',
  '(?:ab){1001}', '(?:ab){2,5000}', '(a){1001}', '(?i-i:a)', '(?ii:a)', '(?-:a)', '(?i', '(?x:a)', '(?-ii:a)', '(?--i:a)', '(?i-m', '(?<\\ud835>.)', '[a-', '[\\', '(?<a>(?<a>x))', '(?<a>x(?<a>y))', '(?<\ud835>.)', '(?<a\ud835>.)'];
for (const s of cases) p(JSON.stringify(s), E(() => String(new RegExp(s))));
for (const f of ['gg', 'G', 'uv', 'x', ' ', 'dgimsuyd', 'vu', 'gimsuyvd']) p('flags ' + JSON.stringify(f), E(() => String(new RegExp('a', f))));
p(E(() => eval('/a{2,1}/')), E(() => new Function('return /(?<n>a)(?<n>b)/')), E(() => eval('/a/gg')));
"""


def test_syntax_errors_legacy_mode(run):
    """CATCHES: invalid non-unicode patterns and flag strings accepted, or rejected with a different SyntaxError message (nothing to repeat, unterminated class/group, bad group names, duplicate names, quantified lookbehind, inline modifier errors, bad flags)."""
    _ok(run, PROG_ERRORS_LEGACY, "errors_legacy")


PROG_ERRORS_UNICODE = r"""
const cases = ['{', '}', ']', 'a{', 'a{1', '\\-', '\\a', '\\z', '\\c', '\\c1', '[\\c1]', '\\x1', '\\xg0', '\\u12', '\\u{}', '\\u{110000}', '\\u{12x}',
  '\\u{FFFFFFFFFFFF}', '\\01', '[\\01]', '\\1', '(a)\\2', '\\8', '\\k<a>', '\\k', '\\p', '\\pL', '\\p{', '\\p{L', '\\p{ L}', '\\p{Foo}', '\\p{gc=Foo}',
  '\\p{Foo=L}', '\\p{lu}', '\\p{Script}', '\\p{General_Category}', '\\p{ascii}', '\\p{Block=Basic_Latin}', '\\P{RGI_Emoji}', '\\p{RGI_Emoji}', '[\\d-z]', '[a-\\w]', '[\\p{L}-z]', '[\\z]', '(?=a)*', '(?!a)+', '(?=a){1}',
  '(?<a\\u{E000}>.)', '(?<a\\u{1D7CE}\\u0300>.)', '(?<\\ud835>.)', '[\\uDBFF\\uDFFF-\\uD800\\uDC00]', '\\uD83D\\u12', '(?<\\uD835\\u0041>x)', '[\\x4]', '[\\u{110000}]'];
for (const s of cases) p(JSON.stringify(s), E(() => String(new RegExp(s, 'u'))));
const ok = ['\\/', '[\\-]', '\\p{L}', '\\P{Lu}', '\\p{gc=L}', '\\p{sc=Grek}', '\\p{scx=Grek}', '\\u{1F600}', '[\\u{1F600}-\\u{1F64F}]', '(?<\\u0061>.)\\k<a>', '\\0', '[\\0]', '\\^\\$\\\\\\.\\*\\+\\?\\(\\)\\[\\]\\{\\}\\|', '(?<\\uD835\\uDC9C>x)\\k<\\u{1D49C}>', '\\uD83D\\u0041', '[\\x41\\u0042\\u{43}\\cJ\\f\\v\\t]'];
for (const s of ok) p('valid', JSON.stringify(s), E(() => String(new RegExp(s, 'u'))));
p(E(() => eval('/\\p{Foo}/u')), E(() => new RegExp('\\p{L}').test('p{L}')));
"""


def test_syntax_errors_unicode_mode(run):
    """CATCHES: u-mode parsers that keep Annex B leniency (lone braces, identity escapes, \\c, short \\x/\\u, octal escapes, dangling backreferences), accept unknown or loosely-spelled \\p{...} names, or report different SyntaxError messages."""
    _ok(run, PROG_ERRORS_UNICODE, "errors_unicode")


PROG_ERRORS_VMODE = r"""
const cases = ['[a&&&b]', '[a&&b--c]', '[ab&&c]', '[a--b&&c]', '[ab--c]', '[(]', '[)]', '[{]', '[}]', '[/]', '[|]', '[-]', '[a-]',
  '[&&a]', '[a&&]', '[!!]', '[a##]', '[a$$]', '[\\q]', '[\\q{a]', '[\\qa}]', '[\\z]', '[\\c1]', '[\\c]', '[\\x4]', '[\\', '[^\\q{ab}]',
  '[^\\p{RGI_Emoji}]', '\\P{RGI_Emoji}', '[\\P{Emoji_Keycap_Sequence}]', '[[a-z]-b]', '[z-a]', '[\\d-z]', '[\\p{Foo}]', '[\\p{L]', '[\\p{ L}]',
  '[\\pL]', '[a', '[[a]', '[a-z--[aeiou]]', '[^[^\\q{ab}]]', '\\p{RGI_Emoji', '[\\q{a|bc}--[^a]]', '[a-\\q{bc}]', '[a-[bc]]', '[a-'];
for (const s of cases) p(JSON.stringify(s), E(() => String(new RegExp(s, 'v'))));
const ok = ['[\\p{Basic_Emoji}--\\q{x}]', '[\\q{a|bc}&&\\q{bc}]', '[^[^a]]', '[\\q{}]', '[\\w--\\d--_]', '[\\p{L}&&\\p{ASCII}&&[^a-y]]', '[\\-\\&\\!\\#\\%\\,\\:\\;\\<\\=\\>\\@\\`\\~]', '[a&b]', '[^\\q{a|b}]', '[]', '[^]', '[a[]]', '[\\p{sc=Grek}]', '[\\p{Script=Latin}--[a-z]]', '[\\p{gc=Lu}&&\\p{ASCII}]'];
for (const s of ok) p('valid', JSON.stringify(s), E(() => String(new RegExp(s, 'v'))));
"""


def test_syntax_errors_v_mode(run):
    """CATCHES: v-mode (unicodeSets) parsers that accept mixed union/intersection/subtraction operators, unescaped class syntax characters, reserved doubled punctuators, malformed \\q{...}, negated classes containing strings, or that word the errors differently."""
    _ok(run, PROG_ERRORS_VMODE, "errors_vmode")


def test_regex_literal_early_errors(run, workdir):
    """CATCHES: an invalid regular-expression literal that is not reported as an early SyntaxError before any code runs, or whose -e / script-file report format and message differ from the reference."""
    r = run(["-e", "console.log('never'); const r = /(?<a>.)\\k<b>/;"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"SyntaxError: invalid named back reference <b> (line 1)\n")
    r = run(["-e", "console.log('x');\nlet q = 1;\nconst r = /x/gig;"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"SyntaxError: duplicate regular expression flag g (line 3)\n")
    write_files(workdir, {"bad.js": "console.log('first');\nconst r = /[b-a]/u;\n"})
    r = run(["bad.js"])
    assert (r.returncode, r.stdout, r.stderr) == (1, b"", b"Uncaught SyntaxError: range out of order in character class\n")


# ---------------------------------------------------------------- String methods

PROG_REPLACE_PATTERNS = r"""
const s = 'abc-def-ghi';
for (const rep of ['[$&]', '[$`]', "[$']", '[$$]', '[$]', '$', '[$0]', '[$1]', '[$2]', '[$3]', '[$01]', '[$001]', '[$10]', '[$11]', '[$1$2]',
                   '[$<n>]', '[$<x>]', '[$<n]', '[$<>]', '[$x]', '[$$1]', '[$$$1]', '[$&$&]', '$`|$\'']) {
  p(rep, s.replace(/(\w)(\w)(?<n>\w)/, rep), s.replace('def', rep), s.replace(/(d)(e)/g, rep));
}
const re12 = /(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)(l)/;
p('abcdefghijklm'.replace(re12, '$12|$11|$10|$1|$13|$012|$00|$99|$100'));
p('abcdefghijklm'.replace(/(a)(b)/, '$3|$10|$21|$9|$02|$03'));
p('abc'.replace(/(z)?b/, '[$1]'), 'abc'.replace(/(?<n>z)?b/, '[$<n>]'), 'abc'.replace(/b/, {toString() { return '$&$&'; }}), 'abc'.replace('b', "$`$'"));
p('aXbXc'.replaceAll('X', '$&$&'), 'aaa'.replaceAll('', '-'), 'aaa'.replaceAll('a', "$'"), 'xx'.replaceAll('x', '$$'), 'aXbXc'.replace('X', '$<n>'));
p('caf\u00E9'.replace(/\u00E9/u, '$&$&'), 'abc'.replace(/(?<n>b)/, '$<n>$<n>'), 'abc'.replace(/(b)/, '$<n>'), '2025-01-02'.replace(/(?<y>\d+)-(?<m>\d+)-(?<d>\d+)/, '$<d>.$<m>.$<y>'));
p('one two'.replace(/(\w+) (\w+)/, '$2 $1'), 'a.b.c'.replace(/\./g, '$'), 'a+b'.replace('+', '$&$&'), 'abc'.replace(/$/, '$`'), 'abc'.replace(/^/, "$'"));
const fake = /x/; fake.exec = function () { return { 0: 'x', length: 1, index: 0, groups: { n: 'G' } }; };
p('x'.replace(fake, '[$<n>]'));
const fake2 = /x/; fake2.exec = function () { return { 0: 'x', length: 1, index: 0, groups: null }; };
p(E(() => 'x'.replace(fake2, '[$<n>]')), E(() => 'x'.replace(fake2, '[$1]')), E(() => 'x'.replace(fake2, () => 'fn')));
const fake3 = /x/; fake3.exec = function () { return { 0: 'xy', length: 3, 1: 7, 2: undefined, index: -2, groups: undefined }; };
p('axb'.replace(fake3, '[$1|$2|$&]'));
const fake5 = /x/; fake5.exec = function () { return { 0: 'x', length: 1, index: 0, groups: 'abc' }; };
p('x'.replace(fake5, '[$<length>|$<0>|$<nope>]'));
const fake4 = /x/g; let n4 = 0; fake4.exec = function () { return n4++ < 2 ? { 0: 'b', length: 1, index: 3 - n4 } : null; };
p('abcd'.replace(fake4, '_'));
"""


def test_replace_substitution_patterns(run):
    """CATCHES: wrong GetSubstitution handling of $&, $`, $', $$, $<name>, one/two-digit $n (including $0, $00, $10 with fewer groups, $012), literal patterns for string searches, or custom exec results with odd index/groups values."""
    _ok(run, PROG_REPLACE_PATTERNS, "replace_patterns")


PROG_REPLACE_CALLBACKS = r"""
p('aaa'.replace(/a/g, (m, off, str) => `${m}${off}${str.length}`));
p('x1y2'.replace(/(\d)/g, (m, g1, off, str, ...rest) => JSON.stringify([m, g1, off, str, rest.length])));
p('x1y2'.replace(/(?<d>\d)/g, (...args) => JSON.stringify(args)));
p('abc'.replace(/(z)?b/, (m, g1) => String(g1)), 'abc'.replace(/b/, () => 42), 'abc'.replace(/b/, () => ({ toString() { return '$&'; } })));
p('aXbXc'.replaceAll('X', (m, i, str) => `${i}/${str.length}`), 'abab'.replaceAll(/b/g, (m, i) => i), 'aaa'.replace('a', (...a) => a.length));
p(E(() => 'a'.replaceAll(/a/, 'b')), E(() => 'a'.replaceAll(/a/y, 'b')), 'aXbx'.replaceAll(/x/gi, '_'), E(() => 'a'.replaceAll({ [Symbol.match]: true, flags: 'i' }, 'b')));
const order = [];
'a1b2'.replace(/\d/g, (m) => { order.push(m); return ''; });
p(order.join(','), 'ab'.replace(/(?:)/g, (m, i) => `<${i}>`), '\u{1F600}x'.replace(/(?:)/gu, (m, i) => i));
const re = /(?<k>\w)=(?<v>\w)/g;
p('a=1, b=2'.replace(re, (...args) => { const g = args.at(-1); return `${g.v}:${g.k}`; }), re.lastIndex);
const reentrant = /o/g;
p('foo'.replace(reentrant, () => 'bar'.replace(reentrant, '0')), reentrant.lastIndex);
p(E(() => 'abc'.replace(/b/, () => { throw new RangeError('stop'); })), String.prototype.replace.call(123, /2/, 'x'), E(() => String.prototype.replace.call(null, 'a', 'b')));
p('abc'.replace('', '_'), 'abc'.replace(undefined, '_'), 'undefined!'.replace(undefined, '_'), 'null'.replace(null, 'N'), 'a1'.replace(1, 'one'));
p('aaaa'.replaceAll('aa', 'b'), 'abcabc'.replaceAll('bc', '$`'), '\u{1F600}\u{1F600}'.replaceAll('\uDE00', '!').length);
"""


def test_replace_callbacks_and_replaceall(run):
    """CATCHES: replacer callbacks receiving wrong arguments (missing the groups object, wrong offsets), results not stringified, replaceAll accepting a non-global regexp, string replaceAll not replacing every (or empty) occurrence, or wrong coercion of undefined/null search values."""
    _ok(run, PROG_REPLACE_CALLBACKS, "replace_callbacks")


PROG_SPLIT = r"""
const J = JSON.stringify;
p(J('a1b2c3'.split(/\d/)), J('a1b2c3'.split(/(\d)/)), J('a1b2c3'.split(/(\d)/, 3)), J('a1b2c3'.split(/\d/, 0)), J('a1b2c3'.split(/\d/, -1)));
p(J(''.split(/x/)), J(''.split(/(?:)/)), J(''.split('')), J('abc'.split(/(?:)/)), J('abc'.split(/(?:)/, 2)), J('abc'.split()), J('abc'.split(undefined, 0)));
p(J('a,b,,c'.split(/,/)), J('a,b,,c'.split(/(,)/)), J('test'.split(/(t)?/)), J('A<B>bold</B>and<CODE>coded</CODE>'.split(/<(\/)?([^<>]+)>/)));
p(J('ab'.split(/a*?/)), J('ab'.split(/a*/)), J('abc'.split(/$/)), J('abc'.split(/^/m)), J('a\nb\nc'.split(/^/m)), J('a\nb'.split(/$/m)));
p(J('a b  c'.split(/\s+/)), J(' a b '.split(/\s/)), J('aXbxc'.split(/x/i)), J('a1b'.split(/(?<d>\d)/)), J('abc'.split(/b/y)), J('xaxbx'.split(/x/y)));
p(J('\u{1F600}a\u{1F600}'.split(/a/u)), J('\u{1F600}\u{1F600}'.split(/(?:)/u)), J('\u{1F600}\u{1F600}'.split(/(?:)/)), J('a\u{1F600}b'.split(/(?=\uDE00)/u)), J('a\u{1F600}b'.split(/(?=\uDE00)/)));
p(J('a1b2c3'.split(/\d/, 2.7)), J('a1b2c3'.split(/\d/, 2 ** 32 + 1)), J('a1b2'.split(/\d/, undefined)), J('a1b2'.split(/\d/, '2')), J('abc'.split('', 2)));
p(J('a,b'.split(',')), J('a,,b'.split(',,')), J('abc'.split('abc')), J('abc'.split('abcd')), J(''.split(',')), J('\u{1F600}'.split('')));
p(J('one  two'.split(/(\s)(\s)?/)), J('aXbXc'.split(/(x)/i, 2)), J('abcdef'.split(/(?<=c)/)), J('2024-01-02T10:20'.split(/[-T:]/)));
const g = /,/g; g.lastIndex = 2; p(J('a,b,c'.split(g)), g.lastIndex);
const lim = { valueOf() { return 1; } }; p(J('a-b-c'.split(/-/, lim)), J('a-b'.split({ [Symbol.split]: (s, l) => [s, l] }, 9)));
"""


def test_split(run):
    """CATCHES: split implementations that mishandle limits (ToUint32, 0, negative), drop or misplace captured separators, produce extra empty strings at empty matches, split surrogate pairs in u mode, or mutate the separator regexp's lastIndex."""
    _ok(run, PROG_SPLIT, "split")


PROG_MATCH_SEARCH = r"""
const J = JSON.stringify;
p(J('one two three'.match(/\w+/g)), fm('one two'.match(/(\w)(\w+)/)), J('xyz'.match(/q/g)), J('xyz'.match(/q/)), J('a'.match()), J('a.b'.match('.')), E(() => 'a+b'.match('+b')), J('a+b'.match('\\+b')));
const m = 'one two'.match(/(?<f>\w)\w*/); p(m.index, m.input, J(m.groups), m.length);
p(J([...'a1b22c333'.matchAll(/\d+/g)].map(m => [m[0], m.index])), J([...'a1b22'.matchAll(/(?<d>\d)/g)].map(m => m.groups.d)));
p(E(() => 'a'.matchAll(/a/)), [...'aXa'.matchAll('a')].length, J([...'a.a'.matchAll('.')].map(m => m.index)), E(() => [...'a+a'.matchAll('+')]));
const it = 'ab'.matchAll(/./g);
p(Object.prototype.toString.call(it), typeof it.next, it[Symbol.iterator]() === it, J(it.next()), it.next().value[0], J(it.next()), J(it.next()));
const src = /\d/g; src.lastIndex = 2; const it2 = 'a1b2c3'.matchAll(src); p(src.lastIndex, J([...it2].map(m => m[0])), src.lastIndex);
p(J([...'\u{1F600}\u{1F600}'.matchAll(/(?:)/gu)].map(m => m.index)), J([...'\u{1F600}'.matchAll(/(?:)/g)].map(m => m.index)), J([...'aaa'.matchAll(/a*/g)].map(m => m[0])));
p('hello'.search(/l/), 'hello'.search(/z/), 'hello'.search('l+'), 'hello'.search(), 'a.b'.search('.'), 'aBc'.search(/b/i), 'x\ny'.search(/^y/m));
const g = /l/g; g.lastIndex = 3; p('hello'.search(g), g.lastIndex);
const y = /l/y; p('hello'.search(y), y.lastIndex, 'lo'.search(y));
p(fm('x'.match(/x/y)), fm('ax'.match(/x/y)), J('xx'.match(/x/gy)), J('xxax'.match(/x/gy)), J('\u{1F600}a'.match(/./gu)), J('aaa'.match(/^a/gm)));
const mg = 'a1b2'.match(/(\d)/g); p(J(mg), mg.index, mg.groups, Object.keys(mg).join(','));
p(J('abc'.match(/(?:)/g)), J('ABC'.match(/b/gi)), J('test'.match(/t(e)?/g)), String.prototype.match.call(12345, /3(4)/)[1], J('a\u2028b'.match(/^b/gm)));
p([...RegExp.prototype[Symbol.matchAll].call(/a/, 'aa')].length, J('a1'.match({ toString() { return '\\d'; } })), 'abc'.search({ [Symbol.search]: undefined, toString() { return 'c'; } }), J([...'a1b2'.matchAll({ [Symbol.matchAll]: undefined, toString() { return '\\d'; } })].map(m => m[0])));
"""


def test_match_matchall_search(run):
    """CATCHES: global match returning captures, matchAll not requiring /g or not cloning the regexp (shared lastIndex), the iterator protocol/toStringTag of RegExp String Iterator, search not restoring lastIndex, or string arguments not converted to regexps."""
    _ok(run, PROG_MATCH_SEARCH, "match_search")


PROG_SYMBOLS = r"""
const log = [];
const re = /b/g;
re.exec = function (s) { log.push('exec@' + this.lastIndex); return RegExp.prototype.exec.call(this, s); };
p('abcb'.replace(re, 'X'), log.join(','));
log.length = 0; p(re.test('xb'), log.join(','));
log.length = 0; p(JSON.stringify('abcb'.match(re)), log.join(','));
log.length = 0; p('abcb'.search(re), log.join(','));
const bad = /a/; bad.exec = () => 5; p(E(() => bad.test('a')), E(() => 'a'.replace(bad, 'x')));
const nul = /a/; nul.exec = () => null; p(nul.test('a'), 'a'.replace(nul, 'X'), 'a'.match(nul));
class MyRE extends RegExp {
  exec(s) { const m = super.exec(s); if (m) m[0] = m[0].toUpperCase(); return m; }
  get [Symbol.species]() { return RegExp; }
}
const mr = new MyRE('a+', 'g');
p(mr instanceof MyRE, mr instanceof RegExp, String(mr), mr.flags, 'caaab'.replace(mr, '<$&>'), JSON.stringify('caaab'.match(mr)), mr.test('a'), Object.getPrototypeOf(new MyRE('x')) === MyRE.prototype);
class Sp extends RegExp { static get [Symbol.species]() { log.push('species'); return RegExp; } }
log.length = 0; p(JSON.stringify('a1b2'.split(new Sp('\\d'))), log.join(','), RegExp[Symbol.species] === RegExp);
log.length = 0; p([...'a1b2'.matchAll(new Sp('\\d', 'g'))].length, log.join(','));
const custom = { flags: 'g', [Symbol.split](s, lim) { return ['split', s, lim]; }, [Symbol.replace](s, r) { return 'rep:' + s + r; }, [Symbol.search]() { return 99; }, [Symbol.match]() { return ['m']; }, [Symbol.matchAll]() { return 'ma'; } };
p(JSON.stringify('str'.split(custom, 3)), 'str'.replace(custom, '!'), 'str'.search(custom), JSON.stringify('str'.match(custom)), 'str'.matchAll(custom), 'str'.replaceAll(custom, '?'));
p(E(() => 'str'.matchAll({ [Symbol.match]: true })), JSON.stringify('a.b'.split({ [Symbol.split]: undefined, toString() { return '.'; } })));
p(E(() => 'x'.startsWith({ [Symbol.match]: true })), E(() => 'x'.includes(/x/)), E(() => 'x'.endsWith(/x/)));
const r2 = /x/; r2[Symbol.match] = false; p('/x/'.startsWith(r2), '/x/'.includes(r2), '/x/'.endsWith(r2));
p(JSON.stringify(RegExp.prototype[Symbol.match].call(/a/g, 'aa')), RegExp.prototype[Symbol.replace].call(/a/, 'aa', 'b'), RegExp.prototype[Symbol.search].call(/b/, 'ab'));
p(E(() => RegExp.prototype[Symbol.match].call('nope', 'a')), E(() => RegExp.prototype[Symbol.replace].call(1, 'a', 'b')), E(() => RegExp.prototype.test.call(1, 'a')));
const fl = /a/g; Object.defineProperty(fl, 'flags', { value: 'y' }); p(JSON.stringify('baaa'.split(fl)));
const exC = /./g; let calls = 0;
exC.exec = function (s) { calls++; return calls > 3 ? null : { 0: '', length: 1, index: calls, input: s }; };
p('abc'.replace(exC, '-'), calls);
const r5 = /a/; r5.exec = 5; p(r5.test('a'), 'xa'.search(r5), E(() => RegExp.prototype.test.call({ exec: 5 }, 'a')), E(() => RegExp.prototype[Symbol.search].call({ exec() { return { index: 'idx' }; }, lastIndex: 0 }, 'z')));
const genericMatch = { flags: 'g', lastIndex: 0, global: true, exec(s) { return this.lastIndex < 2 ? { 0: 'q', index: this.lastIndex++ } : null; } };
p(E(() => RegExp.prototype[Symbol.match].call(genericMatch, 'zzz')));
"""


def test_symbol_protocols_and_subclassing(run):
    """CATCHES: String methods that bypass Symbol.replace/split/match/search/matchAll or a user-overridden exec, RegExp subclasses whose exec/species are ignored, IsRegExp checks in startsWith/includes/endsWith, or invalid exec results not raising TypeError."""
    _ok(run, PROG_SYMBOLS, "symbols")


PROG_ESCAPE = r"""
p(RegExp.escape('foo.bar*baz'), RegExp.escape('1abc'), RegExp.escape('Abc'), RegExp.escape('_x'), RegExp.escape('a b\tc\n'));
p(RegExp.escape(',-=<>#&!%:;@~\'`"'), RegExp.escape('^$\\.*+?()[]{}|/'), RegExp.escape('\v\f\r'));
p(RegExp.escape('\u00A0\u2028\u2029\uFEFF\u3000z'), RegExp.escape('\u{1F600}\u00E9'), RegExp.escape('\uD800x\uDFFF'), JSON.stringify(RegExp.escape('')), RegExp.escape('9'), RegExp.escape('\u00E9a'));
p(E(() => RegExp.escape(1)), E(() => RegExp.escape(new String('a'))), E(() => RegExp.escape()));
for (const s of ['a.b|c', '(x)[y]{z}', 'a\nb', '^$', '-\u{1F600}-', 'x/y']) {
  const re = new RegExp('^' + RegExp.escape(s) + '$', 'u');
  p(JSON.stringify(s), re.test(s), re.test(s + 'x'), new RegExp('[' + RegExp.escape(s) + ']', 'v').test(s[0]));
}
p(RegExp.escape.length, RegExp.escape.name, typeof RegExp.escape);
"""


def test_regexp_escape(run):
    """CATCHES: RegExp.escape that misses syntax characters, does not hex-escape a leading alphanumeric, other punctuators, whitespace or lone surrogates, or accepts non-string arguments; escaped strings must round-trip through u- and v-mode patterns."""
    _ok(run, PROG_ESCAPE, "escape")


PROG_LEGACY = r"""
const L = () => JSON.stringify([RegExp.input, RegExp.$_, RegExp.lastMatch, RegExp['$&'], RegExp.lastParen, RegExp['$+'], RegExp.leftContext, RegExp['$`'], RegExp.rightContext, RegExp["$'"], RegExp.$1, RegExp.$2, RegExp.$3, RegExp.$9]);
/(\d+)-(\d+)/.exec('tel: 555-1234 ok'); p(L());
'xyz'.replace(/(y)/, 'Y'); p(L());
/nomatch/.test('abc'); p(L());
'a1b2'.match(/\d/g); p(L());
/(a)|(b)/.exec('b'); p(JSON.stringify([RegExp.lastParen, RegExp.$1, RegExp.$2]));
RegExp.input = 'manual'; p(RegExp.input, RegExp.$_); RegExp.$_ = 42; p(RegExp.input, typeof RegExp.input);
const d = Object.getOwnPropertyDescriptor(RegExp, '$1'); p(typeof d.get, d.set, d.enumerable, d.configurable);
const di = Object.getOwnPropertyDescriptor(RegExp, 'input'); p(typeof di.get, typeof di.set, Object.getOwnPropertyDescriptor(RegExp, '$_').enumerable);
p(E(() => d.get.call({})), E(() => di.set.call({}, 'x')));
class Sub extends RegExp {} p(E(() => Sub.$1), E(() => Sub.lastMatch));
'abc'.split(/(b)/); p(RegExp.$1, RegExp.lastMatch);
/(\w)(\w)(\w)(\w)(\w)(\w)(\w)(\w)(\w)(\w)/.exec('abcdefghijk'); p(RegExp.$9, RegExp.lastParen, RegExp.$1, RegExp.rightContext);
/\u{1F600}(.)/u.exec('x\u{1F600}yz'); p(RegExp.$1, RegExp.leftContext, RegExp.rightContext, RegExp.lastMatch.length);
'q'.replace(/q/, () => { p('inside', RegExp.lastMatch); return ''; });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_legacy_regexp_statics(run, tier):
    """CATCHES: legacy RegExp.$1-$9 / lastMatch / lastParen / leftContext / rightContext / input statics that are not updated by every successful match (exec, replace, match, split), are clobbered by failed matches, or lack the receiver brand check."""
    _ok(run, PROG_LEGACY, "legacy", tier)


# ---------------------------------------------------------------- engine robustness

PROG_CATASTROPHIC = r"""
p(/^(a+)+$/.test('a'.repeat(25) + 'b'), /^(\w+\s?)*$/.test('a'.repeat(22) + '!'), /(?:a+)+b/.test('a'.repeat(12)), /(a|aa)+c/.test('a'.repeat(16)));
p(/(?:ab)*c/.test('ab'.repeat(300) + 'c'), /(a|b)*c/.test('ab'.repeat(200) + 'c'), /a*c/.test('a'.repeat(30000) + 'c'), /[^"]*"/.exec('x'.repeat(20000) + '"')[0].length);
p('x'.repeat(4000).replace(/x/g, 'yy').length, 'a,'.repeat(2000).split(/,/).length, ('ab'.repeat(2000)).match(/ab/g).length, /(\d+)\1/.test('12'.repeat(300) + '3'));
p(/^(?:a|b|c|d|e)*$/.test('abcde'.repeat(60)), /(?=(a+))a*b\1/.test('a'.repeat(200) + 'b' + 'a'.repeat(200)));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_pathological_patterns_finish(run, tier):
    """CATCHES: backtracking engines that hang on exponential patterns (nested quantifiers) instead of failing fast, or recursive matchers that overflow on long inputs and lose correct answers for long but linear matches."""
    _ok(run, PROG_CATASTROPHIC, "catastrophic", tier)


PROG_DISCARDED_RESULTS = r"""
const re = /(\d)(\d)?/g;
const sticky = /a/y;
function work(s, i) {
  s.replace(re, '#');
  s.split(/(\d)/);
  s.match(/\d+/);
  s.replace(/[xy]/g, '');
  re.exec(s);
  sticky.lastIndex = i % 3;
  'aab'.replace(sticky, 'Z');
  return sticky.lastIndex;
}
let hits = 0;
for (let i = 0; i < 120; i++) {
  hits += work('x' + i + 'y', i);
  if (i % 40 === 7) p(i, re.lastIndex, RegExp.lastMatch, RegExp.$1, RegExp.$2, RegExp.leftContext, RegExp.rightContext);
}
p(hits, re.lastIndex, sticky.lastIndex, RegExp.input, RegExp.lastMatch);
const st2 = /b/y;
function stickyStr(i) { st2.lastIndex = String(i % 4); 'abab'.replace(st2, '_'); return st2.lastIndex; }
let acc2 = ''; for (let i = 0; i < 40; i++) acc2 += stickyStr(i); p(acc2);
const u = /(?:)/gu;
function emptyU(s) { s.replace(u, '-'); s.split(u); return u.lastIndex; }
let lis = 0; for (let i = 0; i < 30; i++) lis += emptyU('\u{1F600}\u{1F600}'); p(lis, RegExp.leftContext.length, RegExp.rightContext.length);
let execCalls = 0;
const origExec = RegExp.prototype.exec;
const r7 = /7/;
function viaProto() { 'a1b2'.replace(/\d/g, '-'); 'a1b2'.split(/\d/); 'a1b2'.match(/\d/); r7.exec('7'); r7.test('8'); }
for (let i = 0; i < 60; i++) {
  if (i === 30) RegExp.prototype.exec = function (s) { execCalls++; return origExec.call(this, s); };
  viaProto();
}
RegExp.prototype.exec = origExec;
p(execCalls);
let globalReads = 0;
const gdesc = Object.getOwnPropertyDescriptor(RegExp.prototype, 'global');
function flagUse() { 'aXa'.replace(/a/g, 'b'); 'aXa'.split(/X/); }
for (let i = 0; i < 40; i++) {
  if (i === 20) Object.defineProperty(RegExp.prototype, 'global', { get() { globalReads++; return gdesc.get.call(this); }, configurable: true });
  flagUse();
}
Object.defineProperty(RegExp.prototype, 'global', gdesc);
p(globalReads);
const fr = /a/g; Object.defineProperty(fr, 'lastIndex', { writable: false, value: 0 });
function frozen() { try { 'aa'.replace(fr, 'b'); return 0; } catch (e) { return e instanceof TypeError ? 1 : 100; } }
let errs = 0; for (let i = 0; i < 40; i++) errs += frozen(); p(errs);
const own = /q/g; own.exec = () => null;
function ownExec() { 'qq'.replace(own, 'z'); return own.lastIndex; }
let n3 = 0; for (let i = 0; i < 40; i++) if (ownExec() === 0) n3++; p(n3);
let coerced = 0; const rep = { toString() { coerced++; return 'R'; } };
function coerce() { 'abc'.replace(/b/, rep); 'abc'.replace(/zz/g, rep); }
for (let i = 0; i < 40; i++) coerce(); p(coerced);
const sym = /x/g; let symCalls = 0;
function symRep() { 'x'.replace(sym, 'y'); }
for (let i = 0; i < 40; i++) { if (i === 20) sym[Symbol.replace] = function () { symCalls++; return ''; }; symRep(); } p(symCalls);
let splitLim = 0; const limObj = { valueOf() { splitLim++; return 2; } };
function lim() { 'a,b,c'.split(/,/, limObj); }
for (let i = 0; i < 40; i++) lim(); p(splitLim);
let spCount = 0; class Sp extends RegExp { static get [Symbol.species]() { spCount++; return RegExp; } }
const spRe = new Sp(',');
function spec() { 'a,b'.split(spRe); }
for (let i = 0; i < 40; i++) spec(); p(spCount);
const ex = /o/g;
function execDisc(s) { ex.exec(s); return ex.lastIndex; }
let exAcc = []; for (let i = 0; i < 24; i++) exAcc.push(execDisc('foo boo')); p(exAcc.join(''));
const exS = /o/y; function execSticky(s) { exS.exec(s); return exS.lastIndex; }
let exS2 = []; for (let i = 0; i < 12; i++) { exS.lastIndex = i % 4; exS2.push(execSticky('fooo')); } p(exS2.join(''));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_discarded_replace_split_match_side_effects(run, tier):
    """CATCHES: tiers that optimise away regexp calls whose result is unused (`s.replace(re, x);`, `s.split(re);`, `s.match(/lit/);`, `re.exec(s);`) and thereby lose lastIndex updates, legacy RegExp statics, TypeErrors from non-writable lastIndex, replacement/limit coercions, or calls to user-overridden exec/flag getters/Symbol.replace/species."""
    _ok(run, PROG_DISCARDED_RESULTS, "discarded_results", tier)

PROG_DISCARDED_SPLIT = r"""
const L = () => [RegExp.lastMatch, RegExp.leftContext, RegExp.rightContext, RegExp.$1, RegExp.input].join('/');
const sy = /(,)/y, emp = /(?:)/, end = /$/, nul = /(x)?/;
function a(s) { s.split(sy); return L(); }
function b(s) { s.split(emp); return L(); }
function c(s) { s.split(end); return L(); }
function d(s) { s.split(nul); return L(); }
function e(s) { s.split(','); s.split(/b/); return L(); }
const outs = { a: [], b: [], c: [], d: [], e: [] };
for (let i = 0; i < 30; i++) {
  outs.a.push(a(i % 2 ? 'p,q,,r' : ',x,'));
  outs.b.push(b(i % 2 ? 'ab' : '\u{1F600}z'));
  outs.c.push(c(i % 2 ? 'abc' : ''));
  outs.d.push(d(i % 2 ? '' : 'yxy'));
  outs.e.push(e('abc,d'));
}
for (const k of Object.keys(outs)) p(k, [...new Set(outs[k])].join(' ; '));
const ownCtor = /-/; ownCtor.constructor = RegExp; let speciesHits = 0;
function f(s) { s.split(ownCtor); }
for (let i = 0; i < 20; i++) f('1-2');
p(L());
const sd = Object.getOwnPropertyDescriptor(RegExp, Symbol.species);
Object.defineProperty(RegExp, Symbol.species, { get() { speciesHits++; return this; }, configurable: true });
function g(s) { s.split(/;/); }
for (let i = 0; i < 20; i++) g('u;v');
Object.defineProperty(RegExp, Symbol.species, sd);
p(speciesHits, L());
let globalReads = 0; const RE = RegExp;
Object.defineProperty(globalThis, 'RegExp', { get() { globalReads++; return RE; }, configurable: true });
function h(s) { s.split(/=/); }
for (let i = 0; i < 20; i++) h('k=v');
Object.defineProperty(globalThis, 'RegExp', { value: RE, writable: true, configurable: true, enumerable: false });
p(typeof globalReads, L());
let splitCalls = 0; const origSplit = RegExp.prototype[Symbol.split];
function k(s) { s.split(/!/); }
for (let i = 0; i < 20; i++) { if (i === 10) RegExp.prototype[Symbol.split] = function (str, lim) { splitCalls++; return origSplit.call(this, str, lim); }; k('a!b'); }
RegExp.prototype[Symbol.split] = origSplit;
p(splitCalls, L());
let ctorReads = 0; const protoCtor = Object.getOwnPropertyDescriptor(RegExp.prototype, 'constructor');
function m(s) { s.split(/\./); }
for (let i = 0; i < 20; i++) { if (i === 10) Object.defineProperty(RegExp.prototype, 'constructor', { get() { ctorReads++; return RE; }, configurable: true }); m('a.b'); }
Object.defineProperty(RegExp.prototype, 'constructor', protoCtor);
p(ctorReads, L());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_discarded_split_guards_and_legacy_state(run, tier):
    """CATCHES: a dead-result `s.split(re);` shortcut that leaves the legacy RegExp statics in a different state than the spec split loop (sticky separators, empty matches, empty input, a match at the very end), or that keeps running after the separator, RegExp.prototype[Symbol.split], .constructor or @@species has been customised."""
    _ok(run, PROG_DISCARDED_SPLIT, "discarded_split", tier)

PROG_SEARCH_PATHS = r"""
const res = [];
for (let n = 0; n < 20; n++) {
  const s = 'ab'.repeat(n) + 'needle' + 'z'.repeat(n % 5);
  res.push([s.search(/needle/), /needle/.exec(s).index, s.match(/le/g).length, s.replace(/e/g, '').length, s.search(/needlf/), s.search(/z$/)].join(':'));
}
p(res.join(' '));
const st = /ne/y; const out = []; for (let i = 0; i < 12; i++) { st.lastIndex = i; out.push(st.test('xxxxxxxxneedle') ? i + '@' + st.lastIndex : '-'); } p(out.join(','));
const gl = /ne/g; const pos = []; let m; while ((m = gl.exec('ne-ne--ne---ne----ne'))) pos.push(m.index); p(pos.join(','));
p('\u00E9\u00E9needle'.search(/needle/), '\u{1F600}needle'.search(/needle/), '\u{1F600}needle'.search(/needle/u), '\u{1F600}needle'.replace(/needle/u, '!'), 'needle'.search(/needle/y), 'xneedle'.search(/needle/y));
const an = /^ab/g; an.lastIndex = 1; p(an.test('abab'), an.lastIndex, /^ab/.exec('xab'), /^ab|cd/.exec('xcd').index, /(?:^ab)/.test('ab'));
const anm = /^ab/gm; anm.lastIndex = 1; p(anm.test('xx\nab'), anm.lastIndex);
p('xxxx9yy'.search(/\d/), 'xxxx9yy'.search(/[^x]/), 'zzzz'.search(/z*q?/), 'aaaab'.search(/a*b/), '----A'.search(/[a-z]/i), '----\u212A'.search(/k/iu), '----\u212A'.search(/k/i), '____\u03C2'.search(/\u03C3/i), '\u00FF\u0178'.search(/\u0178/i), '--\u017F'.search(/s/iu), 'xx\u212A'.search(/[k]/iu));
p('aaa\u00E9b'.search(/\u00E9b/), '\u00E9\u00E9\u00E9'.search(/[\u00E0-\u00FF]{3}/), 'abc'.search(/(?:x|y|c)/), 'abc'.search(/x*c/), 'abcd'.search(/[cd]+$/), 'ab\ncd'.search(/.$/));
p('abcabc'.search(/\x63/), 'A\u0100'.search(/\u0100/), 'one two'.search(/\btwo/), 'one two'.search(/(?=two)/), 'aXbX'.search(/x/gi), 'q'.repeat(40).search(/q{40}/), 'q'.repeat(39).search(/q{40}/));
const long = 'abcdefgh'.repeat(10);
p(long.search(/h/), long.lastIndexOf('h'), long.match(/gh/g).length, long.search(/hab/), long.search(/habc$/), long.search(/xyz/), long.match(/a/g).length, long.search(/bcd(?=e)/));
p('abcn'.search(/ne/), 'nnnnnnnnnnnnne'.search(/ne/), 'abcdefghn'.search(/ne/), 'abcdefghne'.search(/ne/), 'x'.search(/xy/), ''.search(/a/), ''.search(/(?:)/));
p([...'aaaa'.matchAll(/a/g)].length, 'ab'.repeat(20).replace(/ba/g, '').length, /abc/i.test('xABCx'), /ABC/.test('abc'), /a.c/.test('a\u00E9c'));
"""


def test_literal_and_prefilter_search_paths(run):
    """CATCHES: matchers whose fast paths (pure-literal search over ASCII subjects, first-character prefilters, ^-anchored scans, sticky literal checks, non-ASCII fallbacks) report different positions than a plain scan, e.g. missing matches near 8-byte chunk boundaries or case-folded first characters."""
    _ok(run, PROG_SEARCH_PATHS, "search_paths")

PROG_TOKENIZER = r"""
const src = 'let x = 42 + y1 * (3.5e-2 - "a\\"b") // done\nconst s = `t` ; z >>= 0x1F; /* c */ w => w ** 2';
const tok = /\s+|\/\/[^\n]*|\/\*[\s\S]*?\*\/|(?<num>0x[0-9a-f]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)|(?<id>[A-Za-z_$][\w$]*)|(?<str>"(?:[^"\\]|\\.)*"|`[^`]*`)|(?<op>>>=|=>|\*\*|[-+*\/=();])/iy;
const out = [];
let m;
while (tok.lastIndex < src.length && (m = tok.exec(src))) {
  const g = m.groups;
  const kind = Object.keys(g).find(k => g[k] !== undefined);
  if (kind) out.push(kind + ':' + m[0]);
}
p(out.length, tok.lastIndex, src.length);
p(out.join(' '));
const counts = {};
for (const w of 'the quick brown fox jumps over the lazy dog the end'.split(/\W+/)) counts[w] = (counts[w] || 0) + 1;
p(JSON.stringify(Object.entries(counts).filter(([, n]) => n > 1)));
const csv = 'a,\x22b,c\x22,d\n\x22e \x22\x22q\x22\x22\x22,f,\n';
const rows = csv.trim().split(/\r?\n/).map(line => [...line.matchAll(/(?:^|,)(?:"((?:[^"]|"")*)"|([^,]*))/g)].map(m => m[1] !== undefined ? m[1].replace(/""/g, '"') : m[2]));
p(JSON.stringify(rows));
const tpl = 'Hello {name}, you have {count} new {count, plural}!';
p(tpl.replace(/\{(\w+)(?:,\s*(\w+))?\}/g, (_, k, mod) => mod ? `<${k}:${mod}>` : ({ name: 'Ada', count: 3 })[k]));
let acc = 0;
for (let i = 0; i < 2000; i++) { if (/^(?:[13579]+|2\d)$/.test(String(i))) acc += i; }
p(acc);
const camel = ['foo_bar_baz', 'XMLHttpRequest', 'getHTTPResponseCode', 'already-kebab'].map(s => s.replace(/_(\w)/g, (_, c) => c.toUpperCase()).replace(/([a-z\d])([A-Z])|([A-Z]+)([A-Z][a-z])/g, '$1$3-$2$4').toLowerCase());
p(camel.join(' '));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_regex_driven_programs(run, tier):
    """CATCHES: tiers that disagree when regexps are driven from JS loops: a sticky-regexp tokenizer with named groups, word counting via split, a matchAll CSV parser, callback templating and case conversion via replace."""
    _ok(run, PROG_TOKENIZER, "programs", tier)


PROG_QUIRKS = r"""
p(E(() => String(new RegExp('^*'))), E(() => String(new RegExp('(?:ab){1001}'))), E(() => String(new RegExp('[a-[b]]', 'v'))), E(() => String(new RegExp('[\\q{a}-z]', 'v'))));
p(E(() => String(new RegExp('\\p{Script=greek}', 'u'))), E(() => String(new RegExp('\\p{sc=GREEK}', 'u'))));
const t = (src, flags, s) => new RegExp(src, flags).test(s) ? 1 : 0;
p(t('[\\u03C3]', 'i', '\u03C2'), t('[\\u00B5]', 'i', '\u03BC'), t('[\\u01C5]', 'i', '\u01C4'), t('[\\u0345]', 'i', '\u03B9'), t('[\\u03A3]', 'i', '\u03C2'), t('\\u03C3', 'i', '\u03C2'));
p(RegExp.escape('\x00\x1f\x7f'), RegExp.escape('\u0085'));
let globalReads = 0; const RE = RegExp;
Object.defineProperty(globalThis, 'RegExp', { get() { globalReads++; return RE; }, configurable: true });
'k=v'.split(/=/); const afterSplit = globalReads; [...'k=v'.matchAll(/=/g)]; const afterMatchAll = globalReads; 'k=v'.replace(/=/, ''); /=/.exec('=');
Object.defineProperty(globalThis, 'RegExp', { value: RE, writable: true, configurable: true, enumerable: false });
p(afterSplit, afterMatchAll, globalReads);
p(/^(a?){20}a{20}$/.test('a'.repeat(20)), /^(a?){8}a{8}$/.test('a'.repeat(8)), /^(?:a|b)*?c$/.test('ab'.repeat(30)));
"""


def test_reference_specific_behaviour(run):
    """CATCHES: rewrites that differ from the reference in its deliberate limits and deviations: Annex B '^*' accepted, a 1000 cap on unrolled group repetition, v-mode ranges whose bound is a nested class or \\q{x}, loosely matched Script values, legacy /i classes that only compare simple case partners, RegExp.escape hex-escaping control characters, the per-attempt backtracking step budget that makes an exponential-but-matching pattern report no match, and split/matchAll reading globalThis.RegExp when resolving the species constructor."""
    _ok(run, PROG_QUIRKS, "quirks")
