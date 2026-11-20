"""Temporal.Duration: construction, ISO 8601 duration strings, balancing, rounding and totals.

Covers mixed-sign/range validation, sign/blank/abs/negated/with, add/subtract (time-only without
relativeTo), round() and total() with and without relativeTo (PlainDate, PlainDateTime-like bags,
ZonedDateTime across DST), Duration.compare, toString precision options and toLocaleString.
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
const D = Temporal.Duration;
const F = ['years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds', 'microseconds', 'nanoseconds'];
const fields = (d) => F.map((k) => d[k]).join(' ');
'''


def check(run, workdir, name, body, **kw):
    """Run PRE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRE + body, **kw)


def test_duration_constructor_and_validation(run, workdir):
    """CATCHES: Duration constructor bugs: accepting fractional or non-finite components, mixed signs, components beyond the 2^53 seconds / 2^32 calendar-unit limits, -0 normalization, and the getters/sign/blank values."""
    check(run, workdir, "duration_constructor_and_validation", r'''
t('all fields', () => new D(1, 2, 3, 4, 5, 6, 7, 8, 9, 10));
t('getters', () => fields(new D(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)));
t('empty', () => new D());
t('negative', () => new D(-1, 0, 0, -2));
t('mixed signs', () => new D(1, -1));
t('fractional', () => new D(1.5));
t('Infinity', () => new D(0, 0, 0, Infinity));
t('NaN', () => new D(NaN));
t('string numbers', () => new D('1', '2'));
t('negative zero', () => Object.is(new D(-0).years, 0) + ' ' + new D(-0).sign);
t('no new', () => D(1));
t('years 2^32-1', () => new D(2 ** 32 - 1));
t('years 2^32', () => new D(2 ** 32));
t('months -(2^32-1)', () => new D(0, -(2 ** 32 - 1)));
t('seconds max safe', () => new D(0, 0, 0, 0, 0, 0, Number.MAX_SAFE_INTEGER));
t('seconds 2^53', () => new D(0, 0, 0, 0, 0, 0, 2 ** 53));
t('days max', () => new D(0, 0, 0, 104249991374));
t('days over', () => new D(0, 0, 0, 104249991375));
t('ns large', () => new D(0, 0, 0, 0, 0, 0, 0, 0, 0, 9007199254740991999999999));
t('ms combine over', () => new D(0, 0, 0, 0, 0, 0, Number.MAX_SAFE_INTEGER, 1000));
t('sign/blank', () => [new D(0, 0, 0, 1).sign, new D(0, 0, 0, -1).sign, new D().sign, new D().blank, new D(1).blank].join());
t('negated', () => new D(1, 2, 0, 0, 0, 0, 0, 0, 0, -0).negated());
t('negated zero', () => new D().negated());
t('abs', () => new D(-1, -2, 0, -3).abs());
t('valueOf', () => new D(1).valueOf());
t('toStringTag', () => Object.prototype.toString.call(new D()));
t('getter brand', () => Object.getOwnPropertyDescriptor(D.prototype, 'years').get.call({}));
''')


def test_duration_from_strings_and_bags(run, workdir):
    """CATCHES: ISO 8601 duration parser bugs: fractional hours/minutes/seconds (only on the last unit), comma decimal separator, signs (+/-, not U+2212), week designators, lowercase letters, missing T, empty designators, and property-bag field validation (unknown fields, plural names only). Pins a reference quirk: leading/trailing whitespace around a duration string is accepted."""
    check(run, workdir, "duration_from_strings_and_bags", r'''
for (const s of ['P1Y2M3W4DT5H6M7.123456789S', 'PT0S', 'P0D', '-P1D', '+P1D', '−P1D', 'p1y', 'P1Yt1H', 'PT1.5H',
  'PT1.5M', 'PT0.000000001S', 'PT1,5S', 'PT1.5H30M', 'PT1.1234567891S', 'P1.5D', 'P1.5Y', 'P', 'PT', 'P1DT',
  'P1H', 'PT1D', 'P1W1D', 'P1M1Y', 'PT36H', 'P1Y-1M', ' P1D', 'P1D ', 'PT10000000000000000000000S',
  'P4294967296Y', 'PT9007199254740991S', 'PT9007199254740992S', 'PT0.5H0.5M'])
  t(JSON.stringify(s), () => D.from(s));
t('bag', () => D.from({ hours: 1, minutes: 90 }));
t('bag singular names ignored', () => D.from({ hour: 1 }));
t('bag empty', () => D.from({}));
t('bag mixed signs', () => D.from({ hours: 1, minutes: -1 }));
t('bag fractional', () => D.from({ hours: 1.5 }));
t('bag undefined fields', () => D.from({ hours: undefined, days: 2 }));
t('bag string field', () => D.from({ days: '3' }));
t('bag bad string field', () => D.from({ days: 'x' }));
t('from Duration copies', () => { const a = D.from('P1D'); const b = D.from(a); return `${a === b} ${b}`; });
t('from number', () => D.from(5));
t('from null', () => D.from(null));
t('field read order', () => {
  const log = [];
  const bag = new Proxy({ days: 1 }, { get(o, k) { if (typeof k === 'string') log.push(k); return o[k]; } });
  D.from(bag);
  return log.join(',');
});
''')


