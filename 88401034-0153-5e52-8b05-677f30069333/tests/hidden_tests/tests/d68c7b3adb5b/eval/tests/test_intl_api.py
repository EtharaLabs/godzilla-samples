"""ECMA-402 (Intl) surface for lumen-cli: NumberFormat (styles, notations, sign display, rounding,
parts and ranges), DateTimeFormat (styles, components, hour cycles, explicit IANA/offset time zones,
non-Gregorian calendars, numbering systems, parts and ranges, Temporal inputs), Locale, tag
canonicalization, Segmenter, RelativeTimeFormat, PluralRules, DisplayNames, DurationFormat,
ListFormat, Collator, and the Number/BigInt/Date/String locale methods that delegate to them.
Every timestamp is a fixed epoch value formatted with an explicit timeZone; nothing reads the clock.
The CLDR-derived data is compiled into the binary, so the output is deterministic."""

import pytest

from conftest import out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# Shared helpers: show() prints a labelled result or the thrown error's name and message; each()
# maps thunks to their results (errors rendered the same way); parts() renders formatToParts-style
# arrays with their optional source/unit fields.
PRELUDE = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function each(label, fs) { out.push(label + ': ' + fs.map(function (f) { try { return String(f()); } catch (e) { return e.name + ': ' + e.message; } }).join(' | ')); }
function parts(p) { return p.map(function (x) { return x.type + '=' + JSON.stringify(x.value) + (x.source ? '@' + x.source : '') + (x.unit ? '/' + x.unit : ''); }).join(' '); }
function nf(o, l) { return new Intl.NumberFormat(l || 'en-US', o); }
"""
EPILOGUE = "\nconsole.log(out.join('\\n'));\n"


def check(js, golden, name, body, tier=()):
    r = js(PRELUDE + body + EPILOGUE, *tier)
    assert out(r) == golden(name)
    assert (r.returncode, r.stderr) == (0, b"")


# ----------------------------------------------------------------------------- Intl.NumberFormat


def test_number_format_locale_symbols_and_numbering_systems(js, golden):
    """CATCHES: NumberFormat using the wrong decimal/group separators or Indian 3;2 grouping per locale, ignoring the default arab digits of Arabic, the -u-nu- extension or numberingSystem option, or resolving unsupported numbering systems and locales wrongly fails this."""
    body = r"""var n = 1234567.891;
['en-US', 'de-DE', 'fr-FR', 'es-ES', 'es-MX', 'it-IT', 'pt-BR', 'pt-PT', 'nl-NL', 'ja-JP', 'zh-CN', 'ko-KR', 'ru-RU', 'pl-PL', 'sv-SE', 'en-IN', 'hi-IN', 'ar-EG', 'ar', 'ar-MA', 'th-TH-u-nu-thai', 'zh-Hans-CN-u-nu-hanidec', 'tlh'].forEach(function (l) {
  show(l, function () { var f = new Intl.NumberFormat(l); var r = f.resolvedOptions(); return f.format(n) + ' | ' + f.format(-0.5) + ' | ' + r.locale + ' ' + r.numberingSystem; });
});
show('numberingSystem option', function () { return ['arab', 'arabext', 'beng', 'deva', 'fullwide', 'hanidec', 'tamldec', 'thai', 'mymr', 'latn'].map(function (ns) { return ns + '=' + nf({ numberingSystem: ns }).format(9876.5); }).join(' '); });
show('option vs extension', function () { return [['en-u-nu-arab', undefined], ['en-u-nu-arab', 'thai'], ['en-u-nu-arab', 'arab'], ['en-u-nu-bogus', undefined], ['ar-EG', 'latn'], ['ar-u-nu-latn', undefined], ['en', 'bogus']].map(function (p) { var f = new Intl.NumberFormat(p[0], { numberingSystem: p[1] }); var r = f.resolvedOptions(); return r.locale + '/' + r.numberingSystem + '=' + f.format(42); }).join(' '); });
show('locale fallback list', function () { return [['xx', 'de'], ['tlh-Latn', 'fr-CA'], ['zz'], []].map(function (l) { return new Intl.NumberFormat(l).resolvedOptions().locale; }).join(' '); });
"""
    check(js, golden, "number_format_locale_symbols_and_numbering_systems", body)


def test_number_format_currency_display_and_digits(js, golden):
    """CATCHES: currency formatting with the wrong ISO 4217 minor-unit digits, symbol vs narrowSymbol vs code forms, symbol placement for German/French/Polish, accounting parentheses, or case-insensitive currency codes not uppercased fails this."""
    body = r"""show('symbols en-US', function () { return ['USD', 'EUR', 'GBP', 'JPY', 'CNY', 'AUD', 'CAD', 'KWD', 'CHF', 'BHD'].map(function (c) { return nf({ style: 'currency', currency: c }).format(-1234.5); }).join(' | '); });
