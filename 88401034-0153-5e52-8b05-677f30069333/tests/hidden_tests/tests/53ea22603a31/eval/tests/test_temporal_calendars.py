"""Temporal non-ISO calendars: gregory, japanese, buddhist, roc, islamic-*, hebrew, chinese/dangi,
persian, indian, ethiopic/ethioaa/coptic.

Covers field projection (year/month/monthCode/day/era/eraYear/daysIn*/inLeapYear), leap months
(Hebrew M05L, Chinese/Dangi Mxx L), construction from calendar property bags (era/eraYear,
monthCode, overflow), calendar-aware add/until, PlainYearMonth/PlainMonthDay reference dates,
withCalendar, calendar identifiers/annotations, and calendar-aware toLocaleString.
"""
from conftest import check_script, resources_for

G = resources_for(__file__)

# Shared JS helpers: `t(label, fn)` prints the value (or the thrown error's name and message);
# `f(d)` prints a date's calendar fields.
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
const P = Temporal.PlainDate;
const f = (d) => [d.year, d.month, d.monthCode, d.day, String(d.era), String(d.eraYear), d.daysInMonth,
  d.daysInYear, d.monthsInYear, d.inLeapYear, d.dayOfYear].join(' ');
const iso = (d) => d.withCalendar('iso8601').toString();
'''


def check(run, workdir, name, body, **kw):
    """Run PRE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRE + body, **kw)


def test_calendar_identifiers(run, workdir):
    """CATCHES: calendar-id handling bugs: case-insensitive canonicalization, aliases (islamicc, ethiopic-amete-alem), rejection of Intl-only ids (islamic, islamic-rgsa) and junk, ids taken from ISO strings and Temporal objects, and the u-ca annotation in toString."""
    check(run, workdir, "calendar_identifiers", r'''
const d = P.from('2024-03-11');
for (const c of ['iso8601', 'ISO8601', 'gregory', 'japanese', 'buddhist', 'roc', 'islamic-umalqura', 'islamic-civil',
  'islamic-tbla', 'islamicc', 'hebrew', 'chinese', 'dangi', 'persian', 'indian', 'ethiopic', 'ethioaa',
  'ethiopic-amete-alem', 'coptic', 'Hebrew', 'islamic', 'islamic-rgsa', 'gregorian', 'iso-8601', ''])
  t(JSON.stringify(c), () => d.withCalendar(c).calendarId);
t('from string calendar', () => d.withCalendar('2024-01-01[u-ca=coptic]').calendarId);
t('from string without annotation', () => d.withCalendar('2024-01-01').calendarId);
t('from Temporal object', () => d.withCalendar(Temporal.PlainDateTime.from('2024-01-01T00:00[u-ca=persian]')).calendarId);
t('from ZonedDateTime', () => d.withCalendar(Temporal.ZonedDateTime.from('2024-01-01T00:00[UTC][u-ca=indian]')).calendarId);
t('annotation case', () => P.from('2024-03-11[u-ca=HEBREW]').calendarId);
t('annotation bogus', () => P.from('2024-03-11[u-ca=bogus]'));
t('annotation islamic', () => P.from('2024-03-11[u-ca=islamic]'));
t('toString hebrew', () => d.withCalendar('hebrew').toString());
t('toJSON chinese', () => d.withCalendar('chinese').toJSON());
t('PlainDateTime with calendar', () => Temporal.PlainDateTime.from('2024-03-11T10:00').withCalendar('roc').toString());
t('equals across calendars', () => d.equals(d.withCalendar('gregory')) + ' ' + P.compare(d, d.withCalendar('gregory')));
''')


def test_calendar_field_projection(run, workdir):
    """CATCHES: wrong calendar conversions: each calendar's year/month/monthCode/day/era/eraYear/daysInMonth/daysInYear/monthsInYear/inLeapYear/dayOfYear for the same ISO date, including epagomenal months and lunar month lengths."""
    check(run, workdir, "calendar_field_projection", r'''
const cals = ['iso8601', 'gregory', 'japanese', 'buddhist', 'roc', 'islamic-umalqura', 'islamic-civil', 'islamic-tbla',
  'hebrew', 'chinese', 'dangi', 'persian', 'indian', 'ethiopic', 'ethioaa', 'coptic'];
for (const s of ['2024-03-11', '2023-09-12']) {
  for (const c of cals) t(s + ' ' + c, () => f(P.from(s).withCalendar(c)));
}
''')


def test_calendar_eras_gregorian_family(run, workdir):
    """CATCHES: era bugs in gregory/japanese/buddhist/roc: BCE/before-ROC years, Japanese era boundaries (Heisei->Reiwa on 2019-05-01, Showa->Heisei on 1989-01-08, pre-Meiji fallback to ce), and era/eraYear property bags with aliases and mismatches."""
    check(run, workdir, "calendar_eras_gregorian_family", r'''
for (const [s, c] of [['0000-06-01', 'gregory'], ['-000100-06-01', 'gregory'], ['2019-04-30', 'japanese'], ['2019-05-01', 'japanese'],
  ['1989-01-07', 'japanese'], ['1989-01-08', 'japanese'], ['1926-12-25', 'japanese'], ['1912-07-30', 'japanese'],
  ['1873-01-01', 'japanese'], ['1872-12-31', 'japanese'], ['1911-06-01', 'roc'], ['1912-01-01', 'roc'], ['0001-01-01', 'buddhist']])
  t(s + ' ' + c, () => { const d = P.from(s).withCalendar(c); return [d.year, d.era, d.eraYear].join(' '); });
