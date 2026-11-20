"""String built-ins: padding/repeat/trim/at, replace/replaceAll substitution patterns, split and
search methods, Unicode normalization, well-formedness and surrogates, case mapping (incl.
locale-sensitive), String.raw/fromCodePoint/codePointAt, coercion and boxing, plus the global URI
encode/decode and escape/unescape functions."""

import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)

PRELUDE = r'''
const fmt = (v, d = 0) => {
  if (typeof v === 'string') return JSON.stringify(v);
  if (typeof v === 'number') return Object.is(v, -0) ? '-0' : String(v);
  if (typeof v === 'bigint') return v + 'n';
  if (typeof v === 'symbol') return v.toString();
  if (typeof v === 'function') return '[Function ' + (v.name || '<anon>') + ']';
  if (v === null || typeof v !== 'object') return String(v);
  if (v instanceof Error) return '[' + v.name + ': ' + v.message + ']';
  if (d > 4) return '...';
  if (Array.isArray(v)) {
    const out = [];
    for (let i = 0; i < v.length; i++) out.push(i in v ? fmt(v[i], d + 1) : '<hole>');
    return '[' + out.join(', ') + ']';
  }
  return '{' + Reflect.ownKeys(v).map(k => {
    const desc = Object.getOwnPropertyDescriptor(v, k);
    return String(k) + ': ' + ('value' in desc ? fmt(desc.value, d + 1) : '<accessor>');
  }).join(', ') + '}';
};
const show = (label, f) => {
  try { console.log(label + ' => ' + fmt(f())); }
  catch (e) { console.log(label + ' !! ' + (e !== null && typeof e === 'object' ? e.name + ': ' + e.message : 'thrown ' + fmt(e))); }
};
const hex = s => [...s].map(c => c.codePointAt(0).toString(16)).join(' ');
const units = s => s.split('').map(c => c.charCodeAt(0).toString(16)).join(' ');
'''


def check(run, workdir, name, body, **kw):
    """Run PRELUDE + body as a script and compare with the golden `name`."""
    return check_script(run, workdir, G, name, PRELUDE + body, **kw)


def test_string_pad_repeat_at_trim(run, workdir):
    """CATCHES: padStart/padEnd truncating the filler wrongly or padding with an empty filler,
    repeat accepting negative/infinite counts (exact RangeError) or rejecting count*0 on huge
    counts of '', at() index coercion, and trim using the wrong whitespace set (BOM, NBSP, U+3000
    and line terminators are trimmed; ZWSP and U+180E are not; the reference also trims U+0085)."""
    check(run, workdir, "string_pad_repeat_at_trim", r'''
show('padStart', () => ['5'.padStart(3, '0'), 'abc'.padStart(8, '12'), 'abc'.padStart(2), 'x'.padStart(3, undefined), 'x'.padStart(4, null), 'x'.padStart(-1, 'y'), 'x'.padStart(3.9, 'ab')]);
show('padEnd', () => ['x'.padEnd(4), 'x'.padEnd(5, ''), 'x'.padEnd(6, 'ab'), 'abc'.padEnd(6, '\u{1F600}').length, ''.padEnd(3, 'z')]);
show('repeat', () => ['ab'.repeat(3), 'x'.repeat(0), ''.repeat(100), 'a'.repeat(2.9), 'a'.repeat('2'), 'a'.repeat(NaN), ''.repeat(2 ** 40)]);
show('repeat negative', () => 'a'.repeat(-1));
show('repeat infinity', () => 'a'.repeat(Infinity));
show('repeat empty infinity', () => ''.repeat(Infinity));
show('at', () => ['abc'.at(-1), 'abc'.at(3), 'abc'.at(-4), 'abc'.at(Infinity), 'abc'.at('-1'), ''.at(0), 'abc'.at(1.9), 'abc'.at(), '\u{1F600}'.at(0).length]);
show('charAt', () => ['abc'.charAt(1), 'abc'.charAt(5), 'abc'.charCodeAt(5), 'abc'.charAt(-1), 'abc'[-1], 'abc'.charAt(NaN), 'abc'.charCodeAt('1')]);
const trimmed = ['\u0009', '\u000A', '\u000B', '\u000C', '\u000D', ' ', '\u00A0', '\u1680', '\u2000', '\u2005', '\u200A', '\u2028', '\u2029', '\u202F', '\u205F', '\u3000', '\uFEFF'];
const kept = ['\u180E', '\u200B', '\u200C', '\u2060', '\u0085', '\u001C'];
show('trimmed set', () => trimmed.map(c => (c + 'x' + c).trim().length).join(''));
show('other candidates', () => kept.map(c => (c + 'x' + c).trim().length).join(''));
show('trimStart/trimEnd', () => { const ws = ' \t\n\u3000'; return [(ws + 'x' + ws).trimStart().length, (ws + 'x' + ws).trimEnd().length, String.prototype.trimLeft === String.prototype.trimStart, String.prototype.trimRight.name, String.prototype.trimLeft.name]; });
show('trim null this', () => String.prototype.trim.call(null));
show('trim coerces this', () => [String.prototype.trim.call(42), String.prototype.trim.call({toString() { return '  o  '; }})]);
''')


