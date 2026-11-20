"""Number, Math and BigInt built-ins: number-to-string conversions (radix, toFixed/toPrecision/
toExponential), parsing (Number(), parseInt, parseFloat), Number predicates and constants, Math
functions (exact ones raw, transcendental ones rounded to 12 significant digits), and BigInt
arithmetic, conversions and errors."""

from conftest import check_script, resources_for

G = resources_for(__file__)

PRELUDE = r'''
const fmt = (v, d = 0) => {
  if (typeof v === 'string') return JSON.stringify(v);
  if (typeof v === 'number') return Object.is(v, -0) ? '-0' : String(v);
  if (typeof v === 'bigint') return v + 'n';
  if (typeof v === 'symbol') return v.toString();
  if (typeof v === 'function') return '[Function ' + (v.name || '<anon>') + ']';
  if (v === null || typeof v !== 'object') return String(v);
  if (v instanceof Error) return '[' + v.name + ': ' + v.message + ']';
  if (d > 4) return '...';
  if (Array.isArray(v)) {
    const out = [];
    for (let i = 0; i < v.length; i++) out.push(i in v ? fmt(v[i], d + 1) : '<hole>');
    return '[' + out.join(', ') + ']';
  }
  return '{' + Reflect.ownKeys(v).map(k => {
    const desc = Object.getOwnPropertyDescriptor(v, k);
    return String(k) + ': ' + ('value' in desc ? fmt(desc.value, d + 1) : '<accessor>');
  }).join(', ') + '}';
};
const show = (label, f) => {
  try { console.log(label + ' => ' + fmt(f())); }
  catch (e) { console.log(label + ' !! ' + (e !== null && typeof e === 'object' ? e.name + ': ' + e.message : 'thrown ' + fmt(e))); }
};
// Transcendental results come from the platform libm: compare them at 12 significant digits.
const r12 = x => typeof x === 'number' && isFinite(x) && x !== 0 ? Number(x.toPrecision(12)) : x;
'''


def check(run, workdir, name, body, **kw):
    """Run PRELUDE + body as a script and compare with the golden `name`."""
    return check_script(run, workdir, G, name, PRELUDE + body, **kw)


def test_number_to_string_radix_and_shortest(run, workdir):
    """CATCHES: Number#toString(radix) producing wrong digits for fractions/negatives/huge values,
    accepting radix outside 2..36 (exact RangeError), and the default ToString not choosing the
    shortest round-trip digits or switching to exponent form at the wrong thresholds (1e21, 1e-7)."""
    check(run, workdir, "number_to_string_radix_and_shortest", r'''
show('radix', () => [(255).toString(16), (255).toString(2), (-255).toString(36), (0.5).toString(2), (3.75).toString(8), (255.5).toString(16), (-0.5).toString(2), (2 ** -20).toString(32), (2 ** 53).toString(32)]);
show('radix long fractions', () => [(0.1).toString(3), (0.1).toString(16), (1 / 3).toString(3), (123.456).toString(36), (1e-7).toString(2)]);
show('radix huge', () => [(1e21).toString(36), (-1e21).toString(7), (Number.MAX_VALUE).toString(36).length, (Number.MIN_VALUE).toString(2).length]);
show('radix specials', () => [(-0).toString(2), NaN.toString(16), Infinity.toString(7), (-Infinity).toString(36), (10).toString(undefined), (10).toString(10.9)]);
show('radix 1', () => (1).toString(1));
show('radix 37', () => (1).toString(37));
show('radix NaN', () => (1).toString(NaN));
show('shortest', () => [1e21, 1e-7, 123e-20, 0.000001, 1.7976931348623157e308, 5e-324, 2 ** 53 + 1, -1e-7, 100, 0.1 + 0.2, 1 / 3, 123456789012345680000, 1.5e300, 4.35, 0.000123].map(String));
show('integers near limits', () => [2 ** 53, 2 ** 53 + 2, 9007199254740993, 2 ** 64, 2 ** 70, -(2 ** 31)].map(String));
show('wrong receiver', () => Number.prototype.toString.call('1'));
show('boxed receiver', () => Number.prototype.toString.call(new Number(42), 16));
''')