t('gregory bce bag', () => P.from({ era: 'bce', eraYear: 1, month: 1, day: 1, calendar: 'gregory' }).toString());
t('gregory bc alias', () => P.from({ era: 'bc', eraYear: 10, month: 1, day: 1, calendar: 'gregory' }).toString());
t('gregory ad alias', () => P.from({ era: 'ad', eraYear: 2000, month: 1, day: 1, calendar: 'gregory' }).toString());
t('gregory era + matching year', () => P.from({ era: 'ce', eraYear: 2000, year: 2000, month: 1, day: 1, calendar: 'gregory' }).toString());
t('gregory era + mismatching year', () => P.from({ era: 'ce', eraYear: 2000, year: 1999, month: 1, day: 1, calendar: 'gregory' }));
t('gregory era without eraYear', () => P.from({ era: 'ce', month: 1, day: 1, calendar: 'gregory' }));
t('gregory eraYear without era', () => P.from({ eraYear: 5, month: 1, day: 1, calendar: 'gregory' }));
t('gregory unknown era', () => P.from({ era: 'xyz', eraYear: 5, month: 1, day: 1, calendar: 'gregory' }));
t('japanese heisei 31', () => P.from({ era: 'heisei', eraYear: 31, month: 4, day: 30, calendar: 'japanese' }).toString());
t('japanese reiwa 1', () => P.from({ era: 'reiwa', eraYear: 1, month: 5, day: 1, calendar: 'japanese' }).toString());
t('japanese showa 64', () => P.from({ era: 'showa', eraYear: 64, month: 1, day: 7, calendar: 'japanese' }).toString());
t('japanese meiji', () => P.from({ era: 'meiji', eraYear: 6, month: 1, day: 1, calendar: 'japanese' }).toString());
t('japanese year only', () => P.from({ year: 2020, month: 1, day: 1, calendar: 'japanese' }).eraYear);
t('buddhist be', () => P.from({ era: 'be', eraYear: 2567, month: 1, day: 1, calendar: 'buddhist' }).toString());
t('buddhist year', () => P.from({ year: 2567, month: 1, day: 1, calendar: 'buddhist' }).toString());
t('roc broc', () => P.from({ era: 'broc', eraYear: 1, month: 1, day: 1, calendar: 'roc' }).toString());
t('roc minguo', () => P.from({ era: 'minguo', eraYear: 113, month: 1, day: 1, calendar: 'roc' }).toString());
t('roc year', () => P.from({ year: 113, month: 1, day: 1, calendar: 'roc' }).toString());
t('iso8601 ignores era fields', () => P.from({ era: 'ce', eraYear: 1, year: 2024, month: 1, day: 1 }).toString());
t('with era', () => P.from('2024-05-05').withCalendar('japanese').with({ era: 'heisei', eraYear: 1 }).toString());
t('with eraYear only', () => P.from('2024-05-05').withCalendar('japanese').with({ eraYear: 1 }).toString());
t('with era and year', () => P.from('2024-05-05').withCalendar('gregory').with({ era: 'ce', eraYear: 1, year: 1 }));
''')


def test_calendar_islamic_variants(run, workdir):
    """CATCHES: Islamic calendar bugs: tabular civil vs astronomical (tbla) epochs, Umm al-Qura table lookups (month lengths 29/30, out-of-table fallback), leap years (355 days), Ramadan month code M09, BH era, and bag construction with overflow."""
    check(run, workdir, "calendar_islamic_variants", r'''
for (const c of ['islamic-umalqura', 'islamic-civil', 'islamic-tbla']) {
  t(c + ' 1445-09-01', () => iso(P.from({ year: 1445, month: 9, day: 1, calendar: c })));
  t(c + ' 1446-12-30 constrain', () => iso(P.from({ year: 1446, monthCode: 'M12', day: 30, calendar: c })));
  t(c + ' 1446-12-30 reject', () => iso(P.from({ year: 1446, monthCode: 'M12', day: 30, calendar: c }, { overflow: 'reject' })));
  t(c + ' month lengths 1446', () => Array.from({ length: 12 }, (_, i) => P.from({ year: 1446, month: i + 1, day: 1, calendar: c }).daysInMonth).join(''));
  t(c + ' year lengths', () => [1440, 1441, 1442, 1443, 1444, 1445].map((y) => P.from({ year: y, month: 1, day: 1, calendar: c }).daysInYear).join(','));
  t(c + ' 0622-07-19', () => f(P.from('0622-07-19').withCalendar(c)));
  t(c + ' 0500-01-01 (BH)', () => f(P.from('0500-01-01').withCalendar(c)));
  t(c + ' 2200-01-01', () => f(P.from('2200-01-01').withCalendar(c)));
}
t('umalqura era bh bag', () => iso(P.from({ era: 'bh', eraYear: 1, month: 1, day: 1, calendar: 'islamic-umalqura' })));
t('umalqura month 13', () => P.from({ year: 1445, month: 13, day: 1, calendar: 'islamic-umalqura' }, { overflow: 'reject' }));
t('umalqura M13 code', () => P.from({ year: 1445, monthCode: 'M13', day: 1, calendar: 'islamic-umalqura' }));
t('umalqura add 1 month from 30th', () => P.from({ year: 1445, month: 8, day: 29, calendar: 'islamic-umalqura' }).add({ months: 1 }).toString());
t('civil until years', () => P.from({ year: 1440, month: 1, day: 1, calendar: 'islamic-civil' }).until(P.from({ year: 1445, month: 6, day: 15, calendar: 'islamic-civil' }), { largestUnit: 'years' }));
''')


def test_calendar_hebrew_leap_months(run, workdir):
    """CATCHES: Hebrew calendar bugs: 13-month leap years with Adar I as M05L (ordinal 6) and Adar II keeping M06, month/monthCode mapping across leap and common years, constraining M05L in common years (or rejecting), year lengths 353-385, and add/until preserving monthCode."""
    check(run, workdir, "calendar_hebrew_leap_months", r'''
