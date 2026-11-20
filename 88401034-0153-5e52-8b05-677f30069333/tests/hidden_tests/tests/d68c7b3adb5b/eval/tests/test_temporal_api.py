"""Temporal API surface for lumen-cli: every Temporal type's getters, conversions, with/add/subtract,
until/since/round option handling, property-bag and ISO/RFC 9557 string parsing, calendar-aware
fields, time-zone aware arithmetic with the bundled tz data, Duration balancing/rounding/total, and
argument validation errors. Every instant comes from a fixed epoch value or literal; nothing reads
the wall clock (Temporal.Now is never used)."""

import pytest

from conftest import out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# Shared helpers: show() prints a labelled result or the thrown error's name and message; each()
# maps a list of thunks to their results (errors rendered the same way).
PRELUDE = r"""var out = [];
function show(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
function each(label, fs) { out.push(label + ': ' + fs.map(function (f) { try { return String(f()); } catch (e) { return e.name + ':' + e.message; } }).join(' | ')); }
"""
EPILOGUE = "\nconsole.log(out.join('\\n'));\n"


def check(js, golden, tier, name, body):
    r = js(PRELUDE + body + EPILOGUE, *tier)
    assert out(r) == golden(name)
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_iso_getters_and_week_numbering(js, golden, tier):
    """CATCHES: ISO week numbering that assigns early-January or late-December days to the wrong week-year, wrong dayOfYear/daysInMonth/inLeapYear for leap and extended years, or era fields defined for the iso8601 calendar fails this."""
    body = r"""var P = Temporal.PlainDate;
function g(d) { return [d.calendarId, d.era, d.eraYear, d.year, d.month, d.monthCode, d.day, d.dayOfWeek, d.dayOfYear, d.weekOfYear, d.yearOfWeek, d.daysInWeek, d.daysInMonth, d.daysInYear, d.monthsInYear, d.inLeapYear].join(','); }
['2020-12-31', '2021-01-01', '2021-01-03', '2021-01-04', '2024-12-30', '2026-12-31', '2027-01-01', '2008-12-29', '2010-01-03', '-000001-06-15', '+010000-02-29', '1900-02-28'].forEach(function (s) { show(s, function () { return g(P.from(s)); }); });
show('constructor', function () { return [new P(2024, 2, 29).toString(), new P(2023, 12, 31, 'gregory').toString(), new P('2020', '01', '05').toString(), new P(1.9, 1.9, 1.9).toString()].join(' '); });
each('constructor errors', [function () { return new P(2023, 2, 29); }, function () { return new P(2024, 0, 1); }, function () { return new P(275760, 9, 14); }, function () { return new P(Infinity, 1, 1); }, function () { return new P(2024, 1, 1, 'nope'); }, function () { return P(2024, 1, 1); }]);
"""
    check(js, golden, tier, "plain_date_iso_getters_and_week_numbering", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_getters_in_every_calendar(js, golden, tier):
    """CATCHES: non-ISO calendar field computation (era/eraYear/year/month/monthCode/day, month and year lengths, leap years) that is wrong for any supported calendar, or week fields that are not undefined outside iso8601, fails this."""
    body = r"""var P = Temporal.PlainDate;
function g(d) { return [d.era, d.eraYear, d.year, d.month, d.monthCode, d.day, d.dayOfWeek, d.dayOfYear, d.weekOfYear, d.yearOfWeek, d.daysInWeek, d.daysInMonth, d.daysInYear, d.monthsInYear, d.inLeapYear].join(','); }
['gregory', 'japanese', 'buddhist', 'roc', 'hebrew', 'islamic-civil', 'islamic-tbla', 'islamic-umalqura', 'chinese', 'dangi', 'persian', 'indian', 'ethiopic', 'ethioaa', 'coptic', 'iso8601'].forEach(function (c) {
  show(c, function () { return ['2024-02-29', '1900-01-01', '1989-01-07', '2025-03-21'].map(function (s) { var d = P.from(s).withCalendar(c); if (d.calendarId !== c) throw new Error('calendarId ' + d.calendarId); return g(d); }).join(' | '); });
});
"""
    check(js, golden, tier, "plain_date_getters_in_every_calendar", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_conversions(js, golden, tier):
    """CATCHES: PlainDate conversions (toPlainDateTime, toPlainYearMonth, toPlainMonthDay with non-ISO reference years, withCalendar argument kinds, toZonedDateTime with string or bag and DST gaps, toString calendarName) that compute or validate wrongly fail this."""
    body = r"""var P = Temporal.PlainDate;
var d = P.from('2024-01-31');
show('toPlainDateTime', function () { return [d.toPlainDateTime().toString(), d.toPlainDateTime('12:34:56.789').toString(), d.toPlainDateTime({ hour: 23, minute: 59 }).toString(), d.withCalendar('coptic').toPlainDateTime('01:02').toString()].join(' '); });
show('toPlainDateTime bad', function () { return d.toPlainDateTime('25:00'); });
show('toPlainDateTime limit', function () { return P.from('-271821-04-19').toPlainDateTime('00:00'); });
show('toPlainYearMonth', function () { return [d.toPlainYearMonth().toString(), P.from('2024-03-15[u-ca=hebrew]').toPlainYearMonth().toString(), P.from('2024-03-15[u-ca=chinese]').toPlainYearMonth().toString(), P.from('2024-03-15[u-ca=japanese]').toPlainYearMonth().toString()].join(' '); });
show('toPlainMonthDay', function () { return [d.toPlainMonthDay().toString(), P.from('2024-02-29').toPlainMonthDay().toString(), P.from('2024-03-15[u-ca=hebrew]').toPlainMonthDay().toString(), P.from('2024-03-15[u-ca=islamic-civil]').toPlainMonthDay().toString(), P.from('2023-04-01[u-ca=chinese]').toPlainMonthDay().toString(), P.from('2024-03-15[u-ca=gregory]').toPlainMonthDay().toString(), P.from('2024-03-20[u-ca=persian]').toPlainMonthDay().toString()].join(' '); });
show('withCalendar', function () { return [d.withCalendar('hebrew').toString(), d.withCalendar(P.from('2020-01-01[u-ca=japanese]')).toString(), d.withCalendar(Temporal.ZonedDateTime.from('2020-01-01T00:00[UTC][u-ca=coptic]')).calendarId, d.withCalendar(Temporal.PlainMonthDay.from({ calendar: 'roc', monthCode: 'M01', day: 1 })).calendarId, d.withCalendar('2020-01-01[u-ca=roc]').calendarId, d.withCalendar('GREGORY').calendarId].join(' '); });
each('withCalendar errors', [function () { return d.withCalendar(); }, function () { return d.withCalendar({}); }, function () { return d.withCalendar('julian'); }, function () { return d.withCalendar(1); }, function () { return d.withCalendar(Temporal.PlainTime.from('12:00')); }]);
show('toZonedDateTime', function () { return [d.toZonedDateTime('Asia/Tokyo').toString(), d.toZonedDateTime({ timeZone: 'America/New_York', plainTime: '12:00' }).toString(), P.from('2024-03-10').toZonedDateTime({ timeZone: 'America/New_York', plainTime: '02:30' }).toString(), d.toZonedDateTime({ timeZone: '+05:30' }).toString(), d.toZonedDateTime({ timeZone: Temporal.ZonedDateTime.from('2020-01-01T00:00[Europe/Rome]') }).toString()].join(' '); });
each('toZonedDateTime errors', [function () { return d.toZonedDateTime({ plainTime: '12:00' }); }, function () { return d.toZonedDateTime('Nowhere/Land'); }, function () { return P.from('-271821-04-19').toZonedDateTime({ timeZone: 'UTC', plainTime: '00:00' }); }, function () { return d.toZonedDateTime(); }]);
show('valueOf', function () { return d < d; });
show('toString calendarName', function () { return ['auto', 'always', 'never', 'critical'].map(function (c) { return d.toString({ calendarName: c }) + '/' + d.withCalendar('gregory').toString({ calendarName: c }); }).join(' '); });
show('toString bad calendarName', function () { return d.toString({ calendarName: 'yes' }); });
show('equals', function () { return [d.equals('2024-01-31'), d.equals({ year: 2024, month: 1, day: 31 }), d.equals(d.withCalendar('gregory')), d.withCalendar('gregory').equals('2024-01-31[u-ca=gregory]'), d.equals(Temporal.PlainDateTime.from('2024-01-31T23:00'))].join(','); });
show('compare across calendars', function () { return [P.compare(d, d.withCalendar('hebrew')), P.compare('2024-01-31', Temporal.PlainDateTime.from('2024-01-31T23:00')), P.compare(Temporal.ZonedDateTime.from('2024-02-01T00:00[UTC]'), d)].join(','); });
show('JSON of iso date', function () { return JSON.stringify({ d: d }); });
"""
    check(js, golden, tier, "plain_date_conversions", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_with_and_arithmetic(js, golden, tier):
    """CATCHES: PlainDate.with that skips field validation (calendar/timeZone keys, empty bags, era pairing, monthCode syntax, overflow) or add/subtract that ignores month-end constraining, time-unit folding or the reject overflow mode fails this."""
    body = r"""var P = Temporal.PlainDate;
var d = P.from('2024-01-31');
show('with', function () { return [d.with({ day: 15 }).toString(), d.with({ month: 2 }).toString(), d.with({ month: 2 }, { overflow: 'constrain' }).toString(), d.with({ monthCode: 'M04' }).toString(), d.with({ year: 2023, month: 2 }).toString(), d.with({ day: 99 }).toString()].join(' '); });
show('with era', function () { var j = d.withCalendar('japanese'); return [j.with({ era: 'heisei', eraYear: 30 }).toString(), d.withCalendar('gregory').with({ era: 'bce', eraYear: 1 }).year, d.withCalendar('roc').with({ year: -5 }).era, d.withCalendar('buddhist').with({ year: 2500 }).toString()].join(' '); });
show('with hebrew leap', function () { var h = P.from('2024-03-15[u-ca=hebrew]'); return [h.with({ monthCode: 'M05L' }).toString(), h.with({ month: 7 }).monthCode, h.with({ year: 5785 }).monthCode, h.with({ day: 30 }).toString()].join(' '); });
each('with errors', [function () { return d.with({ month: 2 }, { overflow: 'reject' }); }, function () { return d.withCalendar('japanese').with({ era: 'showa' }); }, function () { return d.withCalendar('japanese').with({ era: 'showa', eraYear: 1, year: 1926 }); }, function () { return d.with({ calendar: 'hebrew' }); }, function () { return d.with({ timeZone: 'UTC' }); }, function () { return d.with({}); }, function () { return d.with(P.from('2020-01-01')); }, function () { return d.with('2020-01-01'); }, function () { return d.with({ day: 0 }); }, function () { return d.with({ month: -1 }); }, function () { return d.with({ monthCode: 'X01' }); }, function () { return d.with({ monthCode: 5 }); }, function () { return d.with({ month: 3, monthCode: 'M04' }); }, function () { return d.with({ day: Infinity }); }, function () { return d.with({ day: 1 }, { overflow: 'clamp' }); }, function () { return d.with({ day: 1 }, 'reject'); }, function () { return P.from('+275760-09-13').with({ day: 14 }); }]);
show('add', function () { return [d.add({ months: 1 }).toString(), d.add({ months: 1 }, { overflow: 'constrain' }).toString(), d.add('P1Y1M1W1D').toString(), d.add({ hours: 47 }).toString(), d.subtract({ hours: 48 }).toString(), d.subtract({ weeks: 5 }).toString(), d.add({ years: -2024 }).toString(), d.add('-P1M').toString(), d.add({ days: 1e6 }).toString(), P.from('2024-02-29').add({ years: 4 }).toString(), P.from('2024-02-29').subtract({ years: 1 }).toString()].join(' '); });
each('add errors', [function () { return d.add({ months: 1 }, { overflow: 'reject' }); }, function () { return d.add({ month: 1 }); }, function () { return d.add('1 month'); }, function () { return d.add({ days: 1, hours: -1 }); }, function () { return d.add({ days: 1e9 }); }, function () { return d.add(); }, function () { return d.subtract({ years: 1 }, null); }]);
show('add non-iso', function () { return ['gregory', 'japanese', 'roc', 'buddhist', 'persian', 'indian', 'islamic-civil', 'islamic-tbla', 'islamic-umalqura', 'ethiopic', 'coptic'].map(function (c) { var x = d.withCalendar(c); return c + ':' + x.add({ months: 1 }).toString({ calendarName: 'never' }) + '/' + x.add({ years: 1, months: 2, days: 3 }).toString({ calendarName: 'never' }) + '/' + x.subtract({ months: 13 }).toString({ calendarName: 'never' }); }).join(' '); });
"""
    check(js, golden, tier, "plain_date_with_and_arithmetic", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_until_since_options(js, golden, tier):
    """CATCHES: PlainDate until/since that ignores largestUnit/smallestUnit/roundingIncrement/roundingMode, negates rounding modes incorrectly for since, accepts time units or bad increments, or diffs non-ISO calendars wrongly fails this."""
    body = r"""var P = Temporal.PlainDate;
var a = P.from('2020-02-29'), b = P.from('2024-08-15');
show('default', function () { return [a.until(b).toString(), b.until(a).toString(), a.since(b).toString(), a.until('2020-03-01').toString()].join(' '); });
show('largestUnit', function () { return ['years', 'months', 'weeks', 'days', 'auto', 'year', 'month', 'week', 'day'].map(function (u) { return u + '=' + a.until(b, { largestUnit: u }).toString(); }).join(' '); });
show('smallestUnit', function () { return ['years', 'months', 'weeks', 'days'].map(function (u) { return u + '=' + a.until(b, { smallestUnit: u }).toString() + '/' + a.until(b, { smallestUnit: u, roundingMode: 'halfExpand' }).toString(); }).join(' '); });
show('modes', function () { return ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(function (m) { return m + '=' + a.until(b, { smallestUnit: 'months', roundingMode: m }).toString() + '/' + b.until(a, { smallestUnit: 'months', roundingMode: m }).toString() + '/' + b.since(a, { smallestUnit: 'years', roundingMode: m }).toString(); }).join(' '); });
show('half modes on a tie', function () { var x = P.from('2024-01-01'), y = P.from('2024-01-16'); return ['halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(function (m) { return m + '=' + x.until(y, { smallestUnit: 'days', roundingIncrement: 10, roundingMode: m }).toString() + '/' + y.until(x, { smallestUnit: 'days', roundingIncrement: 10, roundingMode: m }).toString(); }).join(' '); });
show('increments', function () { return [a.until(b, { smallestUnit: 'months', roundingIncrement: 5 }).toString(), a.until(b, { smallestUnit: 'days', roundingIncrement: 10, largestUnit: 'months' }).toString(), a.until(b, { smallestUnit: 'weeks', roundingIncrement: 3, roundingMode: 'ceil' }).toString(), a.until(b, { smallestUnit: 'years', roundingIncrement: 4, roundingMode: 'halfEven' }).toString(), a.until(b, { smallestUnit: 'days', roundingIncrement: 2 }).toString()].join(' '); });
show('since rounding', function () { return [b.since(a, { smallestUnit: 'months', roundingMode: 'floor' }).toString(), a.since(b, { smallestUnit: 'months', roundingMode: 'floor' }).toString(), b.since(a, { largestUnit: 'weeks', smallestUnit: 'weeks', roundingMode: 'halfExpand' }).toString()].join(' '); });
each('errors', [function () { return a.until(b, { largestUnit: 'hours' }); }, function () { return a.until(b, { smallestUnit: 'hour' }); }, function () { return a.until(b, { largestUnit: 'decades' }); }, function () { return a.until(b, { largestUnit: 'months', smallestUnit: 'years' }); }, function () { return a.until(b, { roundingMode: 'nearest' }); }, function () { return a.until(b.withCalendar('hebrew')); }, function () { return a.until(b, 'years'); }, function () { return a.until('2024-13-01'); }]);
show('increment range', function () { return [0, 1e9 + 1, NaN, -1, 1.9, 1e9].map(function (n) { try { return a.until(b, { smallestUnit: 'days', roundingIncrement: n }).toString(); } catch (e) { return e.name + ':' + e.message; } }).join(' | '); });
show('non-iso', function () { var h1 = a.withCalendar('hebrew'), h2 = b.withCalendar('hebrew'); return [h1.until(h2, { largestUnit: 'years' }).toString(), h1.until(h2, { largestUnit: 'months', smallestUnit: 'months', roundingMode: 'halfExpand' }).toString(), a.withCalendar('chinese').until(b.withCalendar('chinese'), { largestUnit: 'years', smallestUnit: 'days' }).toString(), a.withCalendar('islamic-civil').until(b.withCalendar('islamic-civil'), { largestUnit: 'years' }).toString(), b.withCalendar('persian').since(a.withCalendar('persian'), { largestUnit: 'months' }).toString(), a.withCalendar('japanese').until(b.withCalendar('japanese'), { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'ceil' }).toString()].join(' '); });
show('same', function () { return a.until(a, { largestUnit: 'years' }).toString() + ' ' + a.until(a).blank; });
"""
    check(js, golden, tier, "plain_date_until_since_options", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_time_fields_strings_and_with(js, golden, tier):
    """CATCHES: PlainTime construction/range checks, toString precision and rounding options, with() validation and overflow, or from() conversions of bags, PlainDateTime/ZonedDateTime and Z-suffixed strings that behave incorrectly fail this."""
    body = r"""var T = Temporal.PlainTime;
var t = new T(13, 45, 30, 123, 456, 789);
show('getters', function () { return [t.hour, t.minute, t.second, t.millisecond, t.microsecond, t.nanosecond, t.toString(), t.toJSON(), String(new T())].join(','); });
show('ctor range', function () { return [[24], [0, 60], [0, 0, 60], [0, 0, 0, 1000], [0, 0, 0, 0, 1000], [0, 0, 0, 0, 0, 1000], [-1], [1.9, 2.9]].map(function (a) { try { return Reflect.construct(T, a).toString(); } catch (e) { return e.name + ':' + e.message; } }).join(' | '); });
show('toString opts', function () { return [t.toString({ smallestUnit: 'minute' }), t.toString({ smallestUnit: 'second' }), t.toString({ smallestUnit: 'millisecond' }), t.toString({ smallestUnit: 'microsecond' }), t.toString({ smallestUnit: 'nanosecond' }), t.toString({ fractionalSecondDigits: 1 }), t.toString({ fractionalSecondDigits: 5, roundingMode: 'halfExpand' }), t.toString({ fractionalSecondDigits: 'auto' }), new T(23, 59, 59, 999, 999, 999).toString({ smallestUnit: 'second', roundingMode: 'ceil' }), new T(12).toString({ fractionalSecondDigits: 2 }), t.toString({ smallestUnit: 'minute', fractionalSecondDigits: 9 })].join(' '); });
each('toString errors', [function () { return t.toString({ fractionalSecondDigits: -1 }); }, function () { return t.toString({ fractionalSecondDigits: 'two' }); }, function () { return t.toString({ smallestUnit: 'hour' }); }, function () { return t.toString({ roundingMode: 'sideways' }); }, function () { return t.toString(null); }]);
show('with', function () { return [t.with({ hour: 1 }).toString(), t.with({ second: 61 }).toString(), t.with({ millisecond: 0, microsecond: 0, nanosecond: 0 }).toString(), t.with({ minute: 0 }, { overflow: 'reject' }).toString()].join(' '); });
each('with errors', [function () { return t.with({ minute: 60 }, { overflow: 'reject' }); }, function () { return t.with({ year: 2020 }); }, function () { return t.with({ calendar: 'iso8601', hour: 1 }); }, function () { return t.with({ timeZone: 'UTC', hour: 1 }); }, function () { return t.with(new T(1)); }, function () { return t.with('12:00'); }, function () { return t.with({ hour: -1 }); }]);
show('from bag', function () { return [T.from({ hour: 1, minute: 2, second: 3, millisecond: 4, microsecond: 5, nanosecond: 6 }).toString(), T.from({ minute: 70 }).toString(), T.from(Temporal.PlainDateTime.from('2020-01-01T05:06:07')).toString(), T.from(Temporal.ZonedDateTime.from('2020-01-01T05:06:07+09:00[Asia/Tokyo]')).toString(), T.from(t) === t, T.from(t).equals(t)].join(' '); });
each('from errors', [function () { return T.from(5); }, function () { return T.from(Temporal.PlainDate.from('2020-01-01')); }, function () { return T.from('2020-01-01T10:00Z'); }, function () { return T.from('12:00', { overflow: 'nope' }); }, function () { return T.from({ hour: 24 }, { overflow: 'reject' }); }, function () { return T.from(null); }]);
show('equals/compare', function () { return [t.equals('13:45:30.123456789'), t.equals({ hour: 13, minute: 45, second: 30 }), T.compare('08:00', '17:00'), T.compare('17:00', '08:00'), T.compare('00:00', { hour: 0 })].join(','); });
show('valueOf', function () { return t > t; });
"""
    check(js, golden, tier, "plain_time_fields_strings_and_with", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_time_arithmetic_difference_and_round(js, golden, tier):
    """CATCHES: PlainTime add/subtract that does not wrap past midnight or ignores days, until/since that mis-balances to the requested largestUnit or mis-rounds with increments, or round() with wrong increment validation or rounding modes fails this."""
    body = r"""var T = Temporal.PlainTime;
var t = new T(13, 45, 30, 123, 456, 789);
show('add/subtract', function () { return [t.add({ hours: 12 }).toString(), t.add({ minutes: -46 }).toString(), t.subtract('PT14H').toString(), t.add({ days: 3, hours: 1 }).toString(), t.add({ years: 1 }).toString(), t.subtract({ nanoseconds: 1e12 }).toString(), t.add('PT0.000000001S').toString()].join(' '); });
var a = T.from('08:15:30.5'), b = T.from('17:45:10.25');
show('until', function () { return [a.until(b).toString(), b.until(a).toString(), a.until(b, { largestUnit: 'minute' }).toString(), a.until(b, { largestUnit: 'second' }).toString(), a.until(b, { largestUnit: 'millisecond' }).toString(), a.until(b, { largestUnit: 'microseconds' }).toString(), a.until(b, { largestUnit: 'nanosecond' }).toString()].join(' '); });
show('until rounding', function () { return [a.until(b, { smallestUnit: 'minute' }).toString(), a.until(b, { smallestUnit: 'minute', roundingMode: 'halfExpand' }).toString(), a.until(b, { smallestUnit: 'hour', roundingMode: 'ceil' }).toString(), a.until(b, { smallestUnit: 'second', roundingIncrement: 15 }).toString(), b.since(a, { smallestUnit: 'minute', roundingIncrement: 30, roundingMode: 'halfEven' }).toString(), a.since(b, { smallestUnit: 'minute', roundingMode: 'floor' }).toString(), a.until(b, { smallestUnit: 'millisecond', roundingIncrement: 100, largestUnit: 'second' }).toString()].join(' '); });
each('until errors', [function () { return a.until(b, { largestUnit: 'day' }); }, function () { return a.until(b, { smallestUnit: 'minute', roundingIncrement: 7 }); }, function () { return a.until(b, { smallestUnit: 'hour', roundingIncrement: 24 }); }, function () { return a.until(b, { largestUnit: 'second', smallestUnit: 'minute' }); }]);
show('round', function () { return [t.round('hour').toString(), t.round('minute').toString(), t.round({ smallestUnit: 'second', roundingMode: 'floor' }).toString(), t.round({ smallestUnit: 'millisecond', roundingIncrement: 250 }).toString(), t.round({ smallestUnit: 'microsecond', roundingIncrement: 500, roundingMode: 'trunc' }).toString(), t.round({ smallestUnit: 'nanosecond', roundingIncrement: 100, roundingMode: 'halfCeil' }).toString(), T.from('23:30').round('hour').toString(), T.from('11:30').round({ smallestUnit: 'hour', roundingMode: 'halfFloor' }).toString(), T.from('11:30').round({ smallestUnit: 'hour', roundingMode: 'halfTrunc' }).toString(), T.from('11:30').round({ smallestUnit: 'hour', roundingMode: 'halfEven' }).toString(), T.from('12:30').round({ smallestUnit: 'hour', roundingMode: 'halfEven' }).toString(), T.from('12:00:01').round({ smallestUnit: 'hour', roundingMode: 'expand' }).toString(), T.from('20:00').round({ smallestUnit: 'hour', roundingIncrement: 12 }).toString()].join(' '); });
each('round errors', [function () { return t.round(); }, function () { return t.round({ roundingMode: 'ceil' }); }, function () { return t.round(5); }, function () { return t.round({ smallestUnit: 'hour', roundingIncrement: 5 }); }, function () { return t.round({ smallestUnit: 'second', roundingIncrement: 60 }); }]);
"""
    check(js, golden, tier, "plain_time_arithmetic_difference_and_round", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_time_fields_with_and_conversions(js, golden, tier):
    """CATCHES: PlainDateTime getters, with/withPlainTime/withCalendar, toPlainDate/toPlainTime, toZonedDateTime disambiguation in gaps and overlaps, add/subtract overflow, or property-bag from() handling that deviates from Temporal fails this."""
    body = r"""var DT = Temporal.PlainDateTime;
var x = new DT(2024, 2, 29, 13, 45, 30, 123, 456, 789);
show('getters', function () { return [x.year, x.month, x.monthCode, x.day, x.hour, x.minute, x.second, x.millisecond, x.microsecond, x.nanosecond, x.dayOfWeek, x.dayOfYear, x.weekOfYear, x.yearOfWeek, x.daysInWeek, x.daysInMonth, x.daysInYear, x.monthsInYear, x.inLeapYear, x.era, x.eraYear, x.calendarId].join(','); });
show('getters japanese', function () { var j = x.withCalendar('japanese'); return [j.era, j.eraYear, j.year, j.month, j.monthCode, j.day, j.weekOfYear, j.yearOfWeek, j.daysInMonth, j.inLeapYear, j.toString()].join(','); });
show('getters chinese', function () { var c = x.withCalendar('chinese'); return [c.era, c.eraYear, c.year, c.month, c.monthCode, c.day, c.daysInMonth, c.daysInYear, c.monthsInYear, c.inLeapYear].join(','); });
show('ctor', function () { return [new DT(2024, 1, 1).toString(), new DT(2024, 1, 1, 0, 0, 0, 0, 0, 0, 'hebrew').toString()].join(' '); });
each('ctor errors', [function () { return new DT(2024, 13, 1); }, function () { return new DT(2024, 1, 1, 24); }, function () { return new DT(-271821, 4, 19); }, function () { return DT(2024, 1, 1); }]);
show('with', function () { return [x.with({ hour: 0, day: 1 }).toString(), x.with({ year: 2023 }).toString(), x.with({ monthCode: 'M12', nanosecond: 0 }).toString(), x.with({ minute: 99 }).toString(), x.withCalendar('hebrew').with({ monthCode: 'M05L', day: 1 }).toString()].join(' '); });
each('with errors', [function () { return x.with({ year: 2023 }, { overflow: 'reject' }); }, function () { return x.with({ foo: 1 }); }, function () { return x.with({ calendar: 'iso8601' }); }, function () { return x.with(x); }, function () { return x.with({ hour: 25 }, { overflow: 'reject' }); }]);
show('withPlainTime', function () { return [x.withPlainTime().toString(), x.withPlainTime('07:08').toString(), x.withPlainTime({ hour: 9 }).toString(), x.withPlainTime(Temporal.PlainDateTime.from('2000-01-01T05:06')).toString()].join(' '); });
show('withCalendar', function () { return [x.withCalendar('persian').toString(), x.withCalendar('persian').month, x.withCalendar(Temporal.PlainYearMonth.from('2020-01')).calendarId].join(' '); });
each('withCalendar errors', [function () { return x.withCalendar(); }, function () { return x.withCalendar({}); }, function () { return x.withCalendar('lunar'); }]);
show('toPlain', function () { return [x.toPlainDate().toString(), x.toPlainTime().toString(), x.withCalendar('roc').toPlainDate().toString()].join(' '); });
show('toZonedDateTime', function () { return [x.toZonedDateTime('Europe/Berlin').toString(), DT.from('2024-03-31T02:30').toZonedDateTime('Europe/Berlin').toString(), DT.from('2024-03-31T02:30').toZonedDateTime('Europe/Berlin', { disambiguation: 'earlier' }).toString(), DT.from('2024-10-27T02:30').toZonedDateTime('Europe/Berlin', { disambiguation: 'later' }).toString(), DT.from('2024-10-27T02:30').toZonedDateTime('Europe/Berlin').toString()].join(' '); });
each('toZonedDateTime errors', [function () { return DT.from('2024-03-31T02:30').toZonedDateTime('Europe/Berlin', { disambiguation: 'reject' }); }, function () { return DT.from('2024-10-27T02:30').toZonedDateTime('Europe/Berlin', { disambiguation: 'reject' }); }, function () { return x.toZonedDateTime(); }, function () { return x.toZonedDateTime('UTC', { disambiguation: 'first' }); }]);
show('add/subtract', function () { return [x.add({ hours: 11, minutes: 15 }).toString(), x.add({ years: 1 }).toString(), x.subtract({ months: 1, nanoseconds: 789 }).toString(), x.add('PT100000H').toString(), x.subtract({ weeks: 1, days: 1, microseconds: 456 }).toString()].join(' '); });
each('add errors', [function () { return x.add({ years: 1 }, { overflow: 'reject' }); }, function () { return DT.from('+275760-09-13T00:00').add({ days: 1 }); }, function () { return x.add({ hours: 1, minutes: -1 }); }]);
show('from', function () { return [DT.from({ year: 2020, month: 2, day: 30, hour: 25 }).toString(), DT.from('2020-01-01T10:00:00+05:00[Asia/Tokyo]').toString(), DT.from(Temporal.PlainDate.from('2020-05-05')).toString(), DT.from(Temporal.ZonedDateTime.from('2020-05-05T10:00[Asia/Tokyo]')).toString(), DT.from({ year: 2020, month: 1, day: 1, calendar: 'japanese' }).toString(), DT.from({ era: 'showa', eraYear: 64, month: 1, day: 7, hour: 12, calendar: 'japanese' }).toString()].join(' '); });
each('from errors', [function () { return DT.from({ year: 2020, month: 2, day: 30 }, { overflow: 'reject' }); }, function () { return DT.from({ year: 2020, month: 1 }); }, function () { return DT.from('2020-01-01T10:00Z'); }, function () { return DT.from(42); }]);
show('equals/compare', function () { return [x.equals('2024-02-29T13:45:30.123456789'), x.equals(x.withCalendar('gregory')), DT.compare('2020-01-15T08:00', '2024-03-10T06:30'), DT.compare(x, x.withCalendar('hebrew')), DT.compare('2020-01-01', { year: 2020, month: 1, day: 1 })].join(','); });
show('valueOf', function () { return +x; });
"""
    check(js, golden, tier, "plain_date_time_fields_with_and_conversions", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_date_time_difference_round_and_to_string(js, golden, tier):
    """CATCHES: PlainDateTime until/since that mis-balances date and time parts per largestUnit, mis-rounds with smallestUnit/increment/mode, round() that carries into the next day wrongly or accepts calendar units, or toString rounding options fail this."""
    body = r"""var DT = Temporal.PlainDateTime;
var x = new DT(2024, 2, 29, 13, 45, 30, 123, 456, 789);
var a = DT.from('2020-01-15T08:00'), b = DT.from('2024-03-10T06:30:15.5');
show('until', function () { return ['auto', 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds', 'nanoseconds'].map(function (u) { return u + '=' + a.until(b, { largestUnit: u }).toString(); }).join(' '); });
show('since', function () { return ['auto', 'years', 'months', 'weeks', 'days', 'hours'].map(function (u) { return u + '=' + a.since(b, { largestUnit: u }).toString(); }).join(' '); });
show('until rounding', function () { return [a.until(b, { smallestUnit: 'hour' }).toString(), a.until(b, { largestUnit: 'years', smallestUnit: 'day', roundingMode: 'halfExpand' }).toString(), a.until(b, { largestUnit: 'months', smallestUnit: 'week' }).toString(), a.until(b, { smallestUnit: 'minutes', roundingIncrement: 30, roundingMode: 'ceil' }).toString(), b.since(a, { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'halfEven' }).toString(), a.since(b, { largestUnit: 'years', smallestUnit: 'seconds', roundingMode: 'floor' }).toString(), a.until(b, { largestUnit: 'years', smallestUnit: 'years', roundingIncrement: 3, roundingMode: 'ceil' }).toString(), a.until(b, { smallestUnit: 'days', roundingIncrement: 2 }).toString(), b.until(a, { largestUnit: 'hours', smallestUnit: 'hours', roundingIncrement: 6, roundingMode: 'halfFloor' }).toString()].join(' '); });
show('time-only differences', function () { var p = DT.from('2024-01-01T23:00'), q = DT.from('2024-01-02T01:30'); return [p.until(q).toString(), q.since(p, { largestUnit: 'years' }).toString(), p.until(q, { largestUnit: 'months', smallestUnit: 'days', roundingMode: 'halfExpand' }).toString(), q.until(p, { largestUnit: 'days', smallestUnit: 'days', roundingMode: 'floor' }).toString()].join(' '); });
each('until errors', [function () { return a.until(b, { smallestUnit: 'hours', roundingIncrement: 5 }); }, function () { return a.until(b.withCalendar('gregory')); }, function () { return a.until(b, { largestUnit: 'minutes', smallestUnit: 'hours' }); }, function () { return a.until(b, { smallestUnit: 'fortnights' }); }]);
show('non-iso until', function () { var h1 = a.withCalendar('hebrew'), h2 = b.withCalendar('hebrew'); return [h1.until(h2, { largestUnit: 'years' }).toString(), h2.since(h1, { largestUnit: 'months', smallestUnit: 'months' }).toString(), a.withCalendar('coptic').until(b.withCalendar('coptic'), { largestUnit: 'years', smallestUnit: 'hours' }).toString()].join(' '); });
show('round', function () { return [x.round('day').toString(), x.round({ smallestUnit: 'hour', roundingIncrement: 6 }).toString(), x.round({ smallestUnit: 'minute', roundingMode: 'floor' }).toString(), DT.from('2024-12-31T23:59:59.999').round('second').toString(), x.round({ smallestUnit: 'day', roundingMode: 'trunc' }).toString(), x.round({ smallestUnit: 'microsecond', roundingIncrement: 250 }).toString(), x.round({ smallestUnit: 'nanosecond', roundingIncrement: 500 }).toString(), x.round({ smallestUnit: 'millisecond', roundingIncrement: 500, roundingMode: 'ceil' }).toString()].join(' '); });
each('round errors', [function () { return x.round({ smallestUnit: 'month' }); }, function () { return x.round({ smallestUnit: 'day', roundingIncrement: 2 }); }, function () { return DT.from('+275760-09-13T23:59').round('day'); }, function () { return x.round(); }, function () { return x.round({}); }]);
show('toString', function () { return [x.toString({ smallestUnit: 'minute', calendarName: 'always' }), x.toString({ fractionalSecondDigits: 0 }), x.toString({ roundingMode: 'expand', fractionalSecondDigits: 2 }), DT.from('2024-12-31T23:59:59.999').toString({ smallestUnit: 'second', roundingMode: 'ceil' }), x.toJSON()].join(' '); });
each('toString errors', [function () { return x.toString({ smallestUnit: 'hour' }); }, function () { return DT.from('+275760-09-13T23:59:59.9').toString({ smallestUnit: 'second', roundingMode: 'ceil' }); }, function () { return x.toString({ fractionalSecondDigits: 9.5 }); }]);
"""
    check(js, golden, tier, "plain_date_time_difference_round_and_to_string", body)


@pytest.mark.parametrize("tier", TIERS)
def test_zoned_getters_conversions_and_start_of_day(js, golden, tier):
    """CATCHES: ZonedDateTime getters computed in UTC instead of local time, wrong offset/offsetNanoseconds/hoursInDay on DST days, startOfDay that ignores midnight gaps, broken toInstant/toPlain* conversions, or equals() that ignores zone/calendar fails this."""
    body = r"""var Z = Temporal.ZonedDateTime;
var z = new Z(1709214330123456789n, 'Australia/Sydney');
show('getters', function () { return [z.year, z.month, z.monthCode, z.day, z.hour, z.minute, z.second, z.millisecond, z.microsecond, z.nanosecond, z.dayOfWeek, z.dayOfYear, z.weekOfYear, z.yearOfWeek, z.daysInWeek, z.daysInMonth, z.daysInYear, z.monthsInYear, z.inLeapYear, z.era, z.eraYear, z.calendarId, z.hoursInDay, z.epochMilliseconds, z.epochNanoseconds, z.offsetNanoseconds, z.offset, z.timeZoneId].join(','); });
show('getters hebrew', function () { var h = z.withCalendar('hebrew'); return [h.year, h.month, h.monthCode, h.day, h.era, h.eraYear, h.weekOfYear, h.yearOfWeek, h.daysInMonth, h.daysInYear, h.monthsInYear, h.inLeapYear, h.calendarId].join(','); });
show('getters japanese', function () { var j = z.withCalendar('japanese'); return [j.era, j.eraYear, j.year, j.toString()].join(','); });
show('conversions', function () { return [z.toInstant().toString(), z.toPlainDate().toString(), z.toPlainTime().toString(), z.toPlainDateTime().toString(), z.withCalendar('buddhist').toPlainDate().toString(), z.withCalendar('buddhist').toPlainDateTime().toString(), z.toJSON()].join(' '); });
show('startOfDay', function () { return [z.startOfDay().toString(), Z.from('2024-10-06T12:00[Australia/Sydney]').startOfDay().toString(), Z.from('2024-03-31T12:00[Asia/Beirut]').startOfDay().toString(), Z.from('2024-10-06T12:00[Australia/Sydney]').hoursInDay, Z.from('2024-04-07T12:00[Australia/Sydney]').hoursInDay, Z.from('2024-03-31T12:00[Asia/Beirut]').hoursInDay, Z.from('2024-06-01T12:00[+03:00]').hoursInDay].join(' '); });
show('equals', function () { return [z.equals(z.toString()), z.equals(new Z(z.epochNanoseconds, 'Australia/Melbourne')), z.equals(z.withCalendar('gregory')), z.equals({ year: 2024, month: 3, day: 1, hour: 0, minute: 45, second: 30, millisecond: 123, microsecond: 456, nanosecond: 789, timeZone: 'Australia/Sydney' }), new Z(0n, '+01:00').equals(new Z(0n, '+01:00'))].join(','); });
show('valueOf', function () { return z > 0; });
show('add', function () { return [z.add({ hours: 1 }).toString(), z.add({ months: 1 }).toString(), z.add({ years: 1 }).toString(), z.subtract({ days: 1, nanoseconds: 1 }).toString(), Z.from('2024-01-31T12:00[UTC]').add({ months: 1 }).toString(), Z.from('2024-10-05T02:30[Australia/Sydney]').add({ days: 1 }).toString(), Z.from('2024-10-05T02:30[Australia/Sydney]').add({ hours: 24 }).toString()].join(' '); });
each('add errors', [function () { return Z.from('2024-01-31T12:00[UTC]').add({ months: 1 }, { overflow: 'reject' }); }, function () { return Z.from('+275760-09-13T00:00[UTC]').add({ days: 1 }); }, function () { return Z.from('-271821-04-20T00:00[UTC]').subtract({ nanoseconds: 1 }); }, function () { return z.add({ hours: 1 }, { overflow: 'nope' }); }]);
show('ctor', function () { return [new Z(0n, 'UTC', 'ethiopic').toString(), new Z(0n, 'utc', 'ISO8601').toString(), new Z(-1n, 'America/Los_Angeles').toString()].join(' '); });
each('ctor errors', [function () { return new Z(0n); }, function () { return new Z(0, 'UTC'); }, function () { return new Z(0n, 'UTC', 'mayan'); }, function () { return new Z(8640000000000000000001n, 'UTC'); }, function () { return Z(0n, 'UTC'); }, function () { return new Z(0n, {}); }]);
"""
    check(js, golden, tier, "zoned_getters_conversions_and_start_of_day", body)


@pytest.mark.parametrize("tier", TIERS)
def test_zoned_with_time_zone_calendar_and_transitions(js, golden, tier):
    """CATCHES: ZonedDateTime.with that mishandles offset/disambiguation options in DST gaps and overlaps, withTimeZone/withCalendar/withPlainTime that change the wrong component, or getTimeZoneTransition that misses rule changes, LMT transitions, or fixed-offset nulls fails this."""
    body = r"""var Z = Temporal.ZonedDateTime;
var z = Z.from('2024-07-15T10:20:30.5+02:00[Europe/Paris]');
show('with', function () { return [z.with({ hour: 23, minute: 0 }).toString(), z.with({ year: 2023, month: 2, day: 31 }).toString(), z.with({ monthCode: 'M03', day: 31, hour: 2, minute: 30 }).toString(), z.with({ month: 10, day: 27, hour: 2, minute: 30 }).toString(), z.with({ month: 10, day: 27, hour: 2, minute: 30 }, { disambiguation: 'later' }).toString(), z.with({ month: 10, day: 27, hour: 2, minute: 30, offset: '+01:00' }).toString(), z.with({ nanosecond: 7, millisecond: 1, microsecond: 2, second: 3 }).toString()].join(' '); });
show('with offset modes', function () { return [z.with({ month: 1 }).toString(), z.with({ month: 1 }, { offset: 'use' }).toString(), z.with({ month: 1 }, { offset: 'ignore' }).toString(), z.with({ month: 1 }, { offset: 'prefer' }).toString()].join(' '); });
each('with errors', [function () { return z.with({ month: 1 }, { offset: 'reject' }); }, function () { return z.with({ month: 3, day: 31, hour: 2, minute: 30 }, { disambiguation: 'reject' }); }, function () { return z.with({ month: 2, day: 30 }, { overflow: 'reject' }); }, function () { return z.with('x'); }, function () { return z.with({}); }, function () { return z.with({ timeZone: 'UTC' }); }, function () { return z.with({ calendar: 'iso8601' }); }, function () { return z.with(z); }, function () { return z.with({ offset: 'bogus' }); }, function () { return z.with({ hour: 1 }, { offset: 'bad' }); }, function () { return z.with({ era: 'ce' }); }]);
show('with japanese era', function () { var j = z.withCalendar('japanese'); return j.with({ era: 'heisei', eraYear: 2 }).toString() + ' ' + j.with({ eraYear: 2, era: 'showa', month: 5 }).toPlainDate().toString(); });
show('withTimeZone', function () { return [z.withTimeZone('Asia/Kathmandu').toString(), z.withTimeZone('-03:30').toString(), z.withTimeZone(Z.from('2020-01-01T00:00[America/Sao_Paulo]')).timeZoneId, z.withTimeZone('Asia/Calcutta').timeZoneId].join(' '); });
each('withTimeZone errors', [function () { return z.withTimeZone(); }, function () { return z.withTimeZone(42); }, function () { return z.withTimeZone('Europe/Atlantis'); }]);
show('withCalendar', function () { return [z.withCalendar('islamic-umalqura').toString(), z.withCalendar(Temporal.PlainDate.from('2020-01-01[u-ca=indian]')).calendarId, z.withCalendar('dangi').withCalendar('iso8601').toString()].join(' '); });
each('withCalendar errors', [function () { return z.withCalendar(); }, function () { return z.withCalendar({}); }, function () { return z.withCalendar('xx'); }]);
show('transitions', function () { var t = Z.from('2024-01-01T00:00[America/Sao_Paulo]'); return [t.getTimeZoneTransition('previous').toString(), t.getTimeZoneTransition('next'), Z.from('1950-01-01T00:00[Europe/Paris]').getTimeZoneTransition('next').toString(), Z.from('2024-03-31T02:00:00+01:00[Europe/London]').getTimeZoneTransition('previous').toString(), Z.from('2024-03-31T02:00:00+01:00[Europe/London]').getTimeZoneTransition('next').toString(), Z.from('2024-01-01T00:00[+05:00]').getTimeZoneTransition('previous'), Z.from('1800-01-01T00:00[America/New_York]').getTimeZoneTransition('next').toString(), Z.from('1800-01-01T00:00[America/New_York]').getTimeZoneTransition('previous'), Z.from('2024-06-01T00:00[Australia/Lord_Howe]').getTimeZoneTransition({ direction: 'next' }).toString()].join(' '); });
each('transition errors', [function () { return z.getTimeZoneTransition({}); }, function () { return z.getTimeZoneTransition(5); }, function () { return z.getTimeZoneTransition({ direction: 'up' }); }, function () { return z.getTimeZoneTransition('NEXT'); }]);
show('withPlainTime', function () { return [z.withPlainTime().toString(), z.withPlainTime('12:00').toString(), Z.from('2024-03-31T12:00[Europe/Paris]').withPlainTime('02:30').toString(), Z.from('2024-09-08T12:00[America/Santiago]').withPlainTime().toString(), z.withPlainTime({ hour: 6, minute: 7 }).toString()].join(' '); });
each('withPlainTime errors', [function () { return z.withPlainTime('24:01'); }, function () { return z.withPlainTime({}); }]);
"""
    check(js, golden, tier, "zoned_with_time_zone_calendar_and_transitions", body)


@pytest.mark.parametrize("tier", TIERS)
def test_zoned_until_since_round_from_and_compare(js, golden, tier):
    """CATCHES: ZonedDateTime until/since that does not use wall-clock days for date units, mis-rounds with increments or modes, accepts mismatched calendars, round() to days on 23/25-hour days, or from()/compare() that resolve bags, annotations and options wrongly fails this."""
    body = r"""var Z = Temporal.ZonedDateTime;
var a = Z.from('2024-01-15T09:00[America/New_York]'), b = Z.from('2025-04-02T17:45:30.25[America/New_York]');
show('until', function () { return ['auto', 'years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds', 'microseconds', 'nanoseconds'].map(function (u) { return u + '=' + a.until(b, { largestUnit: u }).toString(); }).join(' '); });
show('since', function () { return [b.since(a).toString(), a.since(b, { largestUnit: 'years' }).toString(), b.since(a, { largestUnit: 'months', smallestUnit: 'days', roundingMode: 'ceil' }).toString(), b.since(a, { smallestUnit: 'hours', roundingIncrement: 6, roundingMode: 'halfExpand' }).toString(), a.until(b, { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'halfExpand' }).toString(), a.until(b, { largestUnit: 'years', smallestUnit: 'weeks' }).toString(), a.until(b, { largestUnit: 'years', smallestUnit: 'years', roundingIncrement: 2, roundingMode: 'expand' }).toString(), a.until(b, { smallestUnit: 'minute', roundingIncrement: 15 }).toString(), a.until(b, { largestUnit: 'days', smallestUnit: 'days', roundingMode: 'halfEven' }).toString(), b.until(a, { largestUnit: 'weeks', smallestUnit: 'days', roundingMode: 'halfTrunc' }).toString()].join(' '); });
show('until other zone', function () { return a.until(b.withTimeZone('Europe/Paris'), { largestUnit: 'hours' }).toString() + ' ' + a.until(a.withTimeZone('Asia/Tokyo'), { largestUnit: 'minutes' }).toString(); });
show('until same day', function () { var p = Z.from('2024-03-10T00:30[America/New_York]'); return [p.until(p.with({ hour: 5 }), { largestUnit: 'days' }).toString(), p.until(p.add({ days: 1 }), { largestUnit: 'days' }).toString(), p.until(p.add({ hours: 23 }), { largestUnit: 'days' }).toString()].join(' '); });
each('until errors', [function () { return a.until(b.withCalendar('gregory'), { largestUnit: 'hours' }); }, function () { return a.until(b.withCalendar('gregory')); }, function () { return a.until(b, { largestUnit: 'weeks', smallestUnit: 'months' }); }, function () { return a.until(b, { smallestUnit: 'seconds', roundingIncrement: 7 }); }, function () { return a.until(b, { roundingMode: 'round' }); }, function () { return a.until(b, { largestUnit: 'fortnight' }); }, function () { return a.until(b.withTimeZone('Europe/Paris'), { largestUnit: 'days' }); }]);
show('until zoned non-iso', function () { var h1 = a.withCalendar('hebrew'), h2 = b.withCalendar('hebrew'); return h1.until(h2, { largestUnit: 'years' }).toString() + ' ' + h2.since(h1, { largestUnit: 'months', smallestUnit: 'months' }).toString(); });
show('round', function () { var z = Z.from('2024-03-10T01:47:31.5[America/New_York]'); return [z.round('hour').toString(), z.round({ smallestUnit: 'minute', roundingIncrement: 15, roundingMode: 'ceil' }).toString(), z.round({ smallestUnit: 'second', roundingMode: 'floor' }).toString(), z.round({ smallestUnit: 'millisecond' }).toString(), z.round({ smallestUnit: 'microsecond' }).toString(), z.round({ smallestUnit: 'nanosecond' }).toString(), z.round({ smallestUnit: 'day', roundingMode: 'ceil' }).toString(), z.round({ smallestUnit: 'day', roundingMode: 'floor' }).toString(), z.round({ smallestUnit: 'day', roundingMode: 'halfExpand' }).toString(), Z.from('2024-11-03T11:20[America/New_York]').round('day').toString(), Z.from('2024-11-03T12:40[America/New_York]').round('day').toString()].join(' '); });
each('round errors', [function () { return Z.from('2024-03-10T01:47[UTC]').round(); }, function () { return a.round('month'); }, function () { return a.round({ smallestUnit: 'day', roundingIncrement: 2 }); }, function () { return a.round({ smallestUnit: 'hour', roundingIncrement: 5 }); }, function () { return a.round({}); }, function () { return a.round(7); }]);
show('compare', function () { return [Z.compare(a, b), Z.compare(b, a), Z.compare(a, a.withTimeZone('Asia/Tokyo')), Z.compare('2024-01-01T00:00[UTC]', { year: 2024, month: 1, day: 1, timeZone: 'Europe/London' }), Z.compare(a, a.withCalendar('hebrew'))].join(','); });
show('from', function () { return [Z.from({ year: 2024, month: 3, day: 10, hour: 2, minute: 30, timeZone: 'America/New_York' }).toString(), Z.from({ year: 2024, month: 3, day: 10, hour: 2, minute: 30, timeZone: 'America/New_York' }, { disambiguation: 'earlier' }).toString(), Z.from({ year: 5784, monthCode: 'M05L', day: 30, timeZone: 'Asia/Jerusalem', calendar: 'hebrew' }).toString(), Z.from('2024-05-01T00:00Z[Asia/Tokyo]').toString(), Z.from('2024-05-01[Asia/Tokyo]').toString(), Z.from('2024-05-01T12:00+09:00[!Asia/Tokyo][u-ca=japanese]').toString(), Z.from('2024-05-01T12:00+09:00[Asia/Tokyo][foo=bar]').toString(), Z.from(a) === a, Z.from({ year: 2024, month: 5, day: 1, timeZone: Z.from('2020-01-01T00:00[Africa/Lagos]') }).toString()].join(' '); });
each('from errors', [function () { return Z.from(5); }, function () { return Z.from('2024-05-01T00:00Z'); }, function () { return Z.from('2024-05-01T00:00+09:00'); }, function () { return Z.from({ year: 2024, month: 1, day: 1 }); }, function () { return Z.from({ year: 2024, month: 1, day: 1, timeZone: 5 }); }, function () { return Z.from({ year: 2024, month: 1, timeZone: 'UTC' }); }, function () { return Z.from('2024-05-01T00:00[Asia/Tokyo][u-ca=bogus]'); }, function () { return Z.from('2024-05-01T00:00[Asia/Tokyo][!x-foo=bar]'); }, function () { return Z.from('2024-05-01T00:00[Asia/Tokyo][Europe/Paris]'); }, function () { return Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC' }, { overflow: 'x' }); }, function () { return Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC' }, { disambiguation: 'x' }); }, function () { return Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC' }, { offset: 'x' }); }]);
"""
    check(js, golden, tier, "zoned_until_since_round_from_and_compare", body)


@pytest.mark.parametrize("tier", TIERS)
def test_instant_construction_arithmetic_and_strings(js, golden, tier):
    """CATCHES: Instant epoch conversions with negative values, fromEpoch* validation, add/subtract that accept calendar units, until/since/round increment validation, toString timeZone/precision options, or from()/compare() parsing that behaves incorrectly fails this."""
    body = r"""var I = Temporal.Instant;
var i1 = I.fromEpochMilliseconds(1700000000123), i2 = I.fromEpochNanoseconds(1735689599999999999n);
show('basics', function () { return [i1.toString(), i1.epochMilliseconds, i1.epochNanoseconds, i2.toString(), i2.epochMilliseconds, I.fromEpochMilliseconds(-1).toString(), I.fromEpochNanoseconds(-1n).epochMilliseconds, new I(0n).toJSON(), new I(-123456789n).toString(), new I(-123456789n).epochMilliseconds].join(' '); });
each('fromEpochMilliseconds', [function () { return I.fromEpochMilliseconds(1.5); }, function () { return I.fromEpochMilliseconds(NaN); }, function () { return I.fromEpochMilliseconds(8.64e15 + 1); }, function () { return I.fromEpochMilliseconds('12'); }, function () { return I.fromEpochMilliseconds(); }, function () { return I.fromEpochMilliseconds(-8.64e15); }]);
each('fromEpochNanoseconds', [function () { return I.fromEpochNanoseconds(1); }, function () { return I.fromEpochNanoseconds('1'); }, function () { return I.fromEpochNanoseconds(8640000000000000000001n); }]);
each('ctor errors', [function () { return new I(); }, function () { return new I(1.5); }, function () { return I(0n); }]);
show('toZonedDateTimeISO', function () { return [i1.toZonedDateTimeISO('Asia/Shanghai').toString(), i1.toZonedDateTimeISO('-08:00').toString(), i1.toZonedDateTimeISO(Temporal.ZonedDateTime.from('2020-01-01T00:00[Africa/Cairo]')).toString(), i1.toZonedDateTimeISO('UTC').calendarId].join(' '); });
each('toZonedDateTimeISO errors', [function () { return i1.toZonedDateTimeISO(); }, function () { return i1.toZonedDateTimeISO('Moon/Base'); }, function () { return i1.toZonedDateTimeISO(12); }]);
show('add/subtract', function () { return [i1.add({ hours: 25, minutes: 1 }).toString(), i1.subtract('PT1.5S').toString(), i1.add({ nanoseconds: -123000000 }).toString(), i1.add(Temporal.Duration.from({ microseconds: 7 })).toString(), i1.subtract({ hours: -1 }).toString()].join(' '); });
each('add errors', [function () { return i1.add({ days: 1 }); }, function () { return i1.add({ weeks: 1 }); }, function () { return i1.subtract({ months: 1 }); }, function () { return i1.add({ years: 1 }); }, function () { return I.fromEpochNanoseconds(8640000000000000000000n).add({ nanoseconds: 1 }); }]);
show('until/since', function () { return [i1.until(i2).toString(), i2.since(i1).toString(), i1.until(i2, { largestUnit: 'hours' }).toString(), i1.until(i2, { largestUnit: 'minutes', smallestUnit: 'minutes', roundingMode: 'halfExpand' }).toString(), i1.until(i2, { largestUnit: 'seconds' }).toString(), i1.until(i2, { largestUnit: 'milliseconds' }).toString(), i1.until(i2, { largestUnit: 'microseconds' }).toString(), i1.until(i2, { largestUnit: 'nanoseconds' }).toString(), i2.since(i1, { smallestUnit: 'hours', roundingIncrement: 3 }).toString(), i1.since(i2, { smallestUnit: 'seconds', roundingIncrement: 30, roundingMode: 'ceil' }).toString(), i1.until(i2, { largestUnit: 'auto', smallestUnit: 'millisecond', roundingIncrement: 500 }).toString()].join(' '); });
each('until errors', [function () { return i1.until(i2, { largestUnit: 'days' }); }, function () { return i1.until(i2, { smallestUnit: 'week' }); }, function () { return i1.until(i2, { smallestUnit: 'minutes', roundingIncrement: 1440 }); }, function () { return i1.until(i2, { largestUnit: 'seconds', smallestUnit: 'hours' }); }, function () { return i1.until(i2, { roundingIncrement: Infinity }); }, function () { return i1.until('2020-01-01'); }]);
show('round', function () { return [i1.round('second').toString(), i1.round({ smallestUnit: 'minute', roundingMode: 'trunc' }).toString(), i1.round({ smallestUnit: 'hour', roundingIncrement: 4 }).toString(), i1.round({ smallestUnit: 'hour', roundingIncrement: 24 }).toString(), i1.round({ smallestUnit: 'millisecond', roundingIncrement: 1000, roundingMode: 'halfEven' }).toString(), i1.round({ smallestUnit: 'microsecond', roundingIncrement: 3 }).toString(), new I(-1500000000n).round({ smallestUnit: 'second', roundingMode: 'halfTrunc' }).toString(), new I(-1500000000n).round({ smallestUnit: 'second', roundingMode: 'floor' }).toString(), new I(-1500000000n).round({ smallestUnit: 'second', roundingMode: 'halfCeil' }).toString()].join(' '); });
each('round errors', [function () { return i1.round(); }, function () { return i1.round('day'); }, function () { return i1.round({ smallestUnit: 'hour', roundingIncrement: 7 }); }, function () { return i1.round({ smallestUnit: 'minute', roundingIncrement: 1441 }); }, function () { return i1.round({}); }]);
show('toString', function () { return [i1.toString({ smallestUnit: 'minute' }), i1.toString({ smallestUnit: 'second', timeZone: 'Asia/Kolkata' }), i1.toString({ fractionalSecondDigits: 6 }), i1.toString({ fractionalSecondDigits: 1, roundingMode: 'ceil' }), i1.toString({ timeZone: Temporal.ZonedDateTime.from('2020-01-01T00:00[Pacific/Chatham]') }), i1.toString({ smallestUnit: 'microsecond' }), new I(-1n).toString({ smallestUnit: 'millisecond', roundingMode: 'halfExpand' })].join(' '); });
each('toString errors', [function () { return i1.toString({ smallestUnit: 'hour' }); }, function () { return i1.toString({ timeZone: 'Nope/Nope' }); }, function () { return i1.toString({ fractionalSecondDigits: 10 }); }, function () { return i1.toString({ roundingMode: 'x' }); }]);
show('equals/compare', function () { return [i1.equals(I.from('2023-11-14T22:13:20.123Z')), i1.equals(i2), I.compare(i1, i2), I.compare(i2, i1), I.compare(i1, '2023-11-14T23:13:20.123+01:00'), I.from(Temporal.ZonedDateTime.from('2020-01-01T00:00[UTC]')).toString(), I.from(i1) === i1, I.from('2020-06-01T12:00:00.5-03:00[America/Sao_Paulo][u-ca=hebrew]').toString()].join(','); });
each('from errors', [function () { return I.from(5); }, function () { return I.from('2020-01-01'); }, function () { return I.from('2020-01-01T00:00'); }, function () { return I.from({}); }, function () { return I.from(Temporal.PlainDateTime.from('2020-01-01T00:00')); }]);
show('valueOf', function () { return i1 < i2; });
"""
    check(js, golden, tier, "instant_construction_arithmetic_and_strings", body)


@pytest.mark.parametrize("tier", TIERS)
def test_duration_fields_with_and_arithmetic(js, golden, tier):
    """CATCHES: Duration getters/sign/blank, negated/abs, with() validation, fractional hour/minute parsing into lower units, time-only add/subtract with balancing, or balancing via round({largestUnit}) that is computed wrongly fails this."""
    body = r"""var D = Temporal.Duration;
var d = new D(1, 2, 3, 4, 5, 6, 7, 8, 9, 10);
show('getters', function () { return [d.years, d.months, d.weeks, d.days, d.hours, d.minutes, d.seconds, d.milliseconds, d.microseconds, d.nanoseconds, d.sign, d.blank, d.toString(), d.toJSON(), new D().toString(), new D(-0).sign, Object.is(new D(-0).years, 0)].join(','); });
show('negative', function () { var n = new D(0, 0, 0, -1, -2); return [n.sign, n.toString(), n.abs().toString(), n.negated().toString(), new D().negated().toString(), D.from('-P1Y2M').months].join(' '); });
show('with', function () { return [d.with({ years: 0, months: 0 }).toString(), d.with({ nanoseconds: 999 }).toString(), D.from('PT1H').with({ hours: -1 }).toString(), D.from('P1D').with({ days: 0 }).blank].join(' '); });
each('with errors', [function () { return d.with({}); }, function () { return d.with({ hours: 1.5 }); }, function () { return d.with({ years: -1 }); }, function () { return d.with('PT1H'); }]);
show('from', function () { return [D.from(d) !== d, D.from({ hours: 1, minutes: -0 }).toString(), D.from({ days: 1, years: undefined }).toString(), D.from('P1Y').years, D.from('-PT0.000000001S').nanoseconds].join(' '); });
each('from errors', [function () { return D.from(); }, function () { return D.from(null); }, function () { return D.from(5); }, function () { return D.from(true); }, function () { return D.from(Symbol.iterator); }]);
show('fractional parse', function () { return ['PT1.5H', 'PT1.25M', 'PT0.000001S', 'PT1.999999999S', 'P1DT0.5H', '-PT2.75H', 'PT0.123456789H'].map(function (s) { var x = D.from(s); return [x.days, x.hours, x.minutes, x.seconds, x.milliseconds, x.microseconds, x.nanoseconds].join('/'); }).join(' '); });
show('add/subtract', function () { return [D.from('PT90M').add('PT45M').toString(), D.from('P1D').add('PT1H').toString(), D.from('PT1H').subtract('PT2H').toString(), D.from('P2D').subtract('P2DT1S').toString(), D.from({ milliseconds: 999 }).add({ milliseconds: 1 }).toString(), D.from({ hours: 1e9 }).add({ hours: 1e9 }).toString(), D.from('P1D').add('P1D', { relativeTo: '2020-01-01' }).toString(), D.from('PT59M').add({ seconds: 60 }).toString()].join(' '); });
each('add errors', [function () { return D.from('P1Y').add('P1D'); }, function () { return D.from('P1D').subtract('P1W'); }, function () { return D.from({ days: 104249991374 }).add({ days: 1 }); }]);
show('round balance', function () { return [D.from({ seconds: 100000 }).round({ largestUnit: 'hours' }).toString(), D.from({ seconds: 100000 }).round({ largestUnit: 'days' }).toString(), D.from({ minutes: 1e6 }).round({ largestUnit: 'auto', smallestUnit: 'hours' }).toString(), D.from({ milliseconds: 123456789 }).round({ largestUnit: 'minutes' }).toString(), D.from({ nanoseconds: 3e12 }).round({ largestUnit: 'microseconds' }).toString(), D.from({ hours: -49 }).round({ largestUnit: 'days' }).toString(), D.from({ milliseconds: 123456789 }).round({ largestUnit: 'milliseconds' }).toString(), D.from({ hours: 30, minutes: 45 }).round({ smallestUnit: 'hours', roundingMode: 'halfEven' }).toString(), D.from({ days: 2, hours: 50 }).round({ largestUnit: 'hours' }).toString(), D.from({ seconds: 90 }).round({ smallestUnit: 'minutes', roundingMode: 'halfEven' }).toString(), D.from({ seconds: 150 }).round({ smallestUnit: 'minutes', roundingMode: 'halfEven' }).toString()].join(' '); });
"""
    check(js, golden, tier, "duration_fields_with_and_arithmetic", body)


@pytest.mark.parametrize("tier", TIERS)
def test_duration_round_with_relative_to(js, golden, tier):
    """CATCHES: Duration.round with PlainDateTime, PlainDate-string, bag or ZonedDateTime relativeTo that balances months/weeks wrongly, ignores 23/25-hour days, mis-rounds calendar units with modes/increments, or validates relativeTo inputs wrongly fails this."""
    body = r"""var D = Temporal.Duration;
var pdt = Temporal.PlainDateTime.from('2024-01-31T12:00');
show('PlainDateTime relativeTo', function () { return [D.from({ days: 30, hours: 12 }).round({ largestUnit: 'months', relativeTo: pdt }).toString(), D.from({ hours: 1000 }).round({ largestUnit: 'years', relativeTo: pdt }).toString(), D.from({ months: 1, hours: 13 }).round({ smallestUnit: 'days', relativeTo: pdt }).toString(), D.from({ years: 1, months: 13 }).round({ largestUnit: 'months', relativeTo: pdt }).toString(), D.from({ weeks: 10 }).round({ largestUnit: 'years', smallestUnit: 'months', roundingMode: 'ceil', relativeTo: pdt }).toString(), D.from({ years: -1, days: -15 }).round({ smallestUnit: 'years', roundingMode: 'halfExpand', relativeTo: pdt }).toString(), D.from({ days: 400 }).round({ largestUnit: 'weeks', relativeTo: pdt }).toString(), D.from({ days: 10 }).round({ smallestUnit: 'weeks', roundingMode: 'halfCeil', relativeTo: pdt }).toString(), D.from({ months: 5 }).round({ smallestUnit: 'months', roundingIncrement: 3, relativeTo: pdt }).toString(), D.from({ days: -45 }).round({ largestUnit: 'months', smallestUnit: 'weeks', roundingMode: 'floor', relativeTo: pdt }).toString()].join(' '); });
show('relativeTo kinds', function () { return [D.from({ hours: 50 }).round({ largestUnit: 'days', relativeTo: '2024-03-09T12:00[America/Los_Angeles]' }).toString(), D.from({ hours: 50 }).round({ largestUnit: 'days', relativeTo: '2024-03-09T12:00' }).toString(), D.from({ months: 2 }).round({ largestUnit: 'days', relativeTo: Temporal.ZonedDateTime.from('2024-01-01T00:00[Europe/Paris]') }).toString(), D.from({ months: 2 }).round({ largestUnit: 'days', relativeTo: { year: 2023, month: 1, day: 1, timeZone: 'UTC' } }).toString(), D.from({ months: 2 }).round({ largestUnit: 'days', relativeTo: { year: 2023, month: 1, day: 1, hour: 12 } }).toString(), D.from({ months: 2 }).round({ largestUnit: 'days', relativeTo: Temporal.PlainDate.from('2023-12-31') }).toString(), D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: { year: 2024, month: 13, day: 1 } }).toString()].join(' '); });
var zr = Temporal.ZonedDateTime.from('2024-10-26T12:00[Europe/London]');
show('zoned relativeTo', function () { return [D.from({ days: 1, hours: 12 }).round({ smallestUnit: 'days', relativeTo: zr }).toString(), D.from({ hours: 36 }).round({ largestUnit: 'days', smallestUnit: 'hours', relativeTo: zr }).toString(), D.from({ hours: 24 }).round({ largestUnit: 'days', relativeTo: zr }).toString(), D.from({ hours: 25 }).round({ largestUnit: 'days', relativeTo: zr }).toString(), D.from({ days: 1 }).round({ largestUnit: 'hours', relativeTo: zr }).toString(), D.from({ months: 1, days: 1 }).round({ largestUnit: 'weeks', relativeTo: zr }).toString(), D.from({ hours: -25 }).round({ largestUnit: 'days', relativeTo: Temporal.ZonedDateTime.from('2024-10-28T00:00[Europe/London]') }).toString(), D.from({ days: 1, minutes: 59 }).round({ smallestUnit: 'hours', roundingIncrement: 2, relativeTo: zr }).toString(), D.from({ years: 1, hours: 30 }).round({ smallestUnit: 'months', roundingMode: 'halfExpand', relativeTo: zr }).toString(), D.from({ hours: 23, minutes: 30 }).round({ smallestUnit: 'days', roundingMode: 'halfExpand', relativeTo: zr }).toString(), D.from({ hours: 12, minutes: 30 }).round({ smallestUnit: 'days', roundingMode: 'halfExpand', relativeTo: zr }).toString(), D.from({ minutes: 1439 }).round({ largestUnit: 'days', smallestUnit: 'minutes', roundingIncrement: 30, roundingMode: 'ceil', relativeTo: zr }).toString()].join(' '); });
each('relativeTo errors', [function () { return D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: { year: 2024, month: 1, day: 1, offset: '+01:00', timeZone: 'UTC' } }); }, function () { return D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: '2024-01-01T00:00+01:00[UTC]' }); }, function () { return D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: { year: 2024, month: 1, day: 1, calendar: 'bogus' } }); }, function () { return D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: Temporal.Instant.fromEpochMilliseconds(0) }); }, function () { return D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: new Date(0) }); }, function () { return D.from({ years: 300000 }).round({ largestUnit: 'days', relativeTo: '2024-01-01' }); }, function () { return D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: null }); }]);
show('relativeTo calendars', function () { return [D.from({ months: 1 }).total({ unit: 'days', relativeTo: '2024-01-15[u-ca=hebrew]' }), D.from({ years: 1 }).total({ unit: 'days', relativeTo: '2024-01-15[u-ca=hebrew]' }), D.from({ years: 1 }).total({ unit: 'months', relativeTo: '2024-01-15[u-ca=chinese]' }), D.from({ months: 1 }).round({ largestUnit: 'days', relativeTo: { year: 5784, monthCode: 'M05L', day: 1, calendar: 'hebrew' } }).toString(), D.from({ days: 400 }).round({ largestUnit: 'years', relativeTo: '2024-03-21[u-ca=persian]' }).toString(), D.from({ months: 13 }).round({ largestUnit: 'years', relativeTo: '2024-09-11[u-ca=coptic]' }).toString()].join(' '); });
"""
    check(js, golden, tier, "duration_round_with_relative_to", body)


@pytest.mark.parametrize("tier", TIERS)
def test_duration_total_and_compare(js, golden, tier):
    """CATCHES: Duration.total that returns wrong fractional values for time units, calendar units relative to PlainDate/ZonedDateTime across DST, or Duration.compare that ignores day lengths, needs relativeTo inconsistently, or mis-handles equal components fails this."""
    body = r"""var D = Temporal.Duration;
var pdt = Temporal.PlainDateTime.from('2024-01-31T12:00');
var zr = Temporal.ZonedDateTime.from('2024-10-26T12:00[Europe/London]');
show('total zoned', function () { return [D.from({ hours: 25 }).total({ unit: 'days', relativeTo: zr }), D.from({ days: 2 }).total({ unit: 'hours', relativeTo: zr }), D.from({ months: 1 }).total({ unit: 'weeks', relativeTo: zr }), D.from({ months: 18 }).total({ unit: 'years', relativeTo: zr }), D.from({ hours: 1 }).total({ unit: 'minutes', relativeTo: zr }), D.from({ days: -3 }).total({ unit: 'months', relativeTo: zr }), D.from({ hours: 12 }).total({ unit: 'days', relativeTo: zr }), D.from({ days: 1 }).total({ unit: 'seconds', relativeTo: zr })].join(' '); });
show('total plain', function () { return [D.from('PT1H30M').total('minutes'), D.from('PT1H30M').total('hours'), D.from({ milliseconds: 1 }).total('nanoseconds'), D.from({ microseconds: 1500 }).total('milliseconds'), D.from({ seconds: 1 }).total('microseconds'), D.from({ days: 45 }).total({ unit: 'years', relativeTo: pdt }), D.from({ weeks: 6 }).total({ unit: 'months', relativeTo: pdt }), D.from({ hours: 36 }).total({ unit: 'days' }), D.from({ days: 3, hours: 12 }).total({ unit: 'weeks', relativeTo: pdt }), D.from({ months: -2 }).total({ unit: 'days', relativeTo: pdt }), D.from({ nanoseconds: 1 }).total('hours')].join(' '); });
each('total errors', [function () { return D.from({ days: 3 }).total('weeks'); }, function () { return D.from({ months: 1 }).total('days'); }, function () { return D.from('PT1H').total({ unit: 'hour', relativeTo: 'bad' }); }, function () { return D.from('PT1H').total(5); }]);
show('compare', function () { return [D.compare({ days: 1 }, { hours: 24 }, { relativeTo: zr }), D.compare({ days: 1 }, { hours: 25 }, { relativeTo: zr }), D.compare({ hours: 24 }, { days: 1 }), D.compare({ months: 1 }, { days: 31 }, { relativeTo: zr }), D.compare({ years: 1 }, { days: 365 }, { relativeTo: '2024-01-01' }), D.compare({ years: 1 }, { days: 365 }, { relativeTo: '2023-01-01' }), D.compare('P1Y', 'P1Y'), D.compare('PT1S', 'PT1.000000001S'), D.compare({ weeks: 1 }, { days: 7 }, { relativeTo: zr }), D.compare({ hours: 2 }, { minutes: 119 }, { relativeTo: zr }), D.compare('-P1D', 'P1D'), D.compare({ months: 1 }, { weeks: 4 }, { relativeTo: Temporal.PlainDateTime.from('2023-02-01T00:00') })].join(','); });
each('compare errors', [function () { return D.compare({ months: 1 }, { days: 30 }); }, function () { return D.compare({ weeks: 1 }, { days: 7 }); }, function () { return D.compare('P1D', 'bad'); }, function () { return D.compare('P1D', 'P1D', 'opts'); }, function () { return D.compare({ years: 100000 }, { days: 1 }, { relativeTo: '2024-01-01' }); }]);
"""
    check(js, golden, tier, "duration_total_and_compare", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_year_month_api(js, golden, tier):
    """CATCHES: PlainYearMonth getters in non-ISO calendars, reference-day handling in toString, with/add/subtract overflow and unit restrictions, until/since rounding, toPlainDate day constraining, or string/bag parsing validation that is implemented incorrectly fails this."""
    body = r"""var YM = Temporal.PlainYearMonth;
var y = new YM(2024, 2);
show('getters', function () { return [y.year, y.month, y.monthCode, y.daysInMonth, y.daysInYear, y.monthsInYear, y.inLeapYear, y.era, y.eraYear, y.calendarId, y.toString(), y.toJSON(), new YM(2024, 2, 'gregory', 15).toString(), new YM(2024, 2, 'iso8601', 15).toString(), new YM(2024, 2, 'iso8601', 15).toString({ calendarName: 'always' })].join(','); });
show('getters non-iso', function () { return [['hebrew', 5784], ['chinese', 2023], ['japanese', 2024], ['islamic-civil', 1445], ['persian', 1403], ['coptic', 1740], ['roc', 113], ['indian', 1946], ['dangi', 2023], ['buddhist', 2567]].map(function (p) { var x = YM.from({ calendar: p[0], year: p[1], month: 3 }); return p[0] + ':' + [x.year, x.month, x.monthCode, x.daysInMonth, x.daysInYear, x.monthsInYear, x.inLeapYear, x.era, x.eraYear, x.toString()].join(','); }).join(' | '); });
each('ctor errors', [function () { return new YM(2024, 13); }, function () { return new YM(2024, 0); }, function () { return new YM(275760, 10); }, function () { return new YM(-271821, 3); }, function () { return new YM('x', 1); }, function () { return new YM(2024, 1, 'bogus'); }, function () { return YM(2024, 1); }]);
show('with', function () { return [y.with({ month: 12 }).toString(), y.with({ year: 2025 }).toString(), y.with({ monthCode: 'M07' }).toString(), y.with({ month: 14 }).toString()].join(' '); });
each('with errors', [function () { return y.with({ month: 14 }, { overflow: 'reject' }); }, function () { return y.with({}); }, function () { return y.with({ day: 1 }); }, function () { return y.with({ calendar: 'iso8601' }); }, function () { return y.with(y); }, function () { return y.with({ month: 2, monthCode: 'M03' }); }]);
show('add/subtract', function () { return [y.add({ months: 11 }).toString(), y.add('P1Y').toString(), y.subtract({ months: 2 }).toString(), y.add({ years: 1, months: 1 }).toString(), y.subtract('P30Y11M').toString(), y.add({ months: -14 }).toString()].join(' '); });
each('add errors', [function () { return y.add({ days: 40 }); }, function () { return y.add({ weeks: 1 }); }, function () { return y.add({ hours: 1 }); }, function () { return y.subtract({ nanoseconds: -1 }); }, function () { return YM.from('+275760-09').add({ months: 1 }); }, function () { return YM.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L' }).add({ years: 1 }, { overflow: 'reject' }); }]);
show('add non-iso', function () { return ['chinese', 'islamic-umalqura', 'ethiopic', 'japanese', 'hebrew'].map(function (c) { var x = Temporal.PlainDate.from('2024-02-10').withCalendar(c).toPlainYearMonth(); return c + ':' + x.toString() + '>' + x.add({ months: 5 }).toString() + '>' + x.subtract({ years: 2, months: 1 }).toString(); }).join(' '); });
show('add hebrew leap', function () { var h = YM.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L' }); return [h.add({ months: 1 }).monthCode, h.add({ years: 1 }).monthCode, h.add({ years: 1 }).toString()].join(' '); });
var a = YM.from('2019-11'), b = YM.from('2024-02');
show('until/since', function () { return [a.until(b).toString(), b.since(a).toString(), a.until(b, { largestUnit: 'months' }).toString(), a.until(b, { smallestUnit: 'years', roundingMode: 'halfExpand' }).toString(), b.since(a, { smallestUnit: 'months', roundingIncrement: 6 }).toString(), a.since(b, { largestUnit: 'years', smallestUnit: 'years', roundingMode: 'ceil' }).toString(), b.until(a, { largestUnit: 'auto' }).toString(), a.until(b, { smallestUnit: 'months', roundingIncrement: 10, roundingMode: 'halfExpand' }).toString()].join(' '); });
each('until errors', [function () { return a.until(b, { largestUnit: 'days' }); }, function () { return a.until(b, { smallestUnit: 'weeks' }); }, function () { return a.until(b, { largestUnit: 'months', smallestUnit: 'years' }); }, function () { return a.until(b, { roundingMode: 'x' }); }, function () { return a.until(YM.from('2024-02-01[u-ca=gregory]')); }]);
show('until non-iso', function () { var h1 = YM.from({ calendar: 'hebrew', year: 5780, month: 1 }), h2 = YM.from({ calendar: 'hebrew', year: 5784, monthCode: 'M06' }); return h1.until(h2).toString() + ' ' + h1.until(h2, { largestUnit: 'months' }).toString() + ' ' + h2.since(h1, { smallestUnit: 'years', roundingMode: 'halfExpand' }).toString(); });
show('toPlainDate', function () { return [y.toPlainDate({ day: 29 }).toString(), y.toPlainDate({ day: 31 }).toString(), YM.from('2023-02').toPlainDate({ day: 29 }).toString(), YM.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L' }).toPlainDate({ day: 30 }).toString()].join(' '); });
each('toPlainDate errors', [function () { return y.toPlainDate(); }, function () { return y.toPlainDate({}); }, function () { return y.toPlainDate('x'); }, function () { return y.toPlainDate({ day: 'abc' }); }]);
show('equals/compare', function () { return [y.equals('2024-02'), y.equals({ year: 2024, month: 2 }), y.equals(YM.from('2024-02-15')), YM.compare('2024-02', '2024-03'), YM.compare(YM.from({ year: 2024, month: 2, calendar: 'gregory' }), y), y.equals(YM.from({ year: 2024, month: 2, calendar: 'gregory' }))].join(','); });
show('toString calendarName', function () { var g = YM.from('2024-02-10[u-ca=gregory]'); return [g.toString(), g.toString({ calendarName: 'never' }), g.toString({ calendarName: 'critical' }), y.toString({ calendarName: 'always' }), y.toString({ calendarName: 'critical' })].join(' '); });
show('valueOf', function () { return y + 1; });
show('from strings', function () { return ['2024-02', '2024-02-29T12:00', '2024-02[u-ca=gregory]', '+002024-02', '2024-2', '2024-02-30', '2024-02-01T00:00Z', 'hello', '2024-02-29[u-ca=japanese]'].map(function (s) { try { return YM.from(s).toString(); } catch (e) { return e.name; } }).join(' '); });
show('from bag', function () { return [YM.from({ year: 2024, month: 15 }).toString(), YM.from({ year: 2024, monthCode: 'M02', day: 31 }).toString(), YM.from({ era: 'reiwa', eraYear: 1, month: 6, calendar: 'japanese' }).toString(), YM.from(Temporal.PlainDate.from('2024-07-04')).toString(), YM.from(y) === y].join(' '); });
each('from bag errors', [function () { return YM.from({ year: 2024 }); }, function () { return YM.from({ month: 1 }); }, function () { return YM.from({ year: 2024, month: 15 }, { overflow: 'reject' }); }, function () { return YM.from(2024); }]);
"""
    check(js, golden, tier, "plain_year_month_api", body)


@pytest.mark.parametrize("tier", TIERS)
def test_plain_month_day_api(js, golden, tier):
    """CATCHES: PlainMonthDay construction/getters, with() using a year for constraining, toPlainDate across leap and non-leap years (including Hebrew leap months), equals across calendars, or bag resolution requiring a year for non-ISO ordinal months that is wrong fails this."""
    body = r"""var MD = Temporal.PlainMonthDay;
var m = new MD(2, 29);
show('getters', function () { return [m.monthCode, m.day, m.calendarId, m.month, m.year, m.toString(), m.toJSON(), new MD(12, 25, 'gregory').toString(), new MD(12, 25, 'iso8601', 2000).toString(), new MD(12, 25, 'iso8601', 2000).toString({ calendarName: 'always' }), new MD(12, 25, 'gregory').toString({ calendarName: 'never' })].join(','); });
each('ctor errors', [function () { return new MD(2, 30); }, function () { return new MD(13, 1); }, function () { return new MD(0, 1); }, function () { return new MD(1, 1, 'bogus'); }, function () { return new MD(1, 1, 'iso8601', 275761); }, function () { return MD(1, 1); }]);
show('with', function () { return [m.with({ day: 1 }).toString(), m.with({ monthCode: 'M04', day: 31 }).toString(), m.with({ month: 6 }).toString(), m.with({ year: 2023 }).toString(), m.with({ year: 2023, month: 2 }).toString()].join(' '); });
each('with errors', [function () { return m.with({ day: 31 }, { overflow: 'reject' }); }, function () { return m.with({}); }, function () { return m.with({ calendar: 'iso8601' }); }, function () { return m.with(m); }, function () { return m.with({ month: 2, monthCode: 'M03' }); }, function () { return m.with('--02-28'); }, function () { return m.with({ monthCode: 'M02L' }); }]);
show('toPlainDate', function () { return [m.toPlainDate({ year: 2024 }).toString(), m.toPlainDate({ year: 2023 }).toString(), MD.from({ calendar: 'hebrew', monthCode: 'M05L', day: 15 }).toPlainDate({ year: 5784 }).toString(), MD.from({ calendar: 'hebrew', monthCode: 'M05L', day: 15 }).toPlainDate({ year: 5785 }).toString(), MD.from({ calendar: 'japanese', monthCode: 'M05', day: 1 }).toPlainDate({ era: 'reiwa', eraYear: 1 }).toString(), MD.from({ calendar: 'japanese', monthCode: 'M05', day: 1 }).toPlainDate({ year: 2019 }).toString()].join(' '); });
each('toPlainDate errors', [function () { return m.toPlainDate(); }, function () { return m.toPlainDate({}); }, function () { return m.toPlainDate(5); }, function () { return m.toPlainDate({ year: 'x' }); }, function () { return m.toPlainDate({ year: 275761 }); }]);
show('equals', function () { return [m.equals('--02-29'), m.equals({ month: 2, day: 29 }), m.equals(MD.from({ calendar: 'gregory', monthCode: 'M02', day: 29 })), MD.from({ calendar: 'gregory', monthCode: 'M02', day: 29 }).equals(MD.from('1972-02-29[u-ca=gregory]'))].join(','); });
show('from', function () { return [MD.from({ month: 2, day: 30 }), MD.from({ monthCode: 'M02', day: 29, year: 2023 }), MD.from({ year: 2023, month: 2, day: 29 }), MD.from({ month: 4, day: 31 }), MD.from(Temporal.PlainDate.from('2024-07-04')), MD.from(Temporal.ZonedDateTime.from('2024-07-04T10:00[UTC]')), MD.from({ calendar: 'gregory', year: 2023, month: 2, day: 29 }), MD.from({ calendar: 'hebrew', year: 5784, month: 6, day: 30 }), MD.from(m) === m].map(String).join(' '); });
each('from errors', [function () { return MD.from({ day: 1 }); }, function () { return MD.from({ month: 1 }); }, function () { return MD.from({ monthCode: 'M01' }); }, function () { return MD.from({ calendar: 'hebrew', month: 1, day: 1 }); }, function () { return MD.from({ month: 2, day: 30, year: 2024 }, { overflow: 'reject' }); }, function () { return MD.from({ calendar: 'gregory', month: 2, day: 29 }); }, function () { return MD.from(229); }]);
show('valueOf', function () { return m == 'x'; });
"""
    check(js, golden, tier, "plain_month_day_api", body)


@pytest.mark.parametrize("tier", TIERS)
def test_temporal_to_locale_string(js, golden, tier):
    """CATCHES: Temporal toLocaleString that ignores the receiver kind (dateStyle on PlainTime, timeStyle on PlainDate), lets a timeZone option override a ZonedDateTime's zone, skips the calendar match check, or fails brand checks on foreign receivers fails this."""
    body = r"""var Z = Temporal.ZonedDateTime;
var z = Z.from('2024-01-04T15:30:45.678+00:00[UTC]');
show('zdt defaults', function () { return [z.toLocaleString('en-US'), z.withTimeZone('Asia/Tokyo').toLocaleString('en-US'), z.withTimeZone('+05:30').toLocaleString('en-US'), z.withTimeZone('-11:00').toLocaleString('en-US', { timeZoneName: 'short' })].join(' | '); });
show('zdt components', function () { var ny = z.withTimeZone('America/New_York'); return [ny.toLocaleString('en-US', { dateStyle: 'full' }), ny.toLocaleString('en-US', { timeStyle: 'short' }), ny.toLocaleString('en-US', { hour: 'numeric', minute: '2-digit' }), ny.toLocaleString('en-US', { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' }), ny.toLocaleString('en-US', { second: 'numeric', fractionalSecondDigits: 2 }), ny.toLocaleString('en-US', { dateStyle: 'short', timeStyle: 'medium' })].join(' | '); });
each('zdt errors', [function () { return z.toLocaleString('en-US', { timeZone: 'UTC' }); }, function () { return z.toLocaleString('en-US', 5); }, function () { return z.withCalendar('hebrew').toLocaleString('en-US'); }, function () { return Z.prototype.toLocaleString.call(Temporal.Instant.fromEpochMilliseconds(0)); }, function () { return Z.prototype.toLocaleString.call(5); }, function () { return z.toLocaleString('not a locale!'); }]);
show('plain', function () { return [Temporal.PlainDate.from('2024-07-04').toLocaleString('en-US'), Temporal.PlainTime.from('15:30:45').toLocaleString('en-US'), Temporal.PlainDateTime.from('2024-07-04T15:30:45').toLocaleString('en-US'), Temporal.Instant.fromEpochMilliseconds(1720121445678).toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }), Temporal.PlainDate.from('2024-07-04').toLocaleString('en-US', { dateStyle: 'medium' }), Temporal.PlainTime.from('15:30:45').toLocaleString('en-US', { timeStyle: 'short' }), Temporal.PlainMonthDay.from({ calendar: 'gregory', monthCode: 'M12', day: 25 }).toLocaleString('en-US'), Temporal.PlainYearMonth.from({ calendar: 'gregory', year: 2024, month: 3 }).toLocaleString('en-US')].join(' | '); });
each('plain errors', [function () { return Temporal.PlainDate.from('2024-07-04').toLocaleString('en-US', { timeStyle: 'short' }); }, function () { return Temporal.PlainTime.from('15:30').toLocaleString('en-US', { dateStyle: 'short' }); }, function () { return Temporal.PlainDate.from('2024-07-04[u-ca=hebrew]').toLocaleString('en-US'); }, function () { return Temporal.PlainDate.prototype.toLocaleString.call({}); }, function () { return Temporal.PlainYearMonth.from('2024-03').toLocaleString('en-US'); }, function () { return Temporal.PlainMonthDay.from('--03-01').toLocaleString('en-US'); }, function () { return Temporal.Duration.prototype.toLocaleString.call({}); }]);
show('duration', function () { return Temporal.Duration.from('P1Y2M3DT4H5M6S').toLocaleString('en-US') + ' | ' + Temporal.Duration.from('PT1H').toLocaleString('fr', { style: 'long' }); });
"""
    check(js, golden, tier, "temporal_to_locale_string", body)


@pytest.mark.parametrize("tier", TIERS)
def test_calendar_property_bag_resolution(js, golden, tier):
    """CATCHES: calendar-aware property-bag resolution that accepts malformed or out-of-calendar month codes, lets month and monthCode disagree, mis-resolves era/eraYear per calendar, constrains/rejects month and day overflow wrongly, or reports missing fields with the wrong error fails this."""
    body = r"""var P = Temporal.PlainDate;
var cals = [['hebrew', 5784, 'am'], ['chinese', 2024, null], ['dangi', 2024, null], ['coptic', 1740, 'am'], ['ethiopic', 2016, 'am'], ['ethioaa', 7516, 'aa'], ['islamic-civil', 1445, 'ah'], ['islamic-umalqura', 1445, 'ah'], ['indian', 1946, 'shaka'], ['persian', 1403, 'ap'], ['gregory', 2024, 'ce'], ['japanese', 2024, 'reiwa'], ['roc', 113, 'roc'], ['buddhist', 2567, 'be']];
cals.forEach(function (c) {
  var cal = c[0], y = c[1], era = c[2];
  function f(bag, o) { return function () { return P.from(Object.assign({ calendar: cal }, bag), o).toString({ calendarName: 'never' }); }; }
  each(cal, [f({ day: 1, month: 1 }), f({ year: y, day: 1 }), f({ year: y, monthCode: 'X01', day: 1 }), f({ year: y, monthCode: 'M1', day: 1 }), f({ year: y, monthCode: 'M13', day: 1 }), f({ year: y, monthCode: 'M00', day: 1 }), f({ year: y, monthCode: 'M04L', day: 1 }), f({ year: y, month: 2, monthCode: 'M03', day: 1 }), f({ year: y, month: 1 }), f({ era: era || 'x', month: 1, day: 1 }), f({ era: era || 'x', eraYear: 5, month: 1, day: 1 }), f({ eraYear: 5, month: 1, day: 1 }), f({ year: y, month: 14, day: 1 }), f({ year: y, month: 14, day: 1 }, { overflow: 'reject' }), f({ year: y, month: 1, day: 40 }, { overflow: 'reject' }), f({ year: y, month: 0, day: 1 }), f({ year: y, monthCode: 'M01', day: 0 }), f({ year: y, monthCode: 'M02', day: 31 })]);
});
each('era and year must agree', ['gregory', 'japanese', 'roc', 'buddhist'].map(function (cal) { return function () { return P.from({ calendar: cal, era: cal === 'gregory' ? 'ce' : cal === 'japanese' ? 'reiwa' : cal === 'roc' ? 'roc' : 'be', eraYear: 5, year: 1, month: 1, day: 1 }); }; }));
each('era and year agreeing', [function () { return P.from({ calendar: 'gregory', era: 'bce', eraYear: 1, year: 0, month: 1, day: 1 }).toString(); }, function () { return P.from({ calendar: 'japanese', era: 'reiwa', eraYear: 1, year: 2019, month: 5, day: 1 }).toString(); }]);
"""
    check(js, golden, tier, "calendar_property_bag_resolution", body)


@pytest.mark.parametrize("tier", TIERS)
def test_with_validation_for_date_time_year_month_month_day_and_zoned(js, golden, tier):
    """CATCHES: with() on PlainDateTime, PlainYearMonth, PlainMonthDay and ZonedDateTime that mishandles japanese era/eraYear pairs, unknown eras, timeZone keys, non-positive day/month, monthCode coercion/syntax, month/monthCode conflicts, overflow reject, or non-object options fails this."""
    body = r"""var objs = {
  PlainDateTime: Temporal.PlainDateTime.from('2019-04-30T12:00[u-ca=japanese]'),
  PlainYearMonth: Temporal.PlainYearMonth.from({ calendar: 'japanese', year: 2019, month: 4 }),
  PlainMonthDay: Temporal.PlainMonthDay.from({ calendar: 'japanese', monthCode: 'M04', day: 30 }),
  ZonedDateTime: Temporal.ZonedDateTime.from('2019-04-30T12:00[Asia/Tokyo][u-ca=japanese]')
};
Object.keys(objs).forEach(function (k) {
  var o = objs[k];
  function w(bag, opts) { return function () { return o.with(bag, opts).toString(); }; }
  var cases = [w({ era: 'reiwa', eraYear: 1 }), w({ era: 'heisei', eraYear: 1, month: 1, day: 8 }), w({ era: 'reiwa' }), w({ eraYear: 2 }), w({ era: 'nope', eraYear: 1 }), w({ timeZone: 'UTC' }), w({ day: 0 }), w({ month: 0 }), w({ monthCode: 7 }), w({ monthCode: 'M7' }), w({ monthCode: { toString: function () { return 'M05'; } } }), w({ year: 2020, day: 31 }), w({ month: 13 }, { overflow: 'reject' }), w({ day: 31 }, { overflow: 'reject' }), w({ year: 2020 }, 5)];
  if (k !== 'PlainMonthDay') cases.push(w({ month: 5, monthCode: 'M06' }));
  each(k, cases);
});
"""
    check(js, golden, tier, "with_validation_for_date_time_year_month_month_day_and_zoned", body)


@pytest.mark.parametrize("tier", TIERS)
def test_offset_strings_and_time_zone_arguments(js, golden, tier):
    """CATCHES: UTC offset parsing for the ZonedDateTime offset field (hours-only, compact, seconds and fractions, malformed separators, out-of-range parts, non-string values) or time-zone argument resolution from identifiers, offsets and ISO strings that accepts or rejects the wrong inputs fails this."""
    body = r"""var Z = Temporal.ZonedDateTime;
var base = { year: 2024, month: 11, day: 3, hour: 1, minute: 30, timeZone: 'America/New_York' };
function zb(off, o) { return function () { return Z.from(Object.assign({}, base, { offset: off }), o).toString(); }; }
each('offset strings', ['-04:00', '-05:00', '-0400', '-04', '-04:00:00', '-04:00:00.000000000', '-04:00:00,0', '+00:00', '-4:00', '04:00', '-04:0', '-04:000', '-04:00:', '-04:00:60', '-04:60', '-24:00', '-0400:00', '-04:00:00.', '-04:00:00.1234567890', '-04:00:00x', '−04:00', 'Z'].map(function (s) { return zb(s, { offset: 'reject' }); }));
each('offset values', [zb({ toString: function () { return '-05:00'; } }), zb(-5), zb(null), zb('-05:00:00.5', { offset: 'prefer' }), zb('-05:00:00.5', { offset: 'use' })]);
var z = Z.from('2024-11-03T01:30-04:00[America/New_York]');
each('with offset values', [function () { return z.with({ offset: '-05:00' }).toString(); }, function () { return z.with({ offset: { toString: function () { return '-05:00'; } } }).toString(); }, function () { return z.with({ offset: 5 }).toString(); }, function () { return z.with({ minute: 45, offset: '-05:00:00' }).toString(); }, function () { return z.with({ offset: '+05:00' }).toString(); }, function () { return z.with({ offset: '+05:00' }, { offset: 'ignore' }).toString(); }]);
each('time zone arguments', ['2020-01-01T00:00+05:00', '2020-01-01T00:00Z', '2020-01-01T00:00[Asia/Tokyo]', '2020-01-01T00:00+05:00[Europe/Paris]', '2020-01-01T00:00+05:00:30', '2020-01-01', '2020-01-01T00:00[+03:30]', 'Etc/GMT-14', 'EST5EDT', '+14:00', '-23:59', 'Europe/Kyiv', 'Europe/Kiev', 'GMT', 'Etc/Unknown', '2020-01-01T00:00[Mars/Base]', '+05', '-0830'].map(function (t) { return function () { return Temporal.Instant.fromEpochMilliseconds(0).toZonedDateTimeISO(t).timeZoneId; }; }));
each('zone annotations', [function () { return Z.from('2020-01-01T00:00[Mars/Base]'); }, function () { return Z.from('2020-01-01T00:00+01:00[+01:00]').toString(); }, function () { return Z.from('2020-01-01T00:00+01:00[+0100]').toString(); }, function () { return Z.from('2020-01-01T00:00+01:00[+01]').toString(); }, function () { return Z.from('2020-01-01T00:00-00:00[UTC]').toString(); }, function () { return Z.from('2020-01-01T00:00+00:00:01[UTC]', { offset: 'reject' }).toString(); }, function () { return Z.from('1970-01-01T00:00-00:44:30[Africa/Monrovia]', { offset: 'reject' }).toString(); }, function () { return Z.from('2020-01-01T00:00[America/Argentina/Buenos_Aires]').offset; }]);
"""
    check(js, golden, tier, "offset_strings_and_time_zone_arguments", body)


@pytest.mark.parametrize("tier", TIERS)
def test_duration_relative_to_string_and_bag_forms(js, golden, tier):
    """CATCHES: relativeTo resolution that mishandles Z designators with and without zone annotations, offset-named zones, unknown zones, range limits, calendar annotations, calendar objects in bags, era fields, non-string offsets, or mismatched offsets fails this."""
    body = r"""var D = Temporal.Duration;
function rt(r) { return function () { return D.from({ months: 1, hours: 12 }).round({ largestUnit: 'days', relativeTo: r }).toString(); }; }
each('strings', ['2024-01-31', '2024-01-31T12:00', '2024-01-31T12:00Z[UTC]', '2024-01-31T12:00Z[Asia/Tokyo]', '2024-01-31T12:00+05:00[+05:00]', '2024-01-31T00:00[+0530]', '2024-01-31T12:00Z', '2024-01-31T12:00[Foo/Bar]', '-271821-04-19', '-271821-04-19T00:00[UTC]', '+275760-09-13', '12:00', '2024-01', '2024-01-31[u-ca=hebrew]', '2024-01-31[u-ca=klingon]', '2024-01-31T12:00+09:00[Asia/Tokyo][u-ca=japanese]', '2024-01-31T12:00:00.5+09:00:00[Asia/Tokyo]', 'garbage', '2024-03-09T02:30[America/New_York]'].map(rt));
each('bags', [rt({ year: 2024, month: 1, day: 31, calendar: Temporal.PlainDate.from('2020-01-01[u-ca=coptic]') }), rt({ year: 2024, month: 1, day: 31, calendar: 5 }), rt({ year: 2024, month: 1, day: 31, calendar: {} }), rt({ era: 'reiwa', eraYear: 6, month: 1, day: 31, calendar: 'japanese' }), rt({ era: 'reiwa', month: 1, day: 31, calendar: 'japanese' }), rt({ year: 2024, month: 1, day: 31, hour: 25 }), rt({ year: 2024, month: 1, day: 31, timeZone: 'Asia/Tokyo', offset: { toString: function () { return '+09:00'; } } }), rt({ year: 2024, month: 1, day: 31, timeZone: 'Asia/Tokyo', offset: 9 }), rt({ year: 2024, month: 1, day: 31, timeZone: 'Asia/Tokyo', offset: '+09:00' }), rt({ year: 2024, month: 1, day: 31, timeZone: 'Asia/Tokyo', offset: '+08:00' }), rt({ year: 275760, month: 9, day: 13, timeZone: 'UTC' }), rt({ year: -271821, month: 4, day: 19, timeZone: 'UTC' }), rt({ year: 2024, monthCode: 'M01', day: 31, timeZone: 'UTC', hour: 12, minute: 30, second: 15, millisecond: 1, microsecond: 2, nanosecond: 3 }), rt({ year: 2024, month: 1, day: 31, timeZone: 'Nope/Nope' }), rt({ year: 2024, month: 1, day: 31, timeZone: '2024-01-01T00:00+03:00' }), rt({ year: 2024, month: 1, day: 31, timeZone: Temporal.ZonedDateTime.from('2020-01-01T00:00[Asia/Kolkata]') })]);
"""
    check(js, golden, tier, "duration_relative_to_string_and_bag_forms", body)


@pytest.mark.parametrize("tier", TIERS)
def test_to_string_precision_options(js, golden, tier):
    """CATCHES: toString precision handling (smallestUnit milli/micro/nanosecond, every fractionalSecondDigits value, rounding modes on negative durations, carry into minutes/days, invalid units) for Duration, ZonedDateTime and Instant, or Instant construction via ToBigInt, that is wrong fails this."""
    body = r"""var D = Temporal.Duration;
var d = D.from('P1DT2H3M4.123456789S');
each('duration', [function () { return d.toString({ smallestUnit: 'microsecond' }); }, function () { return d.toString({ smallestUnit: 'nanoseconds' }); }, function () { return d.toString({ smallestUnit: 'milliseconds', roundingMode: 'ceil' }); }].concat([1, 2, 3, 4, 5, 6, 7, 8, 9].map(function (n) { return function () { return d.toString({ fractionalSecondDigits: n }) + '/' + d.negated().toString({ fractionalSecondDigits: n, roundingMode: 'floor' }); }; })).concat([function () { return D.from('PT59.9999999999S'); }, function () { return D.from({ seconds: 59, milliseconds: 999, microseconds: 999, nanoseconds: 999 }).toString({ fractionalSecondDigits: 8, roundingMode: 'halfExpand' }); }, function () { return D.from({ hours: 23, minutes: 59, seconds: 59, milliseconds: 999 }).toString({ smallestUnit: 'second', roundingMode: 'expand' }); }, function () { return D.from({ days: 1 }).toString({ fractionalSecondDigits: 3 }); }, function () { return D.from({ minutes: 5 }).toString({ fractionalSecondDigits: 'auto' }); }, function () { return D.from({ milliseconds: -1 }).toString({ fractionalSecondDigits: 0, roundingMode: 'floor' }); }, function () { return D.from({ weeks: 2, milliseconds: 1500 }).toString({ fractionalSecondDigits: 0 }); }, function () { return D.from({ milliseconds: 1500 }).toString({ fractionalSecondDigits: 2 }); }, function () { return D.from({ microseconds: 1500 }).toString({ fractionalSecondDigits: 4 }); }, function () { return D.from({ nanoseconds: 1500 }).toString({ fractionalSecondDigits: 7 }); }, function () { return D.from({ minutes: 1, nanoseconds: 1500 }).toString({ smallestUnit: 'microsecond' }); }]));
var z = Temporal.ZonedDateTime.from('2024-07-04T09:08:07.654321987+02:00[Europe/Berlin]');
each('zoned', [function () { return z.toString({ smallestUnit: 'millisecond' }); }, function () { return z.toString({ smallestUnit: 'microsecond' }); }, function () { return z.toString({ smallestUnit: 'nanosecond' }); }, function () { return z.toString({ smallestUnit: 'minute', roundingMode: 'ceil' }); }, function () { return z.toString({ smallestUnit: 'hour' }); }, function () { return z.toString({ smallestUnit: 'day' }); }].concat([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 'auto'].map(function (n) { return function () { return z.toString({ fractionalSecondDigits: n }); }; })).concat([function () { return z.toString({ offset: 'auto', timeZoneName: 'auto', calendarName: 'auto' }); }, function () { return Temporal.ZonedDateTime.from('2024-12-31T23:59:59.9999[Asia/Tokyo]').toString({ smallestUnit: 'second', roundingMode: 'halfExpand' }); }]));
var ins = Temporal.Instant.from('2024-07-04T09:08:07.654321987Z');
each('instant', [0, 1, 4, 7, 9].map(function (n) { return function () { return ins.toString({ fractionalSecondDigits: n }); }; }).concat([function () { return ins.toString({ smallestUnit: 'nanosecond' }); }, function () { return ins.toString({ smallestUnit: 'millisecond', roundingMode: 'halfExpand', timeZone: '-03:00' }); }, function () { return ins.toString({ smallestUnit: 'day' }); }, function () { return new Temporal.Instant(true).toString(); }, function () { return new Temporal.Instant('123').toString(); }, function () { return new Temporal.Instant('1.5').toString(); }]));
"""
    check(js, golden, tier, "to_string_precision_options", body)


@pytest.mark.parametrize("tier", TIERS)
def test_duration_round_validation_and_expansion(js, golden, tier):
    """CATCHES: Duration.round that skips argument/unit validation or the increment-while-balancing rule, or zoned/plain relative rounding that fails to carry a rounded-up time into the next day and then bubble into weeks, months or years, fails this."""
    body = r"""var D = Temporal.Duration, Z = Temporal.ZonedDateTime;
var d = D.from('P1DT2H3M4.123456789S');
each('round errors', [function () { return d.round(); }, function () { return d.round(5); }, function () { return d.round({ largestUnit: 'eons' }); }, function () { return d.round({ smallestUnit: 'eons' }); }, function () { return d.round({ largestUnit: 'days', smallestUnit: 'days', roundingIncrement: 2 }); }, function () { return d.round({ largestUnit: 'weeks', smallestUnit: 'days', roundingIncrement: 2, relativeTo: '2024-01-01' }); }, function () { return d.round({ smallestUnit: 'days', roundingIncrement: 3 }); }, function () { return d.round('days'); }, function () { return d.round({ largestUnit: 'auto' }); }, function () { return d.round({ largestUnit: 'auto', smallestUnit: 'auto' }); }, function () { return d.round({ smallestUnit: 'months' }); }, function () { return D.from({ microseconds: 1500 }).round({ smallestUnit: 'microsecond', largestUnit: 'auto' }).toString(); }, function () { return D.from({ nanoseconds: 1500 }).round({ smallestUnit: 'nanosecond', largestUnit: 'auto' }).toString(); }, function () { return D.from({ weeks: 1, nanoseconds: 1 }).round({ smallestUnit: 'nanosecond', relativeTo: '2024-01-01' }).toString(); }]);
var zr = Z.from('2024-03-01T00:00[America/New_York]');
each('expansion', [function () { return zr.until(zr.add({ days: 1, hours: 23, minutes: 30 }), { largestUnit: 'days', smallestUnit: 'hours', roundingMode: 'ceil' }).toString(); }, function () { return D.from({ days: 6, hours: 23, minutes: 59 }).round({ largestUnit: 'weeks', smallestUnit: 'hours', relativeTo: zr }).toString(); }, function () { return D.from({ days: 6, hours: 23, minutes: 59 }).round({ largestUnit: 'months', smallestUnit: 'hours', relativeTo: zr }).toString(); }, function () { return D.from({ days: 30, hours: 23, minutes: 59 }).round({ largestUnit: 'months', smallestUnit: 'minutes', roundingIncrement: 30, relativeTo: zr }).toString(); }, function () { return D.from({ days: -6, hours: -23, minutes: -59 }).round({ largestUnit: 'weeks', smallestUnit: 'hours', relativeTo: zr }).toString(); }, function () { return D.from({ hours: 23, minutes: 59 }).round({ largestUnit: 'days', smallestUnit: 'minutes', roundingIncrement: 30, relativeTo: Z.from('2024-03-10T00:00[America/New_York]') }).toString(); }, function () { return D.from({ months: 11, days: 30, hours: 23 }).round({ largestUnit: 'years', smallestUnit: 'hours', roundingIncrement: 2, roundingMode: 'ceil', relativeTo: zr }).toString(); }, function () { return D.from({ days: 6, hours: 23, minutes: 59 }).round({ largestUnit: 'weeks', smallestUnit: 'hours', relativeTo: '2024-03-01' }).toString(); }, function () { return D.from({ months: 1, days: 30, hours: 23, minutes: 59 }).round({ largestUnit: 'years', smallestUnit: 'hours', relativeTo: '2024-03-01T00:00' }).toString(); }]);
each('zero and tiny', [function () { return Temporal.PlainYearMonth.from('2024-05').until('2024-05', { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'ceil' }).toString(); }, function () { return D.from('PT0S').total({ unit: 'days', relativeTo: zr }); }, function () { return D.from('PT0S').total({ unit: 'months', relativeTo: '2024-01-01' }); }, function () { return D.from('PT0S').round({ largestUnit: 'years', relativeTo: zr }).toString(); }, function () { return D.from('PT0S').round({ smallestUnit: 'months', relativeTo: '2024-01-01' }).toString(); }, function () { return zr.until(zr, { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'ceil' }).toString(); }, function () { return Temporal.PlainDateTime.from('2024-01-01T12:00').until('2024-01-01T12:00', { largestUnit: 'years', smallestUnit: 'weeks' }).toString(); }, function () { return Temporal.PlainDate.from('2024-01-01[u-ca=hebrew]').until('2024-01-01[u-ca=hebrew]', { largestUnit: 'years' }).toString(); }, function () { return D.from({ hours: 0 }).total('hours'); }, function () { return D.from({ hours: 1 }).total({ unit: 'hours', relativeTo: '2024-01-01' }); }, function () { return D.from({ hours: 25 }).total({ unit: 'minutes', relativeTo: '2024-01-01' }); }, function () { return D.from({ days: 1e8 }).total('nanoseconds'); }, function () { return D.from({ seconds: 9007199254740991 }).total('nanoseconds'); }, function () { return D.from({ nanoseconds: 1 }).total('days'); }, function () { return D.from({ days: 104249991374 }).total('days'); }]);
each('difference option errors', [function () { return Temporal.PlainTime.from('10:00').until('12:00', { largestUnit: 'eon' }); }, function () { return Temporal.PlainTime.from('10:00').until('12:00', { smallestUnit: 'eon' }); }, function () { return Temporal.Instant.fromEpochMilliseconds(0).since(Temporal.Instant.fromEpochMilliseconds(1), { largestUnit: 'eon' }); }, function () { return Temporal.Instant.fromEpochMilliseconds(0).since(Temporal.Instant.fromEpochMilliseconds(1), { smallestUnit: 'eon' }); }, function () { return Temporal.PlainDate.from('2024-01-01').until('2024-02-01', { smallestUnit: 'eon' }); }, function () { return Temporal.PlainDateTime.from('2024-01-01').until('2024-02-01', { largestUnit: 'eon' }); }, function () { return Temporal.ZonedDateTime.from('2024-01-01T00:00[UTC]').until('2024-02-01T00:00[UTC]', { smallestUnit: 'eon' }); }, function () { return Temporal.PlainYearMonth.from('2024-01').until('2024-02', { largestUnit: 'eon' }); }, function () { return Temporal.PlainYearMonth.from('2024-01').until('2024-02', { smallestUnit: 'eon' }); }]);
"""
    check(js, golden, tier, "duration_round_validation_and_expansion", body)


@pytest.mark.parametrize("tier", TIERS)
def test_calendar_era_boundaries(js, golden, tier):
    """CATCHES: era computation that misplaces Japanese era start dates (meiji/taisho/showa/heisei/reiwa, pre-1873 ce/bce), ROC/Buddhist/Gregorian year-zero handling, Ethiopic Amete Alem or Islamic bh eras, or era-bag resolution for these calendars fails this."""
    body = r"""var P = Temporal.PlainDate;
function ee(s, c) { return function () { var d = P.from(s).withCalendar(c); return s + '=' + d.era + '/' + d.eraYear + '/' + d.year; }; }
each('japanese', ['1868-10-22', '1868-10-23', '1872-12-31', '1873-01-01', '1912-07-29', '1912-07-30', '1926-12-24', '1926-12-25', '1989-01-07', '1989-01-08', '2019-04-30', '2019-05-01', '1600-06-15', '0001-01-01', '0000-12-31', '-000100-01-01'].map(function (s) { return ee(s, 'japanese'); }));
each('gregory/roc/buddhist', ['0001-01-01', '0000-12-31', '-000005-03-01', '1911-12-31', '1912-01-01', '-000543-01-01'].map(function (s) { return function () { return ['gregory', 'roc', 'buddhist'].map(function (c) { return ee(s, c)(); }).join(' '); }; }));
each('other eras', ['0008-08-26', '0008-08-27', '0284-08-28', '0284-08-29', '-005492-07-18', '0001-01-01', '0622-07-19'].map(function (s) { return function () { return ['ethiopic', 'coptic', 'ethioaa', 'islamic-civil', 'islamic-umalqura', 'persian', 'indian', 'hebrew'].map(function (c) { return ee(s, c)(); }).join(' '); }; }));
function eb(bag) { return function () { return P.from(bag).toString(); }; }
each('era bags', [eb({ calendar: 'japanese', era: 'taisho', eraYear: 5, month: 3, day: 1 }), eb({ calendar: 'japanese', era: 'meiji', eraYear: 6, month: 1, day: 1 }), eb({ calendar: 'japanese', era: 'meiji', eraYear: 45, month: 7, day: 30 }), eb({ calendar: 'japanese', era: 'ce', eraYear: 1500, month: 1, day: 1 }), eb({ calendar: 'japanese', era: 'bce', eraYear: 10, month: 1, day: 1 }), eb({ calendar: 'japanese', era: 'heisei', eraYear: 40, month: 1, day: 1 }), eb({ calendar: 'japanese', era: 'reiwa', eraYear: 0, month: 1, day: 1 }), eb({ calendar: 'ethiopic', era: 'aa', eraYear: 5000, month: 1, day: 1 }), eb({ calendar: 'ethiopic', era: 'am', eraYear: 2016, month: 1, day: 1 }), eb({ calendar: 'ethiopic', era: 'bc', eraYear: 1, month: 1, day: 1 }), eb({ calendar: 'roc', era: 'roc', eraYear: 113, month: 1, day: 1 }), eb({ calendar: 'roc', era: 'broc', eraYear: 113, month: 1, day: 1 }), eb({ calendar: 'buddhist', era: 'be', eraYear: 2567, month: 1, day: 1 }), eb({ calendar: 'islamic-tbla', era: 'bh', eraYear: 1, month: 1, day: 1 }), eb({ calendar: 'islamic-umalqura', era: 'ah', eraYear: 1445, monthCode: 'M09', day: 30 }), eb({ calendar: 'coptic', era: 'am', eraYear: 1740, month: 13, day: 6 }), eb({ calendar: 'japanese', era: 'kamakura', eraYear: 1, month: 1, day: 1 })]);
"""
    check(js, golden, tier, "calendar_era_boundaries", body)


@pytest.mark.parametrize("tier", TIERS)
def test_calendar_year_tables(js, golden, tier):
    """CATCHES: Hebrew new-year postponement rules and year lengths, Persian Nowruz and 33-year leap cycle placement, Umm al-Qura fallback outside its table, or astronomical Chinese new years in the 1800s/1930s that are computed wrongly fail this."""
    body = r"""var P = Temporal.PlainDate;
var hist = {}, starts = [];
for (var y = 5600; y <= 5800; y++) { var d = P.from({ calendar: 'hebrew', year: y, month: 1, day: 1 }); hist[d.daysInYear] = (hist[d.daysInYear] || 0) + 1; if (y % 20 === 0) starts.push(y + ':' + d.toString({ calendarName: 'never' }) + ':' + d.dayOfWeek); }
out.push('hebrew lengths: ' + Object.keys(hist).sort().map(function (k) { return k + 'x' + hist[k]; }).join(' '));
out.push('hebrew new years: ' + starts.join(' '));
var eve = [];
for (var g = 1990; g <= 2030; g += 4) { var t = P.from({ calendar: 'hebrew', year: g + 3761, month: 1, day: 1 }); var e = t.subtract({ days: 1 }); eve.push(e.toString({ calendarName: 'never' }) + '=' + e.year + '/' + e.monthCode + '/' + e.day); }
out.push('hebrew eves: ' + eve.join(' '));
var pers = [];
for (var g2 = 1990; g2 <= 2040; g2 += 5) { ['03-19', '03-20', '03-21'].forEach(function (md) { var p = P.from(g2 + '-' + md).withCalendar('persian'); pers.push(g2 + '-' + md + '=' + p.year + '/' + p.month + '/' + p.day + (p.inLeapYear ? 'L' : '')); }); }
out.push('persian nowruz: ' + pers.join(' '));
var pl = [];
for (var py = 1380; py <= 1420; py++) { if (P.from({ calendar: 'persian', year: py, month: 1, day: 1 }).inLeapYear) pl.push(py); }
out.push('persian leap years: ' + pl.join(','));
out.push('umalqura outside table: ' + ['1800-01-01', '1850-06-15', '2178-01-01', '2200-12-31'].map(function (s) { var u = P.from(s).withCalendar('islamic-umalqura'), c = P.from(s).withCalendar('islamic-civil'); return s + '=' + u.year + '/' + u.month + '/' + u.day + '/' + u.daysInMonth + '/' + u.daysInYear + ' civil ' + c.year + '/' + c.month + '/' + c.day; }).join(' '));
out.push('umalqura bags outside table: ' + [[1200, 1, 1], [1601, 12, 30], [1650, 6, 29]].map(function (a) { return P.from({ calendar: 'islamic-umalqura', year: a[0], month: a[1], day: a[2] }).toString({ calendarName: 'never' }); }).join(' '));
out.push('chinese 1800s/1930s: ' + ['1820-02-14', '1855-02-17', '1930-01-30', '1938-07-01', '1940-12-31'].map(function (s) { var c = P.from(s).withCalendar('chinese'); return s + '=' + c.year + '/' + c.monthCode + '/' + c.day + '/' + c.monthsInYear + '/' + c.daysInYear; }).join(' '));
"""
    check(js, golden, tier, "calendar_year_tables", body)


@pytest.mark.parametrize("tier", TIERS)
def test_month_day_reference_years(js, golden, tier):
    """CATCHES: PlainMonthDay reference ISO years that are wrong for Chinese/Dangi regular and leap month codes, Hebrew 30-day months and Adar I, tabular and Umm al-Qura day-30 months, epagomenal day 6, or Persian/Indian 31-day months, or impossible days that are not rejected, fails this."""
    body = r"""var MD = Temporal.PlainMonthDay;
function r(cal, code, day, ovf) { try { return MD.from({ calendar: cal, monthCode: code, day: day }, { overflow: ovf || 'constrain' }).toString({ calendarName: 'never' }); } catch (e) { return e.name; } }
['chinese', 'dangi'].forEach(function (cal) {
  var codes = [];
  for (var m = 1; m <= 12; m++) { var c = 'M' + (m < 10 ? '0' : '') + m; codes.push(c, c + 'L'); }
  out.push(cal + ': ' + codes.map(function (c) { return c + '=' + r(cal, c, 29) + (/L$/.test(c) ? '' : ',' + r(cal, c, 30)); }).join(' '));
});
out.push('chinese leap day 30: ' + ['M03L', 'M04L', 'M05L', 'M06L', 'M07L'].map(function (c) { return c + '=' + r('chinese', c, 30); }).join(' '));
out.push('chinese never-leap reject: ' + ['M01L', 'M12L'].map(function (c) { return c + '=' + r('chinese', c, 1, 'reject'); }).join(' '));
out.push('hebrew: ' + ['M01', 'M02', 'M03', 'M04', 'M05', 'M05L', 'M06', 'M07', 'M12', 'M06L'].map(function (c) { return c + '=' + r('hebrew', c, 30); }).join(' ') + ' reject ' + ['M04', 'M06', 'M12', 'M01', 'M05L'].map(function (c) { return c + '=' + r('hebrew', c, 30, 'reject'); }).join(' '));
out.push('islamic: ' + ['islamic-civil', 'islamic-tbla', 'islamic-umalqura'].map(function (cal) { return cal + ' ' + ['M01', 'M02', 'M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09', 'M10', 'M11', 'M12'].map(function (c) { return c + '=' + r(cal, c, 30); }).join(' '); }).join(' | '));
out.push('13-month: ' + ['coptic', 'ethiopic', 'ethioaa'].map(function (cal) { return cal + ' ' + [5, 6, 7].map(function (d) { return r(cal, 'M13', d); }).join(' ') + ' ' + r(cal, 'M13', 7, 'reject'); }).join(' | '));
out.push('persian/indian: ' + ['persian', 'indian'].map(function (cal) { return cal + ' ' + ['M01', 'M06', 'M07', 'M12'].map(function (c) { return c + '=' + r(cal, c, 31) + ',' + r(cal, c, 30); }).join(' ') + ' reject ' + r(cal, 'M07', 31, 'reject'); }).join(' | '));
out.push('with year: ' + [MD.from({ calendar: 'chinese', year: 2023, month: 3, day: 1 }), MD.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 30 }), MD.from({ calendar: 'hebrew', year: 5783, monthCode: 'M05L', day: 1 }), MD.from({ calendar: 'hebrew', year: 5783, month: 13, day: 1 }), MD.from({ calendar: 'islamic-civil', year: 1445, month: 12, day: 30 }), MD.from({ calendar: 'gregory', era: 'bce', eraYear: 5, month: 2, day: 29 }), MD.from({ calendar: 'japanese', era: 'reiwa', eraYear: 2, month: 2, day: 29 })].map(function (x) { return x.toString(); }).join(' '));
"""
    check(js, golden, tier, "month_day_reference_years", body)


@pytest.mark.parametrize("tier", TIERS)
def test_receivers_namespace_and_date_interop(js, golden, tier):
    """CATCHES: Temporal methods and getters that do not brand-check their receiver, a Temporal namespace with wrong toStringTag/property attributes/prototype members, Date.prototype.toTemporalInstant mishandling invalid dates, or transition lookup that stops at rule-only tz entries fails this."""
    body = r"""out.push('namespace: ' + [Object.prototype.toString.call(Temporal), Object.prototype.toString.call(Temporal.PlainDate.prototype), Object.prototype.toString.call(Temporal.Duration.from('PT1S')), Temporal.PlainDate.length, Temporal.PlainDate.name, Temporal.ZonedDateTime.prototype.with.length, Object.keys(Temporal).length, Object.getOwnPropertyNames(Temporal).sort().join('/'), Object.getOwnPropertyDescriptor(Temporal, 'PlainDate').writable, Object.getOwnPropertyDescriptor(Temporal, 'PlainDate').enumerable].join(' '));
out.push('PlainDate.prototype: ' + Object.getOwnPropertyNames(Temporal.PlainDate.prototype).sort().join(','));
show('toTemporalInstant', function () { return new Date(1700000000123).toTemporalInstant().toString() + ' ' + new Date(-1).toTemporalInstant().epochNanoseconds; });
show('toTemporalInstant invalid', function () { return new Date(NaN).toTemporalInstant(); });
show('toTemporalInstant receiver', function () { return Date.prototype.toTemporalInstant.call({}); });
each('calendarId receivers', ['PlainDate', 'PlainDateTime', 'PlainYearMonth', 'PlainMonthDay', 'ZonedDateTime'].map(function (k) { return function () { return Object.getOwnPropertyDescriptor(Temporal[k].prototype, 'calendarId').get.call({ calendarId: 'iso8601' }); }; }));
['PlainDate', 'PlainDateTime', 'PlainYearMonth', 'PlainMonthDay', 'ZonedDateTime', 'Instant', 'Duration'].forEach(function (k) { var r = []; ['toString', 'toJSON', 'equals', 'add', 'with', 'until', 'round'].forEach(function (m) { var f = Temporal[k].prototype[m]; if (!f) { r.push(m + ':absent'); return; } try { f.call(new Temporal.PlainTime()); r.push(m + ':ok'); } catch (e) { r.push(m + ':' + e.name + ':' + e.message); } }); out.push(k + ' on PlainTime: ' + r.join(' ')); });
each('getter receivers', [['PlainTime', 'hour'], ['PlainDateTime', 'hour'], ['PlainYearMonth', 'daysInMonth'], ['PlainMonthDay', 'day'], ['ZonedDateTime', 'hoursInDay'], ['Instant', 'epochNanoseconds'], ['Duration', 'sign'], ['PlainDate', 'dayOfWeek']].map(function (p) { return function () { return Object.getOwnPropertyDescriptor(Temporal[p[0]].prototype, p[1]).get.call(p[0] === 'PlainDate' ? Temporal.PlainDateTime.from('2020-01-01T00:00') : Temporal.PlainDate.from('2020-01-01')); }; }));
show('rule-only transitions skipped', function () { var Z = Temporal.ZonedDateTime; return [Z.from('1968-03-01T00:00[Europe/London]').getTimeZoneTransition('next').toString(), Z.from('1971-06-01T00:00[Europe/London]').getTimeZoneTransition('previous').toString(), Z.from('2011-06-01T00:00[Europe/Moscow]').getTimeZoneTransition('next').toString(), Z.from('2011-06-01T00:00[Europe/Moscow]').getTimeZoneTransition('previous').toString()].join(' '); });
"""
    check(js, golden, tier, "receivers_namespace_and_date_interop", body)


@pytest.mark.parametrize("tier", TIERS)
def test_iso_string_grammar_edge_cases(js, golden, tier):
    """CATCHES: an ISO 8601/RFC 9557 parser that resolves PlainTime/year-month/month-day ambiguity wrongly, accepts malformed offsets, fractions, annotation keys/values, time-zone annotation names or ordering, out-of-range year-month limits, or malformed duration strings fails this."""
    body = r"""function parse(label, ctor, inputs) { out.push(label + ': ' + inputs.map(function (s) { try { return ctor.from(s).toString(); } catch (e) { return e.name; } }).join(' | ')); }
parse('PlainTime', Temporal.PlainTime, ['2021-12', '202112', '2021-13', '1214', '1232', '1301', '-1214', '--1214', 'T2021-12', '12:34-05:00', '1234+0530', '12:34:56+05:30:15', '12:34+05:30:15.5', '12:34+053015', '12:34+05:60', '12:60', '12:34:61', '12:34:60', 'T12:34[u-ca=iso8601]', '12:34[!u-ca=iso8601]', '12:34[]', '12:34[U-CA=iso8601]', '12:34[1a=b]', '12:34[a=]', '12:34[a=b c]', '12:34[u-ca=iso8601', '12:34[Europe/1abc]', '12:34[Europe/Paris][Asia/Tokyo]', '12:34[a=b][Europe/Paris]', '12:34.5', '12:34:56.', '12:34:56.1234567891']);
parse('PlainDate', Temporal.PlainDate, ['2024-01-01T12:34[_x=y]', '2024-01-01[x_y-z=a-b-1]', '2024-01-01[!u-ca=iso8601][!u-ca=iso8601]', '2024-01-01[Etc/GMT+5]', '2024-01-01[+05:00]', '2024-01-01[-25:00]', '2024-01-01[.hidden]', '2024-01-01T25', '2024-01-01T23:59:59,999999999', '2024-00-01', '2024-13-01', '2024-02-00', '2024-1-01', '2024-01-1', '+2024-01-01', '-0000000-01-01', '20240101T1200', '2024-0101', '2024-01-01t12', '2024-01-01T12:00:00.5Z[u-ca=iso8601]']);
parse('PlainYearMonth', Temporal.PlainYearMonth, ['-271821-04', '-271821-03', '+275760-09', '+275760-10', '2024-01[Europe/Paris]', '2024-01[!u-ca=iso8601]', '2024-01[u-ca=gregory][u-ca=iso8601]', '202401[u-ca=iso8601]', '2024-01-15[u-ca=hebrew]', '2024-01T12', '1214']);
parse('PlainMonthDay', Temporal.PlainMonthDay, ['--02-29', '02-29', '0229', '--0229', '-02-29', '--13-01', '--02-30[u-ca=iso8601]', '--02-28[u-ca=gregory]', '2023-02-28[u-ca=gregory]', '12-25[Europe/Paris]', '1225T12', '--12-25[!u-ca=iso8601]', '2024-02-29T12:00Z']);
parse('Duration', Temporal.Duration, ['P1Y2', 'P1X', 'PT1.2.3S', 'PT.5S', 'PT1H2', 'PT1X', 'PT1S2M', 'P1DT1H1.5', 'PT1M1H', 'P1W1D', 'P1D1W', 'p1y1m1w1dt1h1m1s', 'PT1,000000001S', 'P0YT0S', '-P0D', 'P1M1Y', 'PT0.5H0M', 'P1.5W']);
"""
    check(js, golden, tier, "iso_string_grammar_edge_cases", body)


@pytest.mark.parametrize("tier", TIERS)
def test_bags_with_calendar_objects_and_range_limits(js, golden, tier):
    """CATCHES: property bags whose calendar is a Temporal object (or an invalid object), PlainMonthDay/ZonedDateTime/PlainDateTime bag field validation, unsupported calendar annotations, or the representable-range limits enforced by from(), with(), withPlainTime(), startOfDay(), toString() rounding and year-month arithmetic, implemented incorrectly fail this."""
    body = r"""var MD = Temporal.PlainMonthDay, Z = Temporal.ZonedDateTime, DT = Temporal.PlainDateTime, P = Temporal.PlainDate, YM = Temporal.PlainYearMonth;
var calObj = P.from('2020-01-01[u-ca=hebrew]');
each('month-day bags', [function () { return MD.from({ calendar: calObj, monthCode: 'M05L', day: 1 }); }, function () { return MD.from({ calendar: Temporal.ZonedDateTime.from('2020-01-01T00:00[UTC][u-ca=coptic]'), monthCode: 'M13', day: 6 }); }, function () { return MD.from({ calendar: {}, monthCode: 'M01', day: 1 }); }, function () { return MD.from({ calendar: 7, monthCode: 'M01', day: 1 }); }, function () { return MD.from({ monthCode: 'M01', day: 0 }); }, function () { return MD.from({ month: 0, day: 1 }); }, function () { return MD.from({ monthCode: 1, day: 1 }); }, function () { return MD.from({ monthCode: 'M001', day: 1 }); }, function () { return MD.from({ calendar: 'gregory', era: 'ce', eraYear: 700000, monthCode: 'M01', day: 1 }); }, function () { return MD.from({ calendar: 'gregory', era: 'ce', eraYear: 2020, monthCode: 'M02', day: 29 }); }, function () { return MD.from({ year: 300000, monthCode: 'M02', day: 29 }); }, function () { return MD.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30 }, { overflow: 'reject' }); }, function () { return MD.from({ calendar: 'chinese', year: 2024, monthCode: 'M06L', day: 1 }, { overflow: 'reject' }); }, function () { return MD.from({ calendar: 'chinese', year: 2025, monthCode: 'M06L', day: 1 }, { overflow: 'reject' }); }, function () { return MD.from({ calendar: 'hebrew', month: 6, day: 1, year: 5784 }); }, function () { return MD.from({ calendar: 'hebrew', month: 6, day: 1, year: 5783 }); }, function () { return MD.from({ month: 2, day: 29, calendar: 'iso8601' }, { overflow: 'reject' }); }]);
each('zoned bags', [function () { return Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC', calendar: calObj }).toString(); }, function () { return Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC', calendar: {} }); }, function () { return Z.from({ year: 2024, monthCode: 1, day: 1, timeZone: 'UTC' }); }, function () { return Z.from({ month: 1, day: 1, timeZone: 'UTC' }); }, function () { return Z.from({ year: 2024, day: 1, timeZone: 'UTC' }); }, function () { return Z.from({ year: -271821, month: 4, day: 19, timeZone: 'UTC' }); }, function () { return Z.from({ year: -271821, month: 4, day: 20, timeZone: 'UTC' }).toString(); }, function () { return Z.from({ year: 275760, month: 9, day: 13, hour: 1, timeZone: '+01:00' }).toString(); }, function () { return Z.from({ year: 275760, month: 9, day: 14, timeZone: 'UTC' }); }, function () { return Z.from({ year: -271821, month: 4, day: 19, hour: 23, timeZone: '-01:00' }).toString(); }, function () { return Z.from('2024-01-01T00:00[UTC][u-ca=nope]'); }, function () { return Z.from({ year: 2024, month: 1, day: 1, hour: 24, timeZone: 'UTC' }, { overflow: 'reject' }); }, function () { return Z.from({ year: 2024, month: 1, day: 1, hour: 24, timeZone: 'UTC' }).toString(); }]);
each('date and date-time bags', [function () { return DT.from({ month: 1, day: 1 }); }, function () { return DT.from({ year: 2024, day: 1 }); }, function () { return DT.from('2024-01-01T00:00[u-ca=nope]'); }, function () { return DT.from({ year: 2024, month: 1, day: 1, calendar: calObj }).toString(); }, function () { return DT.from({ year: -271821, month: 4, day: 19 }); }, function () { return DT.from({ year: -271821, month: 4, day: 19, nanosecond: 1 }).toString(); }, function () { return P.from('2024-01-01[u-ca=nope]'); }, function () { return P.from(5); }, function () { return P.from({ year: 275760, month: 9, day: 14 }); }, function () { return P.from({ year: 2024, month: 1, day: 1, calendar: calObj }).toString(); }, function () { return YM.from('2024-01-01[u-ca=nope]'); }, function () { return YM.from({ year: 275760, month: 10 }); }, function () { return YM.from({ year: 2024, month: 1, calendar: calObj }).toString(); }]);
var dt = DT.from('+275760-09-13T00:00'), zz = Z.from('+275760-09-13T00:00[UTC]');
each('range limits in methods', [function () { return DT.from('-271821-04-19T00:00:00.000000001').withPlainTime('00:00'); }, function () { return DT.from('-271821-04-19T00:00:00.000000001').with({ nanosecond: 0 }); }, function () { return dt.add({ nanoseconds: -1 }).toString(); }, function () { return dt.subtract({ days: -1 }); }, function () { return Z.from('-271821-04-20T00:00[UTC]').withPlainTime('00:00').toString(); }, function () { return Z.from('-271821-04-20T00:00+01:00[+01:00]').withPlainTime('00:00'); }, function () { return Z.from('-271821-04-20T00:30+01:00[+01:00]').startOfDay(); }, function () { return zz.toString({ smallestUnit: 'minute' }); }, function () { return Z.from('+275760-09-13T00:00-01:00[-01:00]'); }, function () { return Z.from('-271821-04-20T00:00[UTC]').with({ day: 19 }); }, function () { return Z.from('-271821-04-20T00:00[UTC]').round({ smallestUnit: 'day', roundingMode: 'floor' }).toString(); }, function () { return P.from('-271821-04-19').toZonedDateTime('UTC'); }, function () { return P.from('-271821-04-20').toZonedDateTime('-01:00').toString(); }, function () { return YM.from('-271821-04').subtract({ months: 1 }); }, function () { return YM.from('-271821-04').until('+275760-09', { largestUnit: 'years' }).toString(); }, function () { return YM.from('-271821-05').until('+275760-09', { largestUnit: 'years' }).toString(); }]);
each('extended years in toString', [function () { return new YM(-5, 1).toString({ calendarName: 'always' }); }, function () { return new YM(12345, 1).toString(); }, function () { return new MD(1, 1, 'iso8601', -5).toString({ calendarName: 'always' }); }, function () { return new MD(1, 1, 'iso8601', 12345).toString({ calendarName: 'critical' }); }, function () { return new P(-5, 1, 1).toString(); }, function () { return new DT(10000, 1, 1).toString(); }]);
"""
    check(js, golden, tier, "bags_with_calendar_objects_and_range_limits", body)


@pytest.mark.parametrize("tier", TIERS)
def test_option_and_field_read_order_and_coercion(js, golden, tier):
    """CATCHES: Temporal methods that read options or property-bag fields in a non-alphabetical or otherwise non-spec order, read options before parsing their primary argument, or coerce fractionalSecondDigits/roundingIncrement/smallestUnit/roundingMode values incorrectly fail this."""
    body = r"""function logged(obj) { var log = []; var p = new Proxy(obj, { get: function (t, k) { if (typeof k === 'string') log.push(k); return t[k]; } }); return { p: p, log: log }; }
function order(label, f, base) { var l = logged(base || {}); try { var r = f(l.p); out.push(label + ': ' + l.log.join(',') + ' => ' + String(r)); } catch (e) { out.push(label + ': ' + l.log.join(',') + ' => ' + e.name + ':' + e.message); } }
var dt = Temporal.PlainDateTime.from('2024-07-04T09:08:07.654321987'), z = dt.toZonedDateTime('Europe/Berlin'), ins = z.toInstant(), d = Temporal.Duration.from('P1DT2H3M4.5S'), t = dt.toPlainTime();
order('PlainDateTime.toString', function (o) { return dt.toString(o); });
order('PlainTime.toString', function (o) { return t.toString(o); });
order('ZonedDateTime.toString', function (o) { return z.toString(o); });
order('Instant.toString', function (o) { return ins.toString(o); });
order('Duration.toString', function (o) { return d.toString(o); });
order('Duration.round', function (o) { return d.round(o); }, { largestUnit: 'hours' });
order('Duration.total', function (o) { return d.total(o); }, { unit: 'minutes' });
order('ZonedDateTime.from', function (o) { return Temporal.ZonedDateTime.from('2024-11-03T01:30-04:00[America/New_York]', o); });
order('ZonedDateTime.from bad string', function (o) { return Temporal.ZonedDateTime.from('not a date', o); });
order('ZonedDateTime.with', function (o) { return z.with({ hour: 1 }, o); });
order('ZonedDateTime.round', function (o) { return z.round(o); }, { smallestUnit: 'hour' });
order('ZonedDateTime.until', function (o) { return z.until(z.add({ days: 40 }), o); });
order('Instant.round', function (o) { return ins.round(o); }, { smallestUnit: 'minute' });
order('PlainTime.round', function (o) { return t.round(o); }, { smallestUnit: 'minute' });
order('PlainDateTime.round', function (o) { return dt.round(o); }, { smallestUnit: 'minute' });
order('PlainYearMonth.until', function (o) { return Temporal.PlainYearMonth.from('2020-01').until('2024-07', o); });
order('PlainDate.add', function (o) { return Temporal.PlainDate.from('2024-01-31').add({ months: 1 }, o); });
order('PlainDateTime.from bag', function (o) { return Temporal.PlainDateTime.from(o); }, { year: 2024, month: 2, day: 29, hour: 1, minute: 2, second: 3, millisecond: 4, microsecond: 5, nanosecond: 6 });
order('ZonedDateTime.from bag', function (o) { return Temporal.ZonedDateTime.from(o); }, { year: 2024, month: 2, day: 29, hour: 1, timeZone: 'UTC', offset: '+00:00', calendar: 'iso8601' });
order('Duration.from bag', function (o) { return Temporal.Duration.from(o); }, { hours: 1, days: 2 });
order('PlainMonthDay.from bag', function (o) { return Temporal.PlainMonthDay.from(o); }, { monthCode: 'M02', day: 29, calendar: 'gregory' });
order('PlainYearMonth.from bag', function (o) { return Temporal.PlainYearMonth.from(o); }, { year: 2024, month: 2, calendar: 'japanese' });
order('PlainTime.from bag', function (o) { return Temporal.PlainTime.from(o); }, { hour: 1, second: 2 });
order('relativeTo bag', function (o) { return Temporal.Duration.from({ months: 1 }).total({ unit: 'days', relativeTo: o }); }, { year: 2024, month: 2, day: 1, timeZone: 'UTC' });
each('coercions', [function () { return dt.toString({ fractionalSecondDigits: NaN }); }, function () { return dt.toString({ fractionalSecondDigits: Infinity }); }, function () { return dt.toString({ fractionalSecondDigits: '3' }); }, function () { return dt.toString({ fractionalSecondDigits: 3.9 }); }, function () { return dt.toString({ smallestUnit: { toString: function () { return 'second'; } } }); }, function () { return dt.round({ smallestUnit: 'minute', roundingIncrement: '15' }).toString(); }, function () { return dt.round({ smallestUnit: 'minute', roundingIncrement: { valueOf: function () { return 30; } } }).toString(); }, function () { return dt.toString({ smallestUnit: 'eon' }); }, function () { return z.toString({ smallestUnit: 'eon' }); }, function () { return ins.toString({ smallestUnit: 'eon' }); }, function () { return dt.round({ smallestUnit: 'minute', roundingIncrement: 1.5 }).toString(); }, function () { return dt.round({ smallestUnit: 'minute', roundingIncrement: 0.5 }).toString(); }, function () { return dt.toString({ roundingMode: { toString: function () { return 'ceil'; } }, smallestUnit: 'second' }); }]);
"""
    check(js, golden, tier, "option_and_field_read_order_and_coercion", body)


@pytest.mark.parametrize("tier", TIERS)
def test_subclass_instances_produce_base_types(js, golden, tier):
    """CATCHES: Temporal operations that propagate a subclass prototype (or a species constructor) to their results instead of always returning base Temporal instances, or static from() that honours the receiver class, fails this."""
    body = r"""class MyDate extends Temporal.PlainDate { hello() { return 'hi'; } }
var m = new MyDate(2024, 1, 31);
function kinds(list, C) { return list.map(function (x) { return x.constructor.name + ':' + (x instanceof C); }).join(' '); }
show('subclass instance', function () { return m.hello() + ' ' + (m instanceof MyDate) + ' ' + m.toString() + ' ' + (Object.getPrototypeOf(MyDate) === Temporal.PlainDate); });
show('PlainDate results', function () { return kinds([m.add({ days: 1 }), m.with({ day: 1 }), m.withCalendar('hebrew'), MyDate.from('2024-01-01'), Temporal.PlainDate.from.call(MyDate, '2024-01-01'), m.toPlainDateTime(), m.until('2024-02-01'), m.toPlainYearMonth()], MyDate); });
class MyZ extends Temporal.ZonedDateTime {}
var z = new MyZ(0n, 'UTC');
show('ZonedDateTime results', function () { return kinds([z.add({ hours: 1 }), z.with({ hour: 3 }), z.withTimeZone('Asia/Tokyo'), z.startOfDay(), z.round('hour'), z.toPlainDate(), z.toInstant(), z.getTimeZoneTransition('next') || z.withCalendar('gregory')], MyZ); });
class MyD extends Temporal.Duration {}
var d = new MyD(0, 0, 0, 1);
show('Duration results', function () { return kinds([d.add('PT1H'), d.negated(), d.abs(), d.with({ days: 2 }), d.round('hours'), MyD.from('PT1H')], MyD); });
class MyT extends Temporal.PlainTime {}
show('PlainTime results', function () { var t = new MyT(1, 2); return kinds([t.add({ hours: 1 }), t.with({ minute: 0 }), t.round('hour'), t.since('00:00')], MyT) + ' ' + Temporal.PlainTime.compare(t, '01:02'); });
"""
    check(js, golden, tier, "subclass_instances_produce_base_types", body)


@pytest.mark.parametrize("tier", TIERS)
def test_loop_driven_calendar_and_zone_computations(js, golden, tier):
    """CATCHES: Temporal arithmetic that drifts or diverges between execution tiers inside hot loops: Friday-the-13th counting, per-day hoursInDay sums across DST years, transition walking with getTimeZoneTransition, Chinese new-year and Umm al-Qura Ramadan dates, and accumulated Duration balancing fail this."""
    body = r"""function fri13(y0, y1) { var n = 0, list = []; for (var y = y0; y <= y1; y++) { for (var m = 1; m <= 12; m++) { var d = new Temporal.PlainDate(y, m, 13); if (d.dayOfWeek === 5) { n++; if (y === 2026) list.push(d.toString()); } } } return n + ' ' + list.join(','); }
out.push('friday 13ths 2000-2030: ' + fri13(2000, 2030));
function hours(tz, y) { var d = Temporal.PlainDate.from({ year: y, month: 1, day: 1 }), total = 0, odd = []; while (d.year === y) { var h = d.toZonedDateTime(tz).hoursInDay; total += h; if (h !== 24) odd.push(d.toString().slice(5) + '=' + h); d = d.add({ days: 1 }); } return tz + ' ' + total + ' ' + odd.join(','); }
['America/New_York', 'Europe/London', 'Australia/Lord_Howe', 'Asia/Tokyo'].forEach(function (tz) { out.push('hours ' + hours(tz, 2024)); });
function transitions(tz, from, to) { var z = Temporal.ZonedDateTime.from(from + 'T00:00[' + tz + ']'), end = Temporal.ZonedDateTime.from(to + 'T00:00[' + tz + ']'), n = 0, offs = {}; for (;;) { z = z.getTimeZoneTransition('next'); if (z === null || Temporal.ZonedDateTime.compare(z, end) > 0) break; n++; offs[z.offset] = 1; } return tz + ' ' + n + ' ' + Object.keys(offs).sort().join(','); }
['Europe/Berlin', 'America/Sao_Paulo', 'Asia/Kolkata', 'Pacific/Apia'].forEach(function (tz) { out.push('transitions ' + transitions(tz, '2000-01-01', '2024-01-01')); });
function chineseNewYears(y0, y1) { var r = []; for (var y = y0; y <= y1; y++) r.push(Temporal.PlainDate.from({ calendar: 'chinese', year: y, month: 1, day: 1 }).withCalendar('iso8601').toString().slice(5)); return r.join(' '); }
out.push('chinese new years 2020-2030: ' + chineseNewYears(2020, 2030));
function ramadan(y0, y1) { var r = []; for (var y = y0; y <= y1; y++) { var d = Temporal.PlainDate.from({ calendar: 'islamic-umalqura', year: y, month: 9, day: 1 }); r.push(y + ':' + d.withCalendar('iso8601').toString() + '/' + d.daysInMonth); } return r.join(' '); }
out.push('ramadan umalqura: ' + ramadan(1440, 1450));
var acc = Temporal.Duration.from('PT0S'); for (var i = 0; i < 200; i++) acc = acc.add({ minutes: 7, seconds: 13 });
out.push('accumulated: ' + acc.toString() + ' ' + acc.round({ largestUnit: 'day' }).toString() + ' ' + acc.total('hour'));
"""
    check(js, golden, tier, "loop_driven_calendar_and_zone_computations", body)
