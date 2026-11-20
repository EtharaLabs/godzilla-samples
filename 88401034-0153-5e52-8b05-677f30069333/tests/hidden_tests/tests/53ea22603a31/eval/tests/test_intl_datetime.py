"""ECMA-402 Intl.DateTimeFormat and Date.prototype.toLocale{,Date,Time}String: dateStyle/timeStyle,
component options, hour cycles, time zones (IANA and offset), timeZoneName styles, non-Gregorian
calendars, eras, dayPeriod, fractional seconds, formatToParts, formatRange(ToParts),
resolvedOptions and option errors.

Every instant is a fixed timestamp (Date.UTC / numeric epoch ms) so outputs never depend on the clock;
the engine embeds its own CLDR and tz tables."""
from conftest import check_script, resources_for

G = resources_for(__file__)

PRELUDE = r'''
const t = (f) => { try { return f(); } catch (e) { return e.name + ': ' + e.message; } };
const df = (l, o) => new Intl.DateTimeFormat(l, o);
const J = (x) => JSON.stringify(x);
const D = new Date(Date.UTC(2024, 2, 5, 14, 7, 9, 45));   // Tue 2024-03-05 14:07:09.045Z
'''


def check_js(run, workdir, name, body):
    return check_script(run, workdir, G, name, PRELUDE + body)


def test_date_and_time_styles_across_locales(run, workdir):
    """CATCHES: wrong dateStyle/timeStyle expansions (full adds the weekday and long zone name, long
    adds the short zone name, short uses a 2-digit year), wrong numeric field order/separators per
    locale (de d.m.y, ja y/m/d, nl d-m-y, sv y-m-d), or localized month names missing for medium/long."""
    check_js(run, workdir, "date_and_time_styles_across_locales", r'''
for (const l of ['en', 'en-GB', 'de', 'fr', 'ja', 'zh', 'zh-TW', 'ko', 'ru', 'es', 'pt-BR', 'ar', 'hi', 'it', 'nl', 'sv', 'pl', 'th', 'xx'])
  console.log(l, '|', df(l).format(D), '|', ['full', 'long', 'medium', 'short'].map(s => df(l, {dateStyle: s, timeStyle: s}).format(D)).join(' | '));
for (const s of ['full', 'long', 'medium', 'short'])
  console.log(s, '|', df('en', {dateStyle: s}).format(D), '|', df('en', {timeStyle: s}).format(D), '|', df('de', {timeStyle: s}).format(D));
''')


def test_component_options_widths(run, workdir):
    """CATCHES: weekday/month/year/day width options rendering the wrong form (long/short/narrow names,
    2-digit padding, 2-digit year), era being appended (or, when it is the only option, defaulting the
    date components), and the localized month names of de/fr/ja/ru/es (a weekday-only formatter keeps
    a trailing ', ' in the reference — pinned as observed)."""
    check_js(run, workdir, "component_options_widths", r'''
const opts = [
  {weekday: 'long'}, {weekday: 'short'}, {weekday: 'narrow'},
  {month: 'long'}, {month: 'short'}, {month: 'narrow'}, {month: 'numeric'}, {month: '2-digit'},
  {day: 'numeric'}, {day: '2-digit'}, {year: 'numeric'}, {year: '2-digit'},
  {year: 'numeric', era: 'short'}, {era: 'long'}, {era: 'narrow', year: 'numeric'},
  {year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'},
  {year: '2-digit', month: '2-digit', day: '2-digit'},
  {month: 'short', day: 'numeric'}, {year: 'numeric', month: 'short'},
];
const early = new Date(Date.UTC(2009, 0, 2, 3, 4, 5));
for (const o of opts)
  console.log(J(o), '=>', ['en', 'de', 'fr', 'ja', 'ru', 'es'].map(l => df(l, o).format(D)).join(' | '), '||', df('en', o).format(early));
''')