def test_duration_to_string_precision(run, workdir):
    """CATCHES: Duration.toString bugs: fractional seconds combined from ms/us/ns (with carry), negative durations, fractionalSecondDigits/smallestUnit rounding (incl. rounding up into minutes), unbalanced large components, and invalid smallestUnit values."""
    check(run, workdir, "duration_to_string_precision", r'''
const x = new D(0, 0, 0, 0, 1, 2, 3, 456, 789, 123);
t('default', () => x.toString());
t('negative', () => x.negated().toString());
t('ms only', () => new D(0, 0, 0, 0, 0, 0, 0, 5).toString());
t('ms carry', () => new D(0, 0, 0, 0, 0, 0, 1, 1500).toString());
t('us/ns', () => new D(0, 0, 0, 0, 0, 0, 0, 0, 1, 1).toString());
t('big ns', () => new D(0, 0, 0, 0, 0, 0, 0, 0, 0, 1e15).toString());
t('mixed big', () => new D(0, 0, 0, 0, 0, 0, Number.MAX_SAFE_INTEGER, 999, 999, 999).toString());
t('unbalanced', () => new D(0, 0, 0, 0, 100, 100, 100).toString());
t('date only', () => new D(1, 0, 2).toString());
t('zero', () => new D().toString());
for (const d of [0, 2, 9, 'auto']) t('fsd ' + d, () => x.toString({ fractionalSecondDigits: d }));
t('fsd on zero', () => new D().toString({ fractionalSecondDigits: 2 }));
t('fsd on date only', () => new D(0, 0, 0, 1).toString({ fractionalSecondDigits: 3 }));
t('smallestUnit second', () => x.toString({ smallestUnit: 'second' }));
t('smallestUnit ms ceil', () => x.toString({ smallestUnit: 'millisecond', roundingMode: 'ceil' }));
t('smallestUnit minute', () => x.toString({ smallestUnit: 'minute' }));
t('round up carries', () => new D(0, 0, 0, 0, 0, 59, 59, 999).toString({ smallestUnit: 'second', roundingMode: 'halfExpand' }));
t('negative ceil', () => new D(0, 0, 0, 0, 0, 0, -1, -500).toString({ fractionalSecondDigits: 0, roundingMode: 'ceil' }));
t('negative floor', () => new D(0, 0, 0, 0, 0, 0, -1, -500).toString({ fractionalSecondDigits: 0, roundingMode: 'floor' }));
t('fsd 10', () => x.toString({ fractionalSecondDigits: 10 }));
t('smallestUnit ns', () => x.toString({ smallestUnit: 'nanoseconds' }));
t('toJSON', () => JSON.stringify({ d: x }));
''')


def test_duration_with_add_subtract(run, workdir):
    """CATCHES: Duration with/add/subtract bugs: with() merging fields and re-validating signs, time-only balancing on add (largest unit of either operand), RangeError when calendar units are present without relativeTo, and negative results."""
    check(run, workdir, "duration_with_add_subtract", r'''
const x = D.from('PT1H30M');
t('with', () => x.with({ minutes: 45, seconds: 10 }));
t('with mixed sign', () => x.with({ seconds: -1 }));
t('with empty', () => x.with({}));
t('with string', () => x.with('PT1H'));
t('with negate all', () => x.with({ hours: -1, minutes: -30 }));
t('add', () => x.add('PT45M'));
t('add balances to hours', () => D.from('PT50M').add({ minutes: 20 }));
t('add keeps largest days', () => D.from('P1DT12H').add('PT13H'));
t('add seconds only', () => D.from('PT59S').add('PT2S'));
t('add to negative', () => x.add('-PT2H'));
t('subtract', () => x.subtract({ hours: 2 }));
t('subtract self', () => x.subtract(x));
t('add with years', () => D.from('P1Y').add('P1M'));
t('add weeks', () => D.from('P1W').add('P1D'));
t('add ms precision', () => D.from('PT0.1S').add('PT0.2S'));
t('add us + ns', () => D.from({ microseconds: 5 }).add({ nanoseconds: 5 }));
t('add ns + ns', () => D.from({ nanoseconds: 5 }).add({ nanoseconds: 5 }));
t('add ms + us', () => D.from({ milliseconds: 5 }).add({ microseconds: 5 }));
t('add bad', () => x.add({}));
t('add options ignored', () => x.add('PT1M', { relativeTo: '2024-01-01' }));
t('add exceeding range', () => D.from({ seconds: Number.MAX_SAFE_INTEGER }).add({ seconds: 1 }));
''')


