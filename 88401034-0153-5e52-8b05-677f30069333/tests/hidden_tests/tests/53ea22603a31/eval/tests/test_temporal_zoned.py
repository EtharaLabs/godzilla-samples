"""Temporal.Instant and Temporal.ZonedDateTime with the engine's built-in IANA time-zone database.

Covers epoch construction (BigInt nanoseconds), ISO/RFC 9557 strings with offsets and bracketed
zones, DST gaps/folds (America/New_York, Europe/London, Australia/Lord_Howe, Pacific/Apia,
Asia/Kolkata), disambiguation and offset options, startOfDay/hoursInDay, getTimeZoneTransition,
arithmetic/difference/rounding, toString options, toLocaleString and Date.prototype.toTemporalInstant.
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
const Z = Temporal.ZonedDateTime, I = Temporal.Instant;
'''


def check(run, workdir, name, body, **kw):
    """Run PRE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRE + body, **kw)


def test_instant_construction_and_epochs(run, workdir):
    """CATCHES: Instant constructor accepting Numbers instead of BigInt, wrong range limits (+-8.64e21 ns), epochMilliseconds flooring for negative instants, fromEpochMilliseconds/fromEpochNanoseconds validation and the exact error messages."""
    check(run, workdir, "instant_construction_and_epochs", r'''
t('ctor 0n', () => new I(0n));
t('ctor negative', () => new I(-1n));
t('ctor number', () => new I(0));
t('ctor string', () => new I('1000000000'));
t('ctor max', () => new I(8640000000000000000000n));
t('ctor max+1', () => new I(8640000000000000000001n));
t('ctor min', () => new I(-8640000000000000000000n));
t('ctor min-1', () => new I(-8640000000000000000001n));
t('no new', () => I(0n));
const x = new I(-1500000n);
t('epochMilliseconds floors', () => x.epochMilliseconds);
t('epochNanoseconds', () => x.epochNanoseconds);
t('fromEpochMilliseconds', () => I.fromEpochMilliseconds(1700000000123));
t('fromEpochMilliseconds negative', () => I.fromEpochMilliseconds(-1));
t('fromEpochMilliseconds frac', () => I.fromEpochMilliseconds(1.5));
t('fromEpochMilliseconds NaN', () => I.fromEpochMilliseconds(NaN));
t('fromEpochMilliseconds bigint', () => I.fromEpochMilliseconds(1n));
t('fromEpochMilliseconds max', () => I.fromEpochMilliseconds(8.64e15));
t('fromEpochMilliseconds over', () => I.fromEpochMilliseconds(8.64e15 + 1));
t('fromEpochNanoseconds', () => I.fromEpochNanoseconds(1234567890123456789n));
t('fromEpochNanoseconds number', () => I.fromEpochNanoseconds(5));
t('fromEpochNanoseconds over', () => I.fromEpochNanoseconds(10n ** 22n));
t('typeof epochNanoseconds', () => typeof new I(5n).epochNanoseconds);
t('valueOf', () => new I(0n).valueOf());
t('toJSON', () => JSON.stringify([new I(1n)]));
t('equals', () => new I(5n).equals(new I(5n)) + ' ' + new I(5n).equals('1970-01-01T00:00:00.000000006Z'));
t('compare', () => [I.compare(new I(1n), new I(2n)), I.compare('1970-01-01T00:00Z', new I(0n)), I.compare(new I(3n), new I(2n))].join());
t('toStringTag', () => Object.prototype.toString.call(new I(0n)));
''')


def test_instant_from_strings(run, workdir):
    """CATCHES: Instant.from string parsing bugs: required offset or Z, offsets with seconds and fractions, bracketed zone ignored for the instant, rejection of date-only/local strings, extended years and representable-range checks."""
    check(run, workdir, "instant_from_strings", r'''
for (const s of [
  '2024-03-10T07:00:00Z', '2024-03-10T02:00:00-05:00', '2024-03-10T02:00:00.123456789+05:30',
  '2024-03-10T02:00-05:00[America/New_York]', '2024-03-10T02:00:00+01:00[Asia/Tokyo]', '2024-03-10T02:00:00-04:59:59.5',
  '20240310T020000Z', '2024-03-10t02:00:00z', '2024-03-10 02:00Z', '2024-03-10T02Z', '2024-03-10T02:00:00',
  '2024-03-10', '2024-03-10Z', '-271821-04-20T00:00Z', '-271821-04-19T23:59:59.999999999Z', '+275760-09-13T00:00Z',
  '+275760-09-13T00:00:00.000000001Z', '+275760-09-13T01:00+01:00', '1970-01-01T00:00Z[u-ca=hebrew]',
  '1970-01-01T00:00Z[!u-ca=hebrew]', '1970-01-01T00:00Z[UTC][u-ca=x][u-ca=y]', '1970-01-01T23:59:60Z',
]) t(JSON.stringify(s), () => I.from(s));
t('from Instant', () => I.from(new I(42n)));
t('from ZonedDateTime', () => I.from(Z.from('2024-01-01T00:00[Asia/Tokyo]')));
t('from object', () => I.from({ epochNanoseconds: 0n }));
t('from number', () => I.from(0));
''')


def test_instant_arithmetic_until_round(run, workdir):
    """CATCHES: Instant add/subtract accepting calendar units, until/since largestUnit defaulting to seconds, rounding with increments that must divide a solar day, and every roundingMode on negative epoch values."""
    check(run, workdir, "instant_arithmetic_until_round", r'''
const a = I.from('2024-01-01T00:00:00Z');
const b = I.from('2024-02-15T13:14:15.678901234Z');
t('add hours', () => a.add({ hours: 25, minutes: 61 }));
t('add string', () => a.add('PT1.5S'));
t('add days', () => a.add({ days: 1 }));
t('add months', () => a.add({ months: 1 }));
t('subtract', () => a.subtract({ nanoseconds: 1 }));
t('add out of range', () => I.from('+275760-09-13T00:00Z').add({ nanoseconds: 1 }));
t('until default', () => a.until(b));
t('since default', () => a.since(b));
t('until hours', () => a.until(b, { largestUnit: 'hours' }));
t('until ms', () => a.until(b, { largestUnit: 'milliseconds' }));
t('until days', () => a.until(b, { largestUnit: 'days' }));
t('until smallest minute', () => a.until(b, { largestUnit: 'hours', smallestUnit: 'minutes', roundingMode: 'halfExpand' }));
t('since smallest second ceil', () => a.since(b, { smallestUnit: 'second', roundingMode: 'ceil' }));
t('until incr 15 min', () => a.until(b, { smallestUnit: 'minutes', roundingIncrement: 15 }));
t('until bad incr', () => a.until(b, { smallestUnit: 'minutes', roundingIncrement: 7 }));
t('round hour', () => b.round('hour'));
t('round minute incr 30 floor', () => b.round({ smallestUnit: 'minute', roundingIncrement: 30, roundingMode: 'floor' }));
t('round hour incr 24', () => b.round({ smallestUnit: 'hour', roundingIncrement: 24 }));
t('round hour incr 5', () => b.round({ smallestUnit: 'hour', roundingIncrement: 5 }));
t('round ns incr 86400e9', () => b.round({ smallestUnit: 'nanosecond', roundingIncrement: 86400e9 }));
t('round day', () => b.round('day'));
t('round no unit', () => b.round({}));
const n = new I(-1500n);
for (const m of ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'])
  t('neg round us ' + m, () => n.round({ smallestUnit: 'microsecond', roundingMode: m }).epochNanoseconds);
''')


