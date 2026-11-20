"""ECMA-402 services other than NumberFormat/DateTimeFormat: Collator (+ localeCompare), PluralRules,
RelativeTimeFormat, ListFormat, DisplayNames, Segmenter, Locale (tag canonicalisation, likely
subtags, info getters), Intl.getCanonicalLocales / supportedValuesOf / supportedLocalesOf,
DurationFormat, and the legacy constructor-chaining behaviour.

All outputs come from the engine's embedded locale tables and are deterministic."""
from conftest import check_script, resources_for

G = resources_for(__file__)

PRELUDE = r'''
const t = (f) => { try { return f(); } catch (e) { return e.name + ': ' + e.message; } };
const J = (x) => JSON.stringify(x);
'''


def check_js(run, workdir, name, body):
    return check_script(run, workdir, G, name, PRELUDE + body)


# ----- Collator ---------------------------------------------------------------------------------

def test_collator_sorting_by_options(run, workdir):
    """CATCHES: a Collator that sorts by raw UTF-16 code units (uppercase before lowercase, accented
    letters after 'z'), ignores sensitivity levels, numeric ordering of digit runs, caseFirst
    upper/lower, or ignorePunctuation when sorting a mixed Latin/Greek/Cyrillic/CJK word list."""
    check_js(run, workdir, "collator_sorting_by_options", r'''
const words = ['résumé', 'resume', 'Resume', 'RESUME', 'rèsume', 'zebra', 'Zebra', 'apple', 'Äpfel', 'apfel', 'äpfel', 'Ångström', 'ångström',
  'Ñandú', 'nandu', 'item10', 'item2', 'item1', 'item02', 'a-b', 'ab', 'a b', 'éclair', 'eclair', 'Éclair', 'Ωmega', 'ωmega', 'Яблоко',
  'яблоко', '日本', '中国', '한국', 'x', 'X', '', '10', '9'];
for (const o of [{}, {sensitivity: 'base'}, {sensitivity: 'accent'}, {sensitivity: 'case'}, {numeric: true}, {caseFirst: 'upper'},
                 {caseFirst: 'lower'}, {ignorePunctuation: true}, {numeric: true, caseFirst: 'upper', sensitivity: 'base'}])
  console.log(J(o), words.slice().sort(new Intl.Collator('en', o).compare).join(' '));
for (const l of ['de', 'sv', 'es', 'fr', 'ja', 'th'])
  console.log(l, words.slice(0, 15).sort(new Intl.Collator(l).compare).join(' '));
''')


def test_collator_compare_matrix_and_locales(run, workdir):
    """CATCHES: compare() returning other than -1/0/1, sensitivity levels mis-ordering accent vs case
    differences, German phonebook (-u-co-phonebk / collation option) and search-usage umlaut
    expansion, -u-kn/-u-kf extensions, Thai defaulting ignorePunctuation to true, and resolvedOptions."""
    check_js(run, workdir, "collator_compare_matrix_and_locales", r'''
const c = (o, a, b, l = 'en') => new Intl.Collator(l, o).compare(a, b);
for (const s of ['base', 'accent', 'case', 'variant'])
  console.log(s, [['a', 'á'], ['a', 'A'], ['a', 'b'], ['á', 'A'], ['A', 'á'], ['ß', 'ss'], ['æ', 'ae'], ['', 'a'], ['abc', 'ab']].map(([x, y]) => c({sensitivity: s}, x, y)).join(' '),
    '| search:', c({sensitivity: s, usage: 'search'}, 'a', 'á'));
console.log(c({}, 'Müller', 'Mueller', 'de'), c({usage: 'search'}, 'Müller', 'Mueller', 'de'), c({collation: 'phonebk'}, 'Müller', 'Mueller', 'de'),
  c({}, 'Müller', 'Mueller', 'de-u-co-phonebk'), c({}, 'Müller', 'Muller', 'de'), c({usage: 'search', sensitivity: 'base'}, 'Müller', 'Mueller', 'de'));
const names = ['Müller', 'Mueller', 'Muller', 'Mxyz', 'Möller', 'Moeller'];
console.log(names.slice().sort(new Intl.Collator('de-u-co-phonebk').compare).join(), '|', names.slice().sort(new Intl.Collator('de').compare).join());
console.log(['10', '9', '1', '100', '09', '1a', 'a1'].sort(new Intl.Collator('en-u-kn').compare).join(), '|',
  ['10', '9', '1', '100'].sort(new Intl.Collator('en-u-kn-false').compare).join(), '|', ['B', 'a', 'A', 'b'].sort(new Intl.Collator('en-u-kf-upper').compare).join());
console.log(['ก-ข', 'กข', 'ก ข'].sort(new Intl.Collator('th').compare).join('|'), '|', ['ก-ข', 'กข', 'ก ข'].sort(new Intl.Collator('th', {ignorePunctuation: false}).compare).join('|'));
for (const l of ['en', 'de-u-co-phonebk', 'es-u-co-trad', 'zh-u-co-pinyin', 'en-u-kn-kf-upper', 'en-u-co-emoji', 'en-u-co-standard', 'de-u-co-bogus', 'th',
                 'sv-u-co-reformed', 'fr-CA', 'xx', 'ko-u-co-searchjl', 'ar-u-co-compat', 'en-u-co-phonebk'])
  console.log(l, J(new Intl.Collator(l).resolvedOptions()));
console.log(J(new Intl.Collator('en-u-kn-kf-upper', {numeric: false, caseFirst: 'upper'}).resolvedOptions()));
console.log(J(new Intl.Collator('de', {usage: 'search', collation: 'phonebk', sensitivity: 'base', ignorePunctuation: true}).resolvedOptions()));
console.log(J(new Intl.Collator('de-u-co-phonebk', {collation: 'eor'}).resolvedOptions()), J(new Intl.Collator('en-u-kf-lower-kn-false').resolvedOptions().locale));
''')