def test_duration_round_without_relative_to(run, workdir):
    """CATCHES: Duration.round bugs without relativeTo: balancing time units up to days (24h days), largestUnit/smallestUnit validation, roundingIncrement rules, every roundingMode on negative durations, and calendar units requiring relativeTo."""
    check(run, workdir, "duration_round_without_relative_to", r'''
const x = D.from('PT130H45M30.5S');
t('largest days', () => x.round({ largestUnit: 'days' }));
t('largest hours smallest minute', () => x.round({ largestUnit: 'hours', smallestUnit: 'minutes' }));
t('smallest hour', () => x.round('hours'));
t('smallest day', () => x.round({ smallestUnit: 'days' }));
t('largest auto', () => D.from('PT3600S').round({ largestUnit: 'auto' }));
t('largest minutes', () => D.from('PT2H').round({ largestUnit: 'minutes' }));
t('largest seconds from days', () => D.from('P1D').round({ largestUnit: 'seconds' }));
t('incr 15 minutes', () => x.round({ smallestUnit: 'minutes', roundingIncrement: 15 }));
t('incr 7 minutes', () => x.round({ smallestUnit: 'minutes', roundingIncrement: 7 }));
t('incr 2 days', () => D.from('PT75H').round({ smallestUnit: 'days', roundingIncrement: 2 }));
t('incr 12 hours largest hours', () => D.from('PT75H').round({ largestUnit: 'hours', smallestUnit: 'hours', roundingIncrement: 12 }));
t('largest weeks no relativeTo', () => x.round({ largestUnit: 'weeks' }));
t('largest months', () => x.round({ largestUnit: 'months' }));
t('smallest years', () => x.round({ smallestUnit: 'years' }));
t('has years', () => D.from('P1Y').round({ smallestUnit: 'hours' }));
t('has weeks', () => D.from('P1W').round({ largestUnit: 'days' }));
t('no options', () => x.round());
t('empty options', () => x.round({}));
t('bad unit', () => x.round('fortnights'));
t('smallest > largest', () => x.round({ largestUnit: 'minutes', smallestUnit: 'hours' }));
t('bad mode', () => x.round({ smallestUnit: 'hour', roundingMode: 'round' }));
const n = D.from('-PT1H30M');
for (const m of ['ceil', 'floor', 'expand', 'trunc', 'halfCeil', 'halfFloor', 'halfExpand', 'halfTrunc', 'halfEven'])
  t('neg 1.5h ' + m, () => n.round({ smallestUnit: 'hours', roundingMode: m }));
t('halfEven 2.5h', () => D.from('PT2H30M').round({ smallestUnit: 'hours', roundingMode: 'halfEven' }));
t('subsecond', () => D.from('PT1.23456789S').round({ smallestUnit: 'microseconds' }));
''')


def test_duration_round_relative_to_plain_date(run, workdir):
    """CATCHES: Duration.round with a PlainDate/PlainDateTime relativeTo: month lengths and leap years when balancing days into months/years, week rounding, increments on calendar units, relativeTo given as strings/bags, and invalid relativeTo values."""
    check(run, workdir, "duration_round_relative_to_plain_date", r'''
const rel = Temporal.PlainDate.from('2024-01-31');
t('days to months', () => D.from('P60D').round({ largestUnit: 'months', relativeTo: rel }));
t('days to years', () => D.from('P400D').round({ largestUnit: 'years', relativeTo: '2024-01-01' }));
t('days to years from 2023', () => D.from('P400D').round({ largestUnit: 'years', relativeTo: '2023-01-01' }));
t('months to days', () => D.from('P2M').round({ largestUnit: 'days', relativeTo: rel }));
t('years to months', () => D.from('P1Y6M').round({ largestUnit: 'months', relativeTo: rel }));
t('round to months', () => D.from('P1M15D').round({ smallestUnit: 'months', relativeTo: '2024-02-01' }));
t('round to months from Jan', () => D.from('P1M15D').round({ smallestUnit: 'months', relativeTo: '2024-01-01' }));
t('round to years halfExpand', () => D.from('P1Y6M').round({ smallestUnit: 'years', relativeTo: rel }));
t('round to years trunc', () => D.from('P1Y6M').round({ smallestUnit: 'years', roundingMode: 'trunc', relativeTo: rel }));
t('round weeks', () => D.from('P20D').round({ smallestUnit: 'weeks', relativeTo: rel }));
t('largest weeks', () => D.from('P1M').round({ largestUnit: 'weeks', relativeTo: rel }));
t('months incr 3', () => D.from('P7M').round({ smallestUnit: 'months', roundingIncrement: 3, relativeTo: rel }));
t('negative to months', () => D.from('-P60D').round({ largestUnit: 'months', relativeTo: rel }));
t('negative to months floor', () => D.from('-P45D').round({ smallestUnit: 'months', roundingMode: 'floor', relativeTo: rel }));
t('time + date to days', () => D.from('P1DT36H').round({ largestUnit: 'days', relativeTo: rel }));
t('time to months', () => D.from('PT1000H').round({ largestUnit: 'months', smallestUnit: 'hours', relativeTo: rel }));
t('relativeTo datetime string', () => D.from('PT36H').round({ largestUnit: 'days', relativeTo: '2024-01-01T12:00' }));
t('relativeTo bag', () => D.from('P45D').round({ largestUnit: 'months', relativeTo: { year: 2024, month: 2, day: 1 } }));
t('relativeTo PlainDateTime', () => D.from('P45D').round({ largestUnit: 'months', relativeTo: Temporal.PlainDateTime.from('2024-02-01T23:00') }));
t('relativeTo bad string', () => D.from('P1D').round({ largestUnit: 'months', relativeTo: 'tomorrow' }));
t('relativeTo Z string', () => D.from('P1D').round({ largestUnit: 'months', relativeTo: '2024-01-01T00:00Z' }));
t('relativeTo number', () => D.from('P1D').round({ largestUnit: 'months', relativeTo: 20240101 }));
t('relativeTo bag missing day', () => D.from('P1D').round({ largestUnit: 'months', relativeTo: { year: 2024, month: 1 } }));
t('relativeTo hebrew', () => D.from('P60D').round({ largestUnit: 'months', relativeTo: Temporal.PlainDate.from('2024-01-31[u-ca=hebrew]') }));
t('out of range result', () => D.from('P1D').round({ largestUnit: 'days', relativeTo: '+275760-09-13' }));
''')