def test_instant_to_string_options(run, workdir):
    """CATCHES: Instant.toString bugs: timeZone option rendering local time with the zone's offset (not the zone name), fractionalSecondDigits/smallestUnit with rounding across day boundaries, invalid timeZone values, and toZonedDateTimeISO."""
    check(run, workdir, "instant_to_string_options", r'''
const x = I.from('2024-07-04T23:59:59.987654321Z');
t('default', () => x.toString());
t('timeZone NY', () => x.toString({ timeZone: 'America/New_York' }));
t('timeZone Kolkata', () => x.toString({ timeZone: 'Asia/Kolkata' }));
t('timeZone offset', () => x.toString({ timeZone: '+01:00' }));
t('timeZone UTC', () => x.toString({ timeZone: 'UTC' }));
t('timeZone bad', () => x.toString({ timeZone: 'Nowhere/City' }));
t('timeZone number', () => x.toString({ timeZone: 5 }));
t('timeZone zdt string', () => x.toString({ timeZone: '2020-01-01T00:00[Asia/Tokyo]' }));
t('fsd 0', () => x.toString({ fractionalSecondDigits: 0 }));
t('fsd 4', () => x.toString({ fractionalSecondDigits: 4 }));
t('smallestUnit minute', () => x.toString({ smallestUnit: 'minute' }));
t('second halfExpand rolls over', () => x.toString({ smallestUnit: 'second', roundingMode: 'halfExpand' }));
t('ms ceil with zone', () => x.toString({ smallestUnit: 'millisecond', roundingMode: 'ceil', timeZone: 'Asia/Tokyo' }));
t('smallestUnit hour', () => x.toString({ smallestUnit: 'hour' }));
t('toZonedDateTimeISO', () => x.toZonedDateTimeISO('Europe/London'));
t('toZonedDateTimeISO offset', () => x.toZonedDateTimeISO('-08:00'));
t('toZonedDateTimeISO missing', () => x.toZonedDateTimeISO());
t('toZonedDateTimeISO calendar annot', () => x.toZonedDateTimeISO('Asia/Tokyo').calendarId);
t('epoch before 1970 string', () => new I(-1n).toString());
t('far past', () => new I(-8640000000000000000000n).toString());
t('far future', () => new I(8640000000000000000000n).toString());
''')


def test_date_to_temporal_instant(run, workdir):
    """CATCHES: Date.prototype.toTemporalInstant missing or converting via seconds, invalid Dates not throwing RangeError, and lost millisecond precision or sign for pre-1970 dates."""
    check(run, workdir, "date_to_temporal_instant", r'''
t('epoch', () => new Date(0).toTemporalInstant());
t('ms precision', () => new Date(Date.UTC(2020, 1, 29, 12, 34, 56, 789)).toTemporalInstant());
t('negative', () => new Date(-1).toTemporalInstant().epochNanoseconds);
t('invalid', () => new Date(NaN).toTemporalInstant());
t('max date', () => new Date(8.64e15).toTemporalInstant());
t('non-Date receiver', () => Date.prototype.toTemporalInstant.call({}));
t('round trip', () => new Date(new Date(1234567890123).toTemporalInstant().epochMilliseconds).toISOString());
t('function name', () => Date.prototype.toTemporalInstant.name + ' ' + Date.prototype.toTemporalInstant.length);
''')


def test_zoned_construct_and_getters(run, workdir):
    """CATCHES: ZonedDateTime constructor bugs (BigInt requirement, zone/calendar validation, offset-string zones), and getter errors: offset/offsetNanoseconds, epochMilliseconds, timeZoneId preserving case-normalized/alias names, and hoursInDay on normal days."""
    check(run, workdir, "zoned_construct_and_getters", r'''
t('ctor', () => new Z(0n, 'America/New_York'));
t('ctor number', () => new Z(0, 'UTC'));
t('ctor calendar', () => new Z(0n, 'UTC', 'japanese'));
t('ctor bad calendar', () => new Z(0n, 'UTC', 'mayan'));
t('ctor calendar number', () => new Z(0n, 'UTC', 5));
t('ctor bad zone', () => new Z(0n, 'Moon/Base'));
t('ctor zone number', () => new Z(0n, 42));
t('ctor zone missing', () => new Z(0n));
t('ctor lowercase zone', () => new Z(0n, 'europe/paris').timeZoneId);
t('ctor alias zone', () => new Z(0n, 'Asia/Calcutta').timeZoneId);
t('ctor utc alias', () => new Z(0n, 'Etc/UTC').timeZoneId + ' ' + new Z(0n, 'utc').timeZoneId + ' ' + new Z(0n, 'Etc/GMT').timeZoneId);
t('ctor Etc/GMT+5', () => new Z(0n, 'Etc/GMT+5').toString());
t('ctor offset zone', () => new Z(0n, '+05:30').timeZoneId);
t('ctor offset zone basic', () => new Z(0n, '-0800').timeZoneId);
t('ctor offset zone seconds', () => new Z(0n, '+05:30:15'));
t('ctor offset zone hours', () => new Z(0n, '+05').timeZoneId);
t('ctor iso string zone', () => new Z(0n, '2020-01-01T00:00+01:00[Europe/Paris]'));
t('ctor out of range', () => new Z(8640000000000000000001n, 'UTC'));
const z = Z.from('2024-07-04T15:16:17.123456789-04:00[America/New_York]');
t('date getters', () => [z.year, z.month, z.monthCode, z.day, z.dayOfWeek, z.dayOfYear, z.weekOfYear, z.yearOfWeek,
  z.daysInWeek, z.daysInMonth, z.daysInYear, z.monthsInYear, z.inLeapYear, String(z.era)].join(' '));
t('time getters', () => [z.hour, z.minute, z.second, z.millisecond, z.microsecond, z.nanosecond].join(' '));
t('epoch getters', () => [z.epochMilliseconds, z.epochNanoseconds, z.offsetNanoseconds, z.offset, z.timeZoneId, z.calendarId, z.hoursInDay].join(' '));
t('kolkata offset', () => Z.from('2024-01-01T00:00[Asia/Kolkata]').offset);
t('kathmandu offset', () => Z.from('2024-01-01T00:00[Asia/Kathmandu]').offsetNanoseconds);
t('LMT offset', () => Z.from('1800-01-01T00:00[Europe/London]').toString() + ' ' + Z.from('1800-01-01T00:00[Europe/London]').offsetNanoseconds);
t('valueOf', () => z.valueOf());
t('toJSON', () => z.toJSON());
t('conversions', () => [z.toInstant(), z.toPlainDate(), z.toPlainTime(), z.toPlainDateTime()].map(String).join(' | '));
''')