def test_string_replace_substitutions(run, workdir):
    """CATCHES: wrong $-pattern expansion in replace/replaceAll with string patterns ($&, $`, $',
    $$, lone $, $0, $1, $<name> stay literal without captures), replaceAll on empty patterns,
    replacer-function arguments, search coercion, and the exact errors for non-global RegExps
    and replaceAll searchValue checks (Symbol.match before toString)."""
    check(run, workdir, "string_replace_substitutions", r'''
show('replace first only', () => ['aaa'.replace('a', 'b'), 'abc'.replace('', '^'), 'abc'.replace('zz', 'y')]);
show('$ patterns', () => ['abc'.replace('b', '$&$&'), 'abc'.replace('b', '$`'), 'abc'.replace('b', "$'"), 'abc'.replace('b', '$$'), 'abc'.replace('b', '$'), 'abc'.replace('b', '$0'), 'abc'.replace('b', '$1'), 'abc'.replace('b', '$<x>'), 'abc'.replace('b', '$$&'), 'abc'.replace('b', '$`$`'), 'abc'.replace('c', '$9$')]);
show('regex captures', () => ['2020-01'.replace(/(?<y>\d+)-(?<m>\d+)/, '$<m>/$<y> $2 $3 $<none>| $01 $10 $00'), 'abc'.replace(/(b)/, '[$1$2]')]);
show('replacer fn args', () => { const r = []; 'x-y-'.replace('-', (...a) => { r.push(a); return '+'; }); return r; });
show('replacer fn result coerced', () => ['abc'.replace('b', () => 42), 'abc'.replace('b', () => null), 'abc'.replace('b', () => ({toString() { return 'T'; }}))]);
show('replacer not $-expanded', () => 'abc'.replace('b', () => '$&$&'));
show('search coercion', () => ['a1b'.replace(1, 'X'), 'anullb'.replace(null, '_'), 'undefined'.replace(undefined, 'U'), 'a,b'.replace([','], ';')]);
show('replaceAll', () => ['a.b.c'.replaceAll('.', '-'), 'aaa'.replaceAll('aa', 'b'), 'abc'.replaceAll('', '_'), 'x-y'.replaceAll('-', '$&$&'), 'abc'.replaceAll('b', "[$`|$']"), 'abc'.replaceAll('b', '$$'), 'abc'.replaceAll('b', '$1$<n>$')]);
show('replaceAll fn offsets', () => ['abab'.replaceAll('b', (m, off, s) => `${m}${off}${s.length}`), 'aXbXc'.replaceAll('X', (m, off) => off)]);
show('replaceAll empty', () => [''.replaceAll('', 'x'), ''.replace('', 'y'), 'ab'.replaceAll('', '$&|')]);
show('replaceAll global regex', () => 'aXbx'.replaceAll(/x/gi, '_'));
show('replaceAll non-global regex', () => 'aa'.replaceAll(/a/, 'b'));
show('replaceAll check order', () => { const log = []; 'aa'.replaceAll({get [Symbol.match]() { log.push('get match'); return undefined; }, get [Symbol.replace]() { log.push('get replace'); return undefined; }, toString() { log.push('toString'); return 'a'; }}, 'b'); return log; });
show('custom Symbol.replace', () => 'abc'.replace({[Symbol.replace](s, r) { return 'custom:' + s + ':' + r; }}, 'R'));
show('replaceAll null this', () => String.prototype.replaceAll.call(null, 'a', 'b'));
show('unicode', () => ['\u{1F600}a\u{1F600}'.replaceAll('\u{1F600}', 'x'), 'a\u{1F600}'.replace('\uD83D', 'H').length, '\u00E9\u00E9\u00E9'.replace('\u00E9', 'e')]);
''')