def test_duration_round_relative_to_zoned(run, workdir):
    """CATCHES: Duration.round with a ZonedDateTime relativeTo: days are not 24h across DST (23h/25h days), offset/zone strings as relativeTo, and offset mismatches in relativeTo strings."""
    check(run, workdir, "duration_round_relative_to_zoned", r'''
const z = Temporal.ZonedDateTime.from('2024-03-09T12:00[America/New_York]');
t('PT48H to days', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: z }));
t('PT47H to days', () => D.from('PT47H').round({ largestUnit: 'days', relativeTo: z }));
t('P2D to hours', () => D.from('P2D').round({ largestUnit: 'hours', relativeTo: z }));
t('P1D to hours on spring day', () => D.from('P1D').round({ largestUnit: 'hours', relativeTo: '2024-03-10T00:00[America/New_York]' }));
t('P1D to hours on fall day', () => D.from('P1D').round({ largestUnit: 'hours', relativeTo: '2024-11-03T00:00[America/New_York]' }));
t('PT36H round days on 25h day', () => D.from('PT12H30M').round({ smallestUnit: 'days', relativeTo: '2024-11-03T00:00[America/New_York]' }));
t('PT11H30M round days on 23h day', () => D.from('PT11H30M').round({ smallestUnit: 'days', relativeTo: '2024-03-10T00:00[America/New_York]' }));
t('months from zoned', () => D.from('P45DT6H').round({ largestUnit: 'months', relativeTo: z }));
t('years from zoned', () => D.from('PT10000H').round({ largestUnit: 'years', relativeTo: z }));
t('weeks smallest from zoned', () => D.from('P10D').round({ smallestUnit: 'weeks', relativeTo: z }));
t('negative from zoned', () => D.from('-PT48H').round({ largestUnit: 'days', relativeTo: z }));
t('relativeTo string with offset', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: '2024-03-09T12:00-05:00[America/New_York]' }));
t('relativeTo string wrong offset', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: '2024-03-09T12:00-04:00[America/New_York]' }));
t('relativeTo bag with timeZone', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, hour: 12, timeZone: 'America/New_York' } }));
t('relativeTo bag bad timeZone', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, timeZone: 'Nowhere' } }));
t('relativeTo string bad zone', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: '2024-03-09T12:00[Nowhere/Zone]' }));
t('relativeTo Z with zone', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: '2024-03-09T17:00Z[America/New_York]' }));
t('lord howe P1D in hours', () => D.from('P1D').round({ largestUnit: 'minutes', relativeTo: '2024-10-06T00:00[Australia/Lord_Howe]' }));
''')


