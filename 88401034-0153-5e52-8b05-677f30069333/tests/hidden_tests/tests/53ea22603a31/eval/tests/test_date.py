"""Date: construction from components/timestamps/strings, Date.UTC, Date.parse (strict ISO and the
lenient fallback formats), getters and setters with overflow normalisation, the string formats
(toISOString/toJSON/toString/toDateString/toTimeString/toUTCString, toLocale*), the time-value range
limits, Symbol.toPrimitive, and local-time behaviour under different TZ settings. Every test builds
dates from fixed values; none reads the clock."""

from conftest import assert_result, check_script, resources_for

G = resources_for(__file__)

PRE = r'''
const iso = (d) => isNaN(d) ? 'Invalid' : d.toISOString();
const err = (f) => { try { return 'ok ' + String(f()); } catch (e) { return e.name + ': ' + e.message; } };
'''


def test_date_utc_and_component_constructor(run, workdir):
    r"""CATCHES: Date.UTC / new Date(y, m, ...) not mapping two-digit years 0-99 to 1900+, not
    normalising overflowing/negative months, days, hours, minutes, seconds and milliseconds,
    truncating fractional components wrongly, NaN propagation from any component, missing-argument
    defaults, and TimeClip at +-8.64e15."""
    check_script(run, workdir, G, "utc_and_components", PRE + r'''
console.log(Date.UTC(2024), Date.UTC(), Date.UTC(99, 11, 31), Date.UTC(100, 0), Date.UTC(-1, 0), Date.UTC(0), Date.UTC(99.9), Date.UTC(-0.5));
console.log(Date.UTC(2024, 1, 29, 23, 59, 59, 999), Date.UTC(2024, 12), Date.UTC(2024, -1), Date.UTC(2024, 0, 0), Date.UTC(2024, 0, 1, 24), Date.UTC(2024, 0, 1, 0, -1), Date.UTC(2024, 0, 1, 0, 0, 0, -1));
console.log(Date.UTC(2024, 0, 1.9, 1.9, 1.9, 1.9, 1.9), Date.UTC(2024, NaN), Date.UTC(2024, 0, 1, Infinity), Date.UTC('2024', '1', '2'), Date.UTC(1e6), Date.UTC(275760, 8, 13), Date.UTC(275760, 8, 13, 0, 0, 0, 1), Date.UTC(-271821, 3, 20), Date.UTC(-271821, 3, 19, 23, 59, 59, 999));
console.log(iso(new Date(2024, 0, 31, 25, 61, 61, 1001)), iso(new Date(99, 0)), iso(new Date(0, 0)), iso(new Date(-1, 0)), iso(new Date(2024, 1)), iso(new Date(2024, 13, 1)), iso(new Date(1970, 0, 1, 0, 0, 0, -1)));
console.log(iso(new Date(2024, 0, 1, 0, 0, 0, 0.9)), iso(new Date(2024, undefined)), iso(new Date(2024, 0, undefined)), iso(new Date('2024', '5')), iso(new Date(2024, 0, 1, NaN)), iso(new Date(1e5, 0)));
console.log(new Date(8.64e15).getTime(), new Date(8.64e15 + 1).getTime(), new Date(-8.64e15).getTime(), new Date(-8.64e15 - 1).getTime(), new Date(1.9).getTime(), new Date(-1.9).getTime(), Object.is(new Date(-0).getTime(), 0));
console.log(new Date(new Date(123)).getTime(), new Date({ valueOf() { return 456; } }).getTime(), new Date({ toString() { return '1970-01-01T00:00:01Z'; }, valueOf: undefined }).getTime(), new Date(true).getTime(), new Date(null).getTime(), new Date(undefined).getTime(), new Date('').getTime());
console.log(Date.length, Date.UTC.length, Date.name, typeof Date.prototype.constructor, Object.prototype.toString.call(new Date(0)), Object.prototype.toString.call(Date.prototype));
''')


