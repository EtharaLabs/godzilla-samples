"""Temporal plain types: PlainDate, PlainTime, PlainDateTime, PlainYearMonth, PlainMonthDay.

Construction (constructors, ISO 8601 / RFC 9557 strings, property bags with overflow), getters,
with/add/subtract, until/since with rounding options, round(), equals/compare, toString options,
conversions between the plain types, and the exact TypeError/RangeError messages for bad inputs.
"""
from conftest import check_script, resources_for

G = resources_for(__file__)

# Shared JS helpers: `t(label, fn)` prints the value (or the thrown error's name and message).
PRE = r'''
const show = (v) => {
  if (v === undefined) return 'undefined';
  if (typeof v === 'bigint') return v + 'n';
  if (v !== null && typeof v === 'object' && !(Symbol.toStringTag in v)) return JSON.stringify(v);
  return String(v);
};
const t = (label, fn) => {
  let out;
  try { out = show(fn()); } catch (e) { out = 'threw ' + e.name + ': ' + e.message; }
  console.log(label + ' => ' + out);
};
'''


def check(run, workdir, name, body, **kw):
    """Run PRE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRE + body, **kw)


def test_plain_date_constructor_and_errors(run, workdir):
    """CATCHES: PlainDate constructor that skips 'new' checks, wraps/accepts Feb 29 in common years, truncation of fractional args, wrong calendar validation (TypeError vs RangeError) or wrong extended-year formatting."""
    check(run, workdir, "plain_date_constructor_and_errors", r'''
const P = Temporal.PlainDate;
t('leap day', () => new P(2024, 2, 29));
t('common-year feb 29', () => new P(2023, 2, 29));
t('month 13', () => new P(2023, 13, 1));
t('day 0', () => new P(2023, 1, 0));
t('call without new', () => P(2024, 1, 1));
t('gregory', () => new P(2024, 1, 1, 'gregory'));
t('calendar case-insensitive', () => new P(2024, 1, 1, 'GREGORY'));
t('alias islamicc', () => new P(2024, 1, 1, 'islamicc').calendarId);
t('unknown calendar', () => new P(2024, 1, 1, 'foo'));
t('iso string as calendar', () => new P(2024, 1, 1, '2024-01-01[u-ca=hebrew]'));
t('numeric calendar', () => new P(2024, 1, 1, 5));
t('infinite year', () => new P(Infinity, 1, 1));
t('NaN month', () => new P(2024, NaN, 1));
t('fractional fields truncate', () => new P(2024.7, 1.9, 1.2));
t('string fields', () => new P('2024', '02', '3'));
t('negative year', () => new P(-5, 1, 1));
t('six-digit year', () => new P(12345, 1, 1));
t('min date', () => new P(-271821, 4, 19));
t('below min', () => new P(-271821, 4, 18));
t('max date', () => new P(275760, 9, 13));
t('above max', () => new P(275760, 9, 14));
t('length', () => P.length + ' ' + P.name);
t('toStringTag', () => Object.prototype.toString.call(new P(2000, 1, 1)));
t('symbol arg', () => new P(Symbol(), 1, 1));
''')


def test_plain_date_from_iso_strings(run, workdir):
    """CATCHES: ISO 8601/RFC 9557 parser bugs: basic vs extended formats, expanded years, -000000, Z rejection for PlainDate, annotation critical flags, duplicate calendars, time zone annotations, lowercase t / space separators and leap seconds."""
    check(run, workdir, "plain_date_from_iso_strings", r'''
const P = Temporal.PlainDate;
for (const s of [
  '2024-02-29', '20240229', '+002024-02-29', '-002024-02-29', '-000000-02-29', '+0020240229',
  '2024-0229', '2024-02-29T12:00:00Z', '2024-02-29T12:00:00+01:00', '2024-02-29 12:00',
  '2024-02-29t12:00', '2024-02-29T23:59:60', '2024-02-29T12:00:00.123456789+05:30[Asia/Kolkata]',
  '2024-02-29T12:00:00,5', '2024-02-29T12', '2024-02-29T1200', '2024-02-29T12:0000',
  '2024-02-29[u-ca=japanese]', '2024-02-29[!u-ca=japanese]', '2024-02-29[foo=bar]',
  '2024-02-29[!foo=bar]', '2024-02-29[u-ca=japanese][u-ca=hebrew]', '2024-02-29[u-ca=japanese][!u-ca=hebrew]',
  '2024-02-29[Europe/Paris][u-ca=hebrew]', '2024-02-29[u-ca=hebrew][Europe/Paris]', '2024-02-29[Europe/Paris][America/New_York]',
  '2024-02-29[+01:00]', '2024-02-29[FOO=bar]', '2024-02-29[u-ca=]', '2024-02-29[u-ca=bogus]',
  '2024-02-30', '2024-13-01', '2024-02-29T25:00', '2024-02-29T12:00:00.1234567891',
  '2024-02-29T12:00Z[UTC]', ' 2024-02-29', '2024−02-29', '', '2024-02', '02-29',
  '2024-02-29T12:00:00-00:00', '2024-02-29T12:00:00+23:59:59.999999999', '2024-02-29T12:00:00+24:00',
  '2024-02-29T12:00:00.', '2024-02-29T12:60', '2024-02-29T12:00+053000', '2024-02-29T12:00+05:60', '2024-02-29[+05:60]',
  '2024-02-29[1abc]', '2024-02-29[Europe/Paris', '2024-02-29T12:00:00+05:30:00.5[Asia/Kolkata]',
]) t(JSON.stringify(s), () => P.from(s));
''')


def test_plain_date_property_bags(run, workdir):
    """CATCHES: property-bag conversion ignoring overflow 'constrain'/'reject', month/monthCode consistency checks, missing-field TypeErrors, monthCode syntax validation, and the wrong error type for bad overflow values or non-object inputs."""
    check(run, workdir, "plain_date_property_bags", r'''
const P = Temporal.PlainDate;
t('constrain month/day', () => P.from({ year: 2024, month: 13, day: 40 }));
t('constrain feb', () => P.from({ year: 2023, month: 2, day: 31 }, { overflow: 'constrain' }));
t('reject month', () => P.from({ year: 2024, month: 13, day: 1 }, { overflow: 'reject' }));
t('reject day', () => P.from({ year: 2023, month: 2, day: 29 }, { overflow: 'reject' }));
t('monthCode', () => P.from({ year: 2024, monthCode: 'M02', day: 30 }));
t('month+monthCode agree', () => P.from({ year: 2024, month: 2, monthCode: 'M02', day: 1 }));
t('month+monthCode disagree', () => P.from({ year: 2024, month: 3, monthCode: 'M02', day: 1 }));
t('bad monthCode', () => P.from({ year: 2024, monthCode: 'M13', day: 1 }));
t('leap monthCode in iso', () => P.from({ year: 2024, monthCode: 'M02L', day: 1 }));
t('monthCode syntax', () => P.from({ year: 2024, monthCode: '2', day: 1 }));
t('monthCode number', () => P.from({ year: 2024, monthCode: 2, day: 1 }));
t('missing month', () => P.from({ year: 2024, day: 30 }));
t('missing year', () => P.from({ month: 1, day: 30 }));
t('missing day', () => P.from({ year: 2024, month: 1 }));
t('day 0', () => P.from({ year: 2024, month: 1, day: 0 }));
t('negative month', () => P.from({ year: 2024, month: -1, day: 1 }));
t('fractional fields', () => P.from({ year: 2024.9, month: 2.5, day: 3.99 }));
t('infinite day', () => P.from({ year: 2024, month: 1, day: Infinity }));
t('string values', () => P.from({ year: '2024', month: '6', day: '7' }));
t('bad overflow', () => P.from({ year: 2024, month: 1, day: 1 }, { overflow: 'foo' }));
t('options not object', () => P.from({ year: 2024, month: 1, day: 1 }, 'reject'));
t('options null', () => P.from({ year: 2024, month: 1, day: 1 }, null));
t('number', () => P.from(20240101));
t('null', () => P.from(null));
t('undefined', () => P.from(undefined));
t('from PlainDateTime', () => P.from(Temporal.PlainDateTime.from('2024-05-05T10:00')));
t('from ZonedDateTime', () => P.from(Temporal.ZonedDateTime.from('2024-05-05T23:30-04:00[America/New_York]')));
t('from PlainDate copies', () => { const a = new P(2024, 1, 1); const b = P.from(a); return `${a !== b} ${b}`; });
t('string still validates overflow', () => P.from('2024-01-01', { overflow: 'bogus' }));
t('calendar in bag', () => P.from({ year: 5784, month: 1, day: 1, calendar: 'hebrew' }).toString());
t('bad calendar in bag', () => P.from({ year: 2024, month: 1, day: 1, calendar: 'nope' }));
t('field read order', () => {
  const log = [];
  const bag = new Proxy({ year: 2024, month: 2, day: 3 }, { get(o, k) { if (typeof k === 'string') log.push(k); return o[k]; } });
  P.from(bag);
  return log.join(',');
});
''')


def test_plain_date_getters_week_numbering(run, workdir):
    """CATCHES: ISO week-date bugs (weekOfYear/yearOfWeek at year boundaries, 53-week years), wrong dayOfWeek/dayOfYear, daysInMonth/daysInYear/inLeapYear for century years, and era/eraYear leaking for the iso8601 calendar."""
    check(run, workdir, "plain_date_getters_week_numbering", r'''
const fields = (d) => [d.year, d.month, d.monthCode, d.day, d.dayOfWeek, d.dayOfYear, d.weekOfYear, d.yearOfWeek,
  d.daysInWeek, d.daysInMonth, d.daysInYear, d.monthsInYear, d.inLeapYear, String(d.era), String(d.eraYear), d.calendarId].join(' ');
for (const s of ['2024-12-30', '2021-01-01', '2020-12-31', '2026-01-01', '2027-01-03', '2015-12-31',
  '1900-02-15', '2000-02-15', '2100-12-31', '-000001-06-15', '0000-01-01', '1970-01-01', '2024-07-04'])
  t(s, () => fields(Temporal.PlainDate.from(s)));
t('getter brand check', () => Object.getOwnPropertyDescriptor(Temporal.PlainDate.prototype, 'year').get.call({}));
t('getter on PlainDateTime', () => Object.getOwnPropertyDescriptor(Temporal.PlainDate.prototype, 'dayOfWeek').get.call(Temporal.PlainDateTime.from('2024-01-01T00:00')));
''')


def test_plain_date_with_add_subtract(run, workdir):
    """CATCHES: with() accepting calendar/timeZone/empty bags, add/subtract month-end clamping vs overflow 'reject', week/day balancing, time units in date add, and out-of-range results not throwing."""
    check(run, workdir, "plain_date_with_add_subtract", r'''
const d = Temporal.PlainDate.from('2024-01-31');
t('with day', () => d.with({ day: 15 }));
t('with month constrain', () => d.with({ month: 2 }));
t('with month reject', () => d.with({ month: 2 }, { overflow: 'reject' }));
t('with monthCode', () => d.with({ monthCode: 'M04' }));
t('with year', () => Temporal.PlainDate.from('2024-02-29').with({ year: 2023 }));
t('with empty', () => d.with({}));
t('with calendar', () => d.with({ calendar: 'iso8601' }));
t('with timeZone', () => d.with({ timeZone: 'UTC' }));
t('with string', () => d.with('2024-05-05'));
t('with PlainDate', () => d.with(Temporal.PlainDate.from('2020-01-01')));
t('with negative day', () => d.with({ day: -1 }));
t('with unknown only', () => d.with({ hour: 3 }));
t('add 1 month', () => d.add({ months: 1 }));
t('add 1 month reject', () => d.add({ months: 1 }, { overflow: 'reject' }));
t('add P1Y1M1W1D', () => d.add('P1Y1M1W1D'));
t('add 36h (time balances to days)', () => d.add({ hours: 36 }));
t('add -1 day', () => d.add({ days: -1 }));
t('add Duration', () => d.add(Temporal.Duration.from({ weeks: 52 })));
t('subtract 1 month', () => Temporal.PlainDate.from('2024-03-31').subtract({ months: 1 }));
t('subtract P1Y from leap day', () => Temporal.PlainDate.from('2024-02-29').subtract('P1Y'));
t('subtract negative', () => d.subtract({ days: -366 }));
t('add bad', () => d.add({}));
t('add bad string', () => d.add('1 day'));
t('add out of range', () => Temporal.PlainDate.from('+275760-09-13').add({ days: 1 }));
t('subtract out of range', () => Temporal.PlainDate.from('-271821-04-19').subtract({ days: 1 }));
t('add huge years', () => d.add({ years: 300000 }));
t('add bad overflow', () => d.add({ days: 1 }, { overflow: 'nope' }));
t('add mixed signs', () => d.add({ days: 1, months: -1 }));
t('add -36h truncates toward zero', () => d.add({ hours: -36 }));
t('with month 0', () => d.with({ month: 0 }));
t('with monthCode number', () => d.with({ monthCode: 1 }));
t('with monthCode bad', () => d.with({ monthCode: 'M1' }));
t('with year out of range', () => d.with({ year: 275761 }));
''')


def test_plain_date_until_since(run, workdir):
    """CATCHES: date difference bugs: month-end anchoring, largestUnit year/month/week/day, smallestUnit rounding with roundingIncrement/roundingMode (incl. since() negating the mode), invalid unit combinations, and time units rejected for dates."""
    check(run, workdir, "plain_date_until_since", r'''
const a = Temporal.PlainDate.from('2020-01-31');
const b = Temporal.PlainDate.from('2024-03-01');
t('until default', () => a.until(b));
t('since default', () => a.since(b));
t('until years', () => a.until(b, { largestUnit: 'years' }));
t('until months', () => a.until(b, { largestUnit: 'month' }));
t('until weeks', () => a.until(b, { largestUnit: 'weeks' }));
t('since years', () => b.since(a, { largestUnit: 'year' }));
t('jan31 -> feb29 months', () => a.with({ year: 2024 }).until('2024-02-29', { largestUnit: 'months' }));
t('jan31 -> mar1 months', () => Temporal.PlainDate.from('2024-01-31').until('2024-03-01', { largestUnit: 'months' }));
t('round to years halfExpand', () => a.until(b, { smallestUnit: 'years' }));
t('round to months trunc', () => a.until(b, { smallestUnit: 'months', roundingMode: 'trunc' }));
t('round to months ceil', () => a.until(b, { smallestUnit: 'months', roundingMode: 'ceil' }));
t('since months floor', () => a.since(b, { smallestUnit: 'months', roundingMode: 'floor' }));
t('since months ceil', () => a.since(b, { smallestUnit: 'months', roundingMode: 'ceil' }));
t('weeks increment 4', () => a.until(b, { smallestUnit: 'weeks', roundingIncrement: 4 }));
t('days increment 10', () => a.until(b, { smallestUnit: 'days', roundingIncrement: 10, roundingMode: 'halfEven' }));
t('years largest, months smallest', () => a.until(b, { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'expand' }));
t('largest < smallest', () => a.until(b, { largestUnit: 'months', smallestUnit: 'years' }));
t('time unit', () => a.until(b, { largestUnit: 'hours' }));
t('smallest time unit', () => a.until(b, { smallestUnit: 'seconds' }));
t('bad unit', () => a.until(b, { largestUnit: 'fortnight' }));
t('bad mode', () => a.until(b, { smallestUnit: 'days', roundingMode: 'up' }));
t('increment 0', () => a.until(b, { roundingIncrement: 0 }));
t('increment 1e9+1', () => a.until(b, { roundingIncrement: 1e9 + 1 }));
t('increment NaN', () => a.until(b, { roundingIncrement: NaN }));
t('auto largest', () => a.until(b, { largestUnit: 'auto', smallestUnit: 'months' }));
t('same date', () => a.until(a));
t('until string', () => a.until('2020-02-29'));
t('until bag', () => a.until({ year: 2020, month: 2, day: 1 }));
t('until different calendar', () => a.until(Temporal.PlainDate.from('2020-02-01[u-ca=hebrew]')));
t('until PlainDateTime', () => a.until(Temporal.PlainDateTime.from('2020-02-01T23:00')));
t('options string', () => a.until(b, 'years'));
''')


def test_plain_date_compare_equals_tostring(run, workdir):
    """CATCHES: compare/equals ignoring calendars or not converting strings/bags, valueOf not throwing, relational operators silently working, and toString calendarName option handling (auto/always/never/critical)."""
    check(run, workdir, "plain_date_compare_equals_tostring", r'''
const P = Temporal.PlainDate;
const a = P.from('2024-01-01'), b = P.from('2024-01-02');
t('compare a b', () => P.compare(a, b));
t('compare b a', () => P.compare(b, a));
t('compare equal', () => P.compare(a, '2024-01-01'));
t('compare bag', () => P.compare({ year: 2024, month: 1, day: 1 }, a));
t('compare ignores calendar', () => P.compare(a, a.withCalendar('hebrew')));
t('equals same', () => a.equals('2024-01-01'));
t('equals different calendar', () => a.equals(a.withCalendar('gregory')));
t('sort', () => ['2024-03-01', '2023-12-31', '2024-01-15'].map((s) => P.from(s)).sort(P.compare).join(' '));
t('valueOf', () => a.valueOf());
t('less-than operator', () => a < b);
t('string concat', () => `${a}`);
t('toJSON', () => JSON.stringify({ d: a }));
t('toString auto', () => a.toString());
t('toString always', () => a.toString({ calendarName: 'always' }));
t('toString never on hebrew', () => a.withCalendar('hebrew').toString({ calendarName: 'never' }));
t('toString critical', () => a.withCalendar('hebrew').toString({ calendarName: 'critical' }));
t('toString auto on gregory', () => a.withCalendar('gregory').toString());
t('toString bad calendarName', () => a.toString({ calendarName: 'bogus' }));
t('toString options not object', () => a.toString('always'));
t('toString brand', () => P.prototype.toString.call({}));
t('toJSON brand', () => P.prototype.toJSON.call(Temporal.PlainTime.from('12:00')));
t('equals brand arg', () => a.equals(42));
''')


def test_plain_date_conversions(run, workdir):
    """CATCHES: PlainDate conversion bugs: toPlainDateTime with/without time, toPlainYearMonth/toPlainMonthDay, toZonedDateTime with string vs options bag (timeZone + plainTime), and DST-gap start-of-day resolution."""
    check(run, workdir, "plain_date_conversions", r'''
const d = Temporal.PlainDate.from('2024-03-10');
t('toPlainDateTime()', () => d.toPlainDateTime());
t('toPlainDateTime(time)', () => d.toPlainDateTime('13:45:01.5'));
t('toPlainDateTime(bag)', () => d.toPlainDateTime({ hour: 7 }));
t('toPlainDateTime(bad)', () => d.toPlainDateTime('25:00'));
t('toPlainYearMonth', () => d.toPlainYearMonth());
t('toPlainMonthDay', () => d.toPlainMonthDay());
t('toZonedDateTime string', () => d.toZonedDateTime('America/New_York'));
t('toZonedDateTime bag', () => d.toZonedDateTime({ timeZone: 'America/New_York', plainTime: '02:30' }));
t('toZonedDateTime no time', () => d.toZonedDateTime({ timeZone: 'Europe/London' }));
t('toZonedDateTime missing tz', () => d.toZonedDateTime({}));
t('toZonedDateTime bad tz', () => d.toZonedDateTime('Mars/Olympus'));
t('toZonedDateTime offset tz', () => d.toZonedDateTime('+05:30'));
t('toZonedDateTime min date midnight', () => Temporal.PlainDate.from('-271821-04-19').toZonedDateTime({ timeZone: 'UTC', plainTime: '00:00' }));
t('Apia skipped day start', () => Temporal.PlainDate.from('2011-12-30').toZonedDateTime('Pacific/Apia'));
t('withCalendar', () => d.withCalendar('japanese').toString());
t('withCalendar missing', () => d.withCalendar());
t('withCalendar object', () => d.withCalendar({}));
t('withCalendar PlainDate', () => d.withCalendar(Temporal.PlainDate.from('2000-01-01[u-ca=buddhist]')).toString());
t('withCalendar iso string', () => d.withCalendar('2000-01-01[u-ca=roc]').toString());
''')


def test_plain_time_construct_and_from(run, workdir):
    """CATCHES: PlainTime constructor/from() bugs: field range checks, overflow constrain vs reject in bags, time-only strings (T-prefixed, basic format), rejection of date-only or Z strings, ambiguous strings that look like dates, and leap second handling."""
    check(run, workdir, "plain_time_construct_and_from", r'''
const T = Temporal.PlainTime;
t('ctor', () => new T(13, 37, 5, 123, 456, 789));
t('ctor default', () => new T());
t('ctor hour 24', () => new T(24));
t('ctor neg', () => new T(0, -1));
t('ctor ms 1000', () => new T(0, 0, 0, 1000));
t('getters', () => { const x = new T(1, 2, 3, 4, 5, 6); return [x.hour, x.minute, x.second, x.millisecond, x.microsecond, x.nanosecond, String(x.calendarId)]; });
for (const s of ['12:34', '12:34:56.789', 'T12:34', 't1234', '123456', '12:34:60', '1234:56', '12:34Z',
  '12:34+01:00', '2024-01-01T12:34', '2024-01-01', '12-14', '2021-12', '1214', '202112', 'T1214',
  '12:34[u-ca=iso8601]', '12:34[u-ca=hebrew]', '12:34[!u-ca=hebrew]', '24:00', '12:34:56.1234567890',
  '2024-01-01T12:00Z', '12:34:56,5'])
  t(JSON.stringify(s), () => T.from(s));
t('bag constrain', () => T.from({ hour: 25, minute: 70, second: 61, millisecond: 1001, microsecond: -1, nanosecond: 5000 }));
t('bag reject', () => T.from({ hour: 25 }, { overflow: 'reject' }));
t('bag negative reject', () => T.from({ minute: -1 }, { overflow: 'reject' }));
t('bag empty', () => T.from({}));
t('bag unrelated', () => T.from({ hours: 1 }));
t('from PlainDateTime', () => T.from(Temporal.PlainDateTime.from('2020-01-01T05:06:07')));
t('from ZonedDateTime', () => T.from(Temporal.ZonedDateTime.from('2020-01-01T05:06:07+09:00[Asia/Tokyo]')));
t('from number', () => T.from(1234));
''')


def test_plain_time_with_add_round(run, workdir):
    """CATCHES: PlainTime wrap-around arithmetic, with() overflow, round() unit/increment validation and each roundingMode (including negative-free halfEven/halfTrunc ties), and until/since with largestUnit/smallestUnit."""
    check(run, workdir, "plain_time_with_add_round", r'''
const x = Temporal.PlainTime.from('23:59:59.999999999');
t('add 1ns wraps', () => x.add({ nanoseconds: 1 }));
t('add P1D ignored days', () => x.add('P1D'));
t('subtract 25h', () => Temporal.PlainTime.from('01:00').subtract({ hours: 25 }));
t('with minute', () => x.with({ minute: 0 }));
t('with constrain', () => x.with({ hour: 99 }));
t('with reject', () => x.with({ hour: 99 }, { overflow: 'reject' }));
t('with empty', () => x.with({}));
const y = Temporal.PlainTime.from('12:34:56.5');
for (const mode of ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'])
  t('round second ' + mode, () => y.round({ smallestUnit: 'second', roundingMode: mode }));
t('round hour', () => y.round('hour'));
t('round minute incr 15', () => y.round({ smallestUnit: 'minutes', roundingIncrement: 15 }));
t('round minute incr 7', () => y.round({ smallestUnit: 'minute', roundingIncrement: 7 }));
t('round hour incr 12 up', () => Temporal.PlainTime.from('18:00').round({ smallestUnit: 'hour', roundingIncrement: 12 }));
t('round ns incr 500', () => Temporal.PlainTime.from('00:00:00.000000250').round({ smallestUnit: 'nanosecond', roundingIncrement: 500 }));
t('round no unit', () => y.round({}));
t('round day', () => y.round('day'));
t('round undefined', () => y.round());
t('round bad', () => y.round('years'));
const a = Temporal.PlainTime.from('08:15:30'), b = Temporal.PlainTime.from('17:45:10.25');
t('until', () => a.until(b));
t('since', () => a.since(b));
t('until minutes', () => a.until(b, { largestUnit: 'minutes' }));
t('until seconds round', () => a.until(b, { smallestUnit: 'seconds', roundingMode: 'halfExpand' }));
t('until hour incr 2', () => a.until(b, { smallestUnit: 'hours', roundingIncrement: 2 }));
t('since minute floor', () => a.since(b, { smallestUnit: 'minute', roundingMode: 'floor' }));
t('until days', () => a.until(b, { largestUnit: 'days' }));
t('equals', () => a.equals('08:15:30.000'));
t('compare', () => Temporal.PlainTime.compare(b, a) + ' ' + Temporal.PlainTime.compare(a, '08:15:30'));
t('valueOf', () => a.valueOf());
''')


def test_plain_time_tostring_options(run, workdir):
    """CATCHES: PlainTime/PlainDateTime toString precision bugs: fractionalSecondDigits 0..9/auto, smallestUnit minute/second/ms/us/ns overriding digits, roundingMode applied to the display (carry into the date), and invalid option RangeErrors."""
    check(run, workdir, "plain_time_tostring_options", r'''
const x = Temporal.PlainTime.from('09:05:07.123456789');
for (const d of [0, 1, 3, 5, 9, 'auto']) t('fsd ' + d, () => x.toString({ fractionalSecondDigits: d }));
for (const u of ['minute', 'second', 'millisecond', 'microsecond', 'nanosecond']) t('smallestUnit ' + u, () => x.toString({ smallestUnit: u }));
t('smallestUnit wins over digits', () => x.toString({ smallestUnit: 'second', fractionalSecondDigits: 9 }));
t('fsd 2 halfExpand', () => x.toString({ fractionalSecondDigits: 2, roundingMode: 'halfExpand' }));
t('fsd 0 ceil', () => x.toString({ fractionalSecondDigits: 0, roundingMode: 'ceil' }));
t('fsd 10', () => x.toString({ fractionalSecondDigits: 10 }));
t('fsd -1', () => x.toString({ fractionalSecondDigits: -1 }));
t('fsd 2.7', () => x.toString({ fractionalSecondDigits: 2.7 }));
t('fsd "3"', () => x.toString({ fractionalSecondDigits: '3' }));
t('fsd NaN', () => x.toString({ fractionalSecondDigits: NaN }));
t('smallestUnit hour', () => x.toString({ smallestUnit: 'hour' }));
t('smallestUnit bad', () => x.toString({ smallestUnit: 'jiffy' }));
t('roundingMode bad', () => x.toString({ roundingMode: 'nearest' }));
t('auto trims zeros', () => Temporal.PlainTime.from('09:05:07.100').toString());
t('zero seconds kept', () => Temporal.PlainTime.from('09:05').toString());
t('JSON', () => JSON.stringify(x));
const dt = Temporal.PlainDateTime.from('1999-12-31T23:59:59.999');
t('pdt carry into next year', () => dt.toString({ smallestUnit: 'second', roundingMode: 'halfExpand' }));
t('pdt minute ceil', () => dt.toString({ smallestUnit: 'minute', roundingMode: 'ceil' }));
t('pdt fsd 1 trunc', () => dt.toString({ fractionalSecondDigits: 1 }));
t('pdt calendarName always', () => dt.toString({ calendarName: 'always' }));
t('pdt calendar critical', () => dt.withCalendar('roc').toString({ calendarName: 'critical', smallestUnit: 'minute' }));
t('pdt max carry out of range', () => Temporal.PlainDateTime.from('+275760-09-13T23:59:59.999').toString({ smallestUnit: 'second', roundingMode: 'ceil' }));
''')


def test_plain_datetime_construct_from(run, workdir):
    """CATCHES: PlainDateTime constructor/from() bugs: field validation, time defaults, string forms with offsets and annotations (Z rejected), property bags with overflow, range limits at the edges of the representable range, and the full set of getters."""
    check(run, workdir, "plain_datetime_construct_from", r'''
const PDT = Temporal.PlainDateTime;
t('ctor full', () => new PDT(2024, 2, 29, 23, 59, 59, 999, 999, 999));
t('ctor date only', () => new PDT(2024, 2, 29));
t('ctor bad hour', () => new PDT(2024, 2, 29, 24));
t('ctor calendar', () => new PDT(2024, 2, 29, 0, 0, 0, 0, 0, 0, 'japanese').toString());
t('min edge', () => new PDT(-271821, 4, 19, 0, 0, 0, 0, 0, 1));
t('below min', () => new PDT(-271821, 4, 19, 0, 0, 0, 0, 0, 0));
t('max edge', () => new PDT(275760, 9, 13, 23, 59, 59, 999, 999, 999));
for (const s of ['2024-02-29T12:34:56.5', '2024-02-29', '20240229T123456', '2024-02-29T12:34:56+09:00[Asia/Tokyo]',
  '2024-02-29T12:34:56Z', '2024-02-29T12:34:56.000000001[u-ca=hebrew]', '2024-02-29T24:00', '-271821-04-19T00:00',
  '-271821-04-19T00:00:00.000000001', '+275760-09-13T23:59', '+275760-09-14T00:00'])
  t(JSON.stringify(s), () => PDT.from(s));
t('bag', () => PDT.from({ year: 2024, month: 2, day: 29, hour: 25, minute: 61 }));
t('bag reject', () => PDT.from({ year: 2024, month: 2, day: 29, hour: 25 }, { overflow: 'reject' }));
t('bag missing day', () => PDT.from({ year: 2024, month: 2, hour: 1 }));
t('from PlainDate', () => PDT.from(Temporal.PlainDate.from('2024-01-01')));
t('from ZonedDateTime', () => PDT.from(Temporal.ZonedDateTime.from('2024-01-01T00:00:00.5+05:45[Asia/Kathmandu]')));
const x = PDT.from('2024-12-31T18:07:09.010203040');
t('getters', () => [x.year, x.month, x.monthCode, x.day, x.hour, x.minute, x.second, x.millisecond, x.microsecond,
  x.nanosecond, x.dayOfWeek, x.dayOfYear, x.weekOfYear, x.yearOfWeek, x.daysInMonth, x.daysInYear, x.inLeapYear, x.calendarId].join(' '));
t('valueOf', () => x.valueOf());
t('compare', () => PDT.compare(x, '2024-12-31T18:07:09.01020304') + ' ' + PDT.compare('2025-01-01', x));
t('equals calendar', () => x.equals(x.withCalendar('gregory')));
''')


def test_plain_datetime_arithmetic_and_round(run, workdir):
    """CATCHES: PlainDateTime add/subtract time carries into the date, month-end clamping with time, until/since rounding across day boundaries with every largestUnit, round() to day/hour with increments, and RangeErrors for bad increments."""
    check(run, workdir, "plain_datetime_arithmetic_and_round", r'''
const x = Temporal.PlainDateTime.from('2024-01-31T22:30:00');
t('add PT2H', () => x.add('PT2H'));
t('add P1M', () => x.add('P1M'));
t('add P1M reject', () => x.add('P1M', { overflow: 'reject' }));
t('subtract PT23H', () => x.subtract({ hours: 23, minutes: 31 }));
t('add mixed', () => x.add({ years: 1, months: 1, weeks: 1, days: 1, hours: 1, minutes: 1, seconds: 1, milliseconds: 1, microseconds: 1, nanoseconds: 1 }));
t('with', () => x.with({ day: 1, hour: 3 }));
t('withPlainTime', () => x.withPlainTime('04:05'));
t('withPlainTime none', () => x.withPlainTime());
t('toPlainDate/toPlainTime', () => `${x.toPlainDate()} ${x.toPlainTime()}`);
const y = Temporal.PlainDateTime.from('2025-03-01T01:15:30.5');
t('until', () => x.until(y));
t('until years', () => x.until(y, { largestUnit: 'years' }));
t('until months', () => x.until(y, { largestUnit: 'months' }));
t('until weeks', () => x.until(y, { largestUnit: 'weeks' }));
t('until hours', () => x.until(y, { largestUnit: 'hours' }));
t('until ns', () => x.until(y, { largestUnit: 'nanoseconds' }));
t('until smallest day', () => x.until(y, { smallestUnit: 'days' }));
t('until smallest month halfExpand', () => x.until(y, { largestUnit: 'years', smallestUnit: 'months' }));
t('since smallest hour ceil', () => x.since(y, { smallestUnit: 'hours', roundingMode: 'ceil' }));
t('since smallest minute incr 30', () => x.since(y, { smallestUnit: 'minutes', roundingIncrement: 30 }));
t('until bad incr', () => x.until(y, { smallestUnit: 'minutes', roundingIncrement: 7 }));
t('round day', () => x.round('day'));
t('round day incr 2', () => x.round({ smallestUnit: 'day', roundingIncrement: 2 }));
t('round hour incr 6', () => x.round({ smallestUnit: 'hour', roundingIncrement: 6, roundingMode: 'floor' }));
t('round ms', () => y.round({ smallestUnit: 'millisecond', roundingIncrement: 250 }));
t('round second halfEven', () => y.round({ smallestUnit: 'second', roundingMode: 'halfEven' }));
t('round month', () => x.round('month'));
t('round increment 1000ms', () => y.round({ smallestUnit: 'millisecond', roundingIncrement: 1000 }));
''')


def test_plain_datetime_to_zoned(run, workdir):
    """CATCHES: PlainDateTime.toZonedDateTime disambiguation bugs in DST gaps and folds (compatible/earlier/later/reject), invalid disambiguation values, and wrong offsets in the resulting ZonedDateTime string."""
    check(run, workdir, "plain_datetime_to_zoned", r'''
const gap = Temporal.PlainDateTime.from('2024-03-10T02:30');
const fold = Temporal.PlainDateTime.from('2024-11-03T01:30');
for (const dis of ['compatible', 'earlier', 'later', 'reject']) {
  t('gap ' + dis, () => gap.toZonedDateTime('America/New_York', { disambiguation: dis }));
  t('fold ' + dis, () => fold.toZonedDateTime('America/New_York', { disambiguation: dis }));
}
t('bad disambiguation', () => gap.toZonedDateTime('America/New_York', { disambiguation: 'latest' }));
t('default', () => gap.toZonedDateTime('America/New_York'));
t('missing tz', () => gap.toZonedDateTime());
t('tz object', () => gap.toZonedDateTime({}));
t('UTC', () => gap.toZonedDateTime('UTC'));
t('offset zone', () => gap.toZonedDateTime('-03:30'));
t('london fold later', () => Temporal.PlainDateTime.from('2024-10-27T01:30').toZonedDateTime('Europe/London', { disambiguation: 'later' }));
''')


def test_plain_year_month(run, workdir):
    """CATCHES: PlainYearMonth bugs: reference-day handling in strings/bags, getters (daysInMonth, inLeapYear), add/subtract of months/years (and rejection of smaller units), until/since in years/months with rounding, toPlainDate with a day, and calendar annotation rules for non-ISO strings."""
    check(run, workdir, "plain_year_month", r'''
const YM = Temporal.PlainYearMonth;
t('ctor', () => new YM(2024, 2));
t('ctor ref day', () => new YM(2024, 2, 'iso8601', 15).toString({ calendarName: 'always' }));
t('ctor bad month', () => new YM(2024, 13));
for (const s of ['2024-02', '202402', '+002024-02', '2024-02-29', '2024-02-29T12:00', '2024-02[u-ca=iso8601]',
  '2024-02[u-ca=hebrew]', '2024-02-01[u-ca=hebrew]', '2024-13', '-271821-04', '-271821-03', '+275760-09', '+275760-10', '2024-02Z'])
  t(JSON.stringify(s), () => YM.from(s));
t('bag', () => YM.from({ year: 2024, month: 14 }));
t('bag reject', () => YM.from({ year: 2024, month: 14 }, { overflow: 'reject' }));
t('bag monthCode', () => YM.from({ year: 2024, monthCode: 'M07' }));
t('bag missing year', () => YM.from({ month: 3 }));
const ym = YM.from('2024-01');
t('getters', () => [ym.year, ym.month, ym.monthCode, ym.daysInMonth, ym.daysInYear, ym.monthsInYear, ym.inLeapYear, String(ym.era), ym.calendarId].join(' '));
t('add months', () => ym.add({ months: 13 }));
t('add years', () => ym.add('P2Y'));
t('subtract months', () => ym.subtract({ months: 1 }));
t('add days', () => ym.add({ days: 40 }));
t('add weeks', () => ym.add({ weeks: 1 }));
t('add hours', () => ym.add({ hours: 1 }));
t('add negative days', () => ym.add({ days: -1 }));
t('with', () => ym.with({ month: 12 }));
t('with year', () => ym.with({ year: 1999 }));
t('until', () => ym.until('2026-07'));
t('until months', () => ym.until('2026-07', { largestUnit: 'months' }));
t('since years round', () => ym.since('2021-08', { smallestUnit: 'years', roundingMode: 'halfExpand' }));
t('until weeks', () => ym.until('2026-07', { largestUnit: 'weeks' }));
t('until days', () => ym.until('2026-07', { smallestUnit: 'days' }));
t('toPlainDate', () => ym.toPlainDate({ day: 31 }));
t('toPlainDate constrain', () => YM.from('2023-02').toPlainDate({ day: 31 }));
t('toPlainDate missing', () => ym.toPlainDate({}));
t('toPlainDate none', () => ym.toPlainDate());
t('compare', () => YM.compare('2024-01', '2023-12') + ' ' + YM.compare(ym, { year: 2024, month: 1 }));
t('equals', () => ym.equals('2024-01-31'));
t('toJSON', () => ym.toJSON());
t('valueOf', () => ym.valueOf());
t('toString calendarName always', () => ym.toString({ calendarName: 'always' }));
''')


def test_plain_month_day(run, workdir):
    """CATCHES: PlainMonthDay bugs: Feb 29 accepted with the leap reference year 1972, --MM-DD and MMDD string forms, year used only for validation in bags, toPlainDate constraining Feb 29 in common years, and equals/toString with reference years."""
    check(run, workdir, "plain_month_day", r'''
const MD = Temporal.PlainMonthDay;
t('ctor', () => new MD(2, 29));
t('ctor ref year', () => new MD(2, 29, 'iso8601', 2000).toString({ calendarName: 'always' }));
t('ctor bad', () => new MD(2, 30));
t('ctor bad ref', () => new MD(2, 29, 'iso8601', 2001));
for (const s of ['-02-29', '--2-29', '-0229', '02-29', '--02-29', '0229', '--0229', '2024-02-29', '2023-02-29', '12-31T10:00', '02-29[u-ca=iso8601]',
  '02-29[u-ca=hebrew]', '2024-02-29[u-ca=hebrew]', '13-01', '1972-02-29T00:00Z', '-271821-01-01', '+275760-12-31'])
  t(JSON.stringify(s), () => MD.from(s));
t('bag monthCode', () => MD.from({ monthCode: 'M02', day: 29 }));
t('bag month needs year', () => MD.from({ month: 2, day: 29 }));
t('bag year month day', () => MD.from({ year: 2023, month: 2, day: 29 }));
t('bag year reject', () => MD.from({ year: 2023, month: 2, day: 29 }, { overflow: 'reject' }));
t('bag leap year reject', () => MD.from({ year: 2024, month: 2, day: 29 }, { overflow: 'reject' }));
t('bag day 32', () => MD.from({ monthCode: 'M01', day: 32 }));
t('bag missing day', () => MD.from({ monthCode: 'M01' }));
const md = MD.from('02-29');
t('getters', () => [md.monthCode, md.day, String(md.month), md.calendarId].join(' '));
t('toPlainDate 2023', () => md.toPlainDate({ year: 2023 }));
t('toPlainDate 2024', () => md.toPlainDate({ year: 2024 }));
t('toPlainDate missing', () => md.toPlainDate({}));
t('with day', () => md.with({ day: 1 }));
t('with monthCode', () => md.with({ monthCode: 'M04', day: 31 }));
t('with month', () => md.with({ month: 4 }));
t('with year', () => md.with({ year: 2021 }));
t('equals', () => md.equals('--02-29') + ' ' + md.equals(new MD(2, 29, 'iso8601', 2000)));
t('compare exists?', () => typeof MD.compare);
t('toJSON', () => md.toJSON());
t('valueOf', () => md.valueOf());
t('toString always', () => md.toString({ calendarName: 'always' }));
t('add exists?', () => typeof md.add);
''')


def test_plain_types_brand_and_shape(run, workdir):
    """CATCHES: missing brand checks across Temporal plain prototypes, wrong function lengths/names, non-configurable namespace properties, subclassing (new.target prototype) and Symbol.toStringTag values."""
    check(run, workdir, "plain_types_brand_and_shape", r'''
const kinds = ['PlainDate', 'PlainTime', 'PlainDateTime', 'PlainYearMonth', 'PlainMonthDay', 'Instant', 'ZonedDateTime', 'Duration'];
for (const k of kinds) {
  const C = Temporal[k];
  t(k + ' ctor', () => [C.name, C.length, typeof C.from, typeof C.compare, Object.prototype.toString.call(C.prototype)].join(' '));
  t(k + ' toString brand', () => C.prototype.toString.call(Temporal.PlainDate.prototype));
}
t('namespace tag', () => Object.prototype.toString.call(Temporal));
t('namespace keys', () => Object.getOwnPropertyNames(Temporal).sort().join(','));
t('PlainDate proto methods', () => Object.getOwnPropertyNames(Temporal.PlainDate.prototype).sort().join(','));
t('PlainTime proto methods', () => Object.getOwnPropertyNames(Temporal.PlainTime.prototype).sort().join(','));
class MyDate extends Temporal.PlainDate {
  hello() { return 'hello ' + this.toString(); }
}
t('subclass', () => { const m = new MyDate(2024, 5, 6); return [m instanceof MyDate, m.hello(), m.add({ days: 1 }) instanceof MyDate].join(' '); });
t('from on subclass', () => MyDate.from('2024-01-01') instanceof MyDate);
t('add length', () => Temporal.PlainDate.prototype.add.length + ' ' + Temporal.PlainDate.prototype.until.length);
t('year getter name', () => Object.getOwnPropertyDescriptor(Temporal.PlainDate.prototype, 'year').get.name);
''')


def test_plain_types_to_locale_string(run, workdir):
    """CATCHES: Temporal plain-type toLocaleString bugs: locale-dependent formatting of dates/times, dateStyle/timeStyle restrictions (TypeError for timeStyle on a date), option objects forwarded to Intl.DateTimeFormat, and calendar handling (YearMonth/MonthDay with the iso8601 calendar mismatch the gregory formatter). Pins the reference's limited CLDR data: en-GB full dates and fr-FR long dates use the en-US pattern."""
    check(run, workdir, "plain_types_to_locale_string", r'''
const d = Temporal.PlainDate.from('2024-07-04');
const tm = Temporal.PlainTime.from('15:07:08');
const dt = Temporal.PlainDateTime.from('2024-07-04T15:07:08');
t('date en-US', () => d.toLocaleString('en-US'));
t('date de-DE', () => d.toLocaleString('de-DE'));
t('date ja-JP', () => d.toLocaleString('ja-JP'));
t('date long', () => d.toLocaleString('en-GB', { dateStyle: 'full' }));
t('date month long', () => d.toLocaleString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' }));
t('date timeStyle', () => d.toLocaleString('en-US', { timeStyle: 'short' }));
t('time en-US', () => tm.toLocaleString('en-US'));
t('time de-DE', () => tm.toLocaleString('de-DE'));
t('time hour12 false', () => tm.toLocaleString('en-US', { hour12: false }));
t('time dateStyle', () => tm.toLocaleString('en-US', { dateStyle: 'short' }));
t('datetime en-US', () => dt.toLocaleString('en-US'));
t('datetime styles', () => dt.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }));
t('yearmonth', () => Temporal.PlainYearMonth.from('2024-07').toLocaleString('en-US'));
t('monthday', () => Temporal.PlainMonthDay.from('07-04').toLocaleString('en-US'));
t('date default locale', () => d.toLocaleString());
t('brand', () => Temporal.PlainDate.prototype.toLocaleString.call({}));
t('date hebrew calendar', () => d.withCalendar('hebrew').toLocaleString('en-US-u-ca-hebrew'));
t('date calendar mismatch', () => d.withCalendar('hebrew').toLocaleString('en-US'));
t('date timeZone option', () => d.toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
''')