def test_number_fixed_precision_exponential(run, workdir):
    """CATCHES: toFixed/toPrecision/toExponential rounding with the binary value (1.005 -> '1.00',
    1.45 -> '1.4', 1.35.toPrecision(2) -> '1.4'), switching toFixed to exponent form at 1e21,
    negative zero handling, argument coercion, NaN/Infinity before range checks for toPrecision/
    toExponential but not toFixed, and the exact RangeError texts."""
    check(run, workdir, "number_fixed_precision_exponential", r'''
show('toFixed', () => [(1.005).toFixed(2), (1.45).toFixed(1), (0).toFixed(2), (-0).toFixed(2), (-1.5).toFixed(0), (2.5).toFixed(0), (-2.5).toFixed(0), (0.5).toFixed(0), (1.5).toFixed(), (123.456).toFixed()]);
show('toFixed big/small', () => [(1e21).toFixed(2), (1e20).toFixed(2), (1e21 - 65537).toFixed(1), (2 ** 70).toFixed(1), (0.000001).toFixed(7), (1.23e-10).toFixed(20), (0.1).toFixed(20), (-0.0000001).toFixed(3), (-1e-10).toFixed(2), (5e-7).toFixed(100).length]);
show('toFixed specials', () => [NaN.toFixed(2), Infinity.toFixed(1), (-Infinity).toFixed()]);
show('toFixed carries', () => [(99.5).toFixed(0), (9.96).toFixed(1), (999.9999).toFixed(2), (9.5).toFixed(0), (0.995).toFixed(2), (1.5e-7).toFixed(7), (-99.95).toFixed(1)]);
show('toFixed coercion', () => [(1.5).toFixed('1'), (1.5).toFixed(null), (1.5).toFixed(undefined), (1.5).toFixed(1.9), (1.5).toFixed(-0.5), (1.25).toFixed(1), (8.345).toFixed(2)]);
show('toFixed -1', () => (1).toFixed(-1));
show('toFixed 101', () => (1).toFixed(101));
show('NaN toFixed 101', () => NaN.toFixed(101));
show('toPrecision', () => [(123.456).toPrecision(4), (0.000123).toPrecision(2), (123456).toPrecision(2), (1e21).toPrecision(3), (0).toPrecision(5), (-1.5).toPrecision(1), (1).toPrecision(), (99.99).toPrecision(3), (1e-7).toPrecision(1), (1.25).toPrecision(2), (1.35).toPrecision(2)]);
show('toPrecision edges', () => [(1e21).toPrecision(22), (123456789).toPrecision(9), (0.00001).toPrecision(1), (0.000001).toPrecision(2), (-0).toPrecision(3), (5e-324).toPrecision(3), (1.7976931348623157e308).toPrecision(5), (123).toPrecision(100).length, (123.456).toPrecision(undefined)]);
show('toPrecision specials', () => [NaN.toPrecision(200), Infinity.toPrecision(0), (-Infinity).toPrecision(1000)]);
show('toPrecision 0', () => (1).toPrecision(0));
show('toPrecision 101', () => (1).toPrecision(101));
show('toExponential', () => [(123456).toExponential(2), (0).toExponential(), (0).toExponential(3), (-1.5e-7).toExponential(1), (1).toExponential(), (12345).toExponential(), (1.45).toExponential(1), (0.00015).toExponential(1), (-0).toExponential(2), (123.456).toExponential(0)]);
show('toExponential edges', () => [(5e-324).toExponential(), (1.7976931348623157e308).toExponential(20), (1e21).toExponential(), Infinity.toExponential(1000), NaN.toExponential(-1)]);
show('toExponential -1', () => (1).toExponential(-1));
show('toExponential 101', () => (1).toExponential(101));
show('wrong receiver', () => Number.prototype.toFixed.call('1'));
show('wrong receiver valueOf', () => Number.prototype.valueOf.call({}));
show('toLocaleString', () => [(1234567.891).toLocaleString(), (0).toLocaleString(), (-1e21).toLocaleString(), (1234.5).toLocaleString('de-DE'), NaN.toLocaleString(), (-0).toLocaleString()]);
''')


