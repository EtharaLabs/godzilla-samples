"""Remaining library-builtin corners of lumen-cli: Temporal calendar-bag field resolution, non-ISO
calendar arithmetic under overflow:'reject', month clamping in calendar differences, values at the
representable instant/date limits, DST-aware duration rounding, sub-minute historical offsets,
ECMA-402 locale canonicalization of -u-/-t- extension aliases, the legacy Intl fallback symbol,
GetPrototypeFromConstructor with odd new.target values, option validation errors, Collator
extension resolution, RegExp replace/split limits and dead-result split guards, lone surrogates
under /i, typed arrays over shrinking resizable buffers, Uint8Array codecs on immutable buffers,
JSON reviver/proxy interplay, set-like protocols, WeakMap upserts, Reflect on module namespaces
and BigInt/Number comparisons. Every date is a literal; nothing reads the clock."""

import pytest

from conftest import out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# show() prints "label: String(result)" or the thrown error's name and message. String() (not `+`)
# is used so Temporal objects render via toString instead of their throwing valueOf.
PRELUDE = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + String(f())); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
"""
EPILOGUE = "\nconsole.log(out.join('\\n'));\n"


def check(js, golden, name, body, tier=()):
    r = js(PRELUDE + body + EPILOGUE, *tier)
    assert out(r) == golden(name)
    assert (r.returncode, r.stderr) == (0, b"")


# ----------------------------------------------------------------------------------- Temporal


@pytest.mark.parametrize("tier", TIERS)
def test_calendar_bag_required_fields_in_relative_to(js, golden, tier):
    """CATCHES: a non-ISO relativeTo property bag that is missing its year or month, has month 0, an ill-formed monthCode, or a month that agrees with its monthCode being resolved wrongly (silently defaulting a field, wrong error type, or a mis-anchored month length) in any calendar fails this."""
    body = r"""var T = Temporal;
var D = T.Duration.from({ days: 40 });
function rel(bag) { return D.round({ largestUnit: 'month', relativeTo: bag }).toString(); }
['hebrew', 'chinese', 'coptic', 'ethiopic', 'islamic-civil', 'indian', 'persian', 'gregory', 'japanese', 'buddhist'].forEach(function (c) {
  show(c + ' no year', function () { return rel({ calendar: c, monthCode: 'M01', day: 1 }); });
  show(c + ' no month', function () { return rel({ calendar: c, year: 1400, day: 1 }); });
  show(c + ' month 0', function () { return rel({ calendar: c, year: 1400, month: 0, day: 1 }); });
  show(c + ' month agrees', function () { return rel({ calendar: c, year: 2000, month: 2, monthCode: 'M02', day: 1 }); });
  show(c + ' from() no year', function () { return T.PlainDate.from({ calendar: c, monthCode: 'M01', day: 1 }); });
});
['chinese', 'coptic', 'islamic-civil', 'persian', 'gregory'].forEach(function (c) {
  show(c + ' monthCode M1', function () { return rel({ calendar: c, year: 1400, monthCode: 'M1', day: 1 }); });
});
show('ethiopic era aa', function () { return rel({ calendar: 'ethiopic', era: 'aa', eraYear: 7500, monthCode: 'M01', day: 1 }); });
show('ethiopic era only', function () { return rel({ calendar: 'ethiopic', era: 'am', monthCode: 'M01', day: 1 }); });
"""
    check(js, golden, "calendar_bag_required_fields_in_relative_to", body, tier)


@pytest.mark.parametrize("tier", TIERS)
def test_non_iso_add_overflow_constrain_vs_reject(js, golden, tier):
    """CATCHES: calendar date addition that ignores overflow:'reject' for a leap month missing in the target Hebrew/Chinese year or a day past the target month's end (Persian Esfand, Islamic months, the 5/6-day Coptic and Ethiopic epagomenal month), or clamps to the wrong day under constrain, fails this."""
    body = r"""var T = Temporal;
function cd(c, y, mc, d) { return T.PlainDate.from({ calendar: c, year: y, monthCode: mc, day: d }, { overflow: 'reject' }); }
function desc(d) { return d.toString() + ' ' + d.year + '-' + d.monthCode + '-' + d.day; }
var cases = [
  ['hebrew leap Adar I + 1y', 'hebrew', 5784, 'M05L', 1, { years: 1 }],
  ['hebrew leap Adar I + 3y', 'hebrew', 5784, 'M05L', 1, { years: 3 }],
  ['hebrew 29 Heshvan + 1y', 'hebrew', 5784, 'M02', 29, { years: 1 }],
  ['hebrew 30 Kislev 5785 + 1y', 'hebrew', 5785, 'M03', 30, { years: 1 }],
  ['hebrew 30 Shevat + 1m', 'hebrew', 5785, 'M05', 30, { months: 1 }],
  ['chinese M04L + 1y', 'chinese', 2020, 'M04L', 1, { years: 1 }],
  ['chinese M01 30 + 1m3d', 'chinese', 2022, 'M01', 30, { months: 1, days: 3 }],
  ['persian 30 Esfand + 1y', 'persian', 1403, 'M12', 30, { years: 1 }],
  ['persian 29 Esfand + 1y', 'persian', 1403, 'M12', 29, { years: 1 }],
  ['persian 31 Shahrivar + 1m', 'persian', 1403, 'M06', 31, { months: 1 }],
  ['islamic 30 Muharram + 1m', 'islamic-civil', 1445, 'M01', 30, { months: 1 }],
  ['coptic M13 6 + 1y', 'coptic', 1739, 'M13', 6, { years: 1 }],
  ['coptic M13 5 + 1y', 'coptic', 1738, 'M13', 5, { years: 1 }],
  ['coptic M13 5 + 4y', 'coptic', 1735, 'M13', 5, { years: 4 }],
  ['ethiopic M13 6 - 1y', 'ethiopic', 2015, 'M13', 6, { years: -1 }],
  ['indian 31 Vaisakha + 6m', 'indian', 1946, 'M02', 31, { months: 6 }],
  ['gregory Jan 31 + 1m', 'gregory', 2023, 'M01', 31, { months: 1 }]
];
cases.forEach(function (k) {
  show(k[0], function () {
    var d = cd(k[1], k[2], k[3], k[4]);
    var c = d.add(k[5]);
    var r;
    try { r = desc(d.add(k[5], { overflow: 'reject' })); } catch (e) { r = e.name + ': ' + e.message; }
    return desc(d) + ' => constrain ' + desc(c) + ' | reject ' + r;
  });
});
show('coptic M13 lengths', function () { return [1736, 1737, 1738, 1739].map(function (y) { return y + ':' + cd('coptic', y, 'M13', 1).daysInMonth; }).join(' '); });
"""
    check(js, golden, "non_iso_add_overflow_constrain_vs_reject", body, tier)


def test_non_iso_until_since_with_clamped_months(js, golden):
    """CATCHES: calendar-aware until/since that counts a whole year or month when the anchor's leap month code or day had to be clamped to land exactly on the target (Chinese M04L, Hebrew Adar I, Persian/Islamic/Coptic short months), or that mishandles identical dates and sub-day spans, fails this."""
    body = r"""var T = Temporal;
function cd(c, y, mc, d) { return T.PlainDate.from({ calendar: c, year: y, monthCode: mc, day: d }); }
function diffs(label, a, b) {
  show(label, function () {
    return ['year', 'month'].map(function (u) {
      return u + ':' + [a.until(b, { largestUnit: u }), b.until(a, { largestUnit: u }), b.since(a, { largestUnit: u })].join('/');
    }).join(' ') + ' | days ' + a.until(b).days;
  });
}
var c1 = cd('chinese', 2020, 'M04L', 1);
diffs('chinese M04L -> +1y', c1, c1.add({ years: 1 }));
var h1 = cd('hebrew', 5784, 'M05L', 1);
diffs('hebrew Adar I -> -1y', h1, h1.subtract({ years: 1 }));
diffs('hebrew Adar I -> -1y-1d', h1, h1.subtract({ years: 1, days: 1 }));
diffs('persian 31 Shahrivar -> 30 Mehr', cd('persian', 1403, 'M06', 31), cd('persian', 1403, 'M07', 30));
diffs('persian 30 Esfand -> 29 Esfand', cd('persian', 1403, 'M12', 30), cd('persian', 1404, 'M12', 29));
diffs('islamic 30 M01 -> 29 M02', cd('islamic-civil', 1445, 'M01', 30), cd('islamic-civil', 1445, 'M02', 29));
diffs('coptic M13 6 -> M13 5', cd('coptic', 1739, 'M13', 6), cd('coptic', 1740, 'M13', 5));
show('same date', function () { return [cd('hebrew', 5784, 'M05L', 1).until(cd('hebrew', 5784, 'M05L', 1), { largestUnit: 'year' }), cd('persian', 1403, 'M01', 1).since(cd('persian', 1403, 'M01', 1), { largestUnit: 'month' })].join(' '); });
show('zoned same day hebrew', function () { return T.ZonedDateTime.from('2024-03-10T01:00[UTC][u-ca=hebrew]').until(T.ZonedDateTime.from('2024-03-10T05:00[UTC][u-ca=hebrew]'), { largestUnit: 'year' }); });
show('datetime under a day hebrew', function () { var a = T.PlainDateTime.from('2024-03-10T01:00[u-ca=hebrew]'), b = T.PlainDateTime.from('2024-03-11T00:00[u-ca=hebrew]'); return [a.until(b, { largestUnit: 'year' }), b.until(a, { largestUnit: 'month' })].join(' '); });
"""
    check(js, golden, "non_iso_until_since_with_clamped_months", body)