def test_collator_errors_and_locale_compare(run, workdir):
    """CATCHES: invalid Collator options not throwing RangeError with the exact message, the compare
    getter not being bound (usable as a sort callback), String.prototype.localeCompare not honouring
    locales/options (numeric, sensitivity), and ToString coercion of compare() arguments."""
    check_js(run, workdir, "collator_errors_and_locale_compare", r'''
console.log(t(() => new Intl.Collator('en', {sensitivity: 'x'})), '|', t(() => new Intl.Collator('en', {usage: 'filter'})), '|',
  t(() => new Intl.Collator('en', {caseFirst: true})), '|', t(() => new Intl.Collator('en', {localeMatcher: 'fast'})), '|', t(() => Intl.Collator.prototype.compare));
const co = new Intl.Collator();
console.log(co.compare.length, J(co.compare.name), co.compare === co.compare, typeof Intl.Collator('en').compare, co.compare(1, 2), co.compare(undefined, 'undefined'), co.compare(null, 'nulm'));
console.log('a'.localeCompare('B'), 'a'.localeCompare('b', 'en', {}), 'ä'.localeCompare('a', 'de', {sensitivity: 'base'}), 'a10'.localeCompare('a9', undefined, {numeric: true}),
  'a10'.localeCompare('a9'), ''.localeCompare(''), 'a'.localeCompare(), 'undefined'.localeCompare(), 'Ä'.localeCompare('ä', 'de', {caseFirst: 'upper'}), 'é'.localeCompare('é'));
console.log(t(() => 'a'.localeCompare('b', 'not_a_tag')), '|', t(() => 'a'.localeCompare('b', 'en', {sensitivity: 'loud'})), '|', t(() => String.prototype.localeCompare.call(null, 'a')));
console.log(['b', 'C', 'a', 'B', 'c', 'A'].sort((x, y) => x.localeCompare(y)).join(''), ['file10.txt', 'file9.txt', 'File1.txt'].sort((x, y) => x.localeCompare(y, 'en', {numeric: true, sensitivity: 'base'})).join(' '));
''')


# ----- PluralRules ------------------------------------------------------------------------------

def test_plural_rules_cardinal_and_ordinal(run, workdir):
    """CATCHES: missing or wrong CLDR plural rules per language (French 0/1 'one' and million 'many',
    Polish few/many by i%10 and i%100, Slovenian two/few, Manx), fractions and negatives handling,
    ordinal type selection, and resolvedOptions().pluralCategories lists (the reference's ordinal rules
    reuse the cardinal ones, e.g. en ordinal 2 is 'other', and ru/uk/cs select like English while
    reporting four categories — pinned as observed)."""
    check_js(run, workdir, "plural_rules_cardinal_and_ordinal", r'''
const nums = [0, 1, 2, 3, 5, 11, 12, 21, 22, 25, 100, 101, 102, 111, 1000000, 1.5, 0.1, -1, -2];
for (const l of ['en', 'fr', 'ru', 'pl', 'ar', 'ja', 'de', 'cs', 'uk', 'sl', 'gv', 'he', 'pt', 'pt-PT', 'es', 'it', 'ko', 'zh', 'xx'])
  console.log(l.padEnd(5), nums.map(n => new Intl.PluralRules(l).select(n)).join(','), '|',
    [1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(n => new Intl.PluralRules(l, {type: 'ordinal'}).select(n)).join(','), '|',
    J(new Intl.PluralRules(l).resolvedOptions().pluralCategories), J(new Intl.PluralRules(l, {type: 'ordinal'}).resolvedOptions().pluralCategories));
''')


def test_plural_rules_options_and_select_range(run, workdir):
    """CATCHES: PluralRules ignoring digit options before selecting (minimumFractionDigits makes 1
    'other', rounding 1.4 to 1 makes it 'one'), compact notation exponent affecting French 'many',
    selectRange results/errors, ToNumber coercion (strings, BigInt TypeError), resolvedOptions shape,
    and the requires-new TypeError."""
    check_js(run, workdir, "plural_rules_options_and_select_range", r'''
const P = (l, o) => new Intl.PluralRules(l, o);
console.log(P('en', {minimumFractionDigits: 1}).select(1), P('en', {maximumFractionDigits: 0}).select(1.4), P('en', {maximumSignificantDigits: 1}).select(1.2),
  P('fr', {notation: 'compact'}).select(1e6), P('fr', {notation: 'compact'}).select(2000000), P('fr').select(2000000), P('en', {roundingMode: 'floor', maximumFractionDigits: 0}).select(1.9));
console.log(J(P('en').resolvedOptions()));
console.log(J(P('ar-EG', {type: 'ordinal', minimumSignificantDigits: 2, roundingMode: 'floor'}).resolvedOptions()));
console.log(J(P('pl', {minimumIntegerDigits: 3, minimumFractionDigits: 1, maximumFractionDigits: 2, roundingPriority: 'lessPrecision', maximumSignificantDigits: 4}).resolvedOptions()));
console.log(P('en').selectRange(1, 2), P('fr').selectRange(0, 1), P('ru').selectRange(1, 5), P('ja').selectRange(1, 5), P('en').selectRange(1, 1), P('pl').selectRange(2, 5),
  t(() => P('en').selectRange(NaN, 1)), '|', t(() => P('en').selectRange(1)), '|', t(() => P('en').selectRange(5, 1)));
console.log(t(() => Intl.PluralRules('en')), '|', t(() => P('en', {type: 'x'})), '|', t(() => P('en', 5)), '|', P('en').select('1'), t(() => P('en').select(1n)), P('en').select(), P('en').select(Infinity), P('en').select(NaN));
console.log(J(Intl.PluralRules.supportedLocalesOf(['fr', 'xx', 'pl-PL'])), Object.prototype.toString.call(P('en')), Intl.PluralRules.prototype.select.length, Intl.PluralRules.prototype.selectRange.length);
''')


# ----- RelativeTimeFormat -----------------------------------------------------------------------