def test_plain_with_methods_validation(run, workdir):
    """CATCHES: with() validation bugs on PlainDateTime/PlainYearMonth/PlainMonthDay/PlainTime: non-object or Temporal arguments, calendar/timeZone keys, zero/negative month or day, non-string or malformed monthCode, era/eraYear pairing rules, and monthCode replacing month."""
    check(run, workdir, "plain_with_methods_validation", r'''
const dt = Temporal.PlainDateTime.from('2024-05-31T10:00');
const ym = Temporal.PlainYearMonth.from('2024-05');
const md = Temporal.PlainMonthDay.from('05-31');
const tm = Temporal.PlainTime.from('10:00');
const cases = [
  ['string', '2024-01-01'], ['temporal', Temporal.PlainDate.from('2024-01-01')], ['calendar', { calendar: 'iso8601' }],
  ['timeZone', { timeZone: 'UTC' }], ['month 0', { month: 0 }], ['day 0', { day: 0 }], ['monthCode number', { monthCode: 3 }],
  ['monthCode bad', { monthCode: 'M3' }], ['monthCode M02', { monthCode: 'M02' }], ['monthCode M02 reject', { monthCode: 'M02' }, { overflow: 'reject' }],
  ['monthCode+month disagree', { month: 3, monthCode: 'M04' }], ['era only', { era: 'ce' }], ['empty', {}], ['year', { year: 2023 }],
];
for (const [name, obj] of [['PlainDateTime', dt], ['PlainYearMonth', ym], ['PlainMonthDay', md]]) {
  for (const [label, arg, opts] of cases) t(name + ' ' + label, () => obj.with(arg, opts));
}
t('PlainTime string', () => tm.with('11:00'));
t('PlainTime temporal', () => tm.with(Temporal.PlainTime.from('11:00')));
t('PlainTime calendar', () => tm.with({ calendar: 'iso8601', hour: 1 }));
t('PlainTime timeZone', () => tm.with({ timeZone: 'UTC', hour: 1 }));
t('PlainTime ns', () => tm.with({ nanosecond: 5, microsecond: 6, millisecond: 7 }));
const g = Temporal.PlainDateTime.from('2024-05-31T10:00[u-ca=gregory]');
t('gregory dt era+eraYear', () => g.with({ era: 'bce', eraYear: 5 }).toString());
t('gregory dt eraYear only', () => g.with({ eraYear: 5 }));
t('gregory dt era+eraYear+year', () => g.with({ era: 'ce', eraYear: 5, year: 5 }));
const gy = Temporal.PlainYearMonth.from({ year: 2024, month: 5, calendar: 'gregory' });
t('gregory ym era+eraYear', () => gy.with({ era: 'bce', eraYear: 5 }).toString());
t('gregory ym eraYear only', () => gy.with({ eraYear: 5 }));
t('gregory ym era+eraYear+year', () => gy.with({ era: 'ce', eraYear: 5, year: 5 }));
t('gregory ym monthCode', () => gy.with({ monthCode: 'M12' }).toString());
const gm = Temporal.PlainMonthDay.from({ monthCode: 'M02', day: 28, calendar: 'gregory' });
t('gregory md era+eraYear+day', () => gm.with({ era: 'ce', eraYear: 2024, day: 29 }).toString());
t('gregory md era only', () => gm.with({ era: 'ce' }));
t('gregory md with month and year', () => gm.with({ year: 2023, month: 2, day: 29 }).toString());
''')