@pytest.mark.parametrize("tier", TIERS)
def test_temporal_values_at_the_representable_limits(js, golden, tier):
    """CATCHES: rounding, subtraction, relativeTo resolution, totals, offset:'ignore' interpretation, withPlainTime and ZonedDateTime rounding that produce a date-time or instant just outside the ±8.64e21 ns window instead of throwing RangeError (or that wrongly throw for values exactly inside it) fails this."""
    body = r"""var T = Temporal;
var minDT = T.PlainDateTime.from('-271821-04-19T00:00:00.000000001');
show('min datetime', function () { return minDT; });
show('round min down', function () { return minDT.round({ smallestUnit: 'hour', roundingMode: 'floor' }); });
show('round min up', function () { return minDT.round({ smallestUnit: 'hour', roundingMode: 'ceil' }); });
show('subtract 1ns', function () { return minDT.subtract({ nanoseconds: 1 }); });
show('max datetime round day', function () { return T.PlainDateTime.from('+275760-09-13T23:59:59.9').round({ smallestUnit: 'day' }); });
show('max datetime round second', function () { return T.PlainDateTime.from('+275760-09-13T23:59:59.4').round({ smallestUnit: 'second' }); });
var D = T.Duration.from({ days: 1 });
show('relativeTo string before range', function () { return D.round({ largestUnit: 'year', relativeTo: '-271821-04-18' }); });
show('relativeTo zoned string before range', function () { return D.round({ largestUnit: 'year', relativeTo: '-271821-04-19T00:00Z[UTC]' }); });
show('relativeTo bag before range', function () { return D.round({ largestUnit: 'year', relativeTo: { year: -271821, month: 4, day: 18 } }); });
show('relativeTo bag first day', function () { return D.round({ largestUnit: 'year', relativeTo: { year: -271821, month: 4, day: 19 } }); });
show('relativeTo bag negative hour', function () { return D.round({ largestUnit: 'year', relativeTo: { year: 2020, month: 4, day: 18, hour: -1 } }); });
show('relativeTo bag hour 25', function () { return D.round({ largestUnit: 'hour', relativeTo: { year: 2020, month: 4, day: 18, hour: 25 } }); });
show('total from min datetime', function () { return D.total({ unit: 'day', relativeTo: minDT }); });
show('total from min date', function () { return T.Duration.from({ hours: 1 }).total({ unit: 'day', relativeTo: '-271821-04-19' }); });
show('zoned bag offset ignore at min', function () { return T.ZonedDateTime.from({ year: -271821, month: 4, day: 19, hour: 0, timeZone: 'UTC', offset: '+00:00' }, { offset: 'ignore' }); });
show('zoned string offset ignore at min', function () { return T.ZonedDateTime.from('-271821-04-19T00:00+00:00[UTC]', { offset: 'ignore' }); });
show('zoned string offset ignore next day', function () { return T.ZonedDateTime.from('-271821-04-20T00:00+00:00[UTC]', { offset: 'ignore' }); });
var zmin = T.ZonedDateTime.from('-271821-04-20T00:00+00:00[UTC]').withTimeZone('-01:00');
show('zoned min in -01:00', function () { return zmin; });
show('withPlainTime midnight', function () { return zmin.withPlainTime('00:00'); });
show('withPlainTime 23:30', function () { return zmin.withPlainTime('23:30'); });
var zmax = T.ZonedDateTime.from('+275760-09-13T00:00+00:00[UTC]').withTimeZone('+01:00');
show('zoned max in +01:00', function () { return zmax; });
show('round max to day', function () { return zmax.round({ smallestUnit: 'day', roundingMode: 'ceil' }); });
show('round max to hour', function () { return zmax.round({ smallestUnit: 'hour', roundingMode: 'ceil' }); });
show('round min to day', function () { return zmin.round({ smallestUnit: 'day', roundingMode: 'floor' }); });
show('startOfDay of min', function () { return zmin.startOfDay(); });
show('hoursInDay of min', function () { return zmin.hoursInDay; });
var zhalf = T.ZonedDateTime.from('-271821-04-20T00:00Z[UTC]').withTimeZone('-00:30');
show('zoned min in -00:30', function () { return zhalf; });
show('round -00:30 min to hour floor', function () { return zhalf.round({ smallestUnit: 'hour', roundingMode: 'floor' }); });
show('round -00:30 min to hour halfExpand', function () { return zhalf.round({ smallestUnit: 'hour' }); });
"""
    check(js, golden, "temporal_values_at_the_representable_limits", body, tier)


def test_calendar_identifier_strings_and_non_iso_year_month_month_day(js, golden):
    """CATCHES: withCalendar() not accepting full ISO strings (with critical or zone annotations) and calendar aliases, non-ISO PlainYearMonth/PlainMonthDay serializing without their reference day or annotation, wrong reference years for month-days, or out-of-range years and strings not raising RangeError fails this."""
    body = r"""var T = Temporal;
var d = T.PlainDate.from('2020-01-01');
['2020-01-01[u-ca=hebrew]', '2020-01-01T00:00', '2020-01-01[!u-ca=japanese]', '2020-01-01T12:00+01:00[Europe/Berlin][u-ca=persian]', '2020-01-01[u-ca=bogus]', 'hebrew', 'HEBREW', 'islamicc', 'ethiopic-amete-alem', 'gregorian'].forEach(function (c) {
  show('withCalendar ' + c, function () { return d.withCalendar(c).toString(); });
});
var ym = T.PlainYearMonth.from({ year: 5780, monthCode: 'M05', calendar: 'hebrew' });
show('hebrew year-month', function () { return [ym.toString(), ym.toJSON(), ym.toString({ calendarName: 'never' }), ym.toString({ calendarName: 'always' }), ym.year, ym.monthCode].join(' | '); });
var ymc = T.PlainYearMonth.from({ year: 1403, month: 12, calendar: 'persian' });
show('persian year-month', function () { return [ymc.toJSON(), ymc.toString({ calendarName: 'critical' }), ymc.daysInMonth].join(' | '); });
var md = T.PlainMonthDay.from({ monthCode: 'M05', day: 1, calendar: 'hebrew' });
show('hebrew month-day', function () { return [md.toString(), md.toJSON(), md.toString({ calendarName: 'never' }), md.monthCode, md.day].join(' | '); });
var mdc = T.PlainMonthDay.from({ monthCode: 'M13', day: 6, calendar: 'coptic' });
show('coptic month-day', function () { return [mdc.toJSON(), mdc.toString({ calendarName: 'critical' })].join(' | '); });
show('umalqura month-day day 5', function () { return T.PlainMonthDay.from({ calendar: 'islamic-umalqura', monthCode: 'M03', day: 5 }).toString(); });
show('month-day with huge year', function () { return T.PlainMonthDay.from({ calendar: 'hebrew', year: 400000, monthCode: 'M01', day: 1 }).toString(); });
show('month-day with huge eraYear', function () { return T.PlainMonthDay.from({ calendar: 'gregory', era: 'ce', eraYear: 700000, monthCode: 'M01', day: 1 }).toString(); });
show('month-day year beyond limits', function () { return T.PlainMonthDay.from({ calendar: 'persian', year: 275200, monthCode: 'M12', day: 1 }).toString(); });
show('month-day year before limits', function () { return T.PlainMonthDay.from({ calendar: 'persian', year: -272500, monthCode: 'M01', day: 1 }).toString(); });
show('month-day year in range', function () { return T.PlainMonthDay.from({ calendar: 'persian', year: 1403, monthCode: 'M12', day: 30 }).toString(); });
show('month-day string beyond', function () { return T.PlainMonthDay.from('+275760-09-14[u-ca=hebrew]').toString(); });
show('month-day string before', function () { return T.PlainMonthDay.from('-271821-04-18[u-ca=hebrew]').toString(); });
show('month-day string in range', function () { return T.PlainMonthDay.from('2024-02-10[u-ca=hebrew]').toString(); });
show('year-month string beyond', function () { return T.PlainYearMonth.from('+275760-09-14[u-ca=hebrew]').toString(); });
show('year-month string before', function () { return T.PlainYearMonth.from('-271821-04-18[u-ca=hebrew]').toString(); });
show('year-month month 13', function () { return T.PlainYearMonth.from('2020-13').toString(); });
show('year-month month 00', function () { return T.PlainYearMonth.from('2020-00').toString(); });
show('year-month basic 202012', function () { return T.PlainYearMonth.from('202012').toString(); });
"""
    check(js, golden, "calendar_identifier_strings_and_non_iso_year_month_month_day", body)