ISO_STRINGS = [
    "2024-03-10", "2024-03-10T12:34", "2024-03-10T12:34:56.789", "2024-03-10T12:34:56.789Z",
    "2024-03-10T12:34:56+05:30", "2024-03-10T12:34:56.1234567-08:00", "2024-03", "2024", "+002024-03-10",
    "-000001-01-01T00:00:00Z", "-000000-01-01T00:00:00Z", "+275760-09-13T00:00:00.000Z",
    "+275760-09-13T00:00:00.001Z", "-271821-04-20T00:00:00.000Z", "-271821-04-19T23:59:59.999Z",
    "2024-02-30", "2024-13-01", "2001-00-05", "2001-01-00", "2024-03-10T24:00", "2024-03-10T24:00:01",
    "2024-03-10T25:00", "2001-01-05T23:59:60", "2024-03-10 12:34:56", "2024-03-10T12:34:56z", "2024-3-10",
    "2001-01-05 12", "2001-01-05T12", "2001-01-05T", "2001-01-05T12:00:00.", "2001-01-05T12:00:00.12",
    "2001-01-05T12:00+0100", "2001-01-05 12:00+0100", "2001-01-05 12:00 +01", "2001-01-05 1:2:3",
    "-002001-01-05", "002001-01-05", "20010105", "2001-1-5 10:00", " 2001-01-05 ",
    "2001-01-05T12:00:00.000+24:00", "2001-01-05T12:00:00.000-00:00", "1970-01-01T00:00:00.000+00:00",
    "2024-03-10T12:34:56,789Z", "2024-06-15T10:00:00.5Z", "T12:00",
]


def test_parse_iso_formats(run, workdir):
    r"""CATCHES: an ISO-8601 parser that rejects valid forms (date-only, partial dates, missing
    seconds, extended +/-YYYYYY years, fractional seconds of any length truncated to ms, offsets),
    accepts invalid ones (-000000, lowercase z, comma decimals, 5-digit/unsigned 6-digit years,
    compact forms), treats date-only or date-time forms differently from the reference (local time
    is UTC here), or differs from the reference's lenient handling of out-of-range fields (Feb 30,
    month 13, hour 25 roll over) and the space-separated form; new Date(str) and Date.parse must
    agree for these."""
    src = PRE + "const strs = " + repr(ISO_STRINGS) + ";\n" + r'''
for (const s of strs) {
  const p = Date.parse(s);
  const c = new Date(s).getTime();
  console.log(JSON.stringify(s).padEnd(36), String(p).padStart(16), isNaN(p) ? '' : new Date(p).toISOString(), Object.is(p, c) ? '' : 'ctor=' + c);
}
'''
    check_script(run, workdir, G, "parse_iso", src)


FALLBACK_STRINGS = [
    "Sun Mar 10 2024 12:34:56 GMT+0000 (Coordinated Universal Time)", "Sun, 10 Mar 2024 12:34:56 GMT",
    "Mar 10 2024", "Tue Mar 10 2024", "March 10, 2024 10:00 PM", "Mar 10, 2024 12:00:00 EST",
    "Thu, 01 Jan 1970 00:00:00 PDT", "10 Mar 2024 12:00 +0200", "Thu, 01 Jan 1970 00:00:00 GMT+0130",
    "Jan 1 1970 00:00:00 GMT-0230", "Sat Jan 01 2000 12:00:00 GMT+0100 (CET)", "2000 Jan 1", "1 2 3",
    "Jan 2000", "Jan 32 2000", "Feb 30 2001 10:00", "December 25, 1995 23:15:30", "Dec 25 1995 1:2:3",
    "Dec 25 1995 13:61:61", "dec 25 95", "Monday December 25 1995", "Tue Dec 25 -1995", "12:00 Jan 5 2001",
    "Jan 5 2001 12:00 garbage", "3/10/2024", "2024/03/10", "12/31/1999 23:59:59", "Jan 1 10000",
    "01 Jan 99", "garbage", "",
]