const H = (y, fields, opts) => P.from({ year: y, calendar: 'hebrew', ...fields }, opts);
t('5784 codes', () => Array.from({ length: 13 }, (_, i) => H(5784, { month: i + 1, day: 1 }).monthCode).join(','));
t('5783 codes', () => Array.from({ length: 12 }, (_, i) => H(5783, { month: i + 1, day: 1 }).monthCode).join(','));
t('5784 month lengths', () => Array.from({ length: 13 }, (_, i) => H(5784, { month: i + 1, day: 1 }).daysInMonth).join(','));
t('year lengths', () => [5779, 5780, 5781, 5782, 5783, 5784, 5785, 5786].map((y) => H(y, { month: 1, day: 1 }).daysInYear + (H(y, { month: 1, day: 1 }).inLeapYear ? 'L' : '')).join(','));
t('M05L in 5784', () => iso(H(5784, { monthCode: 'M05L', day: 15 })));
t('M05L in 5783 constrain', () => { const d = H(5783, { monthCode: 'M05L', day: 15 }); return iso(d) + ' ' + d.monthCode; });
t('M05L in 5783 reject', () => H(5783, { monthCode: 'M05L', day: 15 }, { overflow: 'reject' }));
t('M06 in 5784', () => { const d = H(5784, { monthCode: 'M06', day: 1 }); return iso(d) + ' month=' + d.month; });
t('month 13 in 5783 constrain', () => H(5783, { month: 13, day: 1 }).monthCode);
t('month 13 in 5783 reject', () => H(5783, { month: 13, day: 1 }, { overflow: 'reject' }));
t('month 6 vs M06 disagree in leap year', () => H(5784, { month: 6, monthCode: 'M06', day: 1 }));
t('Cheshvan 30 in short year', () => H(5784, { monthCode: 'M02', day: 30 }, { overflow: 'reject' }));
t('rosh hashanah 5785', () => iso(H(5785, { month: 1, day: 1 })));
t('from iso', () => f(P.from('2024-04-23').withCalendar('hebrew')));
t('add 1 year from M05L', () => { const d = H(5784, { monthCode: 'M05L', day: 10 }).add({ years: 1 }); return d.monthCode + ' ' + iso(d); });
t('add 1 year from M05L reject', () => H(5784, { monthCode: 'M05L', day: 10 }).add({ years: 1 }, { overflow: 'reject' }));
t('add 1 month from M05', () => H(5784, { monthCode: 'M05', day: 10 }).add({ months: 1 }).monthCode);
t('add 13 months', () => { const d = H(5784, { month: 1, day: 1 }).add({ months: 13 }); return d.year + ' ' + d.monthCode; });
t('subtract months across leap', () => { const d = H(5785, { month: 2, day: 1 }).subtract({ months: 14 }); return d.year + ' ' + d.month + ' ' + d.monthCode; });
t('until months across leap', () => H(5784, { month: 1, day: 1 }).until(H(5785, { month: 1, day: 1 }), { largestUnit: 'months' }));
t('until years', () => H(5780, { monthCode: 'M05', day: 1 }).until(H(5784, { monthCode: 'M05L', day: 1 }), { largestUnit: 'years' }));
t('with monthCode M05L', () => H(5784, { month: 1, day: 1 }).with({ monthCode: 'M05L' }).month);
t('with month 6', () => H(5784, { month: 1, day: 1 }).with({ month: 6 }).monthCode);
t('era am', () => iso(P.from({ era: 'am', eraYear: 5784, month: 1, day: 1, calendar: 'hebrew' })));
''')


def test_calendar_chinese_dangi(run, workdir):
    """CATCHES: Chinese/Dangi lunisolar bugs: new-year dates, leap months (2023 M02L in chinese, 2020 M04L), month counts 12/13, month lengths from astronomical new moons, Dangi (Seoul meridian) differing from Chinese, leap monthCode constraining and arithmetic."""
    check(run, workdir, "calendar_chinese_dangi", r'''
const C = (cal, y, fields, opts) => P.from({ year: y, calendar: cal, ...fields }, opts);
for (const cal of ['chinese', 'dangi']) {
  for (const y of [2020, 2023, 2024, 2025]) {
    t(cal + ' ' + y + ' new year', () => iso(C(cal, y, { month: 1, day: 1 })));
    t(cal + ' ' + y + ' months', () => { const n = C(cal, y, { month: 1, day: 1 }).monthsInYear; return n + ' ' + Array.from({ length: n }, (_, i) => C(cal, y, { month: i + 1, day: 1 }).monthCode + ':' + C(cal, y, { month: i + 1, day: 1 }).daysInMonth).join(','); });
  }
}
t('chinese 2023 M02L', () => iso(C('chinese', 2023, { monthCode: 'M02L', day: 1 })));
t('chinese 2024 M02L constrain', () => { const d = C('chinese', 2024, { monthCode: 'M02L', day: 1 }); return d.monthCode + ' ' + iso(d); });
t('chinese 2024 M02L reject', () => C('chinese', 2024, { monthCode: 'M02L', day: 1 }, { overflow: 'reject' }));
t('chinese day 30 constrain', () => { const d = C('chinese', 2024, { monthCode: 'M01', day: 30 }); return d.day + ' ' + d.daysInMonth; });
t('chinese from iso', () => f(P.from('2023-04-01').withCalendar('chinese')));
t('chinese add 1 year from leap', () => { const d = C('chinese', 2023, { monthCode: 'M02L', day: 5 }).add({ years: 1 }); return d.monthCode + ' ' + iso(d); });
t('chinese add 12 months', () => { const d = C('chinese', 2023, { month: 1, day: 1 }).add({ months: 12 }); return d.year + ' ' + d.monthCode; });
t('chinese until months', () => C('chinese', 2023, { month: 1, day: 1 }).until(C('chinese', 2024, { month: 1, day: 1 }), { largestUnit: 'months' }));
t('chinese until years', () => C('chinese', 2020, { month: 5, day: 1 }).until(C('chinese', 2024, { month: 3, day: 15 }), { largestUnit: 'years' }));
t('chinese era undefined', () => String(C('chinese', 2024, { month: 1, day: 1 }).era));
t('chinese era bag', () => P.from({ era: 'x', eraYear: 1, month: 1, day: 1, calendar: 'chinese' }));
t('dangi from iso', () => f(P.from('2023-04-01').withCalendar('dangi')));
''')


def test_calendar_persian_indian(run, workdir):
    """CATCHES: Persian (Solar Hijri) bugs: Nowruz dates from the March equinox, 30-day Esfand in leap years, 31/30-day month split; Indian (Saka) bugs: Chaitra 1 on Mar 21 vs Mar 22 in Gregorian leap years, 31-day months, and round-tripping bags."""
    check(run, workdir, "calendar_persian_indian", r'''