def test_plain_range_limits(run, workdir):
    """CATCHES: missing representable-range checks: arithmetic and conversions that leave -271821-04-19..+275760-09-13 must throw RangeError (PlainDateTime add/subtract/with/round/withPlainTime, PlainDate.toPlainDateTime/toZonedDateTime, PlainYearMonth add, PlainMonthDay.toPlainDate). Pins a reference quirk: PlainYearMonth.with({year: 300000}) is NOT range-checked and yields +300000-01."""
    check(run, workdir, "plain_range_limits", r'''
const maxDT = Temporal.PlainDateTime.from('+275760-09-13T23:59:59.999999999');
const minDT = Temporal.PlainDateTime.from('-271821-04-19T00:00:00.000000001');
t('max dt + 1ns', () => maxDT.add({ nanoseconds: 1 }));
t('min dt - 1ns', () => minDT.subtract({ nanoseconds: 1 }));
t('add negative day onto min date', () => Temporal.PlainDateTime.from('-271821-04-20T00:00').add({ nanoseconds: -86400e9 }));
t('min dt round hour floor', () => minDT.round({ smallestUnit: 'hour', roundingMode: 'floor' }));
t('round number options', () => maxDT.round(5));
t('ym ctor above max', () => new Temporal.PlainYearMonth(275760, 10));
t('ym ctor below min', () => new Temporal.PlainYearMonth(-271821, 3));
t('min dt withPlainTime midnight', () => minDT.withPlainTime('00:00'));
t('max dt round day', () => maxDT.round('day'));
t('max dt round hour floor', () => maxDT.round({ smallestUnit: 'hour', roundingMode: 'floor' }));
t('min dt with hour 0', () => minDT.with({ nanosecond: 0 }));
t('min dt with day', () => minDT.with({ day: 18 }));
t('min date toPlainDateTime', () => Temporal.PlainDate.from('-271821-04-19').toPlainDateTime());
t('min date toPlainDateTime 00:00:01', () => Temporal.PlainDate.from('-271821-04-19').toPlainDateTime('00:00:01'));
t('min date toZonedDateTime UTC', () => Temporal.PlainDate.from('-271821-04-19').toZonedDateTime('UTC'));
t('min date toZonedDateTime +14', () => Temporal.PlainDate.from('-271821-04-20').toZonedDateTime('Pacific/Kiritimati'));
t('max date toZonedDateTime UTC', () => Temporal.PlainDate.from('+275760-09-13').toZonedDateTime('UTC'));
t('max dt toZonedDateTime', () => Temporal.PlainDateTime.from('+275760-09-13T00:00').toZonedDateTime('-01:00'));
t('max ym + 1 month', () => Temporal.PlainYearMonth.from('+275760-09').add({ months: 1 }));
t('min ym - 1 month', () => Temporal.PlainYearMonth.from('-271821-04').subtract({ months: 1 }));
t('ym bag at min', () => Temporal.PlainYearMonth.from({ year: -271821, month: 4 }));
t('ym bag below min', () => Temporal.PlainYearMonth.from({ year: -271821, month: 3 }));
t('ym bag above max', () => Temporal.PlainYearMonth.from({ year: 275760, month: 10 }));
t('ym bag huge year', () => Temporal.PlainYearMonth.from({ year: 1e9, month: 1 }));
t('ym with out of range', () => Temporal.PlainYearMonth.from('2024-01').with({ year: 300000 }));
t('ym until across range', () => Temporal.PlainYearMonth.from('-271821-04').until('+275760-09', { largestUnit: 'months' }));
t('md toPlainDate out of range', () => Temporal.PlainMonthDay.from('01-01').toPlainDate({ year: 275761 }));
t('md toPlainDate min', () => Temporal.PlainMonthDay.from('04-18').toPlainDate({ year: -271821 }));
t('date until extremes', () => Temporal.PlainDate.from('-271821-04-19').until('+275760-09-13', { largestUnit: 'years' }));
t('dt until extremes ns', () => minDT.until(maxDT, { largestUnit: 'nanoseconds' }));
t('dt since extremes weeks', () => maxDT.since(minDT, { largestUnit: 'weeks' }));
t('date from bag huge year', () => Temporal.PlainDate.from({ year: 1e10, month: 1, day: 1 }));
t('date from bag huge year reject', () => Temporal.PlainDate.from({ year: -1e10, month: 1, day: 1 }, { overflow: 'reject' }));
t('time add huge', () => Temporal.PlainTime.from('00:00').add({ hours: 1e15 }));
''')