def test_hour_cycles_and_hour12(run, workdir):
    """CATCHES: hourCycle h11/h12/h23/h24 mapping midnight and noon incorrectly (0 PM vs 12 PM, 24 vs
    00), hour12 not overriding hourCycle, the -u-hc- extension not applying, 2-digit padding rules
    for 12- vs 24-hour clocks, and per-locale defaults (en 12-hour, de 24-hour, ja h11 for hour12)."""
    check_js(run, workdir, "hour_cycles_and_hour12", r'''
const hours = [0, 1, 11, 12, 13, 23].map(h => Date.UTC(2024, 0, 1, h, 5));
const show = (l, o) => console.log(l, J(o), '=>', hours.map(x => df(l, o).format(x)).join(' | '),
  '| hc=' + df(l, o).resolvedOptions().hourCycle + ' h12=' + df(l, o).resolvedOptions().hour12);
for (const hc of ['h11', 'h12', 'h23', 'h24']) show('en', {hour: 'numeric', hourCycle: hc});
show('en', {hour: 'numeric'});
show('en', {hour: '2-digit', minute: '2-digit'});
show('en', {hour: 'numeric', minute: '2-digit', hour12: false});
show('en', {hour: 'numeric', hour12: false, hourCycle: 'h12'});
show('en', {hour: 'numeric', hour12: true, hourCycle: 'h23'});
show('de', {hour: 'numeric'});
show('de', {hour: 'numeric', hour12: true});
show('ja', {hour: 'numeric', hour12: true});
show('en-u-hc-h23', {hour: 'numeric'});
show('en-u-hc-h11', {hour: 'numeric', hourCycle: 'h24'});
show('de-u-hc-h12', {timeStyle: 'short'});
console.log(J(df('en-u-hc-h23', {hour: 'numeric', hourCycle: 'h12'}).resolvedOptions().locale), J(df('en-u-hc-h23', {hour: 'numeric'}).resolvedOptions().locale), J(df('en-u-hc-h23', {hour: 'numeric', hour12: false}).resolvedOptions().locale));
console.log(J(df('en', {hour12: true}).resolvedOptions()));
''')


def test_time_zones_named_and_offset(run, workdir):
    """CATCHES: time-zone conversion ignoring DST (New York EDT in July vs EST in January), half-hour
    and 45-minute zones (Kolkata, Kathmandu, St Johns, Chatham), offset zones like '+05:30'/'-0330',
    date rollover across midnight, and resolvedOptions().timeZone canonicalisation of offsets/aliases."""
    check_js(run, workdir, "time_zones_named_and_offset", r'''
const summer = Date.UTC(2024, 6, 4, 16, 30), winter = Date.UTC(2024, 0, 15, 3, 5);
for (const tz of ['UTC', 'America/New_York', 'America/Los_Angeles', 'Europe/London', 'Europe/Berlin', 'Asia/Kolkata', 'Asia/Tokyo',
                  'Australia/Sydney', 'Asia/Kathmandu', 'America/St_Johns', 'Pacific/Chatham', 'Asia/Calcutta', 'US/Eastern',
                  'Etc/GMT+5', '+05:30', '-0330', '+00:00', '-23:59', '+05', 'america/new_york', 'etc/utc', 'GMT'])
  console.log(tz, '|', df('en', {dateStyle: 'medium', timeStyle: 'medium', timeZone: tz}).format(summer), '|',
    df('en', {dateStyle: 'medium', timeStyle: 'medium', timeZone: tz}).format(winter), '|', df('en', {timeZone: tz}).resolvedOptions().timeZone);
console.log(df('en', {timeZone: 'Pacific/Kiritimati', dateStyle: 'medium'}).format(D), '|', df('en', {timeZone: 'Pacific/Pago_Pago', dateStyle: 'medium'}).format(D));
console.log(df('en').resolvedOptions().timeZone, df('en', {timeZone: '-00:00'}).resolvedOptions().timeZone);
for (const bad of ['Mars/Olympus', '+25:00', '+05:60', 'UTC+1', '+5:30', '05:30', '', '+0530x', '+05:3x', '+0', '-1'])
  console.log(J(bad), t(() => df('en', {timeZone: bad}).resolvedOptions().timeZone));
''')