def test_relative_time_format_english(run, workdir):
    """CATCHES: RelativeTimeFormat in English mishandling past/future (negative zero is past),
    singular/plural unit names, numeric 'auto' phrases (yesterday/tomorrow/last week/now/this
    quarter), plural unit aliases ('days'), and short/narrow abbreviations (qtr./qtrs., mo., yr.)."""
    check_js(run, workdir, "relative_time_format_english", r'''
const rtf = (l, o) => new Intl.RelativeTimeFormat(l, o);
for (const u of ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year', 'days', 'years', 'seconds'])
  console.log(u.padEnd(7), [-2, -1, 0, 1, 2, 1.5, -0, 1000].map(v => rtf('en').format(v, u)).join(' | '), '||',
    [-2, -1, 0, 1, 2].map(v => rtf('en', {numeric: 'auto'}).format(v, u)).join(' | '), '||',
    [-1, 3].map(v => rtf('en', {style: 'short'}).format(v, u) + '/' + rtf('en', {style: 'narrow'}).format(v, u)).join(' | '));
console.log(rtf('en', {numeric: 'auto'}).format(-0, 'day'), '|', rtf('en', {numeric: 'auto'}).format(1.5, 'day'), '|', rtf('en').format('3', 'day'), '|', rtf('en').format(-1234567.891, 'year'));
''')


def test_relative_time_format_locales_parts_errors(run, workdir):
    """CATCHES: RelativeTimeFormat formatToParts not tagging numeric parts with their unit (and not
    splitting grouped integers), Polish few/many forms, localized digits via -u-nu-, resolvedOptions
    shape, and RangeError/TypeError messages for invalid units, non-finite values and bad options."""
    check_js(run, workdir, "relative_time_format_locales_parts_errors", r'''
const rtf = (l, o) => new Intl.RelativeTimeFormat(l, o);
for (const l of ['de', 'fr', 'ja', 'ar', 'pl', 'pl-PL', 'xx'])
  console.log(l, '|', [-1, 0, 1, 5].map(v => rtf(l, {numeric: 'auto'}).format(v, 'day')).join(' | '), '||', [-3, 3, -22, 25, 1.5].map(v => rtf(l).format(v, 'hour')).join(' | '), '||',
    ['short', 'narrow'].map(s => rtf(l, {style: s}).format(-2, 'month')).join(' | '));
for (const u of ['second', 'minute', 'day', 'week', 'month', 'quarter', 'year'])
  console.log('pl', u, [1, 2, 5, 22, -1, -5].map(v => rtf('pl').format(v, u)).join(' | '), '|', rtf('pl', {style: 'short'}).format(5, u), '|', rtf('pl', {numeric: 'auto'}).format(-1, u),
    '|', [1, 2, 5, 1.5].map(v => rtf('pl', {style: 'narrow'}).format(v, u)).join(' | '));
console.log(J(rtf('en').formatToParts(-1234.5, 'day')));
console.log(J(rtf('en', {numeric: 'auto'}).formatToParts(1, 'day')), J(rtf('de').formatToParts(10, 'second')), J(rtf('en-u-nu-arab').formatToParts(12, 'week')));
console.log(J(rtf('en').resolvedOptions()), J(rtf('en-u-nu-arab', {numeric: 'auto', style: 'narrow'}).resolvedOptions()), rtf('en-u-nu-arab').format(12, 'day'), J(rtf('en', {numberingSystem: 'deva'}).resolvedOptions()));
console.log(t(() => rtf('en').format(1, 'decade')), '|', t(() => rtf('en').format(NaN, 'day')), '|', t(() => rtf('en').format(Infinity, 'day')), '|', t(() => rtf('en', {style: 'tiny'})), '|',
  t(() => rtf('en', {numeric: 'sometimes'})), '|', t(() => Intl.RelativeTimeFormat('en')), '|', t(() => rtf('en').format(1)), '|', t(() => rtf('en').format(1n, 'day')));
''')


# ----- ListFormat -------------------------------------------------------------------------------

def test_list_format_types_styles(run, workdir):
    """CATCHES: ListFormat using the wrong two/start/middle/end patterns (Oxford comma in en long,
    '&' in short, Spanish 'y'/'o' without comma, unit lists comma- or space-joined), empty and
    single-item lists, iterable inputs (strings, Sets), and the non-string element TypeError."""
    check_js(run, workdir, "list_format_types_styles", r'''
const lists = [[], ['a'], ['a', 'b'], ['a', 'b', 'c'], ['a', 'b', 'c', 'd']];
for (const l of ['en', 'es', 'de'])
  for (const type of ['conjunction', 'disjunction', 'unit'])
    for (const style of ['long', 'short', 'narrow'])
      console.log(l, type, style, '=>', lists.map(x => J(new Intl.ListFormat(l, {type, style}).format(x))).join(' '));
console.log(J(new Intl.ListFormat('en').formatToParts(['x', 'y', 'z'])));
console.log(J(new Intl.ListFormat('es', {type: 'disjunction'}).formatToParts(['uno', 'dos'])));
console.log(J(new Intl.ListFormat('en').resolvedOptions()), J(new Intl.ListFormat('es-MX', {type: 'unit', style: 'narrow'}).resolvedOptions()), J(new Intl.ListFormat('xx').resolvedOptions()));
const lf = new Intl.ListFormat('en');
console.log(t(() => lf.format(['a', 1])), '|', lf.format('abc'), '|', lf.format(new Set(['p', 'q'])), '|', lf.format(), '|', J(lf.formatToParts([])), '|', lf.format(['', ' ', 'and']));
console.log(t(() => new Intl.ListFormat('en', {type: 'x'})), '|', t(() => new Intl.ListFormat('en', {style: 'x'})), '|', t(() => Intl.ListFormat()), '|', t(() => new Intl.ListFormat('en', 'conjunction')));
''')


# ----- DisplayNames -----------------------------------------------------------------------------