def test_string_split_and_search(run, workdir):
    """CATCHES: split mishandling limits (0, negative -> ToUint32, > 2**32), empty separators
    (code units, not code points), undefined separators, coercion order (this, limit, separator);
    indexOf/lastIndexOf/includes/startsWith/endsWith position clamping and the TypeError for
    RegExp arguments (unless Symbol.match is false); search/match with string arguments."""
    check(run, workdir, "string_split_and_search", r'''
show('split', () => ['a,b,,c'.split(','), 'abc'.split(''), 'abc'.split('', 2), 'a,b,c'.split(',', 0), 'a,b'.split(), ''.split(','), ''.split(''), 'abab'.split('ab'), 'a,b,'.split(',')]);
show('split limits', () => ['a,b,c'.split(',', -1), 'a,b,c'.split(',', 2 ** 32 + 1), 'a,b,c'.split(',', '2'), 'a,b,c'.split(',', 2.9), 'a,b,c'.split(',', null), 'a,b,c'.split(',', undefined)]);
show('split undefined sep limit 0', () => 'abc'.split(undefined, 0));
show('split surrogates', () => '\u{1F600}x'.split('').map(s => s.charCodeAt(0).toString(16)));
show('split multi-char sep', () => ['a--b---c'.split('--'), 'aaaa'.split('aa')]);
show('split object sep', () => 'a-b'.split({toString() { return '-'; }}));
show('split coercion order', () => { const log = []; String.prototype.split.call({toString() { log.push('this'); return 'a,b'; }}, {toString() { log.push('sep'); return ','; }}, {valueOf() { log.push('limit'); return 5; }}); return log; });
show('indexOf', () => ['abcabc'.indexOf('c', -5), 'abc'.indexOf('', 10), 'abc'.indexOf('', 2), 'abc'.indexOf(), 'undefined'.indexOf(), 'abc'.indexOf('c', Infinity)]);
show('lastIndexOf', () => ['abcabc'.lastIndexOf('a', 2), 'abc'.lastIndexOf('', 1), 'abc'.lastIndexOf('c', -Infinity), 'abcabc'.lastIndexOf('c', NaN), 'abc'.lastIndexOf('', 99), 'aaa'.lastIndexOf('aa')]);
show('includes/startsWith/endsWith', () => ['abc'.startsWith('b', 1), 'abc'.endsWith('b', 2), 'abc'.includes('c', 3), 'abc'.startsWith(''), 'abc'.endsWith('abc', 99), 'abc'.endsWith('a', -1), 'abc'.startsWith('abc', -5), 'abc'.includes('')]);
show('startsWith regex', () => 'abc'.startsWith(/a/));
show('endsWith regex', () => 'abc'.endsWith(/a/));
show('includes regex', () => 'abc'.includes(/a/));
show('regex with Symbol.match=false', () => { const r = /a/; r[Symbol.match] = false; return ['/a/'.includes(r), '/a/'.startsWith(r), '/a/'.endsWith(r)]; });
show('object with Symbol.match', () => 'x'.includes({[Symbol.match]: true}));
show('search string', () => ['a.b'.search('.'), 'abc'.search(), 'abc'.search(undefined), 'a(b'.search('\\('), 'abc'.search('z')]);
show('match string', () => ['abcb'.match('b').index, 'abc'.match(null), 'a.c'.match('.')[0], 'abc'.match().length]);
show('matchAll string', () => [...'a.b.c'.matchAll('.')].map(m => m.index));
show('localeCompare', () => [['a', 'b'], ['b', 'a'], ['a', 'a'], ['a', 'B'], ['a', 'A'], ['a', '\u00E1'], ['r\u00E9sum\u00E9', 'resume'], ['10', '9'], ['', 'a'], ['\u00DF', 'ss'], ['\u00C5', 'A\u030A'], ['Z', 'a']].map(([x, y]) => x.localeCompare(y)));
show('localeCompare options', () => ['a'.localeCompare('A', undefined, {sensitivity: 'base'}), '2'.localeCompare('10', undefined, {numeric: true}), '\u00E4'.localeCompare('z', 'sv'), '\u00E4'.localeCompare('z', 'de')]);
show('localeCompare coercion', () => [String.prototype.localeCompare.call(1, '1'), 'null'.localeCompare(null), 'undefined'.localeCompare()]);
''')


