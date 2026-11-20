"""ECMA-402 Intl.NumberFormat (and Number/BigInt/Array toLocaleString): styles, notations, digit
and rounding options, numbering systems, formatToParts, formatRange, resolvedOptions, errors.

The engine ships its own CLDR-derived tables, so every output here is deterministic."""
from conftest import check_script, resources_for

G = resources_for(__file__)

# A tiny JS prelude shared by the scripts: safe call that renders thrown errors, and a JSON helper.
PRELUDE = r'''
const t = (f) => { try { return f(); } catch (e) { return e.name + ': ' + e.message; } };
const nf = (l, o) => new Intl.NumberFormat(l, o);
const J = (x) => JSON.stringify(x);
'''


def check_js(run, workdir, name, body):
    return check_script(run, workdir, G, name, PRELUDE + body)


def test_decimal_separators_and_grouping_by_locale(run, workdir):
    """CATCHES: wrong per-locale decimal/group symbols (de '.' grouping, fr/ru/sv narrow no-break
    space U+202F, pt-PT/pl U+00A0), missing Indian 3;2 grouping for hi/en-IN, Arabic not switching to
    arab digits, or unknown languages not falling back to English separators."""
    check_js(run, workdir, "decimal_separators_and_grouping_by_locale", r'''
const xs = [1234567.891, -0.5, 1234, 12345, 100, 0];
for (const l of ['en', 'en-US', 'de', 'fr', 'ar', 'hi', 'en-IN', 'ja', 'zh', 'ko', 'ru', 'pt-BR', 'pt-PT',
                 'es', 'sv', 'pl', 'it', 'nl', 'th', 'tr', 'da', 'xx-YY'])
  console.log(l.padEnd(6), xs.map(x => J(nf(l).format(x))).join(' '));
''')


def test_percent_style_across_locales(run, workdir):
    """CATCHES: percent style not multiplying by 100, the default maximumFractionDigits of 0 for
    percent not applied, or the locale-specific percent spacing (de/fr/sv use a no-break space before
    '%', es/it/pt-BR do not) being wrong."""
    check_js(run, workdir, "percent_style_across_locales", r'''
for (const l of ['en', 'de', 'fr', 'ar', 'ja', 'ru', 'pt-BR', 'es', 'sv', 'it', 'nl'])
  console.log(l.padEnd(6), [0.256, -0.5, 12.3456, 0, 1].map(x => J(nf(l, {style: 'percent'}).format(x))).join(' '),
    '|', [0.256, 12.3456].map(x => J(nf(l, {style: 'percent', maximumFractionDigits: 1}).format(x))).join(' '));
console.log(nf('en', {style: 'percent', minimumFractionDigits: 2}).format(0.5));
console.log(nf('en', {style: 'percent', signDisplay: 'exceptZero'}).format(0.031));
''')


def test_currency_display_and_digits(run, workdir):
    """CATCHES: wrong currency symbol tables (CA$, CN¥, code fallback for CHF/KWD), symbol placement
    (prefix in en/ja, suffix with space in de/fr), ISO 4217 minor units (JPY 0, KWD 3), lowercase
    currency codes not upper-cased, or currencyDisplay code/narrowSymbol/name mis-handled (the reference
    renders currencyDisplay 'name' exactly like 'symbol' — pinned as observed)."""
    check_js(run, workdir, "currency_display_and_digits", r'''
for (const d of ['symbol', 'narrowSymbol', 'code', 'name'])
  for (const c of ['USD', 'EUR', 'JPY', 'GBP', 'CAD', 'CNY', 'CHF', 'KWD'])
    console.log(d.padEnd(12), c, ['en', 'de', 'fr', 'ja'].map(l =>
      J(nf(l, {style: 'currency', currency: c, currencyDisplay: d}).format(-1234.5))).join(' '));
console.log(nf('en', {style: 'currency', currency: 'usd'}).format(3), nf('en', {style: 'currency', currency: 'usd'}).resolvedOptions().currency);
console.log(nf('en', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}).format(2.5));
console.log(nf('en', {style: 'currency', currency: 'JPY', minimumFractionDigits: 2}).format(1234));
''')