def test_zoned_rounding_across_dst_and_offset_edge_cases(js, golden):
    """CATCHES: duration rounding relative to a 23-hour DST day that fails to roll the excess into a day, totals that ignore the shortened day, duration magnitudes past 2^53 seconds not throwing, PlainDate.add truncating negative hours the wrong way, sub-minute LMT offsets rendered unrounded, basic-format offset fields rejected, or offset-vs-named zone equality fails this."""
    body = r"""var T = Temporal;
var spring = T.ZonedDateTime.from('2024-03-10T00:00[America/New_York]');
show('23h30 round to hour on 23h day', function () { return T.Duration.from({ hours: 23, minutes: 30 }).round({ largestUnit: 'day', smallestUnit: 'hour', relativeTo: spring }); });
show('ceil to minute reaching day end', function () { return T.Duration.from({ hours: 22, minutes: 59, seconds: 59 }).round({ largestUnit: 'day', smallestUnit: 'minute', roundingMode: 'ceil', relativeTo: spring }); });
show('negative from next midnight', function () { return T.Duration.from({ hours: -23, minutes: -30 }).round({ largestUnit: 'day', smallestUnit: 'hour', relativeTo: T.ZonedDateTime.from('2024-03-11T00:00[America/New_York]') }); });
show('largest hour across DST', function () { return T.Duration.from({ days: 1, hours: 3 }).round({ largestUnit: 'hour', smallestUnit: 'minute', relativeTo: spring }); });
show('total month across DST', function () { return T.Duration.from({ days: 29, hours: 23 }).total({ unit: 'month', relativeTo: T.ZonedDateTime.from('2024-02-10T00:00[America/New_York]') }); });
show('round near max duration', function () { return T.Duration.from({ seconds: 9007199254740990 }).round({ smallestUnit: 'hour', roundingMode: 'ceil' }); });
show('round near max duration trunc', function () { return T.Duration.from({ seconds: 9007199254740990 }).round({ smallestUnit: 'hour', roundingMode: 'trunc' }); });
show('compare huge with relativeTo', function () { return T.Duration.compare({ days: 104249991374 }, { days: 104249991374, nanoseconds: 1 }, { relativeTo: '2020-01-01' }); });
show('compare weeks overflow with relativeTo', function () { return T.Duration.compare({ weeks: 1, seconds: 9007199254740991 }, { days: 1 }, { relativeTo: '2020-01-01' }); });
show('date add -25h', function () { return T.PlainDate.from('2020-01-10').add({ hours: -25 }); });
show('date add -48h', function () { return T.PlainDate.from('2020-01-10').add({ hours: -48 }); });
show('date subtract 25h', function () { return T.PlainDate.from('2020-01-10').subtract({ hours: 25 }); });
show('Monrovia instant toString', function () { return T.Instant.from('1950-01-01T00:00Z').toString({ timeZone: 'Africa/Monrovia' }); });
show('Monrovia zoned', function () { return T.Instant.from('1950-01-01T00:00Z').toZonedDateTimeISO('Africa/Monrovia').toString(); });
show('Monrovia 1972', function () { return T.Instant.from('1972-06-01T00:00Z').toString({ timeZone: 'Africa/Monrovia' }); });
show('offset field +010000', function () { return T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, offset: '+010000', timeZone: '+01:00' }); });
show('offset field +0100:00', function () { return T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, offset: '+0100:00', timeZone: '+01:00' }); });
show('offset field +01:0000', function () { return T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, offset: '+01:0000', timeZone: '+01:00' }); });
show('timeZone plain object', function () { return T.PlainDate.from('2020-01-01').toZonedDateTime({ timeZone: {} }); });
show('timeZone PlainDate object', function () { return T.Instant.from('2020-01-01T00:00Z').toZonedDateTimeISO(T.PlainDate.from('2020-01-01')); });
show('timeZone ZonedDateTime object', function () { return T.Instant.from('2020-01-01T00:00Z').toZonedDateTimeISO(T.ZonedDateTime.from('2020-01-01T00:00[Asia/Tokyo]')); });
show('equals offset vs named', function () { return [T.ZonedDateTime.from('2020-01-01T00:00[UTC]').equals(T.ZonedDateTime.from('2020-01-01T00:00[+00:00]')), T.ZonedDateTime.from('2020-01-01T00:00[+00:00]').equals(T.ZonedDateTime.from('2020-01-01T00:00[-00:00]')), T.ZonedDateTime.from('2020-01-01T00:00[Asia/Calcutta]').equals(T.ZonedDateTime.from('2020-01-01T00:00[Asia/Kolkata]'))].join(' '); });
"""
    check(js, golden, "zoned_rounding_across_dst_and_offset_edge_cases", body)


def test_difference_settings_defaults_and_extreme_ranges(js, golden):
    """CATCHES: until/since that do not default largestUnit to a calendar smallestUnit (ZonedDateTime/PlainDateTime), or rounding of the full-range date/zoned spans and zoned-relative duration rounding whose rounding boundary escapes the supported range without a RangeError, fails this."""
    body = r"""var T = Temporal;
var z1 = T.ZonedDateTime.from('2020-01-01T00:00[UTC]'), z2 = T.ZonedDateTime.from('2021-03-15T12:00[UTC]');
show('zoned smallestUnit day (largest auto)', function () { return z1.until(z2, { smallestUnit: 'day' }); });
show('zoned smallestUnit month (largest auto)', function () { return z1.until(z2, { smallestUnit: 'month' }); });
show('zoned since smallestUnit week ceil', function () { return z2.since(z1, { smallestUnit: 'week', roundingMode: 'ceil' }); });
show('zoned smallestUnit year halfExpand', function () { return z1.until(z2, { smallestUnit: 'year', roundingMode: 'halfExpand' }); });
var p1 = T.PlainDateTime.from('2020-01-01T00:00'), p2 = T.PlainDateTime.from('2021-03-15T12:00');
show('datetime smallestUnit year (largest auto)', function () { return p1.until(p2, { smallestUnit: 'year', roundingMode: 'halfExpand' }); });
show('datetime smallestUnit week (largest auto)', function () { return p1.until(p2, { smallestUnit: 'week' }); });
show('datetime smallestUnit month since', function () { return p2.since(p1, { smallestUnit: 'month', roundingMode: 'floor' }); });
var dMax = T.PlainDate.from('+275760-09-13'), dMin = T.PlainDate.from('-271821-04-19');
show('date span since, rounding beyond range', function () { return dMax.since(dMin, { smallestUnit: 'year', roundingIncrement: 1000, roundingMode: 'expand' }); });
show('date span until, rounding beyond range', function () { return dMin.until(dMax, { smallestUnit: 'month', roundingIncrement: 1000, roundingMode: 'expand' }); });
show('date span until, trunc', function () { return dMin.until(dMax, { largestUnit: 'year' }); });
show('zoned span until, rounding beyond range', function () { return T.ZonedDateTime.from('-271821-04-20T00:00[UTC]').until(T.ZonedDateTime.from('+275760-09-13T00:00[UTC]'), { smallestUnit: 'year', roundingIncrement: 1000, roundingMode: 'expand' }); });
show('zoned span since, months', function () { return T.ZonedDateTime.from('+275760-09-13T00:00[UTC]').since(T.ZonedDateTime.from('-271821-04-20T00:00[UTC]'), { largestUnit: 'month', smallestUnit: 'month', roundingIncrement: 1000, roundingMode: 'expand' }); });
var zMin = T.ZonedDateTime.from('-271821-04-20T00:00[UTC]');
show('duration round from zoned min, in range', function () { return T.Duration.from({ years: 500000 }).round({ smallestUnit: 'year', roundingIncrement: 1000, roundingMode: 'expand', relativeTo: zMin }); });
show('duration round from zoned min, beyond range', function () { return T.Duration.from({ years: 547000 }).round({ smallestUnit: 'year', roundingIncrement: 1000, roundingMode: 'ceil', relativeTo: zMin }); });
show('duration balance from zoned min', function () { return T.Duration.from({ days: 199000000 }).round({ largestUnit: 'year', relativeTo: zMin }); });
show('duration balance+round from zoned min beyond', function () { return T.Duration.from({ days: 199000000 }).round({ largestUnit: 'year', smallestUnit: 'year', roundingIncrement: 100000, roundingMode: 'ceil', relativeTo: zMin }); });
show('duration total months from zoned min', function () { return T.Duration.from({ years: 547000 }).total({ unit: 'month', relativeTo: zMin }); });
var zNearMax = T.ZonedDateTime.from('+275760-08-13T00:00[UTC]');
show('total month near max, end boundary in range', function () { return T.Duration.from({ days: 20 }).total({ unit: 'month', relativeTo: zNearMax }); });
show('total month near max, end boundary beyond', function () { return T.Duration.from({ days: 31 }).total({ unit: 'month', relativeTo: zNearMax }); });
show('total year near max', function () { return T.Duration.from({ days: 20 }).total({ unit: 'year', relativeTo: zNearMax }); });
show('round month near max', function () { return T.Duration.from({ days: 20 }).round({ smallestUnit: 'month', roundingMode: 'ceil', relativeTo: zNearMax }); });
show('bubble to year near max', function () { return T.Duration.from({ days: 30, hours: 23, minutes: 30 }).round({ largestUnit: 'year', smallestUnit: 'hour', relativeTo: zNearMax }); });
show('no bubble near max', function () { return T.Duration.from({ days: 20, hours: 12 }).round({ largestUnit: 'year', smallestUnit: 'day', roundingMode: 'ceil', relativeTo: zNearMax }); });
show('year-month until near max, year ceil', function () { return T.PlainYearMonth.from('+275760-08').until(T.PlainYearMonth.from('+275760-09'), { smallestUnit: 'year', roundingMode: 'ceil' }); });
show('year-month until near max, month increment', function () { return T.PlainYearMonth.from('+275760-07').until(T.PlainYearMonth.from('+275760-09'), { smallestUnit: 'month', roundingIncrement: 5, roundingMode: 'ceil' }); });
show('zoned largest minute across DST', function () { return T.ZonedDateTime.from('2020-01-01T00:00[America/New_York]').until(T.ZonedDateTime.from('2020-03-10T12:00[America/New_York]'), { largestUnit: 'minute', smallestUnit: 'minute', roundingIncrement: 30 }); });
show('hebrew datetime since largest hour', function () { return T.PlainDateTime.from('2020-01-01T00:00[u-ca=hebrew]').since(T.PlainDateTime.from('2019-12-30T12:00[u-ca=hebrew]'), { largestUnit: 'hour' }); });
"""
    check(js, golden, "difference_settings_defaults_and_extreme_ranges", body)


