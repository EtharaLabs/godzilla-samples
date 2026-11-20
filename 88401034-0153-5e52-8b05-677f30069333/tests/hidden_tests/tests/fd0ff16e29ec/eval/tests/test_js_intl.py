"""ECMA-402 (Intl) behaviour: NumberFormat, DateTimeFormat, DurationFormat, Locale, getCanonicalLocales /
BCP 47 canonicalization, Collator, Segmenter, PluralRules, RelativeTimeFormat, ListFormat, DisplayNames,
supportedLocalesOf / supportedValuesOf, and the locale-sensitive methods on Date, Number, BigInt and String.

Every program prints labelled lines `label => result` (or `label => THROW Name: message`). Dates are always
fixed timestamps; nothing reads the current time.
"""

import pytest

from conftest import golden

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

HELPER = r"""
const show = v => (v !== null && typeof v === 'object') ? JSON.stringify(v) : String(v);
function t(label, f) {
  let out;
  try { out = show(f()); } catch (e) { out = 'THROW ' + (e && e.constructor && e.constructor.name) + ': ' + (e && e.message); }
  console.log(label + ' => ' + out);
}
"""


def _check(run, prog, name, tier=()):
    r = run([*tier, "-e", HELPER + prog])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


NF_LOCALES = r"""
const f = (l, o, v) => new Intl.NumberFormat(l, o).format(v);
const locs = ['en', 'en-US', 'en-GB', 'en-IN', 'de', 'de-CH', 'de-AT', 'fr', 'fr-CA', 'fr-CH', 'es', 'es-MX', 'it', 'pt', 'pt-BR', 'pt-PT', 'nl',
  'sv', 'nb', 'da', 'fi', 'pl', 'cs', 'ru', 'uk', 'tr', 'el', 'he', 'ar', 'ar-EG', 'ar-SA', 'ar-MA', 'fa', 'ur', 'hi', 'bn', 'mr', 'ta', 'th', 'ja', 'zh',
  'zh-TW', 'ko', 'vi', 'id', 'ms', 'sw', 'und', 'xx', 'en-u-nu-arab', 'hi-u-nu-deva', 'zh-u-nu-hanidec', 'ar-u-nu-latn', 'th-u-nu-thai'];
for (const l of locs) {
  t(l, () => [f(l, {}, 1234567.891), f(l, {}, -0.5), f(l, {}, 1234), f(l, {}, 12345), f(l, {style: 'percent'}, 0.256), f(l, {notation: 'compact'}, 15300), f(l, {style: 'currency', currency: 'EUR'}, -1234.5), new Intl.NumberFormat(l).resolvedOptions().locale + '/' + new Intl.NumberFormat(l).resolvedOptions().numberingSystem].join(' | '));
}
t('special', () => [f('en', {}, NaN), f('en', {}, Infinity), f('en', {}, -Infinity), f('en', {}, -0), f('de', {}, NaN), f('ar', {}, NaN), f('ar-EG', {}, Infinity), f('en', {}, 1e21), f('en', {}, 5e-7), f('en', {}, 123456789012345678901234567890n), f('en', {}, -12n), f('en', {}, '1234.5678901234567890123'), f('en', {}, '-0'), f('en', {}, '  42  '), f('en', {}, '0x1F'), f('en', {}, '1e3'), f('en', {}, 'abc'), f('en', {}, true), f('en', {}, null), f('en', {}, undefined)].join(' | '));
t('string precision', () => [f('en', {maximumFractionDigits: 20}, '0.1000000000000000055511151231257827'), f('en', {maximumSignificantDigits: 21}, '123456789012345678901234567890'), f('en', {}, '99999999999999999999.9999')].join(' | '));
t('bigint toLocaleString', () => [12345678901234567890n.toLocaleString('en-IN'), (-5n).toLocaleString('de', {style: 'currency', currency: 'EUR'}), 10n ** 30n].map(String).join(' | '));
t('number toLocaleString', () => [(1234.5).toLocaleString(), (1234.5).toLocaleString('de'), (1234.5).toLocaleString('en', {style: 'currency', currency: 'CHF'}), (0.5).toLocaleString(undefined, {style: 'percent'}), (1e6).toLocaleString('fr'), NaN.toLocaleString('en')].join(' | '));
t('bad locale', () => f('en_US', {}, 1));
t('bad locale type', () => f(5, {}, 1));
t('locale list', () => new Intl.NumberFormat(['xx-YY', 'de-AT', 'en']).resolvedOptions().locale);
t('extension keys', () => [new Intl.NumberFormat('de-u-nu-thai-ca-japanese').resolvedOptions().locale, new Intl.NumberFormat('en-u-nu-bogus').resolvedOptions().locale, new Intl.NumberFormat('en-u-nu-arab', {numberingSystem: 'latn'}).resolvedOptions().locale].join(' | '));
t('format bound', () => { const nf = new Intl.NumberFormat('en'); return [1, 22, 333333].map(nf.format).join(';') + ' ' + (nf.format === nf.format); });
t('call without new', () => Intl.NumberFormat('de').format(1.5));
t('brand', () => Intl.NumberFormat.prototype.format);
t('brand2', () => Intl.NumberFormat.prototype.resolvedOptions.call({}));
t('length', () => [Intl.NumberFormat.length, Intl.NumberFormat.prototype.formatToParts.length, Intl.NumberFormat.prototype.formatRange.length].join());
"""

NF_STYLES = r"""
const f = (l, o, v) => new Intl.NumberFormat(l, o).format(v);
t('percent', () => [f('en', {style: 'percent'}, 0.256), f('de', {style: 'percent'}, 0.256), f('fr', {style: 'percent', maximumFractionDigits: 2}, 0.25678), f('tr', {style: 'percent'}, 0.5), f('en', {style: 'percent', signDisplay: 'always'}, -0.001)].join(' | '));
t('currency', () => [f('en', {style: 'currency', currency: 'USD'}, 1234.5), f('en', {style: 'currency', currency: 'JPY'}, 1234.5), f('ja', {style: 'currency', currency: 'JPY'}, 1234.5), f('en', {style: 'currency', currency: 'EUR', currencyDisplay: 'code'}, -5), f('en', {style: 'currency', currency: 'EUR', currencyDisplay: 'name'}, 2), f('en', {style: 'currency', currency: 'EUR', currencyDisplay: 'name'}, 1), f('en', {style: 'currency', currency: 'USD', currencySign: 'accounting'}, -5), f('de', {style: 'currency', currency: 'USD'}, 5), f('en', {style: 'currency', currency: 'GBP', currencyDisplay: 'narrowSymbol'}, 5), f('en', {style: 'currency', currency: 'KWD'}, 5), f('fr-CA', {style: 'currency', currency: 'CAD'}, 1234.5), f('en-IN', {style: 'currency', currency: 'INR'}, 1234567), f('en', {style: 'currency', currency: 'xyz'}, 1), f('en', {style: 'currency', currency: 'CLP'}, 1234.5), f('en', {style: 'currency', currency: 'BHD', maximumFractionDigits: 1}, 1.25)].join(' | '));
t('currency display matrix', () => ['USD', 'EUR', 'GBP', 'JPY', 'CNY', 'INR', 'CAD', 'AUD', 'CHF', 'KRW', 'BRL', 'MXN', 'RUB', 'TRY', 'SEK'].map(c => ['symbol', 'narrowSymbol', 'code', 'name'].map(d => f('en', {style: 'currency', currency: c, currencyDisplay: d}, 3)).join('/')).join(' | '));
t('currency locales', () => ['de', 'fr', 'ja', 'zh', 'es', 'it', 'pt-BR', 'ru', 'ar', 'ko', 'nl', 'hi'].map(l => f(l, {style: 'currency', currency: 'USD'}, -1234.56) + ' ' + f(l, {style: 'currency', currency: 'EUR', currencyDisplay: 'name'}, 2)).join(' | '));
t('currency missing', () => f('en', {style: 'currency'}, 1));
t('currency bad code', () => f('en', {style: 'currency', currency: 'US'}, 1));
t('currency bad code2', () => f('en', {style: 'currency', currency: 'U$D'}, 1));
t('currency bad display', () => f('en', {style: 'currency', currency: 'USD', currencyDisplay: 'emoji'}, 1));
t('currency bad sign', () => f('en', {style: 'currency', currency: 'USD', currencySign: 'banker'}, 1));
t('unit', () => [['kilometer-per-hour', 'short'], ['kilometer-per-hour', 'long'], ['liter', 'narrow'], ['megabyte', 'long'], ['celsius', 'short'], ['fahrenheit', 'long'], ['percent', 'short'], ['hour', 'long'], ['meter-per-second', 'long'], ['byte', 'narrow'], ['gigabit', 'short'], ['mile-per-gallon', 'long'], ['degree', 'short'], ['acre', 'long'], ['fluid-ounce', 'short'], ['stone', 'long'], ['millisecond', 'narrow'], ['kilogram-per-liter', 'short'], ['day', 'long']].map(([u, d]) => f('en', {style: 'unit', unit: u, unitDisplay: d}, 1) + '/' + f('en', {style: 'unit', unit: u, unitDisplay: d}, 2.5)).join(' | '));
t('unit locales', () => ['de', 'fr', 'ja', 'es', 'ru', 'zh', 'ar', 'pt', 'it'].map(l => ['short', 'long', 'narrow'].map(d => f(l, {style: 'unit', unit: 'kilometer', unitDisplay: d}, 3)).join('/')).join(' | '));
t('unit bad', () => f('en', {style: 'unit', unit: 'furlong'}, 1));
t('unit bad compound', () => f('en', {style: 'unit', unit: 'meter-per-furlong'}, 1));
t('unit missing', () => f('en', {style: 'unit'}, 1));
t('unit bad display', () => f('en', {style: 'unit', unit: 'meter', unitDisplay: 'tiny'}, 1));
t('style bad', () => f('en', {style: 'bogus'}, 1));
t('supportedValuesOf unit', () => Intl.supportedValuesOf('unit').join(','));
t('supportedValuesOf currency', () => Intl.supportedValuesOf('currency').join(','));
t('parts currency', () => JSON.stringify(new Intl.NumberFormat('en', {style: 'currency', currency: 'USD'}).formatToParts(-1234.5)));
t('parts accounting', () => JSON.stringify(new Intl.NumberFormat('en', {style: 'currency', currency: 'USD', currencySign: 'accounting'}).formatToParts(-1)));
t('parts de currency', () => JSON.stringify(new Intl.NumberFormat('de', {style: 'currency', currency: 'EUR'}).formatToParts(1234.5)));
t('parts unit', () => JSON.stringify(new Intl.NumberFormat('en', {style: 'unit', unit: 'kilogram'}).formatToParts(NaN)));
t('parts unit long', () => JSON.stringify(new Intl.NumberFormat('en', {style: 'unit', unit: 'kilometer-per-hour', unitDisplay: 'long'}).formatToParts(12)));
t('parts percent', () => JSON.stringify(new Intl.NumberFormat('fr', {style: 'percent'}).formatToParts(-0.5)));
t('parts infinity', () => JSON.stringify(new Intl.NumberFormat('en', {signDisplay: 'always'}).formatToParts(Infinity)));
"""

NF_NOTATION = r"""
const f = (l, o, v) => new Intl.NumberFormat(l, o).format(v);
const vals = [0, 1, 999, 1000, 1234, 9999, 99999, 999999, 1e6, 1.5e9, 2e12, 3e15, 4.2e18, -45678, 0.0012];
t('compact en', () => vals.map(v => f('en', {notation: 'compact'}, v)).join(' '));
t('compact en long', () => vals.map(v => f('en', {notation: 'compact', compactDisplay: 'long'}, v)).join(' | '));
for (const l of ['de', 'fr', 'es', 'ja', 'zh', 'ko', 'en-IN', 'hi', 'ru', 'ar', 'it', 'pt']) {
  t('compact ' + l, () => [1234, 15300, 1.5e6, 2e9, 7e12].map(v => f(l, {notation: 'compact'}, v) + '/' + f(l, {notation: 'compact', compactDisplay: 'long'}, v)).join(' | '));
}
t('compact digits', () => [f('en', {notation: 'compact', maximumFractionDigits: 2}, 1234567), f('en', {notation: 'compact', maximumSignificantDigits: 4}, 1234567), f('en', {notation: 'compact', minimumFractionDigits: 1}, 1000), f('en', {notation: 'compact', style: 'currency', currency: 'USD'}, 1234567), f('en', {notation: 'compact', style: 'percent'}, 123)].join(' | '));
t('scientific', () => [0, 1, 123456, 0.000123, -1.5e-10, 1e100, 9.99999, NaN, -Infinity].map(v => f('en', {notation: 'scientific'}, v)).join(' '));
t('scientific de', () => [123456, 0.000123].map(v => f('de', {notation: 'scientific'}, v)).join(' '));
t('scientific digits', () => [f('en', {notation: 'scientific', maximumFractionDigits: 5}, 123456789), f('en', {notation: 'scientific', minimumFractionDigits: 2}, 5), f('en', {notation: 'scientific', maximumSignificantDigits: 2}, 987654)].join(' | '));
t('engineering', () => [0, 1, 123456, 0.000123, 12345678, -0.5, 1e21].map(v => f('en', {notation: 'engineering', maximumSignificantDigits: 3}, v)).join(' '));
t('engineering default', () => [1234, 12345, 123456, 0.01].map(v => f('en', {notation: 'engineering'}, v)).join(' '));
t('notation bad', () => f('en', {notation: 'roman'}, 1));
t('compactDisplay bad', () => f('en', {notation: 'compact', compactDisplay: 'medium'}, 1));
t('parts compact', () => JSON.stringify(new Intl.NumberFormat('de', {notation: 'compact'}).formatToParts(1500000)));
t('parts compact long', () => JSON.stringify(new Intl.NumberFormat('en', {notation: 'compact', compactDisplay: 'long'}).formatToParts(-2500)));
t('parts scientific', () => JSON.stringify(new Intl.NumberFormat('en', {notation: 'scientific'}).formatToParts(-0.00012)));
t('parts engineering', () => JSON.stringify(new Intl.NumberFormat('en', {notation: 'engineering'}).formatToParts(12345)));
"""