def test_currency_sign_accounting_with_sign_display(run, workdir):
    """CATCHES: currencySign 'accounting' not wrapping negatives in parentheses (en/ja), or applying
    parentheses in locales that keep a minus (de), and signDisplay interacting wrongly with the
    accounting pattern (e.g. '+$0.00' for always, negative zero handling)."""
    check_js(run, workdir, "currency_sign_accounting_with_sign_display", r'''
for (const s of ['auto', 'never', 'always', 'exceptZero', 'negative'])
  console.log(s.padEnd(10),
    [-5, 0, 5, -0].map(x => nf('en', {style: 'currency', currency: 'USD', currencySign: 'accounting', signDisplay: s}).format(x)).join(' | '),
    '||', [-5, 0].map(x => nf('de', {style: 'currency', currency: 'EUR', currencySign: 'accounting', signDisplay: s}).format(x)).join(' | '));
console.log(nf('ja', {style: 'currency', currency: 'JPY', currencySign: 'accounting'}).format(-500));
console.log(nf('en', {style: 'currency', currency: 'EUR', signDisplay: 'always'}).format(5));
console.log(nf('de', {style: 'currency', currency: 'USD', signDisplay: 'exceptZero'}).format(-5));
console.log(J(nf('en', {style: 'currency', currency: 'USD', currencySign: 'accounting'}).formatToParts(-5)));
''')


def test_unit_style_unit_display(run, workdir):
    """CATCHES: missing short/narrow/long unit patterns (km/h vs 'kilometers per hour', narrow
    fahrenheit '°', foot '′'), wrong singular/plural selection (1 meter / 2.5 meters), compound
    per-units, or localized long unit names for de/fr/ja/es being dropped."""
    check_js(run, workdir, "unit_style_unit_display", r'''
const units = ['meter', 'kilometer', 'celsius', 'fahrenheit', 'percent', 'liter', 'kilobyte', 'gigabyte',
  'second', 'hour', 'day', 'byte', 'kilometer-per-hour', 'mile-per-hour', 'meter-per-second', 'kilogram',
  'foot', 'inch', 'degree', 'acre'];
for (const u of units)
  console.log(u, '|', ['short', 'narrow', 'long'].map(d => {
      const f = nf('en', {style: 'unit', unit: u, unitDisplay: d});
      return f.format(1) + ' / ' + f.format(2.5);
    }).join(' | '),
    '|', ['de', 'fr', 'ja', 'es'].map(l => nf(l, {style: 'unit', unit: u, unitDisplay: 'long'}).format(2)).join(' | '));
console.log(J(nf('en', {style: 'unit', unit: 'kilometer-per-hour', unitDisplay: 'long'}).formatToParts(1234)));
console.log(J(nf('en', {style: 'unit', unit: 'celsius'}).formatToParts(-3)));
for (const l of ['zh', 'zh-TW', 'en-IN', 'ja', 'ko', 'ru', 'pl', 'ar'])
  console.log(l, '|', [['celsius', 'long', 2], ['kilometer-per-hour', 'long', 1], ['kilometer-per-hour', 'short', 5], ['hour', 'long', 5], ['hour', 'long', 1.5]]
    .map(([u, d, x]) => nf(l, {style: 'unit', unit: u, unitDisplay: d}).format(x)).join(' | '));
console.log(J(nf('ja', {style: 'unit', unit: 'celsius', unitDisplay: 'long'}).formatToParts(-2)));
console.log(J(nf('ja', {style: 'unit', unit: 'meter-per-second', unitDisplay: 'long'}).formatToParts(1234)));
''')