def test_display_names_types_and_fallback(run, workdir):
    """CATCHES: DisplayNames returning wrong English names per type (language dialect names like
    'British English', regions incl. '419', scripts, currencies, calendars incl. alias
    canonicalisation islamicc -> islamic-civil), fallback 'code' (canonicalised code) vs 'none'
    (undefined), and RangeErrors for malformed codes."""
    check_js(run, workdir, "display_names_types_and_fallback", r'''
const DN = (l, o) => new Intl.DisplayNames(l, o);
const cases = {
  language: ['en', 'en-GB', 'en-US', 'de', 'zh', 'ar', 'fr-CA', 'EN-us', 'xx', 'zh-Hant', 'iw', 'en-u-ca-x', 'abc-def-1', 'en-x-priv'],
  region: ['US', 'gb', '419', 'DE', 'ZZ', '001', 'usa', '1', 'BR', 'kr'],
  script: ['Latn', 'latn', 'CYRL', 'Hans', 'Zzzz', 'Lat', 'Kore'],
  currency: ['USD', 'eur', 'jpy', 'XYZ', 'US', 'CNY', 'gbp'],
  calendar: ['gregory', 'islamicc', 'ethiopic-amete-alem', 'japanese', 'roc', 'bogus', 'islamic-civil', 'x', 'islamic-umalqura', 'iso8601'],
  dateTimeField: ['era', 'year', 'month', 'weekOfYear', 'dayPeriod', 'timeZoneName', 'century'],
};
for (const [type, codes] of Object.entries(cases))
  for (const fb of ['code', 'none'])
    console.log(type, fb, '|', codes.map(c => t(() => String(DN('en', {type, fallback: fb}).of(c)))).join(' | '));
console.log(DN('de', {type: 'language'}).of('fr'), '|', DN('ja', {type: 'region'}).of('JP'), '|', DN('en', {type: 'language', style: 'narrow', languageDisplay: 'standard'}).of('en-GB'));
console.log(J(DN('en-GB', {type: 'region'}).resolvedOptions()), J(DN('xx', {type: 'calendar', style: 'short', fallback: 'none', languageDisplay: 'standard'}).resolvedOptions()));
console.log(t(() => DN('en')), '|', t(() => DN('en', {})), '|', t(() => DN('en', {type: 'foo'})), '|', t(() => Intl.DisplayNames('en', {type: 'region'})), '|',
  t(() => DN('en', {type: 'region', style: 'tiny'})), '|', t(() => DN('en', {type: 'region', fallback: 'x'})), '|', t(() => DN('en', {type: 'language', languageDisplay: 'x'})));
console.log(t(() => DN('en', 'abc')), '|', t(() => DN('en', {type: 'region'}).of()), '|', t(() => DN('en', {type: 'region'}).of(Symbol())), '|', t(() => Intl.DisplayNames.prototype.of.call({}, 'US')));
''')


# ----- Segmenter --------------------------------------------------------------------------------

def test_segmenter_graphemes(run, workdir):
    """CATCHES: grapheme segmentation splitting combining marks, ZWJ emoji families, regional-
    indicator flag pairs, skin-tone modifiers, CRLF or Hangul syllable sequences, or reporting
    UTF-16 indices incorrectly for astral characters."""
    check_js(run, workdir, "segmenter_graphemes", r'''
const seg = new Intl.Segmenter('en', {granularity: 'grapheme'});
const show = (s) => console.log(J([...seg.segment(s)].map(x => [x.segment, x.index])));
show('\u{E9}a\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467}\u{200D}\u{1F466}\u{1F1EF}\u{1F1F5}x\r\ny\u{92F}\u{93C}\u{939}\u{D55C}\u{AE00}');
show('e\u{301}\u{302} \u{1F44D}\u{1F3FD} \u{1F3F3}\u{FE0F}\u{200D}\u{1F308} \u{1F1FA}\u{1F1F8}\u{1F1EC}\u{1F1E7}\u{1F1EB}');
show('\u{1100}\u{1161}\u{11A8} \u{915}\u{94D}\u{937} ab\u{200D}c \n\r');
show('');
show('\u{1F600}\u{1F603}');
console.log([...seg.segment('\u{1F1FA}\u{1F1F8}\u{1F1EC}\u{1F1E7}')].length, [...seg.segment('a\u{300}\u{301}\u{302}')].length, [...new Intl.Segmenter().segment('x\u{200D}\u{200D}y')].map(s => s.segment.length).join(','));
''')


def test_segmenter_words_sentences_containing(run, workdir):
    """CATCHES: word segmentation not keeping apostrophes/decimal points/thousand separators inside
    words, wrong isWordLike flags for punctuation and spaces, CJK/Thai runs, sentence boundaries
    after .?! (including abbreviations and quotes), containing() index lookup edge cases, iterator
    protocol, and resolvedOptions."""
    check_js(run, workdir, "segmenter_words_sentences_containing", r'''
const seg = (l, o) => new Intl.Segmenter(l, o);
const show = (g, s) => console.log(g, J([...seg('en', {granularity: g}).segment(s)].map(x => g === 'word' ? [x.segment, x.index, x.isWordLike] : [x.segment, x.index])));
show('word', "Hello, world! It's 3.14 and don't-stop... e-mail 東京タワー 1,000 _id x2 ö");
show('word', 'สวัสดีครับ ไทย');
show('word', '日本語のテキストです。中文分词测试');
show('word', '');
show('word', 'a   b \u{1F600}x \u{1D4B3}yz\t\t!');
show('sentence', 'Hello there. How are you? I am fine! Mr. Smith said "hi." Ok');
show('sentence', '第一句。第二句！第三句？');
show('sentence', 'No terminator here');
show('sentence', 'Line one.\nLine two.\n\nNew para');
const s = seg('en', {granularity: 'word'}).segment('foo bar baz');
console.log([0, 3, 5, 10, 11, -1, undefined, '4', 2.7, NaN].map(i => J(s.containing(i))).join(' '));
console.log(J(seg('en').segment('ab').containing(1)), J(seg('en', {granularity: 'sentence'}).segment('A b. C d.').containing(6)));
const it = seg('en').segment('ab')[Symbol.iterator]();
console.log(J(it.next()), J(it.next()), J(it.next()), typeof it[Symbol.iterator]);
console.log(J(seg('en').resolvedOptions()), J(seg('ja-JP', {granularity: 'sentence'}).resolvedOptions()), J(seg('xx').resolvedOptions()));
console.log(t(() => seg('en', {granularity: 'line'})), '|', t(() => Intl.Segmenter()), '|', [...seg('en').segment()].map(x => x.segment).join('-'), '|', [...seg('en').segment(12.5)].length);
''')