def test_zoned_with_options_and_field_validation(js, golden):
    """CATCHES: ZonedDateTime.with() not validating disambiguation/offset/overflow, era-calendar with() accepting a lone eraYear, the ZonedDateTime constructor accepting a non-string calendar, day/month 0 in bags not raising RangeError, or a sub-minute bracketed offset in an Instant string being accepted fails this."""
    body = r"""var T = Temporal;
var z = T.ZonedDateTime.from('2020-06-01T12:00[Asia/Tokyo][u-ca=gregory]');
show('zoned with bad disambiguation', function () { return z.with({ hour: 1 }, { disambiguation: 'bogus' }); });
show('zoned with bad offset option', function () { return z.with({ hour: 1 }, { offset: 'bogus' }); });
show('zoned with bad overflow', function () { return z.with({ hour: 1 }, { overflow: 'bogus' }); });
show('zoned with era+eraYear', function () { return z.with({ era: 'bce', eraYear: 5 }); });
show('date with eraYear only', function () { return T.PlainDate.from('2020-06-01[u-ca=gregory]').with({ eraYear: 2019 }); });
show('datetime with heisei 3', function () { return T.PlainDateTime.from('2020-06-01T00:00[u-ca=japanese]').with({ era: 'heisei', eraYear: 3 }); });
show('year-month with roc 1', function () { return T.PlainYearMonth.from({ year: 109, month: 6, calendar: 'roc' }).with({ era: 'roc', eraYear: 1 }); });
show('ZonedDateTime ctor numeric calendar', function () { return new T.ZonedDateTime(0n, 'UTC', 5); });
show('ZonedDateTime ctor bad calendar', function () { return new T.ZonedDateTime(0n, 'UTC', 'bogus'); });
show('ZonedDateTime ctor buddhist', function () { return new T.ZonedDateTime(0n, 'UTC', 'buddhist'); });
show('relativeTo day 0', function () { return T.Duration.from({ days: 1 }).round({ largestUnit: 'year', relativeTo: { year: 2020, month: 1, day: 0 } }); });
show('from day 0', function () { return T.PlainDate.from({ year: 2020, month: 1, day: 0 }); });
show('month-day day 0', function () { return T.PlainMonthDay.from({ month: 1, day: 0 }); });
show('year-month with month 0', function () { return T.PlainYearMonth.from({ year: 2020, month: 1 }).with({ month: 0 }); });
show('Instant with sub-minute bracket offset', function () { return T.Instant.from('2020-01-01T00:00Z[+01:00:30]'); });
show('Instant with bracket offset', function () { return T.Instant.from('2020-01-01T00:00Z[+01:00]'); });
show('Instant with bracket zone', function () { return T.Instant.from('2020-01-01T00:00+05:00[Asia/Tokyo]'); });
"""
    check(js, golden, "zoned_with_options_and_field_validation", body)


def test_calendar_conversions_far_from_epoch(js, golden):
    """CATCHES: Hebrew year resolution that drifts or loops forever for proleptic dates hundreds of millennia from the epoch, PlainYearMonth accepting months outside -271821-04..275760-09, or PlainDateTime.add producing a date past +275760-09-13 instead of throwing RangeError fails this."""
    body = r"""var T = Temporal;
[[-271821, 4, 19], [-200000, 3, 21], [-50000, 3, 22], [-1000, 3, 15], [1, 9, 7], [2023, 9, 16], [2024, 10, 2], [100000, 3, 21], [275760, 9, 13]].forEach(function (a) {
  show('hebrew ' + a.join('-'), function () { var h = new T.PlainDate(a[0], a[1], a[2]).withCalendar('hebrew'); return [h.year, h.monthCode, h.day, h.inLeapYear, h.monthsInYear, h.daysInYear].join(' '); });
});
show('year-month after the last month', function () { return T.PlainYearMonth.from({ year: 275761, month: 1 }); });
show('year-month before the first month', function () { return T.PlainYearMonth.from({ year: -271822, month: 12 }); });
show('year-month first representable', function () { return T.PlainYearMonth.from({ year: -271821, month: 4 }); });
show('year-month last representable', function () { return T.PlainYearMonth.from({ year: 275760, month: 9 }); });
show('datetime add past max date', function () { return T.PlainDateTime.from('+275760-09-13T00:00').add({ days: 1 }); });
show('datetime add hours past max date', function () { return T.PlainDateTime.from('+275760-09-12T23:00').add({ hours: 30 }); });
show('datetime add to last day', function () { return T.PlainDateTime.from('+275760-09-12T23:00').add({ hours: 20 }); });
"""
    check(js, golden, "calendar_conversions_far_from_epoch", body)


def test_temporal_primitive_options_arguments(js, golden):
    """CATCHES: Temporal methods that silently accept a primitive (number/boolean) options argument instead of throwing TypeError, or that throw for methods whose options are ignored (equals, PlainTime/Instant/Duration add), fails this."""
    body = r"""var T = Temporal;
var objs = { date: T.PlainDate.from('2020-01-01'), time: T.PlainTime.from('12:00'), datetime: T.PlainDateTime.from('2020-01-01T12:00'), yearmonth: T.PlainYearMonth.from('2020-01'), monthday: T.PlainMonthDay.from('01-01'), instant: T.Instant.from('2020-01-01T00:00Z'), zoned: T.ZonedDateTime.from('2020-01-01T00:00[UTC]'), duration: T.Duration.from('P1DT1H') };
Object.keys(objs).forEach(function (k) {
  var o = objs[k];
  ['toString', 'round', 'total', 'until', 'since', 'add', 'equals'].forEach(function (m) {
    if (typeof o[m] !== 'function') return;
    show(k + '.' + m, function () {
      if (m === 'toString' || m === 'round' || m === 'total') return o[m](5);
      if (m === 'add') return o.add(k === 'yearmonth' ? { months: 1 } : { hours: 1 }, true);
      return o[m](o, 5);
    });
  });
});
show('PlainDate.from(string, 5)', function () { return T.PlainDate.from('2020-01-01', 5); });
show('ZonedDateTime.from(string, 5)', function () { return T.ZonedDateTime.from('2020-01-01T00:00[UTC]', 5); });
show('Duration.compare options 5', function () { return T.Duration.compare({ hours: 1 }, { hours: 2 }, 5); });
show('roundingIncrement 0', function () { return T.Duration.from({ hours: 5 }).round({ smallestUnit: 'hour', roundingIncrement: 0 }); });
show('calendar-unit increments', function () { var a = T.PlainDate.from('2020-01-01'); return [a.until('2021-06-01', { smallestUnit: 'month', roundingIncrement: 5 }), a.until('2031-06-01', { smallestUnit: 'year', roundingIncrement: 3 }), a.until('2020-06-01', { smallestUnit: 'week', roundingIncrement: 7 })].join(' '); });
"""
    check(js, golden, "temporal_primitive_options_arguments", body)


# ------------------------------------------------------------------------------------------- Intl