def test_compact_notation_by_locale(run, workdir):
    """CATCHES: compact notation using the wrong magnitude tiers (ja/zh 万/億, ko 천/만, de Mio./Mrd.
    with no compact form below a million), wrong rounding to 2 significant digits, compactDisplay
    long names, or negative/small values being compacted (the reference prints 999999 as '1000K'
    rather than re-tiering to '1M' — pinned as observed)."""
    check_js(run, workdir, "compact_notation_by_locale", r'''
for (const l of ['en', 'de', 'ja', 'zh', 'zh-TW', 'ko', 'fr', 'es', 'ar', 'hi'])
  console.log(l.padEnd(5), [1234, 12345, 123456, 1234567, 1e9, 1.5e12, 999999].map(x => nf(l, {notation: 'compact'}).format(x)).join(' | '),
    '||', [1234, 1234567, 2e9].map(x => nf(l, {notation: 'compact', compactDisplay: 'long'}).format(x)).join(' | '));
console.log([-1234567, -0.0012, 0, 999, 1e15, 0.5].map(x => nf('en', {notation: 'compact'}).format(x)).join(' | '));
console.log([1234567, 1500, 123].map(x => nf('en', {notation: 'compact', maximumSignificantDigits: 4}).format(x)).join(' | '));
console.log(nf('en', {style: 'currency', currency: 'USD', notation: 'compact'}).format(1234567),
  nf('en', {style: 'unit', unit: 'byte', notation: 'compact', unitDisplay: 'long'}).format(1500000),
  nf('en', {style: 'percent', notation: 'compact'}).format(12345));
console.log(J(nf('en', {notation: 'compact'}).formatToParts(12345)), J(nf('de', {notation: 'compact', compactDisplay: 'long'}).formatToParts(-2500000)));
''')


def test_scientific_and_engineering_notation(run, workdir):
    """CATCHES: engineering notation not forcing exponents to multiples of 3, scientific defaulting
    to other than 3 maximum fraction digits, negative exponents/zero/negative mantissas, and the
    exponentSeparator/exponentMinusSign/exponentInteger parts in formatToParts."""
    check_js(run, workdir, "scientific_and_engineering_notation", r'''
const xs = [1234567, 0.000123, 1, 0, -98765, 12345, 1e21, 5e-7];
for (const n of ['scientific', 'engineering'])
  console.log(n, '|', xs.map(x => nf('en', {notation: n}).format(x)).join(' | '));
console.log([1234567, 0.000123, 12345].map(x => nf('de', {notation: 'scientific', maximumFractionDigits: 1}).format(x)).join(' | '));
console.log(nf('en', {notation: 'scientific', minimumSignificantDigits: 5}).format(12));
console.log(nf('ar', {notation: 'scientific'}).format(-0.00042));
console.log(J(nf('en', {notation: 'scientific'}).formatToParts(-0.00012)));
console.log(J(nf('en', {notation: 'engineering'}).formatToParts(98765)));
''')


def test_sign_display_all_values(run, workdir):
    """CATCHES: signDisplay variants mishandling zero vs negative zero (exceptZero/negative must not
    show a sign on -0, always shows '+0'), NaN getting a plus sign under 'always', Infinity rendered
    as anything other than '∞', or 'never' leaving a minus sign."""
    check_js(run, workdir, "sign_display_all_values", r'''
for (const s of ['auto', 'never', 'always', 'exceptZero', 'negative'])
  console.log(s.padEnd(10), [-1.5, -0, 0, 1.5, NaN, -Infinity, Infinity, -0.0001].map(x => nf('en', {signDisplay: s}).format(x)).join(' | '),
    '|', [-2, 0, 2].map(x => nf('de', {signDisplay: s, style: 'percent'}).format(x / 100)).join(' | '));
console.log(J(nf('en', {signDisplay: 'always'}).formatToParts(0)), J(nf('en').formatToParts(-Infinity)), J(nf('en').formatToParts(NaN)));
''')


def test_grouping_and_integer_digits(run, workdir):
    """CATCHES: useGrouping values (true/false/'always'/'auto'/'min2' and string coercion) being
    treated identically, min2 not suppressing grouping for 4-digit numbers, minimumIntegerDigits not
    zero-padding (and grouping the padded digits), or resolvedOptions().useGrouping not reflecting it."""
    check_js(run, workdir, "grouping_and_integer_digits", r'''
for (const g of [true, false, 'always', 'auto', 'min2', undefined, 0, ''])
  console.log(J(g), [1234, 12345, 1234567].map(x => t(() => nf('en', {useGrouping: g}).format(x))).join(' | '),
    '|', t(() => J(nf('en', {useGrouping: g}).resolvedOptions().useGrouping)));
console.log(t(() => nf('en', {useGrouping: 'sometimes'}).format(1)));
console.log(J(nf('en', {notation: 'compact'}).resolvedOptions().useGrouping), J(nf('de', {useGrouping: 'min2'}).format(1234)), J(nf('de', {useGrouping: 'min2'}).format(12345)));
for (const m of [1, 2, 5, 21])
  console.log('minInt', m, [12, 3.5, 0, 123456].map(x => nf('en', {minimumIntegerDigits: m}).format(x)).join(' | '));
console.log(t(() => nf('en', {minimumIntegerDigits: 0})), '|', t(() => nf('en', {minimumIntegerDigits: 22})));
''')


