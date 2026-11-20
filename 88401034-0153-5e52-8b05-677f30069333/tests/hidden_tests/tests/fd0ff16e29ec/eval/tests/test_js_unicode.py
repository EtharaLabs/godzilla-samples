"""Unicode string processing: String.prototype.normalize (NFC/NFD/NFKC/NFKD incl. Hangul and canonical
reordering), full case mapping (special casing, final sigma, locale-sensitive Turkish/Lithuanian),
UTF-16 code-unit semantics of string methods on astral characters and lone surrogates, surrogate
pairs formed by concatenation, String.fromCodePoint, isWellFormed/toWellFormed, string iteration,
and surrogate handling in JSON, URI coding and TextEncoder/TextDecoder."""

import pytest

from conftest import golden

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

# p() joins values with " | " (strings raw, everything else JSON); hex() lists code points;
# units() lists UTF-16 code units, so lone surrogates are printed safely.
PRELUDE = r"""
const p = (...a) => console.log(a.map(x => typeof x === 'string' ? x : x === undefined ? 'undefined' : JSON.stringify(x)).join(' | '));
const hex = (s) => [...s].map(c => c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')).join(' ');
const units = (s) => Array.from({ length: s.length }, (_, i) => s.charCodeAt(i).toString(16)).join(' ');
const E = (f) => { try { const v = f(); return 'ok ' + (typeof v === 'string' ? v : JSON.stringify(v)); } catch (e) { return e.name + ': ' + e.message; } };
"""


def _ok(run, prog, name, tier=()):
    r = run([*tier, "-e", PRELUDE + prog])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


PROG_NORMALIZE = r"""
const samples = ['Å', 'Å', 'Å', 'ẛ̣', 'ȩ́', 'ȩ́', '가', '각', '가', '각',
  '한글', 'ﬁ', '①', '½', 'ḍ̇', 'q̣̇', '̈́', 'ཱི', 'Ω', 'ǘ', '㌀', 'Ａ',
  '\u{1D400}', '\u{1D15E}', 'क़', 'á́', 'À̖', 'ᄀ가', '각', '가ᇃ', '흔',
  '⾡D', '\u{2FA1D}', ' ', 'ΐ', 'abc', '', '́Å', 'ạ̀', 'Ą́̆', 'Ǆ', '⁵', 'ṩ',
  'ୋ', 'ো', 'ೋ', '゙か', 'が', 'ｶﾞ', 'אַּ', 'آ', '\u{11099}\u{110BA}'];
for (const s of samples) {
  p(hex(s) || '-', hex(s.normalize()) || '-', hex(s.normalize('NFD')) || '-', hex(s.normalize('NFKC')) || '-', hex(s.normalize('NFKD')) || '-');
}
const rnd = 'Cáfé 한국어 ẛ̣ ﬃ Ⅷ ㎡ ÅÅÅ';
for (const f of ['NFC', 'NFD', 'NFKC', 'NFKD']) {
  const n = rnd.normalize(f);
  p(f, n.length, n.normalize(f) === n, n.normalize('NFC') === rnd.normalize('NFC'), n.normalize('NFKC') === rnd.normalize('NFKC'));
}
"""


def test_normalize_forms(run):
    """CATCHES: normalize() with missing canonical/compatibility decompositions, no canonical reordering of combining marks by combining class, broken Hangul syllable (de)composition (LV, LVT, invalid T), composition exclusions/singletons (U+212B, U+2126, U+0958), or forms that are not idempotent."""
    _ok(run, PROG_NORMALIZE, "normalize")


PROG_NORMALIZE_ARGS = r"""
for (const f of ['nfc', 'NFC ', '', 'NFKX', null, 0]) p(JSON.stringify(f), E(() => 'a'.normalize(f)));
p('a'.normalize(undefined), 'Å'.normalize(undefined) === 'Å', 'Å'.normalize() === 'Å', String.prototype.normalize.length, String.prototype.normalize.name);
p(E(() => String.prototype.normalize.call(null)), E(() => String.prototype.normalize.call(undefined, 'NFC')), String.prototype.normalize.call(123), String.prototype.normalize.call(true, 'NFD'));
p(E(() => 'a'.normalize({ toString() { return 'NFKD'; } })), E(() => 'a'.normalize(Symbol())), units('\uD800́'.normalize('NFC')), units('\uDC00Å\uD800'.normalize('NFKC')));
p('Å' === 'Å', 'Å' === 'Å'.normalize(), 'ﬃ'.normalize('NFKD'), 'Ⅷ'.normalize('NFKC'), '㎡'.normalize('NFKD'), '½'.normalize('NFKC'));
"""