def test_string_normalize_and_well_formed(run, workdir):
    """CATCHES: incomplete Unicode normalization (canonical ordering of combining marks, Hangul
    composition/decomposition, compatibility mappings for NFKC/NFKD, singleton exclusions), an
    invalid form name not raising RangeError, isWellFormed/toWellFormed mishandling lone or
    reversed surrogates, and < / > not comparing by UTF-16 code units (the reference's default
    Array#sort, by contrast, orders by code point, which is pinned here too)."""
    check(run, workdir, "string_normalize_and_well_formed", r'''
const forms = ['NFC', 'NFD', 'NFKC', 'NFKD'];
const samples = ['\u1E9B\u0323', '\u00C5', 'A\u030A', '\u212B', '\u1E0B\u0323', 'q\u0307\u0323', '\uAC01', '\u1100\u1161\u11A8', '\u2460', '\u338F', '\uFF76\uFF9E', '\uFB01', '\u00BD', '\u2126', '\u0344', 'e\u0301\u0327'];
for (const s of samples) console.log(hex(s).padEnd(16) + ' -> ' + forms.map(f => f + '[' + hex(s.normalize(f)) + ']').join(' '));
show('default form is NFC', () => ['e\u0301'.normalize().length, 'e\u0301'.normalize(undefined).length]);
show('ascii unchanged', () => 'plain ASCII 123'.normalize('NFKD'));
show('lone surrogate kept', () => units('\uD800\u0301'.normalize('NFD')));
show('bad form', () => 'a'.normalize('nfc'));
show('null form', () => 'a'.normalize(null));
show('empty form', () => 'a'.normalize(''));
show('normalize null this', () => String.prototype.normalize.call(undefined));
show('isWellFormed', () => ['ab'.isWellFormed(), '\uD800'.isWellFormed(), '\uDC00a'.isWellFormed(), '\u{1F600}'.isWellFormed(), '\uDE00\uD83D'.isWellFormed(), ''.isWellFormed()]);
show('toWellFormed', () => [units('a\uD800b\uDFFF'.toWellFormed()), units('\uDE00\uD83D'.toWellFormed()), units('\u{1F600}'.toWellFormed())]);
show('surrogate joining', () => { const s = '\uD83D' + '\uDE00'; return [s === '\u{1F600}', s.length, [...s].length, s.codePointAt(0).toString(16), ('\uD83D' + 'x' + '\uDE00').length]; });
show('slicing pairs', () => ['a\u{1F600}b'.slice(1, 2).charCodeAt(0).toString(16), 'a\u{1F600}b'.substring(2).length, units('a\u{1F600}b'.slice(-2)), JSON.stringify('\u{1F600}'.slice(0, 1))]);
show('comparison by code units', () => ['\u{1F600}' > '\uFFFF', '\uFF61' < '\u{10000}', ['\u{1F600}', '\uFF61', 'z'].sort().map(hex)]);
''')