def test_duration_total(run, workdir):
    """CATCHES: Duration.total bugs: exact fractional totals of time units, calendar units requiring relativeTo, month/year totals depending on month lengths from the relativeTo date, DST-aware day totals with a ZonedDateTime, and unit validation errors."""
    check(run, workdir, "duration_total", r'''
const x = D.from('PT1H30M45.5S');
t('hours', () => x.total('hours'));
t('minutes', () => x.total({ unit: 'minutes' }));
t('seconds', () => x.total('second'));
t('ms', () => x.total('milliseconds'));
t('ns', () => x.total('nanoseconds'));
t('days', () => D.from('PT36H').total('days'));
t('days from P1D no relativeTo', () => D.from('P1DT12H').total('hours'));
t('weeks no relativeTo', () => D.from('P14D').total('weeks'));
t('months no relativeTo', () => D.from('P1M').total('days'));
t('months from Feb leap', () => D.from('P45D').total({ unit: 'months', relativeTo: '2024-02-01' }));
t('months from Feb common', () => D.from('P45D').total({ unit: 'months', relativeTo: '2023-02-01' }));
t('years from 2024', () => D.from('P183D').total({ unit: 'years', relativeTo: '2024-01-01' }));
t('days of P1M from Jan', () => D.from('P1M').total({ unit: 'days', relativeTo: '2024-01-15' }));
t('weeks of P1Y', () => D.from('P1Y').total({ unit: 'weeks', relativeTo: '2024-01-01' }));
t('negative months', () => D.from('-P45D').total({ unit: 'months', relativeTo: '2024-03-31' }));
t('hours of P1D on spring day', () => D.from('P1D').total({ unit: 'hours', relativeTo: '2024-03-10T00:00[America/New_York]' }));
t('days of PT24H on fall day', () => D.from('PT24H').total({ unit: 'days', relativeTo: '2024-11-03T00:00[America/New_York]' }));
t('months zoned', () => D.from('P1M').total({ unit: 'hours', relativeTo: '2024-03-01T00:00[America/New_York]' }));
t('no unit', () => x.total({}));
t('no options', () => x.total());
t('bad unit', () => x.total('decades'));
t('unit auto', () => x.total('auto'));
t('options number', () => x.total(5));
t('large ns total', () => D.from({ seconds: Number.MAX_SAFE_INTEGER, nanoseconds: 999999999 }).total('seconds'));
t('one third', () => D.from('PT1S').total('minutes'));
''')


def test_duration_compare(run, workdir):
    """CATCHES: Duration.compare bugs: time-only comparison by exact nanoseconds, calendar units requiring relativeTo, comparisons that depend on the relativeTo month length or DST day lengths, and string/bag arguments."""
    check(run, workdir, "duration_compare", r'''
t('equal', () => D.compare('PT1H', 'PT60M'));
t('less', () => D.compare('PT59M59.999999999S', 'PT1H'));
t('greater', () => D.compare({ hours: 25 }, { days: 1 }));
t('days vs 24h', () => D.compare('P1D', 'PT24H'));
t('negative', () => D.compare('-PT1H', 'PT1S'));
t('months no relativeTo', () => D.compare('P1M', 'P30D'));
t('identical calendar durations no relativeTo', () => D.compare('P1M', 'P1M'));
t('months vs 30d from Feb', () => D.compare('P1M', 'P30D', { relativeTo: '2024-02-01' }));
t('months vs 30d from Jan', () => D.compare('P1M', 'P30D', { relativeTo: '2024-01-01' }));
t('months vs 31d from Jan', () => D.compare('P1M', 'P31D', { relativeTo: '2024-01-01' }));
t('year vs 365d leap', () => D.compare('P1Y', 'P365D', { relativeTo: '2024-01-01' }));
t('year vs 365d common', () => D.compare('P1Y', 'P365D', { relativeTo: '2023-01-01' }));
t('weeks vs days', () => D.compare('P2W', 'P14D', { relativeTo: '2023-01-01' }));
t('day vs 24h on spring day', () => D.compare('P1D', 'PT24H', { relativeTo: '2024-03-10T00:00[America/New_York]' }));
t('day vs 23h on spring day', () => D.compare('P1D', 'PT23H', { relativeTo: '2024-03-10T00:00[America/New_York]' }));
t('day vs 25h on fall day', () => D.compare('P1D', 'PT25H', { relativeTo: '2024-11-03T00:00[America/New_York]' }));
t('bad relativeTo', () => D.compare('P1M', 'P1D', { relativeTo: 'x' }));
t('bad argument', () => D.compare('P1M', 5));
t('sort', () => ['PT2H', 'PT90M', 'P1D', 'PT1S'].map((s) => D.from(s)).sort(D.compare).join(' '));
t('large values', () => D.compare({ seconds: Number.MAX_SAFE_INTEGER }, { seconds: Number.MAX_SAFE_INTEGER - 1 }));
''')


def test_duration_from_until_results(run, workdir):
    """CATCHES: interplay of difference methods and Duration: results are exact Duration objects with the right largest unit, round-trip add(until()) returns the target, and negated since() equals until()."""
    check(run, workdir, "duration_from_until_results", r'''
const a = Temporal.PlainDateTime.from('2023-12-31T23:30');
const b = Temporal.PlainDateTime.from('2025-03-01T00:15:00.000000001');
for (const lu of ['years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds', 'milliseconds', 'microseconds', 'nanoseconds']) {
  t('largest ' + lu, () => { const d = a.until(b, { largestUnit: lu }); return `${d} roundtrip=${a.add(d).equals(b)}`; });
}
t('since negated equals until', () => a.since(b).negated().toString() === a.until(b).toString());
t('Instant until ns', () => Temporal.Instant.fromEpochNanoseconds(0n).until(Temporal.Instant.fromEpochNanoseconds(10n ** 18n), { largestUnit: 'hours' }));
t('PlainTime until nanos', () => Temporal.PlainTime.from('00:00').until('23:59:59.999999999', { largestUnit: 'nanoseconds' }));
''')