def test_number_parsing(run, workdir):
    """CATCHES: StringToNumber accepting numeric separators, '0x' prefixes with signs, partial
    strings, or rejecting surrounding whitespace incl. BOM/U+00A0; parseInt radix handling
    (0 -> 10, 16 auto-detect, out-of-range -> NaN, ToInt32 wrapping), parseInt of numbers in
    exponent form, parseFloat prefix rules and coercion order; legacy octal literals."""
    check(run, workdir, "number_parsing", r'''
show('Number()', () => [Number(''), Number(' 12 '), Number('0x1f'), Number('0X1A'), Number('0b101'), Number('0B1'), Number('0o17'), Number('0O7'), Number('-0x1'), Number('+0x1'), Number('0x'), Number('1_0'), Number('1e1000'), Number('-1e-1000')]);
show('Number() more', () => [Number(null), Number(undefined), Number([]), Number(['5']), Number([1, 2]), Number(true), Number('Infinity'), Number('+Infinity'), Number('-infinity'), Number('Infinityx'), Number(10n), Number('.'), Number('5.'), Number('.5e1'), Number('5.e1'), Number('1e'), Number('e1'), Number('\n\t'), Number('\u00A0 3 \uFEFF'), Number('\u0661')]);
show('Number(symbol)', () => Number(Symbol()));
show('unary plus bigint', () => +1n);
show('Number(bigint) rounding', () => [Number(2n ** 1024n), Number(-(2n ** 1024n)), Number(2n ** 53n + 1n), Number(2n ** 53n + 3n), Number(BigInt(Number.MAX_SAFE_INTEGER) * 3n)]);
show('parseInt', () => [parseInt('  0x1F'), parseInt('-0x10'), parseInt('0b11'), parseInt('08'), parseInt('1e3'), parseInt(''), parseInt('z', 36), parseInt('10', 37), parseInt('10', 1), parseInt('10', 0), parseInt('ff', 16.9), parseInt('-0'), parseInt('123abc'), parseInt('0x'), parseInt('+-1'), parseInt('-0x')]);
show('parseInt numbers', () => [parseInt(0.0000005), parseInt(1e21), parseInt(-0), parseInt(null, 36), parseInt(Infinity), parseInt('Infinity'), parseInt(0.00000001), parseInt(123.9)]);
show('parseInt radix wrap', () => [parseInt('10', 2.5), parseInt('11', -1), parseInt('11', 4294967298), parseInt('11', -4294967294), parseInt('0x10', 16), parseInt('0x10', 10), parseInt('9'.repeat(20), 10), parseInt('1'.repeat(400))]);
show('parseInt whitespace', () => [parseInt('\uFEFF\u00A042'), parseInt('\u2028 7'), parseInt('  -  1'), parseInt('\u180E5')]);
show('parseInt coercion order', () => { const log = []; parseInt({toString() { log.push('string'); return '1'; }}, {valueOf() { log.push('radix'); return 10; }}); return log; });
show('parseFloat', () => [parseFloat('3.14abc'), parseFloat('.5'), parseFloat('-.5e-3x'), parseFloat('Infinityx'), parseFloat('-Infinity'), parseFloat('infinity'), parseFloat('0x10'), parseFloat('1e'), parseFloat('1e+'), parseFloat(''), parseFloat('  -0'), parseFloat('1_000'), parseFloat('1.2.3')]);
show('parseFloat more', () => [parseFloat('1e1000'), parseFloat('-1e-1000'), parseFloat('0.1e-1'), parseFloat('\u0663'), parseFloat('1e+5x'), parseFloat('+.e1'), parseFloat('5e'), parseFloat(['1.5', '2']), parseFloat({toString() { return '2.5kg'; }})]);
show('identity', () => [Number.parseInt === parseInt, Number.parseFloat === parseFloat, parseInt.length, parseFloat.length]);
show('literals', () => [0b1010, 0o17, 0xff, 1_000_000, .5e1, 0.1e-6, 017, 08, 1e-7, 123e-20]);
''')