def test_normalize_argument_handling(run):
    """CATCHES: normalize() accepting invalid or differently-cased form names instead of throwing RangeError, not defaulting to NFC for undefined, not coercing the receiver/argument with ToString, or corrupting lone surrogates."""
    _ok(run, PROG_NORMALIZE_ARGS, "normalize_args")


PROG_CASE_MAPPING = r"""
for (const s of ['ß', 'ŉ', 'ǰ', 'ΐ', 'ΰ', 'ﬀ', 'ﬃ', 'ﬅ', 'և', 'ᾳ', 'ᾈ', 'ῼ', 'ẖ',
  'İ', 'I', 'ı', 'i', 'ǅ', 'ẞ', '\u{10400}', '\u{10428}', '\u{1E900}', 'ꞵ', 'ȿ', 'ⱥ', 'ʂ',
  'µ', 'ÿ', 'K', 'Å', 'Ω', 'ꭰ', 'ᏸ', 'Ꭰ', 'ʩ', 'ⓐ', 'Ⅻ', 'ͅ', 'ι', '\u{16E40}', '\u{1D400}']) {
  p(hex(s), hex(s.toUpperCase()), hex(s.toLowerCase()), hex(s.toLocaleUpperCase()), hex(s.toLocaleLowerCase()));
}
p('İ'.toLowerCase().length, 'ß'.toUpperCase().length, 'ΐ'.toUpperCase().length, 'Straße'.toUpperCase(), 'ǅungla'.toLowerCase(), 'ǅungla'.toUpperCase());
p('ﬃne ﬁsh'.toUpperCase(), 'ABCÀÉ'.toLowerCase(), 'abcàé'.toUpperCase(), 'MIXed 123 İı'.toLowerCase(), units('\uD800a\uDC00'.toUpperCase()));
p(String.prototype.toUpperCase.call(true), String.prototype.toLowerCase.call(12.5e1), E(() => String.prototype.toUpperCase.call(null)), [].map.call('abß', c => c.toUpperCase()).join('|'));
"""


def test_case_mapping_special_casing(run):
    """CATCHES: toUpperCase/toLowerCase that use only simple (1:1) mappings instead of SpecialCasing (sharp s, ligatures, Greek with ypogegrammeni, dotted capital I -> i + U+0307), miss astral-plane letters (Deseret, Adlam, Medefaidrin), or alter lone surrogates."""
    _ok(run, PROG_CASE_MAPPING, "case_mapping")


PROG_FINAL_SIGMA = r"""
const cases = ['Σ', 'ΑΣ', 'ΑΣ.', 'ΑΣΑ', 'Σ Σ', 'ΑΣ Β', 'ΑΣ́', 'Α­Σ',
  'aΣͅb', 'ΑΣ1', 'ΌΣΟΣ ΆΣΣΟΣ', 'ΣΑΣ', 'ΑΣ’Σ', '1Σ',
  'ΑΣ\u{1D400}', 'AΣ', '\u{10400}Σ', 'Α.Σ', 'ΑΣΣ', 'ΆΣ́ x'];
for (const s of cases) p(hex(s), hex(s.toLowerCase()), hex(s.toLocaleLowerCase()));
"""


def test_final_sigma_context(run):
    """CATCHES: lowercasing that maps every capital sigma to U+03C3 (or always to final U+03C2) instead of applying the Final_Sigma context: preceded by a cased letter and not followed by one, skipping case-ignorable characters on both sides."""
    _ok(run, PROG_FINAL_SIGMA, "final_sigma")


PROG_LOCALE_CASE = r"""
p(hex('Iİiı'.toLocaleLowerCase('tr')), hex('Iİiı'.toLocaleUpperCase('tr')), hex('Iİiı'.toLocaleLowerCase('az')), hex('Iİiı'.toLocaleUpperCase('en-US')));
p(hex('İ'.toLocaleLowerCase('tr')), hex('İ'.toLowerCase()), hex('i̇'.toLocaleUpperCase('lt')), hex('Ì'.toLocaleLowerCase('lt')), hex('Ì'.toLocaleLowerCase('lt')));
p(hex('i'.toLocaleUpperCase(['lt', 'tr'])), hex('i'.toLocaleUpperCase(['tr', 'lt'])), hex('i'.toLocaleUpperCase('TR')), hex('I'.toLocaleLowerCase('tr-TR')), hex('i'.toLocaleUpperCase([])));
p(E(() => 'a'.toLocaleUpperCase('x-invalid-!!')), E(() => 'a'.toLocaleLowerCase('')), E(() => 'a'.toLocaleUpperCase(5)), String.prototype.toLocaleUpperCase.length);
"""