show('minor units', function () { return ['BHD', 'CLP', 'ISK', 'JPY', 'KRW', 'USD', 'TND', 'UGX', 'VND', 'KWD', 'OMR'].map(function (c) { return nf({ style: 'currency', currency: c, currencyDisplay: 'code' }).format(1.5); }).join(' | '); });
show('displays', function () { return ['symbol', 'narrowSymbol', 'code'].map(function (d) { return d + '=' + ['USD', 'EUR', 'GBP'].map(function (c) { return nf({ style: 'currency', currency: c, currencyDisplay: d }).format(2); }).join(','); }).join(' | '); });
show('de/fr EUR', function () { return ['de-DE', 'fr-FR'].map(function (l) { return l + '=' + new Intl.NumberFormat(l, { style: 'currency', currency: 'EUR' }).format(1234.5); }).join(' | '); });
show('de USD/JPY', function () { return ['USD', 'JPY', 'GBP'].map(function (c) { return new Intl.NumberFormat('de-DE', { style: 'currency', currency: c }).format(1234.5); }).join(' | '); });
show('accounting', function () { return [nf({ style: 'currency', currency: 'USD', currencySign: 'accounting' }).format(-5), nf({ style: 'currency', currency: 'USD', currencySign: 'accounting' }).format(5), new Intl.NumberFormat('de', { style: 'currency', currency: 'EUR', currencySign: 'accounting' }).format(-5), nf({ style: 'currency', currency: 'GBP', currencySign: 'accounting', signDisplay: 'always' }).format(-1), nf({ style: 'currency', currency: 'GBP', currencySign: 'accounting', signDisplay: 'always' }).format(1)].join(' | '); });
show('USD symbol per locale', function () { return ['zh-CN', 'ko', 'ja', 'en-US'].map(function (l) { return l + '=' + new Intl.NumberFormat(l, { style: 'currency', currency: 'USD' }).format(12.5); }).join(' | '); });
show('lowercase code', function () { var f = nf({ style: 'currency', currency: 'eur' }); return f.format(3) + ' ' + f.resolvedOptions().currency; });
show('digits override', function () { return [nf({ style: 'currency', currency: 'JPY', minimumFractionDigits: 2 }).format(5), nf({ style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(2.5), nf({ style: 'currency', currency: 'BHD', maximumSignificantDigits: 2 }).format(1.2345), nf({ style: 'currency', currency: 'USD', minimumFractionDigits: 0 }).format(7)].join(' | '); });
show('currency ignored for decimal', function () { var r = nf({ currency: 'USD' }).resolvedOptions(); return r.style + ' ' + r.currency + ' ' + nf({ currency: 'USD' }).format(1.5); });
"""
    check(js, golden, "number_format_currency_display_and_digits", body)


def test_number_format_percent_and_unit_styles(js, golden):
    """CATCHES: percent scaling, the NBSP before % in German/French, unit short/long/narrow patterns, singular-vs-plural long unit names, compound -per- units, or localized German/French/Japanese unit patterns that differ from CLDR fail this."""
    body = r"""show('percent', function () { return [nf({ style: 'percent' }).format(0.256), nf({ style: 'percent', maximumFractionDigits: 2 }).format(0.12345), nf({ style: 'percent' }).format(-1.5), nf({ style: 'percent', minimumFractionDigits: 1 }).format(0), new Intl.NumberFormat('de-DE', { style: 'percent', maximumFractionDigits: 1 }).format(0.2567), new Intl.NumberFormat('fr', { style: 'percent' }).format(0.75), new Intl.NumberFormat('ja', { style: 'percent' }).format(0.75)].join(' | '); });
['meter', 'kilometer', 'centimeter', 'liter', 'kilobyte', 'megabyte', 'gigabyte', 'celsius', 'percent', 'kilometer-per-hour', 'second', 'hour', 'day', 'foot', 'inch', 'kilogram', 'mile', 'byte'].forEach(function (u) {
  show(u, function () { return ['short', 'long', 'narrow'].map(function (d) { var f = nf({ style: 'unit', unit: u, unitDisplay: d }); return f.format(1) + '~' + f.format(-2.5) + '~' + f.format(1000); }).join(' / '); });
});
show('localized units', function () { return ['de', 'fr', 'ja'].map(function (l) { return l + ': ' + ['kilometer', 'liter', 'percent', 'kilometer-per-hour', 'celsius'].map(function (u) { return new Intl.NumberFormat(l, { style: 'unit', unit: u }).format(12.5) + '~' + new Intl.NumberFormat(l, { style: 'unit', unit: u, unitDisplay: 'long' }).format(1); }).join(' / '); }).join(' | '); });
show('unit resolvedOptions', function () { var r = nf({ style: 'unit', unit: 'meter-per-second', unitDisplay: 'long' }).resolvedOptions(); return r.style + ' ' + r.unit + ' ' + r.unitDisplay + ' ' + r.maximumFractionDigits; });
"""
    check(js, golden, "number_format_percent_and_unit_styles", body)


def test_number_format_compact_scientific_engineering(js, golden):
    """CATCHES: compact notation with the wrong tier thresholds (German starting at millions, CJK myriads, Korean thousands, Indian lakh/crore), the 2-significant-digit compact rounding, long compact words, or scientific/engineering mantissa and exponent placement fails this."""
    body = r"""var xs = [1, 15, 150, 1500, 15000, 150000, 1.5e6, 1.5e7, 1.5e8, 1.5e9, 1.5e12, -2.25e6, 0.5];
show('en short', function () { return xs.map(function (x) { return nf({ notation: 'compact' }).format(x); }).join(' '); });
show('en long', function () { return xs.map(function (x) { return nf({ notation: 'compact', compactDisplay: 'long' }).format(x); }).join(' | '); });
show('en sig3', function () { return [12345, 1234567, 999, 2.5e9, -98765].map(function (x) { return nf({ notation: 'compact', maximumSignificantDigits: 3 }).format(x); }).join(' '); });
['de', 'ja', 'zh', 'zh-TW', 'ko'].forEach(function (l) {
  show(l, function () { return xs.map(function (x) { return new Intl.NumberFormat(l, { notation: 'compact' }).format(x); }).join(' '); });
});
show('en-IN', function () { return [1500, 15000, 150000, 1.5e6, 1.5e7, -2.25e6].map(function (x) { return new Intl.NumberFormat('en-IN', { notation: 'compact' }).format(x); }).join(' '); });
show('de long', function () { return xs.map(function (x) { return new Intl.NumberFormat('de', { notation: 'compact', compactDisplay: 'long' }).format(x); }).join(' | '); });
show('scientific', function () { return [0, 1, 123456, 0.000123, -9.99e20, 1e100, 98765].map(function (x) { return nf({ notation: 'scientific' }).format(x); }).join(' '); });
show('engineering', function () { return [0, 1, 123456, 0.000123, -9.99e20, -1e-7, 1234].map(function (x) { return nf({ notation: 'engineering' }).format(x); }).join(' '); });
show('notation digits', function () { return [nf({ notation: 'scientific', maximumFractionDigits: 1 }).format(98765), nf({ notation: 'engineering', minimumFractionDigits: 2 }).format(0.0123), new Intl.NumberFormat('de', { notation: 'scientific' }).format(12345), nf({ notation: 'scientific', signDisplay: 'always' }).format(0.00042), nf({ notation: 'scientific' }).format(Infinity), nf({ notation: 'compact' }).format(-Infinity), nf({ notation: 'compact' }).format(NaN)].join(' | '); });
"""
    check(js, golden, "number_format_compact_scientific_engineering", body)


def test_number_format_sign_display_modes(js, golden):
    """CATCHES: signDisplay handling that shows or hides signs wrongly for negative zero, NaN, values that round to zero, percent/currency/scientific styles, or that keys exceptZero/negative off the unrounded value fails this."""
    body = r"""var vals = [-1, -0, 0, 1, NaN, Infinity, -0.0001, 0.0004];
['auto', 'always', 'never', 'exceptZero', 'negative'].forEach(function (s) {
  show(s, function () { return vals.map(function (x) { return nf({ signDisplay: s }).format(x); }).join(' , '); });
  show(s + ' currency', function () { return [-5, 0, -0, 5].map(function (x) { return nf({ style: 'currency', currency: 'USD', signDisplay: s }).format(x); }).join(' , '); });
  show(s + ' percent', function () { return [-0.123, 0, 0.5].map(function (x) { return nf({ style: 'percent', signDisplay: s }).format(x); }).join(' , '); });
});
show('accounting combos', function () { return [nf({ style: 'currency', currency: 'USD', signDisplay: 'exceptZero', currencySign: 'accounting' }).format(-0), nf({ style: 'currency', currency: 'USD', signDisplay: 'never', currencySign: 'accounting' }).format(-5), nf({ style: 'currency', currency: 'USD', signDisplay: 'negative' }).format(-0.001), nf({ style: 'currency', currency: 'USD', signDisplay: 'always' }).format(5)].join(' | '); });
"""
    check(js, golden, "number_format_sign_display_modes", body)


@pytest.mark.parametrize("tier", TIERS)
def test_number_format_rounding_modes_increments_and_priority(js, golden, tier):
    """CATCHES: the nine Intl rounding modes applied to the magnitude instead of the signed value, roundingIncrement scaling, significant-digit rounding, roundingPriority morePrecision/lessPrecision selection, trailingZeroDisplay, or minimumIntegerDigits padding implemented wrongly fails this."""
    body = r"""['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].forEach(function (m) {
  show(m, function () { var f = nf({ maximumFractionDigits: 0, roundingMode: m }); var g = nf({ maximumFractionDigits: 2, roundingMode: m }); return [2.5, -2.5, 1.5, -1.5, 1.4, -1.6, 0.5, -0.5].map(function (x) { return f.format(x); }).join(',') + ' / ' + [1.005, -1.005, 1.115, 2.675].map(function (x) { return g.format(x); }).join(','); });
});
show('increments', function () { return [1, 2, 5, 10, 20, 25, 50, 100, 250, 500, 1000, 2500, 5000].map(function (inc) { return inc + '=' + nf({ minimumFractionDigits: 2, maximumFractionDigits: 2, roundingIncrement: inc }).format(1.2345) + '/' + nf({ maximumFractionDigits: 0, roundingIncrement: inc }).format(1234.5); }).join(' '); });
show('increment with mode', function () { return [nf({ maximumFractionDigits: 1, minimumFractionDigits: 1, roundingIncrement: 5, roundingMode: 'floor' }).format(1.29), nf({ maximumFractionDigits: 1, minimumFractionDigits: 1, roundingIncrement: 5, roundingMode: 'ceil' }).format(-1.21), nf({ maximumFractionDigits: 0, roundingIncrement: 25, roundingMode: 'halfEven' }).format(37.5)].join(' | '); });
show('significant', function () { return [nf({ maximumSignificantDigits: 3 }).format(123456), nf({ minimumSignificantDigits: 5 }).format(1.5), nf({ maximumSignificantDigits: 2 }).format(0.000123456), nf({ minimumSignificantDigits: 2, maximumSignificantDigits: 4 }).format(9.99999), nf({ maximumSignificantDigits: 1 }).format(-0.95), nf({ maximumSignificantDigits: 3, roundingMode: 'trunc' }).format(98.76), nf({ minimumSignificantDigits: 3 }).format(0)].join(' | '); });
show('priority', function () { return ['auto', 'morePrecision', 'lessPrecision'].map(function (p) { return p + '=' + [[1.2345, 2, 2], [123.456, 1, 4], [0.00456, 3, 2], [98765.4, 0, 2]].map(function (a) { return nf({ maximumFractionDigits: a[1], maximumSignificantDigits: a[2], roundingPriority: p }).format(a[0]); }).join(','); }).join(' | '); });
show('integer/fraction digits', function () { return [nf({ minimumIntegerDigits: 5 }).format(42), nf({ minimumFractionDigits: 3 }).format(1), nf({ maximumFractionDigits: 0 }).format(0.5), nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(0.05), nf({ maximumFractionDigits: 20 }).format(0.1), nf({ minimumIntegerDigits: 3, minimumFractionDigits: 2 }).format(-1.5), nf({ minimumFractionDigits: 5 }).format(2.5), nf({ maximumFractionDigits: 1 }).format(0.96)].join(' | '); });
show('trailingZeroDisplay', function () { return [nf({ minimumFractionDigits: 2, trailingZeroDisplay: 'stripIfInteger' }).format(5), nf({ minimumFractionDigits: 2, trailingZeroDisplay: 'stripIfInteger' }).format(5.1), nf({ minimumFractionDigits: 2, trailingZeroDisplay: 'stripIfInteger' }).format(4.999), nf({ style: 'currency', currency: 'USD', trailingZeroDisplay: 'stripIfInteger' }).format(3), nf({ style: 'currency', currency: 'USD', trailingZeroDisplay: 'stripIfInteger' }).format(3.5)].join(' | '); });
show('hot loop', function () { var f = nf({ maximumFractionDigits: 1, roundingMode: 'halfEven' }); var acc = []; for (var k = 0; k < 40; k++) { acc.push(f.format(k / 20 - 1)); } return acc.join(','); });
"""
    check(js, golden, "number_format_rounding_modes_increments_and_priority", body, tier)


def test_number_format_grouping_exact_decimals_and_bigint(js, golden):
    """CATCHES: useGrouping values (min2/always/auto/booleans/strings) mishandled, Polish minimum-grouping-digits ignored, string inputs converted through Number instead of exact decimals, or BigInt values losing precision fails this."""
    body = r"""show('useGrouping', function () { return [true, false, 'always', 'auto', 'min2', 'true', 'false', undefined].map(function (g) { return String(g) + '=' + nf({ useGrouping: g }).format(12345) + '/' + nf({ useGrouping: g }).format(1234) + '/' + JSON.stringify(nf({ useGrouping: g }).resolvedOptions().useGrouping); }).join(' '); });
show('compact grouping default', function () { return nf({ notation: 'compact' }).resolvedOptions().useGrouping + ' ' + nf({ notation: 'compact', useGrouping: true }).resolvedOptions().useGrouping + ' ' + nf({ notation: 'compact', useGrouping: true }).format(12345678901234) + ' ' + nf({ notation: 'compact' }).format(12345678901234); });
show('exact strings', function () { var f = nf({ maximumFractionDigits: 20 }); return ['123456789012345678901234567890', '0.1000000000000000055511151231257827', '-1.5e-7', '1e21', '  42  ', '0x1F', '0b101', '', 'abc', '-0', '.5', '5.', '1_000', 'Infinity', '-Infinity', '9007199254740993', '1.00000000000000000001'].map(function (s) { return JSON.stringify(s) + '=' + f.format(s); }).join(' | '); });
show('exact rounding', function () { return [nf({ maximumFractionDigits: 2 }).format('1.005'), nf({ maximumFractionDigits: 2 }).format(1.005), nf({ maximumSignificantDigits: 3 }).format('123456789123456789'), nf({ minimumFractionDigits: 25 }).format('0.1')].join(' | '); });
show('bigint', function () { return [nf().format(12345678901234567890n), nf({ style: 'currency', currency: 'EUR' }).format(-5n), nf({ notation: 'compact' }).format(123456789n), new Intl.NumberFormat('de').format(10n ** 20n), nf({ maximumSignificantDigits: 2 }).format(987654321987654321n), new Intl.NumberFormat('en-IN').format(12345678901n), nf({ style: 'percent' }).format(3n), nf({ minimumFractionDigits: 2 }).format(-0n)].join(' | '); });
show('special', function () { var f = nf(); return [f.format(NaN), f.format(Infinity), f.format(-Infinity), f.format(-0), f.format(), f.format(null), f.format(true), f.format('1e3'), new Intl.NumberFormat('zh-TW').format(NaN), nf({ style: 'percent' }).format(Infinity), nf({ signDisplay: 'always' }).format(Infinity), f.format({ valueOf: function () { return 7; } })].join(' | '); });
show('symbol input', function () { return nf().format(Symbol('x')); });
show('large and tiny', function () { return [1e21, 1.7976931348623157e308, 5e-324, 123e-20].map(function (x) { return nf({ maximumFractionDigits: 3 }).format(x).length + ':' + nf({ maximumSignificantDigits: 3 }).format(x).slice(0, 12); }).join(' | '); });
"""
    check(js, golden, "number_format_grouping_exact_decimals_and_bigint", body)


def test_number_format_to_parts(js, golden):
    """CATCHES: formatToParts splitting that mislabels minusSign/plusSign, group/decimal/fraction, currency, percentSign, exponent, compact, unit, nan/infinity or localized literal parts, or whose joined values differ from format() fails this."""
    body = r"""var cases = [
  ['currency', nf({ style: 'currency', currency: 'USD' }), -1234567.891],
  ['currency de', new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }), 1234.5],
  ['accounting', nf({ style: 'currency', currency: 'USD', currencySign: 'accounting' }), -3],
  ['scientific', nf({ notation: 'scientific' }), -12345],
  ['engineering', nf({ notation: 'engineering' }), 0.000123],
  ['compact long', nf({ notation: 'compact', compactDisplay: 'long' }), 2500000],
  ['compact short', nf({ notation: 'compact' }), 1500],
  ['compact ja', new Intl.NumberFormat('ja', { notation: 'compact' }), 123456789],
  ['percent', nf({ style: 'percent', signDisplay: 'always' }), 0.5],
  ['unit', nf({ style: 'unit', unit: 'kilometer-per-hour' }), 88],
  ['unit long', nf({ style: 'unit', unit: 'liter', unitDisplay: 'long' }), 1],
  ['unit narrow', nf({ style: 'unit', unit: 'celsius', unitDisplay: 'narrow' }), -4],
  ['unit ja', new Intl.NumberFormat('ja', { style: 'unit', unit: 'kilometer-per-hour', unitDisplay: 'long' }), 60],
  ['nan', nf(), NaN],
  ['infinity', nf(), -Infinity],
  ['arab', new Intl.NumberFormat('ar-EG'), 1234.5],
  ['fr', new Intl.NumberFormat('fr'), 1234567.5],
  ['bigint', nf(), -123456789n],
  ['exact string', nf({ maximumFractionDigits: 10 }), '-0.0000001234']
];
cases.forEach(function (c) { show(c[0], function () { var p = c[1].formatToParts(c[2]); var joined = p.map(function (x) { return x.value; }).join(''); return parts(p) + (joined === c[1].format(c[2]) ? '' : ' MISMATCH'); }); });
"""
    check(js, golden, "number_format_to_parts", body)


def test_number_format_ranges(js, golden):
    """CATCHES: formatRange/formatRangeToParts that do not collapse equal endpoints into an approximately sign, mislabel startRange/endRange/shared sources, accept a missing or NaN endpoint, or format BigInt and mixed-type endpoints wrongly fails this."""
    body = r"""show('ranges', function () { return [nf().formatRange(3, 5), nf({ style: 'currency', currency: 'USD' }).formatRange(3, 5), nf({ style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).formatRange(2.9, 3.1), nf().formatRange(5, 3), nf().formatRange(1e3, 1e5), nf().formatRange(1n, 10n), nf().formatRange(0.5, '0.75'), nf({ maximumFractionDigits: 0 }).formatRange(1.2, 1.4), nf({ maximumSignificantDigits: 2 }).formatRange(1234, 5678)].join(' | '); });
show('pt range separator', function () { return new Intl.NumberFormat('pt-PT').formatRange(1, 2) + ' | ' + new Intl.NumberFormat('pt-BR').formatRange(10, 20); });
show('rangeToParts currency', function () { return parts(nf({ style: 'currency', currency: 'EUR' }).formatRangeToParts(3, 5)); });
show('rangeToParts equal', function () { return parts(nf().formatRangeToParts(1, 1)); });
show('rangeToParts grouped', function () { return parts(nf().formatRangeToParts(1000, 2500.5)); });
each('range errors', [function () { return nf().formatRange(1); }, function () { return nf().formatRange(NaN, 1); }, function () { return nf().formatRange(1, undefined); }, function () { return nf().formatRangeToParts(1, NaN); }, function () { return nf().formatRangeToParts(); }, function () { return Intl.NumberFormat.prototype.formatRange.call({}, 1, 2); }]);
"""
    check(js, golden, "number_format_ranges", body)


def test_number_format_exact_decimal_rounding_and_unit_fallbacks(js, golden):
    """CATCHES: exact-decimal string formatting that loses carries (9.999 to 10), mishandles significant-digit padding, integer padding or rounding modes on long digit strings, priority defaults without explicit significant digits, or compound/unknown units without CLDR patterns fails this."""
    body = r"""[[{ maximumSignificantDigits: 2 }, '9999'], [{ maximumSignificantDigits: 2 }, '9950'], [{ maximumFractionDigits: 2 }, '9.999'], [{ maximumFractionDigits: 2 }, '-0.995'], [{ roundingIncrement: 5, maximumFractionDigits: 2, minimumFractionDigits: 2 }, '1.234'], [{ roundingPriority: 'morePrecision', maximumSignificantDigits: 2 }, '1.234'], [{ maximumSignificantDigits: 2 }, '1.234'], [{ maximumSignificantDigits: 2, roundingMode: 'floor' }, '123456'], [{ minimumSignificantDigits: 8 }, '12345'], [{ minimumIntegerDigits: 8, maximumSignificantDigits: 3 }, '12345'], [{ maximumFractionDigits: 1, roundingMode: 'trunc' }, '1.99'], [{ maximumFractionDigits: 1 }, '9.96'], [{ maximumFractionDigits: 1, roundingMode: 'ceil' }, '1.21'], [{ minimumFractionDigits: 3 }, '1.5'], [{ minimumIntegerDigits: 4 }, '-12.5'], [{ maximumFractionDigits: 0, roundingMode: 'ceil' }, 0.001], [{ maximumFractionDigits: 0, roundingMode: 'expand' }, -0.001], [{ maximumFractionDigits: 0, roundingMode: 'floor' }, 0.001], [{ maximumFractionDigits: 1, roundingMode: 'halfEven' }, 0.04], [{ roundingPriority: 'lessPrecision', maximumFractionDigits: 1 }, 1.25], [{ roundingPriority: 'morePrecision', minimumFractionDigits: 2 }, 3], [{ maximumSignificantDigits: 2, roundingPriority: 'morePrecision' }, 0], [{ maximumSignificantDigits: 3 }, '0.000'], [{ minimumFractionDigits: 2 }, '00012.50'], [{}, '-0.0'], [{ maximumSignificantDigits: 21 }, '123456789012345678901234'], [{ style: 'percent', maximumFractionDigits: 1 }, '0.12345'], [{ notation: 'compact' }, '1234567890123'], [{ maximumFractionDigits: 3 }, '1e-10'], [{ maximumFractionDigits: 3 }, '-1E3'], [{ maximumFractionDigits: 0, roundingIncrement: 5, roundingMode: 'ceil' }, 0.001], [{ maximumFractionDigits: 0, roundingIncrement: 5, roundingMode: 'floor' }, -0.001], [{ maximumFractionDigits: 2, minimumFractionDigits: 2, roundingIncrement: 25, roundingMode: 'expand' }, 0.0001], [{ notation: 'scientific' }, 1e23], [{ notation: 'engineering' }, 1e23], [{ notation: 'scientific' }, 9.999999999999999e22]].forEach(function (c) {
  show(JSON.stringify(c[0]) + ' ' + JSON.stringify(c[1]), function () { return nf(c[0]).format(c[1]); });
});
show('compound long units', function () { return [nf({ style: 'unit', unit: 'megabyte-per-second', unitDisplay: 'long' }).format(1), nf({ style: 'unit', unit: 'megabyte-per-second', unitDisplay: 'long' }).format(2), nf({ style: 'unit', unit: 'liter-per-kilometer', unitDisplay: 'long' }).format(2.5), nf({ style: 'unit', unit: 'gigabit', unitDisplay: 'long' }).format(3)].join(' | '); });
show('unit parts fallback', function () { return parts(nf({ style: 'unit', unit: 'meter' }).formatToParts(Infinity)) + ' || ' + parts(nf({ style: 'unit', unit: 'megabyte-per-second', unitDisplay: 'long' }).formatToParts(-2)) + ' || ' + parts(new Intl.NumberFormat('ko', { style: 'unit', unit: 'kilometer-per-hour', unitDisplay: 'long' }).formatToParts(5)); });
show('cjk units', function () { return [new Intl.NumberFormat('zh-TW', { style: 'unit', unit: 'kilometer' }).format(5), new Intl.NumberFormat('zh-CN', { style: 'unit', unit: 'kilometer', unitDisplay: 'long' }).format(5), new Intl.NumberFormat('ko', { style: 'unit', unit: 'kilometer-per-hour' }).format(5), new Intl.NumberFormat('zh', { style: 'unit', unit: 'hour' }).format(2), new Intl.NumberFormat('ko', { style: 'unit', unit: 'kilometer', unitDisplay: 'long' }).format(1)].join(' | '); });
show('romance/germanic units', function () { return ['es', 'pt', 'it', 'nl'].map(function (l) { return l + '=' + new Intl.NumberFormat(l, { style: 'unit', unit: 'kilometer', unitDisplay: 'long' }).format(1) + '/' + new Intl.NumberFormat(l, { style: 'unit', unit: 'kilometer', unitDisplay: 'long' }).format(5) + '/' + new Intl.NumberFormat(l, { style: 'unit', unit: 'hour' }).format(2); }).join(' | '); });
"""
    check(js, golden, "number_format_exact_decimal_rounding_and_unit_fallbacks", body)


def test_number_format_option_validation_and_resolved_options(js, golden):
    """CATCHES: NumberFormat option validation that accepts invalid style/currency/unit/notation/rounding values, misses digit-range errors and the roundingIncrement constraints, or resolvedOptions that reports wrong keys, order or defaults fails this."""
    body = r"""[{ style: 'money' }, { style: 'currency' }, { currency: 'US' }, { currency: 'US$' }, { style: 'unit' }, { style: 'unit', unit: 'parsec' }, { style: 'unit', unit: 'meter-per-' }, { currencyDisplay: 'full' }, { currencySign: 'neg' }, { unitDisplay: 'wide' }, { notation: 'fancy' }, { compactDisplay: 'tiny' }, { signDisplay: 'sometimes' }, { roundingMode: 'up' }, { roundingPriority: 'most' }, { roundingIncrement: 3 }, { roundingIncrement: 2.5 }, { roundingIncrement: 5, maximumSignificantDigits: 2 }, { roundingIncrement: 5, minimumFractionDigits: 1, maximumFractionDigits: 2 }, { trailingZeroDisplay: 'never' }, { useGrouping: 'sometimes' }, { minimumIntegerDigits: 0 }, { minimumIntegerDigits: 22 }, { minimumFractionDigits: 101 }, { maximumFractionDigits: -1 }, { minimumFractionDigits: 3, maximumFractionDigits: 1 }, { minimumSignificantDigits: 0 }, { maximumSignificantDigits: 22 }, { minimumSignificantDigits: 5, maximumSignificantDigits: 2 }, { minimumFractionDigits: NaN }, { numberingSystem: 'latn!' }, { localeMatcher: 'best' }].forEach(function (o) {
  var label = JSON.stringify(o, function (k, v) { return typeof v === 'number' && isNaN(v) ? 'NaN' : v; });
  show(label, function () { return nf(o).format(1); });
});
show('null options', function () { return new Intl.NumberFormat('en', null); });
show('primitive options', function () { return new Intl.NumberFormat('en', 5).format(1.23456); });
show('bad locale', function () { return new Intl.NumberFormat('en_US'); });
show('resolved currency', function () { return JSON.stringify(nf({ style: 'currency', currency: 'jpy', currencyDisplay: 'name', currencySign: 'accounting' }).resolvedOptions()); });
show('resolved unit compact', function () { return JSON.stringify(new Intl.NumberFormat('de-CH', { style: 'unit', unit: 'liter', unitDisplay: 'long', notation: 'compact', compactDisplay: 'long' }).resolvedOptions()); });
show('resolved priority', function () { return JSON.stringify(new Intl.NumberFormat('ar-u-nu-latn', { maximumSignificantDigits: 3, roundingPriority: 'lessPrecision', roundingMode: 'floor' }).resolvedOptions()); });
show('resolved increment', function () { return JSON.stringify(new Intl.NumberFormat('hi-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2, roundingIncrement: 50, signDisplay: 'negative', useGrouping: false }).resolvedOptions()); });
show('resolved defaults', function () { return JSON.stringify(nf({ style: 'percent', notation: 'scientific' }).resolvedOptions()); });
"""
    check(js, golden, "number_format_option_validation_and_resolved_options", body)


def test_number_and_bigint_to_locale_string(js, golden):
    """CATCHES: Number.prototype.toLocaleString or BigInt.prototype.toLocaleString that ignore the locales/options arguments, skip option validation, or accept foreign receivers instead of throwing TypeError fails this."""
    body = r"""show('number', function () { return [(1234.5).toLocaleString('de-DE'), (1234.5).toLocaleString(), (0.75).toLocaleString('fr', { style: 'percent' }), (1e9).toLocaleString('ja', { notation: 'compact' }), (-12.5).toLocaleString(undefined, { minimumFractionDigits: 2 }), (12).toLocaleString('ar-EG'), Number.prototype.toLocaleString.call(5, 'zh-Hans-CN-u-nu-hanidec'), (123.456).toLocaleString('en', { maximumSignificantDigits: 2 }), (5).toLocaleString(['xx', 'de'], { style: 'currency', currency: 'EUR' }), new Number(98765.4321).toLocaleString('en-IN'), NaN.toLocaleString('de'), (-Infinity).toLocaleString('en')].join(' | '); });
show('bigint', function () { return [(12345n).toLocaleString('en-IN'), (-7n).toLocaleString('en', { signDisplay: 'exceptZero' }), (10n ** 25n).toLocaleString('fr'), (99n).toLocaleString('ar'), Object(5n).toLocaleString('de', { minimumIntegerDigits: 4 }), (0n).toLocaleString('en', { style: 'unit', unit: 'byte', unitDisplay: 'long' })].join(' | '); });
each('errors', [function () { return (1).toLocaleString('en', { style: 'currency' }); }, function () { return (1).toLocaleString('!!'); }, function () { return Number.prototype.toLocaleString.call('x'); }, function () { return (1n).toLocaleString('en', { maximumFractionDigits: 200 }); }, function () { return BigInt.prototype.toLocaleString.call(1); }, function () { return (1).toLocaleString('en', null); }]);
show('array join', function () { return [1234.5, 6789n, -0.5].toLocaleString('de-DE', { maximumFractionDigits: 0 }); });
"""
    check(js, golden, "number_and_bigint_to_locale_string", body)


# ------------------------------------------------------------------------- Intl.DateTimeFormat


def test_date_time_format_styles_and_numeric_patterns(js, golden):
    """CATCHES: dateStyle/timeStyle presets that pick the wrong fields or widths, combined date+time joining, or locale numeric date patterns (day-month order and separators for German, French, Dutch, Japanese, Swedish, Arabic digits) that differ from CLDR fail this."""
    body = r"""var t = Date.UTC(2024, 11, 25, 15, 4, 5, 678);
['full', 'long', 'medium', 'short'].forEach(function (s) {
  show('dateStyle ' + s, function () { return new Intl.DateTimeFormat('en-US', { dateStyle: s, timeZone: 'UTC' }).format(t); });
  show('timeStyle ' + s, function () { return new Intl.DateTimeFormat('en-US', { timeStyle: s, timeZone: 'UTC' }).format(t); });
});
show('combined', function () { return [['medium', 'short'], ['medium', 'medium'], ['short', 'long'], ['short', 'full']].map(function (p) { return new Intl.DateTimeFormat('en-US', { dateStyle: p[0], timeStyle: p[1], timeZone: 'Asia/Tokyo' }).format(t); }).join(' | '); });
show('numeric default', function () { return ['en-US', 'de-DE', 'fr-FR', 'es', 'it', 'pt-BR', 'nl', 'ja', 'zh-CN', 'ko', 'ru', 'pl', 'sv', 'ar-EG'].map(function (l) { return l + '=' + new Intl.DateTimeFormat(l, { timeZone: 'UTC' }).format(t); }).join(' | '); });
show('2-digit fields', function () { return ['en-US', 'de', 'ja'].map(function (l) { return new Intl.DateTimeFormat(l, { year: '2-digit', month: '2-digit', day: '2-digit', timeZone: 'UTC' }).format(Date.UTC(2009, 0, 5)); }).join(' | '); });
show('short styles across locales', function () { return ['de', 'ru'].map(function (l) { return new Intl.DateTimeFormat(l, { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }).format(t); }).join(' | '); });
show('resolved styles', function () { return JSON.stringify(new Intl.DateTimeFormat('en-US', { dateStyle: 'long', timeStyle: 'medium', timeZone: 'UTC' }).resolvedOptions()); });
"""
    check(js, golden, "date_time_format_styles_and_numeric_patterns", body)


def test_date_time_format_components_eras_and_day_periods(js, golden):
    """CATCHES: explicit DateTimeFormat components rendered in the wrong order or width (weekday, era, month names, 2-digit hour), BCE era years not converted, fractionalSecondDigits truncation, flexible dayPeriod words, or UTC/offset time-zone names wrong fails this."""
    body = r"""var t = Date.UTC(2024, 11, 25, 15, 4, 5, 678);
function f(o, x) { o.timeZone = o.timeZone || 'UTC'; return new Intl.DateTimeFormat('en-US', o).format(x === undefined ? t : x); }
show('all components', function () { return f({ weekday: 'long', era: 'short', year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3, timeZoneName: 'short' }); });
show('weekdays', function () { return [0, 1, 2, 3, 4, 5, 6].map(function (k) { return f({ weekday: 'long', month: 'long', day: 'numeric' }, Date.UTC(2024, 0, 7 + k)) + '/' + f({ weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric' }, Date.UTC(2024, 0, 7 + k)); }).join(' | '); });
show('months', function () { return ['long', 'short', 'numeric', '2-digit'].map(function (w) { return w + '=' + [0, 4, 8, 11].map(function (m) { return f({ month: w }, Date.UTC(2024, m, 1)); }).join(','); }).join(' | '); });
show('month day', function () { return f({ month: 'long', day: 'numeric' }) + ' | ' + f({ year: 'numeric' }) + ' | ' + f({ day: 'numeric' }) + ' | ' + f({ weekday: 'short', month: 'numeric', day: 'numeric' }); });
show('bce eras', function () { var bc = Date.UTC(-44, 2, 15, 9, 0, 0); return [f({ era: 'long', year: 'numeric', month: 'long', day: 'numeric' }, bc), f({ era: 'short', year: 'numeric' }, bc), f({ era: 'narrow', year: 'numeric' }, bc), f({ era: 'long', year: 'numeric' }, -62135596800000), f({ era: 'short' }, new Date(0).setUTCFullYear(0, 5, 1)), f({ era: 'short', year: '2-digit' }, new Date(0).setUTCFullYear(-1234, 0, 1))].join(' | '); });
show('fractional seconds', function () { return [1, 2, 3].map(function (n) { return f({ minute: '2-digit', second: '2-digit', fractionalSecondDigits: n }); }).join(' | ') + ' | ' + f({ hour: 'numeric', minute: 'numeric', second: 'numeric', fractionalSecondDigits: 1 }, -1); });
show('dayPeriod', function () { return [6, 9, 12, 15, 19, 22].map(function (h) { return ['narrow', 'short', 'long'].map(function (w) { return f({ hour: 'numeric', dayPeriod: w }, Date.UTC(2024, 0, 1, h)); }).join('/'); }).join(' | ') + ' | alone=' + f({ dayPeriod: 'long' }); });
show('timeZoneName UTC', function () { return ['short', 'long', 'longOffset'].map(function (s) { return s + '=' + f({ hour: 'numeric', timeZoneName: s }); }).join(' | '); });
show('timeZoneName offsets', function () { return ['short', 'shortOffset', 'shortGeneric'].map(function (s) { return s + '=' + ['+05:30', '-08:00', '+00:00', '-0330'].map(function (z) { return f({ hour: 'numeric', minute: '2-digit', timeZoneName: s, timeZone: z }); }).join(','); }).join(' | '); });
show('short zone names', function () { return ['Asia/Kolkata', 'America/St_Johns', 'Asia/Tokyo'].map(function (z) { return f({ hour: 'numeric', timeZoneName: 'short', timeZone: z }, Date.UTC(2024, 0, 15, 12)); }).join(' | '); });
show('fractional digits alone', function () { return [1, 2, 3].map(function (n) { return f({ fractionalSecondDigits: n }); }).join(' '); });
show('long zone names', function () { return ['America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Kolkata'].map(function (z) { return f({ timeZoneName: 'long', timeZone: z }, Date.UTC(2024, 0, 15, 12)); }).join(' | '); });
show('era only', function () { return JSON.stringify(new Intl.DateTimeFormat('en-US', { era: 'long', timeZone: 'UTC' }).resolvedOptions()) + ' ' + f({ era: 'long' }); });
"""
    check(js, golden, "date_time_format_components_eras_and_day_periods", body)


def test_date_time_format_hour_cycles_and_time_zones(js, golden):
    """CATCHES: hourCycle h11/h12/h23/h24 display ranges, hour12 overriding hourCycle (h11 for Japanese), the -u-hc- extension, half-hour and 45-minute zone offsets, or DST transitions in America/New_York applied at the wrong instant fails this."""
    body = r"""show('hourCycle', function () { return ['h11', 'h12', 'h23', 'h24'].map(function (h) { return h + '=' + [0, 5, 12, 23].map(function (hh) { return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: 'numeric', hourCycle: h, timeZone: 'UTC' }).format(Date.UTC(2024, 0, 1, hh, 5)); }).join(','); }).join(' | '); });
show('hour12', function () { return [true, false].map(function (h) { return ['en-US', 'de'].map(function (l) { var f = new Intl.DateTimeFormat(l, { hour: 'numeric', minute: 'numeric', hour12: h, timeZone: 'UTC' }); var r = f.resolvedOptions(); return l + ':' + f.format(Date.UTC(2024, 0, 1, 0, 7)) + '/' + r.hourCycle + '/' + r.hour12; }).join(',') + ',ja:' + new Intl.DateTimeFormat('ja', { hour: 'numeric', hour12: h }).resolvedOptions().hourCycle; }).join(' | '); });
show('hour12 beats hourCycle', function () { var f = new Intl.DateTimeFormat('en-US', { hour: 'numeric', hourCycle: 'h23', hour12: true, timeZone: 'UTC' }); return f.format(Date.UTC(2024, 0, 1, 13)) + ' ' + f.resolvedOptions().hourCycle; });
show('hc extension', function () { return ['en-US-u-hc-h23', 'de-u-hc-h12', 'en-u-hc-h11', 'de-u-hc-h24'].map(function (l) { var f = new Intl.DateTimeFormat(l, { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }); var r = f.resolvedOptions(); return r.locale + '/' + r.hourCycle + '=' + f.format(Date.UTC(2024, 0, 1, 12, 30)); }).join(' | ') + ' | override=' + new Intl.DateTimeFormat('en-u-hc-h23', { hour: 'numeric', hourCycle: 'h12', timeZone: 'UTC' }).resolvedOptions().locale; });
show('hc extension vs hour12', function () { var r = new Intl.DateTimeFormat('en-u-hc-h23', { hour: 'numeric', hour12: true, timeZone: 'UTC' }).resolvedOptions(); return r.locale + ' ' + r.hourCycle; });
show('no hour, no hourCycle', function () { var r = new Intl.DateTimeFormat('en-US', { hourCycle: 'h23', year: 'numeric' }).resolvedOptions(); return [r.hourCycle, r.hour12, r.year].join(','); });
var t = Date.UTC(2024, 11, 25, 15, 4, 5);
show('zones', function () { return ['UTC', 'Asia/Kolkata', 'America/St_Johns', 'Pacific/Chatham', 'Asia/Kathmandu', 'Australia/Adelaide', 'Pacific/Kiritimati', 'America/Sao_Paulo', '-0330', '+14', '-00:00'].map(function (z) { return z + '=' + new Intl.DateTimeFormat('en-US', { dateStyle: 'short', timeStyle: 'short', timeZone: z }).format(t); }).join(' | '); });
show('zone ids', function () { return ['utc', 'asia/kolkata', 'Asia/Calcutta', 'America/Indiana/Indianapolis', '+05', '-0000', '+1234'].map(function (z) { return new Intl.DateTimeFormat('en', { timeZone: z }).resolvedOptions().timeZone; }).join(' '); });
show('dst spring', function () { var f = new Intl.DateTimeFormat('en-US', { dateStyle: 'short', timeStyle: 'medium', timeZone: 'America/New_York' }); return [Date.UTC(2024, 2, 10, 6, 59, 59), Date.UTC(2024, 2, 10, 7, 0, 0)].map(function (x) { return f.format(x); }).join(' | '); });
show('dst fall', function () { var f = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' }); return [Date.UTC(2024, 10, 3, 4, 30), Date.UTC(2024, 10, 3, 5, 30), Date.UTC(2024, 10, 3, 6, 30), Date.UTC(2024, 10, 3, 7, 30)].map(function (x) { return f.format(x); }).join(' | '); });
show('southern dst', function () { var f = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', hour: 'numeric', timeZone: 'Australia/Sydney' }); return [Date.UTC(2024, 0, 15, 0), Date.UTC(2024, 6, 15, 0)].map(function (x) { return f.format(x); }).join(' | '); });
show('historic offsets', function () { var f = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'Europe/Amsterdam' }); return [Date.UTC(1950, 5, 1, 12), Date.UTC(1977, 5, 1, 12), Date.UTC(1977, 11, 1, 12)].map(function (x) { return f.format(x); }).join(' | '); });
"""
    check(js, golden, "date_time_format_hour_cycles_and_time_zones", body)


def test_date_time_format_to_parts_and_ranges(js, golden):
    """CATCHES: DateTimeFormat formatToParts with mislabeled parts or untranslated digits, formatRange that fails to share fields coarser than the differing one, formatRangeToParts with wrong source tags, or range argument validation that is too lax fails this."""
    body = r"""var t = Date.UTC(2024, 11, 25, 15, 4, 5, 678);
show('parts full', function () { return parts(new Intl.DateTimeFormat('en-US', { dateStyle: 'full', timeStyle: 'long', timeZone: 'UTC' }).formatToParts(t)); });
show('parts arab', function () { return parts(new Intl.DateTimeFormat('ar-EG', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 2, timeZone: 'UTC' }).formatToParts(t)); });
show('parts dayPeriod', function () { return parts(new Intl.DateTimeFormat('en-US', { hour: 'numeric', dayPeriod: 'short', timeZone: 'UTC' }).formatToParts(t)); });
show('parts era', function () { return parts(new Intl.DateTimeFormat('en-US', { era: 'short', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }).formatToParts(Date.UTC(-100, 0, 1))); });
show('parts default', function () { return parts(new Intl.DateTimeFormat('en-US', { timeZone: 'UTC' }).formatToParts(0)) + ' / ' + parts(new Intl.DateTimeFormat('de', { timeZone: 'UTC' }).formatToParts(0)); });
show('range same day', function () { var f = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }); return f.formatRange(Date.UTC(2024, 11, 25, 9), t) + ' | ' + f.formatRange(t, t); });
show('range named month', function () { var f = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }); return [f.formatRange(t, t + 86400000 * 3), f.formatRange(Date.UTC(2024, 0, 10), Date.UTC(2024, 2, 5)), f.formatRange(Date.UTC(2023, 11, 30), Date.UTC(2024, 0, 2))].join(' | '); });
show('range date and time differ', function () { return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).formatRange(t, t + 86400000 * 3 + 3600000); });
show('rangeToParts date and time differ', function () { return parts(new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).formatRangeToParts(t, t + 86400000 * 3 + 3600000)); });
show('rangeToParts shared suffix', function () { return parts(new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }).formatRangeToParts(t, t + 86400000 * 3)); });
show('range numeric', function () { return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC' }).formatRange(t, t + 86400000 * 3); });
show('range time', function () { var f = new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: 'numeric', timeZone: 'UTC' }); return f.formatRange(Date.UTC(2024, 0, 1, 9), Date.UTC(2024, 0, 1, 17)) + ' | ' + f.formatRange(Date.UTC(2024, 0, 1, 11, 59), Date.UTC(2024, 0, 1, 12, 1)); });
show('range Date objects', function () { return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).formatRange(new Date(t), new Date(t + 86400000 * 9)); });
show('rangeToParts days', function () { return parts(new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).formatRangeToParts(t, t + 86400000 * 2)); });
show('rangeToParts equal', function () { return parts(new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' }).formatRangeToParts(t, t)); });
show('rangeToParts time', function () { return parts(new Intl.DateTimeFormat('en-US', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }).formatRangeToParts(Date.UTC(2024, 11, 25, 9), t)); });
each('range errors', [function () { var f = new Intl.DateTimeFormat('en-US'); return f.formatRange(t); }, function () { return new Intl.DateTimeFormat('en-US').formatRange(t, NaN); }, function () { return new Intl.DateTimeFormat('en-US').formatRange(undefined, t); }, function () { return new Intl.DateTimeFormat('en-US').formatRange(Temporal.PlainDate.from('2024-01-01'), t); }, function () { return new Intl.DateTimeFormat('en-US').formatRange(Temporal.PlainDate.from('2024-01-01'), Temporal.PlainDate.from('2024-01-05').withCalendar('gregory')); }, function () { return new Intl.DateTimeFormat('en-US').formatRange(8.64e15 + 1, 0); }, function () { return new Intl.DateTimeFormat('en-US').formatRangeToParts(0); }, function () { return Intl.DateTimeFormat.prototype.formatRange.call({}, 0, 1); }]);
"""
    check(js, golden, "date_time_format_to_parts_and_ranges", body)


def test_date_time_format_calendars_and_numbering_systems(js, golden):
    """CATCHES: DateTimeFormat calendar conversion (Buddhist, Japanese eras, ROC, Hebrew, Islamic, Persian, Indian, Coptic, Ethiopic, Chinese/Dangi related years and leap months) or numbering-system digit substitution and -u-ca-/-u-nu- resolution that deviate from CLDR fail this."""
    body = r"""var t = Date.UTC(2024, 11, 25, 15, 4, 5);
function fields(fmt, x) { return fmt.formatToParts(x).filter(function (p) { return p.type !== 'literal'; }).map(function (p) { return p.type + '=' + p.value; }).join(' '); }
['buddhist', 'japanese', 'roc', 'hebrew', 'islamic-civil', 'islamic-umalqura', 'islamic-tbla', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'chinese', 'dangi', 'iso8601', 'gregory', 'islamic', 'islamicc'].forEach(function (c) {
  show(c, function () { var b = new Intl.DateTimeFormat('en-US', { calendar: c, year: 'numeric', month: 'long', day: 'numeric', era: 'short', timeZone: 'UTC' }); var n = new Intl.DateTimeFormat('en-US', { calendar: c, year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' }); return fields(b, t) + ' / ' + fields(n, t) + ' / ' + b.resolvedOptions().calendar; });
});
show('gregorian default', function () { return new Intl.DateTimeFormat('en-US', { calendar: 'iso8601', timeZone: 'UTC' }).format(t) + ' ' + new Intl.DateTimeFormat('en-US', { calendar: 'gregory', era: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(t); });
show('japanese eras', function () { var f = new Intl.DateTimeFormat('en-US', { calendar: 'japanese', era: 'long', year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' }); return [Date.UTC(2019, 3, 30), Date.UTC(2019, 4, 1), Date.UTC(1989, 0, 7), Date.UTC(1989, 0, 8), Date.UTC(1926, 11, 25), Date.UTC(1912, 6, 30), Date.UTC(1900, 0, 1)].map(function (x) { return fields(f, x); }).join(' | '); });
show('chinese leap month', function () { var f = new Intl.DateTimeFormat('en-US', { calendar: 'chinese', year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' }); return [Date.UTC(2023, 2, 21), Date.UTC(2023, 2, 22), Date.UTC(2023, 3, 19), Date.UTC(2023, 3, 20), Date.UTC(2024, 1, 10)].map(function (x) { return fields(f, x); }).join(' | '); });
show('dangi leap month', function () { var f = new Intl.DateTimeFormat('en-US', { calendar: 'dangi', month: 'numeric', day: 'numeric', timeZone: 'UTC' }); return [Date.UTC(2020, 4, 23), Date.UTC(2020, 5, 21)].map(function (x) { return fields(f, x); }).join(' | '); });
show('chinese zh fields', function () { return fields(new Intl.DateTimeFormat('zh-CN', { calendar: 'chinese', year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' }), t); });
show('hebrew months', function () { var f = new Intl.DateTimeFormat('en-US', { calendar: 'hebrew', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }); return [Date.UTC(2024, 1, 15), Date.UTC(2024, 3, 15), Date.UTC(2023, 2, 15), Date.UTC(2023, 8, 16), Date.UTC(2024, 9, 3)].map(function (x) { return fields(f, x); }).join(' | '); });
show('ca extension', function () { return ['en-u-ca-buddhist', 'th-u-ca-buddhist', 'en-u-ca-ethiopic-amete-alem', 'en-u-ca-bogus'].map(function (l) { var r = new Intl.DateTimeFormat(l, { timeZone: 'UTC' }).resolvedOptions(); return r.locale + '/' + r.calendar; }).join(' | ') + ' | override=' + new Intl.DateTimeFormat('en-u-ca-buddhist', { calendar: 'gregory' }).resolvedOptions().locale + ' | same=' + new Intl.DateTimeFormat('en-u-ca-buddhist', { calendar: 'buddhist' }).resolvedOptions().locale + ' | unsupported option=' + new Intl.DateTimeFormat('en', { calendar: 'bangla' }).resolvedOptions().calendar; });
show('numbering systems', function () { return ['arab', 'arabext', 'deva', 'beng', 'thai', 'hanidec', 'fullwide', 'tamldec', 'latn', 'mymr', 'khmr'].map(function (n) { return new Intl.DateTimeFormat('en-US', { numberingSystem: n, dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }).format(t); }).join(' | '); });
show('resolved combined', function () { return JSON.stringify(new Intl.DateTimeFormat('en-US-u-ca-buddhist-nu-thai-hc-h23', { timeZone: 'asia/kolkata', hour: 'numeric', minute: '2-digit' }).resolvedOptions()); });
show('resolved islamic', function () { return JSON.stringify(new Intl.DateTimeFormat('de', { calendar: 'islamic', numberingSystem: 'arab', hour12: true, dateStyle: 'long', timeStyle: 'short', timeZone: '+0530' }).resolvedOptions()); });
show('resolved fallback', function () { return JSON.stringify(new Intl.DateTimeFormat(['xx', 'ja-JP-u-ca-japanese'], { era: 'short', timeZone: 'UTC' }).resolvedOptions()); });
show('arab fraction separator', function () { return new Intl.DateTimeFormat('en-u-nu-arab', { second: '2-digit', fractionalSecondDigits: 2, timeZone: 'UTC' }).format(t + 456); });
"""
    check(js, golden, "date_time_format_calendars_and_numbering_systems", body)


def test_date_time_format_validation_and_legacy_behaviour(js, golden):
    """CATCHES: DateTimeFormat constructors that accept invalid time zones, calendars, numbering systems, enum options or fractionalSecondDigits, allow dateStyle with explicit components, skip TimeClip, rebind format per access, or break the legacy callable-constructor chain fail this."""
    body = r"""var t = Date.UTC(2024, 11, 25, 15, 4, 5, 678);
[{ timeZone: 'Mars/Base' }, { timeZone: '+5' }, { timeZone: '+25:00' }, { timeZone: '+05:3' }, { timeZone: '+05:60' }, { timeZone: '05:00' }, { calendar: 'x' }, { calendar: 'gregory!' }, { numberingSystem: 'a_b' }, { hourCycle: 'h25' }, { weekday: 'tiny' }, { era: 'wide' }, { month: 'full' }, { year: 'four' }, { hour: 'long' }, { dayPeriod: 'numeric' }, { fractionalSecondDigits: 0 }, { fractionalSecondDigits: 4 }, { fractionalSecondDigits: NaN }, { dateStyle: 'short', hour: 'numeric' }, { timeStyle: 'short', timeZoneName: 'short' }, { timeStyle: 'huge' }, { localeMatcher: 'fast' }, { formatMatcher: 'x' }, { timeZoneName: 'medium' }].forEach(function (o) {
  var label = JSON.stringify(o, function (k, v) { return typeof v === 'number' && isNaN(v) ? 'NaN' : v; });
  show(label, function () { return new Intl.DateTimeFormat('en', o).format(t); });
});
show('fractionalSecondDigits floor', function () { return new Intl.DateTimeFormat('en', { second: 'numeric', fractionalSecondDigits: 2.9, timeZone: 'UTC' }).resolvedOptions().fractionalSecondDigits; });
show('bad locale', function () { return new Intl.DateTimeFormat('en_US'); });
show('null options', function () { return new Intl.DateTimeFormat('en', null); });
each('format values', [function () { return new Intl.DateTimeFormat('en').format(NaN); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).format(new Date(t)); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).format(-1); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).format(-0.9); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).format(8.64e15); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).format(8.64e15 + 1); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).format('86400000'); }, function () { return new Intl.DateTimeFormat('en', { timeZone: 'UTC', year: 'numeric' }).format(Date.UTC(275760, 8, 13)); }]);
show('bound format', function () { var d = new Intl.DateTimeFormat('en', { timeZone: 'UTC' }); var f = d.format; return [t, 0].map(f).join(' ') + ' ' + (f === d.format) + ' ' + (f === new Intl.DateTimeFormat('en').format) + ' ' + f.length + ' ' + JSON.stringify(f.name); });
show('callable', function () { return Intl.DateTimeFormat('en', { timeZone: 'UTC', month: 'long' }).format(t) + ' ' + Object.prototype.toString.call(Intl.DateTimeFormat()); });
show('legacy chain', function () { var o = Object.create(Intl.DateTimeFormat.prototype); var r = Intl.DateTimeFormat.call(o, 'en', { timeZone: 'UTC', year: 'numeric' }); return (r === o) + ' ' + Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, 'format').get.call(o)(0) + ' ' + Intl.DateTimeFormat.prototype.resolvedOptions.call(o).year + ' ' + Object.getOwnPropertySymbols(o).length; });
show('legacy chain formatToParts', function () { var o = Object.create(Intl.DateTimeFormat.prototype); Intl.DateTimeFormat.call(o, 'en'); return Intl.DateTimeFormat.prototype.formatToParts.call(o, 0); });
each('brand checks', [function () { return Intl.DateTimeFormat.prototype.formatToParts.call({}, 0); }, function () { return Intl.DateTimeFormat.prototype.resolvedOptions.call(new Intl.NumberFormat()); }, function () { return Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, 'format').get.call(5); }]);
show('supportedLocalesOf', function () { return Intl.DateTimeFormat.supportedLocalesOf(['en-US', 'de', 'tlh', 'zh-Hant-TW', 'fa', 'ja-u-ca-japanese']).join(','); });
show('supportedLocalesOf matcher', function () { return Intl.DateTimeFormat.supportedLocalesOf('fr', { localeMatcher: 'lookup' }).join(',') + ' ' + (function () { try { return Intl.DateTimeFormat.supportedLocalesOf('fr', { localeMatcher: 'other' }); } catch (e) { return e.name + ': ' + e.message; } })(); });
"""
    check(js, golden, "date_time_format_validation_and_legacy_behaviour", body)


def test_date_time_format_with_temporal_values(js, golden):
    """CATCHES: DateTimeFormat.format/formatToParts/formatRange on Temporal objects that ignore the value's own type (date-only, time-only, year-month, month-day), apply the formatter's time zone to wall-clock values, skip calendar-mismatch or overlap checks, or accept ZonedDateTime fails this."""
    body = r"""var f = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Tokyo' });
show('defaults', function () { return [Temporal.PlainDate.from('2024-07-04'), Temporal.PlainTime.from('13:45:30'), Temporal.PlainDateTime.from('2024-07-04T13:45:30'), Temporal.Instant.from('2024-07-04T13:45:30Z')].map(function (x) { return f.format(x); }).join(' | '); });
show('year-month/month-day', function () { var g = new Intl.DateTimeFormat('en-US', { calendar: 'iso8601' }); return g.format(Temporal.PlainYearMonth.from('2024-07')) + ' | ' + g.format(Temporal.PlainMonthDay.from('07-04')); });
show('styles', function () { var s = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }); return [Temporal.PlainDate.from('2024-07-04'), Temporal.PlainTime.from('09:05'), Temporal.PlainDateTime.from('2024-07-04T21:30')].map(function (x) { return s.format(x); }).join(' | '); });
show('components filtered', function () { var c = new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }); return [Temporal.PlainDate.from('2024-07-04'), Temporal.PlainTime.from('09:05'), Temporal.PlainDateTime.from('2024-07-04T21:30')].map(function (x) { return c.format(x); }).join(' | '); });
show('parts', function () { return parts(new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).formatToParts(Temporal.PlainTime.from('09:05'))); });
show('gregory calendar date', function () { return new Intl.DateTimeFormat('en-US', { calendar: 'gregory', dateStyle: 'medium' }).format(Temporal.PlainDate.from('2024-07-04[u-ca=gregory]')) + ' | ' + new Intl.DateTimeFormat('en-US', { calendar: 'gregory', month: 'long', day: 'numeric' }).format(Temporal.PlainMonthDay.from({ calendar: 'gregory', monthCode: 'M12', day: 25 })); });
show('range', function () { var r = new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric' }); return r.formatRange(Temporal.PlainDate.from('2024-07-04'), Temporal.PlainDate.from('2024-07-09')) + ' | ' + new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).formatRange(Temporal.PlainTime.from('09:00'), Temporal.PlainTime.from('17:30')); });
show('rangeToParts', function () { return parts(new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).formatRangeToParts(Temporal.PlainDate.from('2024-07-04'), Temporal.PlainDate.from('2024-07-04'))); });
show('instant range', function () { return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tokyo' }).formatRange(Temporal.Instant.from('2024-07-04T00:00Z'), Temporal.Instant.from('2024-07-04T05:30Z')); });
show('zoned range', function () { return new Intl.DateTimeFormat('en-US').formatRange(Temporal.ZonedDateTime.from('2024-07-04T00:00[UTC]'), Temporal.ZonedDateTime.from('2024-07-05T00:00[UTC]')); });
show('year-month/month-day ranges', function () { return new Intl.DateTimeFormat('en-US', { calendar: 'iso8601', year: 'numeric', month: 'numeric' }).formatRange(Temporal.PlainYearMonth.from('2024-03'), Temporal.PlainYearMonth.from('2024-07')) + ' | ' + new Intl.DateTimeFormat('en-US', { calendar: 'iso8601', month: 'long', day: 'numeric' }).formatRange(Temporal.PlainMonthDay.from('03-01'), Temporal.PlainMonthDay.from('03-09')); });
each('errors', [function () { return new Intl.DateTimeFormat('en-US').format(Temporal.PlainYearMonth.from('2024-07')); }, function () { return new Intl.DateTimeFormat('en-US').format(Temporal.PlainMonthDay.from('07-04')); }, function () { return new Intl.DateTimeFormat('en-US').format(Temporal.ZonedDateTime.from('2024-07-04T12:00[UTC]')); }, function () { return new Intl.DateTimeFormat('en-US', { timeStyle: 'short' }).format(Temporal.PlainDate.from('2024-07-04')); }, function () { return new Intl.DateTimeFormat('en-US', { year: 'numeric' }).format(Temporal.PlainTime.from('10:00')); }, function () { return new Intl.DateTimeFormat('en-US', { hour: 'numeric' }).format(Temporal.PlainMonthDay.from('07-04')); }, function () { return new Intl.DateTimeFormat('en-US', { calendar: 'japanese' }).format(Temporal.PlainDate.from('2024-07-04[u-ca=hebrew]')); }, function () { return new Intl.DateTimeFormat('en-US').formatRange(Temporal.PlainDate.from('2024-07-04'), Temporal.PlainDateTime.from('2024-07-05T00:00')); }]);
"""
    check(js, golden, "date_time_format_with_temporal_values", body)


def test_date_to_locale_string_methods(js, golden):
    """CATCHES: Date.prototype.toLocaleString/toLocaleDateString/toLocaleTimeString that default to the wrong component set, ignore timeZone/locale arguments, mishandle Invalid Date, or skip option validation and receiver checks fails this."""
    body = r"""var d = new Date(Date.UTC(2024, 11, 25, 15, 4, 5, 678));
show('toLocaleString', function () { return [d.toLocaleString('en-US', { timeZone: 'UTC' }), d.toLocaleString(), d.toLocaleString('en-US', { timeZone: 'UTC', dateStyle: 'long' }), d.toLocaleString('en-US', { timeZone: 'Asia/Kolkata', hour: 'numeric' }), d.toLocaleString('de-DE', { timeZone: 'Europe/Berlin' }), d.toLocaleString(['xx', 'de'], { timeZone: 'UTC' }), d.toLocaleString('en-US', { timeZone: 'America/New_York', hour12: false })].join(' | '); });
show('toLocaleDateString', function () { return [d.toLocaleDateString('en-US', { timeZone: 'Asia/Tokyo' }), d.toLocaleDateString(), d.toLocaleDateString(undefined, { month: 'long', timeZone: 'UTC' }), d.toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'long', month: 'long', day: 'numeric' }), d.toLocaleDateString('en-US', { timeZone: 'UTC', hour: 'numeric' }), d.toLocaleDateString('en-US', { dateStyle: 'full', timeZone: 'Pacific/Kiritimati' }), d.toLocaleDateString('de', { timeZone: 'UTC' })].join(' | '); });
show('toLocaleTimeString', function () { return [d.toLocaleTimeString('en-US', { timeZone: 'America/Los_Angeles' }), d.toLocaleTimeString(), d.toLocaleTimeString('en-US', { timeZone: 'UTC', hour12: false }), d.toLocaleTimeString('en-US', { timeZone: 'UTC', timeStyle: 'short' }), d.toLocaleTimeString('en-US', { timeZone: 'UTC', year: 'numeric' }), d.toLocaleTimeString('de', { timeZone: 'UTC' })].join(' | '); });
show('invalid date', function () { var x = new Date(NaN); return [x.toLocaleString(), x.toLocaleDateString('de'), x.toLocaleTimeString('en', { timeZone: 'Nowhere/City' })].join(' | '); });
show('epoch edges', function () { return [new Date(0).toLocaleString('en-US', { timeZone: 'UTC' }), new Date(-1).toLocaleString('en-US', { timeZone: 'UTC' }), new Date(-62198755200000).toLocaleDateString('en-US', { timeZone: 'UTC', era: 'short', year: 'numeric', month: 'short', day: 'numeric' }), new Date(8.64e15).toLocaleDateString('en-US', { timeZone: 'UTC' })].join(' | '); });
each('errors', [function () { return new Date(0).toLocaleString('en', { timeStyle: 'short', hour: 'numeric' }); }, function () { return new Date(0).toLocaleDateString('en', { timeZone: 'Nowhere/City' }); }, function () { return Date.prototype.toLocaleString.call({}); }, function () { return Date.prototype.toLocaleDateString.call(0); }, function () { return Date.prototype.toLocaleTimeString.call(null); }, function () { return new Date(0).toLocaleString('en', { month: 'enormous' }); }, function () { return new Date(0).toLocaleString('!'); }]);
"""
    check(js, golden, "date_to_locale_string_methods", body)


# ---------------------------------------------------------------------------------- Intl.Locale


def test_locale_getters_options_and_keywords(js, golden):
    """CATCHES: Intl.Locale construction that does not canonicalize case and variant order, ignores language/script/region/variants overrides, mishandles -u- keyword options (calendar, collation, hourCycle, caseFirst, numeric, numberingSystem, firstDayOfWeek), or reports the wrong getter values fails this."""
    body = r"""function desc(l) { return [l.toString(), l.baseName, l.language, l.script, l.region, l.variants, l.calendar, l.collation, l.hourCycle, l.caseFirst, l.numeric, l.numberingSystem, l.firstDayOfWeek].map(String).join(' '); }
show('all keywords', function () { return desc(new Intl.Locale('ZH-hant-tw-u-CA-chinese-co-stroke-hc-h11-kf-upper-kn-nu-hanidec-fw-sun')); });
show('variants', function () { return desc(new Intl.Locale('sl-rozaj-biske-1994')); });
show('plain', function () { return desc(new Intl.Locale('en')); });
show('options', function () { return desc(new Intl.Locale('en', { language: 'FR', script: 'latn', region: 'ca', variants: 'Fonipa', calendar: 'Gregory', collation: 'emoji', hourCycle: 'h23', caseFirst: 'false', numeric: false, numberingSystem: 'arab', firstDayOfWeek: 3 })); });
show('override extension', function () { return [new Intl.Locale('en-u-ca-buddhist-kn-true', { calendar: 'japanese', numeric: true }).toString(), new Intl.Locale('de-u-kn-false').numeric, new Intl.Locale('de-u-kn').numeric, new Intl.Locale('en-u-co-phonebk-x-priv', { collation: 'trad' }).toString(), new Intl.Locale('en-u-foo-bar-ca-gregory', { hourCycle: 'h12' }).toString(), new Intl.Locale('en-t-ja-u-nu-latn').toString()].join(' | '); });
show('region/script replacement', function () { return [new Intl.Locale('sr-Cyrl-RS', { script: 'Latn' }).toString(), new Intl.Locale('en-US-posix', { variants: 'scouse-1901' }).toString(), new Intl.Locale('iw-IL').toString(), new Intl.Locale('en', { language: 'iw' }).toString()].join(' | '); });
show('firstDayOfWeek', function () { return ['mon', 'Sat', 0, 7, '1', 'true', 'wednesday'].map(function (v) { try { var l = new Intl.Locale('en', { firstDayOfWeek: v }); return l.firstDayOfWeek + '/' + l.getWeekInfo().firstDay + '/' + l.toString(); } catch (e) { return e.name + ': ' + e.message; } }).join(' | '); });
show('from Locale objects', function () { var a = new Intl.Locale('en-US-u-ca-gregory'); var b = new Intl.Locale(a, { region: 'GB' }); return b + ' ' + new Intl.Locale({ toString: function () { return 'pt-br'; } }) + ' ' + Object.prototype.toString.call(a) + ' ' + Intl.getCanonicalLocales([a, 'es']).join(',') + ' ' + (a.maximize() !== a); });
"""
    check(js, golden, "locale_getters_options_and_keywords", body)


def test_locale_maximize_and_minimize(js, golden):
    """CATCHES: Add/Remove Likely Subtags that pick the wrong script or region (Chinese Traditional, Serbian, Punjabi in Pakistan, und-*), drop variants or extensions, or minimize to a tag that does not maximize back fails this."""
    body = r"""['en', 'en-US', 'en-GB', 'zh', 'zh-TW', 'zh-Hant', 'zh-HK', 'zh-Hans-SG', 'und', 'und-Cyrl', 'und-JP', 'und-Arab', 'sr', 'sr-ME', 'sr-Latn', 'pa-PK', 'ja-u-ca-japanese', 'en-x-private', 'ar', 'hi', 'und-150', 'en-Shaw', 'zz', 'qaa', 'de-CH-1996', 'es-419', 'ru-Latn', 'az-IR', 'uz-AF', 'mn-CN'].forEach(function (t) {
  show(t, function () { var l = new Intl.Locale(t); return l.maximize() + ' > ' + l.maximize().minimize() + ' | min ' + l.minimize(); });
});
"""
    check(js, golden, "locale_maximize_and_minimize", body)


def test_locale_info_methods_and_errors(js, golden):
    """CATCHES: Intl.Locale info methods (getCalendars/getCollations/getHourCycles/getNumberingSystems/getTimeZones/getWeekInfo/getTextInfo) that ignore keywords, plus constructor and getter validation errors (missing new, bad tags, bad option grammar, foreign receivers) fail this."""
    body = r"""show('keyword info', function () { var l = new Intl.Locale('en-US-u-ca-islamic-hc-h12-nu-arab-co-compat-fw-fri'); return JSON.stringify([l.getCalendars(), l.getCollations(), l.getHourCycles(), l.getNumberingSystems(), l.getWeekInfo().firstDay]); });
show('defaults', function () { return JSON.stringify([new Intl.Locale('en').getTextInfo(), new Intl.Locale('en').getCalendars(), new Intl.Locale('en').getNumberingSystems(), new Intl.Locale('de').getWeekInfo(), new Intl.Locale('de-u-fw-sun').getWeekInfo()]); });
show('region-less timeZones', function () { return String(new Intl.Locale('fr').getTimeZones()) + ' ' + Array.isArray(new Intl.Locale('fr-FR').getTimeZones()); });
show('fresh arrays', function () { var l = new Intl.Locale('en-u-ca-buddhist'); return (l.getCalendars() !== l.getCalendars()) + ' ' + l.getCalendars().length; });
each('constructor errors', [function () { return Intl.Locale('en'); }, function () { return new Intl.Locale(5); }, function () { return new Intl.Locale(); }, function () { return new Intl.Locale(null); }, function () { return new Intl.Locale(''); }, function () { return new Intl.Locale('x-private'); }, function () { return new Intl.Locale('en-'); }, function () { return new Intl.Locale('en', null); }]);
each('option errors', [function () { return new Intl.Locale('en', { language: 'e' }); }, function () { return new Intl.Locale('en', { language: 'en-US' }); }, function () { return new Intl.Locale('en', { script: 'Lat' }); }, function () { return new Intl.Locale('en', { region: 'USA' }); }, function () { return new Intl.Locale('en', { variants: 'ab' }); }, function () { return new Intl.Locale('en', { variants: 'fonipa-fonipa' }); }, function () { return new Intl.Locale('en', { calendar: 'ab' }); }, function () { return new Intl.Locale('en', { collation: 'abc-' }); }, function () { return new Intl.Locale('en', { hourCycle: 'H23' }); }, function () { return new Intl.Locale('en', { caseFirst: 'true' }); }, function () { return new Intl.Locale('en', { numberingSystem: 'latn-' }); }, function () { return new Intl.Locale('en', { firstDayOfWeek: 'x' }); }]);
each('receiver errors', [function () { return Object.getOwnPropertyDescriptor(Intl.Locale.prototype, 'language').get.call({}); }, function () { return Object.getOwnPropertyDescriptor(Intl.Locale.prototype, 'calendar').get.call({}); }, function () { return Object.getOwnPropertyDescriptor(Intl.Locale.prototype, 'numeric').get.call({}); }, function () { return Intl.Locale.prototype.maximize.call('en'); }, function () { return Intl.Locale.prototype.toString.call({}); }, function () { return Intl.Locale.prototype.getCalendars.call({}); }, function () { return Intl.Locale.prototype.getTimeZones.call({}); }, function () { return Intl.Locale.prototype.getWeekInfo.call(new Intl.Collator()); }, function () { return Intl.Locale.prototype.getTextInfo.call({}); }]);
"""
    check(js, golden, "locale_info_methods_and_errors", body)


def test_get_canonical_locales_aliases_and_extensions(js, golden):
    """CATCHES: language-tag canonicalization that misses language/region/script/variant aliases (iw, sh, cmn, art-lojban, sgn-GR, SU, CS, BU, hepburn-heploc), keyword value aliases, extension and attribute ordering, or transform-extension canonicalization fails this."""
    body = r"""['EN-us', 'iw', 'in-ID', 'sh', 'cmn', 'art-lojban', 'sgn-GR', 'ja-latn-hepburn-heploc', 'en-u-ca-ethiopic-amete-alem', 'en-t-zh-hant-m0-names', 'de-1996-1901', 'en-a-bbb-z-ccc-b-aaa', 'hy-arevela', 'und-Qaai', 'en-u-ms-imperial-kb-yes', 'mo', 'aar-x-private', 'en-BU', 'sr-CS', 'und-SU', 'ru-SU', 'hy-SU', 'tl', 'en-u-tz-cnckg-sd-usca', 'en-U-Va-POSIX', 'zh-guoyu', 'cel-gaulish', 'sl-rozaj-biske-1994', 'en-u-attr2-attr1-ca-gregory', 'de-u-co-phonebk-ka-shifted', 'en-u-kn-true', 'en-u-ks-level1', 'en-t-hi-latn-h0-hybrid', 'und-Latn-t-und-hani-m0-names', 'yue-hk', 'heb', 'zh-hans-cn-x-a-b', 'en-u-ca-islamicc', 'en-u-ca', 'en-US-POSIX', 'ja-u-ca-japanese-t-en-m0-ungegn', 'en-z-abc-u-nu-latn', 'ar-u-nu-arabext-ca-islamic-civil', 'en-u-ca-gregory-ca-buddhist', 'en-t-xx-a1-abc', 'art-lojban-fonipa', 'cel-gaulish-fonipa', 'cnr', 'cnr-RS', 'ru-Cyrl-SU', 'xx-Cyrl-SU', 'uz-Cyrl-SU', 'ja-Latn-heploc', 'en-polytoni', 'en-t-en-us-m0-abc', 'en-t-zh-latn-cn-variant1-a1-abc', 'sgn-BR', 'hy-arevmda', 'zh-hakka', 'zh-xiang', 'en-u-ks-primary', 'und-Hant-cn', 'swc', 'en-u-rg-no23', 'en-u-sd-no23'].forEach(function (t) {
  show(t, function () { return Intl.getCanonicalLocales(t)[0]; });
});
"""
    check(js, golden, "get_canonical_locales_aliases_and_extensions", body)


def test_canonical_locale_lists_invalid_tags_and_supported_values(js, golden):
    """CATCHES: CanonicalizeLocaleList that accepts structurally invalid tags (duplicate variants/singletons, empty subtags, irregular grandfathered tags), fails to dedupe or to read array-likes in order, plus wrong supportedValuesOf/supportedLocalesOf results fail this."""
    body = r"""show('invalid tags', function () { return ['', 'en-', '-en', 'en--US', 'e', 'en-u', 'de-1996-1996', 'en-a-x-y', 'abcdefghi', '123', 'en-US-x', 'en-a-aa-a-bb', 'x-', 'en-t-root', 'i-klingon', 'zh-min-nan', 'no-bok', 'en-gb-oed', 'x-whatever', 'en_US', 'en-US-u-', 'en-' + 'a'.repeat(9), 'en-x-abcdefghi', 'en-u-a1-foo', 'en-t-123', 'en-t-m0', 'en-t-a1-ab', 'en-t-en-a1', 'de-u-co-phonebook'].map(function (t) { try { return JSON.stringify(Intl.getCanonicalLocales(t)); } catch (e) { return e.name + ': ' + e.message; } }).join('\n  '); });
show('lists', function () { return JSON.stringify([Intl.getCanonicalLocales(), Intl.getCanonicalLocales('EN'), Intl.getCanonicalLocales(['en', 'EN', 'en-us', 'en-US']), Intl.getCanonicalLocales(new Intl.Locale('fr-ca')), Intl.getCanonicalLocales({ length: 2, 0: 'de', 1: 'it' }), Intl.getCanonicalLocales(5), Intl.getCanonicalLocales({ length: 3, 1: 'ja' }), Intl.getCanonicalLocales([new Intl.Locale('ko-kr'), 'KO-KR'])]); });
each('type errors', [function () { return Intl.getCanonicalLocales(null); }, function () { return Intl.getCanonicalLocales([5]); }, function () { return Intl.getCanonicalLocales([null]); }, function () { return Intl.getCanonicalLocales([undefined]); }, function () { return Intl.getCanonicalLocales([{ toString: function () { return 'de-at'; } }]); }]);
show('read order', function () { var log = []; var p = new Proxy(['de', 'fr'], { get: function (t, k) { log.push(String(k)); return t[k]; }, has: function (t, k) { log.push('has:' + String(k)); return k in t; } }); var r = Intl.getCanonicalLocales(p); return r.join(',') + ' ' + log.join(','); });
show('fresh result', function () { var a = Intl.getCanonicalLocales('en'); a.push('x'); return Intl.getCanonicalLocales('en').length + ' ' + Array.isArray(a); });
show('supportedValuesOf', function () { return ['calendar', 'collation', 'currency', 'numberingSystem', 'unit'].map(function (k) { var v = Intl.supportedValuesOf(k); var sorted = v.slice().sort().join() === v.join(); return k + '(' + v.length + (sorted ? ',sorted' : ',UNSORTED') + ')=' + v.slice(0, 8).join(','); }).join('\n  '); });
show('supported time zones', function () { var z = Intl.supportedValuesOf('timeZone'); return z.filter(function (s) { return /^(UTC|Etc\/|Europe\/P|Asia\/K)/.test(s); }).join(',') + ' sorted=' + (z.slice().sort().join() === z.join()); });
show('supportedValuesOf bad', function () { return Intl.supportedValuesOf('colour'); });
show('supportedLocalesOf', function () { return ['Collator', 'DateTimeFormat', 'DisplayNames', 'DurationFormat', 'ListFormat', 'NumberFormat', 'PluralRules', 'RelativeTimeFormat', 'Segmenter'].map(function (s) { return s + '=' + Intl[s].supportedLocalesOf(['en-US', 'xx', 'ja-JP', 'sw', 'pl', 'gv', 'EN-gb']).join(','); }).join(' | '); });
"""
    check(js, golden, "canonical_locale_lists_invalid_tags_and_supported_values", body)


# --------------------------------------------------------------------------- the other services


@pytest.mark.parametrize("tier", TIERS)
def test_segmenter_grapheme_clusters(js, golden, tier):
    """CATCHES: grapheme segmentation that splits CRLF, combining marks, emoji modifier and ZWJ sequences, regional-indicator pairs or Hangul L/V/T jamo, mishandles lone surrogates, or reports wrong segment indices fails this."""
    body = r"""function segs(it) { return Array.from(it, function (s) { return JSON.stringify(s.segment) + '@' + s.index; }).join(' '); }
var g = new Intl.Segmenter('en');
show('mixed', function () { return segs(g.segment('éa\r\n👍🏽🇯🇵🇺🇸👨‍👩‍👧ẍ한국각!')); });
show('counts', function () { return ['🏳️‍🌈é̃🇫🇷🇩', 'a\u0301\u0302b', '\u0007\u0308x', 'ab\u200dc', '🇦🇧🇨', 'e\u0301\u0301\u0301'].map(function (s) { return [...g.segment(s)].length; }).join(','); });
show('hangul', function () { return segs(g.segment('ᄀ가각각ᆨᅡ')) + ' | ' + segs(g.segment('\u1100\u1161\u11a8\uac00\u1161\u11a8')); });
show('spacing marks', function () { return segs(g.segment('कि각aः')); });
show('lone surrogates', function () { return segs(g.segment('\udc00\ud83d')); });
show('coercion', function () { return segs(g.segment(12.5)) + ' ' + segs(g.segment(undefined)); });
show('empty', function () { var s = g.segment(''); return [...s].length + ' ' + s.containing(0); });
show('iterator', function () { var s = g.segment('abc'); var it = s[Symbol.iterator](); var a = it.next(); var b = it.next(); it.next(); return JSON.stringify(a) + ' ' + b.value.segment + ' ' + JSON.stringify(it.next()) + ' ' + [...s].length + ' ' + [...s].length; });
show('hot loop', function () { var n = 0; for (var k = 0; k < 30; k++) { n += [...g.segment('a\u0301👍🏽' + k)].length; } return n; });
show('resolvedOptions', function () { return JSON.stringify(g.resolvedOptions()) + ' ' + JSON.stringify(new Intl.Segmenter('xx-YY', { granularity: 'sentence' }).resolvedOptions()) + ' ' + JSON.stringify(new Intl.Segmenter(['de-AT', 'en']).resolvedOptions()) + ' ' + Object.prototype.toString.call(g); });
each('errors', [function () { return Intl.Segmenter(); }, function () { return new Intl.Segmenter('en', { granularity: 'line' }); }, function () { return new Intl.Segmenter('en', 'word'); }, function () { return Intl.Segmenter.prototype.segment.call({}, 'x'); }, function () { return new Intl.Segmenter('en', { localeMatcher: 'nope' }); }, function () { return new Intl.Segmenter('$$'); }, function () { return Intl.Segmenter.prototype.resolvedOptions.call(1); }]);
"""
    check(js, golden, "segmenter_grapheme_clusters", body, tier)


def test_segmenter_words_sentences_and_containing(js, golden):
    """CATCHES: word segmentation that splits contractions, decimal numbers or MidLetter/MidNum joins, fails to merge space runs, reports wrong isWordLike flags, sentence segmentation at the wrong terminator positions, or containing() with wrong index coercion fails this."""
    body = r"""function segs(it) { return Array.from(it, function (s) { return JSON.stringify(s.segment) + '@' + s.index + (s.isWordLike === undefined ? '' : (s.isWordLike ? 'w' : '')); }).join(' '); }
var w = new Intl.Segmenter('en', { granularity: 'word' });
show('words', function () { return segs(w.segment("Hello, world! It's 3.14 o'clock, don't  stop.   e.g. a:b 1,000;2 x\ty")); });
show('word edges', function () { return segs(w.segment("can’t isn't 12.5.6 a..b 5,a 'quote' naïve café")); });
show('astral word', function () { return segs(w.segment('a\ud800b 𝒳y')); });
show('null word', function () { return segs(w.segment(null)); });
var s = new Intl.Segmenter('en', { granularity: 'sentence' });
show('sentences', function () { return segs(s.segment('Hi there. How are you?  Fine!\nOK! Bye')); });
show('one sentence', function () { return segs(s.segment('No terminator here')) + ' | ' + segs(s.segment('Ends here.')); });
show('containing', function () { var seg = w.segment('The quick brown fox'); return [0, 3, 4, 8, 18, 19, -1, 2.7, '5', NaN, undefined, Infinity].map(function (i) { var r = seg.containing(i); return r ? r.segment + '@' + r.index + ':' + r.isWordLike : 'undefined'; }).join(' | '); });
show('containing record', function () { var r = new Intl.Segmenter('fr').segment('abc').containing(1); return JSON.stringify(r) + ' ' + Object.keys(r).join(','); });
show('sentence containing', function () { var seg = s.segment('One. Two? Three!'); return [0, 5, 6, 15].map(function (i) { return JSON.stringify(seg.containing(i).segment); }).join(' '); });
"""
    check(js, golden, "segmenter_words_sentences_and_containing", body)


def test_relative_time_format(js, golden):
    """CATCHES: RelativeTimeFormat with wrong past/future phrasing, numeric:auto phrases (yesterday/tomorrow/now/last week), short/narrow abbreviations, Polish plural forms, numbering-system digits, formatToParts unit tagging, or unit/value validation fails this."""
    body = r"""var f = new Intl.RelativeTimeFormat('en');
show('long', function () { return [[-1, 'day'], [1, 'day'], [0, 'second'], [2.5, 'hours'], [-3, 'quarter'], [-0, 'year'], [1000, 'weeks'], [-1, 'months'], [1, 'minute'], [-1234567.891, 'seconds'], ['3', 'year']].map(function (a) { return f.format(a[0], a[1]); }).join(' | '); });
show('auto', function () { var g = new Intl.RelativeTimeFormat('en', { numeric: 'auto' }); return [[-1, 'day'], [1, 'day'], [0, 'day'], [0, 'second'], [-1, 'week'], [1, 'quarter'], [0, 'hour'], [0, 'minute'], [2, 'day'], [-1, 'year'], [1, 'second'], [0, 'months'], [1, 'years'], [-0, 'week'], [1, 'week'], [1, 'month'], [-1, 'month'], [-1, 'quarter'], [0, 'quarter'], [0, 'year']].map(function (a) { return g.format(a[0], a[1]); }).join(' | '); });
['short'].forEach(function (st) {
  show(st, function () { var g = new Intl.RelativeTimeFormat('en', { style: st }); return ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'].map(function (u) { return g.format(-2, u) + '/' + g.format(1, u); }).join(', '); });
});
['long', 'short', 'narrow'].forEach(function (st) {
  show('pl ' + st, function () { var g = new Intl.RelativeTimeFormat('pl', { style: st }); return [1, 2, 5, 22, 1.5, -1, -5, 12].map(function (v) { return g.format(v, 'year') + '/' + g.format(v, 'week') + '/' + g.format(v, 'hour'); }).join(', '); });
});
show('auto parts', function () { var g = new Intl.RelativeTimeFormat('en', { numeric: 'auto' }); return parts(g.formatToParts(0, 'second')) + ' || ' + parts(g.formatToParts(3, 'week')); });
show('pl grouping', function () { return new Intl.RelativeTimeFormat('pl').format(1000, 'year') + ' | ' + new Intl.RelativeTimeFormat('pl').format(-123456, 'day') + ' | ' + new Intl.RelativeTimeFormat('pl', { numeric: 'auto' }).format(-1, 'day'); });
show('pl all units', function () { var g = new Intl.RelativeTimeFormat('pl'); return ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'].map(function (u) { return g.format(3, u) + '/' + g.format(-1, u); }).join(', '); });
show('parts', function () { return parts(f.formatToParts(-1234.5, 'hours')) + ' || ' + parts(new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).formatToParts(-1, 'day')) + ' || ' + parts(f.formatToParts(100, 'day')) + ' || ' + parts(new Intl.RelativeTimeFormat('pl').formatToParts(-5, 'minutes')); });
show('numbering', function () { return new Intl.RelativeTimeFormat('en', { numberingSystem: 'arab' }).format(12345, 'day') + ' | ' + new Intl.RelativeTimeFormat('en-u-nu-deva').format(-42, 'second') + ' | ' + JSON.stringify(new Intl.RelativeTimeFormat('en-u-nu-thai', { style: 'narrow' }).resolvedOptions()) + ' | ' + JSON.stringify(new Intl.RelativeTimeFormat('pl', { numeric: 'auto' }).resolvedOptions()); });
each('errors', [function () { return Intl.RelativeTimeFormat(); }, function () { return f.format(1, 'decade'); }, function () { return f.format(Infinity, 'day'); }, function () { return f.format(NaN, 'day'); }, function () { return new Intl.RelativeTimeFormat('en', { style: 'tiny' }); }, function () { return new Intl.RelativeTimeFormat('en', { numeric: 'never' }); }, function () { return new Intl.RelativeTimeFormat('en', { numberingSystem: '!' }); }, function () { return Intl.RelativeTimeFormat.prototype.format.call({}, 1, 'day'); }, function () { return f.format(1); }, function () { return f.format(1n, 'day'); }, function () { return f.formatToParts(1, 'Days'); }, function () { return new Intl.RelativeTimeFormat('en', null); }]);
"""
    check(js, golden, "relative_time_format", body)


def test_plural_rules_select_and_ranges(js, golden):
    """CATCHES: PluralRules categories for English, French (one for 0-1, many for millions), Polish (few/many), Slovenian and Manx, digit options that change the operands, compact-notation exponents, selectRange, resolvedOptions pluralCategories, or argument validation that deviate from CLDR fail this."""
    body = r"""var nums = [0, 1, 1.5, 2, 3, 4, 5, 11, 12, 21, 22, 25, 100, 101, 102, 103, 1e6, 0.5];
show('ru fractions', function () { return [1, 1.5, 0.5].map(function (n) { return new Intl.PluralRules('ru').select(n); }).join(',') + ' ' + new Intl.PluralRules('ru').resolvedOptions().pluralCategories; });
['en', 'fr', 'pl', 'sl', 'gv', 'ja', 'de', 'ko'].forEach(function (l) {
  show(l, function () { var p = new Intl.PluralRules(l); return nums.map(function (n) { return n + ':' + p.select(n); }).join(' '); });
});
show('ordinal type', function () { var p = new Intl.PluralRules('en', { type: 'ordinal' }); return [1, 4, 11].map(function (n) { return p.select(n); }).join(',') + ' ' + p.resolvedOptions().type; });
show('operands', function () { return [new Intl.PluralRules('en').select('1'), new Intl.PluralRules('en').select(-1), new Intl.PluralRules('en', { minimumIntegerDigits: 3 }).select(1), new Intl.PluralRules('en').select(NaN), new Intl.PluralRules('en').select(Infinity)].join(','); });
show('compact', function () { var p = new Intl.PluralRules('fr', { notation: 'compact' }); return [1e6, 1.5e6, 2e9, 1000, 5].map(function (n) { return p.select(n); }).join(',') + ' ' + JSON.stringify(p.resolvedOptions()); });
show('selectRange', function () { return [['en', 1, 2], ['en', 0, 1.5], ['fr', 0, 1], ['fr', 1, 2], ['pl', 1, 5], ['pl', 1, 3], ['ja', 1, 5], ['en', 5, 1], ['en', 1, Infinity]].map(function (a) { return a.join('/') + '=' + new Intl.PluralRules(a[0]).selectRange(a[1], a[2]); }).join(' | '); });
show('resolved', function () { return ['ar-EG', 'de', 'pl', 'sl', 'gv', 'ja', 'cs', 'fr', 'xx'].map(function (l) { var r = new Intl.PluralRules(l, { minimumSignificantDigits: 2 }).resolvedOptions(); return r.locale + ':' + r.pluralCategories.join('/'); }).join(' | ') + ' || ' + JSON.stringify(new Intl.PluralRules('de').resolvedOptions()) + ' || ' + JSON.stringify(new Intl.PluralRules('en', { maximumSignificantDigits: 3, roundingMode: 'floor' }).resolvedOptions()); });
each('errors', [function () { return Intl.PluralRules(); }, function () { return new Intl.PluralRules('en', { type: 'cardinal2' }); }, function () { return new Intl.PluralRules('en', { minimumFractionDigits: 101 }); }, function () { return new Intl.PluralRules('en', { maximumSignificantDigits: 0 }); }, function () { return new Intl.PluralRules('en').selectRange(1); }, function () { return new Intl.PluralRules('en').selectRange(NaN, 1); }, function () { return Intl.PluralRules.prototype.select.call({}, 1); }, function () { return new Intl.PluralRules('en', 5); }, function () { return new Intl.PluralRules('en').select(1n); }, function () { return new Intl.PluralRules('en', { notation: 'tiny' }); }, function () { return new Intl.PluralRules('en', { roundingMode: 'up' }); }]);
"""
    check(js, golden, "plural_rules_select_and_ranges", body)


def test_display_names_all_types(js, golden):
    """CATCHES: DisplayNames that do not canonicalize codes before lookup (iw→he, lowercase regions/scripts/currencies, islamicc and amete-alem calendars), ignore fallback none/code, validate codes per type wrongly, or report wrong resolvedOptions fails this."""
    body = r"""[['language', ['en', 'en-GB', 'EN-us', 'fr', 'zh', 'ja', 'ar', 'xx']], ['region', ['US', 'gb', '419', 'JP', 'kr', 'BR']], ['script', ['latn', 'Cyrl', 'HANS', 'hant', 'Arab', 'Jpan', 'kore']], ['currency', ['usd', 'EUR', 'JPY', 'gbp', 'CNY', 'XYZ']], ['calendar', ['gregory', 'islamicc', 'ethiopic-amete-alem', 'roc', 'iso8601', 'chinese', 'islamic-umalqura', 'fake']]].forEach(function (p) {
  show(p[0], function () { var dn = new Intl.DisplayNames('en', { type: p[0] }); var dn2 = new Intl.DisplayNames('en', { type: p[0], fallback: 'none' }); return p[1].map(function (c) { return dn.of(c) + '/' + dn2.of(c); }).join(', '); });
});
show('dateTimeField', function () { var dn = new Intl.DisplayNames('en', { type: 'dateTimeField' }); return ['era', 'year', 'quarter', 'month', 'day', 'hour', 'minute', 'second'].map(function (c) { return dn.of(c); }).join(','); });
show('resolved', function () { return JSON.stringify(new Intl.DisplayNames(['de-CH', 'en'], { type: 'region', style: 'narrow', fallback: 'none', languageDisplay: 'standard' }).resolvedOptions()) + ' ' + JSON.stringify(new Intl.DisplayNames('xx', { type: 'language' }).resolvedOptions()) + ' ' + Object.prototype.toString.call(new Intl.DisplayNames('en', { type: 'script' })); });
each('constructor errors', [function () { return Intl.DisplayNames('en', { type: 'region' }); }, function () { return new Intl.DisplayNames('en'); }, function () { return new Intl.DisplayNames('en', {}); }, function () { return new Intl.DisplayNames('en', { type: 'unit' }); }, function () { return new Intl.DisplayNames('en', { type: 'region', style: 'tiny' }); }, function () { return new Intl.DisplayNames('en', { type: 'region', fallback: 'empty' }); }, function () { return new Intl.DisplayNames('en', { type: 'language', languageDisplay: 'x' }); }, function () { return new Intl.DisplayNames('en', 'region'); }, function () { return new Intl.DisplayNames('en', { type: 'region', localeMatcher: 'x' }); }]);
each('of errors', [function () { return new Intl.DisplayNames('en', { type: 'language' }).of('en-u-ca-gregory'); }, function () { return new Intl.DisplayNames('en', { type: 'language' }).of('123'); }, function () { return new Intl.DisplayNames('en', { type: 'region' }).of('USA'); }, function () { return new Intl.DisplayNames('en', { type: 'script' }).of('Lat'); }, function () { return new Intl.DisplayNames('en', { type: 'currency' }).of('US'); }, function () { return new Intl.DisplayNames('en', { type: 'calendar' }).of('gregory_'); }, function () { return new Intl.DisplayNames('en', { type: 'dateTimeField' }).of('millisecond'); }, function () { return Intl.DisplayNames.prototype.of.call({}, 'en'); }, function () { return new Intl.DisplayNames('en', { type: 'region' }).of(); }, function () { return new Intl.DisplayNames('en', { type: 'language' }).of('x-private'); }, function () { return new Intl.DisplayNames('en', { type: 'language' }).of('root'); }, function () { return Intl.DisplayNames.prototype.resolvedOptions.call({}); }]);
"""
    check(js, golden, "display_names_all_types", body)


def test_duration_format_styles_and_units(js, golden):
    """CATCHES: DurationFormat with wrong long/short/narrow/digital unit rendering, sub-second folding into fractional seconds, fractionalDigits truncation, per-unit style/display options, negative-sign placement, localized list joining, or duration/option validation errors fails this."""
    body = r"""var d = { years: 1, months: 2, weeks: 3, days: 4, hours: 5, minutes: 6, seconds: 7, milliseconds: 8, microseconds: 9, nanoseconds: 10 };
['long', 'short', 'narrow', 'digital'].forEach(function (s) { show(s, function () { return new Intl.DurationFormat('en', { style: s }).format(d); }); });
show('digital', function () { var f = new Intl.DurationFormat('en', { style: 'digital' }); return [{ hours: 1, minutes: 2, seconds: 3 }, { minutes: 5 }, { seconds: 9, milliseconds: 50 }, { hours: 100 }, { days: 2, hours: 3, minutes: 4 }, { hours: -1, minutes: -30 }, { milliseconds: 1500 }].map(function (x) { return f.format(x); }).join(' | '); });
show('fractionalDigits', function () { return [0, 2, 9].map(function (n) { return new Intl.DurationFormat('en', { style: 'digital', fractionalDigits: n }).format({ hours: 1, seconds: 5, milliseconds: 123, microseconds: 456 }); }).join(' | ') + ' | ' + new Intl.DurationFormat('en', { seconds: 'numeric', fractionalDigits: 3 }).format({ seconds: 2, milliseconds: 9999 }); });
show('per unit', function () { return [new Intl.DurationFormat('en', { hours: 'numeric', minutes: '2-digit', seconds: '2-digit' }).format({ hours: 3, minutes: 4, seconds: 5 }), new Intl.DurationFormat('en', { style: 'long', minutesDisplay: 'always', secondsDisplay: 'always' }).format({ hours: 2 }), new Intl.DurationFormat('en', { days: 'long', hours: 'numeric' }).format({ days: 1, hours: 2, minutes: 3 }), new Intl.DurationFormat('en', { style: 'narrow', milliseconds: 'numeric' }).format({ seconds: 1, milliseconds: 5, microseconds: 7 }), new Intl.DurationFormat('en', { years: 'narrow', weeks: 'long', yearsDisplay: 'always' }).format({ weeks: 2 }), new Intl.DurationFormat('en', { minutes: 'numeric' }).format({ hours: 1, minutes: 5, seconds: 30 })].join(' | '); });
show('locales', function () { return ['de', 'fr', 'es', 'pl', 'en-GB'].map(function (l) { return l + '=' + new Intl.DurationFormat(l, { style: 'long' }).format({ hours: 1, minutes: 2, seconds: 3 }); }).join(' | '); });
show('inputs', function () { var f = new Intl.DurationFormat('en', { style: 'short' }); return [f.format('PT1H30M'), f.format('-P1DT2H'), f.format('PT0.5S'), f.format(Temporal.Duration.from({ days: 3, hours: 4 })), f.format({ days: -2, hours: -1 }), f.format({ hours: 0 }), f.format({ seconds: 1, nanoseconds: 1 })].join(' | '); });
show('iso strings', function () { var f = new Intl.DurationFormat('en', { style: 'short' }); return ['+PT1H', 'PT1.5H30M', 'P1.5D', 'PT', 'P', 'P1H', 'PT1.H', 'pt2m', 'P1Y2M3W4DT5H6M7.123456789S', 'P1DT', 'PTH'].map(function (x) { try { return f.format(x); } catch (e) { return e.name + ': ' + e.message; } }).join(' | '); });
show('sub-second folding', function () { return [new Intl.DurationFormat('en', { microseconds: 'numeric' }).format({ milliseconds: 5, microseconds: 7 }), new Intl.DurationFormat('en', { microseconds: 'numeric' }).format({ milliseconds: 5 }), new Intl.DurationFormat('en', { nanoseconds: 'numeric' }).format({ microseconds: 5, nanoseconds: 30 }), new Intl.DurationFormat('en', { nanoseconds: 'numeric' }).format({ microseconds: 5 }), new Intl.DurationFormat('en', { hoursDisplay: 'always' }).format({ hours: 0, minutes: -5 }), new Intl.DurationFormat('en', { style: 'digital' }).format({ minutes: -5 }), new Intl.DurationFormat('en', { milliseconds: 'numeric' }).format({ seconds: 3 }), new Intl.DurationFormat('en', { milliseconds: 'numeric' }).format({ seconds: 3, nanoseconds: 5 }), new Intl.DurationFormat('en', { style: 'digital', fractionalDigits: 2 }).format({ minutes: 1, milliseconds: 999 })].join(' | '); });
show('parts long', function () { return parts(new Intl.DurationFormat('en', { style: 'long' }).formatToParts({ hours: 1, minutes: 2, seconds: 3 })); });
show('parts digital', function () { return parts(new Intl.DurationFormat('en', { style: 'digital' }).formatToParts({ days: 1, hours: 1, minutes: 2, seconds: 3, milliseconds: 400 })); });
show('resolved digital', function () { return JSON.stringify(new Intl.DurationFormat('en-u-nu-arab', { style: 'digital', fractionalDigits: 3 }).resolvedOptions()); });
show('resolved long', function () { return JSON.stringify(new Intl.DurationFormat('fr', { style: 'long', hours: 'numeric' }).resolvedOptions()); });
show('arab digits', function () { return new Intl.DurationFormat('en-u-nu-arab', { style: 'digital' }).format({ hours: 12, minutes: 34, seconds: 56 }); });
each('errors', [function () { return Intl.DurationFormat(); }, function () { return new Intl.DurationFormat('en', { style: 'big' }); }, function () { return new Intl.DurationFormat('en', { hours: 'numeric', minutes: 'long' }); }, function () { return new Intl.DurationFormat('en', { years: 'numeric' }); }, function () { return new Intl.DurationFormat('en', { fractionalDigits: 10 }); }, function () { return new Intl.DurationFormat('en', { fractionalDigits: 1.5 }); }, function () { return new Intl.DurationFormat('en', { numberingSystem: 'x' }); }, function () { return new Intl.DurationFormat('en').format({ hours: 1, minutes: -1 }); }, function () { return new Intl.DurationFormat('en').format({}); }, function () { return new Intl.DurationFormat('en').format({ hours: 1.5 }); }, function () { return new Intl.DurationFormat('en').format('P1Q'); }, function () { return new Intl.DurationFormat('en').format(5); }, function () { return new Intl.DurationFormat('en').format({ years: 2 ** 32 }); }, function () { return new Intl.DurationFormat('en').format({ seconds: 2 ** 53 }); }, function () { return new Intl.DurationFormat('en', 'x'); }, function () { return Intl.DurationFormat.prototype.format.call({}, { hours: 1 }); }, function () { return new Intl.DurationFormat('en').format({ hour: 1 }); }]);
"""
    check(js, golden, "duration_format_styles_and_units", body)


def test_list_format_types_and_styles(js, golden):
    """CATCHES: ListFormat conjunction/disjunction/unit patterns for each style, two-item and singleton lists, Spanish y/o joining, formatToParts element/literal splitting, iterable inputs, or element type validation that deviate from CLDR fail this."""
    body = r"""var l = ['a', 'b', 'c', 'd'];
['conjunction', 'disjunction', 'unit'].forEach(function (t) {
  ['long', 'short', 'narrow'].forEach(function (s) {
    if (t === 'conjunction' && s === 'narrow') { return; }
    show(t + '/' + s, function () { var f = new Intl.ListFormat('en', { type: t, style: s }); return [f.format(l), f.format(['x', 'y']), f.format(['z']), JSON.stringify(f.format([]))].join(' ; '); });
    show('es ' + t + '/' + s, function () { var f = new Intl.ListFormat('es', { type: t, style: s }); return f.format(['uno', 'dos', 'tres']) + ' ; ' + f.format(['uno', 'dos']); });
  });
});
show('parts', function () { return parts(new Intl.ListFormat('en').formatToParts(['red', 'green', 'blue'])) + ' || ' + parts(new Intl.ListFormat('en', { type: 'disjunction' }).formatToParts(new Set(['x', 'y']))) + ' || ' + parts(new Intl.ListFormat('es', { type: 'unit', style: 'long' }).formatToParts(['1', '2', '3'])); });
show('iterables', function () { function* gen() { yield 'p'; yield 'q'; yield 'r'; } return new Intl.ListFormat('en').format(gen()) + ' | ' + new Intl.ListFormat('en').format('abc') + ' | ' + new Intl.ListFormat('en').format(new Map([['k', 1]]).keys()) + ' | ' + new Intl.ListFormat('en').format(undefined); });
show('resolved', function () { return JSON.stringify(new Intl.ListFormat('ja', { type: 'unit', style: 'narrow' }).resolvedOptions()) + ' ' + JSON.stringify(new Intl.ListFormat().resolvedOptions()) + ' ' + JSON.stringify(new Intl.ListFormat('es-MX').resolvedOptions()); });
each('errors', [function () { return Intl.ListFormat(); }, function () { return new Intl.ListFormat('en', { type: 'x' }); }, function () { return new Intl.ListFormat('en', { style: 'x' }); }, function () { return new Intl.ListFormat('en').format(['a', 1]); }, function () { return new Intl.ListFormat('en').format(5); }, function () { return new Intl.ListFormat('en', null); }, function () { return Intl.ListFormat.prototype.format.call({}, []); }, function () { return new Intl.ListFormat('en').formatToParts([null]); }, function () { return new Intl.ListFormat('en', { localeMatcher: 'x' }); }]);
"""
    check(js, golden, "list_format_types_and_styles", body)


@pytest.mark.parametrize("tier", TIERS)
def test_collator_sorting_and_options(js, golden, tier):
    """CATCHES: Collator comparison that orders by raw code units instead of primary/secondary/tertiary levels, ignores sensitivity, numeric collation, caseFirst, ignorePunctuation or the German phonebook/search umlaut expansion, or resolves collation keywords wrongly fails this."""
    body = r"""var words = ['résumé', 'resume', 'Resume', 'résume', 'apple', 'Apple', 'Äpfel', 'zebra', 'Zoo', 'item10', 'item2', 'item1', 'a-b', 'ab', 'a b', 'éclair', 'eclair'];
show('default sort', function () { return words.slice().sort(new Intl.Collator('en').compare).join(' '); });
show('numeric', function () { return ['item10', 'item2', 'item1', 'item02', 'x100y', 'x99y', 'v1.10', 'v1.9', 'a0', 'a', 'ab', 'a2b', 'a10'].sort(new Intl.Collator('en', { numeric: true }).compare).join(' ') + ' | ' + ['10', '9', '010', '1'].sort(new Intl.Collator('en-u-kn').compare).join(' ') + ' | ' + ['10', '9', '1'].sort(new Intl.Collator('en-u-kn-false').compare).join(' '); });
show('caseFirst', function () { return ['upper', 'lower', 'false'].map(function (c) { return c + '=' + ['b', 'B', 'a', 'A', 'ab', 'Ab', 'AB'].sort(new Intl.Collator('en', { caseFirst: c }).compare).join(','); }).join(' | ') + ' | kf=' + ['a', 'A'].sort(new Intl.Collator('en-u-kf-upper').compare).join(','); });
show('sensitivity', function () { var pairs = [['a', 'b'], ['a', 'á'], ['a', 'A'], ['a', 'a'], ['á', 'A'], ['ä', 'a'], ['A', 'Á']]; return ['base', 'accent', 'case', 'variant'].map(function (s) { var c = new Intl.Collator('en', { sensitivity: s }); return s + '=' + pairs.map(function (p) { return c.compare(p[0], p[1]); }).join(','); }).join(' | '); });
show('ignorePunctuation', function () { var c = new Intl.Collator('en', { ignorePunctuation: true }); return [c.compare('a-b', 'ab'), c.compare('a b', 'ab'), c.compare('a.b,c', 'abc'), new Intl.Collator('en').compare('a-b', 'ab'), new Intl.Collator('th').resolvedOptions().ignorePunctuation, new Intl.Collator('th', { ignorePunctuation: false }).resolvedOptions().ignorePunctuation].join(','); });
show('german', function () { var w = ['Müller', 'Mueller', 'Muller', 'Mzz', 'Möbius', 'Moe']; return w.slice().sort(new Intl.Collator('de').compare).join(' ') + ' | ' + w.slice().sort(new Intl.Collator('de-u-co-phonebk').compare).join(' ') + ' | ' + w.slice().sort(new Intl.Collator('de', { usage: 'search', sensitivity: 'base' }).compare).join(' ') + ' | ' + new Intl.Collator('de', { usage: 'search', sensitivity: 'base' }).compare('Müller', 'mueller'); });
show('hot sort', function () { var c = new Intl.Collator('en', { numeric: true }); var a = []; for (var k = 0; k < 60; k++) { a.push('f' + ((k * 37) % 61) + (k % 2 ? 'B' : 'a')); } a.sort(c.compare); return a.slice(0, 12).join(',') + ' ... ' + a.slice(-4).join(','); });
['de-u-co-phonebk-kn-kf-upper', 'es-u-co-trad', 'zh-u-co-pinyin', 'sv-u-co-reformed', 'en-u-co-phonebk', 'ar-u-co-compat', 'ko-u-co-searchjl', 'en-u-co-emoji'].forEach(function (l) {
  show('resolved ' + l, function () { return JSON.stringify(new Intl.Collator(l).resolvedOptions()); });
});
show('resolved options override', function () { return [JSON.stringify(new Intl.Collator('de-u-co-phonebk', { collation: 'eor', numeric: false, caseFirst: 'lower' }).resolvedOptions()), JSON.stringify(new Intl.Collator('es', { collation: 'trad', usage: 'search' }).resolvedOptions()), JSON.stringify(new Intl.Collator('en-u-co-phonebk', { collation: 'emoji' }).resolvedOptions()), JSON.stringify(new Intl.Collator(['xx', 'sv'], { collation: 'reformed', sensitivity: 'accent' }).resolvedOptions()), JSON.stringify(new Intl.Collator('de-u-kn-kf-lower', { numeric: true, caseFirst: 'lower' }).resolvedOptions())].join('\n  '); });
"""
    check(js, golden, "collator_sorting_and_options", body, tier)


def test_locale_compare_and_collator_validation(js, golden):
    """CATCHES: String.prototype.localeCompare that ignores its locales/options arguments or the undefined-argument coercion, or Collator construction and compare getter validation (bad usage/sensitivity/caseFirst, null options, foreign receivers, bound compare identity) fails this."""
    body = r"""show('localeCompare', function () { return ['a'.localeCompare('b'), 'b'.localeCompare('a'), 'a'.localeCompare('a'), 'a'.localeCompare('A'), 'a'.localeCompare('A', 'en', { sensitivity: 'base' }), 'ä'.localeCompare('a', 'de', { sensitivity: 'base' }), 'item10'.localeCompare('item9', undefined, { numeric: true }), 'résumé'.localeCompare('resume', 'fr', { sensitivity: 'accent' }), 'A\u030a'.localeCompare('\u00c5'), 'a'.localeCompare(), 'undefined'.localeCompare(), 'Ab'.localeCompare('ab', 'en', { caseFirst: 'upper' }), String.prototype.localeCompare.call(10, 9), 'a-b'.localeCompare('ab', 'en', { ignorePunctuation: true })].join(','); });
show('sort with localeCompare', function () { return ['nube', 'Óscar', 'oso', 'Zara', 'ábaco', 'abeja', 'Abeja', 'oscar'].sort(function (x, y) { return x.localeCompare(y, 'es'); }).join(' '); });
each('errors', [function () { return String.prototype.localeCompare.call(null, 'a'); }, function () { return String.prototype.localeCompare.call(undefined, 'a'); }, function () { return 'a'.localeCompare('b', 'en_US'); }, function () { return 'a'.localeCompare('b', 'en', { sensitivity: 'loose' }); }, function () { return new Intl.Collator('en', { usage: 'find' }); }, function () { return new Intl.Collator('en', { caseFirst: 'UPPER' }); }, function () { return Object.getOwnPropertyDescriptor(Intl.Collator.prototype, 'compare').get.call({}); }, function () { return new Intl.Collator('en', null); }, function () { return new Intl.Collator('en', { localeMatcher: 'x' }); }, function () { return Intl.Collator.prototype.resolvedOptions.call(Intl.Collator.prototype); }]);
show('compare bound', function () { var c = new Intl.Collator('en'); var f = c.compare; return [f === c.compare, f.length, JSON.stringify(f.name), f('b', 'a'), f(1, 2), f(), Intl.Collator().compare('x', 'y'), Object.prototype.toString.call(Intl.Collator()), Intl.Collator.supportedLocalesOf(['zh-Hant', 'tlh', 'si']).join(',')].join(' '); });
show('primitive options', function () { return JSON.stringify(new Intl.Collator('en', 'base').resolvedOptions()); });
"""
    check(js, golden, "locale_compare_and_collator_validation", body)


@pytest.mark.parametrize("tier", TIERS)
def test_intl_namespace_subclassing_and_option_read_order(js, golden, tier):
    """CATCHES: an Intl namespace with the wrong @@toStringTag or members, service constructors that ignore new.target prototypes for subclasses, break the NumberFormat legacy fallback-symbol chain, or read options in a different observable order than ECMA-402 fails this."""
    body = r"""show('namespace', function () { return Object.prototype.toString.call(Intl) + ' ' + Object.keys(Intl).length + ' ' + Object.getOwnPropertyNames(Intl).sort().join(','); });
show('prototype tags', function () { return ['Collator', 'DateTimeFormat', 'DisplayNames', 'DurationFormat', 'ListFormat', 'Locale', 'NumberFormat', 'PluralRules', 'RelativeTimeFormat', 'Segmenter'].map(function (n) { return Intl[n].prototype[Symbol.toStringTag] + '/' + Intl[n].length + '/' + Object.prototype.toString.call(Intl[n].prototype); }).join(' '); });
show('legacy NumberFormat chain', function () { var o = Object.create(Intl.NumberFormat.prototype); var r = Intl.NumberFormat.call(o, 'de', { minimumFractionDigits: 2 }); return (r === o) + ' ' + Object.getOwnPropertyDescriptor(Intl.NumberFormat.prototype, 'format').get.call(o)(1234) + ' ' + Intl.NumberFormat.prototype.resolvedOptions.call(o).locale + ' ' + String(Object.getOwnPropertySymbols(o)[0]); });
show('legacy non-inheriting', function () { var o = {}; var r = Intl.NumberFormat.call(o); return (r === o) + ' ' + Object.prototype.toString.call(r); });
show('legacy formatToParts', function () { var o = Object.create(Intl.NumberFormat.prototype); Intl.NumberFormat.call(o); return Intl.NumberFormat.prototype.formatToParts.call(o, 1); });
show('subclasses', function () {
  class NF extends Intl.NumberFormat { hi() { return 'hi:' + this.format(1e4); } }
  class L extends Intl.Locale { get x() { return this.language + '!'; } }
  class C extends Intl.Collator {}
  class S extends Intl.Segmenter {}
  class P extends Intl.PluralRules {}
  class D extends Intl.DisplayNames {}
  var n = new NF('en');
  return [n.hi(), n instanceof Intl.NumberFormat, Object.getPrototypeOf(n) === NF.prototype, new L('fr-CA').x, Object.getPrototypeOf(new C()) === C.prototype, Object.getPrototypeOf(new S()) === S.prototype, new P('en').select(1), new D('en', { type: 'region' }).of('JP')].join(' ');
});
show('non-object newTarget prototype', function () { function NT() {} NT.prototype = 5; return ['NumberFormat', 'DateTimeFormat', 'Collator', 'PluralRules', 'Segmenter', 'RelativeTimeFormat', 'ListFormat', 'DurationFormat', 'Locale', 'DisplayNames'].map(function (n) { var args = n === 'Locale' ? ['en'] : n === 'DisplayNames' ? ['en', { type: 'region' }] : []; var o = Reflect.construct(Intl[n], args, NT); return n + ':' + (Object.getPrototypeOf(o) === Intl[n].prototype); }).join(','); });
show('Reflect.construct', function () { function F() {} F.prototype = Object.create(Intl.DateTimeFormat.prototype, { tag: { value: 'custom' } }); var d = Reflect.construct(Intl.DateTimeFormat, ['en', { timeZone: 'UTC' }], F); return d.tag + ' ' + d.format(86400000); });
function order(make) { var log = []; var o = new Proxy({}, { get: function (t, k) { log.push(String(k)); return undefined; } }); make(o); return log.join(','); }
show('NumberFormat order', function () { return order(function (o) { new Intl.NumberFormat('en', o); }); });
show('DateTimeFormat order', function () { return order(function (o) { new Intl.DateTimeFormat('en', o); }); });
show('Collator order', function () { return order(function (o) { new Intl.Collator('en', o); }); });
show('Locale order', function () { return order(function (o) { new Intl.Locale('en', o); }); });
show('other orders', function () { return [order(function (o) { new Intl.PluralRules('en', o); }), order(function (o) { new Intl.RelativeTimeFormat('en', o); }), order(function (o) { new Intl.ListFormat('en', o); }), order(function (o) { new Intl.Segmenter('en', o); }), order(function (o) { o.type; new Intl.DisplayNames('en', Object.assign(Object.create(o), { type: 'region' })); }), order(function (o) { new Intl.DurationFormat('en', o); })].join('\n  '); });
show('hot construct', function () { var s = 0; for (var k = 0; k < 25; k++) { s += new Intl.NumberFormat('en', { minimumIntegerDigits: (k % 5) + 1 }).format(k).length; } return s; });
"""
    check(js, golden, "intl_namespace_subclassing_and_option_read_order", body, tier)