def test_number_predicates_and_constants(run, workdir):
    """CATCHES: Number.isInteger/isSafeInteger/isNaN/isFinite coercing their argument (they must not)
    vs the global isNaN/isFinite (which do), wrong MAX/MIN_SAFE_INTEGER/EPSILON/MAX_VALUE/MIN_VALUE,
    Number() as constructor vs function, Number.prototype being a Number object with value 0."""
    check(run, workdir, "number_predicates_and_constants", r'''
show('isInteger', () => [Number.isInteger(5.0), Number.isInteger(5.5), Number.isInteger('5'), Number.isInteger(Infinity), Number.isInteger(-0), Number.isInteger(2 ** 60), Number.isInteger(new Number(1))]);
show('isSafeInteger', () => [Number.isSafeInteger(2 ** 53), Number.isSafeInteger(2 ** 53 - 1), Number.isSafeInteger(-(2 ** 53 - 1)), Number.isSafeInteger(3.0), Number.isSafeInteger(3.1), Number.isSafeInteger('3')]);
show('isNaN', () => [Number.isNaN('NaN'), isNaN('NaN'), Number.isNaN(NaN), isNaN(undefined), isNaN(null), isNaN('  '), isNaN({}), isNaN([]), isNaN(new Date(NaN))]);
show('isFinite', () => [Number.isFinite('1'), isFinite('1'), isFinite(null), isFinite('12'), isFinite(''), isFinite('x'), isFinite(Infinity), Number.isFinite(1e308 * 10)]);
show('global isNaN symbol', () => isNaN(Symbol()));
show('global isFinite bigint', () => isFinite(1n));
show('Number.isNaN bigint', () => [Number.isNaN(1n), Number.isFinite(1n), Number.isInteger(1n)]);
show('constants', () => [Number.EPSILON === 2 ** -52, Number.MAX_SAFE_INTEGER, Number.MIN_SAFE_INTEGER, Number.MAX_VALUE, Number.MIN_VALUE, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, Number.NaN]);
show('epsilon use', () => [0.1 + 0.2 === 0.3, Math.abs(0.1 + 0.2 - 0.3) < Number.EPSILON, 1 + Number.EPSILON > 1, 1 + Number.EPSILON / 2 === 1]);
show('constant descriptors', () => { const d = Object.getOwnPropertyDescriptor(Number, 'MAX_SAFE_INTEGER'); return [d.writable, d.enumerable, d.configurable]; });
show('new Number', () => { const n = new Number(5); return [typeof n, n + 1, n.valueOf(), Object.prototype.toString.call(n), n == 5, n === 5, typeof Number(n), new Number() + 0]; });
show('Number.prototype', () => [Number.prototype.valueOf(), Object.prototype.toString.call(Number.prototype), Number.prototype.toFixed(1)]);
show('arithmetic', () => [7 % -3, -7 % 3, 5.5 % 2, -0 % 1, 1 / 0, -1 / 0, 0 / 0, (-2) ** 2, 0.1 * 3, 9007199254740992 + 1, 2 ** 53 + 2]);
show('int32 ops', () => [1 << 31, 1 << 32, -1 >>> 0, -1 >>> 28, 5 >> 1, -5 >> 1, ~~3.7, ~~-3.7, 2 ** 31 | 0, 4294967296.5 | 0, 1 << -1, NaN | 0, Infinity >>> 0]);
show('float accumulate', () => { let x = 0; for (let i = 0; i < 10; i++) x += 0.1; return [x, x.toFixed(15), x === 1]; });
''')