def test_duration_to_locale_string(run, workdir):
    """CATCHES: Duration.prototype.toLocaleString not delegating to Intl.DurationFormat: long/short/narrow/digital styles, locale-specific unit names, negative durations and brand checks."""
    check(run, workdir, "duration_to_locale_string", r'''
const x = D.from('P1Y2M3DT4H5M6.789S');
t('en default', () => x.toLocaleString('en'));
t('en long', () => x.toLocaleString('en', { style: 'long' }));
t('en narrow', () => x.toLocaleString('en', { style: 'narrow' }));
t('en digital', () => D.from('PT4H5M6S').toLocaleString('en', { style: 'digital' }));
t('de long', () => x.toLocaleString('de', { style: 'long' }));
t('fr short', () => x.toLocaleString('fr'));
t('negative', () => D.from('-PT1H30M').toLocaleString('en', { style: 'long' }));
t('zero', () => new D().toLocaleString('en'));
t('brand', () => D.prototype.toLocaleString.call({}));
t('name', () => D.prototype.toLocaleString.name + ' ' + D.prototype.toLocaleString.length);
''')


def test_duration_relative_to_property_bags(run, workdir):
    """CATCHES: relativeTo property-bag bugs: calendar field forms (string, Temporal object, number), era/eraYear in era calendars, monthCode, time fields (negative ones are errors), offset strings with timeZone (mismatch is an error), timeZone as a ZonedDateTime, and relativeTo strings with unsupported calendars, offsets or out-of-range dates."""
    check(run, workdir, "duration_relative_to_property_bags", r'''
const d = D.from('P45D');
const r = (rel) => d.round({ largestUnit: 'months', relativeTo: rel });
t('bag iso', () => r({ year: 2024, month: 1, day: 31 }));
t('bag monthCode', () => r({ year: 2024, monthCode: 'M02', day: 1 }));
t('bag calendar string', () => r({ year: 5784, month: 6, day: 1, calendar: 'hebrew' }));
t('bag calendar Temporal', () => r({ year: 2024, month: 2, day: 1, calendar: Temporal.PlainDate.from('2024-01-01[u-ca=gregory]') }));
t('bag calendar number', () => r({ year: 2024, month: 2, day: 1, calendar: 1 }));
t('bag calendar bad', () => r({ year: 2024, month: 2, day: 1, calendar: 'nope' }));
t('bag era', () => r({ era: 'ce', eraYear: 2024, month: 2, day: 1, calendar: 'gregory' }));
t('bag era japanese', () => r({ era: 'reiwa', eraYear: 6, month: 2, day: 1, calendar: 'japanese' }));
t('bag constrain day', () => r({ year: 2023, month: 2, day: 31 }));
t('bag time fields', () => D.from('PT36H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 1, day: 1, hour: 25, minute: 61, second: 61, millisecond: 1000, microsecond: 1000, nanosecond: 1000 } }));
t('bag negative hour', () => r({ year: 2024, month: 1, day: 1, hour: -1 }));
t('bag missing year', () => r({ month: 1, day: 1 }));
t('bag huge year', () => r({ year: 999999, month: 1, day: 1 }));
t('bag tz + offset', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, hour: 12, offset: '-05:00', timeZone: 'America/New_York' } }));
t('bag tz + wrong offset', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, hour: 12, offset: '-04:00', timeZone: 'America/New_York' } }));
t('bag offset object', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, offset: { toString() { return '-05:00'; } }, timeZone: 'America/New_York' } }));
t('bag offset number', () => r({ year: 2024, month: 3, day: 9, offset: 5, timeZone: 'UTC' }));
t('bag offset bad', () => r({ year: 2024, month: 3, day: 9, offset: '+5', timeZone: 'UTC' }));
t('bag timeZone ZonedDateTime', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, timeZone: Z0 } }));
t('bag timeZone object', () => r({ year: 2024, month: 3, day: 9, timeZone: {} }));
t('bag timeZone number', () => r({ year: 2024, month: 3, day: 9, timeZone: 5 }));
t('bag timeZone offset string', () => D.from('PT48H').round({ largestUnit: 'days', relativeTo: { year: 2024, month: 3, day: 9, timeZone: '+05:30' } }));
t('bag tz huge year', () => r({ year: 275760, month: 9, day: 14, timeZone: 'UTC' }));
t('string unsupported calendar', () => r('2024-01-01[u-ca=klingon]'));
t('string calendar', () => r('2024-01-01[u-ca=coptic]'));
t('string time only', () => r('12:00'));
t('string offset zone', () => r('2024-01-01T00:00+05:30[+05:30]'));
t('string offset no zone', () => r('2024-01-01T00:00+05:30'));
t('string out of range', () => r('+275760-09-14'));
t('string zoned out of range', () => r('+275760-09-14T00:00[UTC]'));
t('string sub-minute offset exact', () => D.from('P1D').round({ largestUnit: 'hours', relativeTo: '1800-01-01T00:00-00:01:15[Europe/London]' }));
t('PlainDateTime relativeTo keeps date only', () => D.from('PT20H').round({ largestUnit: 'days', relativeTo: Temporal.PlainDateTime.from('2024-01-01T23:00') }));
t('getter order', () => {
  const log = [];
  const bag = new Proxy({ year: 2024, month: 1, day: 1 }, { get(o, k) { if (typeof k === 'string') log.push(k); return o[k]; } });
  d.round({ largestUnit: 'months', relativeTo: bag });
  return log.join(',');
});
'''.replace('Z0', "Temporal.ZonedDateTime.from('2020-01-01T00:00[America/New_York]')"))


