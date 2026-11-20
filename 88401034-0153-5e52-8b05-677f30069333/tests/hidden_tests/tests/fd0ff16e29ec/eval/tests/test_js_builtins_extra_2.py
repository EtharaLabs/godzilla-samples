"""Built-ins, extra coverage (Temporal and Intl): with()/withCalendar()/round()/until() option validation,
representable-range limits, Duration arithmetic/rounding/formatting, offset and time-zone resolution
(including sub-minute LMT offsets and DST gaps), non-ISO calendar month codes and leap months, and Intl
NumberFormat / Locale / PluralRules / Collator / Segmenter / DisplayNames / ListFormat / DurationFormat /
RelativeTimeFormat / DateTimeFormat corner cases.

Every program prints labelled lines (results, or exact error name + message) compared to a golden.
Temporal values are always built from fixed ISO strings or fields (never Temporal.Now) and dates passed to
Intl are fixed UTC timestamps.
"""

from conftest import golden

PROG_TEMPORAL_WITH = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, v && typeof v === 'object' && 'toString' in v ? v.toString() : String(v)); } catch (e) { log(label, 'throws', e.name, e.message); } };
const T = Temporal;
const pdt = T.PlainDateTime.from('2020-03-15T10:20:30');
const pd = T.PlainDate.from('2020-03-15');
const pt = T.PlainTime.from('10:20:30');
const ym = T.PlainYearMonth.from('2020-03');
const md = T.PlainMonthDay.from('03-15');
const zdt = T.ZonedDateTime.from('2020-03-15T10:20:30+01:00[Europe/Paris]');
const gpdt = pdt.withCalendar('gregory');
// with() argument validation across types
const kinds = [['pdt', pdt, 'rw'], ['pd', pd, 'w'], ['pt', pt, 'r'], ['ym', ym, ''], ['md', md, ''], ['zdt', zdt, 'rw']];
for (const [name, v, caps] of kinds) {
  tryit(name + '.with calendar', () => v.with({ calendar: 'iso8601', day: 1 }));
  tryit(name + '.with timeZone', () => v.with({ timeZone: 'UTC', day: 1 }));
  tryit(name + '.with temporal', () => v.with(pd));
  tryit(name + '.with month 0', () => v.with({ month: 0 }));
  tryit(name + '.with monthCode num', () => v.with({ monthCode: 5 }));
  tryit(name + '.with monthCode bad', () => v.with({ monthCode: 'M1' }));
  tryit(name + '.with offset num', () => v.with({ offset: 5 }));
  tryit(name + '.with offset str', () => v.with({ offset: '+01:00', hour: 3 }));
  const cdesc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(v), 'calendarId');
  if (cdesc) tryit(name + '.calendarId bad', () => cdesc.get.call(Object.create(Object.getPrototypeOf(v))));
  else log(name + '.calendarId absent');
  tryit(name + '.toJSON', () => v.toJSON());
  if (caps.includes('r')) tryit(name + '.round 5', () => v.round(5));
  if (caps.includes('w')) {
    tryit(name + '.withCalendar()', () => v.withCalendar());
    tryit(name + '.withCalendar(pd)', () => v.withCalendar(T.PlainDate.from('2020-01-01[u-ca=hebrew]')).calendarId);
    tryit(name + '.withCalendar({})', () => v.withCalendar({}));
  }
}
for (const [name, v] of [['gpdt', gpdt], ['gpd', pd.withCalendar('gregory')], ['gym', T.PlainYearMonth.from({ year: 2020, month: 3, calendar: 'gregory' })], ['gmd', T.PlainMonthDay.from({ monthCode: 'M03', day: 15, calendar: 'gregory' })], ['gzdt', zdt.withCalendar('gregory')]]) {
  tryit(name + '.with era+year', () => v.with({ era: 'ce', eraYear: 2021, year: 2021 }));
  tryit(name + '.toJSON', () => v.toJSON());
}
tryit('pdt.from missing month', () => T.PlainDateTime.from({ year: 2020, day: 1 }));
tryit('pdt.from missing day', () => T.PlainDateTime.from({ year: 2020, month: 1 }));
tryit('zdt.from missing month', () => T.ZonedDateTime.from({ year: 2020, day: 1, timeZone: 'UTC' }));
tryit('zdt.from missing day', () => T.ZonedDateTime.from({ year: 2020, month: 1, timeZone: 'UTC' }));
tryit('ym hebrew toPlainDate', () => T.PlainYearMonth.from({ year: 5784, monthCode: 'M05L', calendar: 'hebrew' }).toPlainDate({ day: 10 }));
tryit('ym hebrew toJSON', () => T.PlainYearMonth.from({ year: 5784, monthCode: 'M05', calendar: 'hebrew' }).toJSON());
tryit('md gregory toPlainDate era', () => T.PlainMonthDay.from({ monthCode: 'M02', day: 29, calendar: 'gregory' }).toPlainDate({ era: 'ce', eraYear: 2021 }));
tryit('md gregory toPlainDate bce', () => T.PlainMonthDay.from({ monthCode: 'M02', day: 28, calendar: 'gregory' }).toPlainDate({ era: 'BCE', eraYear: 5 }));
tryit('md toPlainDate prim', () => md.toPlainDate(2020));
tryit('md hebrew toJSON', () => T.PlainMonthDay.from({ monthCode: 'M06L', day: 1, calendar: 'hebrew' }).toJSON());
tryit('md from md opts', () => T.PlainMonthDay.from(md, { overflow: 'bogus' }));
tryit('md from md ok', () => T.PlainMonthDay.from(md, { overflow: 'reject' }));
tryit('md cal obj', () => T.PlainMonthDay.from({ monthCode: 'M01', day: 1, calendar: pd }).calendarId);
tryit('md cal bad', () => T.PlainMonthDay.from({ monthCode: 'M01', day: 1, calendar: {} }));
tryit('md day 0', () => T.PlainMonthDay.from({ monthCode: 'M01', day: 0 }));
tryit('md month 0', () => T.PlainMonthDay.from({ month: 0, day: 1 }));
tryit('md monthCode num', () => T.PlainMonthDay.from({ monthCode: 1, day: 1 }));
tryit('md monthCode bad', () => T.PlainMonthDay.from({ monthCode: 'X01', day: 1 }));
tryit('ym cal obj', () => T.PlainYearMonth.from({ year: 2020, month: 1, calendar: pd }).calendarId);
tryit('pdt cal obj', () => T.PlainDateTime.from({ year: 2020, month: 1, day: 1, calendar: pd }).calendarId);
tryit('zdt cal obj', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', calendar: zdt }).calendarId);
tryit('zdt cal bad', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', calendar: {} }));
tryit('zdt offset opt', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'Europe/Paris', offset: '+01:00' }));
tryit('zdt offset num', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: 5 }));
tryit('zdt offset use', () => T.ZonedDateTime.from('2020-01-01T00:00+05:00[Europe/Paris]', { offset: 'use' }));
tryit('zdt offset prefer sec', () => T.ZonedDateTime.from('1900-01-01T00:00+00:09[Europe/Paris]', { offset: 'prefer' }));
tryit('zdt offset reject sec', () => T.ZonedDateTime.from('1900-01-01T00:00+00:09:21[Europe/Paris]', { offset: 'reject' }));
tryit('zdt tz from string', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00+05:30' }).timeZoneId);
tryit('zdt tz from Z string', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00Z' }).timeZoneId);
tryit('zdt tz from bracket', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00[Asia/Tokyo]' }).timeZoneId);
tryit('zdt tz from bracket off', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00[+03:00]' }).timeZoneId);
tryit('zdt tz from sec offset', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: '2020-01-01T00:00+05:30:30' }).timeZoneId);
tryit('zdt tz obj bad', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: pd }));
tryit('zdt tz num', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 5 }));
tryit('zdt equals offsets', () => T.ZonedDateTime.from('2020-01-01T00:00+01:00[+01:00]').equals(T.ZonedDateTime.from('2020-01-01T00:00+01:00[+01]')));
tryit('instant toString tz offset sec', () => T.Instant.from('2020-01-01T00:00Z').toString({ timeZone: '+05:30' }));
tryit('instant round 5', () => T.Instant.from('2020-01-01T00:00Z').round(5));
tryit('instant toZDT', () => T.Instant.from('2020-01-01T00:00Z').toZonedDateTimeISO('-00:30').toString());
tryit('instant fromEpochNs bool', () => T.Instant.fromEpochNanoseconds(true));
tryit('zdt round 5', () => zdt.round(5));
tryit('zdt.toString bad smallest', () => zdt.toString({ smallestUnit: 'week' }));
tryit('zdt.toString bogus smallest', () => zdt.toString({ smallestUnit: 'bogus' }));
tryit('instant.toString bogus smallest', () => T.Instant.from('2020-01-01T00:00Z').toString({ smallestUnit: 'bogus' }));
tryit('pdt.toString bogus smallest', () => pdt.toString({ smallestUnit: 'bogus' }));
tryit('pt.toString bogus smallest', () => pt.toString({ smallestUnit: 'bogus' }));
tryit('dur round 5', () => T.Duration.from('PT1H').round(5));
tryit('dur total 5', () => T.Duration.from('PT1H').total(5));
tryit('dur round bogus largest', () => T.Duration.from('PT1H').round({ largestUnit: 'bogus' }));
tryit('dur round bogus smallest', () => T.Duration.from('PT1H').round({ smallestUnit: 'bogus' }));
tryit('ym until bogus', () => ym.until('2021-05', { largestUnit: 'bogus' }));
tryit('ym until bogus small', () => ym.until('2021-05', { smallestUnit: 'bogus' }));
tryit('ym until small>large', () => ym.until('2021-05', { smallestUnit: 'year', largestUnit: 'month' }));
tryit('ym until cal mismatch', () => ym.until(T.PlainYearMonth.from({ year: 2020, month: 1, calendar: 'gregory' })));
tryit('ym since cal mismatch', () => ym.since(T.PlainYearMonth.from({ year: 2020, month: 1, calendar: 'gregory' })));
tryit('pdt until cal mismatch', () => pdt.until(gpdt));
tryit('pdt until bogus small', () => pdt.until(pdt, { smallestUnit: 'bogus' }));
tryit('zdt until cal mismatch', () => zdt.until(zdt.withCalendar('gregory')));
tryit('zdt until bogus large', () => zdt.until(zdt, { largestUnit: 'bogus' }));
tryit('zdt until bogus small', () => zdt.until(zdt, { smallestUnit: 'bogus' }));
tryit('zdt until small>large', () => zdt.until(zdt, { smallestUnit: 'day', largestUnit: 'hour' }));
tryit('zdt until auto ms', () => zdt.until(zdt.add({ hours: 25 }), { smallestUnit: 'day' }).toString());
tryit('pd until bogus large', () => pd.until(pd, { largestUnit: 'bogus' }));
tryit('pd until bogus small', () => pd.until(pd, { smallestUnit: 'bogus' }));
tryit('pd until small>large', () => pd.until(pd, { smallestUnit: 'month', largestUnit: 'day' }));
tryit('pd until auto', () => pd.until('2021-07-04', { smallestUnit: 'month' }).toString());
tryit('opts prim', () => pd.add({ days: 1 }, 5));
tryit('opts prim2', () => T.Duration.from('P1D').round({ smallestUnit: 'hour', relativeTo: 5 }));
console.log(out.join('\n'));
"""

PROG_TEMPORAL_LIMITS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, String(v)); } catch (e) { log(label, 'throws', e.name, e.message); } };
const T = Temporal;
// limits
tryit('ym min-1', () => T.PlainYearMonth.from('-271821-03'));
tryit('ym min', () => T.PlainYearMonth.from('-271821-04'));
tryit('ym max', () => T.PlainYearMonth.from('+275760-09'));
tryit('ym max+1', () => T.PlainYearMonth.from('+275760-10'));
tryit('ym year over', () => T.PlainYearMonth.from({ year: 275761, month: 1 }));
tryit('ym ctor over', () => new T.PlainYearMonth(275760, 10));
tryit('ym ctor under', () => new T.PlainYearMonth(-271821, 3));
tryit('ym ctor year under', () => new T.PlainYearMonth(-271822, 12));
tryit('ym add over', () => T.PlainYearMonth.from('+275760-09').add({ months: 1 }));
tryit('ym str date out', () => T.PlainYearMonth.from('+275760-09-14'));
tryit('ym str date in', () => T.PlainYearMonth.from('+275760-09-13'));
tryit('ym until extreme', () => T.PlainYearMonth.from('-271821-04').until('+275760-09', { largestUnit: 'years' }));
tryit('ym until extreme round', () => T.PlainYearMonth.from('-271821-04').until('+275760-09', { smallestUnit: 'year', roundingIncrement: 1000 }));
tryit('md str out', () => T.PlainMonthDay.from('+275760-09-14'));
tryit('md str in', () => T.PlainMonthDay.from('--12-25'));
tryit('md str bad dash', () => T.PlainMonthDay.from('-12-25'));
tryit('md str bad', () => T.PlainMonthDay.from('--1x-25'));
tryit('pd max add', () => T.PlainDate.from('+275760-09-13').add({ days: 1 }));
tryit('pd min sub', () => T.PlainDate.from('-271821-04-19').subtract({ days: 1 }));
tryit('pd with over', () => T.PlainDate.from('+275760-09-13').with({ day: 14 }));
tryit('pd toPDT over', () => T.PlainDate.from('-271821-04-19').toPlainDateTime('00:00'));
tryit('pd toPDT ok', () => T.PlainDate.from('-271821-04-19').toPlainDateTime('00:00:00.000000001'));
tryit('pd toZDT over', () => T.PlainDate.from('-271821-04-19').toZonedDateTime({ timeZone: 'UTC', plainTime: '00:00' }));
tryit('pd toZDT over2', () => T.PlainDate.from('+275760-09-13').toZonedDateTime({ timeZone: 'UTC', plainTime: '01:00' }));
tryit('pdt from over', () => T.PlainDateTime.from('-271821-04-19T00:00'));
tryit('pdt ctor over', () => new T.PlainDateTime(-271821, 4, 19, 0, 0));
tryit('pdt add over', () => T.PlainDateTime.from('+275760-09-13T00:00').add({ days: 1 }));
tryit('pdt with over', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').with({ nanosecond: 0 }));
tryit('pdt withPlainTime over', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').withPlainTime('00:00'));
tryit('pdt round over', () => T.PlainDateTime.from('+275760-09-13T23:59:59.999').round({ smallestUnit: 'day' }));
tryit('pdt toString round over', () => T.PlainDateTime.from('+275760-09-13T23:59:59.999').toString({ smallestUnit: 'second', roundingMode: 'ceil' }));
tryit('pdt withCalendar edge', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').withCalendar('gregory'));
tryit('pdt until over', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').until(T.PlainDateTime.from('+275760-09-13T00:00'), { largestUnit: 'years' }));
tryit('pdt until rounding big', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').until(T.PlainDateTime.from('+275760-09-13T00:00'), { smallestUnit: 'year', roundingIncrement: 5 }));
tryit('pt toPDT', () => T.PlainTime.from('00:00').toPlainDateTime?.('2020-01-01'));
tryit('zdt from over', () => T.ZonedDateTime.from({ year: -271821, month: 4, day: 19, timeZone: '-01:00' }));
tryit('zdt from over2', () => T.ZonedDateTime.from({ year: 275760, month: 9, day: 13, hour: 1, timeZone: 'UTC' }));
tryit('zdt with over', () => T.ZonedDateTime.from('+275760-09-13T00:00Z[UTC]').with({ hour: 1 }));
tryit('zdt with offset ignore over', () => T.ZonedDateTime.from('+275760-09-13T00:00Z[UTC]').with({ day: 14 }, { offset: 'ignore' }));
tryit('zdt withPlainTime over', () => T.ZonedDateTime.from('+275760-09-13T00:00Z[UTC]').withPlainTime('01:00'));
tryit('zdt startOfDay edge', () => T.ZonedDateTime.from('-271821-04-20T00:00+00:00[UTC]').startOfDay());
tryit('zdt rel over', () => T.Duration.from('P1D').round({ smallestUnit: 'day', relativeTo: { year: 275760, month: 9, day: 13, timeZone: 'UTC' } }));
tryit('zdt rel far', () => T.Duration.from('P1D').total({ unit: 'day', relativeTo: '+200000-01-01T00:00[UTC]' }));
// duration toString precision
for (const su of ['second', 'millisecond', 'microsecond', 'nanosecond']) tryit('dur ts ' + su, () => T.Duration.from('PT1.123456789S').toString({ smallestUnit: su }));
tryit('dur ts digits auto neg', () => T.Duration.from('-PT1.5S').toString({ fractionalSecondDigits: 'auto' }));
tryit('dur ts round neg', () => T.Duration.from('-PT1.987654321S').toString({ fractionalSecondDigits: 2, roundingMode: 'floor' }));
tryit('dur parse trailing', () => T.Duration.from('PT1'));
tryit('dur parse trailing2', () => T.Duration.from('P1Y2'));
tryit('dur compare huge', () => T.Duration.compare({ seconds: Number.MAX_SAFE_INTEGER }, { nanoseconds: 1 }));
tryit('dur compare huge2', () => T.Duration.compare({ seconds: 9007199254740991, nanoseconds: 999999999 }, { seconds: -9007199254740991 }));
tryit('dur largest default', () => [T.Duration.from('PT5S'), T.Duration.from('PT0.005S'), T.Duration.from('PT0.000005S'), T.Duration.from('PT0.000000005S')].map(d => d.round({ smallestUnit: 'nanosecond' }).toString()).join(','));
tryit('dur round auto largest', () => [T.Duration.from({ seconds: 100 }), T.Duration.from({ milliseconds: 100000 }), T.Duration.from({ microseconds: 100000000 }), T.Duration.from({ nanoseconds: 100000000000 })].map(d => d.round({ largestUnit: 'auto', smallestUnit: 'nanosecond' }).toString()).join(','));
tryit('dur round time overflow', () => T.Duration.from({ seconds: 9007199254740991 }).round({ smallestUnit: 'second', roundingIncrement: 30, roundingMode: 'ceil' }));
tryit('dur total micro', () => T.Duration.from({ microseconds: 1500 }).total('millisecond'));
tryit('dur negated zero', () => T.Duration.from('PT0S').negated().toString() + ' ' + T.Duration.from('PT0S').abs().toString());
tryit('dur round incr days', () => T.Duration.from('P10D').round({ smallestUnit: 'day', roundingIncrement: 7, relativeTo: '2020-01-01' }));
tryit('dur round incr months', () => T.Duration.from('P10M').round({ smallestUnit: 'month', roundingIncrement: 4, relativeTo: '2020-01-01' }));
tryit('dur round incr years', () => T.Duration.from('P10Y').round({ smallestUnit: 'year', roundingIncrement: 3, relativeTo: '2020-01-01' }));
tryit('dur round incr weeks', () => T.Duration.from('P10W').round({ smallestUnit: 'week', roundingIncrement: 3, relativeTo: '2020-01-01' }));
tryit('dur round rel zdt dst', () => T.Duration.from('P1M').round({ smallestUnit: 'hour', relativeTo: '2020-03-01T02:30[America/New_York]' }));
tryit('dur total rel zdt', () => T.Duration.from('P1M10DT5H').total({ unit: 'month', relativeTo: '2020-03-01T02:30[America/New_York]' }));
tryit('dur total rel zdt week', () => T.Duration.from('P3W').total({ unit: 'week', relativeTo: '2020-10-25T01:30[Europe/London]' }));
// offsets
tryit('offset sec 60', () => T.ZonedDateTime.from('2020-01-01T00:00+01:00:60[+01:00]'));
tryit('offset trailing', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: '+01:00x' }));
tryit('offset sec ok', () => T.ZonedDateTime.from({ year: 1900, month: 1, day: 1, timeZone: 'Europe/Amsterdam', offset: '+00:19:32' }, { offset: 'reject' }));
tryit('offset prefer mismatch', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'Europe/Amsterdam', offset: '+05:00' }, { offset: 'prefer' }));
tryit('offset use', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'Europe/Amsterdam', offset: '+05:00' }, { offset: 'use' }));
tryit('offset ignore gap', () => T.ZonedDateTime.from({ year: 2020, month: 3, day: 29, hour: 2, minute: 30, timeZone: 'Europe/Amsterdam', offset: '+01:00' }, { offset: 'ignore', disambiguation: 'earlier' }));
tryit('instant tz sec offset', () => T.Instant.from('1900-01-01T00:00Z').toString({ timeZone: 'Europe/Amsterdam' }));
tryit('instant tz sec offset2', () => T.Instant.from('1900-01-01T00:00Z').toZonedDateTimeISO('Europe/Amsterdam').toString());
tryit('instant tz sec offset round', () => T.Instant.from('1900-01-01T00:00Z').toZonedDateTimeISO('Europe/Amsterdam').toString({ offset: 'auto' }));
tryit('instant from offset sec', () => T.Instant.from('2020-01-01T00:00:00+01:30:15'));
tryit('instant from bad offset', () => T.Instant.from('2020-01-01T00:00:00+1'));
tryit('tz equals utc', () => T.ZonedDateTime.from('2020-01-01T00:00Z[UTC]').equals(T.ZonedDateTime.from('2020-01-01T00:00Z[Etc/UTC]')));
tryit('tz equals off/iana', () => T.ZonedDateTime.from('2020-01-01T00:00Z[+00:00]').equals(T.ZonedDateTime.from('2020-01-01T00:00Z[UTC]')));
tryit('zdt tz lower utc', () => T.ZonedDateTime.from('2020-01-01T00:00Z[utc]').timeZoneId);
tryit('zdt tz bad offset bracket', () => T.ZonedDateTime.from('2020-01-01T00:00+01:00[+01:00:30]'));
tryit('zdt getTimeZoneTransition', () => T.ZonedDateTime.from('2020-06-01T00:00[Europe/Paris]').getTimeZoneTransition('next').toString());
tryit('zdt hoursInDay', () => T.ZonedDateTime.from('2020-03-29T12:00[Europe/Paris]').hoursInDay);
tryit('zdt round day dst', () => T.ZonedDateTime.from('2020-03-29T12:00[Europe/Paris]').round({ smallestUnit: 'day' }).toString());
tryit('zdt round day lord howe', () => T.ZonedDateTime.from('2020-10-04T12:00[Australia/Lord_Howe]').round({ smallestUnit: 'day', roundingMode: 'ceil' }).toString());
tryit('zdt round day samoa', () => T.ZonedDateTime.from('2011-12-29T12:00[Pacific/Apia]').round({ smallestUnit: 'day' }).toString());
tryit('zdt since round month', () => T.ZonedDateTime.from('2020-03-29T02:30+02:00[Europe/Paris]').since(T.ZonedDateTime.from('2019-10-27T02:30+01:00[Europe/Paris]'), { largestUnit: 'months', smallestUnit: 'hour', roundingIncrement: 3 }).toString());
tryit('zdt until round days', () => T.ZonedDateTime.from('2020-10-25T02:30+02:00[Europe/Paris]').until(T.ZonedDateTime.from('2020-11-25T01:30+01:00[Europe/Paris]'), { largestUnit: 'days', smallestUnit: 'minute', roundingIncrement: 15, roundingMode: 'halfExpand' }).toString());
tryit('zdt until weeks', () => T.ZonedDateTime.from('2020-01-01T00:00[UTC]').until(T.ZonedDateTime.from('2020-03-15T12:00[UTC]'), { largestUnit: 'weeks', smallestUnit: 'days' }).toString());
tryit('pdt until weeks', () => T.PlainDateTime.from('2020-01-01T00:00').until(T.PlainDateTime.from('2020-03-15T12:00'), { largestUnit: 'weeks', smallestUnit: 'days', roundingMode: 'halfEven' }).toString());
tryit('pd until weeks', () => T.PlainDate.from('2020-01-01').until('2020-03-15', { largestUnit: 'weeks', smallestUnit: 'weeks', roundingMode: 'halfEven' }).toString());
console.log(out.join('\n'));
"""