def test_plain_conversion_errors(run, workdir):
    """CATCHES: from()/conversion error paths for PlainDateTime/PlainYearMonth/PlainMonthDay: unsupported calendar annotations, missing year/month/day fields, non-string calendar values, Temporal objects as calendar, and the exact cannot-convert TypeErrors."""
    check(run, workdir, "plain_conversion_errors", r'''
const PDT = Temporal.PlainDateTime, YM = Temporal.PlainYearMonth, MD = Temporal.PlainMonthDay;
for (const [name, C] of [['PlainDateTime', PDT], ['PlainYearMonth', YM], ['PlainMonthDay', MD]]) {
  t(name + ' number', () => C.from(5));
  t(name + ' null', () => C.from(null));
  t(name + ' bad calendar annotation', () => C.from('2024-05-06[u-ca=klingon]'));
  t(name + ' missing year', () => C.from({ month: 5, day: 6 }));
  t(name + ' missing month', () => C.from({ year: 2024, day: 6 }));
  t(name + ' missing day', () => C.from({ year: 2024, month: 5 }));
  t(name + ' calendar number', () => C.from({ year: 2024, month: 5, day: 6, calendar: 7 }));
  t(name + ' calendar object', () => C.from({ year: 2024, month: 5, day: 6, calendar: {} }));
  t(name + ' calendar Temporal', () => C.from({ year: 2024, month: 5, day: 6, calendar: Temporal.PlainDate.from('2024-01-01[u-ca=gregory]') }).toString());
  t(name + ' calendar ISO string', () => C.from({ year: 2024, month: 5, day: 6, calendar: '2024-01-01[u-ca=roc]' }).toString());
  t(name + ' month 0', () => C.from({ year: 2024, month: 0, day: 6 }));
  t(name + ' day 0', () => C.from({ year: 2024, month: 5, day: 0 }));
  t(name + ' monthCode object', () => C.from({ year: 2024, monthCode: { toString() { return 'M05'; } }, day: 6 }).toString());
  t(name + ' monthCode number', () => C.from({ year: 2024, monthCode: 5, day: 6 }));
  t(name + ' monthCode bad', () => C.from({ year: 2024, monthCode: 'M5', day: 6 }));
  t(name + ' calendarId brand', () => Object.getOwnPropertyDescriptor(C.prototype, 'calendarId').get.call({}));
  t(name + ' toJSON', () => C.from({ year: -12, month: 5, day: 6 }).toJSON());
}
t('PlainDate calendarId brand', () => Object.getOwnPropertyDescriptor(Temporal.PlainDate.prototype, 'calendarId').get.call(5));
t('PDT from PDT keeps calendar', () => PDT.from(PDT.from('2024-01-01T00:00[u-ca=japanese]')).calendarId);
t('PDT from PlainDate checks overflow', () => PDT.from(Temporal.PlainDate.from('2024-01-01'), { overflow: 'x' }));
t('YM from YM checks overflow', () => YM.from(YM.from('2024-01'), { overflow: 'x' }));
t('MD from MD checks overflow', () => MD.from(MD.from('01-01'), { overflow: 'x' }));
t('MD from string checks overflow', () => MD.from('01-01', { overflow: 'x' }));
t('MD from PlainDate', () => MD.from(Temporal.PlainDate.from('2024-02-29')).toString());
t('YM from PlainDate', () => YM.from(Temporal.PlainDate.from('2024-02-29')).toString());
t('MD toPlainDate number', () => MD.from('02-29').toPlainDate(2024));
t('MD toPlainDate era gregory', () => MD.from({ monthCode: 'M02', day: 29, calendar: 'gregory' }).toPlainDate({ era: 'ce', eraYear: 2023 }).toString());
t('MD toPlainDate era only', () => MD.from({ monthCode: 'M02', day: 29, calendar: 'gregory' }).toPlainDate({ era: 'ce' }));
t('YM toPlainDate number', () => YM.from('2024-02').toPlainDate(5));
''')