def test_zoned_from_strings_and_offset_option(run, workdir):
    """CATCHES: ZonedDateTime.from offset-option bugs (use/ignore/prefer/reject on matching and conflicting offsets), Z with a bracketed zone, missing zone annotations, offset-only zones, sub-minute LMT offsets, and offset matching in DST folds."""
    check(run, workdir, "zoned_from_strings_and_offset_option", r'''
const conflict = '2024-07-03T01:30-05:00[America/New_York]';
for (const off of ['use', 'ignore', 'prefer', 'reject', undefined])
  t('conflict offset=' + off, () => Z.from(conflict, off === undefined ? undefined : { offset: off }));
t('bad offset option', () => Z.from(conflict, { offset: 'maybe' }));
const fold = '2024-11-03T01:30-05:00[America/New_York]';
for (const off of ['use', 'ignore', 'prefer', 'reject']) t('fold -05 offset=' + off, () => Z.from(fold, { offset: off }));
t('fold -04 default', () => Z.from('2024-11-03T01:30-04:00[America/New_York]'));
t('fold no offset', () => Z.from('2024-11-03T01:30[America/New_York]'));
t('fold no offset later', () => Z.from('2024-11-03T01:30[America/New_York]', { disambiguation: 'later' }));
t('gap with offset -05', () => Z.from('2024-03-10T02:30-05:00[America/New_York]'));
t('gap with offset -04 reject', () => Z.from('2024-03-10T02:30-04:00[America/New_York]'));
t('gap reject', () => Z.from('2024-03-10T02:30[America/New_York]', { disambiguation: 'reject' }));
t('Z with zone', () => Z.from('2024-07-03T01:30Z[America/New_York]'));
t('Z with zone offset reject', () => Z.from('2024-07-03T01:30Z[America/New_York]', { offset: 'reject' }));
t('no zone', () => Z.from('2024-07-03T01:30Z'));
t('date only with zone', () => Z.from('2024-07-03[Europe/Berlin]'));
t('offset zone', () => Z.from('2024-07-03T01:30+02:00[+02:00]'));
t('offset zone mismatch', () => Z.from('2024-07-03T01:30+03:00[+02:00]'));
t('minute-rounded offset match', () => Z.from('1800-01-01T00:00-00:01[Europe/London]'));
t('exact LMT offset match', () => Z.from('1800-01-01T00:00-00:01:15[Europe/London]'));
t('wrong seconds offset', () => Z.from('1800-01-01T00:00-00:01:14[Europe/London]'));
t('calendar annotation', () => Z.from('2024-07-03T01:30+09:00[Asia/Tokyo][u-ca=japanese]'));
t('critical unknown annotation', () => Z.from('2024-07-03T01:30+09:00[Asia/Tokyo][!x-foo=bar]'));
t('zone case', () => Z.from('2024-07-03T01:30[ASIA/TOKYO]').timeZoneId);
t('bad zone', () => Z.from('2024-07-03T01:30[Asia/Atlantis]'));
t('options not object', () => Z.from(conflict, 'use'));
t('string ignores overflow but validates', () => Z.from('2024-07-03T01:30[UTC]', { overflow: 'bogus' }));
''')


def test_zoned_property_bags(run, workdir):
    """CATCHES: ZonedDateTime property-bag bugs: required timeZone, offset field interaction with the offset option, overflow constrain/reject on fields, disambiguation in gaps for bags, and invalid offset strings."""
    check(run, workdir, "zoned_property_bags", r'''
t('basic', () => Z.from({ year: 2024, month: 3, day: 10, hour: 2, minute: 30, timeZone: 'America/New_York' }));
t('earlier', () => Z.from({ year: 2024, month: 3, day: 10, hour: 2, minute: 30, timeZone: 'America/New_York' }, { disambiguation: 'earlier' }));
t('missing timeZone', () => Z.from({ year: 2024, month: 3, day: 10 }));
t('missing day', () => Z.from({ year: 2024, month: 3, timeZone: 'UTC' }));
t('with offset field', () => Z.from({ year: 2024, month: 11, day: 3, hour: 1, minute: 30, offset: '-05:00', timeZone: 'America/New_York' }));
t('conflicting offset field', () => Z.from({ year: 2024, month: 7, day: 3, offset: '-05:00', timeZone: 'America/New_York' }));
t('conflicting offset use', () => Z.from({ year: 2024, month: 7, day: 3, offset: '-05:00', timeZone: 'America/New_York' }, { offset: 'use' }));
t('bad offset string', () => Z.from({ year: 2024, month: 7, day: 3, offset: '5', timeZone: 'UTC' }));
t('offset number', () => Z.from({ year: 2024, month: 7, day: 3, offset: 5, timeZone: 'UTC' }));
t('overflow constrain', () => Z.from({ year: 2024, month: 2, day: 31, hour: 24, timeZone: 'UTC' }));
t('overflow reject', () => Z.from({ year: 2024, month: 2, day: 31, timeZone: 'UTC' }, { overflow: 'reject' }));
t('timeZone from zdt', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: Z.from('2020-01-01T00:00[Asia/Tokyo]') }));
t('timeZone iso string', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: '2020-01-01T00:00+01:00[Europe/Paris]' }).timeZoneId);
t('timeZone iso string Z only', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: '2020-01-01T00:00Z' }).timeZoneId);
t('timeZone iso offset only', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: '2020-01-01T00:00-07:00' }).timeZoneId);
t('timeZone object', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: {} }));
t('calendar field', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC', calendar: 'gregory' }).toString());
t('from ZonedDateTime copy', () => Z.from(Z.from('2024-01-01T00:00[UTC]')).toString());
t('from PlainDateTime', () => Z.from(Temporal.PlainDateTime.from('2024-01-01T00:00')));
''')