def test_parse_fallback_formats(run, workdir):
    r"""CATCHES: differences from the reference's lenient Date.parse fallback (month names anywhere,
    day/year by magnitude, "GMT+hhmm" offsets honoured but zone abbreviations, AM/PM and bare
    "+hhmm" tokens not -- a bare +0200 is even taken as the year 200, slash dates rejected, field
    overflow rolling over) and the reference quirk that new Date(string) only accepts the ISO
    grammar, so it is Invalid Date for every non-ISO string even when Date.parse succeeds (also for
    the strings produced by toString/toUTCString)."""
    src = PRE + "const strs = " + repr(FALLBACK_STRINGS) + ";\n" + r'''
for (const s of strs) {
  const p = Date.parse(s);
  console.log(JSON.stringify(s), p, isNaN(p) ? '' : new Date(p).toISOString(), 'ctor:' + new Date(s).getTime());
}
const d = new Date(Date.UTC(2001, 8, 9, 1, 46, 40, 123));
for (const f of ['toString', 'toUTCString', 'toISOString', 'toDateString', 'toGMTString'])
  console.log(f, Date.parse(d[f]()), new Date(d[f]()).getTime());
console.log(Date.parse({ toString() { return '1970-01-02'; } }), Date.parse(), Date.parse(0), Date.parse('2000'), Date.parse.length);
'''
    check_script(run, workdir, G, "parse_fallback", src)


def test_getters_local_and_utc(run, workdir):
    r"""CATCHES: wrong civil-date arithmetic for negative time values, leap years (incl. 1900 and
    2000 and proleptic years < 0), weekdays, the local getters differing from the UTC getters when
    the offset is 0, getTimezoneOffset not 0 (NaN for invalid dates), Annex-B getYear, and getters
    on invalid dates returning anything but NaN."""
    check_script(run, workdir, G, "getters", PRE + r'''
const names = ['FullYear', 'Month', 'Date', 'Day', 'Hours', 'Minutes', 'Seconds', 'Milliseconds'];
const stamps = [0, -1, 1e12, 951782400000, 951868800000, -2203891200000, -62135596800001, 253402300799999, -8.64e15, 8.64e15, 1709210096789, -62198755200000];
for (const t of stamps) {
  const d = new Date(t);
  const local = names.map(n => d['get' + n]());
  const utc = names.map(n => d['getUTC' + n]());
  console.log(String(t).padStart(17), local.join(' '), JSON.stringify(local) === JSON.stringify(utc) ? 'same' : 'utc=' + utc.join(' '), d.getTimezoneOffset(), d.getYear(), d.getTime() === d.valueOf());
}
const bad = new Date(NaN);
console.log(names.map(n => bad['get' + n]()).join(' '), names.map(n => bad['getUTC' + n]()).join(' '), bad.getTimezoneOffset(), bad.getYear(), bad.getTime());
console.log(err(() => Date.prototype.getTime.call({})), '|', err(() => Date.prototype.getFullYear.call(Date.prototype)), '|', err(() => Date.prototype.getDay.call(0)), '|', err(() => Date.prototype.valueOf.call({ valueOf() { return 1; } })));
''')