NF_ROUNDING = r"""
const f = (l, o, v) => new Intl.NumberFormat(l, o).format(v);
t('signDisplay', () => ['auto', 'always', 'never', 'exceptZero', 'negative'].map(s => [1, -1, 0, -0, NaN, -0.0001].map(v => f('en', {signDisplay: s}, v)).join(',')).join(' | '));
t('signDisplay currency', () => ['auto', 'always', 'never', 'exceptZero', 'negative'].map(s => [3, -3, 0].map(v => f('en', {style: 'currency', currency: 'USD', currencySign: 'accounting', signDisplay: s}, v)).join(',')).join(' | '));
t('signDisplay bad', () => f('en', {signDisplay: 'sometimes'}, 1));
t('digits', () => [f('en', {minimumFractionDigits: 3}, 1.5), f('en', {maximumFractionDigits: 0}, 2.5), f('en', {maximumFractionDigits: 0}, 3.5), f('en', {minimumIntegerDigits: 4}, 12), f('en', {minimumIntegerDigits: 21}, 1), f('en', {maximumSignificantDigits: 2}, 1234), f('en', {minimumSignificantDigits: 5}, 1.2), f('en', {maximumFractionDigits: 20}, 0.1 + 0.2), f('en', {maximumFractionDigits: 100}, 1 / 3), f('en', {minimumFractionDigits: 0, maximumFractionDigits: 0}, 0.5), f('en', {maximumSignificantDigits: 1}, 0.000951), f('en', {minimumSignificantDigits: 21}, 5)].join(' | '));
t('digits errors', () => [{minimumFractionDigits: 5, maximumFractionDigits: 2}, {maximumFractionDigits: 101}, {minimumIntegerDigits: 0}, {minimumIntegerDigits: 22}, {maximumSignificantDigits: 0}, {minimumSignificantDigits: 3, maximumSignificantDigits: 2}, {minimumFractionDigits: -1}, {maximumFractionDigits: NaN}].map(o => { try { return f('en', o, 1); } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' | '));
t('currency digits interplay', () => [f('en', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}, 1.5), f('en', {style: 'currency', currency: 'USD', minimumFractionDigits: 3}, 1.5), f('en', {style: 'currency', currency: 'JPY', minimumFractionDigits: 2}, 1.5)].join(' | '));
t('currency digits error', () => f('en', {style: 'currency', currency: 'USD', maximumFractionDigits: 1}, 1.5));
t('roundingMode', () => ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(m => [1.25, -1.25, 1.35, -1.35, 1.2501, 0.05].map(v => f('en', {maximumFractionDigits: 1, roundingMode: m}, v)).join(',')).join(' | '));
t('roundingMode bad', () => f('en', {roundingMode: 'nearest'}, 1));
t('roundingIncrement', () => [[2, 5, 1.234], [0, 50, 1234], [1, 25, 1.26], [2, 10, 1.234], [3, 2500, 1.0001], [2, 20, -0.31], [1, 5000, 1234.56], [3, 1, 2.0005]].map(([d, inc, v]) => f('en', {maximumFractionDigits: d, minimumFractionDigits: d, roundingIncrement: inc}, v) + '/' + f('en', {maximumFractionDigits: d, minimumFractionDigits: d, roundingIncrement: inc, roundingMode: 'ceil'}, v)).join(' | '));
t('roundingIncrement currency', () => f('en', {style: 'currency', currency: 'CHF', roundingIncrement: 5, maximumFractionDigits: 2, minimumFractionDigits: 2}, 1.024));
t('roundingIncrement bad', () => f('en', {roundingIncrement: 3}, 1));
t('roundingIncrement sig', () => f('en', {roundingIncrement: 5, maximumSignificantDigits: 2}, 1));
t('roundingIncrement mismatch', () => f('en', {roundingIncrement: 5, minimumFractionDigits: 1, maximumFractionDigits: 2}, 1));
t('roundingPriority', () => ['auto', 'lessPrecision', 'morePrecision'].map(p => [1.234, 123.456, 0.0001234].map(v => f('en', {maximumFractionDigits: 2, maximumSignificantDigits: 2, roundingPriority: p}, v)).join(',')).join(' | '));
t('roundingPriority bad', () => f('en', {roundingPriority: 'most'}, 1));
t('trailingZeroDisplay', () => [f('en', {minimumFractionDigits: 2, trailingZeroDisplay: 'stripIfInteger'}, 5), f('en', {minimumFractionDigits: 2, trailingZeroDisplay: 'stripIfInteger'}, 5.1), f('en', {style: 'currency', currency: 'USD', trailingZeroDisplay: 'stripIfInteger'}, 7), f('en', {style: 'currency', currency: 'USD', trailingZeroDisplay: 'stripIfInteger'}, 7.004)].join(' | '));
t('trailingZeroDisplay bad', () => f('en', {trailingZeroDisplay: 'strip'}, 1));
t('useGrouping', () => ['always', 'auto', 'min2', false, true, 'true', 'false', undefined].map(g => ['es', 'en', 'pl', 'en-IN'].map(l => f(l, {useGrouping: g}, 1234) + '/' + f(l, {useGrouping: g}, 1234567)).join(',')).join(' | '));
t('useGrouping bad', () => f('en', {useGrouping: 'sometimes'}, 1));
t('numberingSystem option', () => ['arab', 'arabext', 'beng', 'deva', 'fullwide', 'gujr', 'guru', 'hanidec', 'khmr', 'knda', 'laoo', 'latn', 'limb', 'mlym', 'mong', 'mymr', 'orya', 'tamldec', 'telu', 'thai', 'tibt', 'bali', 'adlm'].map(n => f('en', {numberingSystem: n}, -1234567.89)).join(' '));
t('numberingSystem unsupported', () => new Intl.NumberFormat('en', {numberingSystem: 'jpan'}).resolvedOptions().numberingSystem);
t('numberingSystem bad', () => f('en', {numberingSystem: 'xx!'}, 1));
t('localeMatcher bad', () => f('en', {localeMatcher: 'fuzzy'}, 1));
t('resolved currency', () => new Intl.NumberFormat('de-DE', {style: 'currency', currency: 'eur'}).resolvedOptions());
t('resolved compact', () => new Intl.NumberFormat('en', {notation: 'compact', maximumSignificantDigits: 3}).resolvedOptions());
t('resolved ar-EG', () => new Intl.NumberFormat('ar-EG').resolvedOptions());
t('resolved unit', () => new Intl.NumberFormat('en', {style: 'unit', unit: 'liter', unitDisplay: 'long', signDisplay: 'exceptZero', roundingMode: 'floor', roundingPriority: 'morePrecision', maximumFractionDigits: 1, maximumSignificantDigits: 3}).resolvedOptions());
t('resolved percent', () => new Intl.NumberFormat('fr', {style: 'percent', useGrouping: false, minimumIntegerDigits: 3}).resolvedOptions());
t('resolved increment', () => new Intl.NumberFormat('en', {roundingIncrement: 50, maximumFractionDigits: 2, minimumFractionDigits: 2, trailingZeroDisplay: 'stripIfInteger'}).resolvedOptions());
t('option getter order', () => { const seen = []; const o = new Proxy({}, {get(_, k) { if (typeof k === 'string') seen.push(k); return undefined; }}); new Intl.NumberFormat('en', o); return seen.join(','); });
"""

NF_RANGE = r"""
t('range', () => [new Intl.NumberFormat('en').formatRange(3, 5), new Intl.NumberFormat('en', {style: 'currency', currency: 'USD'}).formatRange(3, 5), new Intl.NumberFormat('en', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0}).formatRange(2.9, 3.1), new Intl.NumberFormat('de').formatRange(-5, 5), new Intl.NumberFormat('en', {notation: 'compact'}).formatRange(1000, 5000), new Intl.NumberFormat('en', {notation: 'compact'}).formatRange(1000, 5e6), new Intl.NumberFormat('en', {style: 'percent'}).formatRange(0.1, 0.2), new Intl.NumberFormat('en', {style: 'unit', unit: 'meter'}).formatRange(1, 2), new Intl.NumberFormat('en', {style: 'unit', unit: 'meter', unitDisplay: 'long'}).formatRange(1, 2), new Intl.NumberFormat('en').formatRange(5, 3), new Intl.NumberFormat('en').formatRange(-Infinity, Infinity), new Intl.NumberFormat('en').formatRange(1n, 10n ** 20n), new Intl.NumberFormat('en', {signDisplay: 'always'}).formatRange(1, 1), new Intl.NumberFormat('fr', {style: 'currency', currency: 'EUR'}).formatRange(10, 20), new Intl.NumberFormat('ja', {style: 'currency', currency: 'JPY'}).formatRange(100, 200)].join(' | '));
t('range missing', () => new Intl.NumberFormat('en').formatRange(5));
t('range undefined', () => new Intl.NumberFormat('en').formatRange(undefined, 5));
t('range NaN', () => new Intl.NumberFormat('en').formatRange(NaN, 5));
t('rangeParts percent', () => JSON.stringify(new Intl.NumberFormat('en', {style: 'percent'}).formatRangeToParts(0.1, 0.2)));
t('rangeParts approx', () => JSON.stringify(new Intl.NumberFormat('en', {maximumFractionDigits: 0}).formatRangeToParts(2.9, 3.1)));
t('rangeParts currency', () => JSON.stringify(new Intl.NumberFormat('en', {style: 'currency', currency: 'USD'}).formatRangeToParts(-1, 2)));
t('rangeParts NaN', () => new Intl.NumberFormat('en').formatRangeToParts(1, NaN));
"""

DTF_STYLES = r"""
const T0 = Date.UTC(2024, 0, 5, 14, 7, 9, 45);
const f = (l, o, v = T0) => new Intl.DateTimeFormat(l, o).format(v);
const locs = ['en', 'en-US', 'en-GB', 'de', 'fr', 'ja', 'zh', 'zh-TW', 'ko', 'es', 'ru', 'ar', 'ar-EG', 'hi', 'pt-BR', 'it', 'nl', 'pl', 'tr', 'sv', 'fa', 'he', 'th', 'vi', 'uk', 'cs', 'el', 'id', 'fi', 'und'];
for (const l of locs) {
  t(l, () => [f(l, {}), ...['full', 'long', 'medium', 'short'].map(s => f(l, {dateStyle: s, timeStyle: s})), f(l, {dateStyle: 'medium'}), f(l, {timeStyle: 'short'}), new Intl.DateTimeFormat(l).resolvedOptions().locale].join(' | '));
}
t('styles bad', () => f('en', {dateStyle: 'tiny'}));
t('styles with components', () => f('en', {dateStyle: 'short', year: 'numeric'}));
t('timeStyle with hour12', () => [f('en', {timeStyle: 'short', hour12: false}), f('en', {timeStyle: 'medium', hourCycle: 'h11'}), f('de', {timeStyle: 'short', hour12: true}), f('ja', {timeStyle: 'long', hourCycle: 'h12'})].join(' | '));
t('midnight noon', () => [0, 12].map(h => ['h11', 'h12', 'h23', 'h24'].map(hc => f('en', {timeStyle: 'short', hourCycle: hc}, Date.UTC(2024, 0, 5, h, 5))).join(',')).join(' | '));
t('date toLocale', () => { const d = new Date(T0); return [d.toLocaleString(), d.toLocaleDateString(), d.toLocaleTimeString(), d.toLocaleString('de-DE', {timeZone: 'Europe/Berlin'}), d.toLocaleDateString('en-US', {month: 'long'}), d.toLocaleTimeString('ja-JP', {hour: '2-digit'}), d.toLocaleDateString('fr', {dateStyle: 'full'}), d.toLocaleTimeString('en', {timeStyle: 'full', timeZone: 'Asia/Tokyo'}), new Date(NaN).toLocaleString(), new Date(NaN).toLocaleDateString('de'), new Date(-1e14).toLocaleString('en'), new Date(Date.UTC(-50, 5, 1)).toLocaleDateString('en')].join(' | '); });
t('date toLocale bad', () => new Date(0).toLocaleString('en', {timeZone: 'Moon/Base'}));
t('date toLocaleDateString time only', () => new Date(0).toLocaleDateString('en', {hour: 'numeric'}));
t('date toLocaleTimeString date only', () => new Date(0).toLocaleTimeString('en', {year: 'numeric'}));
"""

DTF_COMPONENTS = r"""
const T0 = Date.UTC(2024, 0, 5, 14, 7, 9, 45);
const f = (l, o, v = T0) => new Intl.DateTimeFormat(l, o).format(v);
const combos = [
  {weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'}, {weekday: 'short', month: 'short', day: '2-digit'}, {weekday: 'narrow'},
  {month: 'narrow'}, {month: 'short'}, {month: 'long'}, {month: 'numeric'}, {month: '2-digit'}, {year: 'numeric'}, {year: '2-digit'}, {day: 'numeric'},
  {year: '2-digit', month: '2-digit', day: '2-digit'}, {year: 'numeric', month: 'short'}, {month: 'long', day: 'numeric'}, {month: 'numeric', day: 'numeric'},
  {hour: 'numeric'}, {hour: 'numeric', minute: '2-digit'}, {hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false}, {minute: 'numeric'},
  {second: 'numeric'}, {minute: 'numeric', second: 'numeric', fractionalSecondDigits: 3}, {second: 'numeric', fractionalSecondDigits: 1},
  {hour: 'numeric', minute: 'numeric', second: 'numeric', fractionalSecondDigits: 2}, {era: 'long', year: 'numeric'}, {era: 'short'}, {era: 'narrow', year: 'numeric', month: 'short'},
  {dayPeriod: 'long', hour: 'numeric'}, {dayPeriod: 'short'}, {dayPeriod: 'narrow', hour: 'numeric', minute: 'numeric'}, {timeZoneName: 'short'},
  {timeZoneName: 'long', hour: 'numeric'}, {timeZoneName: 'shortOffset'}, {timeZoneName: 'longOffset'}, {timeZoneName: 'shortGeneric'}, {timeZoneName: 'longGeneric'},
  {weekday: 'long', hour: 'numeric'}, {year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', timeZoneName: 'short'},
];
for (const l of ['en', 'de', 'fr', 'ja', 'es', 'ar', 'zh']) {
  t(l, () => combos.map(o => f(l, {timeZone: 'UTC', ...o})).join(' | '));
}
t('hourCycle', () => [['en', 'h11'], ['en', 'h12'], ['en', 'h23'], ['en', 'h24'], ['de', 'h12'], ['ja', 'h11']].map(([l, hc]) => [0, 12, 23].map(h => f(l, {hour: 'numeric', minute: 'numeric', hourCycle: hc, timeZone: 'UTC'}, Date.UTC(2024, 0, 5, h, 30))).join(',')).join(' | '));
t('hour12 overrides hourCycle', () => [f('en', {hour: 'numeric', hour12: false, hourCycle: 'h11'}), f('en-u-hc-h23', {hour: 'numeric'}), f('en-u-hc-h23', {hour: 'numeric', hour12: true}), f('de-u-hc-h12', {hour: 'numeric'})].join(' | '));
t('dayPeriod hours', () => [0, 3, 6, 9, 11, 12, 13, 17, 18, 20, 21, 23].map(h => f('en', {hour: 'numeric', dayPeriod: 'short', timeZone: 'UTC'}, Date.UTC(2024, 0, 5, h))).join(' | '));
t('era years', () => [Date.UTC(-500, 0, 1), Date.UTC(0, 0, 1), Date.UTC(1, 0, 1), -62198755200000].map(v => f('en', {era: 'short', year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC'}, v)).join(' | '));
t('bad month', () => f('en', {month: 'longish'}));
t('bad hourCycle', () => f('en', {hour: 'numeric', hourCycle: 'h25'}));
t('bad fsd', () => f('en', {fractionalSecondDigits: 4}));
t('bad fsd 0', () => f('en', {fractionalSecondDigits: 0}));
t('bad timeZoneName', () => f('en', {timeZoneName: 'medium'}));
t('bad weekday', () => f('en', {weekday: 'numeric'}));
t('bad calendar', () => f('en', {calendar: '!!'}));
t('bad numberingSystem', () => f('en', {numberingSystem: 'a'}));
t('formatMatcher', () => [f('en', {formatMatcher: 'basic', month: 'long'}), new Intl.DateTimeFormat('en', {formatMatcher: 'basic'}).resolvedOptions().formatMatcher].join(' | '));
t('formatMatcher bad', () => f('en', {formatMatcher: 'best'}));
"""