PROG_TEMPORAL_OPTIONS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, String(v)); } catch (e) { log(label, 'throws', e.name, e.message); } };
const T = Temporal;
const zdt = T.ZonedDateTime.from('2020-03-15T10:20:30+01:00[Europe/Paris]');
tryit('zdt ctor no tz', () => new T.ZonedDateTime(0n));
tryit('zdt ctor tz num', () => new T.ZonedDateTime(0n, 5));
tryit('zdt ctor bad tz', () => new T.ZonedDateTime(0n, '2020-01-01T00:00Z'));
tryit('zdt ctor bad cal', () => new T.ZonedDateTime(0n, 'UTC', 'bogus'));
tryit('zdt ctor cal num', () => new T.ZonedDateTime(0n, 'UTC', 5));
tryit('zdt ctor cal alias', () => new T.ZonedDateTime(0n, '+05:30', 'ISO8601').toString());
tryit('zdt toLocaleString bad recv', () => T.ZonedDateTime.prototype.toLocaleString.call(5));
tryit('zdt from bad disamb', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC' }, { disambiguation: 'bogus' }));
tryit('zdt from bad offset opt', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC' }, { offset: 'bogus' }));
tryit('zdt with bad disamb', () => zdt.with({ hour: 1 }, { disambiguation: 'bogus' }));
tryit('zdt with bad offset opt', () => zdt.with({ hour: 1 }, { offset: 'bogus' }));
tryit('zdt with bad offset', () => zdt.with({ offset: 'bogus' }));
tryit('zdt with offset use', () => zdt.with({ hour: 3, offset: '+05:00' }, { offset: 'use' }).toString());
tryit('zdt with offset reject', () => zdt.with({ hour: 3, offset: '+05:00' }, { offset: 'reject' }).toString());
tryit('zdt toString bad calendarName', () => zdt.toString({ calendarName: 'bogus' }));
tryit('zdt toString bad offset', () => zdt.toString({ offset: 'bogus' }));
tryit('zdt toString bad tzName', () => zdt.toString({ timeZoneName: 'bogus' }));
tryit('zdt toString critical', () => zdt.withCalendar('japanese').toString({ calendarName: 'critical', timeZoneName: 'critical' }));
tryit('zdt round bad mode', () => zdt.round({ smallestUnit: 'day', roundingMode: 'bogus' }));
tryit('pdt toZDT bad disamb', () => T.PlainDateTime.from('2020-01-01T00:00').toZonedDateTime('UTC', { disambiguation: 'bogus' }));
tryit('pdt toZDT over', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').toZonedDateTime('UTC'));
tryit('pdt toZDT over west', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').toZonedDateTime('-01:00'));
tryit('pdt add reject', () => T.PlainDateTime.from('2020-01-31T00:00').add({ months: 1 }, { overflow: 'reject' }));
tryit('pdt add bad overflow', () => T.PlainDateTime.from('2020-01-31T00:00').add({ months: 1 }, { overflow: 'bogus' }));
tryit('pdt round floor over', () => T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').round({ smallestUnit: 'minute', roundingMode: 'floor' }));
tryit('pdt from bad cal', () => T.PlainDateTime.from('2020-01-01T00:00[u-ca=bogus]'));
tryit('pdt from bag over', () => T.PlainDateTime.from({ year: -271821, month: 4, day: 19 }));
tryit('pdt until bogus largest', () => T.PlainDateTime.from('2020-01-01T00:00').until('2021-01-01T00:00', { largestUnit: 'bogus' }));
tryit('pdt until small>large', () => T.PlainDateTime.from('2020-01-01T00:00').until('2021-01-01T00:00', { smallestUnit: 'year', largestUnit: 'day' }));
tryit('ym from far nonISO', () => T.PlainYearMonth.from('+275760-09-14[u-ca=gregory]'));
tryit('md from far nonISO', () => T.PlainMonthDay.from('+275760-09-14[u-ca=gregory]'));
tryit('md with day reject', () => T.PlainMonthDay.from('02-10').with({ day: 30 }, { overflow: 'reject' }));
tryit('md with day 0', () => T.PlainMonthDay.from('02-10').with({ day: 0 }));
tryit('md toPlainDate far', () => T.PlainMonthDay.from('02-10').toPlainDate({ year: 400000 }));
tryit('md gregory far year', () => T.PlainMonthDay.from({ calendar: 'gregory', year: 275760, monthCode: 'M12', day: 1 }));
for (const code of ['M01L', 'M02L', 'M11L', 'M12L', 'M09L']) {
  tryit('chinese md ' + code + ' reject', () => T.PlainMonthDay.from({ calendar: 'chinese', monthCode: code, day: 30 }, { overflow: 'reject' }).toString());
  tryit('chinese md ' + code, () => T.PlainMonthDay.from({ calendar: 'chinese', monthCode: code, day: 30 }).toString());
}
for (const cal of ['hebrew', 'islamic-civil', 'islamic-umalqura', 'persian', 'indian', 'coptic', 'ethiopic', 'dangi']) {
  tryit(cal + ' md day 31 reject', () => T.PlainMonthDay.from({ calendar: cal, monthCode: 'M01', day: 31 }, { overflow: 'reject' }).toString());
  tryit(cal + ' md M12 day 30', () => T.PlainMonthDay.from({ calendar: cal, monthCode: 'M12', day: 30 }).toString());
  tryit(cal + ' md M05L', () => T.PlainMonthDay.from({ calendar: cal, monthCode: 'M05L', day: 29 }).toString());
}
tryit('offset sec 60', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: '+00:00:60' }));
tryit('offset frac junk', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: '+00:00:00.5x' }));
tryit('offset colon junk', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: '+00:00:' }));
tryit('instant tostring tz iso sec', () => T.Instant.from('2020-01-01T00:00Z').toString({ timeZone: '2020-01-01T00:00+01:00:30' }));
tryit('instant tostring tz iso', () => T.Instant.from('2020-01-01T00:00Z').toString({ timeZone: '2020-01-01T00:00+01:30' }));
tryit('instant tostring tz Z', () => T.Instant.from('2020-01-01T00:00Z').toString({ timeZone: '2020-01-01T00:00Z' }));
tryit('instant tostring tokyo lmt', () => T.Instant.from('1880-01-01T00:00Z').toString({ timeZone: 'Asia/Tokyo' }));
tryit('instant tostring brussels', () => T.Instant.from('1885-01-01T00:00Z').toString({ timeZone: 'Europe/Brussels' }));
tryit('zdt tokyo lmt', () => { const z = T.Instant.from('1880-01-01T00:00Z').toZonedDateTimeISO('Asia/Tokyo'); return z.offset + ' ' + z.offsetNanoseconds + ' ' + z.toString(); });
tryit('zdt from tokyo prefer', () => T.ZonedDateTime.from('1880-01-01T09:18:59+09:19[Asia/Tokyo]').toString());
tryit('zdt from tokyo reject', () => T.ZonedDateTime.from('1880-01-01T09:18:59+09:19[Asia/Tokyo]', { offset: 'reject' }).toString());
tryit('zdt from tokyo exact', () => T.ZonedDateTime.from('1880-01-01T09:18:59+09:18:59[Asia/Tokyo]', { offset: 'reject' }).toString());
tryit('zdt compare bag offset', () => T.ZonedDateTime.compare({ year: 2020, month: 1, day: 1, timeZone: 'Europe/Paris', offset: '+01:00' }, '2020-01-01T00:00+01:00[Europe/Paris]'));
tryit('zdt compare bag bad offset', () => T.ZonedDateTime.compare({ year: 2020, month: 1, day: 1, timeZone: 'Europe/Paris', offset: 'x' }, zdt));
tryit('zdt from bad cal', () => T.ZonedDateTime.from('2020-01-01T00:00Z[UTC][u-ca=bogus]'));
tryit('zdt withPlainTime over', () => T.ZonedDateTime.from('-271821-04-19T23:00-01:00[-01:00]').withPlainTime('00:00'));
tryit('zdt startOfDay min', () => T.ZonedDateTime.from('-271821-04-19T23:00-01:00[-01:00]').startOfDay());
tryit('dur relTo cal obj', () => T.Duration.from('P1M').round({ smallestUnit: 'day', relativeTo: { year: 2020, month: 1, day: 31, calendar: T.PlainDate.from('2020-01-01') } }).toString());
tryit('dur relTo cal bad', () => T.Duration.from('P1M').round({ smallestUnit: 'day', relativeTo: { year: 2020, month: 1, day: 31, calendar: {} } }));
tryit('dur relTo offset', () => T.Duration.from('P1M').round({ smallestUnit: 'day', relativeTo: { year: 2020, month: 1, day: 31, timeZone: 'Europe/Paris', offset: '+01:00' } }).toString());
tryit('dur relTo bad offset', () => T.Duration.from('P1M').round({ smallestUnit: 'day', relativeTo: { year: 2020, month: 1, day: 31, timeZone: 'Europe/Paris', offset: 7 } }));
tryit('dur relTo far zdt', () => T.Duration.from('P1D').total({ unit: 'day', relativeTo: { year: 275760, month: 9, day: 12, timeZone: 'UTC' } }));
tryit('dur round relTo zdt err', () => T.Duration.from('P1Y').round({ smallestUnit: 'day', relativeTo: '+275760-09-12T00:00Z[UTC]' }));
tryit('dur round relTo pd err', () => T.Duration.from('P1Y').round({ smallestUnit: 'day', relativeTo: '+275760-09-12' }));
tryit('dur total relTo pd err', () => T.Duration.from('P1Y').total({ unit: 'month', relativeTo: '+275760-09-12' }));
tryit('dur total relTo zdt err', () => T.Duration.from('P1Y').total({ unit: 'month', relativeTo: '+275760-09-12T00:00Z[UTC]' }));
tryit('dur round week relTo zdt', () => T.Duration.from('P5W3D').round({ smallestUnit: 'week', roundingMode: 'halfExpand', relativeTo: '2020-03-01T00:00[Europe/Paris]' }).toString());
tryit('dur round months zdt huge', () => T.Duration.from({ months: 3, hours: 1000 }).round({ largestUnit: 'months', smallestUnit: 'month', relativeTo: '2020-03-01T00:00[America/Sao_Paulo]' }).toString());
tryit('ym until incr', () => T.PlainYearMonth.from('2020-01').until('2031-08', { smallestUnit: 'year', roundingIncrement: 4 }).toString());
tryit('ym until incr extreme', () => T.PlainYearMonth.from('-271821-04').until('+275760-09', { smallestUnit: 'month', roundingIncrement: 7 }).toString());
tryit('pd until incr', () => T.PlainDate.from('2020-01-01').until('2031-08-15', { smallestUnit: 'month', roundingIncrement: 5, largestUnit: 'year' }).toString());
const cals = { hebrew: ['am', 5784], chinese: [null, 2023], coptic: ['am', 1740], gregory: ['ce', 2023], japanese: ['reiwa', 5] };
for (const [cal, [era, y]] of Object.entries(cals)) {
  tryit(cal + ' add month reject', () => T.PlainDate.from({ calendar: cal, year: y, month: 1, day: 30 }).add({ months: 1 }, { overflow: 'reject' }).toString());
  tryit(cal + ' add years+month reject', () => T.PlainDate.from({ calendar: cal, year: y, month: 1, day: 30 }).add({ years: 1, months: 1 }, { overflow: 'reject' }).toString());
  tryit(cal + ' md huge year', () => T.PlainMonthDay.from({ calendar: cal, year: 400000, month: 2, day: 3 }).toString());
  if (era) {
    tryit(cal + ' md huge eraYear', () => T.PlainMonthDay.from({ calendar: cal, era, eraYear: 900000, month: 2, day: 3 }).toString());
    if (cal === 'gregory' || cal === 'japanese') tryit(cal + ' era year disagree', () => T.PlainDate.from({ calendar: cal, day: 1, era, eraYear: y, year: y + 1, month: 1 }).toString());
  }
}
console.log(out.join('\n'));
"""

PROG_TEMPORAL_CALENDARS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, String(v)); } catch (e) { log(label, 'throws', e.name, e.message); } };
const T = Temporal;
tryit('pdt bag year over', () => T.PlainDateTime.from({ year: 275761, month: 1, day: 1 }));
tryit('zdt bag year over', () => T.ZonedDateTime.from({ year: 275761, month: 1, day: 1, timeZone: 'UTC' }));
tryit('pdt bag reject', () => T.PlainDateTime.from({ year: 2021, month: 2, day: 29 }, { overflow: 'reject' }));
tryit('zdt bag reject', () => T.ZonedDateTime.from({ year: 2021, month: 2, day: 29, timeZone: 'UTC' }, { overflow: 'reject' }));
tryit('ym bag reject', () => T.PlainYearMonth.from({ year: 2021, month: 13 }, { overflow: 'reject' }));
tryit('md bag reject', () => T.PlainMonthDay.from({ month: 2, day: 30 }, { overflow: 'reject' }));
tryit('pd with reject', () => T.PlainDate.from('2021-01-31').with({ month: 2 }, { overflow: 'reject' }));
tryit('pdt with reject', () => T.PlainDateTime.from('2021-01-31T00:00').with({ month: 2 }, { overflow: 'reject' }));
tryit('ym with reject', () => T.PlainYearMonth.from('2021-01').with({ month: 13 }, { overflow: 'reject' }));
tryit('pd withCalendar num', () => T.PlainDate.from('2021-01-31').withCalendar(5));
tryit('pdt withCalendar num', () => T.PlainDateTime.from('2021-01-31T00:00').withCalendar(5));
tryit('zdt withCalendar num', () => T.ZonedDateTime.from('2021-01-31T00:00Z[UTC]').withCalendar(5));
tryit('pd from cal num', () => T.PlainDate.from({ year: 2020, month: 1, day: 1, calendar: 5 }));
tryit('pd ctor cal num', () => new T.PlainDate(2020, 1, 1, 5));
for (const s of ['1214', '12-14', '--12-14', '-12-14', '1232', '0229', '1130', '2021-12', '202112', '12:14', 'T1214', '1214[u-ca=iso8601]', '1214Z', '12-31', '--1314', '0230', '1301']) tryit('pt from ' + s, () => T.PlainTime.from(s));
// Hebrew / Persian year boundaries over a long span (exercise the year-estimate corrections)
const hb = [], pr = [];
for (let y = 1500; y <= 2500; y += 7) {
  for (const md of ['09-05', '09-15', '09-25', '10-05', '03-19', '03-20', '03-21', '03-22']) {
    const d = T.PlainDate.from(y + '-' + md);
    const h = d.withCalendar('hebrew'), p = d.withCalendar('persian');
    hb.push(h.year * 100 + h.month); pr.push(p.year * 100 + p.month);
  }
}
const sum = a => a.reduce((x, y) => (x * 31 + y) % 1000000007, 7);
log('hebrew checksum', hb.length, sum(hb), hb.slice(0, 8).join(','));
log('persian checksum', pr.length, sum(pr), pr.slice(-8).join(','));
for (const y of [-2000, -500, 1, 622, 623, 3000, 9999]) {
  tryit('hebrew/persian ' + y, () => { const d = T.PlainDate.from({ year: y, month: 3, day: 21 }); return [d.withCalendar('hebrew').toString(), d.withCalendar('persian').toString(), d.withCalendar('islamic-civil').toString(), d.withCalendar('indian').toString()].join(' '); });
}
tryit('coptic until months', () => T.PlainDate.from({ calendar: 'coptic', year: 1739, month: 13, day: 5 }).until(T.PlainDate.from({ calendar: 'coptic', year: 1742, month: 2, day: 1 }), { largestUnit: 'months' }).toString());
tryit('coptic add months', () => T.PlainDate.from({ calendar: 'coptic', year: 1739, month: 12, day: 30 }).add({ months: 1 }).toString() + ' ' + T.PlainDate.from({ calendar: 'coptic', year: 1739, month: 13, day: 5 }).add({ months: 13 }).toString());
tryit('ethioaa months', () => { const d = T.PlainDate.from({ calendar: 'ethioaa', year: 7515, month: 13, day: 1 }); return [d.monthsInYear, d.add({ months: 1 }).toString(), d.subtract({ months: 14 }).toString()]; });
tryit('islamic add months', () => T.PlainDate.from({ calendar: 'islamic-civil', year: 1445, month: 12, day: 30 }).add({ months: 1, years: 1 }, { overflow: 'constrain' }).toString());
tryit('hebrew leap until', () => T.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 15 }).until(T.PlainDate.from({ calendar: 'hebrew', year: 5787, monthCode: 'M05L', day: 15 }), { largestUnit: 'years' }).toString());
tryit('hebrew leap since', () => T.PlainDate.from({ calendar: 'hebrew', year: 5787, monthCode: 'M05L', day: 30 }).since(T.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30 }), { largestUnit: 'months' }).toString());
tryit('hebrew leap to adar', () => T.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30 }).until(T.PlainDate.from({ calendar: 'hebrew', year: 5785, monthCode: 'M06', day: 29 }), { largestUnit: 'years' }).toString());
tryit('hebrew adar to leap', () => T.PlainDate.from({ calendar: 'hebrew', year: 5783, monthCode: 'M06', day: 29 }).until(T.PlainDate.from({ calendar: 'hebrew', year: 5784, monthCode: 'M05L', day: 30 }), { largestUnit: 'years' }).toString());
tryit('chinese leap until', () => T.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 10 }).until(T.PlainDate.from({ calendar: 'chinese', year: 2025, monthCode: 'M06L', day: 10 }), { largestUnit: 'years' }).toString());
tryit('chinese leap since', () => T.PlainDate.from({ calendar: 'chinese', year: 2025, monthCode: 'M06L', day: 29 }).since(T.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 29 }), { largestUnit: 'years' }).toString());
tryit('chinese leap to regular', () => T.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 15 }).until(T.PlainDate.from({ calendar: 'chinese', year: 2024, monthCode: 'M02', day: 15 }), { largestUnit: 'years' }).toString());
tryit('chinese regular to leap', () => T.PlainDate.from({ calendar: 'chinese', year: 2022, monthCode: 'M02', day: 15 }).until(T.PlainDate.from({ calendar: 'chinese', year: 2023, monthCode: 'M02L', day: 15 }), { largestUnit: 'years' }).toString());
tryit('gregory clamp until', () => T.PlainDate.from({ calendar: 'gregory', year: 2020, month: 2, day: 29 }).until(T.PlainDate.from({ calendar: 'gregory', year: 2021, month: 2, day: 28 }), { largestUnit: 'years' }).toString());
tryit('gregory clamp until 31', () => T.PlainDate.from({ calendar: 'gregory', year: 2020, month: 1, day: 31 }).until(T.PlainDate.from({ calendar: 'gregory', year: 2020, month: 4, day: 30 }), { largestUnit: 'months' }).toString());
tryit('japanese clamp since', () => T.PlainDate.from({ calendar: 'japanese', year: 2020, month: 3, day: 31 }).since(T.PlainDate.from({ calendar: 'japanese', year: 2020, month: 2, day: 29 }), { largestUnit: 'months' }).toString());
console.log(out.join('\n'));
"""