def test_zoned_dst_transitions_new_york_london(run, workdir):
    """CATCHES: wrong DST rules in the bundled tz database: hoursInDay 23/25 on transition days, startOfDay, add() across transitions with calendar vs exact units, wall-clock arithmetic landing in a gap, and Europe/London BST changes."""
    check(run, workdir, "zoned_dst_transitions_new_york_london", r'''
const spring = Z.from('2024-03-10T12:00[America/New_York]');
const fall = Z.from('2024-11-03T12:00[America/New_York]');
t('spring hoursInDay', () => spring.hoursInDay);
t('fall hoursInDay', () => fall.hoursInDay);
t('spring startOfDay', () => spring.startOfDay());
t('before spring +1 day', () => Z.from('2024-03-09T02:30[America/New_York]').add({ days: 1 }));
t('before spring +24h', () => Z.from('2024-03-09T02:30[America/New_York]').add({ hours: 24 }));
t('fall 00:30 + 1h', () => Z.from('2024-11-03T00:30[America/New_York]').add({ hours: 1 }));
t('fall 00:30 + 2h', () => Z.from('2024-11-03T00:30[America/New_York]').add({ hours: 2 }));
t('fall day diff in hours', () => fall.startOfDay().until(fall.startOfDay().add({ days: 1 }), { largestUnit: 'hours' }));
t('spring day diff', () => spring.startOfDay().until(spring.startOfDay().add({ days: 1 })));
t('subtract 1 day into gap', () => Z.from('2024-03-11T02:30[America/New_York]').subtract({ days: 1 }));
t('with hour into gap', () => spring.with({ hour: 2, minute: 30 }));
t('with hour into gap earlier', () => spring.with({ hour: 2, minute: 30 }, { disambiguation: 'earlier' }));
t('with hour into gap reject', () => spring.with({ hour: 2, minute: 30 }, { disambiguation: 'reject' }));
t('with fold keeps offset', () => Z.from('2024-11-03T01:10-05:00[America/New_York]').with({ minute: 45 }));
t('with fold offset ignore', () => Z.from('2024-11-03T01:10-05:00[America/New_York]').with({ minute: 45 }, { offset: 'ignore' }));
t('with fold offset reject', () => Z.from('2024-11-03T01:10-05:00[America/New_York]').with({ minute: 45, offset: '-07:00' }, { offset: 'reject' }));
t('london spring', () => Z.from('2024-03-31T01:30[Europe/London]'));
t('london spring hours', () => Z.from('2024-03-31T12:00[Europe/London]').hoursInDay);
t('london fall earlier', () => Z.from('2024-10-27T01:30[Europe/London]'));
t('london fall later', () => Z.from('2024-10-27T01:30[Europe/London]', { disambiguation: 'later' }));
t('london 1971 BST all year', () => Z.from('1970-01-15T12:00[Europe/London]').offset);
t('2037 last NY transition', () => Z.from('2037-11-01T12:00[America/New_York]').hoursInDay);
''')


def test_zoned_unusual_zones(run, workdir):
    """CATCHES: zone-database bugs for unusual offsets: Lord Howe's 30-minute DST (hoursInDay 23.5/24.5), Pacific/Apia skipping 2011-12-30 entirely, Asia/Kolkata +05:30 and its Asia/Calcutta alias (kept as given but equal), Kathmandu +05:45 and Chatham +13:45."""
    check(run, workdir, "zoned_unusual_zones", r'''
t('lord howe gap', () => Z.from('2024-10-06T02:15[Australia/Lord_Howe]'));
t('lord howe gap earlier', () => Z.from('2024-10-06T02:15[Australia/Lord_Howe]', { disambiguation: 'earlier' }));
t('lord howe hoursInDay spring', () => Z.from('2024-10-06T12:00[Australia/Lord_Howe]').hoursInDay);
t('lord howe hoursInDay fall', () => Z.from('2024-04-07T12:00[Australia/Lord_Howe]').hoursInDay);
t('lord howe fold later', () => Z.from('2024-04-07T01:45[Australia/Lord_Howe]', { disambiguation: 'later' }));
t('apia before skip', () => Z.from('2011-12-29T12:00[Pacific/Apia]'));
t('apia +1 day', () => Z.from('2011-12-29T12:00[Pacific/Apia]').add({ days: 1 }));
t('apia +24h', () => Z.from('2011-12-29T12:00[Pacific/Apia]').add({ hours: 24 }));
t('apia skipped date', () => Z.from('2011-12-30T12:00[Pacific/Apia]'));
t('apia skipped date reject', () => Z.from('2011-12-30T12:00[Pacific/Apia]', { disambiguation: 'reject' }));
t('apia 29th hoursInDay', () => Z.from('2011-12-29T12:00[Pacific/Apia]').hoursInDay);
t('apia 31st startOfDay', () => Z.from('2011-12-31T12:00[Pacific/Apia]').startOfDay());
t('apia day diff', () => Z.from('2011-12-29T12:00[Pacific/Apia]').until(Z.from('2011-12-31T12:00[Pacific/Apia]'), { largestUnit: 'days' }));
t('apia hour diff', () => Z.from('2011-12-29T12:00[Pacific/Apia]').until(Z.from('2011-12-31T12:00[Pacific/Apia]'), { largestUnit: 'hours' }));
t('kolkata', () => Z.from('2024-06-01T09:00[Asia/Kolkata]').toInstant());
t('calcutta kept', () => Z.from('2024-06-01T09:00[Asia/Calcutta]').toString());
t('calcutta equals kolkata', () => Z.from('2024-06-01T09:00[Asia/Calcutta]').equals(Z.from('2024-06-01T09:00[Asia/Kolkata]')));
t('kolkata 1942 war time', () => Z.from('1943-06-01T00:00[Asia/Kolkata]').offset);
t('kathmandu', () => Z.from('2024-06-01T00:00[Asia/Kathmandu]').offset);
t('chatham dst', () => Z.from('2024-01-01T00:00[Pacific/Chatham]').offset + ' ' + Z.from('2024-07-01T00:00[Pacific/Chatham]').offset);
t('kiribati +14', () => Z.from('2024-01-01T00:00[Pacific/Kiritimati]').offset);
t('equals different zone same instant', () => Z.from('2024-01-01T00:00Z[UTC]').equals(Z.from('2024-01-01T00:00Z[Etc/UTC]')));
t('equals offset zone vs named', () => Z.from('2024-01-01T00:00Z[UTC]').equals(Z.from('2024-01-01T00:00Z[+00:00]')));
''')


def test_zoned_time_zone_transitions(run, workdir):
    """CATCHES: getTimeZoneTransition bugs: next/previous direction search, string vs options-bag argument, null for fixed-offset/UTC zones and beyond the end of the rule data, and the exact errors for missing or invalid directions."""
    check(run, workdir, "zoned_time_zone_transitions", r'''
const z = Z.from('2024-06-15T12:00[America/New_York]');
t('next', () => z.getTimeZoneTransition('next'));
t('previous', () => z.getTimeZoneTransition('previous'));
t('next bag', () => z.getTimeZoneTransition({ direction: 'next' }));
t('next of next', () => z.getTimeZoneTransition('next').getTimeZoneTransition('next'));
t('previous at transition', () => Z.from('2024-03-10T03:00-04:00[America/New_York]').getTimeZoneTransition('previous'));
t('london next', () => Z.from('2024-01-01T00:00[Europe/London]').getTimeZoneTransition('next'));
t('lord howe next', () => Z.from('2024-06-01T00:00[Australia/Lord_Howe]').getTimeZoneTransition('next'));
t('apia previous', () => Z.from('2012-01-15T00:00[Pacific/Apia]').getTimeZoneTransition('previous'));
t('kolkata previous', () => Z.from('2024-01-01T00:00[Asia/Kolkata]').getTimeZoneTransition('previous'));
t('kolkata next', () => Z.from('2024-01-01T00:00[Asia/Kolkata]').getTimeZoneTransition('next'));
t('UTC next', () => Z.from('2024-01-01T00:00[UTC]').getTimeZoneTransition('next'));
t('offset zone previous', () => Z.from('2024-01-01T00:00+03:00[+03:00]').getTimeZoneTransition('previous'));
t('NY first transition', () => Z.from('1800-01-01T00:00[America/New_York]').getTimeZoneTransition('next'));
t('london skips rule-only change', () => Z.from('1968-06-01T00:00[Europe/London]').getTimeZoneTransition('next'));
t('london previous skips rule-only', () => Z.from('1971-06-01T00:00[Europe/London]').getTimeZoneTransition('previous'));
t('NY before first', () => Z.from('1800-01-01T00:00[America/New_York]').getTimeZoneTransition('previous'));
t('after rule data', () => Z.from('2200-01-01T00:00[America/New_York]').getTimeZoneTransition('previous'));
t('bad direction', () => z.getTimeZoneTransition('forward'));
t('missing direction', () => z.getTimeZoneTransition());
t('bag missing direction', () => z.getTimeZoneTransition({}));
t('number', () => z.getTimeZoneTransition(1));
''')