def test_time_zone_name_styles(run, workdir):
    """CATCHES: timeZoneName short/long/shortOffset/longOffset/shortGeneric/longGeneric rendering the
    wrong text for UTC ('UTC' vs 'Coordinated Universal Time' vs 'GMT'), GMT-offset formatting for
    offset zones (minutes only when non-zero), and the metazone long names for well-known zones (the
    reference derives short GMT offsets from the zone's offset at the epoch, so New York in July still
    shows GMT-5, and long names of some zones fall back to an alias such as Europe/Guernsey)."""
    check_js(run, workdir, "time_zone_name_styles", r'''
const x = Date.UTC(2024, 0, 15, 12, 0);
for (const tzn of ['short', 'long', 'shortOffset', 'longOffset', 'shortGeneric', 'longGeneric'])
  console.log(tzn, '|', ['UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'Asia/Kolkata', 'Asia/Shanghai', 'Asia/Tokyo',
    'Europe/Paris', 'Europe/London', '+05:30', '-08:00', '+00:00', 'Asia/Dubai'].map(tz =>
      df('en', {hour: 'numeric', minute: 'numeric', timeZone: tz, timeZoneName: tzn}).format(x)).join(' | '));
const july = Date.UTC(2024, 6, 15, 12, 0);
console.log('july', ['America/New_York', 'Europe/London', 'Australia/Sydney', 'Asia/Kathmandu'].map(tz =>
  df('en', {hour: 'numeric', minute: 'numeric', timeZone: tz, timeZoneName: 'short'}).format(july) + ' / ' +
  df('en', {hour: 'numeric', timeZone: tz, timeZoneName: 'long'}).format(july)).join(' | '));
console.log(df('en', {timeZoneName: 'short'}).format(x), '|', df('en', {timeZoneName: 'long', timeZone: 'Asia/Tokyo'}).format(x), '|', df('de', {timeZoneName: 'short', timeZone: 'Europe/Berlin'}).format(x));
console.log(J(df('en', {timeZoneName: 'shortOffset', timeZone: 'Asia/Kolkata', hour: 'numeric'}).formatToParts(x)));
console.log(t(() => df('en', {timeZoneName: 'medium'})));
''')


def test_calendars(run, workdir):
    """CATCHES: wrong calendar arithmetic or month names for buddhist, japanese, islamic(-umalqura,
    -civil, -tbla), hebrew (leap Adar I), chinese/dangi (related year + sexagenary name), persian,
    indian, coptic, ethiopic(aa) and roc; the calendar option vs -u-ca- precedence; and unsupported
    calendars falling back to gregory (islamic -> islamic-civil). The reference names Adar II of a leap
    year plain 'Adar' — pinned as observed."""
    check_js(run, workdir, "calendars", r'''
for (const ca of ['gregory', 'japanese', 'buddhist', 'islamic-umalqura', 'islamic-civil', 'islamic', 'islamic-rgsa', 'islamic-tbla', 'hebrew',
                  'chinese', 'dangi', 'persian', 'indian', 'coptic', 'ethiopic', 'ethioaa', 'roc', 'iso8601', 'bogus'])
  console.log(ca, '|', df('en', {calendar: ca}).format(D), '|', df('en-u-ca-' + ca, {year: 'numeric', month: 'long', day: 'numeric', era: 'short'}).format(D), '|',
    df('en', {calendar: ca, dateStyle: 'full'}).format(D), '|', df('ja', {calendar: ca, year: 'numeric', month: 'long', day: 'numeric'}).format(D), '|',
    df('en-u-ca-' + ca).resolvedOptions().calendar, df('en-u-ca-' + ca).resolvedOptions().locale);
console.log(df('en', {calendar: 'hebrew', month: 'long', day: 'numeric', year: 'numeric'}).format(Date.UTC(2024, 2, 20)), '|',
  df('en', {calendar: 'hebrew', month: 'numeric', day: 'numeric'}).format(Date.UTC(2023, 8, 16)));
console.log(J(df('zh', {calendar: 'chinese', dateStyle: 'long'}).formatToParts(D)));
console.log(df('en', {calendar: 'chinese', year: 'numeric', month: 'numeric', day: 'numeric'}).format(Date.UTC(2023, 3, 25)));
console.log(df('en-u-ca-buddhist', {calendar: 'japanese'}).resolvedOptions().locale, df('en-u-ca-buddhist', {calendar: 'buddhist'}).resolvedOptions().locale,
  df('en-u-ca-islamicc').resolvedOptions().calendar, df('en', {calendar: 'ethiopic-amete-alem'}).resolvedOptions().calendar, df('en', {calendar: 'GREGORY'}).resolvedOptions().calendar);
console.log(t(() => df('en', {calendar: 'a'})), '|', t(() => df('en', {calendar: 'gregory!'})));
''')