for (const y of [1399, 1402, 1403, 1404]) {
  t('persian ' + y + ' nowruz', () => iso(P.from({ year: y, month: 1, day: 1, calendar: 'persian' })));
  t('persian ' + y + ' esfand', () => { const d = P.from({ year: y, month: 12, day: 1, calendar: 'persian' }); return d.daysInMonth + ' ' + d.inLeapYear + ' ' + d.daysInYear; });
}
t('persian month lengths', () => Array.from({ length: 12 }, (_, i) => P.from({ year: 1403, month: i + 1, day: 1, calendar: 'persian' }).daysInMonth).join(','));
t('persian esfand 30 reject', () => P.from({ year: 1402, month: 12, day: 30, calendar: 'persian' }, { overflow: 'reject' }));
t('persian era ap', () => iso(P.from({ era: 'ap', eraYear: 1403, month: 7, day: 1, calendar: 'persian' })));
t('persian negative year', () => f(P.from('0500-01-01').withCalendar('persian')));
t('persian add month', () => P.from({ year: 1403, month: 6, day: 31, calendar: 'persian' }).add({ months: 1 }).day);
for (const y of [1945, 1946]) {
  t('indian ' + y + ' new year', () => iso(P.from({ year: y, month: 1, day: 1, calendar: 'indian' })));
}
t('indian month lengths 1946', () => Array.from({ length: 12 }, (_, i) => P.from({ year: 1946, month: i + 1, day: 1, calendar: 'indian' }).daysInMonth).join(','));
t('indian month lengths 1945', () => Array.from({ length: 12 }, (_, i) => P.from({ year: 1945, month: i + 1, day: 1, calendar: 'indian' }).daysInMonth).join(','));
t('indian from iso', () => f(P.from('2024-12-25').withCalendar('indian')));
t('indian era shaka', () => iso(P.from({ era: 'shaka', eraYear: 1946, month: 10, day: 4, calendar: 'indian' })));
t('indian until', () => P.from({ year: 1940, month: 1, day: 1, calendar: 'indian' }).until(P.from({ year: 1946, month: 3, day: 4, calendar: 'indian' }), { largestUnit: 'years' }));
''')


def test_calendar_ethiopic_coptic(run, workdir):
    """CATCHES: 13-month calendar bugs (ethiopic, ethioaa, coptic): the 5/6-day epagomenal 13th month (M13), leap years every 4 years, Amete Mihret vs Amete Alem eras (+5500), constraining day 6 of M13 in common years, and month arithmetic across M13."""
    check(run, workdir, "calendar_ethiopic_coptic", r'''
for (const c of ['ethiopic', 'ethioaa', 'coptic']) {
  t(c + ' new year 2024', () => f(P.from('2024-09-11').withCalendar(c)));
  t(c + ' M13 lengths', () => [2015, 2016, 2017].map((y) => { const yy = c === 'ethioaa' ? y + 5500 : c === 'coptic' ? y - 276 : y; return P.from({ year: yy, monthCode: 'M13', day: 1, calendar: c }).daysInMonth; }).join(','));
}
t('ethiopic M13 day 6 constrain', () => P.from({ year: 2016, monthCode: 'M13', day: 6, calendar: 'ethiopic' }).day);
t('ethiopic M13 day 6 reject', () => P.from({ year: 2016, monthCode: 'M13', day: 6, calendar: 'ethiopic' }, { overflow: 'reject' }));
t('ethiopic M13 day 6 leap', () => iso(P.from({ year: 2015, monthCode: 'M13', day: 6, calendar: 'ethiopic' }, { overflow: 'reject' })));
t('ethiopic month 14', () => P.from({ year: 2016, month: 14, day: 1, calendar: 'ethiopic' }, { overflow: 'reject' }));
t('ethiopic era aa', () => iso(P.from({ era: 'aa', eraYear: 5500, month: 1, day: 1, calendar: 'ethiopic' })));
t('ethiopic era am', () => iso(P.from({ era: 'am', eraYear: 2017, month: 1, day: 1, calendar: 'ethiopic' })));
t('ethiopic year 0 era', () => { const d = P.from({ year: 0, month: 1, day: 1, calendar: 'ethiopic' }); return d.era + ' ' + d.eraYear + ' ' + iso(d); });
t('ethioaa era', () => { const d = P.from('2024-01-01').withCalendar('ethioaa'); return d.era + ' ' + d.eraYear + ' ' + d.year; });
t('coptic era am', () => iso(P.from({ era: 'am', eraYear: 1741, month: 1, day: 1, calendar: 'coptic' })));
t('add 1 month from M12', () => { const d = P.from({ year: 2016, month: 12, day: 30, calendar: 'ethiopic' }).add({ months: 1 }); return d.monthCode + ' ' + d.day; });
t('add 2 months from M12', () => { const d = P.from({ year: 2016, month: 12, day: 30, calendar: 'ethiopic' }).add({ months: 2 }); return d.year + ' ' + d.monthCode + ' ' + d.day; });
t('add 1 month reject', () => P.from({ year: 2016, month: 12, day: 30, calendar: 'ethiopic' }).add({ months: 1 }, { overflow: 'reject' }));
t('coptic until months', () => P.from({ year: 1740, month: 1, day: 1, calendar: 'coptic' }).until(P.from({ year: 1741, month: 2, day: 1, calendar: 'coptic' }), { largestUnit: 'months' }));
''')


def test_calendar_arithmetic_and_differences(run, workdir):
    """CATCHES: calendar-aware arithmetic bugs: adding years/months in the calendar's own month structure (not ISO months) for lunar, lunisolar and solar calendars, until/since with largestUnit years/months and rounding in non-ISO calendars, and gregorian-structure calendars following ISO."""
    check(run, workdir, "calendar_arithmetic_and_differences", r'''
const base = P.from('2024-03-11');
for (const c of ['gregory', 'buddhist', 'japanese', 'islamic-civil', 'islamic-umalqura', 'hebrew', 'chinese', 'persian', 'indian', 'coptic']) {
  const d = base.withCalendar(c);
  t(c + ' +P1Y', () => iso(d.add('P1Y')));
  t(c + ' +P1M', () => iso(d.add('P1M')));
  t(c + ' -P13M', () => iso(d.subtract('P13M')));
  t(c + ' until 2026-01-01', () => d.until(P.from('2026-01-01').withCalendar(c), { largestUnit: 'years' }).toString());
  t(c + ' since 2020-06-30 months rounded', () => d.since(P.from('2020-06-30').withCalendar(c), { largestUnit: 'months', smallestUnit: 'months', roundingMode: 'halfExpand' }).toString());
}
t('PlainDateTime hebrew add', () => Temporal.PlainDateTime.from('2024-03-11T10:00[u-ca=hebrew]').add({ months: 1, hours: 20 }).toString());
t('ZonedDateTime islamic add', () => Temporal.ZonedDateTime.from('2024-03-11T10:00[Asia/Riyadh][u-ca=islamic-umalqura]').add({ months: 1 }).toString());
t('ZonedDateTime chinese until', () => Temporal.ZonedDateTime.from('2024-03-11T10:00[Asia/Shanghai][u-ca=chinese]').until(Temporal.ZonedDateTime.from('2025-03-11T10:00[Asia/Shanghai][u-ca=chinese]'), { largestUnit: 'months' }).toString());
t('Duration round relativeTo hebrew', () => Temporal.Duration.from('P400D').round({ largestUnit: 'years', relativeTo: P.from('2024-03-11[u-ca=hebrew]') }).toString());
t('Duration total months relativeTo islamic', () => Temporal.Duration.from('P45D').total({ unit: 'months', relativeTo: P.from('2024-03-11[u-ca=islamic-civil]') }));
''')


def test_calendar_year_month_and_month_day(run, workdir):
    """CATCHES: PlainYearMonth/PlainMonthDay calendar bugs: reference ISO days/years for non-ISO calendars, leap-month month-days (M05L, chinese leap months) picking a valid reference year, monthCode+day requirements, toPlainDate across years, and string parsing rules requiring full dates for non-ISO calendars."""
    check(run, workdir, "calendar_year_month_and_month_day", r'''