def test_zoned_with_and_conversions(run, workdir):
    """CATCHES: ZonedDateTime with/withPlainTime/withTimeZone/withCalendar bugs: keeping the instant when changing zone, offset preference on with(), rejecting timeZone/calendar fields, and toPlain* conversions."""
    check(run, workdir, "zoned_with_and_conversions", r'''
const z = Z.from('2024-01-15T10:20:30+01:00[Europe/Paris]');
t('with year', () => z.with({ year: 2023 }));
t('with month to summer', () => z.with({ month: 7 }));
t('with day overflow constrain', () => z.with({ month: 2, day: 31 }));
t('with day overflow reject', () => z.with({ month: 2, day: 31 }, { overflow: 'reject' }));
t('with offset field', () => z.with({ offset: '+02:00' }));
t('with offset field use', () => z.with({ offset: '+02:00' }, { offset: 'use' }));
t('with timeZone field', () => z.with({ timeZone: 'UTC' }));
t('with calendar field', () => z.with({ calendar: 'iso8601' }));
t('with empty', () => z.with({}));
t('with string', () => z.with('2024-01-01'));
t('withPlainTime', () => z.withPlainTime('23:00'));
t('withPlainTime none', () => z.withPlainTime());
t('withPlainTime gap', () => Z.from('2024-03-31T12:00[Europe/Paris]').withPlainTime('02:30'));
t('withTimeZone', () => z.withTimeZone('Asia/Tokyo'));
t('withTimeZone offset', () => z.withTimeZone('-03:00'));
t('withTimeZone missing', () => z.withTimeZone());
t('withTimeZone bad', () => z.withTimeZone('Europe/Atlantis'));
t('withCalendar', () => z.withCalendar('buddhist').toString());
t('withCalendar missing', () => z.withCalendar());
t('toInstant', () => z.toInstant());
t('toPlainDate', () => z.toPlainDate().toString());
t('toPlainTime', () => z.toPlainTime().toString());
t('toPlainDateTime', () => z.toPlainDateTime().toString());
t('startOfDay', () => z.startOfDay());
t('startOfDay sao paulo 2018 midnight gap', () => Z.from('2018-11-04T12:00[America/Sao_Paulo]').startOfDay());
t('hoursInDay sao paulo', () => Z.from('2018-11-04T12:00[America/Sao_Paulo]').hoursInDay);
''')


def test_zoned_arithmetic_and_difference(run, workdir):
    """CATCHES: ZonedDateTime add/subtract/until/since bugs: calendar units following wall-clock time while exact units follow the instant, month-end clamping with reject, largestUnit days vs hours across DST, rounding with relative day lengths, and cross-zone until errors."""
    check(run, workdir, "zoned_arithmetic_and_difference", r'''
const a = Z.from('2024-01-31T12:00[America/New_York]');
const b = Z.from('2024-07-04T09:30:15.5[America/New_York]');
t('add P1M', () => a.add('P1M'));
t('add P1M reject', () => a.add('P1M', { overflow: 'reject' }));
t('add P1Y2M3DT4H', () => a.add('P1Y2M3DT4H'));
t('subtract PT1H', () => a.subtract({ hours: 1 }));
t('add bad overflow', () => a.add({ days: 1 }, { overflow: 'x' }));
t('until default', () => a.until(b));
t('until years', () => a.until(b, { largestUnit: 'years' }));
t('until months', () => a.until(b, { largestUnit: 'months' }));
t('until weeks', () => a.until(b, { largestUnit: 'weeks' }));
t('until days', () => a.until(b, { largestUnit: 'days' }));
t('until minutes', () => a.until(b, { largestUnit: 'minutes' }));
t('since years', () => a.since(b, { largestUnit: 'years' }));
t('until round day', () => a.until(b, { smallestUnit: 'days' }));
t('until round months halfExpand', () => a.until(b, { largestUnit: 'years', smallestUnit: 'months' }));
t('until round hours incr 6', () => a.until(b, { smallestUnit: 'hours', roundingIncrement: 6, roundingMode: 'ceil' }));
t('since round weeks floor', () => a.since(b, { largestUnit: 'weeks', smallestUnit: 'weeks', roundingMode: 'floor' }));
t('until across fall DST days', () => Z.from('2024-11-02T12:00[America/New_York]').until(Z.from('2024-11-04T12:00[America/New_York]'), { largestUnit: 'days' }));
t('until across fall DST hours', () => Z.from('2024-11-02T12:00[America/New_York]').until(Z.from('2024-11-04T12:00[America/New_York]'), { largestUnit: 'hours' }));
t('until half day on 25h day', () => Z.from('2024-11-03T00:00[America/New_York]').until(Z.from('2024-11-03T12:30[America/New_York]'), { smallestUnit: 'days', roundingMode: 'halfExpand' }));
t('until different zone, days', () => a.until(b.withTimeZone('UTC'), { largestUnit: 'days' }));
t('until different zone, hours', () => a.until(b.withTimeZone('UTC'), { largestUnit: 'hours' }));
t('until different calendar', () => a.until(b.withCalendar('gregory')));
t('until bad unit combo', () => a.until(b, { largestUnit: 'hours', smallestUnit: 'days' }));
t('until string', () => a.until('2024-02-01T12:00-05:00[America/New_York]'));
t('compare', () => [Z.compare(a, b), Z.compare(b, a), Z.compare(a, a.withTimeZone('Asia/Tokyo'))].join());
t('equals other zone', () => a.equals(a.withTimeZone('Asia/Tokyo')));
''')