def test_fraction_and_significant_digits(run, workdir):
    """CATCHES: wrong interplay of minimum/maximum fraction and significant digits (significant digits
    override fraction digits, padding with trailing zeros, rounding 0.012345 to 2 significant digits),
    default maximumFractionDigits of 3, and range-check RangeErrors for out-of-range values."""
    check_js(run, workdir, "fraction_and_significant_digits", r'''
const show = (o, xs) => console.log(J(o), '=>', xs.map(x => t(() => nf('en', o).format(x))).join(' | '));
show({}, [1.23456, 0.0005, 1e-7, 123.4]);
show({minimumFractionDigits: 3}, [1, 1.23456]);
show({maximumFractionDigits: 0}, [1.5, 2.5, -1.5, 0.4]);
show({minimumFractionDigits: 1, maximumFractionDigits: 4}, [1, 1.23456, 0.00001]);
show({maximumFractionDigits: 1}, [0.05, 0.95, 9.99]);
show({minimumSignificantDigits: 3}, [1, 123456, 0.5]);
show({maximumSignificantDigits: 2}, [1234, 0.012345, 99.5]);
show({minimumSignificantDigits: 2, maximumSignificantDigits: 4}, [1, 1.23456, 12345.6]);
show({maximumSignificantDigits: 1}, [0.95, 15, -15]);
show({minimumFractionDigits: 20}, [0.1]);
show({maximumFractionDigits: 101}, [1]);
show({minimumFractionDigits: 3, maximumFractionDigits: 1}, [1]);
show({maximumSignificantDigits: 0}, [1]);
show({minimumSignificantDigits: 5, maximumSignificantDigits: 3}, [1]);
show({maximumFractionDigits: 'x'}, [1]);
''')


def test_rounding_modes(run, workdir):
    """CATCHES: any of the nine roundingMode values implemented with the wrong direction for
    negative numbers or ties (ceil/floor vs expand/trunc, halfEven banker's rounding, halfCeil vs
    halfFloor on -2.5), and an invalid roundingMode not throwing RangeError."""
    check_js(run, workdir, "rounding_modes", r'''
const xs = [1.5, 2.5, -1.5, -2.5, 1.4, -1.6, 0.5, -0.5, 2.25];
for (const m of ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'])
  console.log(m.padEnd(10), xs.map(x => nf('en', {maximumFractionDigits: 0, roundingMode: m}).format(x)).join(' | '),
    '| sig:', [1234, -1250].map(x => nf('en', {maximumSignificantDigits: 2, roundingMode: m}).format(x)).join(' | '),
    '| frac:', [1.005, 2.345].map(x => nf('en', {maximumFractionDigits: 2, roundingMode: m}).format(x)).join(' | '));
console.log(t(() => nf('en', {roundingMode: 'up'})));
''')