const YM = Temporal.PlainYearMonth, MD = Temporal.PlainMonthDay;
t('YM hebrew bag', () => YM.from({ year: 5784, monthCode: 'M05L', calendar: 'hebrew' }).toString());
t('YM hebrew bag constrain', () => YM.from({ year: 5783, monthCode: 'M05L', calendar: 'hebrew' }).toString());
t('YM hebrew getters', () => { const y = YM.from({ year: 5784, month: 6, calendar: 'hebrew' }); return [y.year, y.month, y.monthCode, y.daysInMonth, y.monthsInYear, y.inLeapYear, y.era, y.eraYear].join(' '); });
t('YM islamic add', () => YM.from({ year: 1445, month: 12, calendar: 'islamic-civil' }).add({ months: 1 }).toString());
t('YM japanese era', () => YM.from({ era: 'reiwa', eraYear: 6, month: 3, calendar: 'japanese' }).toString());
t('YM chinese until', () => YM.from({ year: 2023, month: 1, calendar: 'chinese' }).until(YM.from({ year: 2024, month: 1, calendar: 'chinese' })).toString());
t('YM toPlainDate', () => YM.from({ year: 5784, monthCode: 'M05L', calendar: 'hebrew' }).toPlainDate({ day: 30 }).toString());
t('YM from PlainDate', () => P.from('2024-03-11[u-ca=persian]').toPlainYearMonth().toString());
t('YM ctor with calendar', () => new YM(2024, 3, 'persian', 1).toString());
t('MD hebrew M05L', () => MD.from({ monthCode: 'M05L', day: 30, calendar: 'hebrew' }).toString());
t('MD hebrew M02 30', () => MD.from({ monthCode: 'M02', day: 30, calendar: 'hebrew' }).toString());
t('MD hebrew M03 30', () => MD.from({ monthCode: 'M03', day: 30, calendar: 'hebrew' }).toString());
t('MD hebrew month needs year', () => MD.from({ month: 6, day: 1, calendar: 'hebrew' }));
t('MD hebrew year+month', () => MD.from({ year: 5784, month: 6, day: 1, calendar: 'hebrew' }).monthCode);
t('MD chinese M04L', () => MD.from({ monthCode: 'M04L', day: 1, calendar: 'chinese' }).toString());
t('MD chinese M11L', () => MD.from({ monthCode: 'M11L', day: 29, calendar: 'chinese' }).toString());
t('MD chinese M01 30', () => MD.from({ monthCode: 'M01', day: 30, calendar: 'chinese' }).toString());
t('MD islamic M12 30', () => MD.from({ monthCode: 'M12', day: 30, calendar: 'islamic-umalqura' }).toString());
t('MD persian M12 30', () => MD.from({ monthCode: 'M12', day: 30, calendar: 'persian' }).toString());
t('MD ethiopic M13 6', () => MD.from({ monthCode: 'M13', day: 6, calendar: 'ethiopic' }).toString());
t('MD ethiopic M13 7 reject', () => MD.from({ monthCode: 'M13', day: 7, calendar: 'ethiopic' }, { overflow: 'reject' }));
t('MD gregory', () => MD.from({ monthCode: 'M02', day: 29, calendar: 'gregory' }).toString());
t('MD toPlainDate hebrew', () => MD.from({ monthCode: 'M05L', day: 1, calendar: 'hebrew' }).toPlainDate({ year: 5783 }).toString());
t('MD from PlainDate', () => P.from('2024-03-11[u-ca=chinese]').toPlainMonthDay().toString());
t('MD with', () => MD.from({ monthCode: 'M01', day: 1, calendar: 'indian' }).with({ day: 31 }).toString());
t('YM toJSON non-ISO', () => YM.from({ year: 5784, monthCode: 'M05L', calendar: 'hebrew' }).toJSON());
t('MD toJSON non-ISO', () => MD.from({ monthCode: 'M05L', day: 1, calendar: 'hebrew' }).toJSON());
t('MD equals', () => MD.from({ monthCode: 'M01', day: 1, calendar: 'coptic' }).equals(MD.from({ monthCode: 'M01', day: 1, calendar: 'coptic' })));
''')


def test_calendar_to_locale_string(run, workdir):
    """CATCHES: calendar-aware toLocaleString bugs: month names and era names from CLDR for hebrew/islamic/japanese/buddhist/persian/chinese, the formatter's u-ca extension matching the value's calendar (RangeError on mismatch), and locale-specific month names. Pins reference quirks: Adar II in a leap year is named plain "Adar", and he-u-ca-hebrew resolves to gregory (calendar mismatch)."""
    check(run, workdir, "calendar_to_locale_string", r'''
const d = P.from('2024-03-11');
const opts = { year: 'numeric', month: 'long', day: 'numeric', era: 'short' };
for (const c of ['gregory', 'japanese', 'buddhist', 'roc', 'islamic-umalqura', 'islamic-civil', 'hebrew', 'persian', 'indian', 'coptic', 'ethiopic', 'chinese', 'dangi'])
  t(c, () => d.withCalendar(c).toLocaleString('en-u-ca-' + c, opts));