DTF_ZONES_PARTS = r"""
const T0 = Date.UTC(2024, 0, 5, 14, 7, 9, 45);
const f = (l, o, v = T0) => new Intl.DateTimeFormat(l, o).format(v);
t('timeZones', () => ['UTC', 'America/New_York', 'Asia/Kathmandu', 'Australia/Lord_Howe', 'Pacific/Chatham', '-03:30', '+0530', '+05', 'Etc/GMT-14', 'America/Argentina/Buenos_Aires', 'asia/tokyo', 'Etc/UTC', 'GMT', 'Asia/Calcutta', 'Europe/London', 'America/Los_Angeles', 'Asia/Shanghai'].map(z => f('en', {timeZone: z, dateStyle: 'short', timeStyle: 'long'})).join(' | '));
t('timeZones summer', () => ['America/New_York', 'Europe/London', 'Europe/Paris', 'Australia/Sydney'].map(z => f('en', {timeZone: z, dateStyle: 'short', timeStyle: 'full'}, Date.UTC(2024, 6, 1, 12))).join(' | '));
t('timeZoneName styles', () => ['UTC', 'Asia/Kolkata', 'America/Chicago', '+05:45', '-00:00', 'Europe/Berlin', 'Asia/Tokyo'].map(z => ['short', 'long', 'shortOffset', 'longOffset', 'shortGeneric', 'longGeneric'].map(s => f('en', {timeZone: z, timeZoneName: s})).join(' / ')).join(' | '));
t('tz bad', () => f('en', {timeZone: 'Mars/Phobos'}));
t('tz bad offset', () => f('en', {timeZone: '+25:00'}));
t('tz bad offset2', () => f('en', {timeZone: '+05:30:00'}));
t('tz bad unicode minus', () => f('en', {timeZone: '−05:00'}));
t('resolved alias', () => new Intl.DateTimeFormat('en', {timeZone: 'asia/calcutta'}).resolvedOptions());
t('resolved extensions', () => new Intl.DateTimeFormat('de-DE-u-ca-buddhist-hc-h11', {hour: 'numeric', minute: 'numeric'}).resolvedOptions());
t('resolved styles', () => new Intl.DateTimeFormat('ja', {dateStyle: 'long', timeStyle: 'short', timeZone: '+0530'}).resolvedOptions());
t('resolved ar-EG', () => new Intl.DateTimeFormat('ar-EG').resolvedOptions());
t('resolved components', () => new Intl.DateTimeFormat('en', {weekday: 'short', era: 'long', year: '2-digit', month: 'narrow', day: '2-digit', hour: '2-digit', minute: 'numeric', second: '2-digit', fractionalSecondDigits: 2, timeZoneName: 'shortOffset', timeZone: 'Europe/Paris', hour12: true}).resolvedOptions());
t('resolved nu option', () => new Intl.DateTimeFormat('en', {numberingSystem: 'thai', calendar: 'japanese'}).resolvedOptions());
t('parts full', () => JSON.stringify(new Intl.DateTimeFormat('en', {dateStyle: 'full', timeStyle: 'full', timeZone: 'UTC'}).formatToParts(T0)));
t('parts fractional', () => JSON.stringify(new Intl.DateTimeFormat('de', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 2}).formatToParts(T0)));
t('parts era dayPeriod', () => JSON.stringify(new Intl.DateTimeFormat('en', {era: 'short', year: 'numeric', hour: 'numeric', dayPeriod: 'long'}).formatToParts(T0)));
t('parts ar', () => JSON.stringify(new Intl.DateTimeFormat('ar-EG', {timeStyle: 'medium', timeZone: 'UTC'}).formatToParts(T0)));
t('parts relatedYear', () => JSON.stringify(new Intl.DateTimeFormat('en-u-ca-chinese', {dateStyle: 'long'}).formatToParts(T0)));
t('parts invalid', () => new Intl.DateTimeFormat('en').formatToParts(NaN));
t('range same day', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium', timeStyle: 'short'}).formatRange(T0, T0 + 3600000));
t('range same day ampm', () => new Intl.DateTimeFormat('en', {hour: 'numeric', minute: 'numeric'}).formatRange(T0 - 4 * 3600000, T0));
t('range diff month', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium'}).formatRange(T0, T0 + 86400000 * 40));
t('range diff year', () => new Intl.DateTimeFormat('en', {year: 'numeric', month: 'short', day: 'numeric'}).formatRange(T0, T0 + 86400000 * 400));
t('range equal', () => new Intl.DateTimeFormat('en', {dateStyle: 'long'}).formatRange(T0, T0));
t('range de', () => new Intl.DateTimeFormat('de', {day: 'numeric', month: 'long', year: 'numeric'}).formatRange(T0, T0 + 86400000 * 3));
t('range ja', () => new Intl.DateTimeFormat('ja', {dateStyle: 'short'}).formatRange(T0, T0 + 86400000 * 3));
t('range months only', () => new Intl.DateTimeFormat('en', {month: 'long'}).formatRange(T0, T0 + 86400000 * 60));
t('range time only', () => new Intl.DateTimeFormat('en', {timeStyle: 'short'}).formatRange(T0, T0 + 86400000 * 2));
t('range reversed', () => new Intl.DateTimeFormat('en', {dateStyle: 'short'}).formatRange(T0 + 86400000, T0));
t('range parts', () => JSON.stringify(new Intl.DateTimeFormat('en', {month: 'short', day: 'numeric'}).formatRangeToParts(T0, T0 + 86400000 * 3)));
t('range parts equal', () => JSON.stringify(new Intl.DateTimeFormat('en', {month: 'short', day: 'numeric'}).formatRangeToParts(T0, T0)));
t('range missing', () => new Intl.DateTimeFormat('en').formatRange(T0));
t('range NaN', () => new Intl.DateTimeFormat('en').formatRange(T0, NaN));
t('calendars', () => ['buddhist', 'japanese', 'hebrew', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla', 'persian', 'chinese', 'dangi', 'roc', 'gregory', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'iso8601', 'islamicc', 'bogus'].map(c => f('en-u-ca-' + c, {dateStyle: 'long', timeZone: 'UTC'}) + ' [' + new Intl.DateTimeFormat('en-u-ca-' + c).resolvedOptions().calendar + ']').join(' | '));
t('calendar option', () => [f('en', {calendar: 'japanese', era: 'short', year: 'numeric', month: 'numeric', day: 'numeric'}), f('en', {calendar: 'hebrew', month: 'long', day: 'numeric'}), f('ja', {calendar: 'japanese', dateStyle: 'full'}), f('en', {calendar: 'islamic-umalqura', dateStyle: 'full'})].join(' | '));
t('numbering systems', () => [f('ar-EG', {dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC'}), f('en-u-nu-thai', {dateStyle: 'short'}), f('hi-IN', {dateStyle: 'long'}), f('fa', {dateStyle: 'short'}), f('en', {numberingSystem: 'deva', timeStyle: 'medium'}), f('ar-EG', {second: 'numeric', fractionalSecondDigits: 3})].join(' | '));
t('invalid date', () => f('en', {}, NaN));
t('out of range date', () => f('en', {}, 8.64e15 + 1));
t('date object arg', () => f('en', {dateStyle: 'short'}, new Date(T0)));
t('string arg', () => f('en', {dateStyle: 'short'}, '2020-01-01'));
t('supportedLocalesOf', () => Intl.DateTimeFormat.supportedLocalesOf(['en-GB', 'de', 'fr', 'ja', 'zh-Hant-TW', 'xx', 'tlh']));
"""

DURATION_FORMAT = r"""
const DF = Intl.DurationFormat;
const d = {years: 1, months: 2, weeks: 3, days: 4, hours: 5, minutes: 6, seconds: 7, milliseconds: 8, microseconds: 9, nanoseconds: 10};
t('styles', () => ['long', 'short', 'narrow', 'digital'].map(s => new DF('en', {style: s}).format(d)).join(' | '));
t('singular', () => ['long', 'short', 'narrow'].map(s => new DF('en', {style: s}).format({years: 1, months: 1, weeks: 1, days: 1, hours: 1, minutes: 1, seconds: 1, milliseconds: 1})).join(' | '));
for (const l of ['de', 'fr', 'es', 'ja', 'zh', 'ru', 'ar', 'pt', 'it', 'ko', 'nl', 'pl', 'sv', 'tr', 'hi']) {
  t(l, () => ['long', 'short', 'narrow', 'digital'].map(s => new DF(l, {style: s}).format({days: 1, hours: 2, minutes: 1, seconds: 30})).join(' | ') + ' | ' + new DF(l, {style: 'long'}).format({years: 5, months: 2, weeks: 1}));
}
t('digital', () => [{hours: 1, minutes: 2, seconds: 3}, {minutes: 2, seconds: 3}, {hours: 10}, {seconds: 3, milliseconds: 450}, {days: 2, hours: 3, minutes: 4}, {hours: -1, minutes: -2}, {hours: 100, minutes: 59, seconds: 59}, {milliseconds: 5}, {seconds: 59, nanoseconds: 1}].map(x => new DF('en', {style: 'digital'}).format(x)).join(' | '));
t('digital fractionalDigits', () => [0, 2, 9].map(n => new DF('en', {style: 'digital', fractionalDigits: n}).format({seconds: 3, milliseconds: 456, microseconds: 789})).join(' | '));
t('fractionalDigits bad', () => new DF('en', {fractionalDigits: 10}));
t('unit options', () => [new DF('en', {hours: 'numeric', minutes: '2-digit'}).format({hours: 1, minutes: 5}), new DF('en', {minutes: 'numeric', seconds: '2-digit'}).format({minutes: 1, seconds: 5}), new DF('en', {hoursDisplay: 'always'}).format({minutes: 5}), new DF('en', {style: 'long', daysDisplay: 'always'}).format({hours: 3}), new DF('en', {seconds: 'narrow', milliseconds: 'numeric'}).format({seconds: 1, milliseconds: 5}), new DF('en', {milliseconds: 'numeric'}).format({seconds: 2, milliseconds: 5, microseconds: 6}), new DF('en', {years: 'narrow', days: 'long'}).format({years: 2, days: 1}), new DF('en', {style: 'digital', hoursDisplay: 'auto'}).format({minutes: 3}), new DF('en', {style: 'narrow', secondsDisplay: 'always', minutesDisplay: 'always'}).format({hours: 1})].join(' | '));
t('empty', () => new DF('en').format({}));
t('zeros', () => [new DF('en').format({seconds: 0}), new DF('en', {style: 'digital'}).format({seconds: 0}), new DF('en', {style: 'long'}).format({hours: 0, minutes: 0})].join(' | '));
t('negative', () => [new DF('en', {style: 'long'}).format({days: -1, hours: -2}), new DF('en', {style: 'narrow'}).format({seconds: -5})].join(' | '));
t('mixed signs', () => new DF('en').format({days: -1, hours: 2}));
t('fractional field', () => new DF('en').format({hours: 1.5}));
t('string input', () => new DF('en').format('P1DT2H'));
t('bad string', () => new DF('en').format('1 day'));
t('temporal input', () => new DF('en').format(Temporal.Duration.from('PT1H30M')));
t('undefined input', () => new DF('en').format(undefined));
t('unknown fields', () => new DF('en').format({foo: 1}));
t('bad style', () => new DF('en', {style: 'tiny'}));
t('conflicting styles', () => new DF('en', {hours: 'numeric', minutes: 'long'}));
t('bad display', () => new DF('en', {hoursDisplay: 'never'}));
t('parts', () => JSON.stringify(new DF('en').formatToParts({hours: 1, minutes: 30})));
t('parts digital', () => JSON.stringify(new DF('en', {style: 'digital'}).formatToParts({hours: 1, minutes: 30, seconds: 5, milliseconds: 250})));
t('parts long', () => JSON.stringify(new DF('fr', {style: 'long'}).formatToParts({years: 1, days: 1234})));
t('resolved narrow', () => new DF('fr', {style: 'narrow'}).resolvedOptions());
t('resolved digital', () => new DF('en', {style: 'digital', fractionalDigits: 3}).resolvedOptions());
t('resolved mixed', () => new DF('de-u-nu-arab', {style: 'short', minutes: 'numeric', daysDisplay: 'always'}).resolvedOptions());
t('numbering system', () => [new DF('ar-u-nu-arab', {style: 'digital'}).format({hours: 12, minutes: 34}), new DF('en', {numberingSystem: 'deva'}).format({hours: 3, minutes: 4})].join(' | '));
t('large values', () => [new DF('en').format({hours: 1234567}), new DF('en', {style: 'digital'}).format({hours: 1234567, minutes: 1})].join(' | '));
t('supportedLocalesOf', () => DF.supportedLocalesOf(['en', 'de', 'xx']));
t('no new', () => DF('en'));
"""

LOCALE = r"""
const L = Intl.Locale;
t('basic', () => { const l = new L('en-Latn-US-u-ca-gregory-co-phonebk-hc-h12-kf-upper-kn-nu-latn-fw-mon'); return [l.toString(), l.baseName, l.language, l.script, l.region, l.calendar, l.collation, l.hourCycle, l.caseFirst, l.numeric, l.numberingSystem, l.firstDayOfWeek, l.variants].join('|'); });
t('minimal getters', () => { const l = new L('fr'); return [l.toString(), l.baseName, l.language, l.script, l.region, l.calendar, l.collation, l.hourCycle, l.caseFirst, l.numeric, l.numberingSystem, l.firstDayOfWeek, l.variants].join('|'); });
t('variants', () => [new L('sl-rozaj-biske-1994').variants, new L('de-1996-1901').toString(), new L('ca-ES-valencia').baseName].join('|'));
t('options', () => new L('en', {region: 'GB', script: 'Latn', calendar: 'buddhist', collation: 'emoji', hourCycle: 'h23', caseFirst: 'lower', numeric: true, numberingSystem: 'arab', firstDayOfWeek: 'tue', language: 'fr', variants: 'fonipa'}).toString());
t('options override', () => new L('en-US-u-ca-japanese', {calendar: 'gregory'}).toString());
t('options numeric false', () => new L('en-u-kn', {numeric: false}).toString());
t('firstDayOfWeek numbers', () => [0, 1, 7, 'sun', 'mon', 'wed'].map(v => new L('en', {firstDayOfWeek: v}).firstDayOfWeek).join(','));
t('maximize', () => ['en', 'zh', 'zh-TW', 'zh-Hant', 'zh-HK', 'sr', 'sr-ME', 'und', 'und-JP', 'und-Arab', 'ar', 'und-Cyrl', 'pt', 'es-419', 'de-CH', 'und-150', 'ku', 'mn-Mong', 'hi-Latn', 'en-u-ca-gregory', 'az-IR', 'uz-AF', 'pa-PK', 'und-419', 'fr-x-private', 'xx', 'und-Latn-RU', 'yue', 'ja-US'].map(s => new L(s).maximize().toString()).join(' '));
t('minimize', () => ['en-Latn-US', 'zh-Hans-CN', 'zh-Hant-TW', 'zh-Hant', 'zh-Hant-HK', 'sr-Cyrl-RS', 'sr-Latn-RS', 'en-Latn-GB', 'und', 'de-Latn-DE-u-co-phonebk', 'ja-Jpan-JP', 'pt-Latn-BR', 'pt-Latn-PT', 'es-Latn-419', 'en-Latn', 'und-Latn', 'az-Arab-IR', 'hi-Latn-IN', 'xx-Latn-YY'].map(s => new L(s).minimize().toString()).join(' '));
t('info ar-EG', () => { const l = new L('ar-EG'); return JSON.stringify([l.getCalendars(), l.getCollations(), l.getHourCycles(), l.getNumberingSystems(), l.getTimeZones(), l.getTextInfo(), l.getWeekInfo()]); });
for (const s of ['en-US', 'de', 'ja-JP', 'he-IL', 'fa-IR', 'en-GB', 'pt-BR', 'zh-TW', 'en-u-ca-japanese-hc-h23-nu-thai-fw-fri-co-emoji', 'und', 'ar-SA', 'hi-IN', 'th-TH', 'ur-PK', 'en-US-u-hc-h11', 'fr-CA'])
  t('info ' + s, () => { const l = new L(s); return JSON.stringify([l.getCalendars(), l.getCollations(), l.getHourCycles(), l.getNumberingSystems(), l.getTimeZones(), l.getTextInfo(), l.getWeekInfo()]); });
t('getters as properties', () => ['calendars', 'hourCycles', 'timeZones', 'textInfo', 'weekInfo'].map(k => typeof new L('en-US')[k]).join(','));
t('bad tag', () => new L('en_US'));
t('bad tag number', () => new L(5));
t('bad tag missing', () => new L());
t('bad empty', () => new L(''));
t('bad region option', () => new L('en', {region: '123x'}));
t('bad script option', () => new L('en', {script: 'Lat'}));
t('bad language option', () => new L('en', {language: 'x'}));
t('bad calendar option', () => new L('en', {calendar: 'a'}));
t('bad hourCycle option', () => new L('en', {hourCycle: 'h25'}));
t('bad caseFirst option', () => new L('en', {caseFirst: 'title'}));
t('long firstDayOfWeek', () => new L('en', {firstDayOfWeek: 'monday'}).toString() + ' ' + new L('en', {firstDayOfWeek: 'monday'}).firstDayOfWeek);
t('bad firstDayOfWeek', () => new L('en', {firstDayOfWeek: 'x'}));
t('bad variants option', () => new L('en', {variants: 'a'}));
t('dup variants option', () => new L('en', {variants: 'fonipa-fonipa'}));
t('no new', () => L('en'));
t('from locale', () => new L(new L('fr-CA')).toString());
t('from locale with opts', () => new L(new L('fr-CA-u-ca-buddhist'), {region: 'FR'}).toString());
t('toJSON', () => JSON.stringify(new L('en-us')));
t('aliases', () => [new L('iw-IL').toString(), new L('sh').toString(), new L('en-u-ca-islamicc').calendar, new L('und-Qaai').script, new L('en-BU').region, new L('cmn').toString(), new L('in').language].join());
t('numeric', () => [new L('en-u-kn-false').numeric, new L('en-u-kn').numeric, new L('en').numeric, new L('en-u-kn-true').toString()].join());
t('used in NumberFormat', () => new Intl.NumberFormat(new L('de-CH')).format(1234.5));
t('used in getCanonicalLocales', () => Intl.getCanonicalLocales([new L('EN-us'), 'fr']));
t('tag', () => Object.prototype.toString.call(new L('en')));
"""