def test_rounding_increment_priority_trailing_zeros(run, workdir):
    """CATCHES: roundingIncrement not rounding to multiples of 5/25/50 at the fraction position,
    missing validation (allowed set, TypeError with significant rounding, RangeError when min != max
    fraction digits), roundingPriority more/lessPrecision choosing the wrong result, and
    trailingZeroDisplay validation (the reference accepts 'stripIfInteger' but still prints '1.00' —
    pinned as observed)."""
    check_js(run, workdir, "rounding_increment_priority_trailing_zeros", r'''
const show = (o, xs) => console.log(J(o), '=>', xs.map(x => t(() => nf('en', o).format(x))).join(' | '));
show({roundingIncrement: 5, maximumFractionDigits: 2, minimumFractionDigits: 2}, [1.234, 1.276, 1.225]);
show({roundingIncrement: 25, maximumFractionDigits: 2, minimumFractionDigits: 2}, [1.234, 1.376, 1.124]);
show({roundingIncrement: 50, maximumFractionDigits: 1, minimumFractionDigits: 1, roundingMode: 'floor'}, [7.9, 12.4]);
show({roundingIncrement: 5000, maximumFractionDigits: 4, minimumFractionDigits: 4}, [0.74, 0.76]);
show({roundingIncrement: 3}, [1]);
show({roundingIncrement: 5, maximumFractionDigits: 2}, [1]);
show({roundingIncrement: 5, maximumSignificantDigits: 2}, [1]);
show({roundingPriority: 'morePrecision', maximumSignificantDigits: 2, maximumFractionDigits: 2}, [1.234, 123.456, 0.001234]);
show({roundingPriority: 'lessPrecision', maximumSignificantDigits: 2, maximumFractionDigits: 2}, [1.234, 123.456, 0.001234]);
show({roundingPriority: 'auto', maximumSignificantDigits: 2, maximumFractionDigits: 2}, [1.234]);
show({roundingPriority: 'x'}, [1]);
show({trailingZeroDisplay: 'stripIfInteger', minimumFractionDigits: 2}, [1, 1.5]);
show({style: 'currency', currency: 'USD', trailingZeroDisplay: 'stripIfInteger'}, [1, 1.5]);
show({trailingZeroDisplay: 'never'}, [1]);
console.log(J(nf('en', {roundingIncrement: 25, maximumFractionDigits: 2, minimumFractionDigits: 2}).resolvedOptions()));
''')


def test_numbering_systems(run, workdir):
    """CATCHES: missing digit tables for numbering systems (arab, arabext, deva, hanidec, thai, beng,
    fullwide, tamldec, khmr, mymr), the -u-nu- extension not being honoured or reflected in the
    resolved locale, the numberingSystem option not overriding the extension, an unknown nu falling
    back to latn, and ar defaulting to arab digits."""
    check_js(run, workdir, "numbering_systems", r'''
for (const ns of ['arab', 'arabext', 'deva', 'hanidec', 'thai', 'beng', 'fullwide', 'tamldec', 'latn', 'khmr', 'mymr', 'tibt', 'guru'])
  console.log(ns.padEnd(8), nf('en', {numberingSystem: ns}).format(1234567.89), '|', nf('en-u-nu-' + ns).format(-42.5), '|',
    nf('en-u-nu-' + ns).resolvedOptions().locale, nf('en', {numberingSystem: ns}).resolvedOptions().numberingSystem);
console.log(nf('ar').resolvedOptions().numberingSystem, nf('ar-EG').format(12.5), nf('ar', {numberingSystem: 'latn'}).format(12.5));
const both = nf('en-u-nu-arab', {numberingSystem: 'deva'});
console.log(both.resolvedOptions().locale, both.resolvedOptions().numberingSystem, both.format(5));
console.log(nf('en-u-nu-bogus').resolvedOptions().locale, nf('en-u-nu-bogus').resolvedOptions().numberingSystem);
console.log(nf('zh-u-nu-hanidec').format(1024), nf('hi-u-nu-deva', {style: 'percent'}).format(0.25), nf('th-u-nu-thai', {style: 'currency', currency: 'USD'}).format(9.5));
console.log(J(nf('en-u-nu-arab').formatToParts(-1234.5)));
console.log(t(() => nf('en', {numberingSystem: 'x'})), '|', t(() => nf('en', {numberingSystem: 'abc-'})));
''')


def test_format_to_parts_decomposition(run, workdir):
    """CATCHES: formatToParts emitting the wrong part types (minusSign/plusSign, currency, group,
    decimal, fraction, percentSign, literal, nan/infinity) or splitting grouped integers incorrectly,
    and the parts not concatenating to exactly format()'s output."""
    check_js(run, workdir, "format_to_parts_decomposition", r'''
const cases = [
  ['en', {style: 'currency', currency: 'USD'}, -1234567.891],
  ['de', {style: 'percent', signDisplay: 'always'}, 0.123],
  ['fr', {}, -1234.5],
  ['de', {style: 'currency', currency: 'EUR'}, -1234.5],
  ['hi', {}, 123456789.25],
  ['en', {minimumIntegerDigits: 4}, 7],
  ['en', {maximumFractionDigits: 0}, 0.4],
  ['ja', {style: 'currency', currency: 'JPY'}, 12345],
];
for (const [l, o, x] of cases) {
  const f = nf(l, o);
  const parts = f.formatToParts(x);
  console.log(l, J(o), x, parts.map(p => p.type + '=' + J(p.value)).join(' '), parts.map(p => p.value).join('') === f.format(x));
}
console.log(J(nf('en').formatToParts()), J(nf('en').formatToParts('12.50')), J(nf('en').formatToParts(5n)));
''')