def test_unicode_and_transform_extension_aliases(js, golden):
    """CATCHES: getCanonicalLocales that skips CLDR -u-tz/-ca/-ms/-ks/-kb/-kn type aliases or -t- tfield aliases, mis-parses a transformed-content language followed by tfields, accepts a tfield key without a value, or mishandles String objects, array-likes, Locale objects and non-string elements in the locale list fails this."""
    body = r"""['en-u-tz-cnckg', 'en-u-tz-eire', 'en-u-tz-est', 'en-u-tz-gmt0', 'en-u-tz-uct', 'en-u-tz-zulu', 'en-u-ca-islamicc', 'en-u-ca-ethiopic-amete-alem', 'en-u-ms-imperial', 'en-u-ks-primary', 'en-u-kb-yes', 'en-u-kn-true', 'en-t-de-h0-hybrid', 'en-t-und-m0-names', 'EN-T-ZH-HANT-M0-UNGEGN', 'de-t-en-latn-us-h0-hybrid-k0-qwerty', 'en-t-h0-hybrid', 'en-t-de-h0', 'en-t-de-h0-x'].forEach(function (t) {
  show(t, function () { return Intl.getCanonicalLocales(t).join(','); });
});
show('Locale object and duplicate string', function () { return Intl.getCanonicalLocales([new Intl.Locale('en-u-tz-eire'), 'en-u-tz-iedub', 'EN-u-TZ-EIRE']).join(','); });
show('Locale timeZone keyword', function () { return new Intl.Locale('en-u-tz-gmt0').toString(); });
show('String object is array-like', function () { return Intl.getCanonicalLocales(Object('de')); });
show('array-like object', function () { return Intl.getCanonicalLocales({ length: 2, 0: 'FR-ca', 1: 'fr-CA' }).join(','); });
show('number is boxed (no length)', function () { return JSON.stringify(Intl.getCanonicalLocales(5)); });
show('object with toString', function () { return Intl.getCanonicalLocales([{ toString: function () { return 'EN-gb'; } }]).join(','); });
show('null element', function () { return Intl.getCanonicalLocales([null]); });
"""
    check(js, golden, "unicode_and_transform_extension_aliases", body)


def test_locale_minimize_irreducible_tags(js, golden):
    """CATCHES: Intl.Locale.prototype.minimize that drops a script or region which the likely-subtags data cannot restore (en-Cyrl-US, de-Arab-AT, zh-Hant-CN) or fails to remove a recoverable one, or maximize that loses extensions, fails this."""
    body = r"""['en-Cyrl-US', 'sr-Latn-ME', 'zh-Hant-CN', 'ja-Latn-JP', 'de-Arab-AT', 'en-Latn-US-u-ca-gregory', 'und', 'zh-TW', 'pt-BR'].forEach(function (t) {
  show(t, function () { var l = new Intl.Locale(t); return l.minimize().toString() + ' / ' + l.maximize().toString(); });
});
"""
    check(js, golden, "locale_minimize_irreducible_tags", body)


def test_intl_legacy_constructed_fallback_symbol(js, golden):
    """CATCHES: calling Intl.NumberFormat/DateTimeFormat as a function on an object inheriting from their prototype without chaining the new instance under the realm's IntlLegacyConstructedSymbol (non-writable, non-enumerable), unwrapping that slot from non-inheriting objects or from a slot holding a non-formatter, or chaining Collator, fails this."""
    body = r"""var NF = Intl.NumberFormat;
var formatGetter = Object.getOwnPropertyDescriptor(NF.prototype, 'format').get;
show('plain object receiver', function () { return NF.prototype.resolvedOptions.call({}).locale; });
var o = Object.create(NF.prototype);
show('legacy call returns receiver', function () { return NF.call(o, 'de', { maximumFractionDigits: 1 }) === o; });
var syms = Object.getOwnPropertySymbols(o);
show('fallback symbol', function () { var d = Object.getOwnPropertyDescriptor(o, syms[0]); return syms.length + ' ' + String(syms[0]) + ' ' + d.writable + ' ' + d.enumerable + ' ' + d.configurable; });
show('format via unwrapped receiver', function () { return formatGetter.call(o)(1234.56); });
show('resolvedOptions via unwrapped receiver', function () { var r = NF.prototype.resolvedOptions.call(o); return r.locale + ' ' + r.maximumFractionDigits; });
show('format getter on prototype', function () { return NF.prototype.format; });
var fake = Object.create(NF.prototype);
Object.defineProperty(fake, syms[0], { value: { not: 'a formatter' } });
show('fallback slot holding a plain object', function () { return NF.prototype.resolvedOptions.call(fake); });
var detached = {};
Object.defineProperty(detached, syms[0], { value: new NF('fr') });
show('fallback slot on non-inheriting object', function () { return NF.prototype.resolvedOptions.call(detached); });
var d = Object.create(Intl.DateTimeFormat.prototype);
show('DateTimeFormat legacy call', function () { return Intl.DateTimeFormat.call(d, 'en', { timeZone: 'UTC', year: 'numeric' }) === d; });
show('DateTimeFormat via unwrapped receiver', function () { return Object.getOwnPropertyDescriptor(Intl.DateTimeFormat.prototype, 'format').get.call(d)(Date.UTC(2001, 1, 3)); });
show('same fallback symbol', function () { return Object.getOwnPropertySymbols(d)[0] === syms[0]; });
show('Collator has no legacy chain', function () { var c = Object.create(Intl.Collator.prototype); var r = Intl.Collator.call(c); return (r === c) + ' ' + Object.getOwnPropertySymbols(c).length + ' ' + (r instanceof Intl.Collator); });
"""
    check(js, golden, "intl_legacy_constructed_fallback_symbol", body)


def test_new_target_prototype_resolution_for_builtin_constructors(js, golden):
    """CATCHES: GetPrototypeFromConstructor in Intl services, typed arrays and Promise that fails to fall back to the intrinsic prototype when new.target is a bound function (no prototype), has a non-Function.prototype chain, or exposes a non-object prototype, or that swallows an exception thrown by new.target's prototype getter, fails this."""
    body = r"""function Base() {}
var bound = Base.bind(null);
var orphan = Base.bind(null);
Object.setPrototypeOf(orphan, Object.create(null));
var poisoned = new Proxy(function () {}, { get: function (t, k) { if (k === 'prototype') throw new EvalError('prototype getter'); return t[k]; } });
var numeric = new Proxy(function () {}, { get: function (t, k) { return k === 'prototype' ? 42 : t[k]; } });
var ctors = [['NumberFormat', Intl.NumberFormat, ['de']], ['DateTimeFormat', Intl.DateTimeFormat, ['en', { timeZone: 'UTC' }]], ['PluralRules', Intl.PluralRules, ['en']], ['Collator', Intl.Collator, ['en']], ['ListFormat', Intl.ListFormat, ['en']], ['Uint8Array', Uint8Array, [4]], ['Float64Array', Float64Array, [[1, 2]]], ['Promise', Promise, [function (r) { r(1); }]]];
ctors.forEach(function (c) {
  [['bound', bound], ['orphan', orphan], ['numeric', numeric], ['poisoned', poisoned]].forEach(function (nt) {
    show(c[0] + ' newTarget ' + nt[0], function () { var x = Reflect.construct(c[1], c[2], nt[1]); return Object.getPrototypeOf(x) === c[1].prototype; });
  });
});
"""
    check(js, golden, "new_target_prototype_resolution_for_builtin_constructors", body)


def test_intl_option_validation_errors(js, golden):
    """CATCHES: PluralRules digit/rounding options, DurationFormat numberingSystem/display/style-sequence options, or DateTimeFormat dateStyle/timeStyle getters that are not validated (or whose getter exceptions are swallowed) with the right RangeError/TypeError fails this."""
    body = r"""var bad = [
  ['PluralRules maximumFractionDigits 101', function () { return new Intl.PluralRules('en', { maximumFractionDigits: 101 }); }],
  ['PluralRules minimumFractionDigits > maximum', function () { return new Intl.PluralRules('en', { minimumFractionDigits: 4, maximumFractionDigits: 2 }); }],
  ['PluralRules roundingIncrement Symbol', function () { return new Intl.PluralRules('en', { roundingIncrement: Symbol('r') }); }],
  ['PluralRules roundingMode up', function () { return new Intl.PluralRules('en', { roundingMode: 'up' }); }],
  ['PluralRules roundingPriority most', function () { return new Intl.PluralRules('en', { roundingPriority: 'most' }); }],
  ['PluralRules trailingZeroDisplay never', function () { return new Intl.PluralRules('en', { trailingZeroDisplay: 'never' }); }],
  ['PluralRules type getter throws', function () { return new Intl.PluralRules('en', { get type() { throw new URIError('type getter'); } }); }],
  ['PluralRules valid digits', function () { var r = new Intl.PluralRules('en', { maximumFractionDigits: 2 }); return r.select(1) + ' ' + r.select(1.5) + ' ' + r.resolvedOptions().maximumFractionDigits; }],
  ['DurationFormat numberingSystem arab', function () { var r = new Intl.DurationFormat('en', { numberingSystem: 'arab' }).resolvedOptions(); return r.numberingSystem + ' ' + r.locale; }],
  ['DurationFormat numberingSystem x', function () { return new Intl.DurationFormat('en', { numberingSystem: 'x' }); }],
  ['DurationFormat hoursDisplay sometimes', function () { return new Intl.DurationFormat('en', { hoursDisplay: 'sometimes' }); }],
  ['DurationFormat seconds numeric then milliseconds long', function () { return new Intl.DurationFormat('en', { seconds: 'numeric', milliseconds: 'long' }); }],
  ['DurationFormat minutes numeric then seconds long', function () { return new Intl.DurationFormat('en', { minutes: 'numeric', seconds: 'long' }); }],
  ['DurationFormat non-object', function () { return new Intl.DurationFormat('en').format(5); }],
  ['DateTimeFormat dateStyle huge', function () { return new Intl.DateTimeFormat('en', { dateStyle: 'huge' }); }],
  ['DateTimeFormat dateStyle getter throws', function () { return new Intl.DateTimeFormat('en', { get dateStyle() { throw new EvalError('dateStyle getter'); } }); }],
  ['DateTimeFormat timeStyle getter throws', function () { return new Intl.DateTimeFormat('en', { get timeStyle() { throw new RangeError('timeStyle getter'); } }); }]
];
bad.forEach(function (b) { show(b[0], b[1]); });
"""
    check(js, golden, "intl_option_validation_errors", body)