CANONICAL = r"""
const tags = ['EN-us', 'zh-hant-tw', 'sr-latn-rs', 'de-DE-u-co-phonebk', 'en-US-u-ca-gregory-nu-latn', 'und', 'iw', 'in-ID', 'ji', 'mo', 'sgn-GR', 'art-lojban',
  'i-klingon', 'en-gb-oed', 'x-private', 'en-a-bbb-x-a-ccc', 'de-1996-1901', 'ja-Latn-hepburn-heploc', 'en-u-kn', 'en-u-kn-true', 'en-t-zh-latn-m0-names',
  'cmn-hans-cn', 'aar', 'sh', 'no-bok', 'en-US-POSIX', 'hy-arevela', 'en-u-ca-ethiopic-amete-alem', 'en-u-tz-usnyc', 'en-u-ms-imperial', 'tl', 'zh-yue',
  'en-u-ks-primary', 'en-u-ca-islamicc', 'de-u-zz-xyz-aa-bb', 'en-z-zz-u-xx', 'en-u-attr-ca-gregory', 'EN-LATN-us-u-CA-gregory', 'sl-rozaj-biske-1994', 'und-Qaai',
  'en-BU', 'de-DD', 'en-u-rg-gbzzzz', 'en-u-sd-usca', 'en-u-tz-cnckg', 'en-t-iw', 'zh-u-co-pinyin-t-iw-m0-ungegn', 'ru-SU', 'sr-u-kn-false-co-phonebk', 'aa-SAAHO',
  'hy-arevmda', 'cel-gaulish', 'zh-guoyu', 'en-u-ca-japanese-hc-h23', 'zh-min-nan', 'zh-cmn', 'en-u-ks-tertiary', 'en-u-kf-yes', 'en-u-kc-no', 'en-u-nu-traditio',
  'en-CS', 'sr-YU', 'und-AN', 'en-NT', 'mn-Mong', 'swc', 'tw', 'mo-MD', 'en-Qaai', 'und-u-rg-no23', 'und-u-sd-no23', 'en-u-dx-thai', 'en-t-en-latn-us-h0-hybrid',
  'en-u-ca-gregory-ca-buddhist', 'en-a-aaa-b-bbb-a-ccc', 'en-x-u-foo', 'en-US-x-twain', 'x-whatever', 'root', 'en-0abc', 'en-abcde', 'en-12345', 'en-1abc',
  'abcd', 'abcde-US', 'ab-cdefg', 'en-Latn-Latn', 'en-US-US', 'en-u', 'en-t', 'en-u-', 'en--US', 'en-u-ca', 'en-u-12-xx', 'en-t-x-y', 'İn', 'en-ßS'];
for (const s of tags) t(s, () => Intl.getCanonicalLocales(s)[0]);
t('array', () => Intl.getCanonicalLocales(['en-US', 'en-us', 'EN-US', 'fr', 'de-de', 'fr']));
t('array-like', () => Intl.getCanonicalLocales({length: 2, 0: 'fr', 1: 'de-de'}));
t('number', () => Intl.getCanonicalLocales(5));
t('null', () => Intl.getCanonicalLocales(null));
t('undefined', () => Intl.getCanonicalLocales());
t('non-string element', () => Intl.getCanonicalLocales([5]));
t('null element', () => Intl.getCanonicalLocales([null]));
t('locale object element', () => Intl.getCanonicalLocales([new Intl.Locale('en-latn')]));
t('empty array', () => Intl.getCanonicalLocales([]));
t('one bad in list', () => Intl.getCanonicalLocales(['en', 'not_valid']));
"""

COLLATOR = r"""
const C = Intl.Collator;
const words = ['b', 'a', 'B', 'A', 'ä', 'á', 'z', '10', '9', 'Z', 'aa', 'a a', 'résumé', 'resume', 'Résumé', '', 'ab', 'a-b', 'Ab', 'æ', 'ß', 'ss', 'ø', 'o', 'œ', 'ç', 'c', 'ñ', 'n'];
t('en', () => [...words].sort(new C('en').compare).join(','));
t('numeric', () => ['item10', 'item9', 'item1', 'item100', 'Item2', 'item02', 'item 3', 'x1.5', 'x1.10'].sort(new C('en', {numeric: true}).compare).join(','));
t('non-numeric', () => ['item10', 'item9', 'item1', 'item100', 'Item2'].sort(new C('en').compare).join(','));
t('sensitivity', () => ['base', 'accent', 'case', 'variant'].map(s => { const c = new C('en', {sensitivity: s}); return s + ':' + [c.compare('a', 'A'), c.compare('a', 'á'), c.compare('a', 'b'), c.compare('a', 'a'), c.compare('A', 'Á'), c.compare('ß', 'ss'), c.compare('æ', 'ae')].join(','); }).join(' '));
t('caseFirst', () => ['upper', 'lower', 'false'].map(cf => ['a', 'A', 'b', 'B', 'ab', 'Ab', 'aB'].sort(new C('en', {caseFirst: cf}).compare).join('')).join(' '));
t('ignorePunctuation', () => [new C('en', {ignorePunctuation: true}).compare('a-b', 'ab'), new C('en', {ignorePunctuation: true}).compare('a b', 'ab'), new C('en').compare('a-b', 'ab'), new C('th').resolvedOptions().ignorePunctuation, new C('en').resolvedOptions().ignorePunctuation].join());
for (const l of ['de', 'sv', 'es', 'da', 'fr', 'tr', 'pl', 'cs', 'fi', 'ja', 'zh', 'ru', 'ar', 'de-u-co-phonebk', 'es-u-co-trad', 'zh-u-co-pinyin', 'zh-u-co-stroke'])
  t('locale ' + l, () => ['Äpfel', 'Zebra', 'Apfel', 'Ofen', 'Öl', 'å', 'ä', 'ö', 'z', 'ñ', 'n', 'ch', 'cz', 'ı', 'i', 'İ', 'ł', 'l', 'č', 'h', 'ж', 'я', 'а', '中', '国', 'あ', 'ア', 'ب', 'ا', 'll', 'lz'].sort(new C(l).compare).join(','));
t('usage search', () => [new C('en', {usage: 'search', sensitivity: 'base'}).compare('Résumé', 'resume'), new C('en', {usage: 'search'}).compare('a', 'A')].join());
t('resolved kn kf co', () => new C('de-u-kn-kf-upper-co-phonebk').resolvedOptions());
t('resolved options', () => new C('en', {numeric: true, caseFirst: 'lower', sensitivity: 'base', usage: 'search', collation: 'emoji'}).resolvedOptions());
t('resolved ext overridden', () => new C('en-u-kn-true-kf-lower', {numeric: false, caseFirst: 'upper'}).resolvedOptions());
t('resolved bad collation', () => new C('en-u-co-bogus', {collation: 'standard'}).resolvedOptions());
t('resolved search co', () => new C('de-u-co-search').resolvedOptions());
t('bad sensitivity', () => new C('en', {sensitivity: 'medium'}));
t('bad usage', () => new C('en', {usage: 'filter'}));
t('bad caseFirst', () => new C('en', {caseFirst: 'title'}));
t('bad collation', () => new C('en', {collation: 'a!'}).resolvedOptions().collation);
t('compare bound', () => { const c = new C('en'); const cmp = c.compare; return [cmp('a', 'b'), cmp === c.compare, cmp.length, cmp.name].join(); });
t('compare coercion', () => new C('en').compare(10, 9) + ',' + new C('en').compare(undefined, 'undefined') + ',' + new C('en').compare(null, 'null'));
t('localeCompare', () => [['a', 'b'], ['b', 'a'], ['a', 'A'], ['ä', 'a', 'de', {sensitivity: 'base'}], ['10', '2', undefined, {numeric: true}], ['é', 'é'], ['a', 'a\u0000'], ['ı', 'I', 'tr']].map(([x, y, l, o]) => x.localeCompare(y, l, o)).join(','));
t('localeCompare bad locale', () => 'a'.localeCompare('b', 'en_US'));
t('unicode ordering', () => ['\u{1F600}', 'Ω', 'ж', 'a', '中', '1', ' ', '_', '-', '!', '\t', '€', '$', ' ', 'Ⅳ', '½', '①', '́', 'ǆ', 'ﬁ', 'Å', 'Å'].sort(new C('en').compare).map(s => s.codePointAt(0).toString(16)).join(' '));
t('large sort', () => { const xs = []; for (let i = 0; i < 300; i++) xs.push(String.fromCharCode(65 + (i * 7) % 26) + (i % 3 ? 'é' : 'e') + (i * 13) % 100); return xs.sort(new C('fr', {numeric: true}).compare).slice(0, 25).join(' '); });
t('supportedLocalesOf', () => C.supportedLocalesOf(['fr-CA', 'xx', 'de-u-co-phonebk']));
"""

SEGMENTER = r"""
const S = Intl.Segmenter;
const seg = (o, s, l = 'en') => [...new S(l, o).segment(s)];
t('grapheme', () => seg({}, 'éa👨‍👩‍👧🇺🇸🇩🇪x\r\nक्षि한국어é̈👍🏽🏳️‍🌈각a‍b').map(x => JSON.stringify(x.segment) + '@' + x.index).join('|'));
t('grapheme keys', () => Object.keys(seg({}, 'ab')[0]).join(','));
t('word', () => seg({granularity: 'word'}, "Hello, world! It's 3.14 o'clock—e-mail me at a@b.co. 你好世界 日本語です").map(x => x.segment + (x.isWordLike ? '*' : '') + '@' + x.index).join('|'));
t('word keys', () => Object.keys(seg({granularity: 'word'}, 'ab')[0]).join(','));
t('word numbers', () => seg({granularity: 'word'}, '1,000.5 $20 ab12 x_y 3rd 2024-01-05 1e10 €5 50% U.S.A. can\'t "quoted" (paren)').map(x => x.segment + (x.isWordLike ? '*' : '')).join('|'));
t('word scripts', () => seg({granularity: 'word'}, 'Привет мир שלום עולם مرحبا بالعالم Γειά σου κόσμε 안녕하세요 세계').filter(x => x.isWordLike).map(x => x.segment).join('|'));
t('word th', () => seg({granularity: 'word'}, 'สวัสดีครับ', 'th').map(x => x.segment).join('|'));
t('word ja', () => seg({granularity: 'word'}, '今日は良い天気ですね。カタカナ', 'ja').map(x => x.segment).join('|'));
t('word emoji', () => seg({granularity: 'word'}, 'hi👋🏽 there🇫🇷!').map(x => x.segment + (x.isWordLike ? '*' : '')).join('|'));
t('sentence', () => seg({granularity: 'sentence'}, 'Mr. Smith went home. He said "Hi!" Then left? Yes... ok\nNew line. 3.5 is a number. End').map(x => JSON.stringify(x.segment)).join(' '));
t('sentence more', () => seg({granularity: 'sentence'}, 'Is it?! No. (Really.) e.g. this one. U.S. ships... "Quote." Next Para. 日本語です。次の文。Что? Да!').map(x => JSON.stringify(x.segment)).join(' '));
t('sentence keys', () => Object.keys(seg({granularity: 'sentence'}, 'A. B.')[0]).join(','));
t('containing', () => { const s = new S('en', {granularity: 'word'}).segment('foo bar baz'); return [0, 2, 3, 4, 10, 11, -1, 1.7, '4', NaN].map(i => JSON.stringify(s.containing(i))).join(' '); });
t('containing grapheme', () => { const s = new S('en').segment('a👨‍👩‍👧b'); return [0, 1, 3, 8, 9].map(i => { const r = s.containing(i); return r.segment + '@' + r.index; }).join(' '); });
t('resolved', () => [new S('fr', {granularity: 'word'}).resolvedOptions(), new S().resolvedOptions(), new S('ja-JP-u-co-emoji', {granularity: 'sentence'}).resolvedOptions()].map(JSON.stringify).join(' '));
t('bad granularity', () => new S('en', {granularity: 'line'}));
t('bad options', () => new S('en', 5));
t('no new', () => S('en'));
t('iterator', () => { const s = new S().segment('ab'); const it = s[Symbol.iterator](); return [typeof it.next, Object.prototype.toString.call(it), Object.prototype.toString.call(s), JSON.stringify(it.next()), JSON.stringify(it.next()), JSON.stringify(it.next())].join(' '); });
t('segments reusable', () => { const s = new S('en', {granularity: 'word'}).segment('a b'); return [...s].length + ',' + [...s].length; });
t('empty', () => seg({}, '').length + ' ' + JSON.stringify(new S().segment('').containing(0)));
t('coercion', () => seg({}, 12).map(x => x.segment).join('|') + ' ' + seg({}, undefined).length);
t('lone surrogates', () => seg({}, 'a\ud800b\udc00').map(x => x.segment.length + '@' + x.index).join('|'));
t('long text', () => { const text = 'The quick brown fox. '.repeat(50); return seg({granularity: 'word'}, text).filter(x => x.isWordLike).length + ' ' + seg({granularity: 'sentence'}, text).length + ' ' + seg({}, text).length; });
"""

PLURAL_RULES = r"""
const P = Intl.PluralRules;
t('en', () => [0, 1, 2, 1.5, '1.0', -1, 1e21, NaN, Infinity, 0.1].map(n => new P('en').select(n)).join(','));
t('en ordinal', () => [0, 1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111, 112, 1001, -1, 1.5].map(n => new P('en', {type: 'ordinal'}).select(n)).join(','));
const langs = ['ar', 'ru', 'pl', 'fr', 'ja', 'cy', 'cs', 'lt', 'he', 'ga', 'sl', 'lv', 'ro', 'pt', 'pt-PT', 'is', 'mk', 'br', 'gd', 'mt', 'uk', 'be', 'hr', 'sr', 'bs', 'da', 'si', 'ksh', 'es', 'it', 'de', 'zh', 'ko', 'hi', 'bn', 'fil', 'ka', 'kw', 'sk', 'gv', 'lag', 'shi', 'tzm', 'ca', 'sv', 'nl', 'fa', 'am', 'ur', 'sw', 'ti', 'xx'];
const nums = [0, 1, 2, 3, 4, 5, 6, 7, 11, 12, 15, 19, 20, 21, 22, 25, 100, 101, 102, 111, 1000000, 0.5, 1.5, 2.5, 0.1, 1.1];
for (const l of langs) t(l, () => nums.map(n => new P(l).select(n)).join(',') + ' / ' + nums.map(n => new P(l, {type: 'ordinal'}).select(n)).join(',') + ' / ' + new P(l).resolvedOptions().pluralCategories.join(',') + ' / ' + new P(l, {type: 'ordinal'}).resolvedOptions().pluralCategories.join(','));
t('digits', () => [new P('en', {minimumFractionDigits: 1}).select(1), new P('en', {maximumSignificantDigits: 1}).select(1.2), new P('en', {maximumFractionDigits: 0}).select(1.4), new P('fr', {maximumFractionDigits: 0}).select(1.6), new P('en', {roundingMode: 'floor', maximumFractionDigits: 0}).select(1.9), new P('en', {minimumSignificantDigits: 3}).select(1)].join());
t('notation compact', () => [new P('fr', {notation: 'compact'}).select(1e6), new P('fr').select(1e6), new P('es', {notation: 'compact'}).select(1e6), new P('en', {notation: 'scientific'}).select(1)].join());
t('selectRange', () => [new P('en').selectRange(1, 2), new P('en').selectRange(1, 1), new P('fr').selectRange(0, 1), new P('fr').selectRange(1, 2), new P('ar').selectRange(1, 3), new P('ru').selectRange(1, 2), new P('pl').selectRange(2, 5), new P('ja').selectRange(1, 2), new P('en').selectRange(5, 1)].join());
t('selectRange NaN', () => new P('en').selectRange(5, NaN));
t('selectRange missing', () => new P('en').selectRange(5));
t('resolved ar ordinal', () => new P('ar', {type: 'ordinal'}).resolvedOptions());
t('resolved en', () => new P('en').resolvedOptions());
t('resolved digits', () => new P('de', {minimumIntegerDigits: 2, maximumSignificantDigits: 3, roundingPriority: 'lessPrecision', roundingIncrement: 1, trailingZeroDisplay: 'stripIfInteger'}).resolvedOptions());
t('bad type', () => new P('en', {type: 'cardinalish'}));
t('bad digits', () => new P('en', {maximumFractionDigits: 200}));
t('no new', () => P('en'));
t('select bigint', () => new P('en').select(1n));
t('supportedLocalesOf', () => P.supportedLocalesOf(['en', 'ar-EG', 'xx']));
"""