def test_math_exact_functions(run, workdir):
    """CATCHES: Math.round rounding half away from zero (must be toward +Infinity, with -0 for
    (-0.5, 0)), sign/-0 handling in floor/ceil/trunc/sign/abs/max/min, max/min not coercing all
    arguments in order or not propagating NaN, fround/f16round/clz32/imul bit-exactness,
    pow special cases (NaN exponent, +-1 ** Infinity), the reference's naive hypot that
    overflows for 1e200, and Math.sumPrecise exactness, errors and subnormal behaviour."""
    check(run, workdir, "math_exact_functions", r'''
show('round', () => [Math.round(2.5), Math.round(-2.5), Math.round(-0.4), Math.round(0.49999999999999994), Math.round(-0), Math.round(2 ** 52 + 0.5), Math.round(NaN), Math.round(-0.5), Math.round(-0.50000000001), Math.round(1.5), Math.round('2.5')]);
show('floor/ceil/trunc', () => [Math.floor(-0.5), Math.ceil(-0.5), Math.trunc(-0.9), Math.trunc('7.8'), Math.floor(-0), Math.ceil(0.2), Math.floor(Infinity), Math.trunc(-Infinity)]);
show('sign/abs', () => [Math.sign(-3), Math.sign(-0), Math.sign('x'), Math.sign(0.001), Math.abs(-5), Math.abs(-0), Math.abs('-2'), Math.abs(null), Math.abs([-3])]);
show('max/min', () => [Math.max(), Math.min(), Math.max(1, NaN, 3), Math.max(-0, 0), Math.min(0, -0), Math.max('5', [7]), Math.min([1, 2]), Math.max(-Infinity, -1e308)]);
show('max coerces all', () => { const log = []; Math.max({valueOf() { log.push('a'); return NaN; }}, {valueOf() { log.push('b'); return 1; }}); return log; });
show('max bigint', () => Math.max(1n));
show('sqrt', () => [Math.sqrt(2), Math.sqrt(-1), Math.sqrt(-0), Math.sqrt(Infinity), Math.sqrt(1e-320), Math.sqrt(16)]);
show('pow specials', () => [Math.pow(2, 10), Math.pow(NaN, 0), Math.pow(1, Infinity), Math.pow(-1, -Infinity), Math.pow(1, NaN), 2 ** -1074, 2 ** 1024, Math.pow(-0, -1), Math.pow(-0, -2), (-2) ** 3, Math.pow(-8, 1 / 3), Math.pow(0, 0), Math.pow(-Infinity, 3)]);
show('fround', () => [Math.fround(5.5), Math.fround(5.05), Math.fround(2 ** 128), Math.fround(1e-46), Math.fround(-0), Math.fround(16777217), Math.fround(NaN)]);
show('f16round', () => [Math.f16round(5.05), Math.f16round(65520), Math.f16round(65519.99), Math.f16round(1e-8), Math.f16round(65504), Math.f16round(0.1), Math.f16round(-0), Math.f16round(5.960464477539063e-8), Math.f16round(2.98023223876953125e-8)]);
show('clz32/imul', () => [Math.clz32(1), Math.clz32(0), Math.clz32(-1), Math.clz32(0.5), Math.clz32(2 ** 32), Math.imul(3, 4), Math.imul(0xffffffff, 5), Math.imul(2 ** 31, 2), Math.imul(-5, 12), Math.imul('3', '7')]);
show('hypot', () => [Math.hypot(), Math.hypot(3, 4), Math.hypot(NaN, Infinity), Math.hypot(-Infinity, NaN), Math.hypot(-0), Math.hypot(-0, -0), Math.hypot(1, '2', [2]), Math.hypot(NaN, 1)]);
show('hypot extremes', () => [Math.hypot(1e200, 1e200), Math.hypot(1e-200, 1e-200), Math.hypot(3e200, 4e200)]);
show('sumPrecise', () => [Math.sumPrecise([0.1, 0.2]), Math.sumPrecise([1e20, 0.1, -1e20]), Math.sumPrecise([]), Math.sumPrecise([-0, -0]), Math.sumPrecise([-0, 0]), Math.sumPrecise([Infinity, -Infinity]), Math.sumPrecise([1e308, 1e308, -1e308]), Math.sumPrecise([1e308, 1e308]), Math.sumPrecise([1, 1e100, 1, -1e100]), Math.sumPrecise([0.1, 0.2, 0.3]), Math.sumPrecise([2 ** 53, 1, 1]), Math.sumPrecise(new Set([NaN, 1]))]);
show('sumPrecise subnormals', () => [Math.sumPrecise([5e-324, 5e-324]), Math.sumPrecise([5e-324, 5e-324, 5e-324]), 5e-324 + 5e-324]);
show('sumPrecise non-number', () => Math.sumPrecise([1, '2']));
show('sumPrecise closes iterator', () => { let closed = false; const it = {[Symbol.iterator]() { let i = 0; return {next() { return i++ ? {value: 'x', done: false} : {value: 1, done: false}; }, return() { closed = true; return {}; }}; }}; try { Math.sumPrecise(it); } catch (e) { return [e.message, closed]; } });
show('sumPrecise not iterable', () => Math.sumPrecise(5));
show('Math object', () => [Math[Symbol.toStringTag], typeof Math, Object.getPrototypeOf(Math) === Object.prototype, Math.max.length, Math.hypot.length, Math.sumPrecise.length]);
show('Math not callable', () => Math());
show('Math not constructible', () => new Math.max());
show('random shape', () => { const xs = Array.from({length: 50}, () => Math.random()); return [xs.every(x => typeof x === 'number' && x >= 0 && x < 1), new Set(xs).size > 40]; });
''')