t('hebrew Adar I', () => P.from({ year: 5784, monthCode: 'M05L', day: 1, calendar: 'hebrew' }).toLocaleString('en-u-ca-hebrew', { month: 'long', year: 'numeric' }));
t('hebrew he', () => d.withCalendar('hebrew').toLocaleString('he-u-ca-hebrew', { month: 'long' }));
t('japanese ja', () => d.withCalendar('japanese').toLocaleString('ja-JP-u-ca-japanese', { era: 'long', year: 'numeric', month: 'long', day: 'numeric' }));
t('islamic ar', () => d.withCalendar('islamic-umalqura').toLocaleString('ar-u-ca-islamic-umalqura', { month: 'long' }));
t('gregory short month de', () => d.toLocaleString('de', { month: 'short' }));
t('iso8601 uses gregory', () => d.toLocaleString('en', opts));
t('mismatch', () => d.withCalendar('persian').toLocaleString('en-u-ca-hebrew'));
t('PlainDateTime hebrew', () => Temporal.PlainDateTime.from('2024-03-11T13:00[u-ca=hebrew]').toLocaleString('en-u-ca-hebrew'));
t('ZonedDateTime buddhist', () => Temporal.ZonedDateTime.from('2024-03-11T13:00[Asia/Bangkok][u-ca=buddhist]').toLocaleString('en-u-ca-buddhist', { dateStyle: 'long' }));
''')


def test_calendar_property_bag_errors(run, workdir):
    """CATCHES: calendar-specific property-bag resolution bugs for every calendar family (hebrew, chinese, 13-month, islamic, indian, persian, gregorian-structured): month 0, missing year/month/day, month/monthCode disagreement, malformed or out-of-range monthCodes, leap codes where none exist, and era/eraYear pairing and validity."""
    check(run, workdir, "calendar_property_bag_errors", r'''
const years = { hebrew: 5784, chinese: 2023, dangi: 2023, coptic: 1740, ethioaa: 7516, 'islamic-civil': 1445, indian: 1946, persian: 1403, gregory: 2024, roc: 113 };
const eras = { hebrew: 'am', chinese: 'x', dangi: 'x', coptic: 'am', ethioaa: 'aa', 'islamic-civil': 'ah', indian: 'shaka', persian: 'ap', gregory: 'ce', roc: 'roc' };
for (const cal of Object.keys(years)) {
  const y = years[cal];
  const tryBag = (label, bag, opts) => t(cal + ' ' + label, () => { const d = P.from({ calendar: cal, ...bag }, opts); return d.toString() + ' ' + d.monthCode; });
  tryBag('month 0', { year: y, month: 0, day: 1 });
  tryBag('no year', { month: 1, day: 1 });
  tryBag('no month', { year: y, day: 1 });
  tryBag('no day', { year: y, month: 1 });
  tryBag('disagree', { year: y, month: 2, monthCode: 'M03', day: 1 });
  tryBag('code X01', { year: y, monthCode: 'X01', day: 1 });
  tryBag('code M1', { year: y, monthCode: 'M1', day: 1 });
  tryBag('code M00', { year: y, monthCode: 'M00', day: 1 });
  tryBag('code M13', { year: y, monthCode: 'M13', day: 1 });
  tryBag('code M03L', { year: y, monthCode: 'M03L', day: 1 });
  tryBag('era only', { era: eras[cal], month: 1, day: 1 });
  tryBag('eraYear only', { eraYear: y, month: 1, day: 1 });
  tryBag('era+eraYear', { era: eras[cal], eraYear: y, month: 1, day: 1 });
  tryBag('bad era', { era: 'zz', eraYear: y, month: 1, day: 1 });
  tryBag('month 14 constrain', { year: y, month: 14, day: 1 });
}
''')


def test_calendar_month_day_references(run, workdir):
    """CATCHES: PlainMonthDay reference-year selection bugs in non-ISO calendars: each monthCode (incl. every Chinese leap month and Hebrew M05L) with day 1 and day 30, constrain vs reject when a code/day combination never occurs, and day clamping per calendar month length."""
    check(run, workdir, "calendar_month_day_references", r'''
const MD = Temporal.PlainMonthDay;
const ref = (cal, code, day, overflow) => { try { return MD.from({ monthCode: code, day, calendar: cal }, { overflow }).toString({ calendarName: 'never' }); } catch (e) { return e.name; } };
const codes = (n, leap) => Array.from({ length: n }, (_, i) => 'M' + String(i + 1).padStart(2, '0') + (leap ? 'L' : ''));
for (const cal of ['chinese', 'dangi']) {
  for (const code of [...codes(12), ...codes(12, true)])
    console.log(cal, code, ref(cal, code, 1, 'reject'), ref(cal, code, 30, 'reject'), ref(cal, code, 30, 'constrain'));
}
for (const code of [...codes(12), 'M05L', 'M13'])
  console.log('hebrew', code, ref('hebrew', code, 29, 'reject'), ref('hebrew', code, 30, 'reject'), ref('hebrew', code, 31, 'constrain'));
for (const cal of ['islamic-umalqura', 'islamic-civil', 'islamic-tbla', 'persian', 'indian', 'coptic', 'ethiopic', 'gregory', 'buddhist', 'japanese', 'roc']) {
  console.log(cal, codes(cal === 'coptic' || cal === 'ethiopic' ? 13 : 12).map((c) => ref(cal, c, 31, 'constrain')).join(' '));
  console.log(cal, 'day30', codes(12).map((c) => ref(cal, c, 30, 'reject').slice(0, 10)).join(' '));
}
for (const cal of ['islamic-umalqura', 'islamic-civil', 'persian', 'indian', 'coptic', 'gregory', 'hebrew'])
  t(cal + ' M13/M01L/M14', () => ['M13', 'M01L', 'M14'].map((c) => { try { return MD.from({ monthCode: c, day: 1, calendar: cal }).toString(); } catch (e) { return e.message; } }).join(' | '));
t('islamic M01L', () => MD.from({ monthCode: 'M01L', day: 1, calendar: 'islamic-civil' }));
t('coptic M13 day 6 reject', () => MD.from({ monthCode: 'M13', day: 6, calendar: 'coptic' }, { overflow: 'reject' }).toString());
t('coptic M14', () => MD.from({ monthCode: 'M14', day: 1, calendar: 'coptic' }));
t('chinese with year', () => MD.from({ year: 2023, month: 3, day: 1, calendar: 'chinese' }).toString());
t('chinese with year+code', () => MD.from({ year: 2023, monthCode: 'M02L', day: 30, calendar: 'chinese' }).toString());
t('hebrew with era', () => MD.from({ era: 'am', eraYear: 5784, month: 6, day: 30, calendar: 'hebrew' }).toString());
t('hebrew huge eraYear', () => MD.from({ era: 'am', eraYear: 1e9, monthCode: 'M01', day: 1, calendar: 'hebrew' }));
t('hebrew huge year', () => MD.from({ year: 1e9, monthCode: 'M01', day: 1, calendar: 'hebrew' }));
t('gregory era md', () => MD.from({ era: 'bce', eraYear: 1, monthCode: 'M02', day: 29, calendar: 'gregory' }).toString());
''')


def test_calendar_astronomical_ranges(run, workdir):
    """CATCHES: astronomical-calendar bugs over long spans: Persian Nowruz across centuries (different ΔT eras), Chinese new year before 1929 (Beijing mean time), Dangi before 1908 (Seoul mean time), Hebrew new-year postponement rules over many years, and Islamic dates outside the Umm al-Qura table."""
    check(run, workdir, "calendar_astronomical_ranges", r'''