def test_setters_overflow_and_nan(run, workdir):
    r"""CATCHES: setters not normalising overflow (setMonth(13), setDate(0/-1), setHours(48,-1,...)),
    not returning the new time value, ignoring the optional trailing arguments, coercing
    arguments in the wrong order relative to the this-check, not producing NaN (Invalid Date) for
    NaN/missing arguments or results beyond 8.64e15, and NaN dates staying NaN except for
    setFullYear/setYear which start from +0."""
    check_script(run, workdir, G, "setters", PRE + r'''
const base = Date.UTC(2024, 0, 31, 10, 30, 45, 123);
const cases = [
  ['setMonth', [1]], ['setUTCMonth', [13, 0]], ['setDate', [0]], ['setDate', [-1]], ['setHours', [48, -1, 3600, -1]],
  ['setMinutes', [1e6]], ['setSeconds', [-86400]], ['setMilliseconds', [1e9]], ['setFullYear', [2023, 1, 29]],
  ['setUTCFullYear', [-5]], ['setTime', ['86400000']], ['setTime', []], ['setHours', [NaN]], ['setFullYear', [275760, 8, 13]],
  ['setUTCFullYear', [275760, 8, 12]], ['setHours', []], ['setMonth', [2, 31]], ['setUTCHours', [23, 59, 59, 1000]],
  ['setUTCMinutes', [0, 0, 0, 999]], ['setUTCSeconds', [1.9, 2.9]], ['setUTCMilliseconds', [-0.5]], ['setUTCDate', [366]],
  ['setMonth', [0, 1, 99]], ['setFullYear', [2024.7]], ['setSeconds', [Infinity]], ['setMinutes', [1, '2', '3']],
];
const label = (args) => '[' + args.map(a => typeof a === 'string' ? JSON.stringify(a) : String(a)).join(',') + ']';
for (const [m, args] of cases) { const d = new Date(base); const r = d[m](...args); console.log(m.padEnd(19), label(args).padEnd(22), String(r).padStart(16), iso(d)); }
for (const m of ['setFullYear', 'setUTCFullYear', 'setMonth', 'setDate', 'setHours', 'setMilliseconds']) { const d = new Date(NaN); console.log('NaN.' + m, d[m](2000), iso(d)); }
const y = new Date(base); console.log(y.setYear(99), iso(y), y.setYear(2001), y.setYear(-1), iso(y), y.getYear(), y.setYear(NaN), iso(y), new Date(NaN).setYear(5), iso(new Date(new Date(NaN).setYear(5))));
const order = []; const probe = (n) => ({ valueOf() { order.push(n); return 1; } });
new Date(base).setHours(probe('h'), probe('m'), probe('s'), probe('ms')); console.log(order.join(','));
console.log(err(() => Date.prototype.setHours.call({}, probe('never'))), order.join(','));
const nanBox = new Date(NaN); console.log(nanBox.setMinutes({ valueOf() { nanBox.setTime(0); return 5; } }), nanBox.getTime());
''')


def test_string_formats(run, workdir):
    r"""CATCHES: wrong toString/toDateString/toTimeString/toUTCString/toISOString layouts (zero
    padding, weekday/month names, "GMT+0000 (Coordinated Universal Time)" suffix), wrong year
    rendering for years < 1000, negative years and years > 9999 (ISO uses +/-YYYYYY), toGMTString
    not being the same function as toUTCString, and "Invalid Date" handling."""
    check_script(run, workdir, G, "string_formats", PRE + r'''
const stamps = [0, 1e12, -1, 951782400000, -62135596800001, -62198755200001, 253402300800000, -8.64e15, 8.64e15, Date.UTC(5, 4, 3, 2, 1, 0), Date.UTC(-44, 2, 15, 12)];
for (const t of stamps) {
  const d = new Date(t);
  console.log(d.toISOString(), '|', d.toString(), '|', d.toDateString(), '|', d.toTimeString(), '|', d.toUTCString(), '|', JSON.stringify(d));
}
const bad = new Date(NaN);
console.log(String(bad), bad.toDateString(), bad.toTimeString(), bad.toUTCString(), bad.toJSON(), JSON.stringify({ when: bad }), err(() => bad.toISOString()));
console.log(Date.prototype.toGMTString === Date.prototype.toUTCString, Date.prototype.toGMTString.name, `${new Date(0)}`, new Date(0) + '', String(new Date(1)));
console.log(err(() => Date.prototype.toString.call({})), '|', err(() => Date.prototype.toISOString.call(1)), '|', err(() => Date.prototype.toUTCString.call('x')));
''')