def test_math_transcendental_rounded(run, workdir):
    """CATCHES: wrong formulas or swapped arguments in Math transcendental functions (atan2 order,
    log bases, hyperbolic/inverse functions) and wrong exact special values (signed zeros,
    infinities, NaN domains). Results are compared at 12 significant digits so libm last-bit
    differences between architectures do not matter."""
    check(run, workdir, "math_transcendental_rounded", r'''
const fns = ['sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh', 'asinh', 'acosh', 'atanh', 'exp', 'expm1', 'log', 'log1p', 'log2', 'log10', 'cbrt'];
const inputs = [0.5, 2, -0.75, 10];
for (const f of fns) console.log(f.padEnd(6), inputs.map(x => fmt(r12(Math[f](x)))).join(' '));
show('specials sin/cos/tan', () => [Math.sin(-0), Math.cos(0), Math.tan(-0), Math.sin(Infinity), Math.cos(NaN)]);
show('specials inverse', () => [Math.asin(-0), Math.acos(1), Math.acos(2), Math.asin(-1.5), Math.atan(-0), r12(Math.atan(Infinity))]);
show('specials hyperbolic', () => [Math.sinh(-0), Math.cosh(0), Math.tanh(Infinity), Math.tanh(-Infinity), Math.asinh(-0), Math.acosh(1), Math.acosh(0.5), Math.atanh(1), Math.atanh(-1), Math.atanh(-0), Math.sinh(-Infinity)]);
show('specials exp/log', () => [Math.exp(0), Math.exp(-Infinity), Math.exp(Infinity), Math.expm1(-0), Math.expm1(-Infinity), Math.log(1), Math.log(0), Math.log(-0), Math.log(-1), Math.log1p(-1), Math.log1p(-2), Math.log2(0), Math.log10(-0)]);
show('exact powers', () => [r12(Math.log2(8)), r12(Math.log10(1000)), r12(Math.log2(0.125)), r12(Math.cbrt(-27)), Math.cbrt(-0), Math.cbrt(-Infinity)]);
show('atan2 quadrants', () => [r12(Math.atan2(1, 1)), r12(Math.atan2(1, -1)), r12(Math.atan2(-1, -1)), r12(Math.atan2(-1, 1)), r12(Math.atan2(0, -0)), r12(Math.atan2(-0, -0)), Math.atan2(0, 0), Math.atan2(-0, 0), r12(Math.atan2(Infinity, -Infinity)), r12(Math.atan2(1, 0))]);
show('small arguments', () => [r12(Math.expm1(1e-10)), r12(Math.log1p(1e-10)), r12(Math.sinh(1e-10)), r12(Math.tanh(1e-10)), r12(Math.sin(1e-10))]);
show('fractional pow', () => [r12(2 ** 0.5), r12(Math.pow(10, -2.5)), r12(Math.pow(27, 1 / 3)), r12(Math.E ** Math.LN2)]);
show('constants', () => [Math.E, Math.PI, Math.LN2, Math.LN10, Math.LOG2E, Math.LOG10E, Math.SQRT2, Math.SQRT1_2].map(r12));
show('identities', () => [r12(Math.sin(Math.PI / 6)), r12(Math.cos(Math.PI)), r12(Math.tan(Math.PI / 4)), r12(Math.exp(Math.log(42))), r12(Math.cosh(1) ** 2 - Math.sinh(1) ** 2)]);
show('coercion', () => [r12(Math.sin('1')), Math.cos([]), Math.exp(null), Math.log(undefined), r12(Math.atan2('1', [1]))]);
''')


def test_bigint_arithmetic(run, workdir):
    """CATCHES: BigInt arithmetic with wrong signs for truncating division and remainder, wrong
    two's-complement semantics for shifts and bitwise ops on negative/huge values, arbitrary
    precision bugs in multiplication/exponentiation/factorials, and missing RangeErrors/TypeErrors
    (division by zero, negative exponent, >>>, unary +)."""
    check(run, workdir, "bigint_arithmetic", r'''
show('basic', () => [2n ** 100n, -7n / 2n, -7n % 2n, 7n % -2n, 7n / -2n, (-2n) ** 3n, 0n ** 0n, -(2n ** 64n), 5n - 10n]);
show('big multiply', () => [123456789012345678901234567890n * 987654321098765432109876543210n, (2n ** 4096n).toString().length, (3n ** 300n) % 1000000007n]);
show('big divide', () => { const a = 10n ** 50n + 12345n; const b = 10n ** 25n + 7n; return [a / b, a % b, (-a) / b, (-a) % b, a / -b, a % -b, (a / b) * b + a % b === a]; });
show('factorial', () => { let f = 1n; for (let i = 1n; i <= 50n; i++) f *= i; return [f, f.toString().length, f % 1000000007n, f / (10n ** 60n)]; });
show('fibonacci', () => { let a = 0n, b = 1n; for (let i = 0; i < 300; i++) [a, b] = [b, a + b]; return [a, a.toString(36)]; });
show('shifts', () => [1n << 100n, -1n >> 1000n, 5n >> 1n, -5n >> 1n, 5n << -1n, -5n << -1n, 255n >> 4n, (1n << 200n) >> 199n, -(1n << 70n) >> 3n, (-1n) << 64n, 12345678901234567890n >> 64n, -12345678901234567890n >> 64n]);
show('bitwise', () => [5n & 3n, 5n | 3n, 5n ^ 3n, ~5n, -5n & 0xffn, -1n ^ 0n, (-12n) | 5n, (2n ** 70n - 1n) & -(2n ** 35n), (-(2n ** 70n)) | 5n, (2n ** 64n) ^ -1n, ~(2n ** 64n), -12345678901234567890123n & 0xffffffffn]);
show('update ops', () => { let x = 2n ** 64n; x++; x--; x--; let y = 1n; y += 2n; y **= 2n; y <<= 3n; return [x, y, -y]; });
show('exponent edge', () => [(-2n) ** 0n, 0n ** 1n, 1n ** (2n ** 64n), (-1n) ** (2n ** 64n + 1n)]);
show('negative zero', () => [-0n, Object.is(0n, -0n), (-0n).toString(), 0n * -1n]);
show('division by zero', () => 1n / 0n);
show('modulo by zero', () => 1n % 0n);
show('negative exponent', () => 2n ** -1n);
show('unsigned shift', () => 1n >>> 1n);
show('unary plus', () => +1n);
show('mix number', () => 1n * 2);
show('mix undefined', () => 1n + undefined);
show('mix in compound', () => { let z = 1n; z += 1; });
show('string concat ok', () => [1n + 'x', `${2n}`, 'v' + -3n]);
''')