const nowruz = [1100, 1200, 1240, 1270, 1290, 1310, 1330, 1350, 1360, 1375, 1390, 1420, 1500, 1600].map((y) => y + ':' + iso(P.from({ year: y, month: 1, day: 1, calendar: 'persian' })).slice(0, 10));
console.log('persian', nowruz.join(' '));
const pl = []; for (let y = 1380; y <= 1420; y++) if (P.from({ year: y, month: 1, day: 1, calendar: 'persian' }).inLeapYear) pl.push(y);
console.log('persian leap', pl.join(','));
const cny = [1850, 1900, 1906, 1920, 1928, 1929, 1950, 1985, 2033, 2057, 2100].map((y) => y + ':' + iso(P.from({ year: y, month: 1, day: 1, calendar: 'chinese' })).slice(5));
console.log('chinese', cny.join(' '));
const dny = [1890, 1900, 1907, 1908, 1912, 1955, 1960, 1997, 2050].map((y) => y + ':' + iso(P.from({ year: y, month: 1, day: 1, calendar: 'dangi' })).slice(5));
console.log('dangi', dny.join(' '));
const leaps = (cal, a, b) => { const out = []; for (let y = a; y <= b; y++) { const d = P.from({ year: y, month: 1, day: 1, calendar: cal }); if (d.monthsInYear === 13) { for (let m = 1; m <= 13; m++) { const c = P.from({ year: y, month: m, day: 1, calendar: cal }).monthCode; if (c.endsWith('L')) { out.push(y + c.slice(1)); break; } } } } return out.join(' '); };
console.log('chinese leap months 1900-1960', leaps('chinese', 1900, 1960));
console.log('dangi leap months 1900-1960', leaps('dangi', 1900, 1960));
const hl = []; for (let y = 5700; y <= 5800; y++) hl.push(P.from({ year: y, month: 1, day: 1, calendar: 'hebrew' }).daysInYear - 350);
console.log('hebrew year lengths-350 5700..5800', hl.join(''));
const hny = [3762, 4000, 5000, 5500, 5660, 5785, 6000].map((y) => y + ':' + iso(P.from({ year: y, month: 1, day: 1, calendar: 'hebrew' })));
console.log('hebrew new years', hny.join(' '));
const um = [1299, 1300, 1301, 1450, 1599, 1600, 1601].map((y) => y + ':' + iso(P.from({ year: y, month: 1, day: 1, calendar: 'islamic-umalqura' })) + '/' + P.from({ year: y, month: 1, day: 1, calendar: 'islamic-umalqura' }).daysInYear);
console.log('umalqura', um.join(' '));
t('umalqura far past', () => f(P.from('1000-01-01').withCalendar('islamic-umalqura')));
t('umalqura far future', () => f(P.from('3000-01-01').withCalendar('islamic-umalqura')));
t('hebrew year 1', () => iso(P.from({ year: 1, month: 1, day: 1, calendar: 'hebrew' })));
t('hebrew negative', () => f(P.from('-004000-01-01').withCalendar('hebrew')));
t('persian ancient', () => f(P.from('0100-03-21').withCalendar('persian')));
t('chinese ancient', () => f(P.from('1000-06-01').withCalendar('chinese')));
''')


def test_calendar_misc_behaviours(run, workdir):
    """CATCHES: assorted calendar bugs: weekOfYear/yearOfWeek undefined outside ISO, Japanese/ROC BCE eras, Hebrew/Chinese month arithmetic with day overflow (constrain vs reject), 13-month and Persian year-month arithmetic, and differences between leap and non-leap months. Pins a reference quirk: era 'roc-inverse' passes era validation but then fails with 'invalid era'."""
    check(run, workdir, "calendar_misc_behaviours", r'''
for (const c of ['iso8601', 'gregory', 'hebrew', 'chinese', 'persian'])
  t('weekOfYear ' + c, () => { const d = P.from('2024-12-30').withCalendar(c); return String(d.weekOfYear) + ' ' + String(d.yearOfWeek) + ' ' + d.dayOfWeek + ' ' + d.daysInWeek; });