def test_duration_rounding_bubbles_up(run, workdir):
    """CATCHES: Duration.round relativeTo bugs where rounding the smallest unit must carry ("bubble") into larger units: days into weeks/months/years, hours into days on DST-length days, and time rounding against the real day span with a ZonedDateTime relativeTo."""
    check(run, workdir, "duration_rounding_bubbles_up", r'''
const pd = '2024-01-01';
const zd = '2024-03-09T00:00[America/New_York]';
t('P11M30DT23H -> years (plain)', () => D.from('P11M30DT23H').round({ largestUnit: 'years', smallestUnit: 'days', roundingMode: 'ceil', relativeTo: pd }));
t('P11M30DT23H -> years (zoned)', () => D.from('P11M30DT23H').round({ largestUnit: 'years', smallestUnit: 'days', roundingMode: 'ceil', relativeTo: zd }));
t('P1M29D -> months halfExpand', () => D.from('P1M29D').round({ largestUnit: 'months', smallestUnit: 'days', roundingIncrement: 5, roundingMode: 'halfExpand', relativeTo: pd }));
t('P6DT23H -> weeks', () => D.from('P6DT23H').round({ largestUnit: 'weeks', smallestUnit: 'days', roundingMode: 'halfExpand', relativeTo: pd }));
t('P6DT23H -> weeks zoned', () => D.from('P6DT23H').round({ largestUnit: 'weeks', smallestUnit: 'hours', roundingIncrement: 2, roundingMode: 'ceil', relativeTo: zd }));
t('P1W6DT23H59M -> months ceil minutes', () => D.from('P1W6DT23H59M').round({ largestUnit: 'months', smallestUnit: 'hours', roundingMode: 'ceil', relativeTo: pd }));
t('zoned hours into day on 23h day', () => D.from('P1DT22H30M').round({ largestUnit: 'days', smallestUnit: 'hours', roundingMode: 'halfExpand', relativeTo: zd }));
t('zoned hours exactly one 23h day', () => D.from('P1DT23H').round({ largestUnit: 'days', smallestUnit: 'hours', relativeTo: zd }));
t('zoned minutes negative', () => D.from('-P1DT22H30M').round({ largestUnit: 'days', smallestUnit: 'minutes', roundingIncrement: 30, relativeTo: '2024-03-11T00:00[America/New_York]' }));
t('zoned ns no change', () => D.from('P1DT1H').round({ largestUnit: 'days', smallestUnit: 'nanoseconds', relativeTo: zd }));
t('zoned months smallest hours', () => D.from('P1M2DT25H').round({ largestUnit: 'months', smallestUnit: 'hours', relativeTo: zd }));
t('zoned years from 25h days', () => D.from('P364DT24H').round({ largestUnit: 'years', relativeTo: '2024-01-01T00:00[America/New_York]' }));
t('zoned total days with time', () => D.from('P1DT12H').total({ unit: 'days', relativeTo: zd }));
t('zoned total months with time', () => D.from('P1MT12H').total({ unit: 'months', relativeTo: zd }));
t('plain total zero', () => D.from('PT0S').total({ unit: 'months', relativeTo: pd }));
t('plain total years negative', () => D.from('-P1Y6M').total({ unit: 'years', relativeTo: pd }));
t('plain total weeks', () => D.from('P1M').total({ unit: 'weeks', relativeTo: pd }));
t('plain total hours', () => D.from('P1M').total({ unit: 'hours', relativeTo: pd }));
t('plain total ns huge', () => D.from({ days: 100000000 }).total({ unit: 'nanoseconds', relativeTo: pd }));
t('days-only largest days relativeTo', () => D.from('PT49H').round({ largestUnit: 'days', relativeTo: pd }));
t('round with relativeTo, time only smallest', () => D.from('PT1H1M').round({ smallestUnit: 'hours', relativeTo: pd }));
''')