def test_locale_sensitive_case_mapping(run):
    """CATCHES: toLocaleUpperCase/toLocaleLowerCase that ignore the requested locale (Turkish/Azeri dotted and dotless i, Lithuanian dot retention), do not pick the first locale of a list, or accept malformed language tags without a RangeError."""
    _ok(run, PROG_LOCALE_CASE, "locale_case")


PROG_UTF16 = r"""
const s = 'a\u{1F600}b\uD800c\uDC00';
p(s.length, [...s].length, JSON.stringify(Array.from(s).map(c => c.length)), units(s.at(1)), units(s.at(-1)), units(s.at(2)), JSON.stringify(s.at(99)), JSON.stringify(s.at(-99)));
p(units(s.charAt(1)), units(s.charAt(2)), JSON.stringify(s.charAt(99)), s.charCodeAt(1), s.charCodeAt(2), s.charCodeAt(99), s.charCodeAt(-1), s.charCodeAt(1.7));
p(s.codePointAt(1), s.codePointAt(2), s.codePointAt(4), s.codePointAt(6), s.codePointAt(7), s.codePointAt(-1), units(s[1]), units(s[2]), s[99]);
p(units('\u{1F600}abc'.slice(1)), units('\u{1F600}abc'.slice(0, 1)), units('\u{1F600}abc'.substring(1, 3)), units('\u{1F600}abc'.substr(-4, 2)), units('ab\u{1F600}'.slice(-1)), 'ab\u{1F600}'.split('').length);
p('\u{1F600}x\u{1F600}'.indexOf('\uDE00'), '\u{1F600}x\u{1F600}'.lastIndexOf('\uD83D'), '\u{1F600}x\u{1F600}'.includes('\uDE00x'), '\u{1F600}'.startsWith('\uD83D'), '\u{1F600}'.endsWith('\uDE00'), '\u{1F600}'.indexOf('\uD83D', 1));
p('x'.padEnd(3, '\u{1F600}') === 'x\u{1F600}', units('x'.padStart(4, '\u{1F600}')), units('x'.padEnd(2, '\u{1F600}')), '\u{1F600}'.repeat(3).length, units('\u{1F600}'.split('\uDE00')[0]));
p(units([...'\u{1F600}\u{1F601}'].reverse().join('')), units('\u{1D49C}\u{1D49D}'.split('').reverse().join('')), JSON.stringify(Array.from('\u{10FFFF}\u{10000}', c => c.codePointAt(0))));
p(units('\u{1F600}'.trim()), units(' \u{1F600}\uD800 '.trimEnd()), units('a\uD800'.concat('\uDC00b')), units(['\uD83D', '\uDE00'].join('')), units(`${'\uD83D'}${'\uDE00'}`));
const ws = '\t\n\v\f\r                  　﻿';
p(ws.length, (ws + 'x' + ws).trim(), (ws + 'x').trimStart().length, ('x' + ws).trimEnd().length, '᠎x​'.trim().length, '‌x‍'.trim().length, [...ws].every(c => /^\s$/.test(c)), Number(ws + '12' + ws), parseInt(ws + '7'), parseFloat('　' + '1.5'), Number('᠎1'));
p('\u{1F600}' < '￿', '￿' > '\u{10000}', '\uD800' < '\uDC00', 'a\u{1F600}' < 'a', '\u{1F600}'.localeCompare('\u{1F600}'), 'a'.localeCompare('b'), 'b'.localeCompare('a'));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_utf16_code_unit_semantics(run, tier):
    """CATCHES: strings measured or indexed by code points or bytes instead of UTF-16 code units: wrong length/at/charAt/charCodeAt/codePointAt on astral characters and lone surrogates, slicing or padding that splits pairs differently, code-point (not code-unit) string comparison, or a wrong WhiteSpace set for trim/Number (U+180E and U+200B are not whitespace)."""
    _ok(run, PROG_UTF16, "utf16", tier)


PROG_SURROGATE_JOIN = r"""
const hi = '\uD83D', lo = '\uDE00';
const j = hi + lo;
p(j === '\u{1F600}', j.length, j.codePointAt(0), [...j].length, units(hi + 'x' + lo), [...(hi + 'x' + lo)].length, (hi + lo).normalize('NFC') === '\u{1F600}');
p(hi.concat(lo) === '\u{1F600}', [lo, hi].join('').codePointAt(0), units(lo + hi), (lo + hi + lo).codePointAt(1), [...(lo + hi + lo)].length);
let acc = ''; for (const u of [0xD83D, 0xDE00, 0xD83D, 0xDE01, 0xDBFF]) acc += String.fromCharCode(u);
p(acc.length, [...acc].length, JSON.stringify([...acc].map(c => c.codePointAt(0).toString(16))), acc.isWellFormed(), acc.slice(0, 4).isWellFormed());
const parts = '\u{1F600}\u{1F601}'.split(''); p(parts.length, parts.join('') === '\u{1F600}\u{1F601}', parts.slice(1, 3).join('').length, [...parts.slice(1, 3).join('')].length);
const m = new Map([[hi + lo, 1]]); p(m.get('\u{1F600}'), JSON.stringify(Object.keys({ [hi + lo]: 1 })), ({ [hi]: 1 })[hi], JSON.stringify(Object.keys({ [hi]: 1, [lo]: 2 })));
let built = ''; for (let i = 0; i < 3; i++) { built += '\uD83D'; built += String.fromCharCode(0xDE00 + i); }
p(JSON.stringify(built), built.length, [...built].length);
let s2 = 'x\uD83D'; s2 += '\uDE00'; p(s2 === 'x\u{1F600}', s2.at(-1) === lo, s2.slice(1) === '\u{1F600}', units(s2.substring(0, 2) + s2.substring(2)));
const tpl = `${hi}`; p(units(tpl + lo), (tpl + lo) === j, units(String.raw`${hi}${lo}`), units(hi.padEnd(2, lo)), units(lo.padStart(2, hi)), units(hi.repeat(2) + lo));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_surrogates_join_into_pairs(run, tier):
    """CATCHES: string representations that keep a lone high and lone low surrogate separate after concatenation/join/+=/padding (so the result is not equal to the astral character), or that wrongly merge surrogates in the reverse order."""
    _ok(run, PROG_SURROGATE_JOIN, "surrogate_join", tier)