def test_eras_japanese_and_bce(run, workdir):
    """CATCHES: Japanese era boundaries (Showa -> Heisei on 1989-01-08, Heisei -> Reiwa on 2019-05-01),
    BCE years shown as positive era years only when an era is displayed (year 0 = 1 BC), and the
    long/short/narrow Gregorian era names."""
    check_js(run, workdir, "eras_japanese_and_bce", r'''
const jp = (l, w, x) => df(l, {calendar: 'japanese', era: w, year: 'numeric', month: 'short', day: 'numeric'}).format(x);
for (const x of [Date.UTC(1989, 0, 7), Date.UTC(1989, 0, 8), Date.UTC(2019, 3, 30), Date.UTC(2019, 4, 1), Date.UTC(1950, 0, 7), Date.UTC(1926, 11, 25),
                 Date.UTC(1912, 6, 30), Date.UTC(1880, 0, 1), Date.UTC(1850, 0, 1)])
  console.log(new Date(x).toISOString().slice(0, 10), '|', jp('en', 'long', x), '|', jp('en', 'short', x), '|', jp('ja', 'long', x));
const years = [-500, -43, 0, 1, 2024];
for (const y of years) {
  const d = new Date(0); d.setUTCFullYear(y, 2, 15);
  console.log(y, '|', ['long', 'short', 'narrow'].map(w => df('en', {era: w, year: 'numeric', month: 'short', day: 'numeric'}).format(d)).join(' | '), '|', df('en', {year: 'numeric'}).format(d), '|', df('de', {era: 'long', year: 'numeric'}).format(d));
}
console.log(df('en', {calendar: 'roc', era: 'long', year: 'numeric'}).format(Date.UTC(1900, 0, 1)), '|', df('en', {calendar: 'buddhist', era: 'short', year: 'numeric'}).format(D));
''')


def test_day_period_and_fractional_seconds(run, workdir):
    """CATCHES: dayPeriod narrow/short/long selecting the wrong flexible period (noon, morning,
    afternoon, evening, night) or not replacing AM/PM, fractionalSecondDigits 1-3 truncating (not
    rounding) milliseconds with a '.' separator (U+066B for arab digits), and range validation."""
    check_js(run, workdir, "day_period_and_fractional_seconds", r'''
for (const h of [0, 5, 6, 11, 12, 13, 17, 18, 20, 21, 23])
  console.log(h, '|', ['narrow', 'short', 'long'].map(w => df('en', {hour: 'numeric', dayPeriod: w}).format(Date.UTC(2024, 0, 1, h, 30))).join(' | '), '|', df('en', {dayPeriod: 'long'}).format(Date.UTC(2024, 0, 1, h)));
const ms = Date.UTC(2024, 0, 1, 9, 8, 7, 987);
for (const f of [1, 2, 3, 2.9, '3'])
  console.log('fsd', J(f), '|', df('en', {hour: 'numeric', minute: 'numeric', second: 'numeric', fractionalSecondDigits: f}).format(ms), '|',
    df('en', {second: 'numeric', fractionalSecondDigits: f}).format(ms), '|', df('en', {fractionalSecondDigits: f}).format(ms), '|',
    df('ar', {minute: 'numeric', second: 'numeric', fractionalSecondDigits: f}).format(ms));
for (const bad of [0, 4, NaN, -1]) console.log('bad', bad, t(() => df('en', {fractionalSecondDigits: bad})));
console.log(J(df('en', {hour: 'numeric', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 2, dayPeriod: 'short'}).formatToParts(ms)));
console.log(J(df('en', {dayPeriod: 'narrow', hour: 'numeric'}).resolvedOptions()));
''')