PROG_TEMPORAL_DURATION_OFFSETS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, String(v)); } catch (e) { log(label, 'throws', e.name, e.message); } };
const T = Temporal;
const D = T.Duration;
tryit('dur add sec+ms', () => D.from({ seconds: 5 }).add({ milliseconds: 1500 }));
tryit('dur add ms+us', () => D.from({ milliseconds: 5 }).add({ microseconds: 1500 }));
tryit('dur add us+ns', () => D.from({ microseconds: 5 }).add({ nanoseconds: 1500 }));
tryit('dur add ns+ns', () => D.from({ nanoseconds: 5 }).add({ nanoseconds: 1500 }));
tryit('dur sub sec-min', () => D.from({ seconds: 5 }).subtract({ minutes: 1 }));
tryit('dur sub mixed', () => D.from({ hours: 1, nanoseconds: 3 }).subtract({ milliseconds: 1 }));
tryit('dur add days', () => D.from({ days: 1, seconds: 5 }).add({ hours: 30 }));
tryit('dur add years', () => D.from({ years: 1 }).add({ days: 1 }));
tryit('md with leap code islamic', () => T.PlainMonthDay.from({ calendar: 'islamic-civil', monthCode: 'M05', day: 1 }).with({ monthCode: 'M05L' }));
tryit('md with leap code persian', () => T.PlainMonthDay.from({ calendar: 'persian', monthCode: 'M05', day: 1 }).with({ monthCode: 'M05L' }, { overflow: 'reject' }));
tryit('md with leap code gregory', () => T.PlainMonthDay.from({ calendar: 'gregory', monthCode: 'M05', day: 1 }).with({ monthCode: 'M05L' }));
tryit('md with leap code hebrew M01L', () => T.PlainMonthDay.from({ calendar: 'hebrew', monthCode: 'M05', day: 1 }).with({ monthCode: 'M01L' }));
tryit('md with leap code chinese reject', () => T.PlainMonthDay.from({ calendar: 'chinese', monthCode: 'M05', day: 1 }).with({ monthCode: 'M12L', day: 30 }, { overflow: 'reject' }));
tryit('md with leap code chinese', () => T.PlainMonthDay.from({ calendar: 'chinese', monthCode: 'M05', day: 1 }).with({ monthCode: 'M12L', day: 30 }));
tryit('relTo bag bad offset str', () => D.from('P1D').round({ smallestUnit: 'hour', relativeTo: { year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: 'bogus' } }));
tryit('instant bracket offset sec', () => T.Instant.from('2020-01-01T00:00Z[+01:00:30]'));
tryit('instant bracket offset', () => T.Instant.from('2020-01-01T00:00+01:00[+01:00]'));
tryit('zdt from bad offset opt str', () => T.ZonedDateTime.from({ year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: '+0x:00' }));
tryit('zdt with bad offset str', () => T.ZonedDateTime.from('2020-01-01T00:00Z[UTC]').with({ offset: '+25:00' }));
tryit('zdt with offset use', () => T.ZonedDateTime.from('2020-06-01T12:00+02:00[Europe/Paris]').with({ day: 2, offset: '+05:00' }, { offset: 'use' }).toString());
tryit('zdt with offset ignore', () => T.ZonedDateTime.from('2020-06-01T12:00+02:00[Europe/Paris]').with({ day: 2, offset: '+05:00' }, { offset: 'ignore' }).toString());
tryit('zdt with offset prefer', () => T.ZonedDateTime.from('2020-06-01T12:00+02:00[Europe/Paris]').with({ day: 2, offset: '+05:00' }, { offset: 'prefer' }).toString());
tryit('zdt from offset use dst', () => T.ZonedDateTime.from('2020-10-25T02:30+05:00[Europe/Paris]', { offset: 'use' }).toString());
tryit('zdt from offset ignore dst', () => T.ZonedDateTime.from('2020-10-25T02:30+05:00[Europe/Paris]', { offset: 'ignore', disambiguation: 'later' }).toString());
tryit('zdt from offset prefer ambiguous', () => T.ZonedDateTime.from('2020-10-25T02:30+01:00[Europe/Paris]', { offset: 'prefer' }).toString());
tryit('zdt from offset reject gap', () => T.ZonedDateTime.from('2020-03-29T02:30+01:00[Europe/Paris]', { offset: 'reject' }).toString());
tryit('ym until round err', () => T.PlainYearMonth.from('-271821-04').until('+275760-09', { smallestUnit: 'year', roundingIncrement: 1000, roundingMode: 'ceil' }));
tryit('ym since round', () => T.PlainYearMonth.from('2031-08').since('2020-01', { smallestUnit: 'year', roundingIncrement: 4, roundingMode: 'floor' }).toString());
tryit('zdt toString round over', () => T.ZonedDateTime.from('+275760-09-12T23:59:59.999999999+00:00[UTC]').toString({ smallestUnit: 'minute', roundingMode: 'ceil' }));
tryit('zdt round over', () => T.ZonedDateTime.from('+275760-09-12T23:59:59.999999999+00:00[UTC]').round({ smallestUnit: 'day', roundingMode: 'ceil' }));
tryit('pdt toZDT west edge', () => T.PlainDateTime.from('+275760-09-13T00:00').toZonedDateTime('+01:00').toString());
tryit('dur round zdt over', () => D.from({ years: 1 }).round({ smallestUnit: 'day', relativeTo: '+275760-08-12T00:00Z[UTC]' }));
tryit('dur total zdt over', () => D.from({ months: 2 }).total({ unit: 'day', relativeTo: '+275760-08-12T00:00Z[UTC]' }));
tryit('dur round pdt big incr', () => D.from({ hours: 100 }).round({ smallestUnit: 'hour', roundingIncrement: 24, relativeTo: '2020-01-01' }));
tryit('dur round days rel pd', () => D.from({ days: 40, hours: 13 }).round({ largestUnit: 'month', smallestUnit: 'day', relativeTo: '2020-01-31' }).toString());
tryit('dur round weeks rel zdt', () => D.from({ days: 40, hours: 13 }).round({ largestUnit: 'week', smallestUnit: 'hour', roundingIncrement: 6, relativeTo: '2020-10-20T00:00[Europe/London]' }).toString());
tryit('dur total months rel zdt dst', () => D.from({ days: 31, hours: 1 }).total({ unit: 'month', relativeTo: '2020-10-01T00:00[Europe/London]' }));
tryit('dur total week neg', () => D.from({ days: -10, hours: -3 }).total({ unit: 'week', relativeTo: '2020-10-30T00:00[Europe/London]' }));
console.log(out.join('\n'));
"""

PROG_INTL_MISC = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const NF = (o, l = 'en') => new Intl.NumberFormat(l, o);
tryit('exact sig string', () => [NF({ maximumSignificantDigits: 3 }).format('123456789012345678901234567890'), NF({ minimumSignificantDigits: 5, maximumSignificantDigits: 8, minimumIntegerDigits: 7 }).format('42'), NF({ maximumSignificantDigits: 2, roundingMode: 'floor' }).format('987654321987654321987')]);
tryit('exact incr', () => NF({ maximumFractionDigits: 2, minimumFractionDigits: 2, roundingIncrement: 5 }).format('1.2345678901234567890123'));
tryit('exact morePrecision', () => NF({ maximumFractionDigits: 2, maximumSignificantDigits: 2, roundingPriority: 'morePrecision' }).format('1.2345678901234567890123'));
tryit('exact sig frac', () => NF({ maximumSignificantDigits: 4 }).format('1.2345678901234567890123'));
tryit('exact minint', () => [NF({ minimumIntegerDigits: 6 }).format('12'), NF({ minimumIntegerDigits: 6 }).format('12.5'), NF({ minimumIntegerDigits: 3, maximumFractionDigits: 0 }).format('0.4')]);
tryit('zero minsig', () => [NF({ minimumSignificantDigits: 4 }).format(0), NF({ minimumSignificantDigits: 1 }).format(0), NF({ minimumSignificantDigits: 3 }).format(-0)]);
tryit('round discard', () => [NF({ maximumFractionDigits: 0, roundingMode: 'ceil' }).format('0.0000000000000000000001'), NF({ maximumFractionDigits: 0, roundingMode: 'expand' }).format('-0.0000000000000000000001'), NF({ maximumFractionDigits: 1, roundingIncrement: 5, roundingMode: 'ceil' }).format('0.0000000000000000000001'), NF({ maximumFractionDigits: 0 }).format('0.0000000000000000000001')]);
tryit('round modes', () => ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'].map(m => NF({ maximumFractionDigits: 0, roundingMode: m }).format('-2.5') + '/' + NF({ maximumFractionDigits: 0, roundingMode: m }).format('2.5')));
tryit('sig defaults', () => NF({ roundingPriority: 'lessPrecision', maximumFractionDigits: 1 }).resolvedOptions());
tryit('sig defaults2', () => NF({ roundingPriority: 'morePrecision' }).format(1234.56789));
tryit('fd only min', () => NF({ minimumFractionDigits: 4 }).resolvedOptions().maximumFractionDigits + ',' + NF({ maximumFractionDigits: 0 }).resolvedOptions().minimumFractionDigits + ',' + NF({ style: 'currency', currency: 'JPY', minimumFractionDigits: 1 }).resolvedOptions().maximumFractionDigits);
tryit('sci exp', () => [NF({ notation: 'scientific' }).format(999.99999999), NF({ notation: 'engineering' }).format(999999.9999999), NF({ notation: 'scientific', maximumSignificantDigits: 2 }).format(9.99e-7), NF({ notation: 'engineering' }).format(0.000999999999)]);
tryit('sci parts', () => NF({ notation: 'scientific' }).formatToParts(-12345).map(p => p.type + ':' + p.value).join('|'));
tryit('compact parts', () => [NF({ notation: 'compact' }).formatToParts(-1234567).map(p => p.type + ':' + p.value).join('|'), NF({ notation: 'compact', compactDisplay: 'long' }).formatToParts(2500000000).map(p => p.type + ':' + p.value).join('|')]);
tryit('accounting parts', () => [NF({ style: 'currency', currency: 'USD', currencySign: 'accounting' }).formatToParts(-12.5).map(p => p.type + ':' + p.value).join('|'), NF({ style: 'currency', currency: 'USD', currencySign: 'accounting', notation: 'compact' }).formatToParts(-1250000).map(p => p.type + ':' + p.value).join('|'), NF({ style: 'currency', currency: 'EUR', currencySign: 'accounting' }, 'de').formatToParts(-12.5).map(p => p.type + ':' + p.value).join('|')]);
tryit('currency code parts', () => [NF({ style: 'currency', currency: 'USD', currencyDisplay: 'code' }).formatToParts(-3).map(p => p.type + ':' + p.value).join('|'), NF({ style: 'currency', currency: 'USD', currencyDisplay: 'name' }).formatToParts(2).map(p => p.type + ':' + p.value).join('|'), NF({ style: 'currency', currency: 'CHF' }, 'de-CH').formatToParts(-1234.5).map(p => p.type + ':' + p.value).join('|')]);
tryit('unit parts', () => ['ja', 'zh', 'ko', 'en', 'de', 'fr', 'ar', 'tr', 'hu'].map(l => l + '=' + NF({ style: 'unit', unit: 'kilometer-per-hour', unitDisplay: 'short' }, l).formatToParts(5).map(p => p.type + ':' + p.value).join('|')));
tryit('unit narrow parts', () => ['en', 'ja', 'fr'].map(l => NF({ style: 'unit', unit: 'percent', unitDisplay: 'narrow' }, l).formatToParts(5).map(p => p.type + ':' + p.value).join('|') + ' ' + NF({ style: 'unit', unit: 'celsius', unitDisplay: 'long' }, l).format(-3)));
tryit('format bound', () => { const f = NF({}).format; return [f(1234.5), [1, 22, 333].map(NF({ minimumIntegerDigits: 2 }).format).join(';')]; });
tryit('supportedValues', () => ['calendar', 'collation', 'currency', 'numberingSystem', 'timeZone', 'unit'].map(k => k + ':' + Intl.supportedValuesOf(k).length + ':' + Intl.supportedValuesOf(k).slice(0, 3).join('/')));
tryit('supportedValues numbering', () => Intl.supportedValuesOf('numberingSystem').join(','));
tryit('supportedValues bad', () => Intl.supportedValuesOf('bogus'));
tryit('getCanonicalLocales', () => Intl.getCanonicalLocales(['ZH-YUE-hk', 'sgn-GR', 'x-private', 'en-x-foo', 'hy-arevela', 'art-lojban', 'cel-gaulish', 'zh-min-nan', 'i-klingon', 'sl-rozaj-biske-1994', 'en-u-ca-gregory-co-phonebk', 'de-1901-1996', 'ja-Latn-hepburn-heploc', 'und-Qaai', 'aar-x-u', 'sh-Cyrl', 'cnr', 'mo', 'en-t-zh-latn-m0-names', 'en-a-bbb-u-ccc', 'tl-PH', 'no-bok']));
for (const t of ['en-', 'en--US', 'abcdefghi', 'en-u-ca', 'en-a', 'en-t-1', 'x', 'en-US-u-ca-gregory-ca-buddhist', 'de-1901-1901', '123', 'en-x-123456789', 'en-u-c', 'en-u-cal-x', 'en-t-zz-m0', 'en-t-en-m0-123456789', 'zh-cmn-Hans-CN', 'en-gb-oed', 'und-x-priv']) tryit('canon ' + t, () => Intl.getCanonicalLocales(t));
tryit('locale obj list', () => Intl.getCanonicalLocales([new Intl.Locale('en-US'), 'fr', new Intl.Locale('de', { region: 'AT' })]));
tryit('locale list arraylike', () => Intl.getCanonicalLocales({ length: 2, 0: 'en', 1: 'FR' }));
tryit('locale list bad', () => Intl.getCanonicalLocales([5]));
tryit('locale maximize', () => ['zh-TW', 'und', 'und-Cyrl', 'sh', 'und-419', 'en-Latn', 'zh-Hant', 'und-150'].map(t => new Intl.Locale(t).maximize().toString() + '>' + new Intl.Locale(t).minimize().toString()));
tryit('locale info', () => { const l = new Intl.Locale('ar-EG'); return [l.getWeekInfo?.(), l.getTextInfo?.(), l.getHourCycles?.(), l.getCalendars?.(), l.getNumberingSystems?.(), l.getTimeZones?.(), l.getCollations?.()]; });
tryit('locale info he', () => { const l = new Intl.Locale('he-IL-u-ca-hebrew-hc-h11-nu-hebr'); return [l.calendar, l.hourCycle, l.numberingSystem, l.getWeekInfo(), l.getHourCycles(), l.getCalendars(), l.getNumberingSystems(), l.getTimeZones()]; });
tryit('locale info und', () => { const l = new Intl.Locale('und'); return [l.getTimeZones(), l.getWeekInfo()]; });
// DurationFormat validation
tryit('df frac always', () => new Intl.DurationFormat('en', { style: 'digital', millisecondsDisplay: 'always' }).format({ milliseconds: 1 }));
tryit('df frac follow', () => new Intl.DurationFormat('en', { milliseconds: 'numeric', microseconds: 'long' }));
tryit('df big', () => new Intl.DurationFormat('en').format({ years: 2 ** 32 }));
tryit('df digital', () => [new Intl.DurationFormat('en', { style: 'digital' }).format({ hours: 1, minutes: 2, seconds: 3, milliseconds: 4, microseconds: 5, nanoseconds: 6 }), new Intl.DurationFormat('en', { style: 'digital', fractionalDigits: 0 }).format({ seconds: 3, milliseconds: 999 }), new Intl.DurationFormat('en', { style: 'digital' }).format({ hours: 0, seconds: 7 }), new Intl.DurationFormat('en', { style: 'digital' }).format({ milliseconds: 1 })]);
tryit('df parts', () => new Intl.DurationFormat('en', { style: 'digital', hoursDisplay: 'auto' }).formatToParts({ days: 1, minutes: 5, seconds: 9, milliseconds: 120 }).map(p => p.type + ':' + p.value + (p.unit ? '@' + p.unit : '')).join('|'));
tryit('df numeric ms', () => [new Intl.DurationFormat('en', { seconds: 'numeric', milliseconds: 'numeric' }).format({ minutes: 1, seconds: 2, milliseconds: 3 }), new Intl.DurationFormat('en', { milliseconds: 'numeric' }).format({ seconds: 2, milliseconds: 30, microseconds: 0 }), new Intl.DurationFormat('en', { microseconds: 'numeric' }).format({ milliseconds: 2, microseconds: 30 })]);
// RelativeTimeFormat
tryit('rtf pl', () => [-1, 2, 5, 22, 1.5].map(n => new Intl.RelativeTimeFormat('pl', { style: 'narrow' }).format(n, 'year')));
tryit('rtf parts', () => new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).formatToParts(-1234.5, 'day').map(p => p.type + ':' + p.value).join('|'));
// DateTimeFormat + hourCycle combos
const d0 = Date.UTC(2020, 0, 1, 0, 5);
tryit('dtf hc', () => ['h11', 'h12', 'h23', 'h24'].map(hc => new Intl.DateTimeFormat('en', { hour: 'numeric', hourCycle: hc, timeZone: 'UTC' }).format(d0) + '/' + new Intl.DateTimeFormat('ja', { hour: 'numeric', minute: 'numeric', hourCycle: hc, timeZone: 'UTC' }).format(d0)));
tryit('dtf hour12', () => [true, false].map(h => new Intl.DateTimeFormat('de', { hour: 'numeric', hour12: h, timeZone: 'UTC' }).format(d0) + '/' + new Intl.DateTimeFormat('en-u-hc-h23', { hour: 'numeric', hour12: h, timeZone: 'UTC' }).format(d0)));
tryit('dtf range kinds', () => { const f = new Intl.DateTimeFormat('en', { timeZone: 'UTC' }); return f.formatRange(Temporal.PlainDate.from('2020-01-01'), Temporal.PlainTime.from('10:00')); });
tryit('dtf range ym md', () => { const f = new Intl.DateTimeFormat('en', { timeZone: 'UTC' }); return [f.formatRange(Temporal.PlainYearMonth.from('2020-01'), Temporal.PlainYearMonth.from('2020-05')), f.formatRange(Temporal.PlainMonthDay.from('01-02'), Temporal.PlainMonthDay.from('03-04'))]; });
tryit('dtf range instant zdt', () => { const f = new Intl.DateTimeFormat('en', { timeZone: 'UTC' }); return f.formatRange(Temporal.Instant.from('2020-01-01T00:00Z'), Temporal.ZonedDateTime.from('2020-01-01T00:00[UTC]')); });
tryit('dtf format zdt', () => new Intl.DateTimeFormat('en').format(Temporal.ZonedDateTime.from('2020-01-01T00:00[UTC]')));
tryit('dtf range diff', () => { const f = new Intl.DateTimeFormat('en', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' }); return [f.formatRange(d0, d0 + 3600e3), f.formatRange(d0, d0 + 86400e3 * 40), f.formatRange(d0, d0 + 86400e3 * 400)]; });
tryit('dtf range weekday', () => { const f = new Intl.DateTimeFormat('en', { timeZone: 'UTC', weekday: 'long', hour: 'numeric' }); return [f.formatRange(d0, d0 + 86400e3 + 3600e3), f.formatRange(d0, d0 + 3600e3)]; });
tryit('dtf tz offset', () => ['+05:30', '-0800', '+01', '+1:00', '+05:61'].map(tz => { try { return new Intl.DateTimeFormat('en', { timeZone: tz, timeZoneName: 'shortOffset', hour: 'numeric' }).format(d0); } catch (e) { return e.name; } }));
tryit('dtf narrow era', () => new Intl.DateTimeFormat('en', { era: 'narrow', year: 'numeric', timeZone: 'UTC' }).format(d0) + '/' + new Intl.DateTimeFormat('en', { era: 'short', year: 'numeric', timeZone: 'UTC' }).format(Date.UTC(-100, 0, 1)));
tryit('dtf dayPeriod narrow', () => ['narrow', 'short', 'long'].map(w => new Intl.DateTimeFormat('en', { dayPeriod: w, hour: 'numeric', timeZone: 'UTC' }).format(d0 + 13 * 3600e3)));
console.log(out.join('\n'));
"""