def test_collator_extension_resolution_and_marks(js, golden):
    """CATCHES: Collator ResolveLocale that keeps an unsupported -u-co- value, drops supported ones, orders or keeps -u-kf/-u-kn keywords wrongly when options agree or disagree, or collation that mis-sorts strings starting with a combining mark or treats lone surrogates and punctuation wrongly under ignorePunctuation fails this."""
    body = r"""function ro(l, o) { var r = new Intl.Collator(l, o).resolvedOptions(); return r.locale + ' co=' + r.collation + ' kn=' + r.numeric + ' kf=' + r.caseFirst; }
['en-u-co-bogus', 'en-u-co-phonebk', 'de-u-co-phonebk', 'zh-u-co-pinyin', 'en-u-kn-false', 'en-u-kn', 'en-u-kf-upper-kn-false', 'en-u-kn-false-kf-lower'].forEach(function (l) {
  show(l, function () { return ro(l); });
});
show('option overrides kn', function () { return ro('en-u-kn-false', { numeric: true }) + ' | ' + ro('en-u-kn', { numeric: false }) + ' | ' + ro('en-u-kf-upper', { caseFirst: 'upper' }); });
var c = new Intl.Collator('en');
show('leading combining marks', function () { return [c.compare('\u0301a', '\u0301b'), c.compare('\u0301b', '\u0301a'), c.compare('\u0301a', '\u0301a')].join(' '); });
var ip = new Intl.Collator('en', { ignorePunctuation: true });
show('ignorePunctuation', function () { return [ip.compare('a\ud800', 'a'), ip.compare('a.b', 'ab'), ip.compare('a\u2010b', 'ab'), ip.compare('a b', 'ab'), ip.resolvedOptions().ignorePunctuation].join(' '); });
"""
    check(js, golden, "collator_extension_resolution_and_marks", body)


def test_number_format_zero_significant_padding_and_suffix_currency_range(js, golden):
    """CATCHES: minimumSignificantDigits padding that is not applied to zero (Number, numeric string and BigInt inputs), negative zero losing its sign, scientific notation of exact powers of ten, or a pt-PT currency range that repeats the trailing euro sign fails this."""
    body = r"""function nf(o, l) { return new Intl.NumberFormat(l || 'en-US', o); }
show('minimumSignificantDigits on zero', function () { return [nf({ minimumSignificantDigits: 3 }).format(0), nf({ minimumSignificantDigits: 3 }).format('0'), nf({ minimumSignificantDigits: 3 }).format(0n), nf({ minimumSignificantDigits: 1 }).format(0), nf({ minimumSignificantDigits: 2, maximumSignificantDigits: 4 }).format(-0)].join(' '); });
show('scientific powers of ten', function () { return [1e3, 1e6, 1e-3, 1e15, 1e21, 12345, 0.00012345].map(function (x) { return nf({ notation: 'scientific' }).format(x); }).join(' '); });
show('engineering', function () { return [1e3, 1e-5, 1e22, 12345, 0.00012345].map(function (x) { return nf({ notation: 'engineering' }).format(x); }).join(' '); });
show('scientific parts', function () { return nf({ notation: 'scientific' }).formatToParts(-1000).map(function (p) { return p.type + ':' + p.value; }).join(' '); });
show('pt-PT currency range', function () { return nf({ style: 'currency', currency: 'EUR' }, 'pt-PT').formatRange(3, 5); });
"""
    check(js, golden, "number_format_zero_significant_padding_and_suffix_currency_range", body)


# --------------------------------------------------------------------------------- RegExp / regex


def test_regexp_replace_exceeding_string_length_limit(js, golden):
    """CATCHES: RegExp.prototype[Symbol.replace] that keeps concatenating a replacement past the engine's maximum string length (crashing or allocating unboundedly) instead of throwing RangeError: Invalid string length, while smaller expansions still succeed, fails this."""
    body = r"""var big = 'a'.repeat(1 << 20);
show('replace expanding past the string limit', function () { return 'x'.repeat(70).replace(/x/g, big).length; });
show('replace below the limit', function () { return 'x'.repeat(3).replace(/x/g, big).length; });
show('replace with $1 below the limit', function () { return 'k1k2'.replace(/k(\d)/g, '[$1]'); });
"""
    check(js, golden, "regexp_replace_exceeding_string_length_limit", body)


@pytest.mark.parametrize("tier", TIERS)
def test_dead_result_split_guard_fallbacks(js, golden, tier):
    """CATCHES: an unused-result `s.split(re)` fast path that updates RegExp legacy statics for a sticky regexp that never matches before the end, or that keeps running after RegExp.prototype.constructor is replaced or globalThis.RegExp becomes an accessor, diverging from the ordinary split in any tier, fails this."""
    code = r"""var log = [];
function spl(s, re) { s.split(re); return 0; }
function statics(label) { log.push(label + ': $1=' + JSON.stringify(RegExp.$1) + ' lastMatch=' + JSON.stringify(RegExp.lastMatch) + ' input=' + JSON.stringify(RegExp.input)); }
RegExp.input = 'reset'; /(-)/.exec('-');
for (var k = 0; k < 30; k++) spl('abc', /$/y);
statics('sticky $ never matches before the end');
for (var k = 0; k < 30; k++) spl('xa1', /(\d)$/y);
statics('sticky match at the last position');
for (var k = 0; k < 30; k++) spl('p1q2r', /(\d)/y);
statics('sticky split');
var origCtor = RegExp.prototype.constructor;
RegExp.prototype.constructor = Object;
for (var k = 0; k < 30; k++) spl('q8r', /(\d)/);
statics('prototype.constructor replaced');
log.push('result with replaced constructor: ' + JSON.stringify('q8r'.split(/(\d)/)));
RegExp.prototype.constructor = origCtor;
var R = RegExp;
Object.defineProperty(globalThis, 'RegExp', { get: function () { return R; }, configurable: true });
for (var k = 0; k < 30; k++) spl('w4x', /(\d)/);
log.push('accessor global: $1=' + R.$1 + ' lastMatch=' + R.lastMatch);
log.push('result: ' + JSON.stringify('w5x'.split(/(\d)/)));
console.log(log.join('\n'));
"""
    r = js(code, *tier)
    assert out(r) == golden("dead_result_split_guard_fallbacks")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_case_insensitive_lone_surrogates(js, golden, tier):
    """CATCHES: a case-insensitive matcher that tries to case-fold lone surrogate code units (panicking or folding them onto other units) in backreferences, literals and classes, with and without the u flag, fails this."""
    body = r"""show('backreference of a lone high surrogate, /i', function () { return [/(.)\1/i.test('\ud800\ud800'), /(.)\1/i.test('\ud800\udbff'), /(\ud83d)\1/i.test('\ud83d\ud83d'), /(.)\1/i.exec('a\udc00\udc00b').index].join(' '); });
show('lone surrogate literal /i', function () { return [/\ud800/i.test('\ud800'), /\udc00x/i.test('\udc00X'), /[\ud800-\udbff]/i.test('\udb00'), /^[^\ud800]$/i.test('\ud801')].join(' '); });
show('lone surrogate /iu', function () { return [/\ud800/iu.test('\ud800'), /(.)\1/iu.test('\ud800\ud800'), /\u{1F600}/iu.test('\u{1F600}')].join(' '); });
show('ascii vs surrogate backref', function () { return [/(a)\1/i.test('aA'), /(.)\1/i.test('\ud800a'), /(\udc00)\1/i.test('\udc00\udc01')].join(' '); });
"""
    check(js, golden, "case_insensitive_lone_surrogates", body, tier)