def test_format_range_and_range_to_parts(run, workdir):
    """CATCHES: formatRange not collapsing equal endpoints into an approximately-sign form ('~$3.00'),
    missing en-dash separators (spaced around currencies), incorrect source tagging
    (startRange/endRange/shared) in formatRangeToParts, and missing TypeError/RangeError for absent or
    NaN arguments."""
    check_js(run, workdir, "format_range_and_range_to_parts", r'''
const usd = nf('en', {style: 'currency', currency: 'USD'});
console.log(nf('en').formatRange(3, 5), '|', usd.formatRange(3, 5), '|', usd.formatRange(3, 3), '|', nf('de', {style: 'currency', currency: 'EUR'}).formatRange(3, 5));
console.log(nf('en', {maximumFractionDigits: 0}).formatRange(2.9, 3.1), '|', nf('en').formatRange(-5, -3), '|', nf('en', {style: 'percent'}).formatRange(0.1, 0.2), '|', nf('en').formatRange(5, 3));
console.log(nf('en', {notation: 'compact'}).formatRange(1000, 5000), '|', nf('en', {style: 'unit', unit: 'meter'}).formatRange(1, 2), '|', nf('en').formatRange(1n, 10n), '|', nf('en').formatRange('1.5', '2.5'));
console.log(t(() => nf('en').formatRange(NaN, 3)), '|', t(() => nf('en').formatRange(undefined, 3)), '|', t(() => nf('en').formatRange(1)), '|', t(() => nf('en').formatRange(1, NaN)));
console.log(J(usd.formatRangeToParts(3, 5)));
console.log(J(nf('en').formatRangeToParts(3, 3)));
console.log(J(nf('fr').formatRangeToParts(-1234, 5678)));
console.log(nf('pt-BR', {style: 'currency', currency: 'EUR'}).formatRange(3, 5), '|', nf('pt-BR').formatRange(-5, -3), '|', nf('pt').formatRange(1, 2), '|',
  usd.formatRange(-5, -3), '|', nf('en', {style: 'currency', currency: 'USD', signDisplay: 'always'}).formatRange(3, 5));
console.log(J(nf('pt-BR', {style: 'currency', currency: 'EUR'}).formatRangeToParts(3, 5)));
''')