RELATIVE_TIME = r"""
const R = Intl.RelativeTimeFormat;
const units = ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'];
t('en always', () => units.map(u => [-2, -1, 0, 1, 2].map(v => new R('en').format(v, u)).join(',')).join(' | '));
t('en auto', () => units.map(u => [-2, -1, 0, -0, 1, 2].map(v => new R('en', {numeric: 'auto'}).format(v, u)).join(',')).join(' | '));
t('plural units', () => ['seconds', 'minutes', 'hours', 'days', 'weeks', 'months', 'quarters', 'years'].map(u => new R('en').format(3, u)).join(' | '));
t('fractions', () => [1.5, -0.5, 1234.567, -1e6, 1e-7].map(v => new R('en').format(v, 'minute')).join(' | '));
t('styles', () => ['long', 'short', 'narrow'].map(s => units.map(u => new R('en', {style: s}).format(-3, u) + ';' + new R('en', {style: s}).format(1, u)).join(',')).join(' | '));
for (const l of ['de', 'fr', 'es', 'it', 'pt', 'ja', 'zh', 'ko', 'ru', 'ar', 'pl', 'nl', 'tr', 'he', 'hi', 'sv', 'xx']) {
  t(l, () => [new R(l, {numeric: 'auto'}).format(-1, 'day'), new R(l, {numeric: 'auto'}).format(1, 'day'), new R(l, {numeric: 'auto'}).format(0, 'year'), new R(l).format(3, 'hours'), new R(l).format(-5, 'minutes'), new R(l).format(1, 'month'), new R(l, {style: 'short'}).format(-2, 'week'), new R(l).format(-21, 'second'), new R(l).resolvedOptions().locale].join(' | '));
}
t('pl matrix', () => ['long', 'short', 'narrow'].map(st => units.map(u => [1, 2, 5, 12, 22, 1.5, -1, -3, -5, -24].map(v => new R('pl', {style: st}).format(v, u)).join(',')).join(' ; ')).join(' | '));
t('parts', () => JSON.stringify(new R('en').formatToParts(-1234.5, 'day')));
t('parts auto', () => JSON.stringify(new R('en', {numeric: 'auto'}).formatToParts(-1, 'day')));
t('parts future de', () => JSON.stringify(new R('de').formatToParts(100, 'year')));
t('parts negative zero', () => JSON.stringify(new R('en').formatToParts(-0, 'second')));
t('bad unit', () => new R('en').format(1, 'fortnight'));
t('bad unit plural', () => new R('en').format(1, 'Days'));
t('bad value', () => new R('en').format(Infinity, 'day'));
t('bad value NaN', () => new R('en').format('abc', 'day'));
t('missing unit', () => new R('en').format(1));
t('bad style', () => new R('en', {style: 'tiny'}));
t('bad numeric', () => new R('en', {numeric: 'sometimes'}));
t('resolved', () => new R('es-MX', {style: 'narrow', numeric: 'auto'}).resolvedOptions());
t('resolved nu', () => new R('ar-EG').resolvedOptions());
t('resolved nu ext', () => new R('en-u-nu-thai').resolvedOptions());
t('nu ext format', () => new R('en-u-nu-thai').format(12, 'day'));
t('no new', () => R('en'));
t('supportedLocalesOf', () => R.supportedLocalesOf(['en', 'zz']));
"""

LIST_FORMAT = r"""
const LF = Intl.ListFormat;
const types = ['conjunction', 'disjunction', 'unit'];
const styles = ['long', 'short', 'narrow'];
for (const l of ['en', 'en-GB', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'ja', 'zh', 'ko', 'ru', 'ar', 'he', 'hi', 'pl', 'sv', 'tr', 'xx']) {
  t(l, () => types.map(ty => styles.map(st => new LF(l, {type: ty, style: st}).format(['A', 'B', 'C'])).join(' ; ')).join(' | ') + ' | ' + new LF(l).format(['X', 'Y']));
}
t('sizes', () => [[], ['x'], ['x', 'y'], ['w', 'x', 'y', 'z'], ['1', '2', '3', '4', '5', '6']].map(a => new LF('en').format(a) + '/' + new LF('en', {type: 'disjunction'}).format(a)).join(' | '));
t('es y/e o/u', () => [new LF('es').format(['agua', 'hielo']), new LF('es').format(['agua', 'iglesia']), new LF('es').format(['agua', 'Hilo']), new LF('es', {type: 'disjunction'}).format(['uno', 'otro']), new LF('es', {type: 'disjunction'}).format(['siete', 'ocho']), new LF('es', {type: 'disjunction'}).format(['siete', '11'])].join(' | '));
t('he vav', () => new LF('he').format(['א', 'ב']));
t('parts', () => JSON.stringify(new LF('en').formatToParts(['a', 'b', 'c'])));
t('parts single', () => JSON.stringify(new LF('en').formatToParts(['only'])));
t('parts unit narrow', () => JSON.stringify(new LF('en', {type: 'unit', style: 'narrow'}).formatToParts(['5 ft', '2 in'])));
t('non-string element', () => new LF('en').format(['a', 5]));
t('non-iterable', () => new LF('en').format(5));
t('undefined list', () => new LF('en').format());
t('iterable', () => new LF('en').format(new Set(['p', 'q'])) + ' / ' + new LF('en').format('xyz'));
t('generator', () => new LF('en').format((function* () { yield 'g1'; yield 'g2'; yield 'g3'; })()));
t('bad type', () => new LF('en', {type: 'either'}));
t('bad style', () => new LF('en', {style: 'tiny'}));
t('resolved', () => [new LF('en', {type: 'unit', style: 'short'}).resolvedOptions(), new LF().resolvedOptions(), new LF('de-AT-u-co-phonebk').resolvedOptions()].map(JSON.stringify).join(' '));
t('no new', () => LF('en'));
t('supportedLocalesOf', () => LF.supportedLocalesOf(['en', 'de', 'zz-ZZ']));
"""

DISPLAY_NAMES = r"""
const DN = Intl.DisplayNames;
const of = (l, o, c) => { try { return String(new DN(l, o).of(c)); } catch (e) { return e.constructor.name + ':' + e.message; } };
for (const l of ['en', 'de', 'fr', 'es', 'ja', 'zh', 'ru', 'ar', 'xx']) {
  t('region ' + l, () => ['US', 'DE', 'JP', '419', 'GB', 'ZZ', 'XK', 'us', '001', 'CN', 'BR', 'IN', '999'].map(c => of(l, {type: 'region'}, c)).join(' | '));
  t('language ' + l, () => ['en', 'en-US', 'fr-CA', 'zh-Hant', 'es-419', 'de', 'ja', 'xx', 'en-GB', 'pt-BR', 'ar', 'zh', 'nl-BE', 'sr-Latn', 'und', 'root'].map(c => of(l, {type: 'language'}, c)).join(' | '));
}
t('language standard', () => ['en-US', 'fr-CA', 'en-GB', 'zh-Hans', 'es-419', 'de-AT'].map(c => of('en', {type: 'language', languageDisplay: 'standard'}, c)).join(' | '));
t('script', () => ['Latn', 'Cyrl', 'Hans', 'Hant', 'Arab', 'Zzzz', 'latn', 'Grek', 'Jpan', 'Kore', 'Deva', 'Hebr'].map(c => of('en', {type: 'script'}, c) + '/' + of('de', {type: 'script'}, c)).join(' | '));
t('currency', () => ['USD', 'EUR', 'JPY', 'XYZ', 'gbp', 'CNY', 'INR', 'CHF', 'BTC'].map(c => of('en', {type: 'currency'}, c) + '/' + of('fr', {type: 'currency'}, c) + '/' + of('ja', {type: 'currency'}, c)).join(' | '));
t('calendar', () => ['gregory', 'japanese', 'islamic-umalqura', 'hebrew', 'xyz', 'buddhist', 'chinese', 'persian', 'iso8601', 'ethioaa', 'roc', 'dangi', 'indian', 'coptic', 'islamic-civil', 'islamicc'].map(c => of('en', {type: 'calendar'}, c)).join(' | '));
t('dateTimeField', () => ['era', 'year', 'quarter', 'month', 'weekOfYear', 'weekday', 'day', 'dayPeriod', 'hour', 'minute', 'second', 'timeZoneName'].map(c => of('en', {type: 'dateTimeField'}, c) + '/' + of('de', {type: 'dateTimeField'}, c)).join(' | '));
t('dateTimeField bad', () => of('en', {type: 'dateTimeField'}, 'millisecond'));
t('styles', () => ['long', 'short', 'narrow'].map(s => [of('en', {type: 'region', style: s}, 'US'), of('en', {type: 'region', style: s}, 'GB'), of('en', {type: 'currency', style: s}, 'USD'), of('en', {type: 'language', style: s}, 'en-US'), of('en', {type: 'dateTimeField', style: s}, 'month')].join(',')).join(' | '));
t('fallback none', () => [of('en', {type: 'region', fallback: 'none'}, 'QQ'), of('en', {type: 'region'}, 'QQ'), of('en', {type: 'language', fallback: 'none'}, 'xx'), of('en', {type: 'currency', fallback: 'none'}, 'XYZ'), of('en', {type: 'calendar', fallback: 'none'}, 'xyz'), of('en', {type: 'script', fallback: 'none'}, 'Qaaa')].join(','));
t('bad codes', () => [of('en', {type: 'region'}, 'USA1'), of('en', {type: 'language'}, 'en_US'), of('en', {type: 'script'}, 'Lat'), of('en', {type: 'currency'}, 'US'), of('en', {type: 'calendar'}, 'a'), of('en', {type: 'language'}, 'en-u-ca-gregory'), of('en', {type: 'region'}, ''), of('en', {type: 'language'}, 'root'), of('en', {type: 'language'}, 'en-x-priv')].join(' | '));
t('missing type', () => new DN('en'));
t('missing options', () => new DN('en', {}));
t('bad type', () => new DN('en', {type: 'country'}));
t('bad style', () => new DN('en', {type: 'region', style: 'medium'}));
t('bad fallback', () => new DN('en', {type: 'region', fallback: 'empty'}));
t('bad languageDisplay', () => new DN('en', {type: 'language', languageDisplay: 'local'}));
t('of missing', () => new DN('en', {type: 'region'}).of());
t('resolved currency', () => new DN('fr', {type: 'currency', style: 'short'}).resolvedOptions());
t('resolved language', () => new DN('en-GB', {type: 'language', languageDisplay: 'standard', fallback: 'none'}).resolvedOptions());
t('resolved region', () => new DN('de-AT-u-nu-arab', {type: 'region'}).resolvedOptions());
t('no new', () => DN('en', {type: 'region'}));
t('supportedLocalesOf', () => DN.supportedLocalesOf(['en', 'de', 'qq']));
"""

SERVICE = r"""
const ctors = ['Collator', 'DateTimeFormat', 'DisplayNames', 'DurationFormat', 'ListFormat', 'Locale', 'NumberFormat', 'PluralRules', 'RelativeTimeFormat', 'Segmenter'];
t('Intl keys', () => Object.getOwnPropertyNames(Intl).sort().join(','));
t('tag', () => [Intl, ...ctors.map(c => Intl[c].prototype)].map(x => Object.prototype.toString.call(x)).join(' '));
t('ctor lengths', () => ctors.map(c => c + ':' + Intl[c].length).join(','));
t('supportedLocalesOf each', () => ctors.filter(c => Intl[c].supportedLocalesOf).map(c => c + ':' + JSON.stringify(Intl[c].supportedLocalesOf(['en-US', 'xx-YY', 'de', 'tlh', 'zh-Hant-TW', 'pt-BR']))).join(' '));
t('supportedLocalesOf lookup', () => Intl.Collator.supportedLocalesOf('fr-CA', {localeMatcher: 'lookup'}));
t('supportedLocalesOf best fit', () => Intl.NumberFormat.supportedLocalesOf(['de-CH-1996', 'en-US-u-nu-thai'], {localeMatcher: 'best fit'}));
t('supportedLocalesOf empty', () => Intl.PluralRules.supportedLocalesOf([]));
t('supportedLocalesOf undefined', () => Intl.PluralRules.supportedLocalesOf());
t('supportedLocalesOf bad matcher', () => Intl.Segmenter.supportedLocalesOf('en', {localeMatcher: 'fuzzy'}));
t('supportedLocalesOf bad tag', () => Intl.ListFormat.supportedLocalesOf(['en', 'e']));
t('supportedLocalesOf null options', () => Intl.ListFormat.supportedLocalesOf('en', null));
t('supportedValuesOf', () => ['calendar', 'collation', 'currency', 'numberingSystem', 'timeZone', 'unit'].map(k => k + ':' + Intl.supportedValuesOf(k).length + ':' + Intl.supportedValuesOf(k).slice(0, 6).join(',')).join(' | '));
t('supportedValuesOf collation', () => Intl.supportedValuesOf('collation').join(','));
t('supportedValuesOf numberingSystem', () => Intl.supportedValuesOf('numberingSystem').join(','));
t('supportedValuesOf timeZone sample', () => { const z = Intl.supportedValuesOf('timeZone'); return [z.includes('UTC'), z.includes('Europe/Berlin'), z.includes('Arctic/Longyearbyen'), z.includes('Asia/Calcutta'), z.includes('Asia/Kolkata'), z.slice(-5).join(',')].join(' '); });
t('supportedValuesOf bad', () => Intl.supportedValuesOf('colour'));
t('supportedValuesOf sorted', () => ['calendar', 'currency', 'unit', 'timeZone'].map(k => { const a = Intl.supportedValuesOf(k); return a.every((x, i) => i === 0 || a[i - 1] < x); }).join());
t('default locale', () => ctors.filter(c => c !== 'Locale' && c !== 'DisplayNames').map(c => new Intl[c]().resolvedOptions().locale).join(','));
t('options null', () => new Intl.NumberFormat('en', null));
t('options primitive', () => new Intl.NumberFormat('en', 5).resolvedOptions().style);
t('locale fallback chain', () => ['de-CH-x-foo', 'zh-Hant-HK', 'en-AU', 'sr-Latn-ME', 'es-AR', 'pt-AO', 'fr-BE', 'no', 'nb-NO', 'iw', 'tl'].map(l => new Intl.NumberFormat(l).resolvedOptions().locale + '/' + new Intl.DateTimeFormat(l).resolvedOptions().locale + '/' + new Intl.Collator(l).resolvedOptions().locale).join(' '));
t('unicode ext filtering', () => [new Intl.Collator('en-u-kn-true-nu-arab-ca-japanese').resolvedOptions().locale, new Intl.DateTimeFormat('en-u-kn-true-nu-arab-ca-japanese-hc-h23').resolvedOptions().locale, new Intl.NumberFormat('en-u-kn-true-nu-arab-ca-japanese').resolvedOptions().locale, new Intl.PluralRules('en-u-nu-arab').resolvedOptions().locale].join(' '));
t('dtf subclass', () => { class My extends Intl.DateTimeFormat { hi() { return 'hi ' + this.format(0); } } return new My('en', {timeZone: 'UTC'}).hi(); });
t('nf subclass', () => { class My extends Intl.NumberFormat {} const m = new My('de'); return [m instanceof Intl.NumberFormat, m.format(1.5), Object.getPrototypeOf(m) === My.prototype].join(); });
t('legacy constructed symbol', () => { const nf = Intl.NumberFormat.call(Object.create(Intl.NumberFormat.prototype), 'en'); return typeof nf + ' ' + Intl.NumberFormat.prototype.format.call(nf, 12345); });
"""

