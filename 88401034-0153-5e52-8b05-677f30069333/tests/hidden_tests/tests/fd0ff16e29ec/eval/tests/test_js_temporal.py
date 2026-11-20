"""Temporal (TC39 proposal) behaviour: PlainDate/PlainTime/PlainDateTime/PlainYearMonth/PlainMonthDay,
Duration, Instant, ZonedDateTime, ISO 8601 / RFC 9557 string parsing, rounding, calendars, time zones
(fixed offsets and IANA zones with DST transitions), toLocaleString and the exact error types/messages.

Every program prints labelled lines `label => result` (or `label => THROW Name: message`), so a single
golden pins down both values and error behaviour. Nothing here reads the current time.
"""

import pytest

from conftest import golden

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

# Shared prelude: t(label, fn) prints the result (Temporal objects via toString, other objects as
# JSON) or the thrown error's constructor name and message.
HELPER = r"""
const show = v => (v !== null && typeof v === 'object' && !String(v[Symbol.toStringTag]).startsWith('Temporal.'))
  ? JSON.stringify(v) : String(v);
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


PLAIN_DATE_PARSE = r"""
const P = Temporal.PlainDate;
t('ctor', () => new P(2024, 2, 29));
t('ctor cal', () => new P(2024, 2, 29, 'gregory'));
t('ctor cal case', () => new P(2024, 2, 29, 'GREGORY').calendarId);
t('ctor bad', () => new P(2023, 2, 29));
t('ctor nonew', () => P(2023, 2, 1));
t('ctor badcal', () => new P(2023, 2, 1, 'foo'));
t('ctor isocal string', () => new P(2023, 2, 1, '2020-01-01[u-ca=japanese]'));
t('ctor numcal', () => new P(2023, 2, 1, 5));
t('ctor inf', () => new P(Infinity, 2, 1));
t('ctor frac', () => new P(2020.9, 2.7, 1.2));
t('ctor str args', () => new P('2020', '3', '04'));
t('ctor missing', () => new P(2020));
t('from str', () => P.from('2020-01-05'));
t('from basic', () => P.from('20200105'));
t('from dt', () => P.from('2020-01-05T10:00:00'));
t('from dt Z', () => P.from('2020-01-05T10:00:00Z'));
t('from dt offset', () => P.from('2020-01-05T23:00:00-08:00'));
t('from space', () => P.from('2020-01-05 23:00'));
t('from ext year', () => P.from('+002020-01-05'));
t('from neg year', () => P.from('-000001-01-05'));
t('from -0', () => P.from('-000000-01-05'));
t('from 5digit', () => P.from('12020-01-05'));
t('from ann', () => P.from('2020-01-05[!u-ca=iso8601]'));
t('from ann tz cal', () => P.from('2020-01-05[Europe/Paris][u-ca=gregory]'));
t('from ann offset tz', () => P.from('2020-01-05T00:00[+01:00]'));
t('from crit unknown', () => P.from('2020-01-05[!foo=bar]'));
t('from unknown', () => P.from('2020-01-05[foo=bar]'));
t('from uppercase key', () => P.from('2020-01-05[U-CA=gregory]'));
t('from 2cal', () => P.from('2020-01-05[u-ca=iso8601][u-ca=gregory]'));
t('from 2cal crit', () => P.from('2020-01-05[u-ca=iso8601][!u-ca=gregory]'));
t('from bad cal ann', () => P.from('2020-01-05[u-ca=nonsense]'));
t('from 2tz', () => P.from('2020-01-05[UTC][UTC]'));
t('from bad month', () => P.from('2020-13-05'));
t('from bad day', () => P.from('2020-02-30'));
t('from trailing', () => P.from('2020-02-03x'));
t('from short', () => P.from('2020-2-3'));
t('from mixed ext', () => P.from('2020-0203'));
t('from fullwidth', () => P.from('２０２０-01-01'));
t('from obj overflow', () => P.from({year: 2020, month: 13, day: 40}));
t('from obj reject', () => P.from({year: 2020, month: 13, day: 40}, {overflow: 'reject'}));
t('from obj monthCode', () => P.from({year: 2020, monthCode: 'M03', day: 4}));
t('from obj bad monthCode', () => P.from({year: 2020, monthCode: 'M13', day: 4}));
t('from obj bad monthCode2', () => P.from({year: 2020, monthCode: '3', day: 4}));
t('from obj mismatch', () => P.from({year: 2020, month: 2, monthCode: 'M03', day: 4}));
t('from obj missing month', () => P.from({year: 2020, day: 4}));
t('from obj missing day', () => P.from({year: 2020, month: 4}));
t('from obj missing year', () => P.from({month: 4, day: 1}));
t('from obj zero day', () => P.from({year: 2020, month: 4, day: 0}));
t('from obj str fields', () => P.from({year: '2021', month: '7', day: '9'}));
t('from obj cal', () => P.from({year: 2020, month: 1, day: 1, calendar: 'gregory'}));
t('from obj bad cal', () => P.from({year: 2020, month: 1, day: 1, calendar: 'nope'}));
t('from num', () => P.from(20200101));
t('from null', () => P.from(null));
t('from bad overflow', () => P.from({year: 2020, month: 1, day: 1}, {overflow: 'bogus'}));
t('from bad options', () => P.from('2020-01-01', 5));
t('from pdt', () => P.from(Temporal.PlainDateTime.from('2021-03-04T05:06')));
t('from zdt', () => P.from(Temporal.ZonedDateTime.from('2021-03-04T23:06+09:00[Asia/Tokyo]')));
t('from copies', () => { const a = P.from('2020-01-01'); const b = P.from(a); return [a === b, a.equals(b)].join(); });
t('limits lo', () => P.from('-271821-04-19'));
t('limits lo-1', () => P.from('-271821-04-18'));
t('limits hi', () => P.from('+275760-09-13'));
t('limits hi+1', () => P.from('+275760-09-14'));
t('limits ctor', () => new P(275760, 9, 14));
t('tag', () => Object.prototype.toString.call(P.from('2020-01-01')));
t('getter brand', () => Object.getOwnPropertyDescriptor(P.prototype, 'year').get.call({}));
t('method brand', () => P.prototype.add.call(Temporal.PlainTime.from('10:00'), {days: 1}));
t('lens', () => [P.length, P.prototype.add.length, P.from.length, P.prototype.until.length, P.prototype.with.length, P.compare.length].join());
t('names', () => [P.name, P.prototype.toPlainDateTime.name, Object.getOwnPropertyDescriptor(P.prototype, 'dayOfWeek').get.name].join());
"""

PLAIN_DATE_OPS = r"""
const P = Temporal.PlainDate;
const d = P.from('2024-02-29');
t('getters', () => [d.year, d.month, d.monthCode, d.day, d.dayOfWeek, d.dayOfYear, d.weekOfYear, d.yearOfWeek, d.daysInWeek, d.daysInMonth, d.daysInYear, d.monthsInYear, d.inLeapYear, d.calendarId, d.era, d.eraYear].join());
t('week numbering', () => ['2021-01-01', '2020-12-31', '2024-12-30', '2027-01-01', '2026-12-31', '2019-12-30', '2010-01-03', '2015-12-31', '2016-01-04'].map(s => { const x = P.from(s); return s + ':' + x.weekOfYear + '/' + x.yearOfWeek + '/' + x.dayOfWeek; }).join(' '));
t('daysInMonth', () => Array.from({length: 12}, (_, i) => P.from({year: 2023, month: i + 1, day: 1}).daysInMonth).join(','));
t('leap years', () => [1900, 2000, 2023, 2024, 2100, -4, 0].map(y => new P(y, 1, 1).inLeapYear).join(','));
t('with', () => d.with({month: 3}));
t('with day', () => d.with({day: 31, month: 4}));
t('with reject', () => d.with({day: 31, month: 4}, {overflow: 'reject'}));
t('with monthCode', () => d.with({monthCode: 'M12'}));
t('with year', () => d.with({year: 2023}));
t('with cal', () => d.with({calendar: 'gregory'}));
t('with tz', () => d.with({timeZone: 'UTC'}));
t('with empty', () => d.with({}));
t('with unknown only', () => d.with({hour: 3}));
t('with temporal', () => d.with(P.from('2020-01-01')));
t('with string', () => d.with('2020-01-01'));
t('add', () => d.add({years: 1}));
t('add reject', () => d.add({years: 1}, {overflow: 'reject'}));
t('add str', () => d.add('P1M1D'));
t('add neg', () => d.add({months: -14, days: -3}));
t('add weeks', () => d.add({weeks: 2}));
t('add hours', () => d.add({hours: 49}));
t('add hours neg', () => d.add({hours: -1}));
t('add ns', () => d.add({nanoseconds: 86400e9 - 1}));
t('add dur', () => d.add(Temporal.Duration.from({years: -1, months: -1})));
t('add out of range', () => d.add({years: 300000}));
t('add bad', () => d.add({}));
t('add bad2', () => d.add('1 day'));
t('sub', () => d.subtract({months: 1}));
t('sub mar31', () => P.from('2023-03-31').subtract({months: 1}));
t('sub neg', () => d.subtract('-P1Y'));
t('until default', () => d.until('2025-03-31'));
t('until months', () => d.until('2025-03-31', {largestUnit: 'months'}));
t('until years', () => d.until('2025-03-31', {largestUnit: 'years'}));
t('until weeks', () => d.until('2025-03-31', {largestUnit: 'weeks'}));
t('until neg years', () => d.until('2020-03-31', {largestUnit: 'years'}));
t('until eom', () => [P.from('2024-01-31').until('2024-02-29', {largestUnit: 'months'}), P.from('2024-01-31').until('2024-03-01', {largestUnit: 'months'}), P.from('2024-03-31').until('2024-02-29', {largestUnit: 'months'})].join(' '));
t('until auto', () => d.until('2025-03-31', {largestUnit: 'auto'}));
t('since round', () => d.since('2020-01-15', {largestUnit: 'year', smallestUnit: 'month', roundingMode: 'halfExpand'}));
t('since inc', () => d.since('2020-01-15', {smallestUnit: 'day', roundingIncrement: 7}));
t('since weeks round', () => d.since('2020-01-15', {smallestUnit: 'week', roundingMode: 'ceil'}));
t('since years trunc', () => d.since('2020-03-01', {smallestUnit: 'year'}));
t('since years ceil', () => d.since('2020-03-01', {smallestUnit: 'year', roundingMode: 'ceil'}));
t('until hours', () => d.until('2024-03-01', {largestUnit: 'hours'}));
t('until smallest hours', () => d.until('2024-03-01', {smallestUnit: 'hours'}));
t('until inverted', () => d.until('2024-03-01', {largestUnit: 'day', smallestUnit: 'year'}));
t('until bad unit', () => d.until('2024-03-01', {largestUnit: 'fortnight'}));
t('until bad inc', () => d.until('2024-03-01', {smallestUnit: 'month', roundingIncrement: 1.5e9}));
t('until other cal', () => d.until(P.from('2024-03-01[u-ca=gregory]')));
t('compare', () => [P.compare('2020-01-01', '2020-01-02'), P.compare(d, d), P.compare({year: 2030, month: 1, day: 1}, d), P.compare('2020-01-01[u-ca=japanese]', '2020-01-01')].join());
t('equals', () => [d.equals('2024-02-29'), d.equals('2024-02-29[u-ca=gregory]'), d.equals({year: 2024, month: 2, day: 29})].join());
t('toString', () => [d.toString({calendarName: 'always'}), d.toString({calendarName: 'never'}), d.toString({calendarName: 'critical'}), d.withCalendar('gregory').toString({calendarName: 'auto'}), d.withCalendar('gregory').toString({calendarName: 'never'})].join(' '));
t('toString bad', () => d.toString({calendarName: 'x'}));
t('toString years', () => [new P(-1, 1, 1), new P(0, 1, 1), new P(999, 1, 1), new P(9999, 12, 31), new P(10000, 1, 1)].map(String).join(' '));
t('toJSON', () => JSON.stringify({d}));
t('toLocale default', () => d.toLocaleString());
t('valueOf', () => d.valueOf());
t('relational', () => d < d);
t('toPDT', () => d.toPlainDateTime('10:30'));
t('toPDT none', () => d.toPlainDateTime());
t('toPDT obj', () => d.toPlainDateTime({hour: 25}));
t('toZDT', () => d.toZonedDateTime('Europe/Berlin'));
t('toZDT obj', () => d.toZonedDateTime({timeZone: 'America/Sao_Paulo', plainTime: '12:00'}));
t('toZDT gap', () => P.from('2018-11-04').toZonedDateTime('America/Sao_Paulo'));
t('toZDT bad', () => d.toZonedDateTime({}));
t('toPYM', () => d.toPlainYearMonth());
t('toPMD', () => d.toPlainMonthDay());
t('withCalendar bad', () => d.withCalendar());
t('chained', () => { let x = P.from('2000-01-31'); const out = []; for (let i = 0; i < 6; i++) { x = x.add({months: 1}); out.push(x.toString()); } return out.join(' '); });
"""

PLAIN_TIME = r"""
const T = Temporal.PlainTime;
t('ctor', () => new T(13, 5, 9, 123, 456, 789));
t('ctor def', () => new T());
t('ctor bad', () => new T(24));
t('ctor neg', () => new T(1, -1));
t('ctor ns', () => new T(0, 0, 0, 0, 0, 1000));
t('from T', () => T.from('T12:34:56.1'));
t('from hm', () => T.from('12:34'));
t('from compact', () => T.from('1234'));
t('from compact frac', () => T.from('123456,123456789'));
t('from dt ann', () => T.from('2020-01-01T12:00:00+05:00[Asia/Kolkata]'));
t('from Z', () => T.from('12:00:00Z'));
t('from leap sec', () => T.from('12:00:60'));
t('from date only', () => T.from('2020-01-01'));
t('from h', () => T.from('12'));
t('from Th', () => T.from('T12'));
t('from too many digits', () => T.from('12:00:00.1234567891'));
t('from ambiguous md', () => T.from('12-12'));
t('from T md', () => T.from('T12-12'));
t('from ambiguous ym', () => T.from('1212'));
t('from ambiguous ym2', () => T.from('202001'));
t('from T ym', () => T.from('T202001'));
t('from ambiguous with ann', () => T.from('1214[UTC]'));
t('from offset', () => T.from('12:00-05:00'));
t('from 24', () => T.from('24:00'));
t('from bad min', () => T.from('12:60'));
t('from obj', () => T.from({hour: 25, minute: 70}));
t('from obj reject', () => T.from({hour: 25}, {overflow: 'reject'}));
t('from obj empty', () => T.from({}));
t('from obj partial', () => T.from({second: 5}));
t('from obj neg', () => T.from({hour: -1}));
t('from pdt', () => T.from(Temporal.PlainDateTime.from('2020-01-01T05:06:07')));
const x = T.from('13:45:30.123456789');
t('getters', () => [x.hour, x.minute, x.second, x.millisecond, x.microsecond, x.nanosecond].join());
t('with', () => x.with({hour: 1, nanosecond: 0}));
t('with overflow', () => x.with({minute: 99}));
t('with reject', () => x.with({minute: 99}, {overflow: 'reject'}));
t('add', () => x.add({hours: 12, minutes: 30}));
t('add days ignored', () => x.add({days: 3, minutes: 1}));
t('add years ignored', () => x.add({years: 3}));
t('sub', () => x.subtract('PT14H'));
t('until', () => x.until('01:00'));
t('until hours', () => x.until('23:59', {largestUnit: 'hours'}));
t('until minutes ceil', () => x.until('23:59', {largestUnit: 'minutes', smallestUnit: 'second', roundingMode: 'ceil'}));
t('until ms', () => x.until('23:59', {largestUnit: 'millisecond'}));
t('since inc', () => x.since('00:00', {smallestUnit: 'minutes', roundingIncrement: 15, roundingMode: 'halfEven'}));
t('since bad inc', () => x.since('00:00', {smallestUnit: 'minutes', roundingIncrement: 7}));
t('since bad inc2', () => x.since('00:00', {smallestUnit: 'hours', roundingIncrement: 24}));
t('until day', () => x.until('00:00', {largestUnit: 'day'}));
t('round hour', () => x.round('hour'));
t('round obj', () => x.round({smallestUnit: 'minute', roundingIncrement: 20}));
t('round modes', () => ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(m => x.round({smallestUnit: 'second', roundingMode: m}).toString()).join(' '));
t('round half modes', () => ['halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(m => T.from('10:00:01.5').round({smallestUnit: 'second', roundingMode: m}).toString() + '/' + T.from('10:00:02.5').round({smallestUnit: 'second', roundingMode: m}).toString()).join(' '));
t('round day', () => x.round({smallestUnit: 'day'}));
t('round wrap', () => T.from('23:59:59.6').round('second'));
t('round none', () => x.round());
t('round empty', () => x.round({}));
t('round badmode', () => x.round({smallestUnit: 'second', roundingMode: 'nearest'}));
t('round inc ms', () => x.round({smallestUnit: 'millisecond', roundingIncrement: 250}));
t('round inc ns', () => x.round({smallestUnit: 'nanosecond', roundingIncrement: 500}));
t('round inc us', () => x.round({smallestUnit: 'microsecond', roundingIncrement: 100, roundingMode: 'ceil'}));
t('round inc bad', () => x.round({smallestUnit: 'millisecond', roundingIncrement: 300}));
t('round inc 0', () => x.round({smallestUnit: 'second', roundingIncrement: 0}));
t('round inc inf', () => x.round({smallestUnit: 'second', roundingIncrement: Infinity}));
t('round plural', () => x.round('minutes'));
t('round bad unit', () => x.round('minuet'));
t('toString fsd', () => [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 'auto'].map(n => x.toString({fractionalSecondDigits: n})).join(' '));
t('toString su', () => ['minute', 'second', 'millisecond', 'microsecond', 'nanosecond'].map(u => x.toString({smallestUnit: u})).join(' '));
t('toString rm', () => x.toString({fractionalSecondDigits: 2, roundingMode: 'ceil'}));
t('toString fsd 10', () => x.toString({fractionalSecondDigits: 10}));
t('toString fsd str', () => x.toString({fractionalSecondDigits: 'x'}));
t('toString fsd float', () => x.toString({fractionalSecondDigits: 2.9}));
t('toString su hour', () => x.toString({smallestUnit: 'hour'}));
t('toString wrap', () => T.from('23:59:59.999').toString({smallestUnit: 'second', roundingMode: 'ceil'}));
t('zero frac', () => T.from('10:00').toString() + ' ' + T.from('10:00:00.5').toString() + ' ' + T.from('10:00:00.000001').toString());
t('compare', () => [T.compare('10:00', '09:59:59.999999999'), T.compare('10:00', '10:00'), T.compare({hour: 1}, '01:00:00.000000001')].join());
t('equals', () => [x.equals('13:45:30.123456789'), x.equals('13:45:30.12345679')].join());
t('valueOf', () => +x);
t('toJSON', () => x.toJSON());
t('toLocale', () => [x.toLocaleString('en'), x.toLocaleString('de'), x.toLocaleString('en', {hour: '2-digit', minute: '2-digit'})].join(' | '));
"""

PLAIN_DATETIME = r"""
const DT = Temporal.PlainDateTime;
t('ctor', () => new DT(2020, 1, 31, 23, 59, 59, 999, 999, 999));
t('ctor cal', () => new DT(2020, 1, 31, 0, 0, 0, 0, 0, 0, 'japanese'));
t('ctor bad', () => new DT(2020, 1, 31, 24));
t('from space', () => DT.from('2020-01-31 10:20'));
t('from lower', () => DT.from('2020-01-31t10:20:30.5+01:00'));
t('from Z', () => DT.from('2020-01-31T10:20Z'));
t('from date', () => DT.from('2020-01-31'));
t('from basic', () => DT.from('20200131T102030.25'));
t('from obj', () => DT.from({year: 2020, month: 2, day: 30, hour: 25}));
t('from obj reject', () => DT.from({year: 2020, month: 2, day: 30}, {overflow: 'reject'}));
t('from obj time reject', () => DT.from({year: 2020, month: 2, day: 3, minute: 60}, {overflow: 'reject'}));
t('from limits lo', () => DT.from('-271821-04-19T00:00:00.000000001'));
t('from limits lo exact', () => DT.from('-271821-04-19T00:00'));
t('from limits hi', () => DT.from('+275760-09-13T23:59:59.999999999'));
t('from pd', () => DT.from(Temporal.PlainDate.from('2020-05-06')));
t('from zdt', () => DT.from(Temporal.ZonedDateTime.from('2020-05-06T07:08:09+02:00[Europe/Paris]')));
const x = DT.from('2024-01-31T13:45:30.5');
t('getters', () => [x.year, x.month, x.day, x.hour, x.minute, x.second, x.millisecond, x.microsecond, x.nanosecond, x.dayOfWeek, x.weekOfYear, x.dayOfYear].join());
t('with', () => x.with({month: 2, minute: 0}));
t('with reject', () => x.with({month: 2}, {overflow: 'reject'}));
t('withPlainTime', () => x.withPlainTime('08:00'));
t('withPlainTime none', () => x.withPlainTime());
t('withCalendar', () => x.withCalendar('buddhist'));
t('add', () => x.add({months: 1, hours: 12}));
t('add reject', () => x.add({months: 1}, {overflow: 'reject'}));
t('add big hours', () => x.add({hours: 1e6}));
t('sub', () => x.subtract({days: 1, nanoseconds: 1}));
t('sub out of range', () => DT.from('-271821-04-19T00:00:00.000000001').subtract({nanoseconds: 1}));
t('until', () => x.until('2025-03-01T00:00'));
t('until year', () => x.until('2025-03-01T00:00', {largestUnit: 'year'}));
t('until hour', () => x.until('2025-03-01T00:00', {largestUnit: 'hour'}));
t('until ms', () => x.until('2024-02-01T00:00', {largestUnit: 'millisecond'}));
t('until ns', () => x.until('2024-02-01T00:00', {largestUnit: 'nanosecond'}));
t('until neg', () => x.until('2023-01-31T13:45:30.4', {largestUnit: 'year'}));
t('since day ceil', () => x.since('2023-01-01', {largestUnit: 'year', smallestUnit: 'day', roundingMode: 'ceil'}));
t('since week', () => x.since('2023-01-01', {largestUnit: 'month', smallestUnit: 'week'}));
t('since month', () => x.since('2023-01-01', {smallestUnit: 'month', roundingMode: 'halfExpand'}));
t('since hour inc', () => x.since('2024-01-30T00:00', {smallestUnit: 'hour', roundingIncrement: 6, roundingMode: 'floor'}));
t('round day', () => x.round({smallestUnit: 'day'}));
t('round hour inc', () => x.round({smallestUnit: 'hour', roundingIncrement: 6}));
t('round str', () => x.round('minute'));
t('round floor day', () => x.round({smallestUnit: 'day', roundingMode: 'floor'}));
t('round day inc', () => x.round({smallestUnit: 'day', roundingIncrement: 2}));
t('round month', () => x.round({smallestUnit: 'month'}));
t('toString', () => x.toString({fractionalSecondDigits: 3, calendarName: 'always'}));
t('toString su', () => x.toString({smallestUnit: 'minute'}));
t('toString round up', () => DT.from('2024-12-31T23:59:59.9').toString({fractionalSecondDigits: 0, roundingMode: 'halfExpand'}));
t('toString cal', () => x.withCalendar('japanese').toString());
t('toPlainDate', () => x.toPlainDate());
t('toPlainTime', () => x.toPlainTime());
t('toZDT', () => x.toZonedDateTime('America/New_York'));
t('toZDT earlier', () => DT.from('2024-03-10T02:30').toZonedDateTime('America/New_York', {disambiguation: 'earlier'}));
t('toZDT later', () => DT.from('2024-03-10T02:30').toZonedDateTime('America/New_York', {disambiguation: 'later'}));
t('toZDT compatible', () => DT.from('2024-03-10T02:30').toZonedDateTime('America/New_York', {disambiguation: 'compatible'}));
t('toZDT reject', () => DT.from('2024-03-10T02:30').toZonedDateTime('America/New_York', {disambiguation: 'reject'}));
t('toZDT bad disamb', () => DT.from('2024-03-10T02:30').toZonedDateTime('America/New_York', {disambiguation: 'whatever'}));
t('toZDT fold', () => ['compatible', 'earlier', 'later'].map(d => DT.from('2024-11-03T01:30').toZonedDateTime('America/New_York', {disambiguation: d}).toString()).join(' '));
t('toZDT fold reject', () => DT.from('2024-11-03T01:30').toZonedDateTime('America/New_York', {disambiguation: 'reject'}));
t('compare', () => [DT.compare('2020-01-01T00:00', '2020-01-01T00:00:00.000000001'), DT.compare('2020-01-02', '2020-01-01T23:59')].join());
t('equals', () => [x.equals('2024-01-31T13:45:30.5'), x.equals(x.withCalendar('gregory'))].join());
t('valueOf', () => x.valueOf());
t('toLocale', () => [x.toLocaleString('en'), x.toLocaleString('en', {dateStyle: 'medium', timeStyle: 'short'}), x.toLocaleString('ja', {month: 'long', day: 'numeric'})].join(' | '));
"""

YEAR_MONTH_MONTH_DAY = r"""
const YM = Temporal.PlainYearMonth;
t('ym ctor', () => new YM(2024, 2));
t('ym ctor ref', () => new YM(2024, 2, 'iso8601', 15).toString({calendarName: 'always'}));
t('ym ctor bad', () => new YM(2024, 13));
t('ym from', () => YM.from('2024-02'));
t('ym from basic', () => YM.from('202402'));
t('ym from dt', () => YM.from('2024-02-15T00:00'));
t('ym from max', () => YM.from('+275760-09'));
t('ym from min', () => YM.from('-271821-04'));
t('ym from below min', () => YM.from('-271821-03'));
t('ym from above max', () => YM.from('+275760-10'));
t('ym from cal', () => YM.from('2024-02-01[u-ca=hebrew]'));
t('ym from cal no day', () => YM.from('2024-02[u-ca=hebrew]'));
t('ym from iso ann', () => YM.from('2024-02[u-ca=iso8601]'));
t('ym from Z', () => YM.from('2024-02-01T00:00Z'));
t('ym from obj', () => YM.from({year: 2024, month: 13}));
t('ym from obj reject', () => YM.from({year: 2024, month: 13}, {overflow: 'reject'}));
t('ym from obj code', () => YM.from({year: 2024, monthCode: 'M05'}));
t('ym from obj missing', () => YM.from({year: 2024}));
const ym = YM.from('2024-02');
t('ym getters', () => [ym.year, ym.month, ym.monthCode, ym.daysInMonth, ym.daysInYear, ym.monthsInYear, ym.inLeapYear, ym.calendarId, ym.era, ym.day].join());
t('ym with', () => ym.with({month: 12}));
t('ym with year', () => ym.with({year: 2023}));
t('ym with day', () => ym.with({day: 3}));
t('ym add', () => ym.add({years: 1, months: 11}));
t('ym add days', () => ym.add({days: 40}));
t('ym add neg', () => ym.add({months: -25}));
t('ym sub', () => ym.subtract('P1M'));
t('ym sub year', () => ym.subtract({years: 1}));
t('ym until', () => ym.until('2030-01'));
t('ym until months', () => ym.until('2030-01', {largestUnit: 'months'}));
t('ym since round', () => ym.since('2020-07', {smallestUnit: 'year', roundingMode: 'halfExpand'}));
t('ym since neg', () => ym.since('2030-07'));
t('ym until days', () => ym.until('2030-01', {largestUnit: 'days'}));
t('ym until weeks', () => ym.until('2030-01', {smallestUnit: 'weeks'}));
t('ym toPlainDate', () => ym.toPlainDate({day: 31}));
t('ym toPlainDate missing', () => ym.toPlainDate({}));
t('ym toPlainDate none', () => ym.toPlainDate());
t('ym compare', () => [YM.compare('2024-02', '2024-03'), YM.compare('2024-02', '2024-02')].join());
t('ym equals', () => [ym.equals('2024-02'), ym.equals(new YM(2024, 2, 'iso8601', 5))].join());
t('ym toString', () => [ym.toString({calendarName: 'always'}), ym.toString({calendarName: 'never'}), ym.toString(), new YM(-5, 3).toString()].join(' '));
t('ym toJSON', () => JSON.stringify([ym]));
t('ym valueOf', () => ym.valueOf());
const MD = Temporal.PlainMonthDay;
t('md ctor', () => new MD(2, 29));
t('md ctor bad', () => new MD(2, 30));
t('md ctor ref', () => new MD(2, 29, 'iso8601', 2000).toString({calendarName: 'always'}));
t('md from dashdash', () => MD.from('--02-29'));
t('md from', () => MD.from('02-29'));
t('md from compact', () => MD.from('0229'));
t('md from dashdash compact', () => MD.from('--0229'));
t('md from date', () => MD.from('2023-02-28'));
t('md from bad', () => MD.from('02-30'));
t('md from obj', () => MD.from({month: 2, day: 30}));
t('md from obj year', () => MD.from({year: 2023, month: 2, day: 29}));
t('md from obj reject', () => MD.from({year: 2023, month: 2, day: 29}, {overflow: 'reject'}));
t('md from obj code', () => MD.from({monthCode: 'M12', day: 25}));
t('md from obj no month', () => MD.from({day: 25}));
t('md from obj no day', () => MD.from({month: 2}));
const md = MD.from('12-25');
t('md getters', () => [md.monthCode, md.day, md.calendarId, md.month, md.year].join());
t('md with', () => md.with({day: 31}));
t('md with month', () => md.with({month: 2}));
t('md with monthCode', () => md.with({monthCode: 'M02', day: 29}));
t('md toPlainDate', () => md.toPlainDate({year: 2020}));
t('md toPlainDate 229', () => MD.from('02-29').toPlainDate({year: 2023}));
t('md toPlainDate missing', () => md.toPlainDate({}));
t('md equals', () => [md.equals('12-25'), md.equals('12-26')].join());
t('md toString', () => [md.toString({calendarName: 'always'}), md.toString({calendarName: 'critical'}), md.toString()].join(' '));
t('md toString cal ann', () => MD.from('12-25[u-ca=gregory]'));
t('md toString iso ann', () => MD.from('12-25[u-ca=iso8601]'));
t('md compare', () => typeof MD.compare);
t('md valueOf', () => md.valueOf());
"""

DURATION_BASIC = r"""
const D = Temporal.Duration;
t('ctor', () => new D(1, 2, 3, 4, 5, 6, 7, 8, 9, 10));
t('ctor neg', () => new D(-1, 0, 0, -4));
t('ctor mixed', () => new D(1, -1));
t('ctor frac', () => new D(1.5));
t('ctor empty', () => new D());
t('ctor -0', () => new D(-0, -0).sign);
t('ctor nan', () => new D(NaN));
t('from', () => D.from('P1Y2M3W4DT5H6M7.008009010S'));
t('from frac h', () => D.from('PT1.5H'));
t('from frac m', () => D.from('PT1.25M'));
t('from frac tiny', () => D.from('PT0.000000001H'));
t('from frac m tiny', () => D.from('PT0.123456789M'));
t('from neg', () => D.from('-P1D'));
t('from plus', () => D.from('+P1D'));
t('from minus sign', () => D.from('−P1D'));
t('from comma', () => D.from('PT1,5S'));
t('from lower', () => D.from('p1dt2h'));
t('from weeks', () => D.from('P52W'));
t('from P', () => D.from('P'));
t('from PT', () => D.from('PT'));
t('from frac day', () => D.from('P1.5D'));
t('from frac not last', () => D.from('PT1.5H2M'));
t('from order', () => D.from('P1D2Y'));
t('from 10 frac', () => D.from('PT1.1234567891S'));
t('from T without time', () => D.from('P1DT'));
t('from obj', () => D.from({hours: 25, minutes: -0}));
t('from obj mixed', () => D.from({hours: 1, minutes: -1}));
t('from obj empty', () => D.from({}));
t('from obj frac', () => D.from({hours: 1.5}));
t('from obj typo', () => D.from({hour: 1}));
t('from obj inf', () => D.from({days: Infinity}));
t('from obj strings', () => D.from({days: '3', hours: '-0'}));
t('from num', () => D.from(5));
t('from big s', () => D.from({seconds: 2 ** 53}));
t('from big y', () => D.from({years: 2 ** 32}));
t('from max y', () => D.from({years: 2 ** 32 - 1}));
t('from max s', () => D.from({seconds: Number.MAX_SAFE_INTEGER}));
t('from max s + ms', () => D.from({seconds: Number.MAX_SAFE_INTEGER, milliseconds: 1000}));
t('from huge ms', () => D.from({milliseconds: 1e20}));
t('from big string', () => D.from('PT9007199254740992S'));
const d = D.from('P1Y2M3W4DT5H6M7.890S');
t('getters', () => [d.years, d.months, d.weeks, d.days, d.hours, d.minutes, d.seconds, d.milliseconds, d.microseconds, d.nanoseconds, d.sign, d.blank].join());
t('negated', () => d.negated());
t('abs', () => d.negated().abs());
t('with', () => d.with({years: 0, hours: -0}));
t('with mixed', () => d.with({years: -1}));
t('with empty', () => d.with({}));
t('blank', () => [new D().blank, new D().sign, D.from('-PT1S').sign, D.from('PT0.000000001S').blank].join());
t('add', () => D.from('PT1H').add('PT59M60S'));
t('add cal', () => D.from('P1M').add('P1D'));
t('add days', () => D.from('P1D').add('PT25H'));
t('add neg result', () => D.from('PT1H').add('-PT3H30M'));
t('add zero', () => D.from('PT1H').add('-PT1H'));
t('sub', () => D.from('PT1H').subtract({minutes: 90}));
t('sub days', () => D.from('P3D').subtract('P1DT12H'));
t('toString', () => [D.from('PT0S'), D.from('-PT0.000001S'), D.from({milliseconds: 1500}), D.from({microseconds: -1}), D.from({seconds: 1, nanoseconds: 1}), D.from({minutes: 120}), D.from({milliseconds: 123456789}), D.from({nanoseconds: 1e15}), D.from({days: 1, nanoseconds: 1})].map(String).join(' '));
t('toString fsd', () => [0, 2, 9, 'auto'].map(n => D.from('PT1.23456S').toString({fractionalSecondDigits: n})).join(' '));
t('toString fsd zero', () => D.from('P1D').toString({fractionalSecondDigits: 3}));
t('toString su', () => D.from('PT1M1.5S').toString({smallestUnit: 'second', roundingMode: 'halfExpand'}));
t('toString su ms', () => D.from('PT1.23456S').toString({smallestUnit: 'millisecond', roundingMode: 'floor'}));
t('toString su minute', () => D.from('PT1M1.5S').toString({smallestUnit: 'minute'}));
t('toString carry', () => D.from('PT59.9999S').toString({fractionalSecondDigits: 2, roundingMode: 'ceil'}));
t('toString neg round', () => D.from('-PT1.55S').toString({fractionalSecondDigits: 1, roundingMode: 'floor'}));
t('toJSON', () => JSON.stringify(D.from('P1D')));
t('valueOf', () => D.from('P1D') + 1);
t('compare', () => [D.compare('PT1H', 'PT60M'), D.compare('PT1H', 'PT61M'), D.compare('P1D', 'PT24H'), D.compare('-PT1S', 'PT0S')].join());
t('compare cal', () => D.compare('P1M', 'P30D'));
t('compare cal rel', () => [D.compare('P1M', 'P30D', {relativeTo: '2024-02-01'}), D.compare('P1M', 'P30D', {relativeTo: '2024-01-01'}), D.compare('P1M', 'P31D', {relativeTo: '2024-01-01'})].join());
t('compare zdt rel', () => D.compare('P1D', 'PT24H', {relativeTo: '2024-03-09T12:00[America/New_York]'}));
t('toLocaleString', () => [D.from('P1DT2H3M').toLocaleString('en'), D.from('P1DT2H3M').toLocaleString('de', {style: 'long'}), D.from('PT1H2M3S').toLocaleString('en', {style: 'digital'})].join(' | '));
"""

DURATION_ROUND_TOTAL = r"""
const D = Temporal.Duration;
t('round hour', () => D.from('PT130M').round('hour'));
t('round largest', () => D.from('PT130M').round({largestUnit: 'hour'}));
t('round days', () => D.from('PT50H').round({largestUnit: 'day'}));
t('round days zdt', () => D.from('PT50H').round({largestUnit: 'day', relativeTo: '2024-03-09T12:00[America/New_York]'}));
t('round days zdt fall', () => D.from('PT50H').round({largestUnit: 'day', relativeTo: '2024-11-02T12:00[America/New_York]'}));
t('round month rel', () => D.from('P40D').round({largestUnit: 'month', relativeTo: '2024-01-15'}));
t('round month norel', () => D.from('P40D').round({largestUnit: 'month'}));
t('round year rel', () => D.from('P1Y11M20D').round({smallestUnit: 'year', relativeTo: '2024-01-15'}));
t('round year rel trunc', () => D.from('P1Y11M20D').round({smallestUnit: 'year', relativeTo: '2024-01-15', roundingMode: 'trunc'}));
t('round week rel', () => D.from('P1M').round({smallestUnit: 'week', relativeTo: '2024-02-01', roundingMode: 'ceil'}));
t('round weeks largest', () => D.from('P100D').round({largestUnit: 'week', relativeTo: '2024-02-01'}));
t('round balance down', () => D.from('P1Y').round({largestUnit: 'day', relativeTo: '2024-02-01'}));
t('round balance hours', () => D.from('P1Y').round({largestUnit: 'hour', relativeTo: '2023-02-01'}));
t('round inc', () => D.from('PT1H17M').round({smallestUnit: 'minute', roundingIncrement: 15}));
t('round floor neg', () => D.from('-PT1H17M').round({smallestUnit: 'hour', roundingMode: 'floor'}));
t('round ceil neg', () => D.from('-PT1H17M').round({smallestUnit: 'hour', roundingMode: 'ceil'}));
t('round modes', () => ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(m => D.from('-PT1H30M').round({smallestUnit: 'hour', roundingMode: m}).toString() + '/' + D.from('PT2H30M').round({smallestUnit: 'hour', roundingMode: m}).toString()).join(' '));
t('round none', () => D.from('PT1H').round({}));
t('round inverted', () => D.from('PT1H').round({largestUnit: 'minute', smallestUnit: 'hour'}));
t('round day inc', () => D.from('P10D').round({smallestUnit: 'day', roundingIncrement: 3}));
t('round month inc', () => D.from('P10M').round({smallestUnit: 'month', roundingIncrement: 4, relativeTo: '2020-01-01'}));
t('round obj rel', () => D.from('PT1H').round({relativeTo: {year: 2020, month: 1, day: 1}, largestUnit: 'months'}));
t('round zdt bag rel', () => D.from('P1D').round({relativeTo: {year: 2024, month: 3, day: 9, hour: 12, timeZone: 'America/New_York'}, largestUnit: 'hours'}));
t('round zdt rel offset', () => D.from('P1D').round({relativeTo: {year: 2024, month: 3, day: 9, hour: 12, offset: '-05:00', timeZone: 'America/New_York'}, largestUnit: 'hours'}));
t('round rel plaindatetime', () => D.from('P1M').round({relativeTo: Temporal.PlainDateTime.from('2024-02-10T12:00'), largestUnit: 'days'}));
t('round rel zdt obj', () => D.from('P1M').round({relativeTo: Temporal.ZonedDateTime.from('2024-03-01T00:00[Europe/London]'), largestUnit: 'hours'}));
t('round rel bad', () => D.from('P1D').round({relativeTo: 'garbage', largestUnit: 'hours'}));
t('round rel offset mismatch', () => D.from('P1D').round({relativeTo: '2024-03-09T12:00+01:00[America/New_York]', largestUnit: 'hours'}));
t('round rel Z only', () => D.from('P1D').round({relativeTo: '2024-03-09T12:00Z', largestUnit: 'hours'}));
t('round rel Z tz', () => D.from('P1D').round({relativeTo: '2024-03-09T17:00Z[America/New_York]', largestUnit: 'hours'}));
t('round rel num', () => D.from('P1D').round({relativeTo: 20240101, largestUnit: 'hours'}));
t('round rel bad cal', () => D.from('P1D').round({relativeTo: '2024-01-01[u-ca=xx]', largestUnit: 'hours'}));
t('round string arg', () => D.from('PT1H59M59.9S').round('minute'));
t('round ns', () => D.from({nanoseconds: 1999999999}).round({largestUnit: 'second'}));
t('round huge', () => D.from({days: 1e8}).round({largestUnit: 'nanosecond'}));
t('total minute', () => D.from('PT1H30M').total('minute'));
t('total day', () => D.from('PT36H').total({unit: 'day'}));
t('total month', () => D.from('P1M').total({unit: 'day', relativeTo: '2024-02-01'}));
t('total year', () => D.from('P18M').total({unit: 'year', relativeTo: '2024-01-01'}));
t('total week', () => D.from('P1Y').total({unit: 'week', relativeTo: '2024-01-01'}));
t('total months frac', () => D.from('P45D').total({unit: 'month', relativeTo: '2024-01-31'}));
t('total months neg', () => D.from('-P45D').total({unit: 'month', relativeTo: '2024-03-31'}));
t('total norel', () => D.from('P1M').total({unit: 'day'}));
t('total zdt hour', () => D.from('P1D').total({unit: 'hour', relativeTo: '2024-11-02T12:00[America/New_York]'}));
t('total zdt day', () => D.from('PT48H').total({unit: 'day', relativeTo: '2024-03-09T12:00[America/New_York]'}));
t('total zdt month', () => D.from('P1M').total({unit: 'hour', relativeTo: '2024-10-15T00:00[Europe/Berlin]'}));
t('total ns', () => D.from('PT1S').total('nanoseconds'));
t('total ms', () => D.from('PT1.0005S').total('millisecond'));
t('total us', () => D.from('PT0.000000123S').total('microsecond'));
t('total empty', () => D.from('PT1S').total({}));
t('total bad unit', () => D.from('PT1S').total('lightyear'));
t('total none', () => D.from('PT1S').total());
"""

INSTANT = r"""
const I = Temporal.Instant;
t('ctor', () => new I(0n));
t('ctor num', () => new I(0));
t('ctor str', () => new I('5'));
t('ctor max', () => new I(8640000000000000000000n));
t('ctor max+1', () => new I(8640000000000000000001n));
t('ctor min', () => new I(-8640000000000000000000n));
t('fromEpochMs', () => I.fromEpochMilliseconds(1700000000123));
t('fromEpochMs frac', () => I.fromEpochMilliseconds(1.5));
t('fromEpochMs big', () => I.fromEpochMilliseconds(8.64e15 + 1));
t('fromEpochMs str', () => I.fromEpochMilliseconds('1000'));
t('fromEpochNs', () => I.fromEpochNanoseconds(-1n));
t('fromEpochNs num', () => I.fromEpochNanoseconds(1));
t('from Z', () => I.from('2020-01-01T00:00Z'));
t('from offset', () => I.from('2020-01-01T00:00+05:30'));
t('from offset seconds', () => I.from('2020-01-01T00:00:00+05:30:15.5'));
t('from offset ann', () => I.from('2020-01-01T00:00-08:00[America/Los_Angeles]'));
t('from no offset', () => I.from('2020-01-01T00:00'));
t('from date', () => I.from('2020-01-01'));
t('from leap second', () => I.from('2016-12-31T23:59:60Z'));
t('from min', () => I.from('-271821-04-20T00:00Z'));
t('from below min', () => I.from('-271821-04-19T23:59:59.999999999Z'));
t('from min offset', () => I.from('-271821-04-19T23:00-01:00'));
t('from basic', () => I.from('20200101T000000Z'));
t('from hh offset', () => I.from('2020-01-01T00:00+01'));
t('from hhmm offset', () => I.from('2020-01-01T00:00-0130'));
t('from Z ann', () => I.from('2020-01-01T00:00Z[UTC]'));
t('from unknown zone ann', () => I.from('2020-01-01T00:00Z[Mars/Olympus]'));
t('from lowercase z', () => I.from('2020-01-01t00:00z'));
t('from 9 frac', () => I.from('2020-01-01T00:00:00.123456789Z'));
t('from zdt', () => I.from(Temporal.ZonedDateTime.from('2020-01-01T00:00+09:00[Asia/Tokyo]')));
t('from obj', () => I.from({epochNanoseconds: 0n}));
const x = I.from('2024-06-15T12:34:56.789123456Z');
t('epoch', () => [x.epochMilliseconds, typeof x.epochNanoseconds, String(x.epochNanoseconds), x.epochSeconds, x.epochMicroseconds].join());
t('neg epoch ms', () => [I.from('1969-12-31T23:59:59.9999Z').epochMilliseconds, I.fromEpochNanoseconds(-1n).epochMilliseconds, I.fromEpochNanoseconds(-1000001n).epochMilliseconds].join());
t('add', () => x.add({hours: 25, nanoseconds: 1}));
t('add day', () => x.add({days: 1}));
t('add months', () => x.add({months: 1}));
t('add out of range', () => I.from('+275760-09-13T00:00Z').add({nanoseconds: 1}));
t('sub', () => x.subtract('PT1.5S'));
t('until', () => x.until('2024-06-16T00:00Z'));
t('until hours', () => x.until('2024-06-16T00:00Z', {largestUnit: 'hours'}));
t('until minute inc', () => x.until('2025-06-16T00:00Z', {largestUnit: 'hours', smallestUnit: 'minute', roundingIncrement: 30}));
t('until day', () => x.until('2024-06-16T00:00Z', {largestUnit: 'day'}));
t('since trunc', () => x.since('2024-01-01T00:00Z', {smallestUnit: 'second', roundingMode: 'trunc'}));
t('since ms', () => x.since('2024-06-15T12:34:56Z', {largestUnit: 'millisecond'}));
t('since us', () => x.since('2024-06-15T12:34:56Z', {largestUnit: 'microsecond', smallestUnit: 'microsecond'}));
t('round second', () => x.round('second'));
t('round hour inc', () => x.round({smallestUnit: 'hour', roundingIncrement: 4}));
t('round hour bad inc', () => x.round({smallestUnit: 'hour', roundingIncrement: 5}));
t('round minute inc 1440', () => x.round({smallestUnit: 'minute', roundingIncrement: 1440}));
t('round day', () => x.round({smallestUnit: 'day'}));
t('round ms floor', () => x.round({smallestUnit: 'millisecond', roundingMode: 'floor'}));
t('round neg epoch', () => I.fromEpochNanoseconds(-1500000000n).round({smallestUnit: 'second', roundingMode: 'halfTrunc'}));
t('toString', () => x.toString());
t('toString kolkata', () => x.toString({timeZone: 'Asia/Kolkata'}));
t('toString fixed', () => x.toString({timeZone: '+01:30', smallestUnit: 'minute'}));
t('toString st johns', () => x.toString({timeZone: 'America/St_Johns', fractionalSecondDigits: 1}));
t('toString utc', () => x.toString({timeZone: 'UTC', fractionalSecondDigits: 0}));
t('toString bad tz', () => x.toString({timeZone: 'Nowhere/Land'}));
t('toString round carry', () => I.from('1999-12-31T23:59:59.9999Z').toString({smallestUnit: 'second', roundingMode: 'ceil'}));
t('toZDT', () => x.toZonedDateTimeISO('Australia/Lord_Howe'));
t('toZDT fixed', () => x.toZonedDateTimeISO('-00:45'));
t('toZDT none', () => x.toZonedDateTimeISO());
t('compare', () => [I.compare('2020-01-01T00:00Z', '2020-01-01T01:00+01:00'), I.compare(x, '2020-01-01T00:00Z')].join());
t('equals', () => [x.equals(x.add({nanoseconds: 0})), x.equals('2024-06-15T12:34:56.789123457Z')].join());
t('toLocale', () => x.toLocaleString('en', {timeZone: 'UTC'}));
t('toLocale de', () => x.toLocaleString('de-DE', {timeZone: 'Asia/Tokyo'}));
t('toJSON', () => x.toJSON());
t('valueOf', () => x.valueOf());
t('Date.toTemporalInstant', () => new Date(86400000).toTemporalInstant());
t('Date invalid toTemporalInstant', () => new Date(NaN).toTemporalInstant());
"""

ZONED_PARSE = r"""
const Z = Temporal.ZonedDateTime;
t('ctor', () => new Z(0n, 'UTC'));
t('ctor offset', () => new Z(0n, '+05:30'));
t('ctor offset seconds', () => new Z(0n, '+05:30:01'));
t('ctor offset compact', () => new Z(0n, '-0800'));
t('ctor lowercase', () => new Z(0n, 'europe/paris'));
t('ctor alias', () => new Z(0n, 'Asia/Calcutta'));
t('ctor etc', () => new Z(0n, 'Etc/GMT+5'));
t('ctor utc aliases', () => ['Etc/UTC', 'GMT', 'Etc/GMT', 'Zulu', 'utc'].map(z => new Z(0n, z).timeZoneId).join(','));
t('ctor bad', () => new Z(0n, 'Mars/Base'));
t('ctor num tz', () => new Z(0n, 5));
t('ctor iso string tz', () => new Z(0n, '2020-01-01T00:00+01:00[Europe/Paris]'));
t('ctor cal', () => new Z(0n, 'Asia/Tokyo', 'japanese'));
t('ctor not bigint', () => new Z(0, 'UTC'));
t('from gap', () => Z.from('2024-03-10T02:30[America/New_York]'));
t('from gap bad offset', () => Z.from('2024-03-10T02:30-05:00[America/New_York]'));
t('from fold -05', () => Z.from('2024-11-03T01:30-05:00[America/New_York]'));
t('from fold -04', () => Z.from('2024-11-03T01:30-04:00[America/New_York]'));
t('from wrong offset', () => Z.from('2024-11-03T01:30+01:00[America/New_York]'));
t('from offset ignore', () => Z.from('2024-11-03T01:30+01:00[America/New_York]', {offset: 'ignore'}));
t('from offset use', () => Z.from('2024-11-03T01:30+01:00[America/New_York]', {offset: 'use'}));
t('from offset prefer', () => Z.from('2024-11-03T01:30+01:00[America/New_York]', {offset: 'prefer'}));
t('from offset prefer fold', () => Z.from('2024-11-03T01:30-05:00[America/New_York]', {offset: 'prefer'}));
t('from offset reject', () => Z.from('2024-11-03T01:30-04:00[America/New_York]', {offset: 'reject'}));
t('from offset bad', () => Z.from('2024-11-03T01:30-04:00[America/New_York]', {offset: 'maybe'}));
t('from gap disamb later', () => Z.from('2024-03-10T02:30[America/New_York]', {disambiguation: 'later'}));
t('from gap disamb earlier', () => Z.from('2024-03-10T02:30[America/New_York]', {disambiguation: 'earlier'}));
t('from gap disamb reject', () => Z.from('2024-03-10T02:30[America/New_York]', {disambiguation: 'reject'}));
t('from Z instant', () => Z.from('2024-11-03T05:30Z[America/New_York]'));
t('from no annotation', () => Z.from('2024-11-03T05:30Z'));
t('from fixed', () => Z.from('2024-11-03T05:30+03:00[+03:00]'));
t('from fixed compact', () => Z.from('2024-11-03T05:30[-1130]'));
t('from fixed seconds', () => Z.from('2024-11-03T05:30[+03:00:01]'));
t('from critical tz', () => Z.from('2024-11-03T05:30[!Europe/Rome]'));
t('from sub-minute offset', () => Z.from('2024-01-01T00:00+05:30:00.000000001[Asia/Kolkata]'));
t('from exact seconds offset', () => Z.from('1900-01-01T00:00+05:53:28[Asia/Kolkata]'));
t('from cal', () => Z.from('2024-01-01T00:00[UTC][u-ca=hebrew]'));
t('from date only', () => Z.from('2024-01-01[Europe/London]'));
t('from date only gap', () => Z.from('2018-11-04[America/Sao_Paulo]'));
t('from bag', () => Z.from({year: 2024, month: 3, day: 31, hour: 2, minute: 30, timeZone: 'Europe/Berlin'}));
t('from bag offset +01', () => Z.from({year: 2024, month: 10, day: 27, hour: 2, minute: 30, offset: '+01:00', timeZone: 'Europe/Berlin'}));
t('from bag offset +02', () => Z.from({year: 2024, month: 10, day: 27, hour: 2, minute: 30, offset: '+02:00', timeZone: 'Europe/Berlin'}));
t('from bag offset wrong', () => Z.from({year: 2024, month: 10, day: 27, hour: 2, minute: 30, offset: '+05:00', timeZone: 'Europe/Berlin'}));
t('from bag no tz', () => Z.from({year: 2024, month: 10, day: 27}));
t('from bag bad offset', () => Z.from({year: 2024, month: 10, day: 27, offset: 'xx', timeZone: 'UTC'}));
t('from bag tz from string', () => Z.from({year: 2024, month: 10, day: 27, timeZone: '2024-01-01T00:00+02:00'}));
t('from bag tz from Z string', () => Z.from({year: 2024, month: 10, day: 27, timeZone: '2024-01-01T00:00Z'}));
t('from bag tz alias', () => Z.from({year: 2024, month: 10, day: 27, timeZone: 'US/Pacific'}));
t('from bag overflow', () => Z.from({year: 2024, month: 2, day: 30, timeZone: 'UTC'}));
t('from bag reject', () => Z.from({year: 2024, month: 2, day: 30, timeZone: 'UTC'}, {overflow: 'reject'}));
t('from bad string', () => Z.from('2024-01-01T00:00[Europe/Nowhere]'));
const x = Z.from('2024-03-31T01:59:59.5+01:00[Europe/Berlin]');
t('getters', () => [x.year, x.month, x.day, x.hour, x.minute, x.second, x.millisecond, x.offset, x.offsetNanoseconds, x.timeZoneId, x.epochMilliseconds, String(x.epochNanoseconds), x.hoursInDay, x.dayOfWeek, x.dayOfYear, x.weekOfYear, x.daysInMonth, x.calendarId].join());
t('toString opts', () => [x.toString({offset: 'never'}), x.toString({timeZoneName: 'never'}), x.toString({timeZoneName: 'critical'}), x.toString({calendarName: 'always', fractionalSecondDigits: 0}), x.toString({smallestUnit: 'minute'}), x.toString({timeZoneName: 'never', offset: 'never'})].join(' | '));
t('toString round to next day', () => Z.from('2024-03-30T23:59:59.9+01:00[Europe/Berlin]').toString({smallestUnit: 'second', roundingMode: 'ceil'}));
t('toString bad offset', () => x.toString({offset: 'maybe'}));
t('toString bad tzname', () => x.toString({timeZoneName: 'sometimes'}));
t('toInstant', () => x.toInstant());
t('toPlainDate', () => x.toPlainDate());
t('toPlainTime', () => x.toPlainTime());
t('toPlainDateTime', () => x.toPlainDateTime());
t('toJSON', () => JSON.stringify(x));
t('compare', () => [Z.compare(x, x.withTimeZone('UTC')), Z.compare('2020-01-01T00:00[UTC]', '2020-01-01T00:00[Asia/Tokyo]')].join());
t('equals', () => [x.equals(x.withTimeZone('UTC')), x.equals(x.withTimeZone('Europe/Berlin')), x.equals(x.withTimeZone('Europe/Paris')), x.equals(x.withCalendar('gregory'))].join());
t('tz equals alias', () => [new Z(0n, 'Asia/Calcutta').equals(new Z(0n, 'Asia/Kolkata')), new Z(0n, '+00:00').equals(new Z(0n, 'UTC')), new Z(0n, 'Etc/UTC').equals(new Z(0n, 'UTC'))].join());
t('valueOf', () => x.valueOf());
"""

ZONED_OPS = r"""
const Z = Temporal.ZonedDateTime;
const x = Z.from('2024-03-31T01:59:59.5+01:00[Europe/Berlin]');
t('hoursInDay', () => ['2024-03-10[America/New_York]', '2024-11-03[America/New_York]', '2024-10-06[Australia/Lord_Howe]', '2024-04-07[Australia/Lord_Howe]', '2024-06-01[UTC]', '2011-12-30[Pacific/Apia]', '2018-11-04[America/Sao_Paulo]', '2024-06-01[+05:00]'].map(s => { try { return Z.from(s).hoursInDay; } catch (e) { return e.constructor.name; } }).join());
t('startOfDay gap', () => Z.from('2018-11-04T12:00[America/Sao_Paulo]').startOfDay());
t('startOfDay dst', () => Z.from('2024-03-10T12:00[America/New_York]').startOfDay());
t('startOfDay apia', () => Z.from('2011-12-31T12:00[Pacific/Apia]').startOfDay());
t('add 1s across gap', () => x.add({seconds: 1}));
t('add 1d', () => x.add({days: 1}));
t('add 24h', () => x.add({hours: 24}));
t('add 1M clamp', () => Z.from('2024-01-31T12:00[Europe/Berlin]').add({months: 1}));
t('add 1M reject', () => Z.from('2024-01-31T12:00[Europe/Berlin]').add({months: 1}, {overflow: 'reject'}));
t('add day into gap', () => Z.from('2024-03-09T02:30[America/New_York]').add({days: 1}));
t('add day from fold', () => Z.from('2024-11-02T01:30-04:00[America/New_York]').add({days: 1}));
t('sub', () => x.subtract({years: 1, hours: 1}));
t('sub weeks', () => x.subtract({weeks: 52}));
t('with gap', () => x.with({hour: 2, minute: 30}));
t('with keep offset +02', () => Z.from('2024-10-27T02:30+02:00[Europe/Berlin]').with({minute: 45}));
t('with keep offset +01', () => Z.from('2024-10-27T02:30+01:00[Europe/Berlin]').with({minute: 45}));
t('with offset field', () => Z.from('2024-10-27T02:30+02:00[Europe/Berlin]').with({offset: '+01:00'}));
t('with offset reject', () => Z.from('2024-10-27T02:30+02:00[Europe/Berlin]').with({offset: '+05:00'}, {offset: 'reject'}));
t('with offset use', () => Z.from('2024-10-27T02:30+02:00[Europe/Berlin]').with({offset: '+05:00'}, {offset: 'use'}));
t('with offset ignore', () => Z.from('2024-10-27T02:30+02:00[Europe/Berlin]').with({offset: '+05:00'}, {offset: 'ignore'}));
t('with disamb', () => x.with({hour: 2, minute: 30}, {disambiguation: 'earlier'}));
t('with tz', () => x.with({timeZone: 'UTC'}));
t('with month', () => x.with({month: 2}));
t('withPlainTime', () => x.withPlainTime('12:00'));
t('withPlainTime gap', () => x.withPlainTime('02:15'));
t('withPlainTime none', () => Z.from('2018-11-04T12:00[America/Sao_Paulo]').withPlainTime());
t('withTimeZone', () => x.withTimeZone('Asia/Tokyo'));
t('withTimeZone bad', () => x.withTimeZone('Nowhere'));
t('withCalendar', () => x.withCalendar('gregory'));
t('until', () => x.until('2024-10-27T12:00[Europe/Berlin]'));
t('until day', () => x.until('2024-10-27T12:00[Europe/Berlin]', {largestUnit: 'day'}));
t('until month hour', () => x.until('2024-10-27T12:00[Europe/Berlin]', {largestUnit: 'month', smallestUnit: 'hour'}));
t('until other tz', () => x.until('2024-10-27T12:00[Asia/Tokyo]', {largestUnit: 'day'}));
t('until other tz hours', () => x.until('2024-10-27T12:00[Asia/Tokyo]'));
t('until across fold day', () => [Z.from('2024-11-02T12:00[America/New_York]').until('2024-11-03T12:00[America/New_York]', {largestUnit: 'day'}), Z.from('2024-11-02T12:00[America/New_York]').until('2024-11-03T12:00[America/New_York]', {largestUnit: 'hour'})].join(' '));
t('until neg', () => Z.from('2024-11-03T12:00[America/New_York]').until('2024-03-09T12:00[America/New_York]', {largestUnit: 'year'}));
t('since round', () => x.since('2023-01-01T00:00[Europe/Berlin]', {largestUnit: 'year', smallestUnit: 'day', roundingMode: 'halfExpand'}));
t('since week', () => x.since('2023-01-01T00:00[Europe/Berlin]', {largestUnit: 'week', smallestUnit: 'week'}));
t('since minute inc', () => x.since('2024-03-30T00:00[Europe/Berlin]', {smallestUnit: 'minute', roundingIncrement: 10, roundingMode: 'ceil'}));
t('round hour', () => x.round('hour'));
t('round day spring', () => Z.from('2024-03-10T12:30[America/New_York]').round('day'));
t('round day spring 2', () => Z.from('2024-03-10T11:29[America/New_York]').round('day'));
t('round day fall', () => Z.from('2024-11-03T12:29[America/New_York]').round('day'));
t('round day fall 2', () => Z.from('2024-11-03T12:31[America/New_York]').round('day'));
t('round minute floor', () => x.round({smallestUnit: 'minute', roundingIncrement: 15, roundingMode: 'floor'}));
t('round day inc', () => x.round({smallestUnit: 'day', roundingIncrement: 2}));
t('transition next', () => x.getTimeZoneTransition('next'));
t('transition previous', () => x.getTimeZoneTransition('previous'));
t('transition obj', () => x.getTimeZoneTransition({direction: 'next'}));
t('transition utc', () => Z.from('2024-01-01T00:00[UTC]').getTimeZoneTransition('next'));
t('transition fixed', () => Z.from('2024-01-01T00:00[+01:00]').getTimeZoneTransition('previous'));
t('transition bad', () => x.getTimeZoneTransition('sideways'));
t('transition none', () => x.getTimeZoneTransition());
t('transition at exact', () => Z.from('2024-03-31T03:00+02:00[Europe/Berlin]').getTimeZoneTransition('previous'));
t('transition far future', () => Z.from('2060-01-01T00:00[America/New_York]').getTimeZoneTransition('next'));
t('far future offset', () => ['2030-07-01', '2037-07-01', '2040-07-01', '2100-07-01'].map(s => Z.from(s + 'T12:00[America/New_York]').offset).join(','));
t('far past offset', () => ['1800-01-01T00:00[America/New_York]', '1800-01-01T00:00[Europe/Amsterdam]', '1850-01-01T00:00[Asia/Kolkata]'].map(s => Z.from(s).toString()).join(' '));
t('moscow chain', () => { let z = Z.from('2020-01-01T00:00[Europe/Moscow]'); const out = []; for (let k = 0; k < 4; k++) { z = z.getTimeZoneTransition('previous'); out.push(z.toString()); } return out.join(' '); });
t('lord howe chain', () => { let z = Z.from('2024-01-01T00:00[Australia/Lord_Howe]'); const out = []; for (let k = 0; k < 3; k++) { z = z.getTimeZoneTransition('next'); out.push(z.toString()); } return out.join(' '); });
"""

TZ_SWEEP = r"""
// Offsets and next transitions for a spread of IANA zones at fixed instants.
const zones = ['America/New_York', 'America/Los_Angeles', 'America/Chicago', 'America/Denver', 'America/Phoenix', 'America/Sao_Paulo',
  'America/Santiago', 'America/Havana', 'America/St_Johns', 'America/Caracas', 'Europe/London', 'Europe/Dublin', 'Europe/Lisbon',
  'Europe/Paris', 'Europe/Istanbul', 'Europe/Kyiv', 'Africa/Casablanca', 'Africa/Cairo', 'Asia/Tehran', 'Asia/Kathmandu',
  'Asia/Kolkata', 'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Pyongyang', 'Australia/Adelaide', 'Australia/Brisbane',
  'Pacific/Auckland', 'Pacific/Chatham', 'Pacific/Kiritimati', 'Pacific/Honolulu', 'Antarctica/Troll', 'Asia/Gaza', 'Etc/GMT-14'];
const instants = ['1970-01-01T00:00Z', '1995-06-15T12:00Z', '2010-01-01T00:00Z', '2024-07-01T00:00Z'];
for (const z of zones) {
  t(z, () => instants.map(s => {
    const zdt = Temporal.Instant.from(s).toZonedDateTimeISO(z);
    const n = zdt.getTimeZoneTransition('next');
    return zdt.offset + '>' + (n ? n.toString({timeZoneName: 'never'}) : 'none');
  }).join(' '));
}
t('supportedValuesOf count', () => Intl.supportedValuesOf('timeZone').length);
t('links', () => ['US/Eastern', 'Asia/Saigon', 'Europe/Kiev', 'America/Buenos_Aires', 'Asia/Katmandu', 'Pacific/Samoa', 'Etc/GMT+12', 'EST5EDT', 'Iceland'].map(z => { const r = new Temporal.ZonedDateTime(1700000000000000000n, z); return r.timeZoneId + '@' + r.offset; }).join(' '));
"""

CALENDAR_FIELDS = r"""
const cals = ['iso8601', 'gregory', 'japanese', 'buddhist', 'roc', 'hebrew', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla',
  'islamicc', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'ethiopic-amete-alem', 'chinese', 'dangi', 'islamic', 'islamic-rgsa', 'gregorian'];
const dates = ['2024-03-20', '1999-12-31', '2033-07-04', '1900-02-28', '0622-07-19'];
for (const c of cals) {
  t(c, () => dates.map(s => { const d = Temporal.PlainDate.from(s).withCalendar(c); return [d.era, d.eraYear, d.year, d.month, d.monthCode, d.day, d.daysInMonth, d.daysInYear, d.monthsInYear, d.inLeapYear, d.dayOfYear].join('|'); }).join('  ') + '  ' + String(Temporal.PlainDate.from('2024-03-20').withCalendar(c)));
}
t('supportedValuesOf calendar', () => Intl.supportedValuesOf('calendar').join(','));
t('hebrew months 5784', () => { const out = []; let d = Temporal.PlainDate.from({calendar: 'hebrew', year: 5784, month: 1, day: 1}); for (let i = 0; i < 13; i++) { out.push(d.monthCode + ':' + d.daysInMonth + ':' + d.toString({calendarName: 'never'})); d = d.add({months: 1}); } return out.join(' '); });
t('chinese months 2023', () => { const out = []; let d = Temporal.PlainDate.from({calendar: 'chinese', year: 2023, month: 1, day: 1}); for (let i = 0; i < 13; i++) { out.push(d.monthCode + ':' + d.daysInMonth + ':' + d.toString({calendarName: 'never'})); d = d.add({months: 1}); } return out.join(' '); });
t('umalqura years', () => [1300, 1400, 1445, 1500, 1600].map(y => { const d = Temporal.PlainDate.from({calendar: 'islamic-umalqura', year: y, month: 1, day: 1}); return y + ':' + d.toString({calendarName: 'never'}) + ':' + d.daysInYear; }).join(' '));
t('persian leap', () => [1399, 1400, 1403, 1404, 1408].map(y => { const d = Temporal.PlainDate.from({calendar: 'persian', year: y, month: 12, day: 1}); return y + ':' + d.inLeapYear + ':' + d.daysInMonth; }).join(' '));
t('ethiopic 13th', () => { const d = Temporal.PlainDate.from({calendar: 'ethiopic', year: 2015, month: 13, day: 1}); return [d.monthCode, d.daysInMonth, d.toString()].join(' '); });
t('coptic leap 13th', () => { const d = Temporal.PlainDate.from({calendar: 'coptic', year: 1739, month: 13, day: 6}); return [d.monthCode, d.daysInMonth, d.inLeapYear, d.toString()].join(' '); });
t('indian leap', () => [1941, 1942, 1946].map(y => { const d = Temporal.PlainDate.from({calendar: 'indian', year: y, month: 1, day: 1}); return d.toString({calendarName: 'never'}) + ':' + d.daysInMonth + ':' + d.inLeapYear; }).join(' '));
"""

CALENDAR_ARITH = r"""
const iso = Temporal.PlainDate.from('2024-03-20');
for (const c of ['hebrew', 'chinese', 'dangi', 'islamic-umalqura', 'islamic-civil', 'persian', 'ethiopic', 'coptic', 'japanese', 'indian', 'buddhist', 'roc', 'gregory']) {
  const w = s => Temporal.PlainDate.from(s).withCalendar(c);
  t(c + ' add', () => { const d = iso.withCalendar(c); return [d.add({months: 1}), d.add({years: 1, months: 5}), d.add({months: -13}), d.add({years: -3, days: -10}), d.add({weeks: 7, days: 1}), d.subtract({years: 1, months: 1, days: 1})].map(x => x.toString({calendarName: 'never'})).join(' '); });
  t(c + ' until', () => { const d = iso.withCalendar(c); return [d.until(d.add({years: 2, months: 3, days: 4}), {largestUnit: 'year'}), d.until(w('2025-01-01'), {largestUnit: 'month'}), d.since(w('2020-02-29'), {largestUnit: 'year'}), d.until(w('2030-06-15'), {largestUnit: 'year', smallestUnit: 'month', roundingMode: 'halfExpand'}), d.until(w('2019-01-31'), {largestUnit: 'year'}), d.until(w('2024-05-01'), {largestUnit: 'week'})].join(' '); });
  t(c + ' ym md', () => { const d = iso.withCalendar(c); return [d.toPlainYearMonth(), d.toPlainMonthDay(), d.toPlainYearMonth().add({months: 7}), d.toPlainYearMonth().until(d.toPlainYearMonth().add({years: 1, months: 1})), d.with({day: 1}).toString({calendarName: 'never'})].map(String).join(' '); });
}
t('hebrew leap month', () => { const d = Temporal.PlainDate.from({calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 1}); return [d, d.month, d.monthCode, d.inLeapYear, d.monthsInYear, d.add({years: 1}), d.add({years: 1}).monthCode].join(' '); });
t('hebrew leap month constrain', () => Temporal.PlainDate.from({calendar: 'hebrew', year: 5785, monthCode: 'M05L', day: 1}));
t('hebrew leap month reject', () => Temporal.PlainDate.from({calendar: 'hebrew', year: 5785, monthCode: 'M05L', day: 1}, {overflow: 'reject'}));
t('hebrew month 13', () => Temporal.PlainDate.from({calendar: 'hebrew', year: 5785, month: 13, day: 1}));
t('hebrew month 13 reject', () => Temporal.PlainDate.from({calendar: 'hebrew', year: 5785, month: 13, day: 1}, {overflow: 'reject'}));
t('chinese leap month', () => { const d = Temporal.PlainDate.from({calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 1}); return [d, d.month, d.monthCode, d.monthsInYear].join(' '); });
t('chinese no leap', () => Temporal.PlainDate.from({calendar: 'chinese', year: 2024, monthCode: 'M02L', day: 1}, {overflow: 'reject'}));
t('chinese day 30', () => Temporal.PlainDate.from({calendar: 'chinese', year: 2024, month: 1, day: 30}, {overflow: 'reject'}));
t('japanese era from', () => Temporal.PlainDate.from({calendar: 'japanese', era: 'heisei', eraYear: 31, month: 4, day: 30}));
t('japanese era overflow', () => Temporal.PlainDate.from({calendar: 'japanese', era: 'heisei', eraYear: 32, month: 1, day: 1}));
t('japanese eras', () => ['1868-10-23', '1873-01-01', '1912-07-29', '1912-07-30', '1926-12-25', '1989-01-07', '1989-01-08', '2019-04-30', '2019-05-01', '1800-01-01', '0001-01-01', '-000001-01-01'].map(s => { const d = Temporal.PlainDate.from(s).withCalendar('japanese'); return d.era + d.eraYear; }).join(' '));
t('gregory eras', () => ['0001-01-01', '0000-12-31', '-000100-01-01'].map(s => { const d = Temporal.PlainDate.from(s).withCalendar('gregory'); return d.era + ':' + d.eraYear + ':' + d.year; }).join(' '));
t('gregory bce from', () => Temporal.PlainDate.from({calendar: 'gregory', era: 'bce', eraYear: 1, month: 1, day: 1}));
t('gregory era alias', () => Temporal.PlainDate.from({calendar: 'gregory', era: 'ad', eraYear: 2000, month: 1, day: 1}));
t('gregory era mismatch', () => Temporal.PlainDate.from({calendar: 'gregory', era: 'ce', eraYear: 2000, year: 1999, month: 1, day: 1}));
t('gregory bad era', () => Temporal.PlainDate.from({calendar: 'gregory', era: 'xyz', eraYear: 1, month: 1, day: 1}));
t('gregory era no eraYear', () => Temporal.PlainDate.from({calendar: 'gregory', era: 'ce', month: 1, day: 1}));
t('iso era ignored', () => Temporal.PlainDate.from({era: 'ce', eraYear: 5, year: 2000, month: 1, day: 1}));
t('roc eras', () => ['1900-01-01', '1912-01-01', '1911-12-31'].map(s => { const d = Temporal.PlainDate.from(s).withCalendar('roc'); return d.era + d.eraYear; }).join(' '));
t('buddhist from', () => Temporal.PlainDate.from({calendar: 'buddhist', year: 2567, month: 1, day: 1}));
t('ethioaa from era', () => Temporal.PlainDate.from({calendar: 'ethiopic', era: 'aa', eraYear: 5000, month: 1, day: 1}));
t('md hebrew leap', () => Temporal.PlainMonthDay.from({calendar: 'hebrew', monthCode: 'M05L', day: 15}));
t('md chinese 30', () => Temporal.PlainMonthDay.from({calendar: 'chinese', monthCode: 'M01', day: 30}));
t('md umalqura', () => Temporal.PlainMonthDay.from({calendar: 'islamic-umalqura', monthCode: 'M09', day: 30}));
t('md gregory', () => Temporal.PlainMonthDay.from({calendar: 'gregory', monthCode: 'M02', day: 29}));
t('md gregory year', () => Temporal.PlainMonthDay.from({calendar: 'gregory', year: 2023, month: 2, day: 29}));
t('md hebrew no code', () => Temporal.PlainMonthDay.from({calendar: 'hebrew', month: 6, day: 1}));
t('md hebrew toPlainDate', () => Temporal.PlainMonthDay.from({calendar: 'hebrew', monthCode: 'M05L', day: 15}).toPlainDate({year: 5785}));
t('ym persian', () => Temporal.PlainYearMonth.from({calendar: 'persian', year: 1403, month: 12}));
t('ym hebrew leap', () => Temporal.PlainYearMonth.from({calendar: 'hebrew', year: 5784, monthCode: 'M05L'}).toString() + ' ' + Temporal.PlainYearMonth.from({calendar: 'hebrew', year: 5784, monthCode: 'M05L'}).daysInMonth);
t('datetime cal', () => Temporal.PlainDateTime.from({calendar: 'japanese', era: 'showa', eraYear: 64, month: 1, day: 7, hour: 12}).toString());
t('zdt cal', () => Temporal.ZonedDateTime.from({calendar: 'hebrew', year: 5784, monthCode: 'M01', day: 1, timeZone: 'Asia/Jerusalem'}).toString());
t('zdt cal add', () => Temporal.ZonedDateTime.from('2024-03-20T12:00[Asia/Tehran][u-ca=persian]').add({months: 1}).toString());
t('zdt cal until', () => Temporal.ZonedDateTime.from('2024-03-20T12:00[UTC][u-ca=chinese]').until(Temporal.ZonedDateTime.from('2025-03-20T12:00[UTC][u-ca=chinese]'), {largestUnit: 'month'}).toString());
"""

ISO_GRAMMAR = r"""
// One table of strings fed to every from(); shows which grammar productions each type accepts.
const types = ['PlainDate', 'PlainTime', 'PlainDateTime', 'PlainYearMonth', 'PlainMonthDay', 'Instant', 'ZonedDateTime'];
const inputs = ['2020-01-02', '2020-01-02T03:04', '2020-01-02T03:04:05.678Z', '2020-01-02T03:04+01:00', '2020-01-02T03:04[Europe/Rome]',
  '2020-01-02T03:04+01:00[Europe/Rome]', '2020-01-02T03:04Z[Europe/Rome]', '2020-01-02T03:04+01:00[+01:00]', '2020-01-02T03:04[u-ca=gregory]',
  '2020-01', '01-02', '--01-02', '03:04', 'T03:04', '030405', '2020-01-02T24:00', '2020-01-02T03:04:05,5', '2020-01-02T03:04:05.',
  '2020-01-02T03', '2020-01-02T0304', '2020-01-02T03:0405', '2020-01-02T03:04:05+0100', '2020-01-02T03:04:05+01:00:00.5',
  '2020-01-02T03:04:05.123456789+23:59', '2020-01-02T03:04:05+24:00', '2020-01-02[Europe/Rome][u-ca=japanese]', '2020-01-02[_foo=bar]',
  '2020-01-02[foo=bar][u-ca=gregory]', '2020-01-02[!u-ca=gregory][u-ca=gregory]', '2020-01-02[u-ca=gregory][!u-ca=japanese]', '', ' 2020-01-02',
  '2020-01-02 ', '+2020-01-02', '-002020-01-02', '+0020200-01-02', '2020-W01-1', '2020-002', '2020-1-02', '20200102T030405Z',
  '2020-01-02T03:04:05-00:00', '2020-01-02T03:04:05−01:00', '2020-01-02T03:04[ Europe/Rome]', '2020-01-02T03:04[Europe/Rome', '2020-01-02T03:04[]',
  '2020-01-02T03:04[-08]', '2020-01-02T03:04[+0530]', '1976-11-18T15:23:30.1234567891Z', '2020-01-02T03:04:60Z', '2020-02-30T00:00Z', 'T24:00', '2020-01'];
for (const s of inputs) {
  console.log(JSON.stringify(s) + ': ' + types.map(ty => { try { return Temporal[ty].from(s).toString(); } catch (e) { return e.constructor.name; } }).join(' ; '));
}
console.log('bad type: ' + types.map(ty => { try { return String(Temporal[ty].from(true)); } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' ; '));
console.log('symbol: ' + types.map(ty => { try { return String(Temporal[ty].from(Symbol('x'))); } catch (e) { return e.constructor.name; } }).join(' ; '));
"""

DURATION_PARSE_TABLE = r"""
const inputs = ['P1Y', 'P1M', 'P1W', 'P1D', 'PT1H', 'PT1M', 'PT1S', 'P1Y1M1W1DT1H1M1.1S', 'PT0.5H', 'PT0.5M', 'PT0.5S', 'PT1.000000001S',
  'PT36H', 'P0D', '-PT0S', 'P1Y-1M', 'P-1Y', 'P1YT', 'PT1H1S', 'PT1S1M', 'P1W1Y', 'P1.0Y', 'PT1,1H', 'PT1.H', 'PT.5S', 'p1y', 'P1y1m1d',
  'P4294967295Y', 'P4294967296Y', 'PT9007199254740991S', 'P104249991374DT7H36M31.999999999S', 'P104249991375D', 'PT1E3S', ' P1D', 'P1D ', '1D', 'P1DT1H1M1.123456789S'];
for (const s of inputs) {
  t(JSON.stringify(s), () => { const d = Temporal.Duration.from(s); return d.toString() + ' sign=' + d.sign; });
}
"""

ROUNDING_MATRIX = r"""
// Each rounding mode x sign x tie position, through PlainTime, Duration, Instant and toString.
const modes = ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'];
const durs = ['PT1.4S', 'PT1.5S', 'PT1.6S', 'PT2.5S', '-PT1.4S', '-PT1.5S', '-PT1.6S', '-PT2.5S', 'PT0S'];
for (const m of modes) {
  console.log(m + ' dur: ' + durs.map(s => Temporal.Duration.from(s).round({smallestUnit: 'second', roundingMode: m}).toString()).join(' '));
  console.log(m + ' inst: ' + [-2500000000n, -1500000000n, -1000000001n, 1500000000n, 2500000000n].map(n => Temporal.Instant.fromEpochNanoseconds(n).round({smallestUnit: 'second', roundingMode: m}).epochMilliseconds).join(' '));
  console.log(m + ' str: ' + ['10:00:00.125', '10:00:00.135', '10:00:00.1251'].map(s => Temporal.PlainTime.from(s).toString({fractionalSecondDigits: 2, roundingMode: m})).join(' ') + ' ' + Temporal.Duration.from('-PT0.125S').toString({fractionalSecondDigits: 2, roundingMode: m}));
  console.log(m + ' diff: ' + [Temporal.PlainDate.from('2024-01-01').until('2024-02-16', {smallestUnit: 'month', roundingMode: m}), Temporal.PlainDate.from('2024-02-16').until('2024-01-01', {smallestUnit: 'month', roundingMode: m}), Temporal.PlainDate.from('2024-01-01').until('2024-01-04', {smallestUnit: 'day', roundingIncrement: 2, roundingMode: m})].join(' '));
}
"""

LOCALE_STRINGS = r"""
const pd = Temporal.PlainDate.from('2024-01-05');
const pdt = Temporal.PlainDateTime.from('2024-01-05T16:07:08');
const zdt = Temporal.ZonedDateTime.from('2024-07-05T16:07:08+02:00[Europe/Berlin]');
t('pd', () => [pd.toLocaleString(), pd.toLocaleString('en'), pd.toLocaleString('de'), pd.toLocaleString('ja', {dateStyle: 'long'}), pd.toLocaleString('en', {weekday: 'long'})].join(' | '));
t('pd timeStyle', () => pd.toLocaleString('en', {timeStyle: 'short'}));
t('pd gregory', () => Temporal.PlainDate.from('2024-01-05[u-ca=gregory]').toLocaleString('en'));
t('pd hebrew', () => Temporal.PlainDate.from('2024-01-05[u-ca=hebrew]').toLocaleString('en'));
t('pd hebrew match', () => Temporal.PlainDate.from('2024-01-05[u-ca=hebrew]').toLocaleString('en-u-ca-hebrew', {dateStyle: 'long'}));
t('pt', () => [Temporal.PlainTime.from('16:07:08').toLocaleString('en'), Temporal.PlainTime.from('16:07:08').toLocaleString('fr'), Temporal.PlainTime.from('16:07:08').toLocaleString('en', {timeStyle: 'short'})].join(' | '));
t('pt dateStyle', () => Temporal.PlainTime.from('16:07').toLocaleString('en', {dateStyle: 'short'}));
t('pdt', () => [pdt.toLocaleString('en'), pdt.toLocaleString('de'), pdt.toLocaleString('en', {dateStyle: 'full', timeStyle: 'medium'})].join(' | '));
t('ym iso', () => Temporal.PlainYearMonth.from('2024-01').toLocaleString('en'));
t('ym gregory', () => Temporal.PlainYearMonth.from('2024-01-01[u-ca=gregory]').toLocaleString('en'));
t('md iso', () => Temporal.PlainMonthDay.from('01-05').toLocaleString('en'));
t('md gregory', () => Temporal.PlainMonthDay.from({calendar: 'gregory', month: 1, day: 5}).toLocaleString('en'));
t('instant', () => Temporal.Instant.from('2024-01-05T16:07:08Z').toLocaleString('en'));
t('zdt', () => [zdt.toLocaleString('en'), zdt.toLocaleString('en', {timeZoneName: 'long'}), zdt.toLocaleString('en', {hour: 'numeric'})].join(' | '));
t('zdt utc', () => Temporal.ZonedDateTime.from('2024-07-05T16:07:08[UTC]').toLocaleString('en'));
t('zdt offset', () => Temporal.ZonedDateTime.from('2024-07-05T16:07:08[+05:30]').toLocaleString('en'));
t('zdt tz option', () => zdt.toLocaleString('en', {timeZone: 'UTC'}));
t('zdt bad options', () => zdt.toLocaleString('en', 5));
t('zdt cal mismatch', () => zdt.withCalendar('hebrew').toLocaleString('en'));
t('dtf zdt', () => new Intl.DateTimeFormat('en').format(zdt));
t('dtf pd', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium', timeZone: 'Asia/Tokyo'}).format(pd));
t('dtf pdt', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tokyo'}).format(pdt));
t('dtf instant', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tokyo'}).format(Temporal.Instant.from('2024-01-05T16:07:08Z')));
t('dtf pt', () => new Intl.DateTimeFormat('en', {timeStyle: 'short'}).format(Temporal.PlainTime.from('16:07')));
t('dtf cal mismatch', () => new Intl.DateTimeFormat('en').format(Temporal.PlainDate.from('2024-01-05[u-ca=hebrew]')));
t('dtf parts', () => JSON.stringify(new Intl.DateTimeFormat('en', {dateStyle: 'short'}).formatToParts(pd)));
t('dtf range', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium'}).formatRange(pd, pd.add({days: 3})));
t('dtf range mixed', () => new Intl.DateTimeFormat('en', {dateStyle: 'medium'}).formatRange(pd, pdt));
t('duration', () => Temporal.Duration.from('P1Y2M3DT4H5M6.007S').toLocaleString('en'));
t('duration fr narrow', () => Temporal.Duration.from('PT4H5M').toLocaleString('fr', {style: 'narrow'}));
t('brand', () => Temporal.PlainDate.prototype.toLocaleString.call({}));
t('brand zdt', () => Temporal.ZonedDateTime.prototype.toLocaleString.call(pd));
"""

TIERED = r"""
// Engine-heavy use of Temporal from user code: loops, closures, sorting, destructuring.
const start = Temporal.PlainDate.from('2023-12-25');
const rows = [];
for (let i = 0; i < 40; i++) {
  const d = start.add({days: i * 11});
  const {year, month, day, dayOfWeek} = d;
  rows.push({iso: d.toString(), key: (year * 100 + month) * 100 + day, dow: dayOfWeek});
}
rows.sort((a, b) => (b.dow - a.dow) || (a.key - b.key));
console.log(rows.slice(0, 8).map(r => r.iso + '/' + r.dow).join(' '));
const byMonth = new Map();
for (const r of rows) { const k = r.iso.slice(0, 7); byMonth.set(k, (byMonth.get(k) || 0) + 1); }
console.log([...byMonth].map(([k, v]) => k + '=' + v).join(','));
let total = Temporal.Duration.from('PT0S');
for (let h = 1; h <= 30; h++) total = total.add({minutes: h * 7, seconds: h});
console.log(total.toString(), total.round({largestUnit: 'day'}).toString(), total.total('hour'));
const times = ['23:59:59.999', '00:00', '12:30', '06:15:30', '18:45:01.5'].map(s => Temporal.PlainTime.from(s));
times.sort(Temporal.PlainTime.compare);
console.log(times.map(String).join(' '));
const z = Temporal.ZonedDateTime.from('2024-01-01T00:00[America/New_York]');
const offs = [];
for (let m = 0; m < 12; m++) offs.push(z.add({months: m}).offset);
console.log(offs.join(' '));
class Meeting { #at; constructor(s) { this.#at = Temporal.PlainDateTime.from(s); } get at() { return this.#at; } shift(d) { return new Meeting(this.#at.add(d).toString()); } }
const m = new Meeting('2024-02-28T09:00').shift({days: 1, hours: 36});
console.log(m.at.toString(), m.at.dayOfWeek, m.at.inLeapYear);
"""


ERROR_PATHS = r"""
const PD = Temporal.PlainDate, PDT = Temporal.PlainDateTime, PT = Temporal.PlainTime, YM = Temporal.PlainYearMonth, MD = Temporal.PlainMonthDay, D = Temporal.Duration, I = Temporal.Instant, Z = Temporal.ZonedDateTime;
t('obj cal number', () => PD.from({year: 2020, month: 1, day: 1, calendar: 5}));
t('relTo cal number', () => D.from('P1D').round({largestUnit: 'hours', relativeTo: {year: 2020, month: 1, day: 1, calendar: 5}}));
t('zdt bag cal number', () => Z.from({year: 2020, month: 1, day: 1, timeZone: 'UTC', calendar: 5}));
t('dt outside', () => PDT.from('+275760-09-13T00:00').until('-271821-04-19T00:00:00.000000001', {largestUnit: 'year'}));
t('dt outside2', () => PD.from('+275760-09-13').toPlainDateTime('23:59').add({days: 1}));
t('reject add hebrew leap', () => PD.from({calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30}).add({years: 1}, {overflow: 'reject'}));
t('reject add hebrew day', () => PD.from({calendar: 'hebrew', year: 5784, monthCode: 'M01', day: 30}).add({months: 1}, {overflow: 'reject'}));
t('reject add chinese', () => PD.from({calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 29}).add({years: 1}, {overflow: 'reject'}));
t('reject add coptic', () => PD.from({calendar: 'coptic', year: 1740, month: 1, day: 30}).add({months: 12}, {overflow: 'reject'}));
t('reject add islamic', () => PD.from({calendar: 'islamic-civil', year: 1445, month: 1, day: 30}).add({months: 1}, {overflow: 'reject'}));
t('constrain add islamic', () => PD.from({calendar: 'islamic-civil', year: 1445, month: 1, day: 30}).add({months: 1}));
t('constrain add hebrew leap', () => PD.from({calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30}).add({years: 1}));
t('day required', () => PD.from({year: 2020, month: 1}));
t('day required cal', () => PD.from({calendar: 'hebrew', year: 5784, monthCode: 'M01'}));
t('era together', () => PD.from({calendar: 'japanese', era: 'reiwa', month: 1, day: 1}));
t('era together2', () => PD.from({calendar: 'japanese', eraYear: 3, month: 1, day: 1}));
t('with era only', () => PD.from('2020-01-01[u-ca=japanese]').with({era: 'heisei'}));
t('with era both', () => PD.from('2020-01-01[u-ca=japanese]').with({era: 'heisei', eraYear: 5}));
t('with eraYear+year', () => PD.from('2020-01-01[u-ca=japanese]').with({era: 'heisei', eraYear: 5, year: 1990}));
t('with eraYear only', () => PD.from('2020-01-01[u-ca=gregory]').with({eraYear: 5}));
t('with year greg', () => PD.from('2020-01-01[u-ca=gregory]').with({year: -5}));
t('with month 0', () => PD.from('2020-01-01').with({month: 0}));
t('with monthCode num', () => PD.from('2020-01-01').with({monthCode: 5}));
t('with monthCode obj', () => PD.from('2020-01-01').with({monthCode: {toString() { return 'M04'; }}}));
t('from month 0', () => PD.from({year: 2020, month: 0, day: 1}));
t('from month -1', () => PD.from({year: 2020, month: -1, day: 1}));
t('from no month cal', () => PD.from({calendar: 'hebrew', year: 5784, day: 1}));
t('from no month', () => PD.from({calendar: 'gregory', year: 2020, day: 1}));
t('ym no month', () => YM.from({calendar: 'hebrew', year: 5784}));
t('md no month', () => MD.from({calendar: 'hebrew', day: 1}));
t('monthCode bool', () => PD.from({year: 2020, monthCode: true, day: 1}));
t('pdt no date', () => PDT.from('12:00'));
t('pdt no date T', () => PDT.from('T12:00'));
t('zdt offset num', () => Z.from({year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: 0}));
t('zdt with offset num', () => Z.from('2020-01-01T00:00[UTC]').with({offset: 0}));
t('relTo offset num', () => D.from('P1D').round({largestUnit: 'hours', relativeTo: {year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: 5}}));
t('relTo needs date', () => D.from('P1D').round({largestUnit: 'hours', relativeTo: {hour: 1}}));
t('relTo bad time field', () => D.from('P1D').round({largestUnit: 'hours', relativeTo: {year: 2020, month: 1, day: 1, hour: 25}}));
t('relTo bad tz string', () => D.from('P1D').round({largestUnit: 'hours', relativeTo: '2020-01-01T00:00[Bad/Zone]'}));
t('relTo bad tz bag', () => D.from('P1D').round({largestUnit: 'hours', relativeTo: {year: 2020, month: 1, day: 1, timeZone: 'Bad/Zone'}}));
t('relTo datetime string', () => D.from('P1M').round({largestUnit: 'days', relativeTo: '2020-01-31T12:00'}));
t('relTo zdt string offset ok', () => D.from('P1M').round({largestUnit: 'hours', relativeTo: '2020-03-01T00:00-05:00[America/New_York]'}));
t('relTo string Z bad', () => D.from('P1M').round({largestUnit: 'days', relativeTo: '2020-01-31Z'}));
t('relTo pdt', () => D.from('P1M').total({unit: 'day', relativeTo: Temporal.PlainDate.from('2020-02-01')}));
t('relTo other', () => D.from('P1M').total({unit: 'day', relativeTo: Temporal.PlainTime.from('10:00')}));
t('round no args', () => D.from('PT1H').round());
t('zdt round no args', () => Z.from('2020-01-01T00:00[UTC]').round());
t('dur with str', () => D.from('PT1H').with('PT2H'));
t('zdt with str', () => Z.from('2020-01-01T00:00[UTC]').with('2020-01-01'));
t('time with empty', () => PT.from('10:00').with({}));
t('time with unknown', () => PT.from('10:00').with({days: 1}));
t('time with string', () => PT.from('10:00').with('11:00'));
t('time with temporal', () => PT.from('10:00').with(PT.from('11:00')));
t('instant toString su hour', () => I.from('2020-01-01T00:00Z').toString({smallestUnit: 'hour'}));
t('zdt toString su hour', () => Z.from('2020-01-01T00:00[UTC]').toString({smallestUnit: 'hour'}));
t('zdt toString su day', () => Z.from('2020-01-01T00:00[UTC]').toString({smallestUnit: 'day'}));
t('ym outside', () => YM.from('+275760-09').add({months: 1}));
t('ym outside2', () => YM.from('-271821-04').subtract({months: 1}));
t('ym outside cal', () => YM.from('+275760-09').with({month: 10}));
t('epochNs out of range', () => I.fromEpochNanoseconds(8640000000000000000001n));
t('zdt ctor out of range', () => new Z(8640000000000000000001n, 'UTC'));
t('zdt from obj bad', () => Z.from({}));
t('iso date invalid', () => new PD(2020, 13, 1));
t('pd from undefined', () => PD.from());
t('dt ctor bad date', () => new PDT(2020, 2, 30));
t('cal brand', () => Object.getOwnPropertyDescriptor(PD.prototype, 'calendarId').get.call(5));
t('brands', () => [[D, 'years'], [I, 'epochMilliseconds'], [PDT, 'hour'], [MD, 'day'], [PT, 'hour'], [YM, 'month'], [Z, 'offset']].map(([C, k]) => { try { Object.getOwnPropertyDescriptor(C.prototype, k).get.call(PD.from('2020-01-01')); return 'ok'; } catch (e) { return e.message; } }).join(' | '));
t('method brands', () => [[D, 'add'], [I, 'add'], [PDT, 'add'], [MD, 'with'], [PT, 'add'], [YM, 'add'], [Z, 'add']].map(([C, k]) => { try { C.prototype[k].call({}, {days: 1}); return 'ok'; } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' | '));
t('calendar ctor non-string', () => new YM(2020, 1, {}));
t('withCalendar obj', () => PD.from('2020-01-01').withCalendar({}));
t('withCalendar temporal', () => PD.from('2020-01-01').withCalendar(PD.from('2020-01-01[u-ca=japanese]')));
t('withCalendar iso string', () => PD.from('2020-01-01').withCalendar('2020-01-01[u-ca=hebrew]'));
t('withTimeZone zdt', () => Z.from('2020-01-01T00:00[UTC]').withTimeZone(Z.from('2020-01-01T00:00[Asia/Tokyo]')));
t('tz string forms', () => ['2020-01-01T00:00Z', '2020-01-01T00:00+01:00', '2020-01-01T00:00[Asia/Tokyo]', '2020-01-01T00:00+09:00[Asia/Tokyo]', 'Z', '+01', '+0100', 'utc', 'Etc/GMT+5', '2020-01-01'].map(s => { try { return Z.from('2020-06-01T00:00[UTC]').withTimeZone(s).timeZoneId; } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' | '));
t('cal string forms', () => ['2020-01-01[u-ca=japanese]', '2020-01-01', 'JAPANESE', 'japanese', '2020-01[u-ca=hebrew]', '01-01[u-ca=iso8601]', '10:00[u-ca=gregory]', 'T10:00', ''].map(s => { try { return PD.from('2020-06-01').withCalendar(s).calendarId; } catch (e) { return e.constructor.name + ':' + e.message; } }).join(' | '));
"""

RELATIVE_ROUNDING = r"""
const D = Temporal.Duration, Z = Temporal.ZonedDateTime, PDT = Temporal.PlainDateTime;
const zrel = '2024-03-09T12:00[America/New_York]';
const prel = '2024-01-31T12:00';
const durs = ['P1Y2M3W4DT5H6M7.123456789S', '-P1M15DT12H', 'PT100H', 'P45D', 'P2W3DT23H59M', '-PT36H30M'];
const opts = [{largestUnit: 'year'}, {smallestUnit: 'month'}, {smallestUnit: 'week', roundingMode: 'ceil'}, {largestUnit: 'week', smallestUnit: 'day'}, {smallestUnit: 'day', roundingIncrement: 5}, {largestUnit: 'day', smallestUnit: 'hour', roundingIncrement: 6, roundingMode: 'floor'}, {smallestUnit: 'minute', roundingMode: 'halfEven'}, {largestUnit: 'month', smallestUnit: 'month', roundingIncrement: 2, roundingMode: 'expand'}, {smallestUnit: 'year', roundingMode: 'halfTrunc'}, {largestUnit: 'hour'}];
for (const rel of [zrel, prel, '2024-10-31T23:30+00:00[Europe/London]']) {
  for (const s of durs) {
    t(rel.slice(0, 10) + ' ' + s, () => opts.map(o => { try { return D.from(s).round({...o, relativeTo: rel}).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
  }
  t(rel.slice(0, 10) + ' totals', () => durs.map(s => ['year', 'month', 'week', 'day', 'hour'].map(u => D.from(s).total({unit: u, relativeTo: rel}).toFixed(6)).join(',')).join(' | '));
}
const a = Z.from('2024-01-31T22:15:30.5+01:00[Europe/Paris]');
const bs = ['2024-03-31T03:30:00+02:00[Europe/Paris]', '2025-02-28T01:00+01:00[Europe/Paris]', '2023-11-05T23:59:59.999+01:00[Europe/Paris]', '2024-01-31T22:15:30.4+01:00[Europe/Paris]'];
for (const b of bs) {
  t('zdt until ' + b.slice(0, 19), () => [{}, {largestUnit: 'year'}, {largestUnit: 'month', smallestUnit: 'day'}, {largestUnit: 'week', smallestUnit: 'week', roundingMode: 'ceil'}, {largestUnit: 'year', smallestUnit: 'month', roundingIncrement: 3, roundingMode: 'halfExpand'}, {smallestUnit: 'hour', roundingIncrement: 12}, {largestUnit: 'day', smallestUnit: 'minute', roundingMode: 'trunc'}, {largestUnit: 'year', smallestUnit: 'year', roundingMode: 'floor'}].map(o => a.until(b, o).toString() + '/' + a.since(b, o).toString()).join(' '));
}
const pa = PDT.from('2024-01-31T22:15:30.5');
for (const b of ['2024-03-31T02:30', '2025-02-28T01:00', '2023-11-05T23:59:59.999', '2024-01-31T22:15:30.4', '2024-02-29T22:15:30.5']) {
  t('pdt until ' + b, () => [{largestUnit: 'year'}, {largestUnit: 'month', smallestUnit: 'day', roundingMode: 'halfCeil'}, {largestUnit: 'week', smallestUnit: 'week', roundingMode: 'ceil'}, {largestUnit: 'year', smallestUnit: 'month', roundingIncrement: 3, roundingMode: 'halfExpand'}, {smallestUnit: 'hour', roundingIncrement: 12}, {largestUnit: 'year', smallestUnit: 'year', roundingMode: 'floor'}, {smallestUnit: 'day', roundingIncrement: 10, roundingMode: 'expand'}].map(o => pa.until(b, o).toString() + '/' + pa.since(b, o).toString()).join(' '));
}
t('pd until rounding', () => ['2024-04-15', '2025-07-31', '2019-12-01', '2024-02-01'].map(b => [{smallestUnit: 'month', roundingIncrement: 5}, {smallestUnit: 'week', largestUnit: 'month'}, {smallestUnit: 'year', roundingMode: 'ceil'}, {largestUnit: 'week', smallestUnit: 'day', roundingIncrement: 3}].map(o => Temporal.PlainDate.from('2024-01-31').until(b, o).toString()).join(' ')).join(' | '));
t('ym until rounding', () => ['2026-08', '2019-02', '2024-01'].map(b => [{smallestUnit: 'year', roundingMode: 'ceil'}, {smallestUnit: 'month', roundingIncrement: 4}, {largestUnit: 'month'}, {smallestUnit: 'year', roundingMode: 'halfEven'}].map(o => Temporal.PlainYearMonth.from('2024-01').until(b, o).toString()).join(' ')).join(' | '));
"""


GETTER_MATRIX = r"""
const cals = ['iso8601', 'gregory', 'japanese', 'buddhist', 'roc', 'hebrew', 'chinese', 'dangi', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa'];
const sv = v => { try { return v === undefined ? 'u' : String(v); } catch (e) { return 'E'; } };
const getterNames = C => Object.getOwnPropertyNames(C.prototype).filter(k => Object.getOwnPropertyDescriptor(C.prototype, k).get).sort();
const methodNames = C => Object.getOwnPropertyNames(C.prototype).filter(k => typeof Object.getOwnPropertyDescriptor(C.prototype, k).value === 'function').sort();
for (const n of ['PlainDate', 'PlainTime', 'PlainDateTime', 'PlainYearMonth', 'PlainMonthDay', 'ZonedDateTime', 'Instant', 'Duration']) {
  const C = Temporal[n];
  console.log(n + ' getters: ' + getterNames(C).join(','));
  console.log(n + ' methods: ' + methodNames(C).join(',') + ' statics: ' + Object.getOwnPropertyNames(C).sort().join(','));
}
console.log('Temporal: ' + Object.getOwnPropertyNames(Temporal).sort().join(',') + ' Now: ' + Object.getOwnPropertyNames(Temporal.Now).sort().join(','));
for (const c of cals) {
  const pd = Temporal.PlainDate.from('2024-03-20').withCalendar(c);
  const pdt = pd.toPlainDateTime('13:14:15.123456789');
  const zdt = pdt.toZonedDateTime('Asia/Tokyo');
  const ym = pd.toPlainYearMonth();
  const md = pd.toPlainMonthDay();
  for (const [name, v, C] of [['pd', pd, Temporal.PlainDate], ['pdt', pdt, Temporal.PlainDateTime], ['zdt', zdt, Temporal.ZonedDateTime], ['ym', ym, Temporal.PlainYearMonth], ['md', md, Temporal.PlainMonthDay]]) {
    console.log(c + ' ' + name + ': ' + getterNames(C).map(k => k + '=' + sv(v[k])).join(' '));
  }
}
"""

WITH_MATRIX = r"""
const cals = ['iso8601', 'gregory', 'japanese', 'roc', 'hebrew', 'chinese', 'islamic-umalqura', 'persian', 'coptic', 'ethiopic', 'indian'];
const bags = [{year: 2000}, {month: 2}, {monthCode: 'M02'}, {day: 31}, {era: 'ce', eraYear: 1999}, {era: 'heisei', eraYear: 2}, {era: 'bce', eraYear: 3}, {era: 'am', eraYear: 5785},
  {eraYear: 5}, {month: 13}, {monthCode: 'M05L'}, {monthCode: 'M13'}, {hour: 23, minute: 59}, {offset: '+09:00'}, {day: 0}, {month: 1, monthCode: 'M02'}, {year: 1, month: 1, day: 1}];
const r = f => { try { return f().toString({calendarName: 'never', timeZoneName: 'never'}); } catch (e) { return e.constructor.name + ':' + e.message; } };
for (const c of cals) {
  const pd = Temporal.PlainDate.from('2024-03-20').withCalendar(c);
  const objs = {pd, pdt: pd.toPlainDateTime('12:30'), zdt: pd.toZonedDateTime({timeZone: 'Asia/Tokyo', plainTime: '12:30'}), ym: pd.toPlainYearMonth(), md: pd.toPlainMonthDay()};
  for (const [name, v] of Object.entries(objs)) {
    console.log(c + ' ' + name + ' constrain: ' + bags.map(b => r(() => v.with(b))).join(' | '));
    console.log(c + ' ' + name + ' reject: ' + bags.map(b => r(() => v.with(b, {overflow: 'reject'}))).join(' | '));
  }
}
"""

MONTH_DAY_MATRIX = r"""
const cals = ['iso8601', 'gregory', 'japanese', 'hebrew', 'chinese', 'dangi', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla', 'persian', 'coptic', 'ethiopic', 'ethioaa', 'indian', 'buddhist', 'roc'];
const codes = [];
for (let m = 1; m <= 13; m++) codes.push('M' + String(m).padStart(2, '0'));
for (let m = 1; m <= 12; m++) codes.push('M' + String(m).padStart(2, '0') + 'L');
const r = f => { try { return f().toString({calendarName: 'never'}); } catch (e) { return e.constructor.name[0] + ':' + e.message; } };
for (const c of cals) {
  for (const ovf of ['constrain', 'reject']) {
    console.log(c + ' ' + ovf + ': ' + codes.map(code => code + '=' + [29, 30].map(d => r(() => Temporal.PlainMonthDay.from({calendar: c, monthCode: code, day: d}, {overflow: ovf}))).join(',')).join(' '));
  }
  console.log(c + ' with year: ' + [[1, 1], [2, 30], [6, 29], [12, 30], [13, 5]].map(([m, d]) => r(() => Temporal.PlainMonthDay.from({calendar: c, year: c === 'iso8601' || c === 'gregory' ? 2023 : Temporal.PlainDate.from('2023-06-01').withCalendar(c).year, month: m, day: d}))).join(' '));
  console.log(c + ' toPlainDate: ' + ['M01', 'M02', 'M06', 'M12'].map(code => r(() => Temporal.PlainMonthDay.from({calendar: c, monthCode: code, day: 30}).toPlainDate({year: Temporal.PlainDate.from('2025-06-01').withCalendar(c).year}))).join(' '));
}
const offs = ['+05:30', '+0530', '+05', '-00:00', '+00:00', '+05:30:15', '+053015', '+05:30:15.123456789', '+05:30:15,5', '+05:30:1', '+5:30', '+05:3', '+05:60', '+24:00', '−05:00', '+05:30:15.', '+05:30:15.1234567891', '05:30', '+05:30:15+', 'Z', '+05:3015', '+0530:15'];
console.log('bag offsets: ' + offs.map(o => r(() => Temporal.ZonedDateTime.from({year: 2024, month: 1, day: 1, hour: 12, offset: o, timeZone: o.length >= 6 && /^[+-]\d\d:\d\d$/.test(o) ? o : 'UTC'}, {offset: 'use'}))).join(' | '));
console.log('relTo offsets: ' + offs.map(o => r(() => Temporal.Duration.from('P1D').round({largestUnit: 'hour', relativeTo: {year: 2024, month: 1, day: 1, offset: o, timeZone: 'Asia/Kolkata'}}))).join(' | '));
"""


FAR_DATES = r"""
// Far past / far future conversions (exercise delta-T, astronomical new moons/solar terms, tabular fallbacks).
const cals = ['chinese', 'dangi', 'hebrew', 'persian', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'japanese', 'roc', 'buddhist'];
const isos = ['-001000-03-01', '0001-01-01', '0500-06-15', '1000-02-10', '1582-10-15', '1700-03-01', '1850-01-25', '1900-01-31', '1950-02-17', '2000-02-05', '2033-11-22', '2100-01-01', '2200-07-07', '2500-12-31', '3000-02-14'];
for (const c of cals) {
  console.log(c + ': ' + isos.map(s => { try { const d = Temporal.PlainDate.from(s).withCalendar(c); return [d.year, d.monthCode, d.day, d.daysInMonth, d.monthsInYear, d.inLeapYear].join('/'); } catch (e) { return e.constructor.name; } }).join(' '));
}
console.log('round trips: ' + cals.map(c => isos.every(s => { try { const d = Temporal.PlainDate.from(s).withCalendar(c); return Temporal.PlainDate.from({calendar: c, year: d.year, monthCode: d.monthCode, day: d.day}).equals(d); } catch (e) { return 'E'; } })).join(','));
console.log('chinese new years: ' + [1900, 1950, 1985, 2000, 2020, 2033, 2050, 2099].map(y => Temporal.PlainDate.from({calendar: 'chinese', year: y, month: 1, day: 1}).withCalendar('iso8601').toString()).join(' '));
console.log('hebrew new years: ' + [5600, 5700, 5784, 5785, 5800, 6000].map(y => Temporal.PlainDate.from({calendar: 'hebrew', year: y, month: 1, day: 1}).withCalendar('iso8601').toString() + '/' + Temporal.PlainDate.from({calendar: 'hebrew', year: y, month: 1, day: 1}).daysInYear).join(' '));
console.log('persian nowruz: ' + [1300, 1354, 1403, 1404, 1450, 1500].map(y => Temporal.PlainDate.from({calendar: 'persian', year: y, month: 1, day: 1}).withCalendar('iso8601').toString()).join(' '));
"""


ERA_AND_GRAMMAR = r"""
const cals = ['iso8601', 'gregory', 'japanese', 'buddhist', 'roc', 'hebrew', 'islamic-umalqura', 'islamic-civil', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'chinese'];
const eras = ['ce', 'bce', 'gregory', 'gregory-inverse', 'ad', 'bc', 'reiwa', 'heisei', 'showa', 'taisho', 'meiji', 'be', 'roc', 'roc-inverse', 'broc', 'minguo', 'before-roc', 'am', 'aa', 'mundi', 'incar', 'ah', 'bh', 'shaka', 'ap', 'CE', 'xyz'];
const r = f => { try { return f().toString({calendarName: 'never'}); } catch (e) { return e.constructor.name[0]; } };
for (const c of cals) {
  console.log(c + ' eras: ' + eras.map(e => e + '=' + r(() => Temporal.PlainDate.from({calendar: c, era: e, eraYear: 5, month: 1, day: 1}))).join(' '));
  console.log(c + ' eraYear edge: ' + [0, -3, 2 ** 31].map(y => r(() => Temporal.PlainDate.from({calendar: c, era: Temporal.PlainDate.from('2000-01-01').withCalendar(c).era || 'ce', eraYear: y, month: 1, day: 1}))).join(' ') + ' | ym: ' + r(() => Temporal.PlainYearMonth.from({calendar: c, era: Temporal.PlainDate.from('2000-01-01').withCalendar(c).era || 'ce', eraYear: 7, month: 2})) + ' | pdt: ' + r(() => Temporal.PlainDateTime.from({calendar: c, era: Temporal.PlainDate.from('2000-01-01').withCalendar(c).era || 'ce', eraYear: 7, month: 2, day: 3, hour: 4})) + ' | zdt: ' + r(() => Temporal.ZonedDateTime.from({calendar: c, era: Temporal.PlainDate.from('2000-01-01').withCalendar(c).era || 'ce', eraYear: 7, month: 2, day: 3, timeZone: 'UTC'})) + ' | md: ' + r(() => Temporal.PlainMonthDay.from({calendar: c, era: Temporal.PlainDate.from('2000-01-01').withCalendar(c).era || 'ce', eraYear: 1, month: 2, day: 3})));
}
t('fsd NaN', () => Temporal.PlainTime.from('10:00').toString({fractionalSecondDigits: NaN}));
t('fsd Infinity', () => Temporal.Instant.from('2020-01-01T00:00Z').toString({fractionalSecondDigits: Infinity}));
t('fsd -1', () => Temporal.PlainDateTime.from('2020-01-01T00:00').toString({fractionalSecondDigits: -1}));
t('fsd -0.5', () => Temporal.ZonedDateTime.from('2020-01-01T00:00[UTC]').toString({fractionalSecondDigits: -0.5}));
t('fsd 9.99', () => Temporal.Duration.from('PT1.123456789S').toString({fractionalSecondDigits: 9.99}));
t('fsd string num', () => Temporal.PlainTime.from('10:00:00.5').toString({fractionalSecondDigits: '3'}));
t('fsd obj auto', () => Temporal.PlainTime.from('10:00:00.5').toString({fractionalSecondDigits: {toString() { return 'auto'; }}}));
t('dur su invalid', () => Temporal.Duration.from('PT1S').toString({smallestUnit: 'fortnight'}));
t('dur su year', () => Temporal.Duration.from('PT1S').toString({smallestUnit: 'year'}));
t('dur bad mode', () => Temporal.Duration.from('PT1S').toString({roundingMode: 'up'}));
t('su + fsd', () => Temporal.PlainTime.from('10:00:00.123456').toString({smallestUnit: 'millisecond', fractionalSecondDigits: 9}));
t('instant toString bad tz type', () => Temporal.Instant.from('2020-01-01T00:00Z').toString({timeZone: 5}));
t('instant toString tz iso string', () => Temporal.Instant.from('2020-01-01T00:00Z').toString({timeZone: '2020-01-01T00:00+05:00'}));
t('instant toString tz zdt', () => Temporal.Instant.from('2020-01-01T00:00Z').toString({timeZone: Temporal.ZonedDateTime.from('2020-01-01T00:00[Asia/Tokyo]')}));
t('withCalendar iso strings', () => ['2020-01-01[u-ca=xyz]', '2020-01-01T00:00Z', '2020-01-01T00:00Z[u-ca=hebrew]', '2020-01[u-ca=coptic]', '--01-01[u-ca=persian]', '10:00', 'T10:00[u-ca=indian]', '2020-13-01[u-ca=roc]'].map(s => { try { return Temporal.PlainDate.from('2020-06-01').withCalendar(s).calendarId; } catch (e) { return e.constructor.name; } }).join(' '));
t('md grammar', () => ['--12-25', '--1225', '12-25', '1225', '-12-25', '--12-2', '--13-01', '--12-32', '--02-30', '---12-25', '--12-25T00:00', '1972-12-25[u-ca=iso8601]', '--12-25[u-ca=iso8601]', '--12-25[!u-ca=iso8601]', '12-25[foo=bar]', '--12-25[Europe/Paris]', '--12-25Z'].map(s => { try { return Temporal.PlainMonthDay.from(s).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
t('ym grammar', () => ['2020-12', '202012', '+002020-12', '-002020-12', '2020-1', '2020-13', '20201', '2020-12[u-ca=iso8601]', '2020-12[!u-ca=gregory]', '2020-12[Europe/Paris]', '2020-12Z', '2020-12-01T00:00+01:00', '2020-12-01T00:00Z'].map(s => { try { return Temporal.PlainYearMonth.from(s).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
t('time grammar', () => ['T1', 'T123', 'T12345', 'T12:3456', 'T1234:56', '12:34:5', '12:34:56.', '12:34:56.1234567890', 'T12:34:56,000000001', '12:34:56+01', '12:34:56-0130', '12:34:56+01:30:45', '12:34:56[Asia/Tokyo]', '12:34:56[u-ca=gregory]', '12:34:56[!u-ca=gregory]', '2020-01-01T12', '20200101T12', 't12:00', 'T12:00:00z', '12:00:00.5[foo=bar]'].map(s => { try { return Temporal.PlainTime.from(s).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
t('offset grammar', () => ['2020-01-01T00:00+00', '2020-01-01T00:00+0000', '2020-01-01T00:00+00:00:00', '2020-01-01T00:00+00:00:00.000000000', '2020-01-01T00:00+235959', '2020-01-01T00:00+23:59:59.999999999', '2020-01-01T00:00+2400', '2020-01-01T00:00+00:60', '2020-01-01T00:00+0:00', '2020-01-01T00:00+00:0', '2020-01-01T00:00+00:00:0', '2020-01-01T00:00+00:00.5', '2020-01-01T00:00-00:00:00.1'].map(s => { try { return Temporal.Instant.from(s).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
t('annotation grammar', () => ['[u-ca=gregory]', '[U-CA=gregory]', '[u-ca=]', '[=gregory]', '[u-ca==g]', '[a-b-c=x]', '[a_b=x]', '[1a=x]', '[aa=x-y-z]', '[aa=x_y]', '[!aa=b]', '[aa=b][!u-ca=iso8601]', '[Etc/GMT+5][u-ca=roc]', '[America/Argentina/Buenos_Aires]', '[+05:30:00]', '[-23:59]', '[+24:00]', '[UTC][!foo=bar]', '[a.b/c-d_e]', '[./x]', '[x/.]'].map(a => { try { return Temporal.PlainDateTime.from('2020-01-01T00:00' + a).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
t('year grammar', () => ['0000-01-01', '+000000-01-01', '-000000-01-01', '+999999-01-01', '-999999-01-01', '+275760-09-13', '+275760-09-14', '-271821-04-19', '-271821-04-18', '99999-01-01', '+12345-01-01'].map(s => { try { return Temporal.PlainDate.from(s).toString(); } catch (e) { return e.constructor.name; } }).join(' '));
"""


REMAINING_BRANCHES = r"""
const I = Temporal.Instant, Z = Temporal.ZonedDateTime, D = Temporal.Duration, PT = Temporal.PlainTime, PD = Temporal.PlainDate, PDT = Temporal.PlainDateTime;
const x = I.from('2024-06-15T12:34:56.789123456Z');
const z = Z.from('2024-06-15T12:34:56.789123456+02:00[Europe/Paris]');
t('instant toString units', () => ['minute', 'second', 'millisecond', 'microsecond', 'nanosecond', 'minutes', 'seconds'].map(u => x.toString({smallestUnit: u})).join(' '));
t('instant toString digits', () => [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 'auto'].map(n => x.toString({fractionalSecondDigits: n, roundingMode: 'halfExpand'})).join(' '));
t('zdt toString units', () => ['minute', 'second', 'millisecond', 'microsecond', 'nanosecond'].map(u => z.toString({smallestUnit: u, roundingMode: 'ceil'})).join(' '));
t('zdt toString digits', () => [0, 2, 4, 7, 9].map(n => z.toString({fractionalSecondDigits: n, offset: 'never', timeZoneName: 'never'})).join(' '));
t('instant subtract days', () => x.subtract({days: 1}));
t('instant subtract weeks', () => x.subtract({weeks: 1}));
t('instant subtract range', () => I.from('-271821-04-20T00:00Z').subtract({nanoseconds: 1}));
t('instant until other forms', () => [x.until(z), x.since(Z.from('2024-06-15T00:00[Asia/Tokyo]')), x.until('2024-06-15T12:34:56.789123456+00:00[UTC]')].join(' '));
t('instant until bad su', () => x.until('2025-01-01T00:00Z', {smallestUnit: 'day'}));
t('instant until bad lu', () => x.until('2025-01-01T00:00Z', {largestUnit: 'parsec'}));
t('instant until bad su2', () => x.until('2025-01-01T00:00Z', {smallestUnit: 'parsec'}));
t('instant until lu<su', () => x.until('2025-01-01T00:00Z', {largestUnit: 'second', smallestUnit: 'hour'}));
t('time until lu<su', () => PT.from('10:00').until('12:00', {largestUnit: 'minute', smallestUnit: 'hour'}));
t('time until bad lu', () => PT.from('10:00').until('12:00', {largestUnit: 'eon'}));
t('time until bad su', () => PT.from('10:00').until('12:00', {smallestUnit: 'eon'}));
t('time until su day', () => PT.from('10:00').until('12:00', {smallestUnit: 'day'}));
t('time until inc', () => PT.from('10:00').until('12:39:47.123456789', {smallestUnit: 'nanosecond', roundingIncrement: 500, largestUnit: 'minute'}));
t('dur compare equal', () => [D.compare('P1Y2M', 'P1Y2M'), D.compare('P1Y', 'P12M', {relativeTo: '2020-01-01'}), D.compare('-P1D', 'P1D', {relativeTo: '2020-01-01[UTC]'}), D.compare({days: 1e8}, {days: 1e8 - 1})].join());
t('dur compare huge rel', () => D.compare({days: 1e8}, {hours: 1}, {relativeTo: '2020-01-01[UTC]'}));
t('dur compare huge', () => D.compare({days: 104249991374}, {seconds: 1}));
t('zdt transition num', () => z.getTimeZoneTransition(5));
t('zdt transition bool', () => z.getTimeZoneTransition(true));
t('zdt transition obj bad', () => z.getTimeZoneTransition({direction: 'up'}));
t('zdt transition obj missing', () => z.getTimeZoneTransition({}));
t('zdt round ns', () => [z.round('nanosecond'), z.round({smallestUnit: 'nanosecond', roundingIncrement: 500}), z.round({smallestUnit: 'microsecond', roundingIncrement: 250, roundingMode: 'floor'})].join(' '));
t('zdt round ns 1000', () => z.round({smallestUnit: 'nanosecond', roundingIncrement: 1000}));
t('zdt round bad inc', () => z.round({smallestUnit: 'hour', roundingIncrement: 7}));
t('zdt round day inc', () => z.round({smallestUnit: 'day', roundingIncrement: 1, roundingMode: 'ceil'}));
t('zdt round bad unit', () => z.round({smallestUnit: 'week'}));
t('zdt from ignore boundary', () => Z.from('+275760-09-13T00:00+00:00[UTC]', {offset: 'ignore'}));
t('zdt from boundary2', () => Z.from('-271821-04-20T00:00[Etc/GMT-1]'));
t('zdt from boundary3', () => Z.from('+275760-09-13T01:00+01:00[+01:00]'));
t('zdt from boundary4', () => Z.from('+275760-09-13T00:00:00.000000001[UTC]'));
t('rel era bag', () => D.from('P1M').round({largestUnit: 'day', relativeTo: {calendar: 'japanese', era: 'heisei', eraYear: 3, month: 2, day: 1}}));
t('rel era bag zdt', () => D.from('P1M').total({unit: 'hour', relativeTo: {calendar: 'gregory', era: 'bce', eraYear: 3, month: 2, day: 1, timeZone: 'UTC'}}));
t('rel bag negative time', () => D.from('P1M').round({largestUnit: 'day', relativeTo: {year: 2020, month: 1, day: 1, minute: -1}}));
t('rel bag monthCode', () => D.from('P1M').round({largestUnit: 'day', relativeTo: {calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 1}}));
t('rel bag out of range', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: {year: 275760, month: 9, day: 14}}));
t('rel string out of range', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: '+275760-09-14'}));
t('rel string zdt out of range', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: '+275760-09-14T00:00[UTC]'}));
t('rel string fixed tz', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: '2020-01-01T00:00[+05:00]'}));
t('rel string fixed tz offset', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: '2020-01-01T00:00+05:00[+05:00]'}));
t('rel bag tz offset string', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: {year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00[+03:00]'}}));
t('rel bag tz offset string2', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: {year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00[Bad/Zone]'}}));
t('rel bag tz Z', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: {year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00Z'}}));
t('rel bag tz seconds offset', () => D.from('P1D').round({largestUnit: 'hour', relativeTo: {year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00+05:00:30'}}));
t('rel same instant', () => [D.from('PT0S').round({largestUnit: 'year', relativeTo: '2020-01-01T00:00[UTC]'}), D.from('PT0S').total({unit: 'month', relativeTo: '2020-01-01'}), D.from('PT0S').round({smallestUnit: 'month', relativeTo: '2020-01-01T00:00'})].join(' '));
t('pdt until same', () => PDT.from('2020-01-01T00:00').until('2020-01-01T00:00', {largestUnit: 'year', smallestUnit: 'month'}));
t('pdt until edge', () => PDT.from('-271821-04-19T00:00:00.000000001').until('+275760-09-13T00:00', {largestUnit: 'year'}));
t('pd until edge', () => PD.from('-271821-04-19').until('+275760-09-13', {largestUnit: 'year', smallestUnit: 'month', roundingMode: 'ceil'}));
t('zdt until same', () => z.until(z, {largestUnit: 'year', smallestUnit: 'day'}));
t('zdt since total', () => D.from(z.since('2020-02-29T12:00[Europe/Paris]', {largestUnit: 'year'})).total({unit: 'day', relativeTo: '2020-02-29T12:00[Europe/Paris]'}));
const tr = f => { try { return String(f()); } catch (e) { return e.constructor.name; } };
t('dur round nudges', () => ['P1M', 'P2M', '-P1M', 'P11M', 'P1Y11M30D'].map(s => [tr(() => D.from(s).round({smallestUnit: 'month', largestUnit: 'month', roundingMode: 'halfEven', roundingIncrement: 2, relativeTo: '2020-01-31[UTC]'})), tr(() => D.from(s).round({smallestUnit: 'month', roundingMode: 'halfEven', roundingIncrement: 2, relativeTo: '2020-01-31[UTC]'})), tr(() => D.from(s).round({smallestUnit: 'year', roundingMode: 'halfFloor', relativeTo: '2020-02-29'})), tr(() => D.from(s).round({largestUnit: 'week', smallestUnit: 'week', roundingMode: 'halfCeil', relativeTo: '2020-12-31T23:00[America/St_Johns]'}))].join('/')).join(' '));
t('dur round zoned day nudge', () => ['PT23H59M', 'PT24H', 'PT25H', 'PT47H30M', '-PT23H30M', 'P1DT1H'].map(s => [D.from(s).round({smallestUnit: 'day', relativeTo: '2024-03-09T02:30[America/New_York]'}), D.from(s).round({smallestUnit: 'hour', largestUnit: 'day', roundingIncrement: 12, relativeTo: '2024-11-02T01:30-04:00[America/New_York]'}), D.from(s).round({smallestUnit: 'day', roundingMode: 'trunc', relativeTo: '2024-03-10T00:00[America/New_York]'})].join('/')).join(' '));
t('dur round zoned days ceil', () => ['PT1H', 'P2DT12H', '-PT1H'].map(s => D.from(s).round({smallestUnit: 'day', roundingMode: 'ceil', relativeTo: '2024-10-27T00:00[Europe/London]'}).toString()).join(' '));
"""


def test_plain_date_construction_and_parsing(run):
    """CATCHES: PlainDate constructors/from() accepting malformed ISO strings or annotations, wrong overflow handling, wrong error types or messages, wrong limits."""
    _check(run, PLAIN_DATE_PARSE, "plain_date_parse")


def test_plain_date_operations(run):
    """CATCHES: wrong PlainDate getters (ISO week numbering, leap years), month-end clamping in add/subtract, until/since balancing and rounding, toString calendar options."""
    _check(run, PLAIN_DATE_OPS, "plain_date_ops")


def test_plain_time(run):
    """CATCHES: PlainTime parsing ambiguities (T designator), wrapping arithmetic, rounding modes/increments, fractionalSecondDigits/smallestUnit formatting and validation errors."""
    _check(run, PLAIN_TIME, "plain_time")


def test_plain_datetime(run):
    """CATCHES: PlainDateTime parsing, limits, add/until with largestUnit, rounding to day, and DST disambiguation (earlier/later/compatible/reject) in toZonedDateTime."""
    _check(run, PLAIN_DATETIME, "plain_datetime")


def test_year_month_and_month_day(run):
    """CATCHES: PlainYearMonth/PlainMonthDay parsing forms, reference days/years, arithmetic restrictions, toPlainDate conversions and calendar annotation rules."""
    _check(run, YEAR_MONTH_MONTH_DAY, "year_month_month_day")


def test_duration_basic(run):
    """CATCHES: Duration parsing (fractional units, sign, limits), mixed-sign rejection, add/subtract balancing, toString precision and compare with/without relativeTo."""
    _check(run, DURATION_BASIC, "duration_basic")


def test_duration_round_and_total(run):
    """CATCHES: Duration.round/total errors with calendar units, relativeTo parsing (dates, bags, zoned strings with offsets), DST-aware day lengths and fractional totals."""
    _check(run, DURATION_ROUND_TOTAL, "duration_round_total")


def test_instant(run):
    """CATCHES: Instant epoch conversions (BigInt), offset-bearing string parsing, range limits, time-unit-only arithmetic, rounding increments and toString with timeZone."""
    _check(run, INSTANT, "instant")


def test_zoned_parsing_and_offsets(run):
    """CATCHES: ZonedDateTime offset/disambiguation option handling, bag parsing, fixed-offset zones, alias preservation, toString options and equality semantics."""
    _check(run, ZONED_PARSE, "zoned_parse")


def test_zoned_operations_dst(run):
    """CATCHES: ZonedDateTime arithmetic across DST gaps/folds, hoursInDay/startOfDay, with() offset preference, rounding to day, and getTimeZoneTransition walks."""
    _check(run, ZONED_OPS, "zoned_ops")


def test_time_zone_database_sweep(run):
    """CATCHES: wrong IANA offset tables or transition search for many zones (half-hour, 45-minute, southern-hemisphere, abolished-DST zones) and link resolution."""
    _check(run, TZ_SWEEP, "tz_sweep")


def test_calendar_fields(run):
    """CATCHES: wrong non-ISO calendar conversions (hebrew, chinese, islamic variants, persian, indian, coptic, ethiopic, japanese eras) and calendar id canonicalization."""
    _check(run, CALENDAR_FIELDS, "calendar_fields")


def test_calendar_arithmetic(run):
    """CATCHES: wrong month arithmetic in lunisolar/13-month calendars, leap-month constrain/reject, era/eraYear resolution, and calendar-aware year-month/month-day references."""
    _check(run, CALENDAR_ARITH, "calendar_arith")


def test_iso_string_grammar_table(run):
    """CATCHES: from() parsers that accept or reject the wrong RFC 9557 forms for one of the seven Temporal types (offsets, annotations, basic format, edge times)."""
    _check(run, ISO_GRAMMAR, "iso_grammar")


def test_duration_string_table(run):
    """CATCHES: ISO 8601 duration parsers that mishandle unit order, fractions, signs, case, range limits or whitespace."""
    _check(run, DURATION_PARSE_TABLE, "duration_parse_table")


def test_rounding_mode_matrix(run):
    """CATCHES: rounding-mode implementations that confuse floor/trunc or half-even/half-expand for negative values, ties, or calendar-unit differences."""
    _check(run, ROUNDING_MATRIX, "rounding_matrix")


def test_temporal_to_locale_string(run):
    """CATCHES: Temporal toLocaleString/Intl.DateTimeFormat integration errors: calendar mismatch checks, style restrictions per type, forced zone for ZonedDateTime."""
    _check(run, LOCALE_STRINGS, "locale_strings")


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_temporal_from_user_code_all_tiers(run, tier):
    """CATCHES: execution tiers that diverge when Temporal objects flow through loops, destructuring, sort comparators, Maps and private class fields."""
    _check(run, TIERED, "tiered", tier)


def test_error_paths_and_receivers(run):
    """CATCHES: missing or wrong TypeError/RangeError checks for field types, era/eraYear pairing, reject-overflow in calendar arithmetic, relativeTo bags, brand checks and calendar/time-zone argument forms."""
    _check(run, ERROR_PATHS, "error_paths")


def test_relative_rounding_matrix(run):
    """CATCHES: wrong Duration.round/total against PlainDateTime and DST-affected ZonedDateTime relativeTo, and wrong until/since rounding (increments, modes, week/month/year units) for zoned and plain types."""
    _check(run, RELATIVE_ROUNDING, "relative_rounding")


def test_getter_matrix_all_calendars(run):
    """CATCHES: missing/extra prototype getters or methods on any Temporal type, and wrong era/eraYear/month/monthCode/day/week getters for each type in each supported calendar."""
    _check(run, GETTER_MATRIX, "getter_matrix")


def test_with_matrix_all_types(run):
    """CATCHES: wrong with() field merging per type and calendar (era/eraYear pairs, month vs monthCode conflicts, leap-month codes, time and offset fields) under constrain and reject."""
    _check(run, WITH_MATRIX, "with_matrix")


def test_month_day_reference_matrix(run):
    """CATCHES: wrong PlainMonthDay reference-year selection and day clamping per calendar and month code (including leap months and day 30), and wrong UTC-offset string parsing in property bags."""
    _check(run, MONTH_DAY_MATRIX, "month_day_matrix")


def test_calendars_far_past_and_future(run):
    """CATCHES: calendar conversions that break far from the present (astronomical Chinese/Dangi months, Hebrew/Persian new years, tabular Islamic fallbacks, era boundaries) or fail to round-trip."""
    _check(run, FAR_DATES, "far_dates")


def test_era_codes_and_grammar_edges(run):
    """CATCHES: wrong era-code acceptance/aliases per calendar (ce/ad/gregory-inverse, minguo/before-roc, mundi, bh...), eraYear edge values, fractionalSecondDigits coercion, and ISO grammar edge cases for times, offsets, annotations, month-days and years."""
    _check(run, ERA_AND_GRAMMAR, "era_and_grammar")


def test_instant_zoned_duration_branches(run):
    """CATCHES: wrong Instant/ZonedDateTime toString precision handling, Instant.subtract unit checks, until/since option validation order, getTimeZoneTransition argument types, relativeTo range/offset/era bags, and DST-aware day nudging in Duration.round."""
    _check(run, REMAINING_BRANCHES, "remaining_branches")