def test_format_to_parts_types(run, workdir):
    """CATCHES: formatToParts producing the wrong part types or literals (weekday, month, day, year,
    hour, minute, second, dayPeriod, timeZoneName, fractionalSecond, era, literal), digits not
    localized per numbering system in each part, or parts not concatenating to format()."""
    check_js(run, workdir, "format_to_parts_types", r'''
const cases = [
  ['en', {dateStyle: 'full', timeStyle: 'long'}],
  ['de', {hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 2, timeZone: 'Asia/Kolkata'}],
  ['ar', {day: 'numeric', month: 'numeric', year: 'numeric'}],
  ['en', {era: 'short', year: 'numeric', month: 'long'}],
  ['ja-u-nu-hanidec', {year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric'}],
  ['en', {weekday: 'short', hour: 'numeric', timeZone: 'America/New_York', timeZoneName: 'short'}],
  ['en-u-nu-deva', {}],
];
for (const [l, o] of cases) {
  const f = df(l, o);
  const parts = f.formatToParts(D);
  console.log(l, J(o));
  console.log('  ', parts.map(p => p.type + '=' + J(p.value)).join(' '), parts.map(p => p.value).join('') === f.format(D));
}
console.log(J(df('en').formatToParts(0)), t(() => df('en').formatToParts(NaN)), t(() => df('en').formatToParts(8.64e15 + 1)));
''')


def test_format_range_and_range_to_parts(run, workdir):
    """CATCHES: formatRange not collapsing shared fields (same month/year printed once), not using the
    thin-space en-dash separator, not collapsing practically-equal endpoints into one date, mis-tagging
    sources in formatRangeToParts, or accepting missing/NaN endpoints instead of throwing."""
    check_js(run, workdir, "format_range_and_range_to_parts", r'''
const a = Date.UTC(2024, 0, 10, 9, 0), b = Date.UTC(2024, 0, 20, 17, 30), c = Date.UTC(2024, 5, 1), e = Date.UTC(2025, 1, 1);
const o1 = {year: 'numeric', month: 'short', day: 'numeric'};
console.log(df('en', o1).formatRange(a, b), '|', df('en', o1).formatRange(a, c), '|', df('en', o1).formatRange(a, e), '|', df('en', o1).formatRange(a, a + 1000));
const o2 = {hour: 'numeric', minute: 'numeric'};
console.log(df('en', o2).formatRange(a, a + 3600e3), '|', df('en', o2).formatRange(a, a + 12 * 3600e3), '|', df('en').formatRange(a, b), '|', df('en', {dateStyle: 'medium', timeStyle: 'short'}).formatRange(a, b));
console.log(df('de', o1).formatRange(a, b), '|', df('ja', {dateStyle: 'long'}).formatRange(a, c), '|', df('en', {month: 'long'}).formatRange(a, c), '|', df('en', {weekday: 'long', day: 'numeric'}).formatRange(a, b));
console.log(df('en', o1).formatRange(new Date(a), new Date(b)), '|', df('en', o1).formatRange(b, a));
console.log(J(df('en', o1).formatRangeToParts(a, b)));
console.log(J(df('en', o2).formatRangeToParts(a, a + 60e3)));
console.log(J(df('en', o1).formatRangeToParts(a, a)));
console.log(t(() => df('en').formatRange(a)), '|', t(() => df('en').formatRange(NaN, a)), '|', t(() => df('en').formatRangeToParts(a, Infinity)), '|', t(() => df('en').formatRange(undefined, a)));
''')


def test_resolved_options(run, workdir):
    """CATCHES: resolvedOptions with wrong property order or presence (hourCycle/hour12 only when an
    hour is shown, defaulted year/month/day components, dateStyle/timeStyle instead of components),
    and the resolved locale not reflecting surviving -u-ca/-hc/-nu keywords in canonical order."""
    check_js(run, workdir, "resolved_options", r'''
console.log(J(df('en').resolvedOptions()));
console.log(J(df('en-u-hc-h23', {hour: 'numeric', timeZone: 'asia/kolkata'}).resolvedOptions()));
console.log(J(df('ja-JP-u-ca-japanese-nu-hanidec', {dateStyle: 'short', timeStyle: 'full', timeZone: '+0530'}).resolvedOptions()));
console.log(J(df('en', {weekday: 'short', era: 'narrow', year: '2-digit', month: '2-digit', day: '2-digit', hour: 'numeric', hour12: true, minute: '2-digit',
  second: '2-digit', fractionalSecondDigits: 3, timeZoneName: 'shortOffset', timeZone: 'America/New_York', dayPeriod: 'short'}).resolvedOptions()));
console.log(J(df('de-AT-u-nu-arab-hc-h11-ca-buddhist', {month: 'long'}).resolvedOptions()));
console.log(J(df('xx', {era: 'long'}).resolvedOptions()));
console.log(J(df(['zz', 'fr-CA'], {calendar: 'islamic', numberingSystem: 'thai'}).resolvedOptions()));
console.log(J(Object.keys(df('en', {timeStyle: 'short'}).resolvedOptions())));
''')