# ----- Locale -----------------------------------------------------------------------------------

def test_locale_maximize_minimize_getters(run, workdir):
    """CATCHES: wrong likely-subtags data (zh -> zh-Hans-CN, zh-TW -> zh-Hant-TW, und-JP -> ja-Jpan-JP,
    sr -> sr-Cyrl-RS), minimize not removing inferable script/region, extensions not preserved by
    maximize/minimize, and Locale getters (baseName, script, region, calendar, collation, hourCycle,
    caseFirst, numeric, numberingSystem, firstDayOfWeek, variants)."""
    check_js(run, workdir, "locale_maximize_minimize_getters", r'''
const L = (s, o) => new Intl.Locale(s, o);
for (const s of ['en', 'zh', 'zh-TW', 'zh-Hant', 'zh-HK', 'sr', 'sr-ME', 'und', 'und-Latn', 'und-JP', 'ja-JP-u-ca-japanese', 'en-Latn-US', 'en-GB', 'pt',
                 'ar', 'ru-Cyrl', 'az', 'uz-Arab', 'mn', 'iw', 'und-150', 'hi', 'de-CH', 'es-419', 'en-Shaw', 'und-Cyrl-RO'])
  console.log(s, '|', L(s).maximize().toString(), '|', L(s).minimize().toString(), '|', L(s).maximize().minimize().baseName);
const keys = ['baseName', 'language', 'script', 'region', 'variants', 'calendar', 'collation', 'hourCycle', 'caseFirst', 'numeric', 'numberingSystem', 'firstDayOfWeek'];
for (const tag of ['en-Latn-US-u-ca-gregory-co-phonebk-hc-h12-kf-upper-kn-nu-latn-fw-mon', 'de', 'sl-rozaj-biske-1994', 'en-u-kn-false'])
  console.log(tag, '|', keys.map(k => k + '=' + J(L(tag)[k])).join(' '));
const l2 = L('de', {region: 'AT', script: 'Latn', calendar: 'buddhist', collation: 'phonebk', hourCycle: 'h23', caseFirst: 'lower', numeric: true, numberingSystem: 'arab', firstDayOfWeek: 'sun'});
console.log(l2.toString(), l2.baseName, J(l2.calendar), l2.numeric, l2.firstDayOfWeek);
console.log(L('fr-CA-u-kn-false', {numeric: true}).toString(), L('en-u-ca-buddhist', {calendar: 'japanese'}).toString(), L('en', {firstDayOfWeek: 7}).toString(), L('en', {firstDayOfWeek: 1}).firstDayOfWeek,
  L('en', {language: 'fr'}).toString(), L(L('ja-JP')).toString(), L('en', {variants: 'fonipa'}).toString());
console.log(Object.prototype.toString.call(L('en')), String(L('en-us')), J(L('en-us')), Intl.Locale.length, typeof Intl.Locale.prototype.maximize);
''')


def test_locale_tag_canonicalization_and_errors(run, workdir):
    """CATCHES: missing BCP-47/CLDR canonicalisation (case folding, deprecated language/region aliases
    like iw->he, tl->fil, BU->MM, grandfathered tags, sorted variants, -u- keyword value aliases like
    islamicc/imperial/primary/true, extension ordering), getCanonicalLocales deduplication, and
    RangeError/TypeError messages for structurally invalid tags and options."""
    check_js(run, workdir, "locale_tag_canonicalization_and_errors", r'''
const L = (s, o) => new Intl.Locale(s, o);
for (const s of ['EN-latn-us', 'zh-cmn-Hans-CN', 'cmn-Hans-CN', 'sgn-GR', 'en-u-ca-islamicc', 'und-x-private', 'de-1996-1901', 'en-a-bar-x-foo', 'en-t-ja-latn',
                 'art-lojban', 'i-klingon', 'zh-min-nan', 'en-u-ms-imperial', 'ja-u-ca-ethiopic-amete-alem', 'en-u-kn-true', 'en-u-kn-yes', 'en-u-tz-usnyc', 'sh',
                 'mo', 'en-US-u-va-posix', 'hy-arevela', 'en-u-ks-primary', 'en-BU', 'en-SU', 'und-Qaai', 'aar', 'heb-IL', 'en-z-zz-u-cu-usd', 'en-x-u-foo', 'tl',
                 'no-bok', 'cel-gaulish', 'en-u-aa-bb-cc', 'EN-U-KF', 'en-u-ca-gregory-ca-buddhist', 'de-u-co-phonebk-ka-shifted', 'en-t-en-us-h0-hybrid'])
  console.log(s, '=>', t(() => L(s).toString()), '|', t(() => Intl.getCanonicalLocales(s)[0]));
for (const s of ['x-private', 'en-u-zattr-aattr-ca-japanese', 'ja-Latn-hepburn-heploc', 'und-SU', 'hy-SU', 'und-Cyrl-SU', 'en-t-zh-latn-m0-names', 'en-t-k0-qwerty-m0-names',
                 'en-t-ja-latn-m0-alalc97-k0-qwerty', 'EN-T-JA-LATN-M0-ALALC97', 'en-u-ca-gregory-u-x', 'en-u-1a', 'en-t-ja-a1-x', 'en-x-', 'en-x-123456789', 'sgn-DE', 'cmn',
                 'zh-Hans-CN-u-co-pinyin-ca-chinese', 'en-b-bb-a-aa', 'hy-arevmda', 'en-u-sd-usny-ks-identic', 'en-u-ca-ethiopic-amete-alem-u', 'de-DD', 'und-YD', 'ccq',
                 'no-nyn', 'zh-hakka', 'en-GB-oed', 'en-U-ca-Gregory', 'en-01', 'en-001', 'qaa-Qaaa-QM', 'en-t-en-u-ca-roc'])
  console.log('gcl', s, '=>', t(() => Intl.getCanonicalLocales(s)[0]));
console.log(J(Intl.getCanonicalLocales(['en', , 'de'])), J(Intl.getCanonicalLocales({length: 3, 0: 'en', 2: 'fr'})), J(Intl.getCanonicalLocales({length: 1, 0: {toString() { return 'pt-br'; }}})),
  t(() => Intl.getCanonicalLocales({length: 1, 0: {toString() { return 'bad tag'; }}})), J(Intl.getCanonicalLocales(true)));
for (const bad of ['', 'en_US', 'en-US-US', 'xx-yyyyy-zz', 'en-a-x-y', 'en-1996-1996', 'en-t-x', '123', 'a', 'en-', 'en--US', 'toolonglanguage'])
  console.log(J(bad), t(() => L(bad)));
console.log(t(() => L(5)), '|', t(() => L()), '|', t(() => L('en', {region: 'USA1'})), '|', t(() => L('en', {calendar: 'a'})), '|', t(() => L('en', {hourCycle: 'h13'})), '|',
  t(() => Intl.Locale('en')), '|', t(() => L('en', {script: 'L4tn'})), '|', t(() => L('en', {language: 'e'})), '|', t(() => L('en', {firstDayOfWeek: 'x'})), '|', t(() => L('en', {caseFirst: 'up'})));
console.log(J(Intl.getCanonicalLocales(['EN-us', 'en-US', 'de', L('fr-ca'), 'DE'])), '|', t(() => Intl.getCanonicalLocales([5])), '|', t(() => Intl.getCanonicalLocales(null)), '|',
  J(Intl.getCanonicalLocales()), '|', J(Intl.getCanonicalLocales({length: 2, 0: 'ja', 1: 'JA'})), '|', t(() => Intl.getCanonicalLocales('')), '|', J(Intl.getCanonicalLocales(7)));
''')