# ------------------------------------------------------------------------- binary data / JSON


def test_typed_array_join_and_locale_string_over_shrinking_buffer(js, golden):
    """CATCHES: %TypedArray%.prototype.join/toLocaleString that do not capture the length up front and render out-of-bounds elements (after a resizable buffer shrinks during separator coercion or an element's toLocaleString) as empty strings, or that read stale bytes after the buffer grows back, fails this."""
    body = r"""var rab = new ArrayBuffer(8, { maxByteLength: 8 });
var ta = new Uint8Array(rab);
ta.set([1, 2, 3, 4, 5, 6, 7, 8]);
show('join with a separator that shrinks the buffer', function () { return ta.join({ toString: function () { rab.resize(3); return '-'; } }) + ' length now ' + ta.length; });
rab.resize(8); ta.set([1, 2, 3, 4, 5, 6, 7, 8]);
show('toLocaleString shrinking mid-way', function () {
  var orig = Number.prototype.toLocaleString, n = 0;
  Number.prototype.toLocaleString = function () { if (++n === 2) rab.resize(3); return '<' + this + '>'; };
  try { return ta.toLocaleString() + ' calls=' + n; } finally { Number.prototype.toLocaleString = orig; }
});
rab.resize(8);
show('toLocaleString after growing back', function () { return ta.toLocaleString(); });
"""
    check(js, golden, "typed_array_join_and_locale_string_over_shrinking_buffer", body)


def test_uint8array_codecs_receivers_and_immutable_buffers(js, golden):
    """CATCHES: Uint8Array toHex/toBase64/setFromHex accepting other typed-array kinds, writes into views over immutable ArrayBuffers (setFromBase64/setFromHex/sort/resize) not throwing TypeError, or SharedArrayBuffer.prototype.slice accepting a plain ArrayBuffer fails this."""
    body = r"""show('toHex on Int8Array', function () { return Uint8Array.prototype.toHex.call(new Int8Array([1, -1])); });
show('toBase64 on Uint16Array', function () { return Uint8Array.prototype.toBase64.call(new Uint16Array(2)); });
show('setFromHex on Int8Array', function () { return Uint8Array.prototype.setFromHex.call(new Int8Array(2), 'ff'); });
show('toHex on Uint8Array', function () { return new Uint8Array([0, 15, 255]).toHex(); });
show('immutable setFromBase64', function () { return new Uint8Array(new ArrayBuffer(8).transferToImmutable()).setFromBase64('AAAA'); });
show('immutable setFromHex', function () { return new Uint8Array(new ArrayBuffer(8).transferToImmutable()).setFromHex('ff'); });
show('immutable resize', function () { return new ArrayBuffer(8, { maxByteLength: 16 }).transferToImmutable().resize(4); });
show('immutable sort', function () { return new Uint8Array(new ArrayBuffer(4).transferToImmutable()).sort(); });
show('immutable read', function () { var b = new ArrayBuffer(2); new Uint8Array(b).set([7, 9]); var im = b.transferToImmutable(); return new Uint8Array(im).join() + ' ' + im.immutable + ' ' + b.detached; });
show('SharedArrayBuffer slice on ArrayBuffer', function () { return SharedArrayBuffer.prototype.slice.call(new ArrayBuffer(8), 0, 4); });
show('SharedArrayBuffer slice', function () { var s = new SharedArrayBuffer(8); new Uint8Array(s).set([1, 2, 3, 4, 5, 6, 7, 8]); return new Uint8Array(s.slice(2, 6)).join(); });
"""
    check(js, golden, "uint8array_codecs_receivers_and_immutable_buffers", body)


def test_json_parse_surrogate_escapes_and_proxy_revivers(js, golden):
    """CATCHES: JSON.parse that pairs a \\uD800 escape with a following non-low-surrogate escape, mis-reports bad escapes, ignores a proxy's ownKeys/defineProperty/deleteProperty traps while a reviver walks it (swallowing a throwing trap, or throwing when the trap returns false), or JSON.rawJSON objects that are not frozen null-prototype primitives fails this."""
    body = r"""show('high surrogate escape then non-low escape', function () { var s = JSON.parse('"\\ud800\\u0041"'); return s.length + ' ' + s.charCodeAt(0).toString(16) + ' ' + s.charCodeAt(1).toString(16) + ' ' + JSON.stringify(s); });
show('high surrogate escape then high escape', function () { var s = JSON.parse('"\\ud800\\ud801x"'); return s.length + ' ' + JSON.stringify(s); });
show('escaped pair', function () { var s = JSON.parse('"\\ud83d\\ude00"'); return s.length + ' ' + s.codePointAt(0).toString(16); });
show('high surrogate escape then bad escape', function () { return JSON.parse('"\\ud800\\uZZZZ"'); });
show('reviver sees proxy ownKeys', function () {
  var log = [];
  var r = JSON.parse('{"a":1,"b":{"c":3}}', function (k, v) {
    log.push(k);
    if (k === 'a') this.b = new Proxy({ c: 5, d: 6 }, { ownKeys: function () { log.push('ownKeys'); return ['d', Symbol('z'), 'c']; } });
    return typeof v === 'number' ? v * 10 : v;
  });
  return log.join(',') + ' ' + JSON.stringify(r);
});
show('reviver result into proxy whose defineProperty throws', function () {
  return JSON.parse('{"a":1,"b":0}', function (k, v) {
    if (k === 'a') this.b = new Proxy({ c: 5 }, { defineProperty: function () { throw new EvalError('no define'); } });
    return typeof v === 'number' ? v + 1 : v;
  });
});
show('reviver result into proxy whose defineProperty returns false', function () {
  var r = JSON.parse('{"a":1,"b":0}', function (k, v) {
    if (k === 'a') this.b = new Proxy({ c: 5 }, { defineProperty: function () { return false; } });
    return typeof v === 'number' ? v + 1 : v;
  });
  return JSON.stringify(r);
});
show('reviver deleting through a proxy', function () {
  var log = [];
  var r = JSON.parse('{"a":1,"b":0}', function (k, v) {
    if (k === 'a') this.b = new Proxy({ c: 5, e: 1 }, { deleteProperty: function (t, key) { log.push('delete ' + key); return delete t[key]; } });
    return k === 'c' ? undefined : v;
  });
  return log.join(',') + ' ' + JSON.stringify(r);
});
show('rawJSON', function () { return JSON.stringify({ x: JSON.rawJSON('1e1000'), y: [JSON.rawJSON('"s"'), JSON.rawJSON('null')] }) + ' ' + JSON.isRawJSON(JSON.rawJSON('1')) + ' ' + JSON.isRawJSON({ rawJSON: '1' }); });
show('rawJSON object', function () { var r = JSON.rawJSON('true'); return Object.isFrozen(r) + ' ' + Object.getPrototypeOf(r) + ' ' + r.rawJSON + ' ' + Object.keys(r); });
show('rawJSON rejects objects', function () { return JSON.rawJSON('{}'); });
show('rawJSON rejects whitespace', function () { return JSON.rawJSON(' 1'); });
"""
    check(js, golden, "json_parse_surrogate_escapes_and_proxy_revivers", body)


# ------------------------------------------------------------------- collections / reflection / misc