def test_bigint_and_string_inputs_exact(run, workdir):
    """CATCHES: BigInt or numeric-string inputs being converted through float64 (losing digits past
    2^53), string parsing rules (whitespace, exponents, hex, empty string -> 0, junk -> NaN, '-0'),
    and coercions of booleans/null/undefined/arrays/Symbols."""
    check_js(run, workdir, "bigint_and_string_inputs_exact", r'''
console.log(nf('en').format(12345678901234567890n), '|', nf('de').format(-98765432109876543210n), '|', nf('en', {style: 'currency', currency: 'USD'}).format(10n ** 20n));
console.log(nf('en').format('12345678901234567890.123456789'), '|', nf('en', {maximumFractionDigits: 20}).format('0.1234567890123456789'));
console.log([' 42 ', '1e3', '', 'abc', '-0', '0x10', '+7', '.5', '1_000', 'Infinity', '-Infinity'].map(s => J(s) + '=' + nf('en').format(s)).join(' '));
console.log(nf('en').format(true), nf('en').format(null), nf('en').format(undefined), nf('en').format([5]), nf('en').format({valueOf() { return 7; }}));
console.log(t(() => nf('en').format(Symbol())), '|', nf('en').format(5e-324), '|', nf('en').format(1e21), '|', nf('en', {maximumSignificantDigits: 21}).format(0.1));
console.log(nf('en').format(Number.MAX_VALUE).length, nf('en').format(Number.MAX_SAFE_INTEGER), nf('en').format(2 ** 53 + 2));
console.log(nf('en', {notation: 'scientific'}).format(123456789012345678901234567890n), nf('en', {notation: 'compact'}).format(98765432109876543210n));
console.log(nf('en', {maximumSignificantDigits: 3, roundingMode: 'ceil'}).format('1.0000000000000000001'), nf('en', {maximumFractionDigits: 0}).format('2.5000000000000000000001'));
const big = 123456789012345678901n;
console.log(nf('en', {maximumSignificantDigits: 3}).format(big), '|', nf('en', {maximumSignificantDigits: 3, roundingMode: 'floor'}).format(big), '|',
  nf('en', {minimumSignificantDigits: 21}).format(12345678901234567890123n), '|', nf('en', {minimumIntegerDigits: 21}).format(12345678901234567890123n), '|',
  nf('en', {minimumSignificantDigits: 3}).format(7n), '|', nf('en', {minimumIntegerDigits: 4, maximumSignificantDigits: 2}).format(5n));
console.log(['trunc', 'floor', 'halfExpand'].map(m => nf('en', {maximumFractionDigits: 2, roundingMode: m}).format('1.23999999999999999999')).join(' | '), '|',
  nf('en', {minimumFractionDigits: 3}).format('1.50000000000000000000000'), '|', nf('en', {minimumIntegerDigits: 3}).format('1.50000000000000000000001'), '|',
  nf('en', {maximumFractionDigits: 2}).format('9.9999999999999999999'), '|', nf('de').format('-1234567890123456789.5'));
''')


def test_resolved_options_shapes(run, workdir):
    """CATCHES: resolvedOptions returning properties in the wrong order, missing currency/unit fields
    for those styles, significant-digit fields appearing only when relevant, percent defaulting
    maximumFractionDigits to 0, compact defaulting useGrouping to 'min2', and locale fallback for
    unsupported languages."""
    check_js(run, workdir, "resolved_options_shapes", r'''
const ro = (l, o) => J(nf(l, o).resolvedOptions());
console.log(ro('en'));
console.log(ro('de', {style: 'currency', currency: 'eur', currencySign: 'accounting'}));
console.log(ro('ja', {style: 'unit', unit: 'liter', notation: 'compact', maximumSignificantDigits: 3}));
console.log(ro('en', {roundingPriority: 'morePrecision', roundingMode: 'floor', useGrouping: false, signDisplay: 'never', trailingZeroDisplay: 'stripIfInteger'}));
console.log(ro('en', {style: 'percent'}));
console.log(ro('fr-CA', {notation: 'engineering', minimumFractionDigits: 2}));
console.log(ro('en-u-nu-thai', {style: 'currency', currency: 'JPY', currencyDisplay: 'code'}));
console.log(J(nf('xx-YY').resolvedOptions().locale), J(nf(['xx', 'de-AT', 'fr']).resolvedOptions().locale), J(nf('en-US-u-ca-buddhist').resolvedOptions().locale));
console.log(J(Object.keys(nf('en').resolvedOptions())));
''')


def test_constructor_option_errors(run, workdir):
    """CATCHES: missing or wrong error types/messages for invalid NumberFormat options: unknown style,
    missing currency/unit (TypeError), malformed currency/unit codes (RangeError), bad localeMatcher,
    null options, malformed locale tags, and invalid notation/compactDisplay/currencyDisplay."""
    check_js(run, workdir, "constructor_option_errors", r'''
const opts = [
  {style: 'bogus'}, {style: 'currency'}, {style: 'currency', currency: 'US'}, {style: 'currency', currency: 'US1'},
  {style: 'unit'}, {style: 'unit', unit: 'foo'}, {style: 'unit', unit: 'meter-per-foo'}, {style: 'unit', unit: 'kilometer-per-hour-per-second'},
  {localeMatcher: 'x'}, {notation: 'tiny'}, {compactDisplay: 'medium'}, {currencyDisplay: 'icon', style: 'currency', currency: 'USD'},
  {currencySign: 'bracket'}, {unitDisplay: 'wide'}, {signDisplay: 'sometimes'}, {currency: 'EURO'},
];
for (const o of opts) console.log(J(o), '=>', t(() => nf('en', o).format(1)));
console.log(t(() => new Intl.NumberFormat('en', null)));
console.log(t(() => new Intl.NumberFormat('en_US')));
console.log(t(() => new Intl.NumberFormat([''])));
console.log(t(() => new Intl.NumberFormat([5])));
console.log(t(() => Intl.NumberFormat.prototype.format.call({}, 1)));
console.log(t(() => Intl.NumberFormat.prototype.resolvedOptions.call(new Intl.Collator())));
console.log(nf('en', {style: 'decimal', currency: 'USD'}).format(5), J(nf('en', {currency: 'usd'}).resolvedOptions().currency));
''')