def test_locale_info_methods(run, workdir):
    """CATCHES: Intl.Locale info methods (getCalendars, getCollations, getHourCycles,
    getNumberingSystems, getTimeZones, getTextInfo, getWeekInfo) not reflecting -u- keywords or
    returning wrong defaults, getTimeZones not being undefined for region-less locales, firstDay from
    -u-fw-, and the brand-check TypeError on foreign receivers."""
    check_js(run, workdir, "locale_info_methods", r'''
const L = (s) => new Intl.Locale(s);
const fns = ['getCalendars', 'getCollations', 'getHourCycles', 'getNumberingSystems', 'getTimeZones', 'getTextInfo', 'getWeekInfo'];
const tags = ['en-US', 'ar-EG', 'ja-JP', 'de', 'he', 'zh-TW', 'en-GB', 'und', 'en-u-ca-buddhist-hc-h23-nu-thai-fw-sun-co-emoji', 'fr-u-fw-wed'];
for (const f of fns) console.log(f, '|', tags.map(s => J(L(s)[f]())).join(' '));
for (const f of fns) console.log(f, Intl.Locale.prototype[f].length, t(() => Intl.Locale.prototype[f].call({})));
console.log(t(() => Object.getOwnPropertyDescriptor(Intl.Locale.prototype, 'baseName').get.call({})), '|', t(() => Intl.Locale.prototype.toString.call('en')));
''')


# ----- Intl namespace ---------------------------------------------------------------------------

def test_supported_values_and_locales(run, workdir):
    """CATCHES: Intl.supportedValuesOf returning unsorted/duplicated lists or wrong members for
    calendar/collation/currency/numberingSystem/unit/timeZone, missing RangeError for unknown keys,
    supportedLocalesOf on every service not filtering unsupported languages, and the Intl namespace
    shape (toStringTag, own properties, constructor lengths)."""
    check_js(run, workdir, "supported_values_and_locales", r'''
for (const k of ['calendar', 'collation', 'currency', 'numberingSystem', 'unit'])
  console.log(k, Intl.supportedValuesOf(k).join(','));
const tz = Intl.supportedValuesOf('timeZone');
console.log('timeZone', tz.length, tz.slice(0, 5).join(','), tz.slice(-5).join(','), tz.includes('UTC'), tz.includes('Etc/UTC'), tz.includes('America/New_York'), tz.includes('Asia/Calcutta'),
  J(tz) === J(tz.slice().sort()), new Set(tz).size === tz.length);
console.log(t(() => Intl.supportedValuesOf('bogus')), '|', t(() => Intl.supportedValuesOf()), '|', Intl.supportedValuesOf('unit') !== Intl.supportedValuesOf('unit'));
for (const svc of ['NumberFormat', 'DateTimeFormat', 'Collator', 'PluralRules', 'RelativeTimeFormat', 'ListFormat', 'DisplayNames', 'Segmenter', 'DurationFormat'])
  console.log(svc, J(Intl[svc].supportedLocalesOf(['en-US', 'de-AT', 'xx', 'he', 'zh-Hant-TW', 'sv', 'ja-JP-u-ca-japanese', 'tlh', 'ar', 'pl'])), Intl[svc].length,
    Object.prototype.toString.call(Intl[svc].prototype), J(Intl[svc].supportedLocalesOf('en', {localeMatcher: 'lookup'})), t(() => Intl[svc].supportedLocalesOf('en', {localeMatcher: 'bad'})));
console.log(Object.prototype.toString.call(Intl), Object.getOwnPropertyNames(Intl).sort().join(','), typeof Intl, t(() => new Intl()));
''')