TIERED = r"""
// Locale-sensitive formatting driven from user code: closures, sort comparators, maps, template literals.
const people = [['Zoë', 1234.5, 1700000000000], ['Ölaf', 99.99, 1600000000000], ['adam', 1e6, 1500000000000], ['Ádám', 0.5, 1400000000000], ['bob', -42, 1300000000000]];
const coll = new Intl.Collator('de', {sensitivity: 'base'});
const nf = new Intl.NumberFormat('de-DE', {style: 'currency', currency: 'EUR'});
const dtf = new Intl.DateTimeFormat('en', {dateStyle: 'medium', timeZone: 'UTC'});
const sorted = [...people].sort((a, b) => coll.compare(a[0], b[0]));
for (const [name, amt, ts] of sorted) console.log(`${name.padEnd(5)} ${nf.format(amt)} ${dtf.format(ts)}`);
const pr = new Intl.PluralRules('en', {type: 'ordinal'});
const suffix = {one: 'st', two: 'nd', few: 'rd', other: 'th'};
const ords = [];
for (let i = 1; i <= 25; i++) ords.push(i + suffix[pr.select(i)]);
console.log(ords.join(' '));
const rtf = new Intl.RelativeTimeFormat('en', {numeric: 'auto'});
console.log([-3, -1, 0, 1, 3].map(d => rtf.format(d, 'day')).join(', '));
const lf = new Intl.ListFormat('en', {type: 'conjunction'});
const groups = new Map();
for (const [name] of people) { const k = name.normalize('NFD')[0].toLowerCase(); groups.set(k, [...(groups.get(k) || []), name]); }
console.log([...groups].map(([k, v]) => k + ': ' + lf.format(v)).join('; '));
const seg = new Intl.Segmenter('en', {granularity: 'word'});
let words = 0;
for (const s of seg.segment('One two, three — four five! Six.')) if (s.isWordLike) words++;
console.log(words, [...new Intl.Segmenter().segment('👨‍👩‍👧x')].length);
console.log(new Intl.NumberFormat('en', {notation: 'compact'}).formatRange(1500, 2.5e6), new Intl.DurationFormat('en', {style: 'digital'}).format({hours: 7, minutes: 5}));
"""


MONTH_ERA_NAMES = r"""
// Month and era names for every locale/calendar combination, via formatToParts.
const locs = ['en', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'ru', 'ar', 'ja', 'ko', 'zh', 'zh-Hant'];
const cals = CALS;
const years = {gregory: 2023, buddhist: 2566, japanese: 2023, roc: 112, hebrew: 5784, 'islamic-umalqura': 1445, 'islamic-civil': 1445, 'islamic-tbla': 1445, persian: 1402, indian: 1945, coptic: 1739, ethiopic: 2015, ethioaa: 7515, chinese: 2023, dangi: 2023};
for (const c of cals) {
  const ms = [];
  const first = Temporal.PlainDate.from({calendar: c, year: years[c], month: 1, day: 15});
  for (let m = 0; m < first.monthsInYear; m++) ms.push(first.add({months: m}).toZonedDateTime('UTC').epochMilliseconds);
  for (const l of locs) {
    const row = ['long', 'short', 'narrow'].map(w => {
      const f = new Intl.DateTimeFormat(l + '-u-ca-' + c, {month: w, timeZone: 'UTC'});
      return ms.map(x => f.formatToParts(x).filter(p => p.type === 'month').map(p => p.value).join('')).join(',');
    });
    const eras = ['long', 'short', 'narrow'].map(w => {
      const f = new Intl.DateTimeFormat(l + '-u-ca-' + c, {era: w, year: 'numeric', timeZone: 'UTC'});
      return (c === 'chinese' || c === 'dangi' ? [ms[0]] : [ms[0], -62198755200000, -2e13]).map(x => f.formatToParts(x).filter(p => p.type === 'era').map(p => p.value).join('') || '-').join(',');
    });
    console.log(c + ' ' + l + ': ' + row.join(' / ') + ' || ' + eras.join(' / '));
  }
}
"""

UNIT_PATTERNS = r"""
// Every sanctioned unit in every unit-data locale, all three widths, several plural categories.
const units = Intl.supportedValuesOf('unit').concat(['kilometer-per-hour', 'meter-per-second', 'mile-per-hour', 'liter-per-kilometer', 'mile-per-gallon']);
const locs = ['en', 'en-IN', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'ru', 'ar', 'ja', 'ko', 'zh', 'zh-Hant'];
for (const l of locs) {
  for (const w of ['long', 'short', 'narrow']) {
    console.log(l + ' ' + w + ': ' + units.map(u => [1, 2, 5, 1.5, 22].map(v => new Intl.NumberFormat(l, {style: 'unit', unit: u, unitDisplay: w}).format(v)).join('|')).join(' ; '));
  }
}
"""

NUMBERING_SYSTEMS = r"""
// Every numbering system Intl.supportedValuesOf reports, through NumberFormat and DateTimeFormat.
const out = [];
for (const nu of Intl.supportedValuesOf('numberingSystem')) {
  let a, b;
  try { a = new Intl.NumberFormat('en-u-nu-' + nu).format(-9876543210.125); } catch (e) { a = e.constructor.name; }
  try { b = new Intl.DateTimeFormat('en', {numberingSystem: nu, timeZone: 'UTC', dateStyle: 'short', timeStyle: 'medium'}).format(1234567890123); } catch (e) { b = e.constructor.name; }
  const r = new Intl.NumberFormat('en', {numberingSystem: nu}).resolvedOptions().numberingSystem;
  console.log(nu + ': ' + a + ' | ' + b + ' | ' + r);
}
"""


EDGES = r"""
const nf = (l, o) => new Intl.NumberFormat(l, o);
// exact decimal strings and BigInts through significant/fraction rounding
t('exact sig', () => ['123456789012345678901234', '-98765432109876543210', '5', '0', '000123'].map(s => [nf('en', {maximumSignificantDigits: 3}).format(s), nf('en', {maximumSignificantDigits: 3, roundingMode: 'trunc'}).format(s), nf('en', {minimumSignificantDigits: 4}).format(s), nf('en', {minimumIntegerDigits: 8, useGrouping: false}).format(s)].join('/')).join(' | '));
t('exact frac', () => ['1.23456789012345678901', '-0.000000000000000000015', '99.995', '0.5', '-0.5'].map(s => [nf('en', {maximumFractionDigits: 2}).format(s), nf('en', {maximumFractionDigits: 2, roundingMode: 'trunc'}).format(s), nf('en', {maximumFractionDigits: 2, roundingMode: 'halfEven'}).format(s), nf('en', {maximumFractionDigits: 0, roundingMode: 'ceil'}).format(s), nf('en', {minimumFractionDigits: 25}).format(s)].join('/')).join(' | '));
t('exact bigint', () => [nf('en', {maximumSignificantDigits: 2}).format(987654321987654321n), nf('en', {notation: 'compact'}).format(987654321987654321n), nf('en', {notation: 'scientific'}).format(-987654321987654321n), nf('de', {style: 'percent'}).format(12n), nf('en', {style: 'currency', currency: 'JPY'}).format(10n ** 25n)].join(' | '));
t('tiny increment', () => [nf('en', {maximumFractionDigits: 2, minimumFractionDigits: 2, roundingIncrement: 50}).format(0.0001), nf('en', {maximumFractionDigits: 2, minimumFractionDigits: 2, roundingIncrement: 50, roundingMode: 'ceil'}).format(0.0001), nf('en', {maximumFractionDigits: 2, minimumFractionDigits: 2, roundingIncrement: 50, roundingMode: 'expand'}).format(-0.0001), nf('en', {maximumFractionDigits: 0, roundingIncrement: 5000}).format(1e-9)].join(' | '));
t('range pt', () => [nf('pt', {style: 'currency', currency: 'EUR'}).formatRange(3, 5), nf('pt', {style: 'currency', currency: 'EUR', signDisplay: 'always'}).formatRange(3, 5), nf('pt').formatRange(-3, 5), nf('pt', {signDisplay: 'always'}).formatRange(3, 5)].join(' | '));
t('range signed currency', () => [nf('en', {style: 'currency', currency: 'USD', signDisplay: 'always'}).formatRange(3, 5), nf('en', {style: 'currency', currency: 'USD'}).formatRange(-5, -3), nf('de', {style: 'currency', currency: 'EUR', signDisplay: 'always'}).formatRange(3, 5), nf('de', {style: 'currency', currency: 'EUR'}).formatRange(-5, -3), nf('en', {style: 'currency', currency: 'EUR', currencyDisplay: 'name'}).formatRange(1, 2), nf('ja', {style: 'unit', unit: 'kilometer'}).formatRange(1, 2)].join(' | '));
t('range parts currency de', () => JSON.stringify(nf('de', {style: 'currency', currency: 'EUR'}).formatRangeToParts(3, 5)));
t('unit parts locales', () => ['ja', 'zh', 'ko', 'de', 'fr', 'ar', 'ru'].map(l => JSON.stringify(nf(l, {style: 'unit', unit: 'hour', unitDisplay: 'long'}).formatToParts(2)) + JSON.stringify(nf(l, {style: 'unit', unit: 'percent', unitDisplay: 'narrow'}).formatToParts(5))).join(' '));
t('unit compound parts', () => JSON.stringify(nf('en', {style: 'unit', unit: 'liter-per-kilometer', unitDisplay: 'long'}).formatToParts(3)) + JSON.stringify(nf('fr', {style: 'unit', unit: 'kilometer-per-hour', unitDisplay: 'short'}).formatToParts(-3)));
t('legacy NumberFormat', () => { const o = Object.create(Intl.NumberFormat.prototype); const r = Intl.NumberFormat.call(o, 'de'); const fmt = Object.getOwnPropertyDescriptor(Intl.NumberFormat.prototype, 'format').get.call(o); return [r === o, fmt(12345.5), Intl.NumberFormat.prototype.resolvedOptions.call(o).locale, Object.getOwnPropertySymbols(o).length].join(); });
t('legacy DateTimeFormat', () => { const o = Object.create(Intl.DateTimeFormat.prototype); const r = Intl.DateTimeFormat.call(o, 'en', {timeZone: 'UTC'}); const fmt = Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, 'format').get.call(o); return [r === o, fmt(0), Intl.DateTimeFormat.prototype.resolvedOptions.call(o).timeZone].join(); });
t('legacy other', () => { const o = Object.create(Intl.Collator.prototype); const r = Intl.Collator.call(o, 'en'); return r === o; });
t('newTarget proto non-object', () => { const F = function () {}; F.prototype = 5; return [Intl.Collator, Intl.NumberFormat, Intl.DateTimeFormat, Intl.PluralRules, Intl.Segmenter, Intl.ListFormat, Intl.Locale].map(C => Object.getPrototypeOf(Reflect.construct(C, C === Intl.Locale ? ['en'] : [], F)) === C.prototype).join(); });
t('newTarget proto custom', () => { function F() {} F.prototype = Object.create(Intl.RelativeTimeFormat.prototype); const r = Reflect.construct(Intl.RelativeTimeFormat, ['en'], F); return [r instanceof F, r.format(1, 'day')].join(); });
// DateTimeFormat edges
const T0 = Date.UTC(2024, 0, 5, 14, 7, 9, 45);
const df = (l, o) => new Intl.DateTimeFormat(l, {timeZone: 'UTC', ...o});
t('frac alone', () => [df('en', {fractionalSecondDigits: 2}).format(T0), df('en', {minute: 'numeric', fractionalSecondDigits: 3}).format(T0), JSON.stringify(df('en', {fractionalSecondDigits: 1}).formatToParts(T0))].join(' | '));
t('tzname alone', () => [df('en', {timeZoneName: 'short'}).format(T0), df('de', {timeZoneName: 'long', timeZone: 'Asia/Tokyo'}).format(T0)].join(' | '));
t('chinese zh', () => [df('zh-u-ca-chinese', {dateStyle: 'long'}).format(T0), df('zh-u-ca-chinese', {year: 'numeric'}).format(T0), JSON.stringify(df('zh-u-ca-chinese', {year: 'numeric', month: 'long'}).formatToParts(T0)), df('ko-u-ca-dangi', {dateStyle: 'full'}).format(T0), df('ja-u-ca-chinese', {dateStyle: 'medium'}).format(T0)].join(' | '));
t('chinese leap month', () => [df('en-u-ca-chinese', {month: 'long', day: 'numeric'}).format(Date.UTC(2023, 2, 25)), df('zh-u-ca-chinese', {month: 'long', day: 'numeric'}).format(Date.UTC(2023, 2, 25)), df('en-u-ca-hebrew', {month: 'short', day: 'numeric', year: 'numeric'}).format(Date.UTC(2024, 1, 20)), df('en-u-ca-hebrew', {month: 'numeric'}).format(Date.UTC(2024, 1, 20))].join(' | '));
t('japanese eras', () => [Date.UTC(1989, 0, 7), Date.UTC(1989, 0, 8), Date.UTC(1926, 11, 25), Date.UTC(1912, 6, 30), Date.UTC(1873, 0, 1), Date.UTC(1800, 0, 1), Date.UTC(-100, 0, 1)].map(x => df('en-u-ca-japanese', {era: 'long', year: 'numeric', month: 'short', day: 'numeric'}).format(x) + '/' + df('ja-u-ca-japanese', {era: 'short', year: 'numeric'}).format(x)).join(' | '));
t('era widths cals', () => ['buddhist', 'roc', 'coptic', 'ethiopic', 'ethioaa', 'persian', 'indian', 'islamic-umalqura', 'hebrew', 'gregory'].map(c => ['long', 'short', 'narrow'].map(w => df('en-u-ca-' + c, {era: w, year: 'numeric'}).format(Date.UTC(1900, 0, 1)) + ';' + df('en-u-ca-' + c, {era: w, year: 'numeric'}).format(Date.UTC(-3000, 0, 1))).join(',')).join(' | '));
t('hc ext conflicts', () => [new Intl.DateTimeFormat('en-u-hc-h23', {hour: 'numeric', hourCycle: 'h11'}).resolvedOptions().locale, new Intl.DateTimeFormat('en-u-hc-h23', {hour: 'numeric', hour12: true}).resolvedOptions().locale, new Intl.DateTimeFormat('en-u-hc-h23', {hour: 'numeric', hourCycle: 'h23'}).resolvedOptions().locale, new Intl.DateTimeFormat('en-u-hc-h25', {hour: 'numeric'}).resolvedOptions().locale, new Intl.DateTimeFormat('en-u-ca-bogus-nu-bogus').resolvedOptions().locale, new Intl.DateTimeFormat('en-u-ca-islamic').resolvedOptions().calendar, new Intl.DateTimeFormat('en', {calendar: 'islamic-rgsa'}).resolvedOptions().calendar].join(' '));
t('temporal no overlap', () => df('en', {hour: 'numeric'}).format(Temporal.PlainDate.from('2024-01-05')));
t('temporal no overlap2', () => df('en', {year: 'numeric'}).format(Temporal.PlainTime.from('10:00')));
t('temporal partial overlap', () => [df('en', {year: 'numeric', hour: 'numeric'}).format(Temporal.PlainDate.from('2024-01-05')), df('en', {year: 'numeric', hour: 'numeric'}).format(Temporal.PlainTime.from('10:00')), df('en', {month: 'long', day: 'numeric', hour: 'numeric'}).format(Temporal.PlainMonthDay.from({calendar: 'gregory', monthCode: 'M01', day: 5})), df('en', {weekday: 'long', year: 'numeric', month: 'long'}).format(Temporal.PlainYearMonth.from({calendar: 'gregory', year: 2024, month: 1}))].join(' | '));
t('temporal defaults', () => [Temporal.PlainYearMonth.from({calendar: 'gregory', year: 2024, month: 1}), Temporal.PlainMonthDay.from({calendar: 'gregory', monthCode: 'M01', day: 5}), Temporal.PlainDateTime.from('2024-01-05T10:20:30'), Temporal.Instant.from('2024-01-05T10:20:30Z'), Temporal.PlainTime.from('10:20:30')].map(v => df('de', {}).format(v)).join(' | '));
t('temporal range cal mismatch', () => df('en', {dateStyle: 'short'}).formatRange(Temporal.PlainDate.from('2024-01-05[u-ca=gregory]'), Temporal.PlainDate.from('2024-01-06[u-ca=japanese]')));
t('temporal range parts', () => JSON.stringify(df('en', {dateStyle: 'medium', timeStyle: 'short'}).formatRangeToParts(Temporal.PlainDateTime.from('2024-01-05T10:00'), Temporal.PlainDateTime.from('2024-01-05T11:30'))));
t('range parts shared suffix', () => JSON.stringify(df('en', {month: 'long', day: 'numeric', year: 'numeric'}).formatRangeToParts(T0, T0 + 86400000 * 5)));
t('range parts different years', () => JSON.stringify(df('de', {dateStyle: 'medium'}).formatRangeToParts(T0, T0 + 86400000 * 400)));
t('format getter', () => { const d = df('en', {dateStyle: 'short'}); const f = d.format; return [f === d.format, f.name, f.length, f(T0), f()].map(String).slice(0, 4).join(','); });
t('format date edge', () => [df('en', {dateStyle: 'full', timeStyle: 'full'}).format(-8.64e15), df('en', {dateStyle: 'full', timeStyle: 'full'}).format(8.64e15), df('en', {dateStyle: 'short'}).format(-0), df('en', {dateStyle: 'short'}).format(1.9)].join(' | '));
// RelativeTimeFormat and DurationFormat edges
t('rtf more locales', () => ['de', 'fr', 'es', 'ru', 'ja', 'zh', 'pl', 'ar', 'pt', 'it', 'nl', 'ko'].map(l => ['long', 'short', 'narrow'].map(s => new Intl.RelativeTimeFormat(l, {style: s, numeric: 'auto'}).format(2, 'day') + ';' + new Intl.RelativeTimeFormat(l, {style: s}).format(-1, 'quarter') + ';' + new Intl.RelativeTimeFormat(l, {style: s}).format(5, 'second')).join(',')).join(' | '));
t('rtf parts locales', () => ['pl', 'ar', 'de'].map(l => JSON.stringify(new Intl.RelativeTimeFormat(l).formatToParts(-12345.6, 'hours'))).join(' '));
t('rtf nu option', () => [new Intl.RelativeTimeFormat('en', {numberingSystem: 'deva'}).format(3, 'day'), new Intl.RelativeTimeFormat('en', {numberingSystem: 'bogus!'}).format(3, 'day')].join(' | '));
t('rtf localeMatcher', () => new Intl.RelativeTimeFormat('en', {localeMatcher: 'magic'}));
t('rtf brand', () => Intl.RelativeTimeFormat.prototype.format.call({}, 1, 'day'));
t('df more', () => [new Intl.DurationFormat('en', {style: 'digital', hours: '2-digit'}).format({hours: 3, minutes: 4}), new Intl.DurationFormat('en', {style: 'digital', minutes: 'numeric'}).format({hours: 3, minutes: 4}), new Intl.DurationFormat('en', {seconds: 'numeric'}).format({minutes: 3, seconds: 4, milliseconds: 5}), new Intl.DurationFormat('en', {style: 'long', fractionalDigits: 2}).format({seconds: 3, milliseconds: 456}), new Intl.DurationFormat('en', {milliseconds: 'long', microseconds: 'numeric'}).format({milliseconds: 3, microseconds: 4, nanoseconds: 5}), new Intl.DurationFormat('en', {style: 'digital'}).format({days: 1, hours: 0, minutes: 0, seconds: 0}), new Intl.DurationFormat('en', {style: 'digital', fractionalDigits: 0}).format({seconds: 1, milliseconds: 999}), new Intl.DurationFormat('de', {style: 'digital'}).format({hours: 1, seconds: 2, milliseconds: 3})].join(' | '));
t('df display errors', () => [{seconds: 'numeric', secondsDisplay: 'auto', minutes: 'long'}, {hours: 'numeric', minutes: 'narrow'}, {style: 'digital', hoursDisplay: 'auto', minutes: 'long'}, {days: 'numeric'}, {milliseconds: 'numeric', seconds: 'long', microseconds: 'long'}, {fractionalDigits: -1}, {fractionalDigits: 1.5}, {numberingSystem: '!!'}].map(o => { try { return JSON.stringify(new Intl.DurationFormat('en', o).resolvedOptions()).length; } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' | '));
t('df value errors', () => [{hours: Infinity}, {hours: 2 ** 53}, {seconds: 123456789, milliseconds: 5}, {years: -1, hours: 1}, {hours: '3'}, {hours: 'x'}, 'PT1H', 'P1Y2W', Temporal.Duration.from('-P1DT1H')].map(v => { try { return new Intl.DurationFormat('en').format(v); } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' | '));
t('df parts long fr', () => JSON.stringify(new Intl.DurationFormat('fr', {style: 'long'}).formatToParts({hours: 2, minutes: 1, seconds: 30})));
t('df parts narrow ja', () => JSON.stringify(new Intl.DurationFormat('ja', {style: 'narrow'}).formatToParts({hours: 2, minutes: 1, seconds: 30})));
// Locale and tags edges
t('locale weird', () => ['en-Latn-US-u-ca-gregory-x-private', 'en-u-ca-gregory-t-ja', 'zh-Hant-u-nu-hanidec', 'en-a-xyz', 'de-u-co-phonebk-x-a', 'sr-Cyrl-u-kn'].map(s => { const l = new Intl.Locale(s); return [l.toString(), l.baseName, l.maximize().toString(), l.minimize().toString()].join('~'); }).join(' | '));
t('locale extension options', () => [new Intl.Locale('en-u-ca-gregory-co-emoji', {calendar: 'japanese', collation: 'phonebk', numberingSystem: 'thai', hourCycle: 'h11', caseFirst: 'false', numeric: false}).toString(), new Intl.Locale('en', {numeric: 'yes'}).toString(), new Intl.Locale('en', {caseFirst: 'upper'}).caseFirst].join(' | '));
t('tags extlang/irregular', () => ['zh-cmn-Hans', 'en-GB-oed', 'i-ami', 'zh-hakka', 'sgn-BR', 'cel-gaulish-x-a', 'en-u-va-posix', 'en-u-ca-chinese-hc-h11-ms-metric', 'de-t-en-u-ca-gregory', 'es-419-u-nu-latn-x-foo-bar', 'sr-Latn-ME-1994', 'yue-Hans', 'und-Latn-DE', 'und-u-ca-gregory', 'en-t-zh-hans', 'tlh', 'en-US-u-rg-uszzzz-sd-usny', 'ar-u-nu-arab-tz-utc', 'th-u-nu-thai-ca-buddhist', 'en-t-k0-dvorak-m0-ungegn', 'ja-t-it-m0-xxxxxxxx'].map(s => { try { return Intl.getCanonicalLocales(s)[0]; } catch (e) { return 'RangeError'; } }).join(' | '));
"""