def test_set_methods_size_shortcuts_and_weakmap_upsert(js, golden):
    """CATCHES: Set.prototype.isSupersetOf/isDisjointFrom not using the size shortcut and receiver walk the spec requires, set-like keys() iterators without a callable next or with non-object results not rejected, Map.groupBy not validating/propagating its callback, or WeakMap getOrInsert/getOrInsertComputed mishandling existing keys, invalid keys and non-callable callbacks fails this."""
    body = r"""function setLike(vals, extra) { var o = { size: vals.length, has: function (v) { return vals.indexOf(v) >= 0; }, keys: function () { var i = 0; return { next: function () { return i < vals.length ? { done: false, value: vals[i++] } : { done: true }; } }; } }; return Object.assign(o, extra || {}); }
show('isSupersetOf smaller receiver', function () { return new Set([1]).isSupersetOf(new Set([1, 2])) + ' ' + new Set([1, 2]).isSupersetOf(new Set([1, 2])); });
show('isSupersetOf smaller receiver skips keys()', function () { var called = false; var r = new Set([1]).isSupersetOf(setLike([1, 2], { keys: function () { called = true; return { next: function () { return { done: true }; } }; } })); return r + ' keysCalled=' + called; });
show('isDisjointFrom walking receiver to the end', function () { var probes = []; var r = new Set([1, 4]).isDisjointFrom(setLike([2, 3, 5], { has: function (v) { probes.push(v); return false; } })); return r + ' probes=' + probes.join(','); });
show('isDisjointFrom early exit', function () { return new Set([1, 4]).isDisjointFrom(setLike([4, 3, 5])); });
show('union keys without next', function () { return new Set([1]).union(setLike([2], { keys: function () { return { next: 5 }; } })); });
show('union keys result not an object', function () { return new Set([1]).union(setLike([2], { keys: function () { return { next: function () { return 7; } }; } })); });
show('symmetricDifference', function () { return [...new Set([1, 2, 3]).symmetricDifference(new Set([1, 1, 4]))].join(); });
show('Map.groupBy non-callable', function () { return Map.groupBy([1], 5); });
show('Map.groupBy callback throws', function () { return Map.groupBy([1, 2], function (x) { if (x === 2) throw new EvalError('group ' + x); return x; }); });
show('Map.groupBy', function () { var m = Map.groupBy([1, 2, 3, 4, -0], function (x) { return x % 2 === 0 ? 0 : 'odd'; }); return [...m.keys()].map(String).join() + ' ' + m.get(0).join() + ' ' + Object.is(m.get(0)[2], -0); });
var wm = new WeakMap(); var k1 = {};
wm.set(k1, 'one');
show('WeakMap getOrInsert existing', function () { return wm.getOrInsert(k1, 'two') + ' ' + wm.get(k1); });
show('WeakMap getOrInsertComputed primitive key', function () { return wm.getOrInsertComputed(1, function () { return 2; }); });
show('WeakMap getOrInsertComputed registered symbol', function () { return wm.getOrInsertComputed(Symbol.for('reg'), function () { return 3; }); });
show('WeakMap getOrInsertComputed non-callable', function () { return wm.getOrInsertComputed({}, 3); });
show('WeakMap getOrInsertComputed existing skips callback', function () { return wm.getOrInsertComputed(k1, function () { throw new Error('not called'); }); });
show('WeakMap getOrInsertComputed new key', function () { var k = {}; var seen; var v = wm.getOrInsertComputed(k, function (kk) { seen = kk === k; return 'computed'; }); return v + ' ' + wm.get(k) + ' ' + seen; });
show('WeakMap getOrInsertComputed symbol key', function () { var s = Symbol('w'); return wm.getOrInsertComputed(s, function () { return 'sym'; }) + ' ' + wm.has(s); });
"""
    check(js, golden, "set_methods_size_shortcuts_and_weakmap_upsert", body)


def test_reflect_on_module_namespace_and_throwing_proxy_traps(js, golden):
    """CATCHES: Reflect.getOwnPropertyDescriptor on a module namespace object that does not report live, writable, non-configurable export bindings (or the Module @@toStringTag), or Reflect.set/defineProperty on proxies that swallow trap exceptions or misreport trap results, fails this."""
    code = r"""import * as self from './main.mjs';
export let counter = 1;
export function helper() {}
export default 'dflt';
var out = [];
function show(label, f) { try { out.push(label + ': ' + String(f())); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
show('namespace binding descriptor', function () { return JSON.stringify(Reflect.getOwnPropertyDescriptor(self, 'counter')); });
counter = 2;
show('namespace binding is live', function () { return Reflect.getOwnPropertyDescriptor(self, 'counter').value + ' ' + self.counter; });
show('namespace default descriptor', function () { return JSON.stringify(Reflect.getOwnPropertyDescriptor(self, 'default')); });
show('namespace missing name', function () { return Reflect.getOwnPropertyDescriptor(self, 'nope'); });
show('namespace toStringTag', function () { var d = Reflect.getOwnPropertyDescriptor(self, Symbol.toStringTag); return d.value + ' ' + d.writable + ' ' + d.configurable; });
show('namespace keys', function () { return Reflect.ownKeys(self).map(String).join(','); });
var p = new Proxy({}, { set: function () { throw new EvalError('set trap'); }, defineProperty: function () { throw new URIError('defineProperty trap'); } });
show('Reflect.set with throwing trap', function () { return Reflect.set(p, 'a', 1); });
show('Reflect.defineProperty with throwing trap', function () { return Reflect.defineProperty(p, 'a', { value: 1 }); });
var receiver = {};
var q = new Proxy({}, { set: function (t, k, v, r) { return r === receiver; }, defineProperty: function () { return false; } });
show('Reflect.set trap result', function () { return Reflect.set(q, 'a', 1, receiver) + ' ' + Reflect.set(q, 'a', 1); });
show('Reflect.defineProperty false', function () { return Reflect.defineProperty(q, 'a', { value: 1 }); });
console.log(out.join('\n'));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("reflect_on_module_namespace_and_throwing_proxy_traps")
    assert (r.returncode, r.stderr) == (0, b"")


def test_bigint_comparisons_and_epoch_range_errors(js, golden):
    """CATCHES: BigInt/Number relational comparisons that mishandle negative fractions, subnormals or 2^64, multi-limb carries, two's-complement bitwise results on negative multi-limb values, or Temporal epoch-nanosecond constructors that wrap BigInts beyond 128 bits instead of throwing RangeError (while accepting exactly ±8.64e21) fails this."""
    body = r"""show('BigInt vs fractional Number', function () { return [-4n > -4.5, -4n < -4.5, 4n < 4.5, -5n < -4.5, 5n > 4.999, -5n == -5.0, 0n < 5e-324, 0n > -5e-324, 1n > 5e-324, 0n == 5e-324, -1n < -5e-324, 2n ** 64n > 1.8446744073709552e19, 2n ** 64n == 1.8446744073709552e19].join(' '); });
show('BigInt shifts and carries', function () { return [0n << 5n, 0n << 100n, (2n ** 128n - 1n) + 1n, (2n ** 192n - 1n) + 1n, -(2n ** 128n) - (2n ** 128n - 1n)].join(' '); });
show('BigInt two\'s complement bitwise ops', function () { return [-(2n ** 64n) & -(2n ** 64n), -(2n ** 64n) | 0n, ~(2n ** 64n - 1n), -(2n ** 128n) ^ 0n, -(2n ** 128n) & -1n, -(2n ** 64n) >> 1n, BigInt.asIntN(128, -(2n ** 64n)), BigInt.asUintN(65, -(2n ** 64n))].join(' '); });
show('Instant from huge BigInt', function () { return new Temporal.Instant(2n ** 200n); });
show('Instant from 2^127', function () { return new Temporal.Instant(2n ** 127n); });
show('Instant from -2^127-1', function () { return new Temporal.Instant(-(2n ** 127n) - 1n); });
show('ZonedDateTime from 2^128', function () { return new Temporal.ZonedDateTime(2n ** 128n, 'UTC'); });
show('fromEpochNanoseconds -2^130', function () { return Temporal.Instant.fromEpochNanoseconds(-(2n ** 130n)); });
show('Instant at the limit', function () { return String(new Temporal.Instant(8640000000000000000000n)) + ' ' + String(new Temporal.Instant(-8640000000000000000000n)); });
show('Instant just past the limit', function () { return new Temporal.Instant(8640000000000000000001n); });
"""
    check(js, golden, "bigint_comparisons_and_epoch_range_errors", body)


def test_misc_builtin_edge_cases(js, golden):
    """CATCHES: String.prototype.codePointAt on non-ASCII strings returning a value for negative/infinite positions, Map iterator next accepting a foreign receiver, Function.prototype.bind ignoring a null or proxy-reported prototype, Atomics.wait mis-reporting not-equal/timed-out or accepting non-shared arrays, or Math.sumPrecise losing -0 or exactness fails this."""
    body = r"""show('codePointAt outside a non-ASCII string', function () { return ['\u00e9'.codePointAt(-1), '\u00e9'.codePointAt(Infinity), '\u00e9'.codePointAt(-0.5), '\u00e9\u{1F600}'.codePointAt(1), '\u00e9\u{1F600}'.codePointAt(2), '\u00e9\u{1F600}'.codePointAt(NaN), '\u00e9\u{1F600}'.codePointAt(3)].map(String).join(' '); });
show('Map iterator next on a plain object', function () { return new Map().entries().next.call({}); });
show('bind keeps a null prototype', function () { var f = function () {}; Object.setPrototypeOf(f, null); var b = Function.prototype.bind.call(f); return (Object.getPrototypeOf(b) === null) + ' ' + b.name; });
show('bind through proxy getPrototypeOf', function () { var p = new Proxy(function g() {}, { getPrototypeOf: function () { return Array.prototype; } }); return Object.getPrototypeOf(p.bind()) === Array.prototype; });
show('Atomics.wait not-equal with infinite timeout', function () { return Atomics.wait(new Int32Array(new SharedArrayBuffer(8)), 0, 1, Infinity); });
show('Atomics.wait zero timeout', function () { return Atomics.wait(new Int32Array(new SharedArrayBuffer(8)), 1, 0, 0); });
show('Atomics.wait on non-shared', function () { return Atomics.wait(new Int32Array(4), 0, 0, 0); });
show('Math.sumPrecise empty and signed zeros', function () { return [Object.is(Math.sumPrecise([]), -0), Object.is(Math.sumPrecise([-0, -0]), -0), Object.is(Math.sumPrecise([-0, 0]), 0), Math.sumPrecise([1e308, 1e308, -1e308]), Math.sumPrecise([0.1, 0.2, -0.3])].join(' '); });
"""
    check(js, golden, "misc_builtin_edge_cases", body)