def test_zoned_round_and_to_string(run, workdir):
    """CATCHES: ZonedDateTime.round bugs (day rounding on 23h/25h days, increments, re-resolution of offsets after rounding) and toString option bugs (offset/timeZoneName/calendarName never/always/critical/auto, fractionalSecondDigits)."""
    check(run, workdir, "zoned_round_and_to_string", r'''
const z = Z.from('2024-03-10T13:45:30.555555555-04:00[America/New_York]');
t('round day (23h day)', () => z.round('day'));
t('round day before noon', () => Z.from('2024-03-10T11:00-04:00[America/New_York]').round('day'));
t('round hour', () => z.round('hour'));
t('round minute incr 15 trunc', () => z.round({ smallestUnit: 'minute', roundingIncrement: 15, roundingMode: 'trunc' }));
t('round ms halfEven', () => z.round({ smallestUnit: 'millisecond', roundingMode: 'halfEven' }));
t('round hour into gap', () => Z.from('2024-03-10T01:40-05:00[America/New_York]').round('hour'));
t('round day incr 2', () => z.round({ smallestUnit: 'day', roundingIncrement: 2 }));
t('round week', () => z.round('week'));
t('round none', () => z.round());
t('fall day round', () => Z.from('2024-11-03T12:20-05:00[America/New_York]').round({ smallestUnit: 'day', roundingMode: 'halfExpand' }));
t('default', () => z.toString());
t('offset never', () => z.toString({ offset: 'never' }));
t('offset bad', () => z.toString({ offset: 'sometimes' }));
t('timeZoneName never', () => z.toString({ timeZoneName: 'never' }));
t('timeZoneName critical', () => z.toString({ timeZoneName: 'critical' }));
t('timeZoneName bad', () => z.toString({ timeZoneName: 'long' }));
t('calendarName always', () => z.toString({ calendarName: 'always' }));
t('calendarName critical japanese', () => z.withCalendar('japanese').toString({ calendarName: 'critical' }));
t('all never', () => z.withCalendar('japanese').toString({ calendarName: 'never', timeZoneName: 'never', offset: 'never' }));
t('fsd 3', () => z.toString({ fractionalSecondDigits: 3 }));
t('smallestUnit minute', () => z.toString({ smallestUnit: 'minute' }));
t('smallestUnit second ceil', () => z.toString({ smallestUnit: 'second', roundingMode: 'ceil' }));
t('fsd 0 halfExpand into next minute', () => Z.from('2024-01-01T00:00:59.6[UTC]').toString({ fractionalSecondDigits: 0, roundingMode: 'halfExpand' }));
t('offset zone string', () => Z.from('2024-01-01T00:00+05:30[+05:30]').toString());
t('LMT offset string', () => Z.from('1850-06-01T12:00[America/New_York]').toString());
''')


def test_zoned_to_locale_string(run, workdir):
    """CATCHES: ZonedDateTime.toLocaleString bugs: the instance's zone forced onto the formatter (timeZone option is a TypeError), default date+time+short zone name, explicit components suppressing defaults, calendar mismatch RangeError, and alias zones canonicalized. Pins the reference's standard-time GMT-5 label even in summer."""
    check(run, workdir, "zoned_to_locale_string", r'''
const z = Z.from('2024-07-04T15:16:17-04:00[America/New_York]');
t('en-US default', () => z.toLocaleString('en-US'));
t('winter', () => Z.from('2024-01-04T15:16:17-05:00[America/New_York]').toLocaleString('en-US'));
t('de-DE', () => z.toLocaleString('de-DE'));
t('kolkata', () => Z.from('2024-01-04T15:16:17[Asia/Kolkata]').toLocaleString('en-US'));
t('calcutta alias', () => Z.from('2024-01-04T15:16:17[Asia/Calcutta]').toLocaleString('en-US'));
t('UTC', () => Z.from('2024-01-04T15:16:17[UTC]').toLocaleString('en-US'));
t('offset zone', () => Z.from('2024-01-04T15:16:17+05:00[+05:00]').toLocaleString('en-US'));
t('dateStyle only', () => z.toLocaleString('en-US', { dateStyle: 'long' }));
t('hour only', () => z.toLocaleString('en-US', { hour: 'numeric' }));
t('timeZoneName long', () => z.toLocaleString('en-US', { timeZoneName: 'long' }));
t('timeZone option', () => z.toLocaleString('en-US', { timeZone: 'UTC' }));
t('options string', () => z.toLocaleString('en-US', 'short'));
t('calendar japanese match', () => z.withCalendar('japanese').toLocaleString('en-US-u-ca-japanese', { dateStyle: 'medium' }));
t('calendar mismatch', () => z.withCalendar('japanese').toLocaleString('en-US'));
t('brand', () => Z.prototype.toLocaleString.call(new I(0n)));
t('instant toLocaleString', () => new I(0n).toLocaleString('en-US', { timeZone: 'Asia/Tokyo' }));
''')


def test_zoned_offset_strings_in_bags(run, workdir):
    """CATCHES: UTC-offset string parsing bugs in ZonedDateTime property bags: ±HH, ±HHMM, ±HH:MM, seconds and fractional seconds, mixed basic/extended separators, out-of-range hours/minutes/seconds, too many fraction digits, and objects coerced via toString."""
    check(run, workdir, "zoned_offset_strings_in_bags", r'''
const bag = { year: 2024, month: 1, day: 1, hour: 12, timeZone: '+05:30' };
for (const off of ['+05:30', '+0530', '+05', '-00:00', '+05:30:00', '+053000', '+05:30:00.000', '+05:30:00,0', '+05:30:00.000000000',
  '+05:3', '+5:30', '+24:00', '+23:60', '+05:30:60', '+05:30:00.', '+05:30:00.0000000000', '+0530:00', '+05:3000',
  '+05:30:00.5', '05:30', 'Z', '', '+05:30 ', '−05:30'])
  t(JSON.stringify(off), () => Z.from({ ...bag, offset: off }));
t('object offset', () => Z.from({ ...bag, offset: { toString() { return '+05:30'; } } }));
t('offset use with seconds', () => Z.from({ ...bag, timeZone: 'Asia/Kolkata', offset: '+05:30:30' }, { offset: 'use' }));
t('offset prefer mismatch falls back', () => Z.from({ ...bag, timeZone: 'Asia/Kolkata', offset: '+05:00' }, { offset: 'prefer' }));
t('offset ignore mismatch', () => Z.from({ ...bag, timeZone: 'Asia/Kolkata', offset: '+05:00' }, { offset: 'ignore' }));
t('LMT exact seconds offset', () => Z.from({ year: 1800, month: 1, day: 1, timeZone: 'Europe/London', offset: '-00:01:15' }));
t('LMT rounded offset', () => Z.from({ year: 1800, month: 1, day: 1, timeZone: 'Europe/London', offset: '-00:01' }));
''')