def test_string_case_mapping(run, workdir):
    """CATCHES: case mapping done per code unit or via ASCII only: special casing (sharp s, final
    sigma context, ligatures, dotted capital I, titlecase digraphs, Deseret/Cherokee astral and
    BMP letters) and locale-sensitive rules for tr/az/lt in toLocale{Upper,Lower}Case, including
    the RangeError for invalid language tags."""
    check(run, workdir, "string_case_mapping", r'''
show('upper specials', () => ['\u00DF'.toUpperCase(), '\uFB00'.toUpperCase(), '\uFB03'.toUpperCase(), '\u0149'.toUpperCase(), '\u01F0'.toUpperCase().length, '\u0390'.toUpperCase().length, '\u01C8'.toUpperCase(), 'hello WORLD'.toUpperCase()]);
show('lower specials', () => ['\u0130'.toLowerCase().length, '\u01C5'.toLowerCase(), '\u01C8'.toLowerCase(), 'MiXeD'.toLowerCase(), '\u0130stanbul'.toLowerCase().length]);
show('final sigma', () => ['\u0391\u03A3'.toLowerCase(), '\u0391\u03A3 \u0391'.toLowerCase(), '\u03A3'.toLowerCase(), '\u0391\u03A3.'.toLowerCase(), 'x\u03A3x'.toLowerCase(), '\u0391\u03A3\u0301'.toLowerCase().split('').map(c => c.charCodeAt(0).toString(16)).join(' ')]);
show('astral and cherokee', () => [hex('\u{10428}'.toUpperCase()), hex('\u{10400}'.toLowerCase()), hex('\uAB70'.toUpperCase()), hex('\u13A0'.toLowerCase())]);
show('turkish', () => ['i'.toLocaleUpperCase('tr'), 'I'.toLocaleLowerCase('tr'), '\u0130'.toLocaleLowerCase('tr'), 'I'.toLocaleLowerCase('az'), 'I\u0307'.toLocaleLowerCase('tr')]);
show('non-turkish', () => ['I'.toLocaleLowerCase('en-US'), 'i'.toLocaleUpperCase('en'), '\u0131'.toLocaleUpperCase(), '\u0130'.toLocaleLowerCase('en').length]);
show('lithuanian', () => [hex('\u00CC'.toLocaleLowerCase('lt')), hex('I\u0300'.toLocaleLowerCase('lt')), hex('i\u0307'.toLocaleUpperCase('lt')), hex('\u0128'.toLocaleLowerCase('lt'))]);
show('lithuanian soft-dotted', () => [hex('J\u0301'.toLocaleLowerCase('lt')), hex('\u012E\u0301'.toLocaleLowerCase('lt')), hex('j\u0307\u0301'.toLocaleUpperCase('lt')), hex('\u012F\u0307'.toLocaleUpperCase('lt')), hex('i\u0323\u0307'.toLocaleUpperCase('lt')), hex('x\u0307'.toLocaleUpperCase('lt')), hex('\u0268\u0307'.toLocaleUpperCase('lt')), hex('\u{1D422}\u0307'.toLocaleUpperCase('lt'))]);
show('locale list', () => ['i'.toLocaleUpperCase(['tr', 'en']), 'i'.toLocaleUpperCase(['en', 'tr']), 'i'.toLocaleUpperCase([])]);
show('bad tag', () => 'a'.toLocaleUpperCase('not a tag!'));
show('bad tag type', () => 'a'.toLocaleLowerCase(5));
show('null this', () => String.prototype.toUpperCase.call(null));
show('coerced this', () => [String.prototype.toUpperCase.call(true), String.prototype.toLowerCase.call(['A', 'B'])]);
show('length changes', () => ['\u00DF\u00DF'.toUpperCase().length, '\uFB03'.toUpperCase().length, '\u0587'.toUpperCase()]);
''')


def test_string_code_points_and_raw(run, workdir):
    """CATCHES: String.fromCodePoint accepting fractional/negative/NaN/out-of-range values (exact
    RangeError), fromCharCode not truncating with ToUint16, codePointAt pairing rules, the string
    iterator yielding code units instead of code points, and String.raw substitution handling
    (the reference rejects a primitive-string `raw` with 'raw is not an object')."""
    check(run, workdir, "string_code_points_and_raw", r'''
show('fromCodePoint', () => [String.fromCodePoint(65, 0x1F600, 0x10FFFF).length, String.fromCodePoint(), String.fromCodePoint('66', 0.0, -0).length, units(String.fromCodePoint(0xD800, 0xDC00))]);
for (const bad of [1.5, -1, 0x110000, NaN, 'x', Infinity, undefined]) show('fromCodePoint ' + String(bad), () => String.fromCodePoint(bad));
show('fromCharCode', () => [units(String.fromCharCode(0x10041, 66.9, -1, 0xD83D, 0xDE00)), String.fromCharCode(), String.fromCharCode('72', '105')]);
show('codePointAt', () => ['\u{1F600}'.codePointAt(0), '\u{1F600}'.codePointAt(1), 'a'.codePointAt(1), '\uD800x'.codePointAt(0), 'a'.codePointAt(-1), 'ab'.codePointAt('1'), 'ab'.codePointAt(NaN), '\uDC00\uD800'.codePointAt(0)]);
show('iterator', () => { const it = 'a\u{1F600}\uD800'[Symbol.iterator](); return [it.next(), it.next().value.length, units(it.next().value), it.next(), Object.prototype.toString.call(it)]; });
show('iterator bad receiver', () => ''[Symbol.iterator]().next.call({}));
show('iterator null this', () => String.prototype[Symbol.iterator].call(null));
show('raw template', () => [String.raw`a\nb${1}\u`, String.raw`\${x}${'y'}`, String.raw``]);
show('raw object', () => [String.raw({raw: ['x', 'y', 'z']}, 1, 2, 3, 4), String.raw({raw: {length: 2, 0: 'p', 1: 'q'}}, 'M'), String.raw({raw: []}), String.raw({raw: {length: -1}}), String.raw({raw: ['only']}, 'ignored')]);
show('raw string raw', () => String.raw({raw: 'abc'}, '-', '+'));
show('raw missing raw', () => String.raw({}));
show('raw no args', () => String.raw());
show('raw coerces subs', () => String.raw({raw: ['a', 'b', 'c']}, {toString() { return 'S'; }}, null));
show('raw symbol sub', () => String.raw({raw: ['a', 'b']}, Symbol()));
''')