def test_duration_misc_edge_cases(run, workdir):
    """CATCHES: Duration edge cases: default largest unit picks the largest non-zero component (weeks, ms, us), round() options type errors and invalid largestUnit, compare with mismatched relativeTo, string parser rejecting trailing digits, and abs/negated on mixed zero components."""
    check(run, workdir, "duration_misc_edge_cases", r'''
t('round options number', () => D.from('PT1H').round(5));
t('round invalid largest', () => D.from('PT1H').round({ largestUnit: 'eons' }));
t('round largest auto smallest ms', () => D.from('PT1.5S').round({ largestUnit: 'auto', smallestUnit: 'milliseconds' }));
t('round default largest weeks', () => D.from('P2W3D').round({ smallestUnit: 'days', relativeTo: '2024-01-01' }));
t('round default largest ms', () => D.from({ milliseconds: 1500, microseconds: 1 }).round({ smallestUnit: 'microseconds' }));
t('round default largest us', () => D.from({ microseconds: 1500 }).round({ smallestUnit: 'nanoseconds' }));
t('round default largest ns', () => D.from({ nanoseconds: 1500 }).round({ smallestUnit: 'nanoseconds' }));
t('round largest smaller than existing', () => D.from('PT2H').round({ largestUnit: 'seconds' }));
t('round smallest us halfEven', () => D.from({ nanoseconds: 2500 }).round({ smallestUnit: 'microseconds', roundingMode: 'halfEven' }));
t('round incr 3 hours', () => D.from('PT10H').round({ smallestUnit: 'hours', roundingIncrement: 3 }));
t('round incr 13 hours', () => D.from('PT10H').round({ smallestUnit: 'hours', roundingIncrement: 13 }));
t('round incr 500 ms', () => D.from('PT1.3S').round({ smallestUnit: 'milliseconds', roundingIncrement: 500 }));
t('round incr 1000 ms', () => D.from('PT1.3S').round({ smallestUnit: 'milliseconds', roundingIncrement: 1000 }));
t('round incr days 3 relativeTo', () => D.from('P10D').round({ smallestUnit: 'days', roundingIncrement: 3, relativeTo: '2024-01-01' }));
t('round incr 1e9 days', () => D.from('P10D').round({ smallestUnit: 'days', roundingIncrement: 1e9, relativeTo: '2024-01-01' }));
t('round incr 1e9+1', () => D.from('P10D').round({ smallestUnit: 'days', roundingIncrement: 1e9 + 1, relativeTo: '2024-01-01' }));
t('round incr 2.9 truncates', () => D.from('PT5H').round({ smallestUnit: 'hours', roundingIncrement: 2.9 }));
t('round incr string', () => D.from('PT5H').round({ smallestUnit: 'hours', roundingIncrement: '2' }));
t('round incr Infinity', () => D.from('PT5H').round({ smallestUnit: 'hours', roundingIncrement: Infinity }));
t('compare bad relativeTo type', () => D.compare('P1D', 'P2D', { relativeTo: 5 }));
t('compare options not object', () => D.compare('P1D', 'P2D', 'x'));
t('compare weeks without relativeTo', () => D.compare('P1W', 'P7D'));
t('compare zoned relativeTo months', () => D.compare('P1M', 'P31D', { relativeTo: '2024-01-15T00:00[Europe/London]' }));
t('compare far out of range relativeTo', () => D.compare({ years: 4000 }, { days: 1 }, { relativeTo: '+275000-01-01' }));
for (const s of ['P1', 'PT1', 'P1Y1', 'PT1H1', 'P1DT1H1M1', 'PT1.5', 'P-1D', '-PT-1S', 'P1W1W', 'P1D1D', 'PT.5S', 'PT1.5.5S', 'PT1X', 'PT1S1M'])
  t(JSON.stringify(s), () => D.from(s));
t('abs of zero', () => new D().abs());
t('negated keeps zero', () => D.from('PT0S').negated().sign);
t('with all undefined', () => D.from('P1D').with({ days: undefined }));
t('with fractional', () => D.from('P1D').with({ days: 1.5 }));
t('with -0', () => Object.is(D.from('P1D').with({ days: -0 }).days, 0));
t('from with overflowing ns', () => D.from({ nanoseconds: Number.MAX_VALUE }));
t('toString ns rounding into seconds', () => D.from({ seconds: 1, nanoseconds: 999999999 }).toString({ fractionalSecondDigits: 3, roundingMode: 'halfExpand' }));
t('toString smallestUnit us', () => D.from({ seconds: 1, nanoseconds: 999999 }).toString({ smallestUnit: 'microseconds' }));
t('toString smallestUnit bad', () => D.from('PT1S').toString({ smallestUnit: 'eon' }));
t('toString negative fsd 0 trunc', () => D.from('-PT1.9S').toString({ fractionalSecondDigits: 0 }));
''')