def test_tojson_and_to_primitive(run, workdir):
    r"""CATCHES: Date.prototype.toJSON not being generic (ToPrimitive number hint, null for
    non-finite, calling a user toISOString) or not throwing for a non-callable toISOString;
    Date @@toPrimitive with the wrong hint mapping (default -> string), not validating the hint,
    not being non-writable, and Date coercion in +, -, ==, <, template literals and JSON."""
    check_script(run, workdir, G, "tojson_toprimitive", PRE + r'''
const x = new Date(1e12);
console.log(x + 1, '|', x - 1, '|', `${x}`, '|', x * 1, +x, x > new Date(0), x == x.toString(), x == 1e12, x === x.valueOf(), [x] + '');
console.log(x[Symbol.toPrimitive]('number'), '|', x[Symbol.toPrimitive]('default'), '|', x[Symbol.toPrimitive]('string'));
console.log(err(() => x[Symbol.toPrimitive]('bogus')), '|', err(() => x[Symbol.toPrimitive](1)), '|', err(() => x[Symbol.toPrimitive]()), '|', err(() => Date.prototype[Symbol.toPrimitive].call(1, 'number')));
const plain = { toString() { return 'S'; }, valueOf() { return 7; } };
console.log(Date.prototype[Symbol.toPrimitive].call(plain, 'default'), Date.prototype[Symbol.toPrimitive].call(plain, 'number'), err(() => Date.prototype[Symbol.toPrimitive].call({ toString: null, valueOf: null }, 'string')));
const d = Object.getOwnPropertyDescriptor(Date.prototype, Symbol.toPrimitive); console.log(d.writable, d.enumerable, d.configurable, d.value.name, d.value.length);
const custom = new Date(0); custom.valueOf = () => 42; custom.toString = () => 'str'; console.log(custom + 1, custom * 2, `${custom}`);
console.log(JSON.stringify([new Date(0), new Date(NaN)]), Date.prototype.toJSON.call({ toISOString() { return 'custom'; } }), Date.prototype.toJSON.call({ valueOf() { return Infinity; }, toISOString() { return 'never'; } }));
console.log(err(() => Date.prototype.toJSON.call({ toISOString: 1 })), '|', err(() => Date.prototype.toJSON.call(null)), '|', Date.prototype.toJSON.call({ valueOf: () => 'not a number', toISOString: () => 'called' }));
''')


def test_to_locale_strings(run, workdir):
    r"""CATCHES: Date toLocaleString/toLocaleDateString/toLocaleTimeString with the default
    locale (en-US style "1/1/1970, 12:00:00 AM"), with explicit locales and dateStyle/timeStyle or
    component options, with a timeZone option converting through the IANA tables correctly across
    US/EU DST transitions and historical LMT offsets, the invalid-timezone RangeError, and
    "Invalid Date" for NaN dates. Pins two observed reference quirks: timeZoneName:'short' shows
    the zone's standard offset even during DST (GMT-5 for New York in July), and
    toLocaleDateString accepts a timeStyle-only option bag instead of throwing."""
    check_script(run, workdir, G, "to_locale", PRE + r'''
const d = new Date(Date.UTC(2024, 6, 4, 15, 5, 9));
console.log(d.toLocaleString(), '|', d.toLocaleDateString(), '|', d.toLocaleTimeString());
console.log(d.toLocaleString('en-US', { dateStyle: 'full', timeStyle: 'long' }), '|', d.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }), '|', d.toLocaleTimeString('en-US', { hour12: false }));
console.log(d.toLocaleDateString('de-DE'), '|', d.toLocaleDateString('ja-JP'), '|', d.toLocaleDateString(undefined, { month: 'short' }), '|', d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
const zones = ['America/New_York', 'Europe/London', 'Asia/Kolkata', 'Australia/Lord_Howe', 'America/Sao_Paulo', 'Etc/GMT+5', 'US/Pacific'];
const instants = [Date.UTC(2024, 2, 10, 6, 59, 59), Date.UTC(2024, 2, 10, 7, 0, 0), Date.UTC(2024, 2, 31, 1, 0, 0), Date.UTC(2024, 10, 3, 5, 59, 59), Date.UTC(2024, 10, 3, 6, 0, 0), Date.UTC(1900, 0, 1)];
for (const z of zones) console.log(z.padEnd(19), instants.map(t => new Date(t).toLocaleString('en-US', { timeZone: z })).join(' | '));
console.log(new Date(Date.UTC(2024, 6, 1)).toLocaleString('en-US', { timeZone: 'America/New_York', timeZoneName: 'short' }), '|', new Date(Date.UTC(2024, 0, 1)).toLocaleString('en-US', { timeZone: 'UTC', timeZoneName: 'short' }));
console.log(err(() => d.toLocaleString('en-US', { timeZone: 'Mars/Base' })), '|', err(() => d.toLocaleDateString('en-US', { timeStyle: 'short' })), '|', err(() => d.toLocaleString('not a locale!')));
console.log(new Date(NaN).toLocaleString(), new Date(NaN).toLocaleDateString(), new Date(NaN).toLocaleTimeString(), err(() => Date.prototype.toLocaleString.call({})));
''')