def test_legacy_constructor_chaining(run, workdir):
    """CATCHES: missing ECMA-402 legacy behaviour where calling Intl.NumberFormat/DateTimeFormat as a
    function on an object inheriting from their prototype stores the instance under a symbol and
    returns that object (whose methods then work), versus returning a fresh instance for unrelated
    receivers; also the newer services rejecting calls without new."""
    check_js(run, workdir, "legacy_constructor_chaining", r'''
const D = Date.UTC(2024, 2, 5, 14, 7, 9);
const o = Object.create(Intl.DateTimeFormat.prototype);
const r = Intl.DateTimeFormat.call(o, 'de');
console.log(r === o, o.format(D), J(o.resolvedOptions().locale), Object.getOwnPropertySymbols(o).length, String(Object.getOwnPropertySymbols(o)[0]), t(() => o.formatToParts(D).length));
const n = Object.create(Intl.NumberFormat.prototype);
const r2 = Intl.NumberFormat.call(n, 'de', {style: 'percent'});
console.log(r2 === n, n.format(0.5), n.resolvedOptions().style, Object.keys(n).length);
const plain = {};
const r3 = Intl.NumberFormat.call(plain, 'de');
console.log(r3 === plain, r3 instanceof Intl.NumberFormat, Object.getOwnPropertySymbols(plain).length);
const r4 = new Intl.DateTimeFormat.prototype.constructor('ja'); console.log(r4.format(D));
console.log(t(() => Intl.Collator.call(Object.create(Intl.Collator.prototype), 'de').compare('a', 'b')), t(() => Intl.NumberFormat.prototype.format.call(Object.create(Intl.NumberFormat.prototype), 1)));
for (const svc of ['PluralRules', 'RelativeTimeFormat', 'ListFormat', 'DisplayNames', 'Segmenter', 'DurationFormat', 'Locale'])
  console.log(svc, t(() => Intl[svc]('en', {type: 'region'})));
''')


# ----- DurationFormat ---------------------------------------------------------------------------

def test_duration_format_styles_locales(run, workdir):
    """CATCHES: DurationFormat long/short/narrow/digital styles producing wrong unit names or list
    joining per locale (es 'y' before the last item), digital style h:mm:ss with fraction digits from
    sub-second units, negative durations signing only the first unit, and the empty-duration error."""
    check_js(run, workdir, "duration_format_styles_locales", r'''
const DF = (l, o) => new Intl.DurationFormat(l, o);
const d1 = {years: 1, months: 2, weeks: 3, days: 4, hours: 5, minutes: 6, seconds: 7, milliseconds: 8, microseconds: 9, nanoseconds: 10};
const d2 = {hours: 1, minutes: 5, seconds: 3};
const d4 = {hours: -2, minutes: -30};
const d5 = {years: 2, days: 1, seconds: 1};
for (const st of ['long', 'short', 'narrow', 'digital'])
  for (const l of ['en', 'de', 'fr', 'ja', 'es'])
    console.log(st, l, '|', [d1, d2, d4, d5].map(d => t(() => DF(l, {style: st}).format(d))).join(' | '));
console.log(t(() => DF('en').format({})), '|', DF('en').format({days: 0, hours: 0}), '|', DF('en').format('PT1H30M'), '|', DF('en').format(Temporal.Duration.from('P1Y2DT3H')), '|',
  DF('en', {style: 'digital'}).format(Temporal.Duration.from({hours: 25, minutes: 3})), '|', DF('en', {style: 'digital'}).format({minutes: 125}), '|', DF('fr-u-nu-arab', {style: 'digital'}).format(d2));
''')