PROG_FROM_CODE_POINT = r"""
p(String.fromCodePoint(0x1F600, 0x41, 0x10FFFF).length, units(String.fromCodePoint(0x10FFFF)), String.fromCharCode(0xD83D, 0xDE00) === '\u{1F600}', String.fromCharCode(0x1F600 + 0x10000 * 3).charCodeAt(0), String.fromCharCode(-1).charCodeAt(0));
for (const bad of [-1, 0x110000, 1.5, NaN, 'x', Infinity, -0.5, undefined, {}]) p(String(bad), E(() => units(String.fromCodePoint(bad))));
p(JSON.stringify(String.fromCodePoint()), units(String.fromCodePoint('65', 66.0, -0, [67])), units(String.fromCodePoint(0xD800)), units(String.fromCodePoint(0xD83D, 0xDE00)), String.fromCodePoint.length, String.fromCharCode.length);
p('ab\uD800'.isWellFormed(), 'ab\u{1F600}'.isWellFormed(), units('a\uD800b\uDFFFc\u{1F600}'.toWellFormed()), units('\uDC00\uD800'.toWellFormed()), ''.isWellFormed(), '\u{10FFFF}'.isWellFormed());
p(String.prototype.isWellFormed.call(12), E(() => String.prototype.toWellFormed.call(null)), units(String.prototype.toWellFormed.call({ toString() { return '\uD800'; } })));
p(JSON.stringify('\uD800'), JSON.stringify('\uDC00\u{1F600}\uD83D'), JSON.stringify({ ['\uDFFF']: 1 }), JSON.stringify('  \u0000\u001f\u007f'), JSON.parse('"\\ud83d\\ude00"') === '\u{1F600}', units(JSON.parse('"\\ud800x"')));
p(String.raw`\u{1F600}`, '\u{1F600}' === '😀', '\u{0041}\x41A' === 'AAA', '\u{000000041}', units('\u{D800}'), eval("'\\u{1F600}'").length);
"""