def test_bigint_conversions_and_comparisons(run, workdir):
    """CATCHES: BigInt() accepting non-integral numbers, decimals/separators/'n' suffixes in strings
    or rejecting whitespace and radix prefixes; asIntN/asUintN wrapping errors and index range
    checks; toString radix; Number(bigint) rounding; loose equality and relational comparisons
    between BigInt, Number and String; Set/Map key semantics for 0n/-0n."""
    check(run, workdir, "bigint_conversions_and_comparisons", r'''
show('BigInt()', () => [BigInt('0x1f'), BigInt('  -42  '), BigInt(''), BigInt(' '), BigInt('0b101'), BigInt('0o17'), BigInt('0X1F'), BigInt('+7'), BigInt('00012'), BigInt(true), BigInt(Number.MAX_SAFE_INTEGER), BigInt(1e21), BigInt(-0), BigInt('-0')]);
for (const s of ['1.5', '-0x10', '1n', '0x', '1_000', '1e3', '--1', '0b2', 'Infinity']) show('BigInt(' + JSON.stringify(s) + ')', () => BigInt(s));
show('BigInt(1.5)', () => BigInt(1.5));
show('BigInt(NaN)', () => BigInt(NaN));
show('BigInt(undefined)', () => BigInt(undefined));
show('BigInt(null)', () => BigInt(null));
show('BigInt(Symbol)', () => BigInt(Symbol()));
show('BigInt(object)', () => BigInt({valueOf() { return 12; }}));
show('new BigInt', () => new BigInt(1));
show('asIntN', () => [BigInt.asIntN(8, 255n), BigInt.asIntN(8, 128n), BigInt.asIntN(8, -129n), BigInt.asUintN(8, -1n), BigInt.asUintN(64, -1n), BigInt.asIntN(64, 2n ** 63n), BigInt.asIntN(0, 5n), BigInt.asUintN(1, 3n), BigInt.asIntN(1, 1n), BigInt.asUintN(200, -1n) === 2n ** 200n - 1n]);
show('asIntN wide', () => [BigInt.asIntN(64, 2n ** 64n + 5n), BigInt.asUintN(64, -(2n ** 64n) - 1n), BigInt.asIntN(65, 2n ** 64n), BigInt.asIntN(3, -5n), BigInt.asUintN(3, -5n), BigInt.asIntN('8', 200n), BigInt.asIntN(8, '257'), BigInt.asIntN(8, true)]);
show('asIntN negative bits', () => BigInt.asIntN(-1, 1n));
show('asUintN too many bits', () => BigInt.asUintN(2 ** 53, 1n));
show('asIntN huge width', () => [BigInt.asIntN(2 ** 30, 5n), BigInt.asUintN(2 ** 30, 5n), BigInt.asIntN(2 ** 30, -5n)]);
show('asUintN huge width negative', () => BigInt.asUintN(2 ** 30, -1n));
show('asIntN number value', () => BigInt.asIntN(8, 1));
show('asIntN bad string', () => BigInt.asIntN(8, 'x'));
show('toString radix', () => [(255n).toString(16), (-255n).toString(2), (2n ** 64n).toString(36), (0n).toString(7), (36n ** 10n - 1n).toString(36), (123n).toString(undefined), BigInt.prototype.toString.call(Object(7n), 2)]);
show('toString radix 1', () => (1n).toString(1));
show('toString bad receiver', () => BigInt.prototype.toString.call(7));
show('valueOf', () => [BigInt.prototype.valueOf.call(Object(5n)), typeof Object(1n), Object(1n) == 1n]);
show('valueOf bad receiver', () => BigInt.prototype.valueOf.call(5));
show('toLocaleString', () => [(1234567n).toLocaleString(), (-1234567890123456789n).toLocaleString('en-US'), (1234567n).toLocaleString('de-DE')]);
show('Number(bigint)', () => [Number(2n ** 64n), Number(-(2n ** 1024n)), parseInt('123n'), String(10n ** 21n)]);
show('loose equality', () => [1n == 1, 1n === 1, 1n == '1', 1n == 1.5, 0n == '', 1n == '0x1', 16n == '0x10', 1n == ' 1 ', 1n == '1n', 1n == '1e0', 0n == false, 1n == true, 2n == true]);
show('relational', () => [1n < 2, 2n > 1.5, 2n > '1', 10n < NaN, 1n < 'x', 1n < '0x2', 5n > '4.5', 2n ** 64n > Number.MAX_SAFE_INTEGER, -1n < -Infinity, 1n <= 1, 9007199254740993n > 9007199254740992]);
show('mixed sort', () => [10n, 9, 8.5, -1n, 0, 0n, 3n].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0)));
show('truthiness', () => [0n ? 't' : 'f', !0n, 1n && 'y', Boolean(-1n)]);
show('collections', () => [Object.is(0n, -0n), [0n].includes(-0n), new Set([0n, -0n, 0]).size, new Map([[1n, 'a']]).get(1n), [1n].indexOf(1)]);
show('as property key', () => { const o = {}; o[10n] = 'ten'; return [Object.keys(o), o['10'], o[10]]; });
show('BigInt statics', () => [BigInt.length, BigInt.name, Object.getOwnPropertyNames(BigInt.prototype).sort().join(' '), BigInt.prototype[Symbol.toStringTag]]);
''')