ALIAS_TABLES = r"""
// Alias canonicalization tables: deprecated languages, regions, multi-candidate regions, variants, -u- types.
const langs = 'in ces iw heb cnr ji jw mo aam adp aue ayx bgm bjd ccq cjr cka cmk coy cqu drh drw gav gfx ggn gti guv hrr ibi ilw jeg kgc kgh koj krm ktr kvs kwq kxe kzj kzt lii lmm meg mst mwj myt nad ncp nnx nts oun pcr pmc pmu ppa ppr pry puz sca skk tdu thc thx tie tkk tlw tmp tne tnf tsf uok xba xia xkh xsj ybd yma yos yuu cmn sh aar tl swc prs zsm arb bh'.split(' ');
const regions = 'BU CT DD DY FQ FX HV JT MI NH NQ PU PZ QU RH TP UK VD WK YD YU ZR 004 008 554 756 840 230 280 532 536 582 886 SU 810 CS 890 NT AN 530'.split(' ');
const canon = s => { try { return Intl.getCanonicalLocales(s)[0]; } catch (e) { return 'RangeError'; } };
console.log('languages: ' + langs.map(l => l + '>' + canon(l) + '/' + canon(l + '-Latn-US')).join(' '));
console.log('sgn: ' + 'br co de dk es fr gb gr ie it jp mx ni nl no pt se us za xx'.split(' ').map(r => canon('sgn-' + r.toUpperCase())).join(' '));
console.log('regions: ' + regions.map(r => r + '>' + canon('und-' + r) + '/' + canon('en-' + r)).join(' '));
console.log('multi: ' + ['hy-SU', 'az-SU', 'uz-SU', 'be-SU', 'et-SU', 'ka-SU', 'kk-SU', 'lv-SU', 'lt-SU', 'ro-SU', 'tg-SU', 'tk-SU', 'uk-SU', 'xx-SU', 'und-Armn-SU', 'und-Cyrl-SU', 'sr-CS', 'sr-Latn-CS', 'cnr-CS', 'ar-NT', 'ckb-NT', 'pap-AN', 'nl-AN', 'en-AN', 'en-530', 'ru-810', 'sr-890'].map(s => s + '>' + canon(s)).join(' '));
console.log('variants: ' + ['ja-Latn-heploc', 'el-polytoni', 'hy-arevela-x-a', 'zh-xiang', 'zh-hakka-TW', 'en-heploc-polytoni', 'sl-rozaj-1994-biske', 'de-DE-1901-1996', 'en-POSIX-u-ca-gregory'].map(s => s + '>' + canon(s)).join(' '));
console.log('u types: ' + [['ca', 'islamicc'], ['ca', 'ethiopic-amete-alem'], ['ca', 'gregorian'], ['ms', 'imperial'], ['tz', 'cnckg'], ['tz', 'eire'], ['tz', 'est'], ['tz', 'gmt0'], ['tz', 'uct'], ['tz', 'zulu'], ['ks', 'primary'], ['ks', 'secondary'], ['ks', 'tertiary'], ['ks', 'quaternary'], ['ks', 'quarternary'], ['ks', 'identical'], ['rg', 'no23'], ['sd', 'cn11'], ['rg', 'cz10a'], ['sd', 'fra'], ['rg', 'frg'], ['sd', 'lud'], ['kb', 'yes'], ['kc', 'yes'], ['kh', 'yes'], ['kk', 'yes'], ['kn', 'yes'], ['kn', 'true'], ['kn', 'false'], ['co', 'standard'], ['nu', 'latn']].map(([k, v]) => k + '-' + v + '>' + canon('en-u-' + k + '-' + v)).join(' '));
console.log('t fields: ' + ['en-t-m0-names', 'en-t-zh-m0-names-h0-hybrid', 'en-t-iw-x-y', 'en-t-sh', 'en-t-in-id', 'en-t-zh-hans-cn', 'en-t-m0-ungegn-k0-dvorak', 'en-t-k0-abc', 'en-t-zh-a-x', 'en-t-x0-names'].map(s => s + '>' + canon(s)).join(' '));
console.log('locale objects: ' + ['iw-IL', 'sh-YU', 'mo', 'tl-PH', 'cmn-Hans-CN', 'en-UK', 'zh-guoyu-x-a', 'und-Qaai-DD'].map(s => { const l = new Intl.Locale(s); return l.toString() + '|' + l.maximize().toString() + '|' + l.minimize().toString(); }).join(' '));
"""