def test_duration_format_unit_options_parts_errors(run, workdir):
    """CATCHES: per-unit style and *Display options (numeric/2-digit, always/auto), fractionalDigits
    rounding of sub-second units, formatToParts part types and unit tags, resolvedOptions defaults for
    digital style, and RangeError/TypeError messages for mixed signs, fractional fields, bad styles and
    style conflicts."""
    check_js(run, workdir, "duration_format_unit_options_parts_errors", r'''
const DF = (l, o) => new Intl.DurationFormat(l, o);
const d2 = {hours: 1, minutes: 5, seconds: 3};
console.log(DF('en', {hours: 'numeric', minutes: '2-digit', seconds: '2-digit'}).format(d2), '|', DF('en', {style: 'long', fractionalDigits: 2}).format({seconds: 5, milliseconds: 123, microseconds: 456}), '|',
  DF('en', {style: 'digital', fractionalDigits: 3}).format({hours: 1, minutes: 2, seconds: 3, milliseconds: 45}), '|', DF('en', {milliseconds: 'numeric'}).format({seconds: 1, milliseconds: 5}), '|',
  DF('en', {hoursDisplay: 'always', minutesDisplay: 'always'}).format({seconds: 5}), '|', DF('en', {style: 'digital', hoursDisplay: 'auto'}).format({minutes: 5, seconds: 3}));
console.log(DF('en', {years: 'narrow', days: 'long', hours: 'short'}).format({years: 2, days: 1, hours: 3}), '|', DF('en', {style: 'narrow', secondsDisplay: 'always'}).format({hours: 1}), '|',
  DF('en', {daysDisplay: 'always'}).format({hours: 1}), '|', DF('en', {style: 'digital', fractionalDigits: 0}).format({seconds: 3, milliseconds: 999}), '|',
  DF('en', {minutes: 'numeric', seconds: 'numeric'}).format({minutes: 3, seconds: 4}), '|', DF('en', {seconds: 'numeric', fractionalDigits: 9}).format({seconds: 1, nanoseconds: 5}));
console.log(J(DF('en', {style: 'digital'}).formatToParts(d2)));
console.log(J(DF('en').formatToParts({hours: 1, minutes: 30})));
console.log(J(DF('de', {style: 'long'}).formatToParts({days: -3, hours: -1})));
console.log(J(DF('en').resolvedOptions()));
console.log(J(DF('fr-u-nu-arab', {style: 'digital', fractionalDigits: 4}).resolvedOptions()));
console.log(t(() => DF('en').format({hours: 1, minutes: -1})), '|', t(() => DF('en').format({hours: 1.5})), '|', t(() => DF('en').format({foo: 1})), '|', t(() => DF('en', {style: 'x'})), '|',
  t(() => DF('en', {fractionalDigits: 10})), '|', t(() => DF('en', {hours: '2-digit', minutes: 'long'})), '|', t(() => Intl.DurationFormat('en')), '|', t(() => DF('en').format(5)), '|',
  t(() => DF('en').format({hours: Infinity})), '|', t(() => DF('en').format('P1X')), '|', t(() => DF('en', {hoursDisplay: 'sometimes'})), '|', t(() => DF('en', {days: 'numeric'})));
for (const s of ['-P1DT2.5S', 'p1w', 'PT', 'P', 'PT1.5H', '+P1Y', 'P1Y2M3W4DT5H6M7.123456789S', '\u2212PT1M', 'PT0,5S', 'P1', 'PTS', 'P1DT', 'PT1H1H'])
  console.log('iso', J(s), t(() => DF('en').format(s)), '|', t(() => DF('en', {style: 'digital'}).format(s)));
console.log(DF('en', {milliseconds: 'numeric', microseconds: 'numeric'}).format({seconds: 1, milliseconds: 5, microseconds: 7}), '|', DF('en', {seconds: 'numeric', millisecondsDisplay: 'always'}).format({seconds: 1}), '|',
  t(() => DF('en', {milliseconds: 'numeric', microseconds: 'long'})), '|', t(() => DF('en', {numberingSystem: 'a'})), '|', t(() => DF('en').format({years: 2 ** 32})), '|',
  t(() => DF('en').format({seconds: 2 ** 53})), '|', t(() => DF('en').format({days: 2 ** 40})));
console.log(DF('en', {style: 'digital'}).format({seconds: -1, milliseconds: -500}), '|', DF('en', {style: 'digital', fractionalDigits: 2}).format({seconds: -1, milliseconds: -505}), '|',
  DF('en', {microseconds: 'numeric'}).format({milliseconds: 3, microseconds: 4, nanoseconds: 5}), '|', DF('en', {style: 'digital'}).format({hours: -0, minutes: 0, seconds: -3}), '|',
  DF('en', {style: 'narrow'}).format({hours: 0, minutes: -5}), '|', DF('en', {style: 'long', hoursDisplay: 'always', minutesDisplay: 'always'}).format({minutes: -0, seconds: -3}));
console.log(J(DF('en', {style: 'digital', fractionalDigits: 2}).formatToParts({hours: 10, minutes: 0, seconds: 7, milliseconds: 891})));
console.log(J(DF('en', {style: 'narrow'}).formatToParts({days: 1, minutes: 2})));
console.log(DF('pl').format({hours: 2, minutes: 5}), '|', DF('ru', {style: 'long'}).format({hours: 2, minutes: 5}), '|', DF('ar').format({hours: 2}), '|', DF('zh', {style: 'long'}).format({days: 3, hours: 2}), '|',
  DF('pt-BR', {style: 'long'}).format({days: 3, hours: 2}), '|', DF('ko', {style: 'narrow'}).format({days: 3, hours: 2}), '|', DF('it', {style: 'short'}).format({days: 3, hours: 2}));
''')


def test_option_read_order_and_coercion(run, workdir):
    """CATCHES: services reading their options in a non-spec order (observable through a Proxy), an
    undefined options argument not being a null-prototype object (Object.prototype pollution must not
    leak in, while an explicit {} does inherit), primitive options being boxed (String.prototype
    properties are read), and getter side-effect order for NumberFormat digit options."""
    check_js(run, workdir, "option_read_order_and_coercion", r'''
const log = [];
const spy = (base = {}) => new Proxy(base, {get(tg, k) { if (typeof k === 'string') log.push(k); return tg[k]; }});
for (const name of ['NumberFormat', 'DateTimeFormat', 'Collator', 'PluralRules', 'RelativeTimeFormat', 'ListFormat', 'Segmenter', 'DurationFormat', 'Locale', 'DisplayNames']) {
  log.length = 0;
  const r = t(() => { new Intl[name]('en', spy(name === 'DisplayNames' ? {type: 'region'} : {})); return 'ok'; });
  console.log(name, r, log.join(','));
}
log.length = 0; t(() => new Intl.NumberFormat('en', spy({style: 'currency'}))); console.log('NF currency missing:', log.join(','));
log.length = 0; t(() => new Intl.DateTimeFormat('en', spy({hourCycle: 'h99'}))); console.log('DTF bad hourCycle:', log.join(','));
Object.prototype.style = 'percent'; Object.prototype.minimumFractionDigits = 2;
console.log(new Intl.NumberFormat('en').format(0.5), new Intl.NumberFormat('en', {}).format(0.5), new Intl.NumberFormat('en', 'x').format(0.5), new Intl.NumberFormat('en', 5).format(0.5),
  new Intl.NumberFormat('en', Object.create(null)).format(0.5));
delete Object.prototype.style; delete Object.prototype.minimumFractionDigits;
String.prototype.timeZone = 'Asia/Tokyo';
console.log(new Intl.DateTimeFormat('en', 'x').resolvedOptions().timeZone, new Intl.DateTimeFormat('en').resolvedOptions().timeZone, t(() => new Intl.PluralRules('en', 'x')));
delete String.prototype.timeZone;
const order = [];
new Intl.NumberFormat('en', {get minimumFractionDigits() { order.push('minFD'); return 1; }, get maximumFractionDigits() { order.push('maxFD'); return 3; },
  get minimumSignificantDigits() { order.push('minSD'); }, get style() { order.push('style'); return 'decimal'; }, get useGrouping() { order.push('grp'); return 'min2'; },
  get roundingMode() { order.push('rm'); return 'floor'; }});
console.log(order.join(','));
const loc = []; Intl.getCanonicalLocales({get length() { loc.push('len'); return 2; }, get 0() { loc.push('0'); return 'de'; }, get 1() { loc.push('1'); return 'fr'; }}); console.log(loc.join(','));
''')