def test_boolean_and_wrapper_objects(run, workdir):
    """CATCHES: wrong ToBoolean for edge values (-0, NaN, '', 0n, objects, wrapper objects are always
    truthy), Boolean.prototype methods accepting non-Boolean receivers, Boolean.prototype being a
    Boolean object, wrapper objects for every primitive type and their loose equality, and
    Symbol/Number valueOf receiver checks."""
    check(run, workdir, "boolean_and_wrapper_objects", r"""
show('Boolean()', () => [Boolean(), Boolean(0), Boolean(-0), Boolean(NaN), Boolean(''), Boolean(' '), Boolean('false'), Boolean(null), Boolean(undefined), Boolean({}), Boolean([]), Boolean(0n), Boolean(1n), Boolean(Symbol())]);
show('new Boolean(false)', () => { const f = new Boolean(false); return [typeof f, !!f, f == false, f.valueOf(), String(f), JSON.stringify(f), Object.prototype.toString.call(f), f instanceof Boolean, f ? 'truthy' : 'falsy']; });
show('toString/valueOf', () => [true.toString(), false.valueOf(), Boolean.prototype.toString.call(new Boolean(true)), Boolean.prototype.valueOf(), Object.prototype.toString.call(Boolean.prototype)]);
show('toString bad receiver', () => Boolean.prototype.toString.call('true'));
show('valueOf bad receiver', () => Boolean.prototype.valueOf.call({}));
show('Boolean shape', () => [Boolean.length, Boolean.name, Object.getOwnPropertyNames(Boolean.prototype).sort().join(' ')]);
show('subclass', () => { class B extends Boolean {} const b = new B(0); return [b.valueOf(), b instanceof Boolean, B.name, Object.prototype.toString.call(b)]; });
show('Symbol valueOf bad receiver', () => Symbol.prototype.valueOf.call('x'));
show('Symbol valueOf boxed', () => typeof Symbol.prototype.valueOf.call(Object(Symbol('b'))));
show('Number valueOf boxed', () => [Number.prototype.valueOf.call(new Number(3)), Number.prototype.toString.call(Object(255), 16)]);
show('wrapper typeof', () => [typeof Object(true), typeof Object(1), typeof Object('s'), typeof Object(Symbol()), typeof Object(1n)]);
show('wrapper equality', () => [new Boolean(true) == true, new Number(1) == new Number(1), new String('a') == 'a', Object(1n) == 1n, new Boolean(false) === false]);
show('logical operators', () => [0 || 'a', '' ?? 'b', null ?? 'c', 1 && 0, !!'0', !![], NaN || null, document_undefined_check()]);
function document_undefined_check() { return typeof document; }
""")