PROG_INTL_SERVICES = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const LP = Intl.Locale.prototype;
const fake = Object.create(LP);
for (const k of ['numeric', 'calendar', 'caseFirst', 'collation', 'hourCycle', 'numberingSystem', 'firstDayOfWeek', 'language', 'script', 'region', 'baseName', 'variants']) {
  const d = Object.getOwnPropertyDescriptor(LP, k);
  tryit('Locale.' + k + ' fake', () => d ? d.get.call(fake) : 'absent');
}
for (const m of ['getTimeZones', 'getCalendars', 'getWeekInfo', 'getTextInfo', 'getHourCycles', 'getNumberingSystems', 'getCollations', 'maximize', 'minimize', 'toString']) {
  tryit('Locale.' + m + ' fake', () => typeof LP[m] === 'function' ? LP[m].call(fake) : 'absent');
}
tryit('Locale fw', () => ['en-u-fw-mon', 'en-u-fw-true'].map(t => { const l = new Intl.Locale(t); return [l.toString(), l.firstDayOfWeek]; }));
tryit('Locale fw opt', () => ['mon', 'sun', 'true', '', 'ab', 'abcdefghi'].map(v => { try { return new Intl.Locale('en', { firstDayOfWeek: v }).toString(); } catch (e) { return e.name + ': ' + e.message; } }));
tryit('Locale fw num', () => [0, 1, 7].map(v => { try { return new Intl.Locale('en', { firstDayOfWeek: v }).firstDayOfWeek; } catch (e) { return e.name; } }));
tryit('Locale variants', () => [new Intl.Locale('de-1996-fonipa').variants, new Intl.Locale('en').variants, new Intl.Locale('sl-rozaj-biske').maximize().toString()]);
tryit('PluralRules ranges', () => [['minimumFractionDigits', 50], ['maximumFractionDigits', -1], ['minimumIntegerDigits', 0], ['maximumSignificantDigits', 22], ['minimumSignificantDigits', 0]].map(([k, v]) => { try { new Intl.PluralRules('en', { [k]: v }); return 'ok'; } catch (e) { return e.name + ': ' + e.message; } }));
tryit('PluralRules infinity', () => ['en', 'ar', 'pl', 'fr'].map(l => { const p = new Intl.PluralRules(l); return [p.select(Infinity), p.select(-Infinity), p.select(NaN)]; }));
tryit('PluralRules compact', () => { const p = new Intl.PluralRules('fr', { notation: 'compact' }); const r = p.resolvedOptions(); return [r.notation, r.compactDisplay, p.select(1e6), p.select(1.5e6)]; });
tryit('PluralRules compact long', () => new Intl.PluralRules('en', { notation: 'compact', compactDisplay: 'long' }).resolvedOptions().compactDisplay);
tryit('PluralRules bad opts', () => [new Intl.PluralRules('en', { roundingMode: 'bogus' })]);
tryit('PluralRules selectRange', () => { const p = new Intl.PluralRules('en'); return [p.selectRange(1, 2), p.selectRange(1, 1)]; });
tryit('PluralRules selectRange nan', () => new Intl.PluralRules('en').selectRange(NaN, 2));
tryit('Collator numeric', () => { const c = new Intl.Collator('en', { numeric: true }); return [c.compare('a10', 'a9'), c.compare('a', 'a1'), c.compare('a1', 'a'), c.compare('item 2', 'item 10'), c.compare('', 'x'), c.compare('x', ''), c.compare('007', '7'), c.compare('1.5', '1.10')]; });
tryit('Collator options', () => { const c = new Intl.Collator('de', { sensitivity: 'base', ignorePunctuation: true, caseFirst: 'upper', usage: 'search' }); return [c.resolvedOptions(), c.compare('a-b', 'ab')]; });
tryit('Collator collation', () => ['zh-u-co-pinyin', 'zh-u-co-stroke', 'de-u-co-phonebk', 'en-u-co-pinyin', 'es-u-co-trad'].map(t => new Intl.Collator(t).resolvedOptions().collation));
tryit('Collator kf kn', () => [new Intl.Collator('en-u-kf-lower-kn').resolvedOptions(), new Intl.Collator('en-u-kn-false', { numeric: true }).resolvedOptions().numeric]);
tryit('Segmenter grapheme hangul', () => [...new Intl.Segmenter('ko').segment('각각각ᆨx')].map(s => s.segment.length));
tryit('Segmenter grapheme controls', () => [...new Intl.Segmenter('en').segment('a​­ b\r\nc\u0001')].map(s => [...s.segment].map(c => c.codePointAt(0).toString(16)).join('+')));
tryit('Segmenter empty', () => [[...new Intl.Segmenter('en').segment('')].length, [...new Intl.Segmenter('en', { granularity: 'word' }).segment('')].length]);
tryit('Segmenter words spaces', () => [...new Intl.Segmenter('en', { granularity: 'word' }).segment('a   b,c;d:e·f 3,5 x.y')].map(s => s.segment + (s.isWordLike ? '*' : '')));
tryit('Segmenter containing', () => { const s = new Intl.Segmenter('en', { granularity: 'word' }).segment('hello big world'); return [s.containing(0).segment, s.containing(5).segment, s.containing(7).segment, s.containing(100), s.containing(-1), s.containing(14).index]; });
tryit('Segmenter sentence', () => [...new Intl.Segmenter('en', { granularity: 'sentence' }).segment('Hi there. How are you? Fine!  Ok')].map(s => s.segment));
tryit('Segmenter resolved', () => new Intl.Segmenter('fr', { granularity: 'word' }).resolvedOptions());
tryit('DisplayNames', () => { const d = new Intl.DisplayNames('en', { type: 'region' }); const l = new Intl.DisplayNames('en', { type: 'language', languageDisplay: 'standard' }); const s = new Intl.DisplayNames('en', { type: 'script' }); const c = new Intl.DisplayNames('en', { type: 'currency', style: 'short' }); const cal = new Intl.DisplayNames('en', { type: 'calendar' }); const dt = new Intl.DisplayNames('en', { type: 'dateTimeField' }); return [d.of('US'), d.of('419'), l.of('en-GB'), s.of('Cyrl'), c.of('EUR'), cal.of('gregory'), dt.of('year'), d.of('ZZ')]; });
tryit('DisplayNames fallback none', () => [new Intl.DisplayNames('en', { type: 'region', fallback: 'none' }).of('QQ'), new Intl.DisplayNames('en', { type: 'region', fallback: 'code' }).of('QQ')]);
tryit('DisplayNames bad', () => [() => new Intl.DisplayNames('en'), () => new Intl.DisplayNames('en', { type: 'region' }).of('1'), () => new Intl.DisplayNames('en', { type: 'calendar' }).of('a b'), () => new Intl.DisplayNames('en', { type: 'dateTimeField' }).of('bogus')].map(f => { try { return f(); } catch (e) { return e.name + ': ' + e.message; } }));
tryit('ListFormat', () => ['conjunction', 'disjunction', 'unit'].map(type => ['long', 'short', 'narrow'].map(style => new Intl.ListFormat('en', { type, style }).format(['a', 'b', 'c'])).join(' | ')));
tryit('ListFormat parts', () => new Intl.ListFormat('es', { type: 'disjunction' }).formatToParts(['x', 'y', 'z']).map(p => p.type + ':' + p.value));
tryit('ListFormat bad', () => new Intl.ListFormat('en').format(['a', 5]));
tryit('ListFormat iter', () => new Intl.ListFormat('de').format(new Set(['a', 'b'])));
tryit('NumberFormat CJK prefix units', () => ['zh', 'ko', 'ja'].flatMap(l => ['kilometer-per-hour', 'celsius'].map(unit => { const f = new Intl.NumberFormat(l, { style: 'unit', unit, unitDisplay: 'long' }); return f.format(-1.5) + ' ' + f.formatToParts(1234).map(p => p.type + ':' + p.value).join('|'); })));
console.log(out.join('\n'));
"""

PROG_INTL_DTF_TEMPORAL = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const T = Temporal;
const vals = { pt: T.PlainTime.from('13:05:09'), pd: T.PlainDate.from('2021-07-04'), pdt: T.PlainDateTime.from('2021-07-04T13:05:09'), ym: T.PlainYearMonth.from('2021-07'), md: T.PlainMonthDay.from('07-04'), inst: T.Instant.from('2021-07-04T13:05:09Z') };
for (const loc of ['en', 'de', 'ja', 'en-u-ca-iso8601', 'fr-u-hc-h23']) {
  const f = new Intl.DateTimeFormat(loc, { timeZone: 'UTC' });
  for (const [k, v] of Object.entries(vals)) tryit(loc + ' default ' + k, () => f.format(v));
}
for (const [k, v] of Object.entries(vals)) {
  tryit('en hour12 false ' + k, () => new Intl.DateTimeFormat('en', { hour12: false, timeZone: 'UTC' }).format(v));
  tryit('de hour12 true ' + k, () => new Intl.DateTimeFormat('de', { hour12: true, timeZone: 'UTC' }).format(v));
  tryit('en timeStyle ' + k, () => new Intl.DateTimeFormat('en', { timeStyle: 'short', timeZone: 'UTC' }).format(v));
  tryit('en dateStyle ' + k, () => new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeZone: 'UTC' }).format(v));
}
tryit('iso8601 md range', () => new Intl.DateTimeFormat('en-u-ca-iso8601', { timeZone: 'UTC' }).formatRange(vals.md, T.PlainMonthDay.from('08-01')));
tryit('iso8601 ym range', () => new Intl.DateTimeFormat('en-u-ca-iso8601', { timeZone: 'UTC' }).formatRange(vals.ym, T.PlainYearMonth.from('2022-01')));
tryit('iso8601 md/ym mismatch', () => new Intl.DateTimeFormat('en-u-ca-iso8601', { timeZone: 'UTC' }).formatRange(vals.md, vals.ym));
tryit('pt range', () => new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).formatRange(vals.pt, T.PlainTime.from('15:00')));
tryit('pt range parts', () => new Intl.DateTimeFormat('en', { timeZone: 'UTC', hour: 'numeric', minute: 'numeric' }).formatRangeToParts(vals.pt, T.PlainTime.from('15:30')).map(p => p.type + ':' + p.value + ':' + p.source).join('|'));
tryit('inst range', () => new Intl.DateTimeFormat('en', { timeZone: 'Asia/Tokyo' }).formatRange(vals.inst, T.Instant.from('2021-07-05T01:00Z')));
tryit('pd range same', () => new Intl.DateTimeFormat('en', { timeZone: 'UTC' }).formatRange(vals.pd, vals.pd));
tryit('pdt range diff literal', () => new Intl.DateTimeFormat('en', { timeZone: 'UTC', month: 'long', day: 'numeric', hour: 'numeric' }).formatRange(vals.pdt, T.PlainDateTime.from('2021-08-04T15:05:09')));
tryit('hebrew month name', () => new Intl.DateTimeFormat('en-u-ca-hebrew', { timeZone: 'UTC', month: 'long', day: 'numeric', year: 'numeric' }).format(vals.pd.withCalendar('hebrew')));
tryit('ms with tz name', () => new Intl.DateTimeFormat('en', { timeZone: 'America/New_York', timeZoneName: 'long', hour: 'numeric' }).format(Date.UTC(2021, 0, 1)));
tryit('fractional', () => [1, 2, 3].map(n => new Intl.DateTimeFormat('en', { timeZone: 'UTC', second: 'numeric', fractionalSecondDigits: n }).format(Date.UTC(2021, 0, 1, 0, 0, 5, 678))));
tryit('dtf timeStyle bad', () => new Intl.DateTimeFormat('en', { timeStyle: 'bogus' }));
tryit('dtf call no new', () => { const f = Intl.DateTimeFormat('en'); return [f instanceof Intl.DateTimeFormat, typeof f.format]; });
tryit('dtf legacy chain', () => { const o = Object.create(Intl.DateTimeFormat.prototype); const r = Intl.DateTimeFormat.call(o, 'en'); return [r === o, typeof r.format]; });
console.log(out.join('\n'));
"""