def test_option_errors_and_coercion(run, workdir):
    """CATCHES: missing TypeError when dateStyle/timeStyle is combined with components, RangeErrors for
    invalid option values (with their exact messages), invalid time values (NaN, beyond +-8.64e15),
    bad receivers, string/Date/number coercion of the formatted value, and Symbol inputs."""
    check_js(run, workdir, "option_errors_and_coercion", r'''
const bad = [{dateStyle: 'full', hour: 'numeric'}, {timeStyle: 'short', timeZoneName: 'short'}, {hourCycle: 'h13'}, {dateStyle: 'tiny'}, {month: 'full'},
  {weekday: 'numeric'}, {year: 'long'}, {hour: 'long'}, {formatMatcher: 'exact'}, {localeMatcher: 'best'}, {numberingSystem: 'a'}, {era: 'wide'}];
for (const o of bad) console.log(J(o), '=>', t(() => df('en', o).format(D)));
console.log(t(() => df('en').format(NaN)), '|', t(() => df('en').format(8.64e15 + 1)), '|', df('en').format(8.64e15), '|', df('en').format(-8.64e15));
console.log(t(() => df('en').format(Symbol())), '|', t(() => df('en').format('2024-01-01')), '|', df('en').format(new Date('2024-03-05T23:30:00Z')), '|', df('en').format(86400000 * 365.25 * 30), '|', df('en').format(true), '|', df('en').format(null));
console.log(t(() => Intl.DateTimeFormat.prototype.format), '|', t(() => Intl.DateTimeFormat.prototype.formatToParts.call({}, 0)), '|', t(() => new Intl.DateTimeFormat('en', null)), '|', t(() => new Intl.DateTimeFormat('en-')));
const f = df('en').format;
console.log([Date.UTC(2024, 0, 10), Date.UTC(2024, 11, 25)].map(f).join(';'), typeof f, f.length, J(f.name), df('en').format === df('en').format);
const g = df('fr'); console.log(g.format === g.format, Intl.DateTimeFormat('en') instanceof Intl.DateTimeFormat, Object.prototype.toString.call(g), Intl.DateTimeFormat.length);
''')