MORE_BRANCHES = r"""
const DF = Intl.DurationFormat;
const tr = f => { try { const v = f(); return typeof v === 'object' ? JSON.stringify(v) : String(v); } catch (e) { return e.constructor.name + ':' + e.message; } };
t('df iso strings', () => ['-P1D', '+PT1H', '−PT1M', 'p1dt2h', 'PT1.5S', 'PT1,25S', 'PT1.5M', 'P1.5D', 'P1DT', 'PT', '1D', 'P1D2', 'P', 'P1Y2M3W4DT5H6M7.123456789S', 'P1DT2H3', 'PT0.000000001S'].map(s => tr(() => new DF('en').format(s))).join(' | '));
t('df fractional combos', () => [{style: 'digital', millisecondsDisplay: 'always'}, {seconds: 'numeric', milliseconds: 'numeric', millisecondsDisplay: 'always'}, {seconds: 'numeric', milliseconds: 'long'}, {milliseconds: 'numeric', microseconds: 'long'}, {microseconds: 'numeric', nanoseconds: 'narrow'}, {style: 'digital', nanosecondsDisplay: 'always'}, {style: 'digital', fractionalDigits: 9}].map(o => tr(() => new DF('en', o).format({seconds: 1, milliseconds: 2, microseconds: 3, nanoseconds: 4}))).join(' | '));
t('df numeric subsecond', () => [{milliseconds: 'numeric'}, {microseconds: 'numeric'}, {nanoseconds: 'numeric'}, {milliseconds: 'numeric', fractionalDigits: 2}, {microseconds: 'numeric', fractionalDigits: 0}].map(o => tr(() => new DF('en', o).format({seconds: 0, milliseconds: 7, microseconds: 8, nanoseconds: 9}))).join(' | '));
t('df display always all', () => tr(() => new DF('en', {yearsDisplay: 'always', monthsDisplay: 'always', weeksDisplay: 'always', daysDisplay: 'always', hoursDisplay: 'always', minutesDisplay: 'always', secondsDisplay: 'always', millisecondsDisplay: 'always', microsecondsDisplay: 'always', nanosecondsDisplay: 'always'}).format({hours: 1})));
t('df digital hours 2-digit', () => [{hours: '2-digit'}, {hours: 'numeric', minutes: 'numeric'}, {minutes: '2-digit', seconds: 'numeric'}, {hours: 'numeric', hoursDisplay: 'auto'}].map(o => tr(() => new DF('en', {style: 'digital', ...o}).format({hours: 0, minutes: 5, seconds: 6}))).join(' | '));
t('df negative zero', () => [tr(() => new DF('en').format({hours: -0, minutes: -5})), tr(() => new DF('en', {style: 'digital'}).format({hours: -0, minutes: -5})), tr(() => new DF('en', {style: 'digital'}).format({seconds: -1, milliseconds: -500}))].join(' | '));
t('df locales digital sep', () => ['de', 'fr', 'fi', 'da', 'ar', 'ja', 'it', 'ru', 'pl'].map(l => tr(() => new DF(l, {style: 'digital'}).format({hours: 1, minutes: 2, seconds: 3, milliseconds: 4}))).join(' | '));
t('df options getters order', () => { const seen = []; new DF('en', new Proxy({}, {get(_, k) { if (typeof k === 'string') seen.push(k); return undefined; }})); return seen.join(','); });
t('df parts negative', () => tr(() => new DF('en', {style: 'long'}).formatToParts({days: -2, hours: -3})));
t('df parts fraction', () => tr(() => new DF('en', {seconds: 'narrow', milliseconds: 'numeric'}).formatToParts({seconds: 1, milliseconds: 5})));
t('locale fw values', () => ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', 'xyz'].map(d => tr(() => { const l = new Intl.Locale('en-u-fw-' + d); return l.firstDayOfWeek + ':' + JSON.stringify(l.getWeekInfo()); })).join(' | '));
t('locale fw option numbers', () => [1, 2, 3, 4, 5, 6, 7, 0, 8, '3', 'mon'].map(v => tr(() => new Intl.Locale('en', {firstDayOfWeek: v}).toString())).join(' | '));
t('locale info ext', () => ['en-u-hc-h12', 'en-u-hc-h24', 'en-u-ca-chinese-co-pinyin', 'zh-u-co-stroke', 'ar-u-nu-arab', 'th-u-nu-thai-ca-buddhist', 'en-u-nu-bogus', 'en-u-ca-bogus'].map(s => tr(() => { const l = new Intl.Locale(s); return [l.getCalendars(), l.getCollations(), l.getHourCycles(), l.getNumberingSystems()]; })).join(' | '));
t('locale info brand', () => tr(() => Intl.Locale.prototype.getWeekInfo.call({})));
t('locale getter brand', () => tr(() => Object.getOwnPropertyDescriptor(Intl.Locale.prototype, 'baseName').get.call({})));
t('locale maximize brand', () => tr(() => Intl.Locale.prototype.maximize.call('en')));
t('locale toString brand', () => tr(() => Intl.Locale.prototype.toString.call(new Intl.Locale('en'))));
t('locale bad options type', () => tr(() => new Intl.Locale('en', 5).toString()));
t('locale null options', () => tr(() => new Intl.Locale('en', null)));
t('locale tag obj', () => tr(() => new Intl.Locale({toString() { return 'fr-CA'; }}).toString()));
t('locale script region opts', () => [{script: 'cyrl', region: 'rs', language: 'SR'}, {region: '419'}, {script: 'latn1'}, {language: 'und'}, {language: 'root'}, {region: 'U'}].map(o => tr(() => new Intl.Locale('en', o).toString())).join(' | '));
t('pr options', () => [{minimumIntegerDigits: 3}, {minimumFractionDigits: 2}, {maximumSignificantDigits: 2}, {roundingIncrement: 5, maximumFractionDigits: 1, minimumFractionDigits: 1}, {roundingPriority: 'morePrecision', maximumFractionDigits: 0, maximumSignificantDigits: 2}, {trailingZeroDisplay: 'stripIfInteger', minimumFractionDigits: 2}, {roundingMode: 'trunc', maximumFractionDigits: 0}].map(o => tr(() => { const p = new Intl.PluralRules('en', o); return p.select(1) + '/' + p.select(1.04) + '/' + p.select(1.5) + '/' + JSON.stringify(p.resolvedOptions()); })).join(' | '));
t('pr errors', () => [{type: 5}, {notation: 'bogus'}, {roundingIncrement: 7}, {minimumFractionDigits: 3, maximumFractionDigits: 1}, {localeMatcher: 'x'}].map(o => tr(() => new Intl.PluralRules('en', o).select(1))).join(' | '));
t('pr select coercion', () => ['1', '1.0', ' 2 ', 'abc', null, true, {valueOf() { return 1; }}].map(v => tr(() => new Intl.PluralRules('en').select(v))).join(' | '));
t('pr selectRange coercion', () => [[1, '2'], ['1', 1], [0, -1], [-1, 0]].map(([a, b]) => tr(() => new Intl.PluralRules('fr').selectRange(a, b))).join(' | '));
t('seg containing coercion', () => { const s = new Intl.Segmenter('en', {granularity: 'sentence'}).segment('Hi. Yo.'); return [0, '3', -0, 6, 7, Infinity, null, {valueOf() { return 4; }}].map(i => tr(() => s.containing(i))).join(' | '); });
t('seg brand', () => [tr(() => Intl.Segmenter.prototype.segment.call({}, 'a')), tr(() => Intl.Segmenter.prototype.resolvedOptions.call({}))].join(' | '));
t('seg iterator brand', () => { const it = new Intl.Segmenter().segment('ab')[Symbol.iterator](); return tr(() => it.next.call({})); });
t('seg segments brand', () => { const segs = new Intl.Segmenter().segment('ab'); return tr(() => segs.containing.call({}, 0)); });
t('coll compare brand', () => tr(() => Object.getOwnPropertyDescriptor(Intl.Collator.prototype, 'compare').get.call({})));
t('coll options', () => [{numeric: 'yes'}, {numeric: 0}, {caseFirst: 'false'}, {ignorePunctuation: 1}, {sensitivity: undefined, usage: 'search'}, {collation: 'phonebk'}, {collation: 'search'}].map(o => tr(() => new Intl.Collator('de', o).resolvedOptions())).join(' | '));
t('coll compare strings', () => [['', ''], ['a', ''], ['', 'a'], ['A', 'a'], ['á', 'á'], ['ﬀ', 'ff'], ['①', '1'], ['Ⅳ', 'IV'], ['ß', 'SS'], ['İ', 'i'], ['\u{10400}', '\u{10428}']].map(([a, b]) => new Intl.Collator('en').compare(a, b) + '/' + new Intl.Collator('en', {sensitivity: 'base'}).compare(a, b)).join(' '));
t('dn more', () => [['region', '150'], ['region', 'EU'], ['region', 'UN'], ['region', 'QO'], ['language', 'zh-Hans-CN'], ['language', 'sr-Cyrl-RS'], ['language', 'en-001'], ['language', 'es-ES'], ['language', 'de-1996'], ['language', 'EN-us'], ['script', 'Brai'], ['currency', 'xau'], ['calendar', 'GREGORY'], ['calendar', 'islamic'], ['dateTimeField', 'Era']].map(([ty, c]) => tr(() => new Intl.DisplayNames('en', {type: ty}).of(c))).join(' | '));
t('dn brand', () => [tr(() => Intl.DisplayNames.prototype.of.call({}, 'US')), tr(() => Intl.DisplayNames.prototype.resolvedOptions.call({}))].join(' | '));
t('lf brand', () => [tr(() => Intl.ListFormat.prototype.format.call({}, [])), tr(() => Intl.ListFormat.prototype.formatToParts.call({}, [])), tr(() => Intl.ListFormat.prototype.resolvedOptions.call({}))].join(' | '));
t('rtf extra', () => [tr(() => new Intl.RelativeTimeFormat('en', {style: 'short', numeric: 'auto'}).format(-1, 'quarters')), tr(() => new Intl.RelativeTimeFormat('en', {numeric: 'auto'}).format(1.5, 'day')), tr(() => new Intl.RelativeTimeFormat('en', {numeric: 'auto'}).format(-0.0, 'hours')), tr(() => new Intl.RelativeTimeFormat('en').format(1e21, 'year')), tr(() => new Intl.RelativeTimeFormat('en').format('2', 'week')), tr(() => new Intl.RelativeTimeFormat('en').formatToParts(Infinity, 'day')), tr(() => new Intl.RelativeTimeFormat('en').formatToParts(1, 'bogus')), tr(() => new Intl.RelativeTimeFormat('de', {style: 'narrow'}).formatToParts(-3, 'months'))].join(' | '));
t('nf misc', () => [tr(() => new Intl.NumberFormat('en', {style: 'unit', unit: 'percent', unitDisplay: 'long'}).format(5)), tr(() => new Intl.NumberFormat('en', {style: 'unit', unit: 'percent', notation: 'compact'}).format(12345)), tr(() => new Intl.NumberFormat('en', {style: 'percent', notation: 'scientific'}).format(12.5)), tr(() => new Intl.NumberFormat('en', {style: 'currency', currency: 'USD', notation: 'engineering'}).format(12345)), tr(() => new Intl.NumberFormat('en', {style: 'currency', currency: 'USD', notation: 'compact', compactDisplay: 'long'}).format(1234567)), tr(() => new Intl.NumberFormat('en', {style: 'unit', unit: 'byte', notation: 'compact', unitDisplay: 'long'}).format(1.5e9)), tr(() => new Intl.NumberFormat('en', {minimumFractionDigits: 2, maximumSignificantDigits: 3}).format(1.23456)), tr(() => new Intl.NumberFormat('en', {maximumFractionDigits: 1, roundingPriority: 'lessPrecision', minimumSignificantDigits: 3}).format(1.23456))].join(' | '));
t('nf brand', () => [tr(() => Intl.NumberFormat.prototype.formatToParts.call({}, 1)), tr(() => Intl.NumberFormat.prototype.formatRange.call({}, 1, 2)), tr(() => Intl.NumberFormat.prototype.formatRangeToParts.call(5, 1, 2))].join(' | '));
t('dtf brand', () => [tr(() => Intl.DateTimeFormat.prototype.formatToParts.call({}, 0)), tr(() => Intl.DateTimeFormat.prototype.formatRange.call({}, 0, 1)), tr(() => Intl.DateTimeFormat.prototype.resolvedOptions.call({})), tr(() => Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, 'format').get.call({}))].join(' | '));
t('dtf zoned in range', () => tr(() => new Intl.DateTimeFormat('en').formatRange(Temporal.ZonedDateTime.from('2024-01-01T00:00[UTC]'), Temporal.ZonedDateTime.from('2024-01-02T00:00[UTC]'))));
t('dtf zoned parts', () => tr(() => new Intl.DateTimeFormat('en').formatToParts(Temporal.ZonedDateTime.from('2024-01-01T00:00[UTC]'))));
t('dtf duration', () => tr(() => new Intl.DateTimeFormat('en').format(Temporal.Duration.from('P1D'))));
t('dtf temporal parts', () => [Temporal.PlainDate.from('2024-01-05'), Temporal.PlainTime.from('10:20:30.5'), Temporal.PlainDateTime.from('2024-01-05T10:20'), Temporal.Instant.from('2024-01-05T10:20Z')].map(v => tr(() => new Intl.DateTimeFormat('ja', {timeZone: 'Asia/Tokyo'}).formatToParts(v).map(p => p.type + ':' + p.value).join(','))).join(' | '));
"""


def test_numberformat_locales(run):
    """CATCHES: wrong per-locale decimal/group separators, digit systems, NaN/Infinity symbols, string/BigInt exact decimals and locale negotiation in NumberFormat."""
    _check(run, NF_LOCALES, "nf_locales")


def test_numberformat_styles(run):
    """CATCHES: wrong currency symbols/codes/names/accounting forms, unit patterns (short/long/narrow, compound units), percent scaling and formatToParts part types."""
    _check(run, NF_STYLES, "nf_styles")


def test_numberformat_notations(run):
    """CATCHES: wrong compact (short/long, per-locale thresholds like Mio./万/lakh), scientific and engineering exponent rendering and their parts."""
    _check(run, NF_NOTATION, "nf_notation")


def test_numberformat_rounding_and_options(run):
    """CATCHES: wrong signDisplay, digit options validation, rounding modes/increments/priority, trailingZeroDisplay, useGrouping and resolvedOptions fields/order."""
    _check(run, NF_ROUNDING, "nf_rounding")


def test_numberformat_ranges(run):
    """CATCHES: wrong formatRange collapsing (shared currency/unit, approximately sign), argument validation, and formatRangeToParts source tagging."""
    _check(run, NF_RANGE, "nf_range")


def test_datetimeformat_styles_per_locale(run):
    """CATCHES: wrong dateStyle/timeStyle patterns per locale, hourCycle/hour12 handling in styles, and Date.prototype.toLocale*String defaults/errors."""
    _check(run, DTF_STYLES, "dtf_styles")


def test_datetimeformat_components(run):
    """CATCHES: wrong component pattern selection (weekday/era/month widths, fractional seconds, dayPeriod, timeZoneName) and option validation messages."""
    _check(run, DTF_COMPONENTS, "dtf_components")


def test_datetimeformat_zones_parts_ranges(run):
    """CATCHES: wrong time-zone offset application/naming, resolvedOptions, formatToParts types, formatRange collapsing and non-Gregorian calendar output."""
    _check(run, DTF_ZONES_PARTS, "dtf_zones_parts")


def test_durationformat(run):
    """CATCHES: wrong DurationFormat unit styles, digital clock layout, fractional digits, display options, sign handling, parts and resolvedOptions."""
    _check(run, DURATION_FORMAT, "durationformat")


def test_locale(run):
    """CATCHES: wrong Intl.Locale parsing/getters/options, likely-subtags maximize/minimize, alias canonicalization and locale info getters (week, hour cycles, zones)."""
    _check(run, LOCALE, "locale")


def test_get_canonical_locales(run):
    """CATCHES: wrong BCP 47 canonicalization (case, grandfathered/legacy tags, language/region/script aliases, extension sorting) or wrong rejection of malformed tags."""
    _check(run, CANONICAL, "canonical")


def test_collator(run):
    """CATCHES: wrong collation order (accents, case, punctuation, numeric), sensitivity levels, locale tailorings, resolvedOptions and String.prototype.localeCompare."""
    _check(run, COLLATOR, "collator")


def test_segmenter(run):
    """CATCHES: wrong grapheme clusters (ZWJ emoji, flags, Hangul, combining marks), word boundaries/isWordLike, sentence boundaries, containing() and iterator protocol."""
    _check(run, SEGMENTER, "segmenter")


def test_plural_rules(run):
    """CATCHES: wrong cardinal/ordinal plural categories per language, digit-option effects, selectRange results and resolvedOptions.pluralCategories."""
    _check(run, PLURAL_RULES, "plural_rules")


def test_relative_time_format(run):
    """CATCHES: wrong relative-time phrases (numeric auto/always, styles, plural forms, locales), formatToParts structure and unit/value validation."""
    _check(run, RELATIVE_TIME, "relative_time")


def test_list_format(run):
    """CATCHES: wrong list patterns per type/style/locale (Spanish y/e and o/u, Hebrew), iterable handling, element type checks and formatToParts."""
    _check(run, LIST_FORMAT, "list_format")


def test_display_names(run):
    """CATCHES: wrong region/language/script/currency/calendar/dateTimeField display names, fallback handling, code validation and option errors."""
    _check(run, DISPLAY_NAMES, "display_names")


def test_intl_service_surface(run):
    """CATCHES: wrong supportedLocalesOf/supportedValuesOf lists, locale negotiation and extension filtering, Intl property surface, subclassing and legacy construction."""
    _check(run, SERVICE, "service")


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_intl_from_user_code_all_tiers(run, tier):
    """CATCHES: execution tiers that diverge when Intl formatters are used from closures, sort comparators, template literals, Maps and for-of over segments."""
    _check(run, TIERED, "tiered", tier)


SOLAR_CALS = "['gregory', 'buddhist', 'japanese', 'roc', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa']"
LUNAR_CALS = "['hebrew', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla']"
LUNISOLAR_CALS = "['chinese', 'dangi']"


@pytest.mark.parametrize("cals", [SOLAR_CALS, LUNAR_CALS, LUNISOLAR_CALS], ids=["solar", "lunar", "lunisolar"])
def test_month_and_era_names_all_calendars(run, cals):
    """CATCHES: wrong or missing localized month names (long/short/narrow, leap months, 13-month calendars) and era names for any supported locale x calendar combination."""
    name = {SOLAR_CALS: "month_era_names_solar", LUNAR_CALS: "month_era_names_lunar", LUNISOLAR_CALS: "month_era_names_lunisolar"}[cals]
    _check(run, MONTH_ERA_NAMES.replace("CALS;", cals + ";", 1), name)


def test_unit_patterns_all_locales(run):
    """CATCHES: wrong localized unit patterns or plural selection for any sanctioned unit (and compound per-units) in any unit-data locale and width."""
    _check(run, UNIT_PATTERNS, "unit_patterns")


def test_every_numbering_system(run):
    """CATCHES: wrong digit tables for any numbering system listed by supportedValuesOf, in NumberFormat and DateTimeFormat, or wrong resolution of unsupported systems."""
    _check(run, NUMBERING_SYSTEMS, "numbering_systems")


def test_intl_edge_cases(run):
    """CATCHES: wrong exact-decimal rounding of string/BigInt inputs, range collapsing for prefix/suffix currencies, legacy constructor chaining, Temporal/DateTimeFormat field overlap errors, lunisolar and era names, and DurationFormat/RelativeTimeFormat option validation."""
    _check(run, EDGES, "edges")


def test_alias_canonicalization_tables(run):
    """CATCHES: missing or wrong CLDR alias data in tag canonicalization: deprecated language codes, sign-language tags, region aliases (incl. multi-candidate SU/CS/NT/AN resolution via likely subtags), variant, -u- type and -t- field aliases."""
    _check(run, ALIAS_TABLES, "alias_tables")


def test_intl_option_and_brand_branches(run):
    """CATCHES: wrong DurationFormat ISO-string parsing and fractional/sub-second unit styles, Locale firstDayOfWeek/info getters, PluralRules digit options, Segmenter/Collator/DisplayNames/ListFormat brand checks and argument coercion, and Temporal-type handling in DateTimeFormat."""
    _check(run, MORE_BRANCHES, "more_branches")