t('PDT weekOfYear hebrew', () => { const d = Temporal.PlainDateTime.from('2024-12-30T00:00[u-ca=hebrew]'); return [String(d.weekOfYear), String(d.yearOfWeek), d.era, d.eraYear, d.monthsInYear, d.daysInWeek].join(' '); });
t('PDT toJSON hebrew', () => Temporal.PlainDateTime.from('2024-12-30T00:00[u-ca=hebrew]').toJSON());
t('japanese bce', () => { const d = P.from('-000005-01-01').withCalendar('japanese'); return d.era + ' ' + d.eraYear; });
t('japanese bce bag', () => P.from({ era: 'bce', eraYear: 6, month: 1, day: 1, calendar: 'japanese' }).toString());
t('roc before', () => { const d = P.from('1900-01-01').withCalendar('roc'); return d.era + ' ' + d.eraYear + ' ' + d.year; });
t('roc roc-inverse era', () => P.from({ era: 'roc-inverse', eraYear: 12, month: 1, day: 1, calendar: 'roc' }));
t('buddhist negative', () => { const d = P.from('-000600-01-01').withCalendar('buddhist'); return d.era + ' ' + d.eraYear + ' ' + d.year; });
const H = (y, m, day) => P.from({ year: y, month: m, day, calendar: 'hebrew' });
t('hebrew 30 Tishri +1M constrain', () => { const d = H(5784, 1, 30).add({ months: 1 }); return d.monthCode + ' ' + d.day; });
t('hebrew 30 Tishri +1M reject', () => H(5784, 1, 30).add({ months: 1 }, { overflow: 'reject' }));
t('hebrew 30 Adar I +1Y constrain', () => { const d = P.from({ year: 5784, monthCode: 'M05L', day: 30, calendar: 'hebrew' }).add({ years: 1 }); return d.monthCode + ' ' + d.day + ' ' + iso(d); });
t('hebrew +1Y1M2W3D', () => iso(H(5784, 1, 1).add({ years: 1, months: 1, weeks: 2, days: 3 })));
t('hebrew -P2Y', () => iso(H(5784, 6, 15).subtract({ years: 2 })));
t('hebrew until weeks', () => H(5784, 1, 1).until(H(5785, 1, 1), { largestUnit: 'weeks' }));
t('hebrew until days', () => H(5784, 1, 1).until(H(5785, 1, 1)));
t('hebrew since years leap end', () => P.from({ year: 5784, monthCode: 'M05L', day: 15, calendar: 'hebrew' }).since(P.from({ year: 5782, monthCode: 'M05L', day: 20, calendar: 'hebrew' }), { largestUnit: 'years' }));
t('hebrew until M05L to M06 next year', () => P.from({ year: 5784, monthCode: 'M05L', day: 1, calendar: 'hebrew' }).until(P.from({ year: 5785, monthCode: 'M06', day: 1, calendar: 'hebrew' }), { largestUnit: 'years' }));
const C = (y, code, day) => P.from({ year: y, monthCode: code, day, calendar: 'chinese' });
t('hebrew same date until years', () => H(5784, 3, 3).until(H(5784, 3, 3), { largestUnit: 'years' }));
t('hebrew backward from M05L to M06', () => P.from({ year: 5784, monthCode: 'M05L', day: 15, calendar: 'hebrew' }).until(P.from({ year: 5783, monthCode: 'M06', day: 15, calendar: 'hebrew' }), { largestUnit: 'years' }));
t('hebrew 30 Tishri until 29 Cheshvan months', () => H(5784, 1, 30).until(H(5784, 2, 29), { largestUnit: 'months' }));
t('chinese forward leap clamp years', () => C(2023, 'M02L', 10).until(C(2024, 'M02', 10), { largestUnit: 'years' }));
t('chinese day 30 clamp years', () => `${C(2023, 'M01', 29).until(C(2024, 'M01', 29), { largestUnit: 'years' })} ${C(2023, 'M02', 30).until(C(2024, 'M02', 29), { largestUnit: 'years' })}`);
t('chinese 30 +1M reject', () => C(2023, 'M02', 30).add({ months: 1 }, { overflow: 'reject' }));
t('chinese 30 +1M constrain', () => { const d = C(2023, 'M02', 30).add({ months: 1 }); return d.monthCode + ' ' + d.day; });
t('chinese leap +1Y reject', () => C(2023, 'M02L', 1).add({ years: 1 }, { overflow: 'reject' }));
t('chinese since years from leap', () => C(2023, 'M02L', 10).since(C(2020, 'M04L', 10), { largestUnit: 'years' }));
t('chinese until same month leap', () => C(2023, 'M02', 10).until(C(2023, 'M02L', 10), { largestUnit: 'years' }));
t('coptic YM add 13 months', () => Temporal.PlainYearMonth.from({ year: 1740, month: 13, calendar: 'coptic' }).add({ months: 1 }).toString());
t('coptic YM until', () => Temporal.PlainYearMonth.from({ year: 1740, month: 1, calendar: 'coptic' }).until(Temporal.PlainYearMonth.from({ year: 1742, month: 13, calendar: 'coptic' })));
t('persian YM add', () => Temporal.PlainYearMonth.from({ year: 1403, month: 12, calendar: 'persian' }).add({ months: 13 }).toString());
t('indian YM since', () => Temporal.PlainYearMonth.from({ year: 1946, month: 1, calendar: 'indian' }).since(Temporal.PlainYearMonth.from({ year: 1940, month: 7, calendar: 'indian' }), { largestUnit: 'months' }));
t('hebrew YM add years from M05L', () => Temporal.PlainYearMonth.from({ year: 5784, monthCode: 'M05L', calendar: 'hebrew' }).add({ years: 1 }).toString());
t('hebrew YM until', () => Temporal.PlainYearMonth.from({ year: 5780, month: 1, calendar: 'hebrew' }).until(Temporal.PlainYearMonth.from({ year: 5784, month: 13, calendar: 'hebrew' }), { largestUnit: 'months' }));
t('islamic duration total years', () => Temporal.Duration.from('P400D').total({ unit: 'years', relativeTo: P.from({ year: 1445, month: 1, day: 1, calendar: 'islamic-umalqura' }) }));
t('chinese duration round months', () => Temporal.Duration.from('P100D').round({ largestUnit: 'months', relativeTo: C(2023, 'M01', 1) }).toString());
t('coptic duration round years', () => Temporal.Duration.from('P400D').round({ largestUnit: 'years', smallestUnit: 'months', relativeTo: P.from({ year: 1740, month: 13, day: 5, calendar: 'coptic' }) }).toString());
''')


def test_calendar_relative_to_bag_resolution(run, workdir):
    """CATCHES: relativeTo property bags resolved through each calendar (where required-field errors come from the calendar resolver itself): missing year/month, era-only years, month/monthCode disagreement, leap codes, and the resulting month-length-dependent rounding. Pins a reference quirk: a Hebrew relativeTo bag accepts the malformed monthCode 'M5'."""
    check(run, workdir, "calendar_relative_to_bag_resolution", r'''
const years = { hebrew: 5784, chinese: 2023, coptic: 1740, 'islamic-umalqura': 1445, indian: 1946, persian: 1403, gregory: 2024, ethiopic: 2016 };
const eras = { hebrew: 'am', chinese: 'x', coptic: 'am', 'islamic-umalqura': 'bh', indian: 'shaka', persian: 'ap', gregory: 'bce', ethiopic: 'aa' };
const dur = Temporal.Duration.from('P45D');
for (const cal of Object.keys(years)) {
  const y = years[cal];
  const r = (label, bag) => t(cal + ' ' + label, () => dur.round({ largestUnit: 'months', relativeTo: { calendar: cal, ...bag } }).toString());
  r('ok', { year: y, month: 1, day: 1 });
  r('no year', { month: 1, day: 1 });
  r('no month', { year: y, day: 1 });
  r('no day', { year: y, month: 1 });
  r('disagree', { year: y, month: 2, monthCode: 'M01', day: 1 });
  r('era+eraYear', { era: eras[cal], eraYear: 1, month: 1, day: 1 });
  r('era only', { era: eras[cal], month: 1, day: 1 });
  r('leap code', { year: y, monthCode: 'M05L', day: 1 });
  r('bad code', { year: y, monthCode: 'Q05', day: 1 });
  r('bad code digits', { year: y, monthCode: 'M5', day: 1 });
}
''')