@pytest.mark.parametrize("cli", [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp")])
def test_string_hot_loop_methods(run, workdir, cli):
    """CATCHES: fast paths for substring/slice/charAt/charCodeAt/codePointAt/indexOf in hot loops
    (JIT-compiled immediately because the function has a loop) diverging from the reference
    semantics on non-ASCII strings, lone surrogates, swapped/negative/NaN bounds and arguments
    with valueOf side effects; the default tier must equal the interpreter tier."""
    check(run, workdir, "string_hot_loop_methods", r'''
function work(strs, args) {
  const out = [];
  for (let k = 0; k < 3; k++) {
    for (const s of strs) {
      for (const [a, b] of args) {
        out.push([s.substring(a, b), s.slice(a, b), s.substr(a, b), s.charAt(a), s.charCodeAt(a), s.codePointAt(a), s.at(a), s.indexOf('b', a)].map(fmt).join(' '));
      }
    }
  }
  return out;
}
const strs = ['abcdef', 'h\u00E9llo b', 'a\u{1F600}b\u{1F601}', '\uD800ab\uDC00', ''];
const log = [];
const tracked = n => ({valueOf() { log.push('valueOf ' + n); return n; }});
const args = [[1, 3], [3, 1], [-2, 2], [NaN, 4], [2, undefined], [1.7, 99], [Infinity, -Infinity], [tracked(1), tracked(2)]];
const res = work(strs, args);
console.log(res.slice(0, res.length / 3).join('\n'));
console.log('consistent across iterations:', res.slice(0, res.length / 3).join() === res.slice(res.length / 3 * 2).join());
console.log('valueOf calls:', log.length, log.slice(0, 4).join(', '));
function lens() { let total = 0; for (let i = 0; i < 2000; i++) total += ('x'.repeat(i % 7) + '\u{1F600}').substring(i % 5).length; return total; }
console.log('loop total', lens());
''', cli=cli)


def test_string_coercion_boxing_and_html(run, workdir):
    """CATCHES: wrong ToString of numbers/arrays/objects (toString vs valueOf preference for String()
    vs + vs templates), String objects lacking indexed non-writable own properties, concat
    coercion, Annex B HTML methods not escaping quotes in attributes, and the exact TypeError
    for String.prototype methods called on null/undefined."""
    check(run, workdir, "string_coercion_boxing_and_html", r'''
const both = {toString: () => 'ts', valueOf: () => 'vo'};
show('String()', () => [String(Symbol('d')), String(null), String(undefined), String([1, [2, [3]]]), String(-0), String(1e21), String(both), `${both}`, '' + both, String(123n), String({})]);
show('new String', () => { const s = new String('ab'); return [typeof s, s.length, Object.keys(s), s[1], Object.getOwnPropertyDescriptor(s, 0), 1 in s, 2 in s, Object.getOwnPropertyNames(s)]; });
show('String object writes', () => { 'use strict'; const s = new String('ab'); s.extra = 1; try { s[0] = 'z'; } catch (e) { return [s.extra, e.name + ': ' + e.message]; } });
show('String object length', () => { const s = new String('abc'); s.length = 1; return [s.length, delete s.length, delete s[0], delete s[9]]; });
show('new String symbol', () => new String(Symbol('s')));
show('String as function vs ctor', () => [typeof String(1), typeof new String(1), new String(1) == '1', new String('a') === 'a']);
show('concat', () => ['a'.concat(1, null, [2, 3], {}, undefined), String.prototype.concat.call(1, 2), ''.concat()]);
show('html', () => ['a'.anchor('"x"'), 'b'.bold(), 'c'.link('u"v'), 'd'.fontcolor('red'), 'e'.sub(), 'f'.sup(), 'g'.big(), 'h'.blink(), 'i'.fixed(), 'j'.italics(), 'k'.small(), 'l'.strike(), 'm'.fontsize(7)]);
show('html null this', () => String.prototype.bold.call(null));
show('methods on null', () => ['at', 'trim', 'split', 'padEnd', 'normalize', 'includes', 'replace', 'match', 'search', 'matchAll', 'localeCompare'].map(m => { try { String.prototype[m].call(null); return 'ok'; } catch (e) { return e.name + ': ' + e.message; } }));
show('valueOf/toString this checks', () => [String.prototype.valueOf.call(new String('x')), String.prototype.toString.call('y')]);
show('valueOf bad this', () => String.prototype.valueOf.call({}));
show('@@search not callable', () => 'abc'.search({[Symbol.search]: 1}));
show('@@match not callable', () => 'abc'.match({[Symbol.match]: 1}));
show('@@split not callable', () => 'abc'.split({[Symbol.split]: 1}));
show('@@replace not callable', () => 'abc'.replace({[Symbol.replace]: 1}, ''));
show('toString bad this', () => String.prototype.toString.call(1));
show('lengths', () => [String.length, String.prototype.length, String.prototype.padStart.length, String.prototype.replace.length, String.fromCharCode.length, String.raw.length, String.prototype.at.length]);
show('string keys', () => { const s = 'hi'; return [s.length, s[0], s['1'], s[2], 'length' in Object(s), Object.keys(s)]; });
show('primitive property write', () => { const s = 'abc'; s.x = 1; s[0] = 'z'; return [s.x, s]; });
show('primitive property write strict', () => { 'use strict'; const s = 'abc'; s.x = 1; });
''')


def test_uri_and_escape_functions(run, workdir):
    """CATCHES: encodeURI/encodeURIComponent escaping the wrong reserved set, not encoding UTF-8
    correctly or not throwing URIError on lone surrogates; decodeURI keeping reserved escapes
    (%2F, %23) encoded while decodeURIComponent decodes them; malformed/overlong/surrogate UTF-8
    sequences raising URIError('URI malformed'); Annex B escape/unescape with %uXXXX."""
    check(run, workdir, "uri_and_escape_functions", r'''
show('encodeURI', () => [encodeURI('http://x.com/a b?q=1&r=\u00E4#h'), encodeURI("-_.!~*'();/?:@&=+$,#"), encodeURI('\0\x7f[]{}|\\^`"<>%')]);
show('encodeURIComponent', () => [encodeURIComponent('a b&c=d/\u00E9?#'), encodeURIComponent("-_.!~*'();/?:@&=+$,#"), encodeURIComponent('\u{1F600}\u20AC\u07FF\u0800'), encodeURIComponent(undefined), encodeURIComponent(12.5)]);
show('encodeURI lone high', () => encodeURI('\uD800'));
show('encodeURIComponent lone low', () => encodeURIComponent('\uDC00x'));
show('encode reversed pair', () => encodeURIComponent('\uDE00\uD83D'));
show('decodeURI', () => [decodeURI('%41%20%3B%2F%23%3f'), decodeURI('%e4%b8%ad'), decodeURI('%25'), decodeURI('100%25 sure')]);
show('decodeURIComponent', () => [decodeURIComponent('%41%20%3B%2F%23'), decodeURIComponent('%F0%9F%98%80'), decodeURIComponent('a+b'), decodeURIComponent('%c3%a9')]);
for (const bad of ['%', '%zz', '%4', '%C0%80', '%ED%A0%80', '%F4%90%80%80', '%80', '%E0%A4%A', '%E4%B8', '%F8%80%80%80%80', '%C3%28']) show('decode ' + bad, () => decodeURIComponent(bad));
show('decodeURI malformed', () => decodeURI('%E0%A4%A'));
show('round trip', () => { const s = 'k\u00F8\u00F8l \u{1F600} &=?/'; return decodeURIComponent(encodeURIComponent(s)) === s && decodeURI(encodeURI(s)) === s; });
show('escape', () => [escape('a b+c/\u00E4\u20AC\u{1F600}@*_-.'), escape(''), escape('\x00\xff\u0100'), escape(42)]);
show('unescape', () => [unescape('%u20AC%41%zz%u12'), unescape('%E4'), unescape('%%41'), unescape('%u00e9%U00e9'), unescape('%')]);
show('lengths', () => [encodeURI.length, decodeURIComponent.length, escape.length, unescape.length]);
''')


def test_string_plane16_private_use_chars(run, workdir):
    """CATCHES: wrong UTF-16 semantics for supplementary characters at the top of plane 16
    (U+10F800..U+10FFFF), which the reference stores specially: length/codePointAt/slicing,
    re-joining surrogate halves, comparisons, URI encoding, well-formedness and searching must all
    behave as ordinary astral characters. Pinned reference quirks: spreading such a character
    yields two elements, the default Array#sort compares the internal representation (U+FFFF sorts
    before them) while the < operator compares code units, and JSON.parse of the escaped pair
    '\\udbff\\udfff' does not produce the same string as String.fromCodePoint(0x10FFFF)."""
    check(run, workdir, "string_plane16_private_use_chars", r'''
const top = String.fromCodePoint(0x10FFFF), base = String.fromCodePoint(0x10F800), below = String.fromCodePoint(0x10F7FF);
show('lengths and units', () => [top.length, base.length, below.length, units(top), units(base), units(below)]);
show('codePointAt', () => [top.codePointAt(0).toString(16), base.codePointAt(0).toString(16), top.codePointAt(1).toString(16)]);
show('spread', () => [[...top].length, [...base].length, [...below].length, [...('a' + top + 'b')].length]);
show('joined halves', () => { const s = '\uDBFF' + '\uDFFF'; return [s === top, s.length, s.codePointAt(0).toString(16), String.fromCharCode(0xDBFF, 0xDFFF) === top, `${'\uDBFF'}${'\uDFFF'}` === top]; });
show('relational', () => [top > below, '\uDBFF' < top, '\uFFFF' < top, top < '\uFFFF', '\uD800' < below]);
show('default sort', () => [top, '\uFFFF', below, '\uD800'].sort().map(s => s.codePointAt(0).toString(16)));
show('comparator sort', () => [top, '\uFFFF', below, '\uD800'].sort((x, y) => x < y ? -1 : x > y ? 1 : 0).map(s => s.codePointAt(0).toString(16)));
show('JSON', () => [JSON.stringify(top).length, JSON.stringify(top) === '"' + top + '"', JSON.parse('"\\udbff\\udfff"') === top]);
show('encodeURIComponent', () => [encodeURIComponent(top), encodeURIComponent(base), encodeURIComponent(below), decodeURIComponent('%F4%8F%BF%BF') === top]);
show('well-formed', () => [top.isWellFormed(), base.isWellFormed(), units(top.toWellFormed()), ('\uDBFF' + 'x').isWellFormed()]);
show('slice halves', () => [units(top.slice(0, 1)), units(top.slice(1)), top.slice(0, 1) + top.slice(1) === top]);
show('search', () => [('x' + top).indexOf(top), ('x' + top).indexOf('\uDFFF'), ('x' + top).lastIndexOf('\uDBFF'), top.includes('\uDFFF'), top.startsWith('\uDBFF')]);
show('split/pad/repeat', () => [top.split('').map(units), ('a' + top).split('\uDFFF').map(units), units('a'.padEnd(3, top)), top.repeat(2).length]);
show('normalize/case', () => [top.normalize() === top, base.normalize('NFD') === base, top.toUpperCase() === top, base.toLowerCase() === base]);
show('property keys', () => { const o = {}; o['\uD800'] = 1; o[top] = 2; return [Object.keys(o).map(units), o['\u{10FFFF}'], new Map([[top, 'm']]).get('\uDBFF\uDFFF')]; });
show('regexp', () => [/^.$/u.test(top), /^..$/.test(top), /\u{10FFFF}/u.test('a' + top)]);
''')