def test_zoned_time_zone_argument_forms(run, workdir):
    """CATCHES: time-zone argument parsing bugs: ISO strings with bracketed zones or Z/offset used as a zone, sub-minute offsets rejected as zones, whitespace and case handling, Etc/GMT sign inversion, alias preservation, offset zone canonical form, and tz equality for equals()."""
    check(run, workdir, "zoned_time_zone_argument_forms", r'''
const z = Z.from('2024-06-01T12:00Z[UTC]');
for (const tz of ['Europe/Paris', 'europe/PARIS', 'Asia/Calcutta', 'US/Eastern', 'GMT', 'Etc/GMT-14', 'Etc/GMT+12', 'Etc/GMT+13',
  'UTC', 'Etc/Universal', 'Zulu', '+01', '+0100', '-01:00', '+01:00:00', '+01:00:30', '2024-01-01T00:00+01:00[Asia/Tokyo]',
  '2024-01-01T00:00+01:00', '2024-01-01T00:00:30+01:00:30', '2024-01-01T00:00Z', '2024-01-01T00:00', '2024-01-01T00:00[+02:00]',
  '2024-01-01T00:00[Mars/Base]', ' Europe/Paris', 'Europe/Paris ', '', 'EST', 'EST5EDT', 'America/Argentina/Buenos_Aires'])
  t('withTimeZone ' + JSON.stringify(tz), () => z.withTimeZone(tz).toString());
t('toZonedDateTimeISO iso string', () => z.toInstant().toZonedDateTimeISO('2024-01-01T00:00-03:00[America/Sao_Paulo]').toString());
t('Instant toString zone from ISO', () => z.toInstant().toString({ timeZone: '2024-01-01T00:00Z' }));
t('Instant toString LMT seconds offset', () => I.from('1800-01-01T00:00Z').toString({ timeZone: 'Europe/London' }));
t('ZDT LMT seconds offset string', () => Z.from('1800-01-01T00:00Z[Europe/Amsterdam]').toString() + ' ' + Z.from('1800-01-01T00:00Z[Europe/Amsterdam]').offset);
t('equals offset zones', () => new Z(0n, '+01:00').equals(new Z(0n, '+0100')));
t('equals alias', () => new Z(0n, 'US/Eastern').equals(new Z(0n, 'America/New_York')));
t('equals different zones', () => new Z(0n, 'Europe/Paris').equals(new Z(0n, 'Europe/Berlin')));
t('equals offset vs named fixed', () => new Z(0n, 'Etc/GMT-1').equals(new Z(0n, '+01:00')));
t('ctor tz with brackets', () => new Z(0n, '[UTC]'));
t('supportedValuesOf timeZone', () => { const z = Intl.supportedValuesOf('timeZone'); return [z.length, z.includes('America/New_York'), z.includes('Asia/Kolkata'), z.includes('Asia/Calcutta'), z.includes('UTC'), z[0]].join(' '); });
''')


def test_zoned_with_field_validation(run, workdir):
    """CATCHES: ZonedDateTime.with field validation bugs: Temporal objects as arguments, zero month/day, monthCode type/format and month disagreement, era/eraYear rules in era calendars, time fields with overflow, and offset string fields."""
    check(run, workdir, "zoned_with_field_validation", r'''
const z = Z.from('2024-05-31T10:00+02:00[Europe/Paris]');
t('temporal arg', () => z.with(Temporal.PlainDate.from('2024-01-01')));
t('month 0', () => z.with({ month: 0 }));
t('day 0', () => z.with({ day: 0 }));
t('monthCode', () => z.with({ monthCode: 'M02' }));
t('monthCode reject', () => z.with({ monthCode: 'M02' }, { overflow: 'reject' }));
t('monthCode number', () => z.with({ monthCode: 2 }));
t('monthCode bad', () => z.with({ monthCode: 'm02' }));
t('monthCode disagree', () => z.with({ month: 3, monthCode: 'M02' }));
t('time fields', () => z.with({ hour: 23, minute: 59, second: 59, millisecond: 999, microsecond: 999, nanosecond: 999 }));
t('time constrain', () => z.with({ hour: 25, minute: 61 }));
t('time reject', () => z.with({ hour: 25 }, { overflow: 'reject' }));
t('offset number', () => z.with({ offset: 2 }));
t('offset bad string', () => z.with({ offset: '+2' }));
t('offset object', () => z.with({ hour: 11, offset: { toString() { return '+02:00'; } } }));
t('bad disambiguation', () => z.with({ hour: 11 }, { disambiguation: 'x' }));
t('bad offset option', () => z.with({ hour: 11 }, { offset: 'x' }));
const g = z.withCalendar('gregory');
t('gregory era+eraYear', () => g.with({ era: 'bce', eraYear: 1 }).toString());
t('gregory eraYear only', () => g.with({ eraYear: 1 }));
t('gregory era+eraYear+year', () => g.with({ era: 'ce', eraYear: 1, year: 1 }));
t('gregory era getters', () => [g.era, g.eraYear, z.era, z.eraYear].map(String).join(' '));
const j = z.withCalendar('japanese');
t('japanese era getters', () => [j.era, j.eraYear, j.year].join(' '));
t('japanese with era', () => j.with({ era: 'showa', eraYear: 50 }).toString());
t('japanese weekOfYear', () => String(j.weekOfYear) + ' ' + String(j.yearOfWeek));
t('hebrew getters', () => { const h = z.withCalendar('hebrew'); return [h.year, h.month, h.monthCode, h.day, h.daysInMonth, h.monthsInYear, h.inLeapYear, String(h.weekOfYear)].join(' '); });
t('calendarId brand', () => Object.getOwnPropertyDescriptor(Z.prototype, 'calendarId').get.call({}));
t('withCalendar Temporal', () => z.withCalendar(Temporal.PlainDate.from('2024-01-01[u-ca=coptic]')).toString());
t('withCalendar number', () => z.withCalendar(5));
t('withCalendar plain object', () => z.withCalendar({}));
t('withCalendar bad', () => z.withCalendar('xyz'));
''')