def test_local_time_ignores_tz_environment(run, workdir):
    r"""CATCHES: a runtime that honours the TZ environment variable for Date local time; the
    reference always uses UTC as the local zone (getTimezoneOffset 0, local getters equal UTC
    getters, toString shows GMT+0000 (Coordinated Universal Time), date-time strings without an
    offset are UTC, Intl's default timeZone is UTC) regardless of TZ, while an explicit timeZone
    option still converts."""
    src = r'''
const d = new Date(2024, 6, 1, 12, 30);
console.log(d.getTime(), d.getTimezoneOffset(), d.getHours(), d.getUTCHours(), d.toString());
console.log(new Date(2024, 0, 15).getTimezoneOffset(), Date.parse('2024-07-01T12:30'), Date.parse('2024-07-01'), new Date('2024-01-15T08:00').getHours());
console.log(d.toLocaleString(), '|', new Intl.DateTimeFormat().resolvedOptions().timeZone, '|', d.toLocaleString('en-US', { timeZone: 'America/New_York' }));
console.log(new Date(Date.UTC(2024, 2, 10, 7)).toTimeString(), new Date(Date.UTC(2024, 9, 27, 1)).getHours());
'''
    (workdir / "tz.js").write_text(src)
    utc = run(["tz.js"])
    assert_result(utc, G / "local_time_tz.golden")
    for zone in ["America/New_York", "Asia/Kolkata", "Europe/London", "Australia/Lord_Howe"]:
        other = run(["tz.js"], env_overrides={"TZ": zone})
        assert_result(other, G / "local_time_tz.golden")