def test_format_getter_and_constructor_shape(run, workdir):
    """CATCHES: the format getter not returning a bound function (usable with Array.map), being
    re-created on each access, the legacy callable-without-new form, the toStringTag, function
    names/lengths, and supportedLocalesOf filtering unsupported languages."""
    check_js(run, workdir, "format_getter_and_constructor_shape", r'''
const f1 = nf('de');
const g = f1.format;
console.log(g(1234.5), [1, 2, 3000].map(f1.format).join(';'), typeof g, J(g.name), g.length, f1.format === f1.format);
console.log(Intl.NumberFormat('en') instanceof Intl.NumberFormat, Object.prototype.toString.call(nf('en')), Intl.NumberFormat.name, Intl.NumberFormat.length);
console.log(Intl.NumberFormat.prototype.formatToParts.length, Intl.NumberFormat.prototype.formatRange.length, Intl.NumberFormat.prototype.resolvedOptions.length);
console.log(J(Intl.NumberFormat.supportedLocalesOf(['de-DE', 'xx', 'ja', 'zz-Latn', 'pt-BR', 'EN-gb'])), J(Intl.NumberFormat.supportedLocalesOf('sv')), J(Intl.NumberFormat.supportedLocalesOf()));
console.log(t(() => Intl.NumberFormat.supportedLocalesOf('en', {localeMatcher: 'nope'})));
console.log(new Intl.NumberFormat(new Intl.Locale('de-CH')).resolvedOptions().locale, nf(['ja', 'en']).resolvedOptions().locale);
''')


def test_to_locale_string_number_bigint_array(run, workdir):
    """CATCHES: Number/BigInt.prototype.toLocaleString ignoring locales/options (not delegating to
    NumberFormat), Array.prototype.toLocaleString not forwarding (locales, options) to each element,
    null/undefined elements not becoming empty strings, and TypedArray toLocaleString."""
    check_js(run, workdir, "to_locale_string_number_bigint_array", r'''
console.log((1234567.891).toLocaleString(), '|', (1234567.891).toLocaleString('de-DE'), '|', (0.5).toLocaleString('en', {style: 'percent'}), '|',
  (12).toLocaleString('ja', {style: 'currency', currency: 'JPY'}), '|', (123456789n).toLocaleString('en-IN'), '|', NaN.toLocaleString('ar'), '|', (-0).toLocaleString());
console.log((1e6).toLocaleString('fr', {notation: 'compact', compactDisplay: 'long'}), '|', (42).toLocaleString('en-u-nu-deva'), '|', (5).toLocaleString(['xx', 'de'], {minimumFractionDigits: 2}));
console.log([1234.5, new Date(Date.UTC(2020, 0, 1)), 'x', null, undefined, 9876n].toLocaleString());
console.log([1234.5, 7].toLocaleString('de'), '|', [0.25].toLocaleString('en', {style: 'percent'}), '|', [[1000, 2000], [3000]].toLocaleString('fr'), '|', [].toLocaleString());
console.log([{toLocaleString() { return 'X' + J([...arguments]); }}].toLocaleString('de', {a: 1}));
console.log(new Int16Array([1000, -2000]).toLocaleString('de'), '|', new Float64Array([1.5, 1234.25]).toLocaleString('en-IN'), '|', new BigInt64Array([10n ** 6n]).toLocaleString('de'));
console.log(t(() => (1).toLocaleString('en', {style: 'currency'})), '|', t(() => (1).toLocaleString('??')));
''')