def test_zoned_misc_errors_and_limits(run, workdir):
    """CATCHES: ZonedDateTime/Instant edge cases: from() bags missing year/month, unsupported calendar annotations, non-object/non-string inputs, out-of-range wall times and offsets near the representable limits, round()/toString() option errors, nanosecond rounding no-ops, and Instant subtract/round/BigInt coercion errors."""
    check(run, workdir, "zoned_misc_errors_and_limits", r'''
t('from number', () => Z.from(5));
t('from missing year', () => Z.from({ month: 1, day: 1, timeZone: 'UTC' }));
t('from missing month', () => Z.from({ year: 2024, day: 1, timeZone: 'UTC' }));
t('from bad calendar annotation', () => Z.from('2024-01-01T00:00[UTC][u-ca=klingon]'));
t('from calendar number', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC', calendar: 5 }));
t('from calendar Temporal', () => Z.from({ year: 2024, month: 1, day: 1, timeZone: 'UTC', calendar: Temporal.PlainDate.from('2024-01-01[u-ca=roc]') }).toString());
t('from date-only no zone', () => Z.from('2024-01-01'));
t('max wall time UTC', () => Z.from('+275760-09-13T00:00[UTC]'));
t('max wall time + offset', () => Z.from('+275760-09-13T00:00-01:00[-01:00]'));
t('max wall time offset use', () => Z.from({ year: 275760, month: 9, day: 13, hour: 1, offset: '+01:00', timeZone: 'UTC' }, { offset: 'use' }));
t('min wall time', () => Z.from('-271821-04-20T00:00[UTC]'));
t('below min wall time', () => Z.from('-271821-04-19T23:00[UTC]'));
t('below min with offset', () => Z.from('-271821-04-19T23:00-01:00[-01:00]'));
t('far out of range bag', () => Z.from({ year: 300000, month: 1, day: 1, timeZone: 'UTC' }));
t('far out of range ignore', () => Z.from({ year: 300000, month: 1, day: 1, timeZone: 'UTC', offset: '+00:00' }, { offset: 'ignore' }));
t('far out of range prefer', () => Z.from({ year: 300000, month: 1, day: 1, timeZone: 'UTC', offset: '+00:00' }, { offset: 'prefer' }));
const z = Z.from('2024-05-31T10:20:30.123456789+02:00[Europe/Paris]');
t('round number options', () => z.round(5));
t('round ns incr 1', () => z.round({ smallestUnit: 'nanosecond' }));
t('round ns incr 1 by string', () => z.round('nanoseconds'));
t('round us', () => z.round('microsecond'));
t('round bad incr hour 5', () => z.round({ smallestUnit: 'hour', roundingIncrement: 5 }));
t('round max out of range', () => Z.from('+275760-09-12T23:59[-00:30]').round({ smallestUnit: 'day', roundingMode: 'ceil' }));
t('toString bad smallestUnit', () => z.toString({ smallestUnit: 'hours' }));
t('toString unknown smallestUnit', () => z.toString({ smallestUnit: 'eon' }));
t('toString us', () => z.toString({ smallestUnit: 'microsecond' }));
t('toString ms', () => z.toString({ smallestUnit: 'millisecond' }));
t('toString fsd 5', () => z.toString({ fractionalSecondDigits: 5 }));
t('toString fsd 8 halfExpand', () => z.toString({ fractionalSecondDigits: 8, roundingMode: 'halfExpand' }));
t('withPlainTime out of range', () => Z.from('-271821-04-20T12:00[UTC]').withPlainTime('00:00').subtract({ nanoseconds: 1 }));
t('withPlainTime bad', () => z.withPlainTime('25:00'));
t('withPlainTime below min local', () => Z.from('-271821-04-20T00:00Z[-01:00]').withPlainTime('00:00'));
t('toString ns', () => z.toString({ smallestUnit: 'nanosecond' }));
t('getTimeZoneTransition bad bag type', () => z.getTimeZoneTransition({ direction: 5 }));
t('until bad largest', () => z.until(z, { largestUnit: 'eon' }));
t('until bad smallest', () => z.until(z, { smallestUnit: 'eon' }));
t('until same', () => z.until(z, { largestUnit: 'years' }));
const i = I.from('2024-01-01T00:00:00.123456789Z');
t('Instant subtract calendar units', () => i.subtract({ weeks: 1 }));
t('Instant round number', () => i.round(5));
t('Instant round string', () => i.round('millisecond'));
t('Instant toString us', () => i.toString({ smallestUnit: 'microseconds' }));
t('Instant toString fsd 6', () => i.toString({ fractionalSecondDigits: 6 }));
t('Instant toString fsd 7 negative', () => new I(-1n).toString({ fractionalSecondDigits: 7 }));
t('Instant toString ns negative', () => new I(-1n).toString({ smallestUnit: 'nanosecond' }));
t('Instant toString fsd 8 halfExpand negative', () => new I(-15n).toString({ fractionalSecondDigits: 8, roundingMode: 'halfExpand' }));
t('Instant toString bad smallestUnit', () => i.toString({ smallestUnit: 'eon' }));
t('Instant toString ns floor negative', () => new I(-1n).toString({ smallestUnit: 'second' }));
t('Instant toString fsd 2 negative', () => new I(-1n).toString({ fractionalSecondDigits: 2, roundingMode: 'ceil' }));
t('Instant ctor true', () => new I(true).epochNanoseconds);
t('Instant ctor string bigint', () => new I('-123').epochNanoseconds);
t('Instant ctor bad string', () => new I('1.5'));
t('Instant ctor undefined', () => new I());
t('Instant ctor symbol', () => new I(Symbol()));
t('Instant until bad largest', () => i.until(i, { largestUnit: 'days' }));
t('Instant since smallest hour', () => i.since(I.from('2023-12-31T10:29:59Z'), { smallestUnit: 'hours', roundingMode: 'halfEven' }));
t('Instant until largest ms', () => i.until(I.from('2024-01-01T00:00:05Z'), { largestUnit: 'microseconds' }));
''')


def test_zoned_rounding_differences_across_dst(run, workdir):
    """CATCHES: ZonedDateTime until/since rounding bugs where the time part is rounded against the real (23h/25h) day length, days bubbling into weeks/months/years after rounding, and differences that end inside a repeated hour."""
    check(run, workdir, "zoned_rounding_differences_across_dst", r'''
const ny = (s) => Z.from(s + '[America/New_York]');
t('days+hours rounding on 25h day', () => ny('2024-11-02T18:00').until(ny('2024-11-03T23:40'), { largestUnit: 'days', smallestUnit: 'hours' }));
t('days+hours ceil to next day', () => ny('2024-11-02T00:00').until(ny('2024-11-03T23:31'), { largestUnit: 'days', smallestUnit: 'hours', roundingMode: 'ceil' }));
t('days+minutes 23h day', () => ny('2024-03-09T12:00').until(ny('2024-03-10T12:00'), { largestUnit: 'days', smallestUnit: 'minutes' }));
t('since days+hours', () => ny('2024-03-09T12:00').since(ny('2024-03-11T11:30'), { largestUnit: 'days', smallestUnit: 'hours' }));
t('months+hours', () => ny('2024-02-10T02:30').until(ny('2024-03-10T03:30'), { largestUnit: 'months', smallestUnit: 'hours' }));
t('years+days bubbling', () => ny('2023-01-01T00:00').until(ny('2023-12-31T23:00'), { largestUnit: 'years', smallestUnit: 'days', roundingMode: 'ceil' }));
t('months bubbling to years', () => ny('2023-01-15T00:00').until(ny('2024-01-10T00:00'), { largestUnit: 'years', smallestUnit: 'months', roundingMode: 'halfExpand' }));
t('weeks bubbling', () => ny('2024-01-01T00:00').until(ny('2024-01-14T20:00'), { largestUnit: 'weeks', smallestUnit: 'days', roundingMode: 'halfExpand' }));
t('weeks smallest with months largest', () => ny('2024-01-01T00:00').until(ny('2024-03-20T00:00'), { largestUnit: 'months', smallestUnit: 'weeks' }));
t('fold end later offset', () => Z.from('2024-11-03T00:00-04:00[America/New_York]').until(Z.from('2024-11-03T01:30-05:00[America/New_York]'), { largestUnit: 'days' }));
t('fold end hours', () => Z.from('2024-11-03T00:00-04:00[America/New_York]').until(Z.from('2024-11-03T01:30-05:00[America/New_York]'), { largestUnit: 'hours' }));
t('negative days across spring', () => ny('2024-03-11T01:00').until(ny('2024-03-09T03:00'), { largestUnit: 'days' }));
t('negative months', () => ny('2024-03-31T12:00').until(ny('2024-01-31T11:00'), { largestUnit: 'months' }));
t('lord howe days+minutes', () => Z.from('2024-10-05T12:00[Australia/Lord_Howe]').until(Z.from('2024-10-06T12:15[Australia/Lord_Howe]'), { largestUnit: 'days', smallestUnit: 'minutes', roundingIncrement: 30 }));
t('apia across skipped day', () => Z.from('2011-12-29T23:00[Pacific/Apia]').until(Z.from('2011-12-31T01:00[Pacific/Apia]'), { largestUnit: 'days', smallestUnit: 'hours' }));
''')