def test_date_prototype_subclass_and_descriptors(run, workdir):
    r"""CATCHES: Date.prototype being a Date instance (it must be an ordinary object, so methods
    throw on it), subclassing Date not producing instances with working methods, Date objects
    gaining own properties, and Date's methods/properties having the wrong lengths or
    descriptors."""
    check_script(run, workdir, G, "prototype_and_subclass", PRE + r'''
class MyDate extends Date { constructor(...a) { super(...a); this.tag = 't'; } year() { return this.getUTCFullYear(); } }
const m = new MyDate(Date.UTC(2020, 5, 15));
console.log(m.year(), m.tag, m instanceof Date, m.toISOString(), Object.prototype.toString.call(m), JSON.stringify(m), String(new MyDate(0)).slice(0, 15));
console.log(Object.getOwnPropertyNames(new Date(0)).length, err(() => Date.prototype.getTime()), typeof Date.prototype.getTime);
const methods = ['getTime', 'setTime', 'setFullYear', 'setMonth', 'setDate', 'setHours', 'setMinutes', 'setSeconds', 'setMilliseconds', 'setUTCHours', 'toISOString', 'toJSON', 'toLocaleString', 'getYear', 'setYear'];
console.log(methods.map(n => n + '/' + Date.prototype[n].length).join(' '));
const pd = Object.getOwnPropertyDescriptor(Date, 'prototype'); console.log(pd.writable, pd.enumerable, pd.configurable, err(() => JSON.stringify(pd)), JSON.stringify(Object.getOwnPropertyDescriptor(Date.prototype, 'getTime')));
console.log(Reflect.construct(Date, [0], MyDate) instanceof MyDate, Reflect.construct(Date, [5], Object).getTime === undefined, err(() => Date.prototype.getTime.call(Reflect.construct(Date, [7], Object))));
console.log(typeof Date.now, Date.now.length, Date.parse.name, Date.UTC.name, typeof Date.prototype.toTemporalInstant);
console.log(new Date(0).toTemporalInstant ? String(new Date(1e12).toTemporalInstant()) : 'no temporal', err(() => new Date(NaN).toTemporalInstant()));
''')


def test_date_arithmetic_round_trips(run, workdir):
    r"""CATCHES: lossy round trips between time values, components and ISO strings (millisecond
    precision, negative years, the 400-year Gregorian cycle, end-of-month and leap-day rollovers)
    and wrong day differences across centuries, all computed with fixed inputs."""
    check_script(run, workdir, G, "round_trips", PRE + r'''
const days = (a, b) => (Date.UTC(...b) - Date.UTC(...a)) / 864e5;
const utcY = (y, m, d) => new Date(0).setUTCFullYear(y, m, d);
console.log(days([1900, 0, 1], [2000, 0, 1]), days([2000, 0, 1], [2100, 0, 1]), days([1600, 0, 1], [2000, 0, 1]), days([2024, 1, 28], [2024, 2, 1]), days([2023, 1, 28], [2023, 2, 1]));
console.log((utcY(0, 0, 1) - utcY(-400, 0, 1)) / 864e5, (utcY(100, 0, 1) - utcY(0, 0, 1)) / 864e5, utcY(0, 0, 1), utcY(-1, 1, 29), new Date(utcY(-4, 1, 29)).toISOString(), new Date(utcY(-1, 1, 29)).toISOString());
let ok = 0, first = null;
for (let t = -8.64e15; t <= 8.64e15; t += 8.64e15 / 4999 * 7 + 12345) {
  const d = new Date(Math.trunc(t));
  const back = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds(), d.getUTCMilliseconds());
  const viaIso = Date.parse(d.toISOString());
  if (back === d.getTime() && viaIso === d.getTime()) ok++; else if (first === null) first = d.getTime();
}
console.log('round trips ok', ok, 'first failure', first);
const leap = []; for (let y = 1896; y <= 2104; y += 4) if (new Date(Date.UTC(y, 1, 29)).getUTCMonth() !== 1) leap.push(y); console.log('non-leap multiples of 4:', leap.join(','));
const eom = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map(mo => { const d = new Date(Date.UTC(2024, 0, 31)); d.setUTCMonth(mo); return d.toISOString().slice(5, 10); }); console.log(eom.join(' '));
const step = new Date(Date.UTC(2024, 0, 1)); const seen = []; for (let i = 0; i < 6; i++) { step.setUTCDate(step.getUTCDate() + 61); seen.push(step.toISOString().slice(0, 10)); } console.log(seen.join(' '));
console.log(new Date(Date.UTC(-1, 11, 31, 23, 59, 59, 999) + 1).toISOString(), new Date(Date.UTC(0, 0, 1) - 1).toISOString(), new Date(Date.UTC(9999, 11, 31, 23, 59, 59, 999) + 1).toISOString());
''')