def test_temporal_with_and_option_validation(run):
    """CATCHES: Temporal types whose with()/withCalendar()/round()/until()/from() accept calendar/timeZone fields, non-plain objects, bad month/monthCode/offset values, bogus units or mismatched calendars instead of throwing the exact TypeError/RangeError, or that format toJSON/calendarId wrongly."""
    r = run(["-e", PROG_TEMPORAL_WITH])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "temporal_with")

def test_temporal_limits_durations_and_offsets(run):
    """CATCHES: Temporal arithmetic that ignores the representable date/time limits, Duration toString/round/total/compare edge cases (precision, increments, huge values, relativeTo across DST), offset string parsing (seconds, trailing junk) and offset/time-zone resolution for ZonedDateTime."""
    r = run(["-e", PROG_TEMPORAL_LIMITS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "temporal_limits")

def test_temporal_option_errors_lmt_offsets_and_calendar_month_days(run):
    """CATCHES: ZonedDateTime constructor/from/with/toString/round that accept invalid timeZone/calendar/disambiguation/offset/calendarName options, PlainDateTime/YearMonth/MonthDay conversions that ignore range limits or overflow:'reject', sub-minute LMT offsets (Asia/Tokyo 1880, Brussels 1885) printed or matched wrongly, relativeTo property bags with calendar/offset fields, and non-ISO PlainMonthDay leap-month/day clamping."""
    r = run(["-e", PROG_TEMPORAL_OPTIONS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "temporal_options")

def test_temporal_overflow_ambiguity_and_lunisolar_differences(run):
    """CATCHES: Temporal property-bag conversions that ignore overflow:'reject' or the year limits, withCalendar/from accepting non-string calendars, PlainTime.from that does not reject strings ambiguous with month-day/year-month (or rejects unambiguous ones), wrong Hebrew/Persian year boundaries over a 1000-year span, and until/since/add across Hebrew/Chinese leap months, Coptic/Ethiopic epagomenal months and Gregorian/Japanese month-end clamping."""
    r = run(["-e", PROG_TEMPORAL_CALENDARS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "temporal_calendars")

def test_temporal_duration_arithmetic_and_offset_resolution(run):
    """CATCHES: Duration add/subtract that balances time-only results to the wrong largest unit or accepts calendar units without relativeTo, PlainMonthDay.with leap month codes, bad offset strings in bags/with/relativeTo, ZonedDateTime offset:'use'/'ignore'/'prefer'/'reject' resolution in DST gaps/overlaps, rounding at the upper representable limit, and Duration round/total relative to ZonedDateTimes across DST."""
    r = run(["-e", PROG_TEMPORAL_DURATION_OFFSETS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "temporal_duration_offsets")

def test_intl_number_locale_duration_corner_cases(run):
    """CATCHES: Intl.NumberFormat exact-decimal string formatting (significant digits, increments, minimumIntegerDigits, rounding modes, scientific/compact/accounting/unit parts), locale canonicalization and validation, Intl.Locale info getters, DurationFormat digital/fractional validation, RelativeTimeFormat plurals and DateTimeFormat hourCycle/range/offset handling."""
    r = run(["-e", PROG_INTL_MISC])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "intl_misc")

def test_intl_locale_plural_collator_segmenter_displaynames(run):
    """CATCHES: Intl.Locale getters/methods without a brand check, firstDayOfWeek keyword handling, PluralRules digit-option ranges, Infinity/compact selection and selectRange, numeric Collator ordering of prefixes and digit runs, Segmenter grapheme (Hangul, controls), word (spaces, MidLetter/MidNum) and sentence segmentation with containing(), DisplayNames fallbacks/errors and ListFormat styles."""
    r = run(["-e", PROG_INTL_SERVICES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "intl_services")

def test_intl_datetimeformat_with_temporal_values(run):
    """CATCHES: Intl.DateTimeFormat formatting Temporal values with default/hour12/timeStyle/dateStyle options across locales (PlainTime shows no date, PlainYearMonth/MonthDay require an iso8601 formatter calendar, missing overlap is a TypeError), formatRange/formatRangeToParts of same-type Temporal endpoints, Hebrew month names, time-zone names, fractionalSecondDigits and legacy constructor chaining."""
    r = run(["-e", PROG_INTL_DTF_TEMPORAL])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "intl_dtf_temporal")