def test_from_code_point_and_well_formed(run):
    """CATCHES: String.fromCodePoint accepting non-integer or out-of-range code points, fromCharCode not truncating to 16 bits, isWellFormed/toWellFormed not detecting or replacing lone surrogates with U+FFFD, or JSON.stringify not escaping lone surrogates."""
    _ok(run, PROG_FROM_CODE_POINT, "from_code_point")


PROG_ITERATION = r"""
p(JSON.stringify([...'a\u{10000}\uDC00'].map(c => c.codePointAt(0).toString(16))), Array.from('\u{10FFFF}').length, [...'\uD800𐀀'].length);
const it = '\u{1F600}a'[Symbol.iterator]();
p(Object.prototype.toString.call(it), JSON.stringify(it.next()), JSON.stringify(it.next()), JSON.stringify(it.next()), typeof it[Symbol.iterator], it[Symbol.iterator]() === it);
const out = []; for (const ch of 'x\u{1F468}‍\u{1F469}\uD800y') out.push(units(ch)); p(out.join(' / '));
p(JSON.stringify(Object.entries('a\u{1F600}').map(([k, v]) => k + '=' + units(v))), Object.keys('\u{1F600}').length, JSON.stringify(Object.getOwnPropertyNames('ab')));
const seg = (s) => { const r = []; for (const c of s) r.push(c.length); return r.join(''); };
p(seg('\u{1F1EF}\u{1F1F5}'), seg('é'), seg('\u{E0067}a'), [...new Set('\u{1F600}\u{1F600}a')].length, Array.prototype.map.call('a\u{1F600}', c => c.length).join(''));
let n = 0; for (let i = 0; i < 'a\u{1F600}b'.length; i++) n += 'a\u{1F600}b'.charCodeAt(i) > 0xFFFF ? 100 : 1; p(n, [...'\u{1F600}'.repeat(500)].length, 'a\u{1F600}'.split('').map(c => c.charCodeAt(0)).join());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_string_iteration_by_code_point(run, tier):
    """CATCHES: string iterators that yield code units instead of code points (or merge a lone surrogate with its neighbour), a wrong String Iterator toStringTag/self-iterator, or Object.keys/entries on strings that count code points."""
    _ok(run, PROG_ITERATION, "iteration", tier)


PROG_ENCODING = r"""
p(encodeURIComponent('\u{1F600}é /?#'), encodeURI('\u{1F600}/a b?x=1#f'), decodeURIComponent('%F0%9F%98%80') === '\u{1F600}', decodeURI('%E2%82%AC%2F'));
for (const bad of ['\uD800', '\uDC00', 'a\uD83D', '\uDE00\uD83D']) p(units(bad), E(() => encodeURIComponent(bad)), E(() => encodeURI(bad)));
for (const bad of ['%ED%A0%80', '%F4%90%80%80', '%C0%AF', '%E2%82', '%FF', '%', '%G0']) p(bad, E(() => units(decodeURIComponent(bad))));
p(escape('\u{1F600}ä +'), units(unescape('%uD83D%uDE00')), units(unescape('%u12%zz%41')));
p(new TextEncoder().encode('a\u00E9\u20AC').join(','), new TextEncoder().encode('\u{1F600}').join(','), new TextEncoder().encode('\uD83D' + '\uDE00').join(','));
p(units(new TextDecoder().decode(new Uint8Array([0xF0, 0x9F, 0x98, 0x80, 0xFF, 0x41]))), units(new TextDecoder().decode(new Uint8Array([0xED, 0xA0, 0x80]))), units(new TextDecoder().decode(new Uint8Array([0xE2, 0x82]))));
p(units(new TextDecoder().decode(new Uint8Array([0xEF, 0xBB, 0xBF, 0x41]))), units(new TextDecoder('utf-8', { ignoreBOM: true }).decode(new Uint8Array([0xEF, 0xBB, 0xBF, 0x41]))), E(() => new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array([0xC3]))));
"""


def test_uri_and_text_coding_with_surrogates(run):
    """CATCHES: encodeURI(Component) that does not throw URIError on lone surrogates, decodeURIComponent accepting overlong/surrogate/truncated UTF-8, TextEncoder mis-encoding astral characters built from surrogate halves, or TextDecoder BOM stripping, fatal mode and U+FFFD replacement of invalid/truncated sequences."""
    _ok(run, PROG_ENCODING, "encoding")