def test_date_to_locale_string_methods(run, workdir):
    """CATCHES: Date.prototype.toLocaleString/DateString/TimeString not delegating to DateTimeFormat
    with the right required/defaults (date-only methods default to y/m/d, time-only to h:m:s, explicit
    components replace defaults), ignoring the timeZone option, Invalid Date handling, and bad tags
    (the reference does not throw for toLocaleTimeString with dateStyle — pinned as observed)."""
    check_js(run, workdir, "date_to_locale_string_methods", r'''
const d = new Date(Date.UTC(2024, 11, 31, 23, 59, 58, 999));
console.log(d.toLocaleString(), '|', d.toLocaleDateString(), '|', d.toLocaleTimeString());
console.log(d.toLocaleString('de-DE'), '|', d.toLocaleDateString('ja-JP'), '|', d.toLocaleTimeString('fr'), '|', d.toLocaleString(['xx', 'es']));
console.log(d.toLocaleString('en-US', {timeZone: 'America/New_York'}), '|', d.toLocaleDateString('en-US', {timeZone: 'Asia/Tokyo', weekday: 'long'}), '|', d.toLocaleTimeString('en-US', {timeZone: 'Asia/Kolkata', timeZoneName: 'short'}));
console.log(d.toLocaleTimeString('en-US', {hour: '2-digit'}), '|', d.toLocaleDateString('en-US', {hour: '2-digit'}), '|', d.toLocaleTimeString('en-US', {year: 'numeric'}), '|', d.toLocaleString('en', {month: 'long'}));
console.log(d.toLocaleDateString(undefined, {dateStyle: 'medium'}), '|', t(() => d.toLocaleTimeString('en', {dateStyle: 'medium'})), '|', t(() => d.toLocaleDateString('en', {timeStyle: 'medium'})), '|', d.toLocaleString('en', {timeStyle: 'short'}));
console.log(d.toLocaleString('en', {hour12: false}), '|', d.toLocaleTimeString('en', {hourCycle: 'h11'}), '|', d.toLocaleDateString('ar'), '|', d.toLocaleDateString('en', {calendar: 'buddhist', era: 'short'}));
console.log(new Date(NaN).toLocaleString(), '|', new Date(NaN).toLocaleDateString('de'), '|', new Date(NaN).toLocaleTimeString(), '|', t(() => d.toLocaleString('x_y')), '|', t(() => d.toLocaleString('en', {timeZone: 'Nowhere/City'})));
console.log(t(() => Date.prototype.toLocaleString.call({})), '|', new Date(Date.UTC(1969, 6, 20, 20, 17)).toLocaleString('en-GB', {timeZone: 'UTC'}));
''')


def test_temporal_values_through_date_time_format(run, workdir):
    """CATCHES: DateTimeFormat.format not adapting to Temporal receivers (PlainDate drops time fields,
    PlainTime drops date fields, PlainDateTime/Instant show both), the 'no overlap' TypeError,
    ZonedDateTime being rejected by format but accepted by its own toLocaleString, and calendar
    mismatch errors for PlainYearMonth/PlainMonthDay under a gregory formatter."""
    check_js(run, workdir, "temporal_values_through_date_time_format", r'''
const T = Temporal;
const vals = {pd: T.PlainDate.from('2024-03-05'), pt: T.PlainTime.from('13:45:30.123'), pdt: T.PlainDateTime.from('2024-03-05T13:45:30'),
  pym: T.PlainYearMonth.from('2024-03'), pmd: T.PlainMonthDay.from('03-05'), ins: T.Instant.from('2024-03-05T13:45:30Z'),
  zdt: T.ZonedDateTime.from('2024-03-05T13:45:30[UTC]')};
for (const [k, v] of Object.entries(vals))
  console.log(k, '|', t(() => df('en').format(v)), '|', t(() => df('en-u-ca-iso8601').format(v)), '|', t(() => df('en', {calendar: 'iso8601', hour: 'numeric'}).format(v)), '|',
    t(() => df('en', {calendar: 'iso8601', dateStyle: 'long'}).format(v)), '|', t(() => v.toLocaleString('en')), '|', t(() => v.toLocaleString('de', {timeZone: 'Asia/Tokyo'})));
console.log(df('en').formatRange(vals.pd, T.PlainDate.from('2024-03-09')), '|', t(() => df('en').formatRange(vals.pd, Date.UTC(2024, 1, 1))), '|', t(() => df('en').formatRange(vals.pd, vals.pdt)));
console.log(J(df('en').formatToParts(vals.pt)));
const iso = df('en-u-ca-iso8601');
console.log(t(() => df('en').formatRange(T.PlainDate.from('2024-03-05[u-ca=japanese]'), T.PlainDate.from('2024-03-09'))), '|',
  df('en').formatRange(T.PlainTime.from('10:00'), T.PlainTime.from('12:30')), '|',
  df('en').formatRange(T.PlainDateTime.from('2024-03-05T10:00'), T.PlainDateTime.from('2024-03-05T12:30')), '|',
  df('en').formatRange(T.Instant.from('2024-03-05T10:00Z'), T.Instant.from('2024-03-06T12:30Z')));
console.log(iso.formatRange(vals.pym, T.PlainYearMonth.from('2024-05')), '|', iso.formatRange(vals.pmd, T.PlainMonthDay.from('03-09')), '|',
  t(() => df('en').formatRange(vals.zdt, vals.zdt)), '|', df('en', {timeZoneName: 'short'}).format(vals.pdt));
''')