def test_plain_difference_option_errors(run, workdir):
    """CATCHES: until/since option validation for PlainYearMonth/PlainDateTime/PlainTime: different calendars, invalid or out-of-order units, zero results, increment rules for calendar units, and string shorthand rejection."""
    check(run, workdir, "plain_difference_option_errors", r'''
const ym = Temporal.PlainYearMonth.from('2024-05');
t('ym different calendar', () => ym.until(Temporal.PlainYearMonth.from({ year: 2024, month: 5, calendar: 'gregory' })));
t('ym bad largest', () => ym.until('2025-01', { largestUnit: 'decade' }));
t('ym bad smallest', () => ym.until('2025-01', { smallestUnit: 'decade' }));
t('ym smallest > largest', () => ym.until('2025-01', { largestUnit: 'months', smallestUnit: 'years' }));
t('ym same', () => ym.until('2024-05'));
t('ym same with rounding', () => ym.since('2024-05', { smallestUnit: 'years', roundingIncrement: 5 }));
t('ym months incr 5 halfExpand', () => ym.until('2026-12', { smallestUnit: 'months', roundingIncrement: 5 }));
t('ym years incr 2 ceil', () => ym.until('2027-01', { smallestUnit: 'years', roundingIncrement: 2, roundingMode: 'ceil' }));
t('ym since negative', () => ym.since('2026-12', { largestUnit: 'years' }));
const dt = Temporal.PlainDateTime.from('2024-05-01T00:00');
t('dt different calendar', () => dt.until(dt.withCalendar('gregory')));
t('dt bad largest', () => dt.until(dt, { largestUnit: 'eon' }));
t('dt bad smallest', () => dt.until(dt, { smallestUnit: 'eon' }));
t('dt smallest > largest', () => dt.until(dt, { largestUnit: 'hours', smallestUnit: 'days' }));
t('dt smallest only years', () => dt.until('2026-09-01T12:00', { smallestUnit: 'years' }));
t('dt smallest weeks', () => dt.until('2024-07-01T12:00', { smallestUnit: 'weeks' }));
t('dt days incr 3', () => dt.until('2024-07-01T12:00', { smallestUnit: 'days', roundingIncrement: 3 }));
t('dt months incr 2 since', () => dt.since('2024-12-31T12:00', { smallestUnit: 'months', roundingIncrement: 2, roundingMode: 'halfFloor' }));
t('dt until same', () => dt.until(dt, { smallestUnit: 'years' }));
t('dt us/ms largest', () => `${dt.until('2024-05-01T00:00:01.0015', { largestUnit: 'microseconds' })} ${dt.until('2024-05-01T00:00:01.0015', { largestUnit: 'milliseconds', smallestUnit: 'microsecond' })}`);
const tm = Temporal.PlainTime.from('10:00');
t('time bad largest', () => tm.until('11:00', { largestUnit: 'day' }));
t('time bad smallest', () => tm.until('11:00', { smallestUnit: 'years' }));
t('time bad unit name', () => tm.until('11:00', { largestUnit: 'jiffies' }));
t('time bad smallest name', () => tm.until('11:00', { smallestUnit: 'jiffies' }));
t('time smallest > largest', () => tm.until('11:00', { largestUnit: 'minutes', smallestUnit: 'hours' }));
t('time us', () => tm.until('10:00:00.0012345', { smallestUnit: 'microseconds', roundingMode: 'halfExpand' }));
t('time ms incr 250', () => tm.since('10:00:00.6', { smallestUnit: 'milliseconds', roundingIncrement: 250 }));
t('time round options string', () => tm.round(5));
''')
