"""Hot code across execution tiers: real programs whose functions and loops run hot enough to tier
up (loop bodies compile on first call, other functions after a few calls) and exercise tricky
semantics inside the compiled code -- int32 overflow, -0/NaN, ToInt32/ToUint32, coercions, holes,
elements-kind and hidden-class changes, accessors/proxies, prototype mutation, exceptions,
closures, generators, collections, typed arrays, string scanners and labeled control flow.
Every program runs on the default JIT tier, --tier=bytecode and --tier=interp and must match ONE
shared golden, so any tier that diverges from the tree-walker is caught."""
import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)
TIERS = [pytest.param([], id="jit"), pytest.param(["--tier=bytecode"], id="bytecode"),
         pytest.param(["--tier=interp"], id="interp")]
tiers = pytest.mark.parametrize("cli", TIERS)


@tiers
def test_int32_overflow_and_bitwise(run, workdir, cli):
    """CATCHES: compiled int32 fast paths that wrap instead of overflowing into doubles (2147483647+1,
    65536*65536, ++/-- across the boundary), produce +0 instead of -0 (0*-1, -5%5,
    Math.round(-0.4)), apply ToInt32/ToUint32 wrongly to doubles >= 2^31, negative fractions,
    NaN/Infinity, strings and objects with valueOf, forget that shift counts are masked to 5
    bits, return a signed value from >>>, or miscompute
    Math.imul/FNV/CRC32/xorshift/popcount/sieve-bitset loops and BigInt bit ops."""
    check_script(run, workdir, G, "int32_overflow_and_bitwise", r'''
function addChain(n) { var x = 2147483640, out = []; for (var i = 0; i < n; i++) { x = x + 1; if (i >= 5) out.push(x); } return out.join(','); }
function subChain(n) { var x = -2147483640; for (var i = 0; i < n; i++) x--; return x + ' ' + (x | 0) + ' ' + (x >>> 0); }
function mulChain(n) { var x = 1, y = 3, s = []; for (var i = 0; i < n; i++) { x *= 2; y = y * y % 1000003; } s.push(x, y, 65536 * 65536, 46341 * 46341, -46341 * 46341); return s.join(','); }
function negs(list) { var out = []; for (var i = 0; i < list.length; i++) { var v = list[i]; var n = -v; out.push(Object.is(n, -0) ? '-0' : String(n)); } return out.join(','); }
function zeros(n) {
  var res = [];
  for (var i = 0; i < n; i++) {
    var a = 0 * -1, b = -0 + -0, c = -0 - 0, d = -5 % 5, e = 5 % -5, f = Math.round(-0.4), g = -1 / Infinity, h = Math.trunc(-0.5), k = (-3) * 0;
    if (i === n - 1) res = [a, b, c, d, e, f, g, h, k].map(function (z) { return Object.is(z, -0) ? '-0' : String(z); });
  }
  return res.join(',');
}
function divs(n) { var s = 0, out = []; for (var i = 1; i <= n; i++) { s += 7 / i; if (i <= 4) out.push(7 / i, -7 / i, 7 % i, -7 % i); } return out.join(',') + ' ' + s.toFixed(10); }
function imul(n) { var h = 0x811c9dc5, h2 = 0; for (var i = 0; i < n; i++) { h ^= i & 0xff; h = Math.imul(h, 0x01000193); h2 = (h2 * 31 + i) | 0; } return (h >>> 0) + ' ' + h + ' ' + h2; }
function incs() {
  var a = 2147483646, b = -2147483647, c = 4294967294, out = [];
  for (var i = 0; i < 3; i++) { out.push(a++, ++b, c++); b -= 2; }
  out.push(a, b, c, a | 0, b | 0, c | 0, c >>> 0, ~~(c + 1));
  return out.join(',');
}
function mixed(n) { var x = 0; for (var i = 0; i < n; i++) { x += i % 3 === 0 ? 0.5 : i % 3 === 1 ? 2147483647 : -2147483648; } return x; }
function accum(n) { var s = 0; for (var i = 0; i < n; i++) s += i * i * i; return s + ' ' + (s | 0) + ' ' + (s > 2 ** 53) + ' ' + Number.isSafeInteger(s); }
var r = [];
for (var k = 0; k < 3; k++) r = [addChain(10), subChain(20), mulChain(40), negs([0, -0, 2147483648, -2147483648, 1, -1, NaN, Infinity]), zeros(500), divs(1000), imul(5000), incs(), mixed(3001), accum(100000)];
console.log(r.join('\n'));
function conv(list) { var out = []; for (var i = 0; i < list.length; i++) { var v = list[i]; out.push((v | 0) + '/' + (v >>> 0) + '/' + (~v) + '/' + (v >> 1) + '/' + (v << 1)); } return out.join(' '); }
var inputs = [2147483648, 4294967295, 4294967296, -1, -1.9, 1.9, -2147483649, NaN, Infinity, -Infinity, 1e21, -0, '12', '0x1f', ' 7 ', 'x', true, null, undefined, { valueOf: function () { return 6; } }, [3], 2 ** 53 + 2];
var c;
for (var k = 0; k < 100; k++) c = conv(inputs);
console.log(c);
function shifts() { var out = []; var counts = [0, 1, 31, 32, 33, -1, 64, 1.5, '2', NaN]; for (var i = 0; i < counts.length; i++) { var s = counts[i]; out.push((1 << s) + ',' + (-8 >> s) + ',' + (-8 >>> s) + ',' + (0x80000000 >> s)); } return out.join(' '); }
var sh;
for (var k = 0; k < 100; k++) sh = shifts();
console.log(sh);
function popcount(x) { x = x - ((x >>> 1) & 0x55555555); x = (x & 0x33333333) + ((x >>> 2) & 0x33333333); return (((x + (x >>> 4)) & 0x0F0F0F0F) * 0x01010101) >>> 24; }
function crcTable() { var t = []; for (var n = 0; n < 256; n++) { var c = n; for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; }
var table = crcTable();
function crc32(str) { var crc = -1; for (var i = 0; i < str.length; i++) crc = (crc >>> 8) ^ table[(crc ^ str.charCodeAt(i)) & 0xFF]; return (crc ^ -1) >>> 0; }
function xorshift(seed, n) { var x = seed | 0, out = 0; for (var i = 0; i < n; i++) { x ^= x << 13; x ^= x >> 17; x ^= x << 5; out = (out + (x >>> 0) % 1000) | 0; } return out + ':' + x; }
var pc = 0;
for (var i = 0; i < 5000; i++) pc += popcount(i * 2654435761);
console.log(pc, popcount(-1), popcount(0x80000000), crc32('The quick brown fox jumps over the lazy dog'), crc32(''), crc32('é中'), xorshift(2463534242, 10000), xorshift(1, 3));
function bitsets(n) { var words = new Array(Math.ceil(n / 32)).fill(0); for (var i = 2; i < n; i++) words[i >>> 5] |= 1 << (i & 31); for (var p = 2; p * p < n; p++) if (words[p >>> 5] & (1 << (p & 31))) for (var q = p * p; q < n; q += p) words[q >>> 5] &= ~(1 << (q & 31)); var count = 0; for (var w = 0; w < words.length; w++) count += popcount(words[w]); return count + ' ' + words[0] + ' ' + (words[0] >>> 0) + ' ' + words[words.length - 1]; }
console.log('sieve', bitsets(10000), bitsets(64));
function rotl(x, r) { return (x << r) | (x >>> (32 - r)); }
function mix(n) { var a = 0x9e3779b9 | 0, b = 0; for (var i = 0; i < n; i++) { a = rotl(a ^ i, 7) + b | 0; b = (b ^ a) >>> 3; } return a + ',' + b + ',' + (a & 0xffff) + ',' + (a ^ b).toString(16) + ',' + (b >>> 0).toString(2).length; }
console.log('mix', mix(10000), rotl(1, 31), rotl(-1, 4), rotl(0x12345678, 0));
function bigbits(n) { var x = 0n; for (var i = 0n; i < n; i++) x = (x << 3n) ^ (i * 0x9e3779b97f4a7c15n) & ((1n << 64n) - 1n); return BigInt.asUintN(64, x).toString(16) + ' ' + BigInt.asIntN(32, x) + ' ' + (x >> 200n) + ' ' + (-x >> 3n === -(x >> 3n)); }
console.log('bigint bits', bigbits(100n));
''', cli=cli)


@tiers
def test_array_elements_kinds(run, workdir, cli):
    """CATCHES: hot array loops specialised for one elements kind that break when the array changes
    shape mid-loop (int -> double -> object -> holey -> dictionary/sparse), read holes as 0
    instead of undefined or ignore Array.prototype elements, mishandle out-of-
    bounds/negative/string indices, length truncation and growth during iteration, or array
    methods (push/pop/splice/sort) in loops."""
    check_script(run, workdir, G, "array_elements_kinds", r'''
function sum(a) { var s = 0; for (var i = 0; i < a.length; i++) s += a[i]; return s; }
function describe(a) { var t = []; for (var i = 0; i < a.length; i++) t.push(i in a ? typeof a[i] : 'hole'); return t.join(''); }
var a = [];
for (var i = 0; i < 1000; i++) a.push(i);
var out = [sum(a)];
a[500] = 0.5; out.push(sum(a));
a[501] = 'x'; var sx = sum(a); out.push(typeof sx, sx.length, sx.slice(0, 12));
a[501] = { valueOf: function () { return 1; } }; out.push(sum(a));
a.length = 10; out.push(sum(a), a.length);
a[20] = 1; out.push(sum(a), describe(a).slice(8));
a[1e6] = 2; out.push(a.length, a.filter(function () { return true; }).length);
console.log('transitions', out.join(','));
function oob(a, n) { var u = 0, s = 0; for (var i = -2; i < n; i++) { var v = a[i]; if (v === undefined) u++; else s += v; } return u + ':' + s; }
var base = [1, 2, 3];
var o2 = [oob(base, 6)];
Array.prototype[4] = 100; o2.push(oob(base, 6), 4 in base, base.hasOwnProperty(4));
delete Array.prototype[4]; o2.push(oob(base, 6));
Object.prototype[-1] = 7; o2.push(oob(base, 3)); delete Object.prototype[-1];
var holey = [1, , 3, , 5];
o2.push(oob(holey, 5), describe(holey), holey.indexOf(undefined), holey.includes(undefined), holey.findIndex(function (x) { return x === undefined; }));
console.log('holes', o2.join(','));
function growWhileLooping(a) { var steps = 0; for (var i = 0; i < a.length; i++) { steps++; if (a[i] % 2 === 0 && a.length < 50) a.push(a[i] + 1, a[i] + 3); } return steps + ':' + a.length + ':' + a.slice(-4).join('|'); }
function shrinkWhileLooping(a) { var seen = []; for (var i = 0; i < a.length; i++) { seen.push(a[i]); if (a[i] === 3) a.length = 5; if (a[i] === 4) a.splice(0, 2); } return seen.join('') + ':' + a.join(''); }
console.log('mutating', growWhileLooping([0, 2]), shrinkWhileLooping([1, 2, 3, 4, 5, 6, 7, 8]));
function doubles(n) { var d = []; for (var i = 0; i < n; i++) d.push(i / 4); var s = 0; for (var j = 0; j < d.length; j++) s += d[j] * d[j]; d[3] = NaN; d[5] = -0; var nan = 0, negz = 0; for (var j = 0; j < d.length; j++) { if (d[j] !== d[j]) nan++; if (Object.is(d[j], -0)) negz++; } return s + ':' + nan + ':' + negz + ':' + d.indexOf(NaN) + ':' + d.includes(NaN) + ':' + d.indexOf(-0); }
console.log('doubles', doubles(2000));
function stack(n) { var st = []; var total = 0; for (var i = 0; i < n; i++) { st.push(i); if (i % 3 === 2) total += st.pop() * st.pop(); } return total + ':' + st.length + ':' + st.slice(0, 5).join(','); }
function queue(n) { var q = [], out = 0; for (var i = 0; i < n; i++) { q.push(i); if (q.length > 7) out += q.shift(); } q.unshift(-1, -2); return out + ':' + q.join(','); }
console.log('stack/queue', stack(3000), queue(3000));
function sortedChecks(n) { var arr = []; var x = 12345; for (var i = 0; i < n; i++) { x = (x * 1103515245 + 12345) & 0x7fffffff; arr.push(x % 1000 - 500); } var lex = arr.slice(0, 12).sort().join(','); arr.sort(function (p, q) { return p - q; }); var ok = true; for (var i = 1; i < arr.length; i++) if (arr[i - 1] > arr[i]) ok = false; return ok + ':' + arr[0] + ':' + arr[arr.length - 1] + ':' + arr[n >> 1] + ' ' + lex; }
console.log('sort', sortedChecks(5000));
var mixedSort = [3, undefined, 'b', , 10, null, 'a', 2, NaN, -0, 0];
console.log('mixed sort', JSON.stringify(mixedSort.slice().sort()), mixedSort.slice().sort().length, String([, 1, , 2].sort()));
function objects(n) { var list = []; for (var i = 0; i < n; i++) list.push({ id: i, tag: i % 3 === 0 ? 'fizz' : i % 5 === 0 ? 'buzz' : null }); var counts = {}; for (var j = 0; j < list.length; j++) { var t = list[j].tag; counts[t] = (counts[t] || 0) + 1; } list[7] = 7; list[8] = undefined; var bad = 0; for (var j = 0; j < list.length; j++) { var it = list[j]; if (!it || typeof it !== 'object') bad++; } return JSON.stringify(counts) + ' bad=' + bad; }
console.log('objects', objects(3000));
function arrayLike() { var al = { length: 3, 0: 'a', 2: 'c' }; var r = []; for (var k = 0; k < 50; k++) r = [Array.prototype.join.call(al, '-'), Array.from(al).length, Array.prototype.map.call(al, function (x) { return x + x; }).length, String(Array.prototype.slice.call('hey'))]; return r.join(' '); }
console.log('array-like', arrayLike());
''', cli=cli)


@tiers
def test_property_caches_and_prototypes(run, workdir, cli):
    """CATCHES: hot property/method caches that miss hidden-class or prototype changes after warm-up:
    properties added in different orders, deleted and re-added, turned into accessors or non-
    writable, dictionary-mode objects, getters/setters and Proxy traps (exact call counts),
    frozen/sealed objects, class prototype methods replaced or deleted, Object.setPrototypeOf on
    instances and intermediate prototypes, Object.prototype/Array.prototype additions,
    Symbol.hasInstance and super lookups after the home object's prototype changes."""
    check_script(run, workdir, G, "property_caches_and_prototypes", r'''
function readXY(o) { return o.x * 10 + o.y; }
function loopRead(list) { var s = 0; for (var i = 0; i < list.length; i++) s += readXY(list[i]); return s; }
var list = [];
for (var i = 0; i < 500; i++) {
  var o;
  switch (i % 5) {
    case 0: o = { x: 1, y: 2 }; break;
    case 1: o = { y: 2, x: 1 }; break;
    case 2: o = { z: 0, x: 1, y: 2 }; break;
    case 3: o = { x: 0, y: 2 }; delete o.x; o.x = 1; break;
    case 4: o = Object.create({ x: 1 }); o.y = 2; break;
  }
  list.push(o);
}
var r = [loopRead(list)];
var gets = 0;
Object.defineProperty(list[3], 'x', { get: function () { gets++; return 5; } });
r.push(loopRead(list), gets);
Object.getPrototypeOf(list[4]).x = 3; r.push(loopRead(list));
Object.defineProperty(list[0], 'y', { value: 100, writable: false });
list[0].y = 0; r.push(loopRead(list), list[0].y);
for (var k = 0; k < 100; k++) list[10]['p' + k] = k;
for (var k = 0; k < 100; k += 2) delete list[10]['p' + k];
r.push(loopRead(list), Object.keys(list[10]).length);
console.log('shapes', r.join(','));
function Temp(c) { this._c = c; this.reads = 0; this.writes = 0; }
Object.defineProperty(Temp.prototype, 'f', { get: function () { this.reads++; return this._c * 9 / 5 + 32; }, set: function (v) { this.writes++; this._c = (v - 32) * 5 / 9; } });
function convert(t, n) { var s = 0; for (var i = 0; i < n; i++) { s += t.f; t.f = t.f + 1.8; } return s.toFixed(4) + ' ' + t.reads + ' ' + t.writes + ' ' + t._c.toFixed(4); }
console.log('accessors', convert(new Temp(0), 1000));
var log = [];
var handler = {
  get: function (t, k, rcv) { log.push('get:' + String(k)); return Reflect.get(t, k, rcv); },
  set: function (t, k, v, rcv) { log.push('set:' + String(k)); return Reflect.set(t, k, v, rcv); },
  has: function (t, k) { log.push('has:' + String(k)); return k in t; },
  deleteProperty: function (t, k) { log.push('del:' + String(k)); return delete t[k]; },
};
function useProxy(p, n) { var s = 0; for (var i = 0; i < n; i++) { if ('a' in p) s += p.a; p.b = i; if (i === n - 1) delete p.a; } return s + ':' + p.b + ':' + ('a' in p); }
var px = new Proxy({ a: 3 }, handler);
console.log('proxy', useProxy(px, 300), log.length, log.slice(0, 4).join(' '), log.slice(-3).join(' '));
var revocable = Proxy.revocable({ v: 1 }, {});
function readV(p) { return p.v; }
var rv = 0;
for (var i = 0; i < 100; i++) rv += readV(revocable.proxy);
revocable.revoke();
try { readV(revocable.proxy); } catch (e) { console.log('revoked', rv, e.name); }
function freezeAfterWarm() {
  var obj = { count: 0 }, res = [];
  function bump(o) { o.count++; return o.count; }
  for (var i = 0; i < 300; i++) bump(obj);
  Object.freeze(obj); res.push(bump(obj));
  var sealed = Object.seal({ count: 1 }); bump(sealed); sealed.extra = 1; delete sealed.count;
  res.push(sealed.count, sealed.extra, Object.isSealed(sealed));
  var ne = Object.preventExtensions({ count: 5 }); bump(ne); ne.z = 1; res.push(ne.count, ne.z);
  return res.join(',');
}
console.log('integrity', freezeAfterWarm());
function protoShadow() {
  var proto = { kind: 'proto' }, objs = [];
  for (var i = 0; i < 10; i++) objs.push(Object.create(proto));
  function kinds() { var s = ''; for (var i = 0; i < objs.length; i++) s += objs[i].kind[0]; return s; }
  var res = [kinds()];
  objs[3].kind = 'own'; res.push(kinds());
  Object.defineProperty(proto, 'kind', { writable: false, value: 'ro' });
  objs[4].kind = 'try'; res.push(kinds(), objs[4].hasOwnProperty('kind'));
  Object.defineProperty(proto, 'kind', { get: function () { return this === objs[5] ? 'five' : 'getter'; } });
  res.push(kinds());
  return res.join(' ');
}
console.log('prototype', protoShadow());
class A { who() { return 'A'; } get tag() { return 'tagA'; } }
class B extends A { who() { return 'B>' + super.who(); } }
class C extends B { }
function callAll(list) { var s = ''; for (var i = 0; i < list.length; i++) s += list[i].who() + ',' + list[i].tag + ';'; return s; }
var objs = [new A(), new B(), new C()];
var w = '';
for (var i = 0; i < 300; i++) w = callAll(objs);
var out = [w];
A.prototype.who = function () { return 'A2'; }; out.push(callAll(objs));
delete B.prototype.who; out.push(callAll(objs));
Object.setPrototypeOf(C.prototype, A.prototype); out.push(callAll(objs));
Object.defineProperty(A.prototype, 'tag', { get: function () { return 'getter-' + this.constructor.name; }, configurable: true }); out.push(callAll(objs));
Object.setPrototypeOf(objs[0], { who: function () { return 'adopted'; }, tag: 'plain' }); out.push(callAll(objs));
console.log(out.join('\n'));
function hasLength(list) { var c = 0; for (var i = 0; i < list.length; i++) if (list[i].extra !== undefined) c++; return c; }
var plain = [];
for (var i = 0; i < 200; i++) plain.push({ i: i });
var hr = [hasLength(plain)];
Object.prototype.extra = 1; hr.push(hasLength(plain), [].extra, (5).extra);
delete Object.prototype.extra; hr.push(hasLength(plain));
Array.prototype.sum = function () { var s = 0; for (var i = 0; i < this.length; i++) s += this[i]; return s; };
var arrs = [];
for (var i = 0; i < 100; i++) arrs.push([i, i + 1]);
var as = 0;
for (var i = 0; i < arrs.length; i++) as += arrs[i].sum();
hr.push(as, Object.keys([1]).length);
var forInKeys = []; for (var k in [7]) forInKeys.push(k);
hr.push(forInKeys.join('|'));
delete Array.prototype.sum;
console.log('globals', hr.join(','));
function check(list, Ctor) { var c = 0; for (var i = 0; i < list.length; i++) if (list[i] instanceof Ctor) c++; return c; }
function Animal() { } function Dog() { }
Dog.prototype = Object.create(Animal.prototype);
var zoo = [];
for (var i = 0; i < 300; i++) zoo.push(i % 3 ? new Dog() : new Animal());
var ir = [check(zoo, Animal), check(zoo, Dog)];
Dog.prototype = {}; ir.push(check(zoo, Dog), check(zoo, Animal));
Object.defineProperty(Animal, Symbol.hasInstance, { value: function (v) { return typeof v === 'object' && v !== null && 'length' in v; } });
ir.push(check(zoo, Animal), check([[], 'str', { length: 0 }], Animal));
var bound = Animal.bind(null);
ir.push(check([new bound()], Animal));
try { check(zoo, {}); } catch (e) { ir.push(e.name); }
console.log('instanceof', ir.join(','));
var base1 = { greet() { return 'base1'; } }, base2 = { greet() { return 'base2'; } };
var mid = { __proto__: base1, greet() { return 'mid>' + super.greet(); } };
var leaf = { __proto__: mid };
var sr = [];
for (var i = 0; i < 300; i++) sr[0] = leaf.greet();
Object.setPrototypeOf(mid, base2); sr.push(leaf.greet());
var detachedGreet = mid.greet; sr.push(detachedGreet.call({}));
Object.setPrototypeOf(leaf, base1); sr.push(leaf.greet());
console.log('super', sr.join(','));
function chainDepth(o) { var d = 0; while (o) { o = Object.getPrototypeOf(o); d++; } return d; }
var deep = {};
for (var i = 0; i < 50; i++) deep = Object.create(deep);
deep.constructor;
console.log('chain', chainDepth(deep), chainDepth(Object.create(null)), chainDepth([]), chainDepth(function () { }), chainDepth(new C()));
try { Object.setPrototypeOf(A.prototype, objs[2]); } catch (e) { console.log('cycle', e.name); }
console.log('frozen proto', (function () { var fp = Object.freeze({ m: 1 }); var o = Object.create(fp); o.m = 2; return o.m + ':' + Object.keys(o).length; })(), Reflect.setPrototypeOf(Object.preventExtensions({}), {}));
''', cli=cli)


@tiers
def test_exceptions_in_hot_code(run, workdir, cli):
    """CATCHES: compiled exception handling that loses loop state when throwing from hot code: wrong
    catch/finally ordering, finally that fails to override a return/break/continue, catch
    bindings leaking or shared across iterations, rethrow from nested handlers, errors thrown by
    builtins and by getters/valueOf inside the loop, primitive throws, or exceptions escaping
    through several compiled frames; the exact messages and counters must match the tree-walker."""
    check_script(run, workdir, G, "exceptions_in_hot_code", r'''
function parseAll(list) {
  var ok = 0, bad = [], fin = 0;
  for (var i = 0; i < list.length; i++) {
    try { var v = JSON.parse(list[i]); if (typeof v !== 'number') throw new TypeError('not a number: ' + list[i]); ok += v; }
    catch (e) { if (bad.length < 4) bad.push(e.name + '(' + e.message.slice(0, 24) + ')'); }
    finally { fin++; }
  }
  return ok + ' ' + fin + ' ' + bad.join(' ');
}
var inputs = [];
for (var i = 0; i < 600; i++) inputs.push(i % 7 === 0 ? '{bad' : i % 11 === 0 ? '"str"' : String(i));
console.log(parseAll(inputs));
function finallyFlow(n) {
  var log = [];
  for (var i = 0; i < n; i++) {
    try {
      if (i === 1) continue;
      if (i === 3) break;
      log.push('t' + i);
    } finally {
      log.push('f' + i);
    }
  }
  return log.join('');
}
function finallyOverride() { for (var i = 0; i < 3; i++) { try { return 'try' + i; } finally { if (i === 0) continue; } } return 'loop end'; }
function finallyReturn() { try { throw new Error('lost'); } finally { return 'finally wins'; } }
function nested(i) {
  try {
    try { if (i % 3 === 0) throw i; if (i % 3 === 1) null.f; return 'none'; }
    catch (e) { if (typeof e === 'number') throw new RangeError('re' + e); return 'inner:' + e.name; }
    finally { if (i === 7) return 'finally7'; }
  } catch (outer) { return 'outer:' + outer.message; }
}
var nr = [];
for (var i = 0; i < 300; i++) nr[i % 9] = nested(i);
console.log(finallyFlow(6), finallyOverride(), finallyReturn(), nr.join(','));
function depth3(x) { if (x > 250) throw { code: x }; return x; }
function depth2(x) { return depth3(x) + 1; }
function depth1(x) { return depth2(x) * 2; }
function driver(n) { var s = 0, caught = []; for (var i = 0; i < n; i++) { try { s += depth1(i); } catch (e) { caught.push(e.code); } } return s + ' ' + caught.length + ' ' + caught[0] + ' ' + caught[caught.length - 1]; }
console.log('frames', driver(300));
function builtinErrors() {
  var msgs = [];
  var cases = [
    function () { return [].reduce(function (a, b) { return a + b; }); },
    function () { return new Array(-1); },
    function () { return (1).toFixed(101); },
    function () { return 'abc'.repeat(-1); },
    function () { return BigInt(1.5); },
    function () { return Symbol() + ''; },
    function () { return JSON.parse('{"a":}'); },
    function () { return decodeURIComponent('%'); },
    function () { var o = {}; o.self = o; return JSON.stringify(o); },
    function () { return Object.defineProperty(Object.freeze({}), 'x', { value: 1 }); },
    function () { return new (function () { }.bind())().x.y; },
    function () { return 1n / 0n; },
  ];
  for (var k = 0; k < 20; k++) for (var i = 0; i < cases.length; i++) { try { cases[i](); msgs[i] = 'no error'; } catch (e) { msgs[i] = e.name + ': ' + e.message; } }
  return msgs.join('\n');
}
console.log(builtinErrors());
function throwingValueOf(n) { var count = 0, s = 0; var bomb = { valueOf: function () { count++; if (count % 50 === 0) throw new Error('bomb' + count); return 1; } }; for (var i = 0; i < n; i++) { try { s += bomb * 2; } catch (e) { s -= 1000; } } return s + ':' + count; }
console.log('valueOf throws', throwingValueOf(500));
function catchScope(n) { var fns = []; for (var i = 0; i < n; i++) { try { throw i * i; } catch (sq) { fns.push(function () { return sq; }); } } var e = 'outer'; try { throw 'x'; } catch (e) { e = 'reassigned'; } return fns.map(function (f) { return f(); }).join(',') + ' ' + e; }
console.log('catch scope', catchScope(6));
function optionalCatch(n) { var c = 0; for (var i = 0; i < n; i++) { try { if (i & 1) throw 0; } catch { c++; } } return c; }
console.log('optional binding', optionalCatch(1001));
function errorProps() { var e = new Error('m', { cause: 'c' }); var t = new TypeError(); var agg = new AggregateError([1, 2], 'agg'); return [e.cause, t.message === '', agg.errors.length, agg.name, e instanceof Error, Object.prototype.toString.call(e), String(new RangeError('r'))].join(','); }
console.log(errorProps());
''', cli=cli)


@tiers
def test_generators_in_loops(run, workdir, cli):
    """CATCHES: generator/iterator handling in hot loops that loses generator state between next()
    calls, ignores values passed to next(v), does not run finally blocks on early break
    (return()), mishandles gen.throw()/gen.return() mid-iteration, yield* delegation (including
    to arrays and strings), infinite generators bounded by take(), or spreads/destructures
    generators wrongly."""
    check_script(run, workdir, G, "generators_in_loops", r'''
function* range(start, end, step) { for (var i = start; i < end; i += step) yield i; }
function* take(it, n) { var k = 0; if (n <= 0) return; for (var v of it) { yield v; if (++k >= n) return; } }
function* naturals() { var n = 0; while (true) yield n++; }
function* mapGen(it, f) { for (var v of it) yield f(v); }
function* filterGen(it, p) { for (var v of it) if (p(v)) yield v; }
function sumIter(it) { var s = 0; for (var v of it) s += v; return s; }
var r = [sumIter(range(0, 10000, 3)), sumIter(take(naturals(), 1000)), [...take(filterGen(mapGen(naturals(), function (x) { return x * x; }), function (x) { return x % 3 === 1; }), 8)].join(',')];
console.log('pipelines', r.join(' '));
var log = [];
function* guarded(n) { try { for (var i = 0; i < n; i++) yield i; } finally { log.push('cleanup@' + i); } }
function firstOver(limit) { for (var v of guarded(100)) if (v > limit) return v; return -1; }
var fo = 0;
for (var i = 0; i < 200; i++) fo += firstOver(i % 10);
console.log('early exit', fo, log.length, log.slice(0, 3).join(','), log[log.length - 1]);
function* accumulator() { var total = 0, v; while (true) { v = yield total; if (v === undefined) break; total += v; } return 'final:' + total; }
function drive(n) { var g = accumulator(); g.next(); var last; for (var i = 1; i <= n; i++) last = g.next(i).value; var end = g.next(); return last + ' ' + end.value + ' ' + end.done + ' ' + JSON.stringify(g.next()); }
console.log('send values', drive(1000), drive(1));
function* resilient() { var errors = 0; while (true) { try { yield errors; } catch (e) { errors++; if (e === 'stop') return 'stopped after ' + errors; } } }
function hammer(n) { var g = resilient(); g.next(); var v; for (var i = 0; i < n; i++) v = g.throw(new Error('e' + i)).value; var stop = g.throw('stop'); var after; try { g.throw('again'); } catch (e) { after = 'rethrown ' + e; } return v + ' ' + stop.value + ' ' + stop.done + ' ' + after; }
console.log('throw()', hammer(500));
function* withReturn() { try { yield 1; yield 2; } finally { yield 'from finally'; } }
var wr = withReturn(); var wrs = [wr.next().value, JSON.stringify(wr.return('R')), JSON.stringify(wr.next()), JSON.stringify(wr.next())];
console.log('return()', wrs.join(' '));
function* inner() { var x = yield 'i1'; yield 'got ' + x; return 'inner-result'; }
function* outer() { var res = yield* inner(); yield res; yield* [10, 20]; yield* 'ab'; return 'done'; }
function collect(g) { var out = [], step = g.next(); var k = 0; while (!step.done) { out.push(step.value); step = g.next('v' + k++); } out.push('=' + step.value); return out.join(','); }
var dc;
for (var i = 0; i < 100; i++) dc = collect(outer());
console.log('delegation', dc);
function* fib() { var a = 0, b = 1; while (true) { yield a; var t = a + b; a = b; b = t; } }
var [f0, f1, , f3, ...rest] = take(fib(), 10);
var fibs = [];
for (var v of fib()) { if (v > 1e15) break; fibs.push(v); }
console.log('destructure', f0, f1, f3, rest.join(','), fibs.length, fibs[fibs.length - 1]);
class Tree { constructor(v, l, r) { this.v = v; this.l = l; this.r = r; } *[Symbol.iterator]() { if (this.l) yield* this.l; yield this.v; if (this.r) yield* this.r; } }
function build(lo, hi) { if (lo > hi) return null; var mid = (lo + hi) >> 1; return new Tree(mid, build(lo, mid - 1), build(mid + 1, hi)); }
var tree = build(1, 300), inorder = [...tree];
var okOrder = inorder.every(function (v, i) { return v === i + 1; });
console.log('tree', inorder.length, okOrder, sumIter(tree), Math.max(...tree));
var genProto = Object.getPrototypeOf(range(0, 1, 1));
console.log('protocol', typeof genProto.next, range(0, 1, 1)[Symbol.iterator]() instanceof range, Object.prototype.toString.call(range(0, 1, 1)), String(Array.from({ length: 3 }, function (_, i) { return i * 2; })));
''', cli=cli)


@tiers
def test_string_scanners(run, workdir, cli):
    """CATCHES: hot string code that mishandles charCodeAt/codePointAt out of range (NaN/undefined),
    surrogate pairs and lone surrogates, indexes by bytes instead of UTF-16 units, builds
    strings with += incorrectly (ropes/flattening), coerces numbers to strings with the wrong
    formatting (exponents, -0, large/small doubles), or mis-tokenises in a charCodeAt-driven
    lexer."""
    check_script(run, workdir, G, "string_scanners", r'''
function tokenize(src) {
  var tokens = [], i = 0, n = src.length;
  while (i < n) {
    var c = src.charCodeAt(i);
    if (c === 32 || c === 10 || c === 9) { i++; continue; }
    if (c >= 48 && c <= 57) { var j = i; while (j < n && ((src.charCodeAt(j) >= 48 && src.charCodeAt(j) <= 57) || src.charCodeAt(j) === 46)) j++; tokens.push('num:' + src.slice(i, j)); i = j; continue; }
    if ((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 95 || c > 127) { var k = i; while (k < n) { var d = src.charCodeAt(k); if ((d >= 65 && d <= 90) || (d >= 97 && d <= 122) || d === 95 || (d >= 48 && d <= 57) || d > 127) k++; else break; } tokens.push('id:' + src.slice(i, k)); i = k; continue; }
    if (c === 34) { var e = i + 1, s = ''; while (e < n && src.charCodeAt(e) !== 34) { if (src.charCodeAt(e) === 92) { e++; s += src[e] === 'n' ? '\n' : src[e]; } else s += src[e]; e++; } tokens.push('str:' + JSON.stringify(s)); i = e + 1; continue; }
    var two = src.substr(i, 2);
    if (two === '==' || two === '<=' || two === '>=' || two === '=>' || two === '&&') { tokens.push('op:' + two); i += 2; continue; }
    tokens.push('op:' + src[i]); i++;
  }
  return tokens;
}
var program = 'let x_1 = 42.5 + y*(3-1);\nif (x_1 >= 10 && ok) { print("a\\"b\\n", café, π) } => done';
var toks;
for (var k = 0; k < 100; k++) toks = tokenize(program);
console.log(toks.length, toks.join(' '));
function codes(s) { var out = []; for (var i = -1; i <= s.length; i++) out.push(s.charCodeAt(i) + '/' + s.codePointAt(i) + '/' + JSON.stringify(s[i]) + '/' + JSON.stringify(s.at(i))); return out.join(' '); }
var cs;
for (var k = 0; k < 100; k++) cs = codes('a\u{1F600}\uD800z');
console.log(cs);
function countCodePoints(s) { var n = 0; for (var i = 0; i < s.length; i++) { var c = s.charCodeAt(i); if (c >= 0xD800 && c <= 0xDBFF && i + 1 < s.length) { var d = s.charCodeAt(i + 1); if (d >= 0xDC00 && d <= 0xDFFF) i++; } n++; } return n; }
var emoji = '', ascii = '';
for (var i = 0; i < 500; i++) { emoji += String.fromCodePoint(0x1F600 + (i % 50)) + (i % 7 === 0 ? '\uDC00' : 'x'); ascii += String.fromCharCode(97 + (i % 26)); }
console.log(emoji.length, countCodePoints(emoji), [...emoji].length, Array.from(emoji.slice(0, 8)).join('|'), ascii.length, ascii.slice(-5), ascii.lastIndexOf('z'), ascii.split('a').length);
function forOfString(s) { var counts = {}; for (var ch of s) counts[ch] = (counts[ch] || 0) + 1; return Object.keys(counts).length + ':' + counts['x'] + ':' + counts['\u{1F601}']; }
console.log('for-of string', forOfString(emoji));
function numberStrings() { var vals = [0, -0, 1e21, 1e-7, 123456789012345680000, 0.1 + 0.2, -1e-7, 2 ** 53, 1 / 3, 100, 1.5e300 * 1e10, -Infinity, 5e-324, 0.000001, 1e20, 255]; var out = []; for (var k = 0; k < 50; k++) { out = []; for (var i = 0; i < vals.length; i++) out.push('' + vals[i] + '|' + vals[i].toString(16).slice(0, 12) + '|' + vals[i].toFixed(2).slice(0, 25)); } return out.join(' '); }
console.log(numberStrings());
function caesar(s, shift) { var out = ''; for (var i = 0; i < s.length; i++) { var c = s.charCodeAt(i); if (c >= 97 && c <= 122) out += String.fromCharCode((c - 97 + shift + 26) % 26 + 97); else if (c >= 65 && c <= 90) out += String.fromCharCode((c - 65 + shift + 26) % 26 + 65); else out += s[i]; } return out; }
var msg = 'Hello, World! The quick brown fox.';
var enc = msg;
for (var r = 0; r < 26; r++) enc = caesar(enc, 7);
console.log(caesar(msg, 3), caesar(caesar(msg, 3), -3) === msg, enc === msg);
function builders(n) { var a = '', b = [], c = ''; for (var i = 0; i < n; i++) { a += i; b.push(i); c = i + c; } return a.length + ' ' + (a === b.join('')) + ' ' + c.slice(0, 10) + ' ' + a.slice(-10); }
console.log('build', builders(3000));
function parseCsv(text) { var rows = [], row = [], field = '', q = false; for (var i = 0; i < text.length; i++) { var ch = text[i]; if (q) { if (ch === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; } else field += ch; } else if (ch === '"') q = true; else if (ch === ',') { row.push(field); field = ''; } else if (ch === '\n') { row.push(field); rows.push(row); row = []; field = ''; } else field += ch; } if (field || row.length) { row.push(field); rows.push(row); } return rows; }
var csv = 'name,qty,note\n"Smith, J",3,"said ""hi"""\nDoe,,\n"multi\nline",7,end';
var rows;
for (var k = 0; k < 100; k++) rows = parseCsv(csv);
console.log(JSON.stringify(rows));
function caseOps() { var s = 'İstanbul ß ǅ ΣΑΣ', out; for (var k = 0; k < 50; k++) out = [s.toUpperCase(), s.toLowerCase(), 'abc'.localeCompare('abd'), 'a'.padStart(4, 'xy'), 'trim me  '.trimEnd() + '|', 'x'.repeat(3), 'a-b-c'.replaceAll('-', '+'), 'Mississippi'.split('ss').join('|'), 'abc'.normalize('NFD') === 'abc']; return out.join(' '); }
console.log(caseOps());
''', cli=cli)


@tiers
def test_typed_arrays(run, workdir, cli):
    """CATCHES: compiled typed-array element access that skips the per-type conversions: Uint8 wrap,
    Int8/Int16 sign wrap, Uint8Clamped round-half-to-even and NaN->0, Float32 rounding (fround),
    Int32/Uint32 views of the same buffer, out-of-bounds writes being dropped and reads
    returning undefined, subarray aliasing, DataView endianness, BigInt64 wrap, or numeric keys
    like '-0'/1.5."""
    check_script(run, workdir, G, "typed_arrays", r'''
function fill(ta, n) { for (var i = 0; i < n; i++) ta[i] = i * 37 - 300; return ta; }
function checksum(ta) { var s = 0; for (var i = 0; i < ta.length; i++) s = (s * 31 + ta[i]) % 1000000007; return s; }
var kinds = [Int8Array, Uint8Array, Uint8ClampedArray, Int16Array, Uint16Array, Int32Array, Uint32Array, Float32Array, Float64Array];
var lines = [];
for (var k = 0; k < kinds.length; k++) { var ta = fill(new kinds[k](64), 64); lines.push(kinds[k].name + ':' + checksum(ta) + ':' + ta[0] + ',' + ta[1] + ',' + ta[9] + ',' + ta[63]); }
console.log(lines.join(' '));
function clamp(vals) { var c = new Uint8ClampedArray(vals.length); for (var i = 0; i < vals.length; i++) c[i] = vals[i]; return Array.from(c).join(','); }
console.log('clamped', clamp([0.5, 1.5, 2.5, 3.5, -1, 255.5, 254.5, 300, NaN, Infinity, -Infinity, '7', null, 127.49999]));
function froundLoop(n) { var f = new Float32Array(1), s = 0; for (var i = 0; i < n; i++) { f[0] = i / 10; s += f[0]; } return s + ' ' + (f[0] === Math.fround(f[0])) + ' ' + Math.fround(0.1) + ' ' + f[0]; }
console.log('float32', froundLoop(1000));
var buf = new ArrayBuffer(16), u8 = new Uint8Array(buf), i32 = new Int32Array(buf), u32 = new Uint32Array(buf), f64 = new Float64Array(buf), dv = new DataView(buf);
for (var i = 0; i < 16; i++) u8[i] = 0xF0 + i;
console.log('views', i32[0], u32[0], i32[3], u32[3], f64[0], dv.getInt32(0), dv.getInt32(0, true), dv.getUint16(1), dv.getFloat32(4, true));
dv.setFloat64(0, -0); dv.setInt16(8, -2, true); dv.setUint32(12, 0xDEADBEEF);
console.log('dataview', Object.is(f64[0], -0), u8.slice(0, 2).join(','), u8.slice(8, 10).join(','), u32[3].toString(16), dv.getBigInt64(8).toString(16), dv.getBigUint64(8, true));
function oob(ta) { var res = []; ta[ta.length] = 99; ta[-1] = 5; ta['-0'] = 6; ta[1.5] = 7; ta['01'] = 8; res.push(ta[ta.length], ta[-1], ta['-0'], ta[1.5], ta['01'], Object.keys(ta).join('/'), ta.length); return res.join(','); }
console.log('oob', oob(new Int16Array(3)), oob(new Float64Array(0)));
function aliasing() { var whole = new Int32Array(10); for (var i = 0; i < 10; i++) whole[i] = i; var sub = whole.subarray(3, 7); for (var j = 0; j < sub.length; j++) sub[j] *= -1; var copy = whole.slice(2, 5); copy[0] = 1000; whole.copyWithin(0, 6); whole.set([77, 88], 8); return whole.join(',') + ' | ' + sub.join(',') + ' | ' + copy.join(',') + ' ' + sub.byteOffset + ' ' + (sub.buffer === whole.buffer); }
console.log('aliasing', aliasing());
function bigint64() { var b = new BigInt64Array(4), u = new BigUint64Array(b.buffer); b[0] = 2n ** 63n; b[1] = -1n; b[2] = 2n ** 64n + 5n; for (var i = 0; i < 100; i++) b[3] += 3n; var err = ''; try { b[0] = 1; } catch (e) { err = e.name; } return b.join(',') + ' ' + u.join(',') + ' ' + err; }
console.log('bigint64', bigint64());
function histogram(n) { var data = new Uint8Array(n), hist = new Uint32Array(16); var x = 7; for (var i = 0; i < n; i++) { x = (x * 1664525 + 1013904223) >>> 0; data[i] = x >>> 24; } for (var i = 0; i < n; i++) hist[data[i] >> 4]++; var sorted = data.slice().sort(); return Array.from(hist).join(',') + ' ' + sorted[0] + ' ' + sorted[n - 1] + ' ' + sorted[n >> 1] + ' ' + data.reduce(function (a, b) { return a + b; }, 0); }
console.log('histogram', histogram(20000));
function methods() { var f = new Float64Array([3, -1, NaN, -0, 0, 2.5, Infinity]); var sorted = f.slice().sort(); return [Array.from(sorted).map(function (v) { return Object.is(v, -0) ? '-0' : v; }).join(','), f.indexOf(NaN), f.includes(NaN), f.indexOf(-0), f.lastIndexOf(0), f.map(function (v) { return v * 2; }).join(','), Int8Array.from([127, 128, 129, -129]).join(','), new Uint16Array([1, 2, 3]).reverse().join(''), Float32Array.of(1.1)[0]].join(' '); }
console.log('methods', methods());
function detach() { var b = new ArrayBuffer(8), v = new Uint8Array(b); v[0] = 1; var t = b.transfer ? b.transfer(16) : null; return t ? [v.length, v[0], b.byteLength, t.byteLength, new Uint8Array(t)[0], b.detached].join(',') : 'no transfer'; }
console.log('transfer', detach());
''', cli=cli)


@tiers
def test_calls_arguments_recursion(run, workdir, cli):
    """CATCHES: hot call paths that mis-handle argument count mismatches (missing -> undefined, extra
    visible only via arguments), sloppy arguments aliasing, Function.prototype.call/apply/bind
    with odd receivers and array-likes, bound-function partial args and new on bound functions,
    default and rest parameters, deep/mutual recursion results, tail-position calls, or
    fn.length/name."""
    check_script(run, workdir, G, "calls_arguments_recursion", r'''
function argsInfo(a, b) { return arguments.length + ':' + a + ':' + b + ':' + (arguments[2] === undefined ? '-' : arguments[2]); }
function alias(a) { a = a + 1; arguments[0] = arguments[0] * 10; return a; }
function sumAll() { var s = 0; for (var i = 0; i < arguments.length; i++) s += arguments[i]; return s; }
var r = [];
for (var i = 0; i < 300; i++) { r[0] = argsInfo(i); r[1] = argsInfo(1, 2, 3); r[2] = alias(i); r[3] = sumAll(1, 2, 3, i); r[4] = sumAll(); }
r.push(argsInfo.length, sumAll.length, (function (a, b = 1, c) { }).length, (function (...z) { }).length);
console.log('arguments', r.join(' '));
var obj = { base: 100, add: function (x, y) { return this.base + x + (y || 0); } };
var bound = obj.add.bind({ base: 1 }, 10), bound2 = bound.bind({ base: 999 }, 20);
var br = [];
for (var i = 0; i < 300; i++) { br[0] = obj.add.call({ base: i }, 1); br[1] = obj.add.apply({ base: 2 }, [3, 4]); br[2] = bound(5); br[3] = bound2(); br[4] = obj.add.apply(obj, { length: 2, 0: 1, 1: 2 }); }
br.push(bound.name, bound2.name, bound.length, bound2.length);
function Pt(x, y) { this.x = x; this.y = y; }
var BoundPt = Pt.bind(null, 7), p = new BoundPt(8);
br.push(p.x + ',' + p.y, p instanceof Pt, p instanceof BoundPt);
try { obj.add.apply(obj, 5); } catch (e) { br.push(e.name); }
br.push(Math.max.apply(null, [1, 9, 3]), Math.min.call(null), String.prototype.toUpperCase.call(true), Array.prototype.concat.call(1, 2).length);
console.log('call/apply/bind', br.join(' '));
function fib(n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
function ack(m, n) { return m === 0 ? n + 1 : n === 0 ? ack(m - 1, 1) : ack(m - 1, ack(m, n - 1)); }
function isEven(n) { return n === 0 ? true : isOdd(n - 1); }
function isOdd(n) { return n === 0 ? false : isEven(n - 1); }
function hanoi(n, from, to, via, moves) { if (n === 0) return moves; hanoi(n - 1, from, via, to, moves); moves.push(from + to); return hanoi(n - 1, via, to, from, moves); }
function deep(n) { return n === 0 ? 0 : 1 + deep(n - 1); }
function permutations(arr) { if (arr.length <= 1) return [arr]; var out = []; for (var i = 0; i < arr.length; i++) { var rest = arr.slice(0, i).concat(arr.slice(i + 1)); var ps = permutations(rest); for (var j = 0; j < ps.length; j++) out.push([arr[i]].concat(ps[j])); } return out; }
var hm = hanoi(10, 'A', 'C', 'B', []);
var perms = permutations([1, 2, 3, 4, 5]);
console.log('recursion', fib(18), ack(2, 3), ack(1, 20), isEven(40), isOdd(37), hm.length, hm.slice(0, 5).join(','), deep(40), perms.length, perms[77].join(''));
function variadic(first, ...rest) { return first + '|' + rest.length + '|' + rest.reduce(function (a, b) { return a + b; }, 0); }
function withDefaults(a, b = a * 2, c = b + 1) { return [a, b, c].join(','); }
var vr = [];
for (var i = 0; i < 300; i++) { vr[0] = variadic(i, 1, 2, 3); vr[1] = withDefaults(i); vr[2] = withDefaults(1, undefined, null); }
vr.push(variadic(), withDefaults(), variadic.apply(null, new Array(5).fill(2)));
console.log('rest/defaults', vr.join(' '));
function poly(f, x) { return f(x); }
var fns = [Math.abs, Math.floor, function (v) { return v * 2; }, (v) => -v, String, Number.isInteger, parseInt, Boolean.prototype.valueOf.bind(true)];
var pr = [];
for (var i = 0; i < 400; i++) pr[i % fns.length] = poly(fns[i % fns.length], -(i % 7) - 0.5);
console.log('polymorphic targets', pr.join(','));
function curry(fn) { return function c() { var args = Array.prototype.slice.call(arguments); return args.length >= fn.length ? fn.apply(this, args) : function () { return c.apply(this, args.concat(Array.prototype.slice.call(arguments))); }; }; }
var add3 = curry(function (a, b, c) { return a + b + c; }), cs = 0;
for (var i = 0; i < 500; i++) cs += add3(i)(1)(2) + add3(i, 1)(2) + add3(i, 1, 2);
console.log('curry', cs);
function tailCount(n, acc) { if (n === 0) return acc; return tailCount(n - 1, acc + 1); }
console.log('tail position', tailCount(40, 0), (function () { return typeof arguments.callee; })(), (function () { 'use strict'; try { return arguments.callee; } catch (e) { return e.name; } })());
''', cli=cli)


@tiers
def test_collections_in_loops(run, workdir, cli):
    """CATCHES: Map/Set/WeakMap code in hot loops that hashes keys incorrectly (objects vs strings vs
    numbers, 1 vs '1', NaN, -0), loses insertion order on update/delete/re-add, visits entries
    wrongly when the collection is mutated during for-of/forEach (deleted entries skipped, added
    ones visited), or mis-implements graph algorithms (BFS/topological sort/LRU) built on them."""
    check_script(run, workdir, G, "collections_in_loops", r'''
function graph(n) {
  var adj = new Map();
  for (var i = 0; i < n; i++) adj.set(i, []);
  for (var i = 0; i < n; i++) { adj.get(i).push((i * 7 + 3) % n); adj.get(i).push((i * 13 + 5) % n); if (i % 3 === 0) adj.get(i).push((i + 1) % n); }
  var dist = new Map([[0, 0]]), queue = [0], head = 0;
  while (head < queue.length) { var u = queue[head++]; for (var v of adj.get(u)) if (!dist.has(v)) { dist.set(v, dist.get(u) + 1); queue.push(v); } }
  var maxd = 0, sum = 0; dist.forEach(function (d) { if (d > maxd) maxd = d; sum += d; });
  return dist.size + ' ' + maxd + ' ' + sum + ' ' + [...dist.keys()].slice(0, 8).join(',');
}
console.log('bfs', graph(500), graph(7));
function topo(edges) {
  var indeg = new Map(), out = new Map();
  for (var [a, b] of edges) { if (!indeg.has(a)) indeg.set(a, 0); indeg.set(b, (indeg.get(b) || 0) + 1); if (!out.has(a)) out.set(a, new Set()); out.get(a).add(b); }
  var ready = [...indeg].filter(function (e) { return e[1] === 0; }).map(function (e) { return e[0]; }).sort(), order = [];
  while (ready.length) { var x = ready.shift(); order.push(x); for (var y of out.get(x) || []) { indeg.set(y, indeg.get(y) - 1); if (indeg.get(y) === 0) { ready.push(y); ready.sort(); } } }
  return order.length === indeg.size ? order.join('') : 'cycle';
}
console.log('topo', topo([['a', 'b'], ['b', 'c'], ['a', 'd'], ['d', 'c'], ['e', 'a'], ['c', 'f']]), topo([['x', 'y'], ['y', 'x']]));
function LRU(cap) { this.cap = cap; this.map = new Map(); this.evicted = 0; }
LRU.prototype.get = function (k) { if (!this.map.has(k)) return -1; var v = this.map.get(k); this.map.delete(k); this.map.set(k, v); return v; };
LRU.prototype.put = function (k, v) { if (this.map.has(k)) this.map.delete(k); else if (this.map.size >= this.cap) { this.map.delete(this.map.keys().next().value); this.evicted++; } this.map.set(k, v); };
var lru = new LRU(30), hits = 0;
for (var i = 0; i < 20000; i++) { var key = (i * i + (i >> 6)) % 97; if (lru.get(key) !== -1) hits++; else lru.put(key, i); }
console.log('lru', hits, lru.evicted, lru.map.size, [...lru.map.keys()].slice(0, 6).join(','));
function mutateDuringIteration() {
  var m = new Map([[1, 'a'], [2, 'b'], [3, 'c']]), seen = [];
  for (var [k, v] of m) { seen.push(k + v); if (k === 1) { m.delete(2); m.set(4, 'd'); } if (k === 3) m.set(1, 'A'); if (k === 4) { m.delete(1); m.set(1, 'z'); } if (seen.length > 10) break; }
  var s = new Set([1, 2, 3]), ss = [];
  s.forEach(function (x) { ss.push(x); if (x < 6) s.add(x + 3); if (x === 2) s.delete(3); });
  var cleared = new Map([[1, 1], [2, 2]]), cs = [];
  for (var e of cleared) { cs.push(e[0]); cleared.clear(); if (e[0] !== 9) cleared.set(9, 9); }
  return seen.join(',') + ' | ' + ss.join(',') + ' | ' + cs.join(',') + ' | ' + [...m.values()].join('');
}
console.log('mutation', mutateDuringIteration());
function keyKinds(n) {
  var m = new Map(), objKey = {}, arrKey = [1], fnKey = function () { };
  for (var i = 0; i < n; i++) { m.set(i % 10, (m.get(i % 10) || 0) + 1); m.set(String(i % 10), (m.get(String(i % 10)) || 0) + 2); m.set(objKey, i); m.set(i % 2 ? NaN : 0 / 0, i); m.set(i % 2 ? 0 : -0, -i); }
  m.set(arrKey, 'arr'); m.set(fnKey, 'fn'); m.set([1], 'other arr');
  return m.size + ' ' + m.get(3) + ' ' + m.get('3') + ' ' + m.get(objKey) + ' ' + m.get(NaN) + ' ' + m.get(-0) + ' ' + m.get(arrKey) + ' ' + m.get([1]) + ' ' + [...m.keys()].slice(0, 4).map(String).join(',');
}
console.log('keys', keyKinds(1000));
function weak() { var wm = new WeakMap(), ws = new WeakSet(), keys = []; for (var i = 0; i < 300; i++) { var k = { i: i }; keys.push(k); wm.set(k, i * 2); if (i % 3 === 0) ws.add(k); } var s = 0, c = 0; for (var j = 0; j < keys.length; j++) { s += wm.get(keys[j]); if (ws.has(keys[j])) c++; } var err = []; try { wm.set(1, 1); } catch (e) { err.push(e.name); } try { ws.add('s'); } catch (e) { err.push(e.name); } return s + ' ' + c + ' ' + wm.has({}) + ' ' + err.join(','); }
console.log('weak', weak());
function setAlgebra() { var a = new Set(), b = new Set(); for (var i = 0; i < 100; i++) { if (i % 2 === 0) a.add(i); if (i % 3 === 0) b.add(i); } var inter = [...a].filter(function (x) { return b.has(x); }), uni = new Set([...a, ...b]), diff = [...a].filter(function (x) { return !b.has(x); }); return inter.length + ' ' + uni.size + ' ' + diff.length + ' ' + inter.slice(0, 5).join(','); }
console.log('set algebra', setAlgebra());
function groupBy() { var data = []; for (var i = 0; i < 50; i++) data.push({ n: i, kind: ['a', 'b', 'c'][i % 3] }); var g = Map.groupBy(data, function (d) { return d.kind; }); var o = Object.groupBy(data, function (d) { return d.n % 2 ? 'odd' : 'even'; }); return [...g.keys()].join('') + ' ' + g.get('b').length + ' ' + Object.keys(o).join(',') + ' ' + o.odd.length; }
console.log('groupBy', groupBy());
''', cli=cli)


@tiers
def test_labeled_control_flow(run, workdir, cli):
    """CATCHES: compiled loops that mis-route labeled break/continue across nested for/while/do-while/
    for-in/for-of/switch, skip finally blocks when a labeled jump leaves a try, re-run or skip
    the update clause, break out of labeled plain blocks incorrectly, or leave iterators
    unclosed when a labeled continue exits an inner for-of."""
    check_script(run, workdir, G, "labeled_control_flow", r'''
function findPair(arr, target) {
  var res = 'none';
  search: for (var i = 0; i < arr.length; i++) {
    for (var j = i + 1; j < arr.length; j++) {
      if (arr[i] + arr[j] > target * 2) continue search;
      if (arr[i] + arr[j] === target) { res = i + ',' + j; break search; }
    }
  }
  return res + '@' + i;
}
var nums = [];
for (var k = 0; k < 300; k++) nums.push((k * 37) % 101);
console.log('pair', findPair(nums, 150), findPair(nums, 1000), findPair([1, 2], 3));
function primes(limit) { var out = []; outer: for (var n = 2; out.length < limit; n++) { for (var d = 2; d * d <= n; d++) if (n % d === 0) continue outer; out.push(n); } return out.length + ' ' + out[out.length - 1] + ' ' + out.slice(0, 10).join(','); }
console.log('primes', primes(1000));
function withFinally(n) {
  var log = [];
  outer: for (var i = 0; i < n; i++) {
    inner: for (var j = 0; j < n; j++) {
      try {
        if (j === 1) continue inner;
        if (j === 2) continue outer;
        if (i === 2) break outer;
        log.push(i + '' + j);
      } finally { log.push('f'); }
    }
  }
  return log.join(' ');
}
console.log('finally', withFinally(4));
function blocks(x) { var r = ''; a: { r += 'a'; b: { r += 'b'; if (x === 1) break b; if (x === 2) break a; r += 'c'; } r += 'd'; } return r + 'e'; }
var br = [];
for (var k = 0; k < 300; k++) br[k % 3] = blocks(k % 3);
console.log('blocks', br.join(' '));
function doWhileLabels(n) { var c = 0, i = 0; outer: do { var j = 0; while (true) { j++; if (j > 3 && i > 150) break outer; if ((i + j) % 4 === 0) break; c += j; } c += 100; i++; } while (i < n); return c + ':' + i; }
console.log('do-while', doWhileLabels(200), doWhileLabels(1));
function mixedLoops(obj, list) {
  var out = [];
  keys: for (var k in obj) {
    for (var v of list) {
      switch (v) {
        case 'skip-key': continue keys;
        case 'stop': break keys;
        case 'next': continue;
        default: out.push(k + v);
      }
    }
  }
  return out.join(',');
}
var mr;
for (var k = 0; k < 100; k++) mr = [mixedLoops({ a: 1, b: 2, c: 3 }, ['x', 'next', 'y']), mixedLoops({ a: 1, b: 2 }, ['x', 'skip-key', 'y']), mixedLoops({ a: 1, b: 2 }, ['x', 'stop'])];
console.log('mixed', mr.join(' | '));
var closes = 0;
function closing() { var i = 0; return { [Symbol.iterator]: function () { return this; }, next: function () { return { value: i++, done: i > 5 }; }, return: function () { closes++; return {}; } }; }
function labeledOf(n) { var s = 0; outer: for (var a = 0; a < n; a++) { for (var v of closing()) { if (v === 2) continue outer; s += v; } } return s; }
console.log('iterator close', labeledOf(300), closes);
function matrixSearch(m, x) { var r = -1, c = -1; rows: for (var i = 0; i < m.length; i++) { if (m[i][0] > x) break; for (var j = 0; j < m[i].length; j++) { if (m[i][j] === x) { r = i; c = j; break rows; } if (m[i][j] > x) continue rows; } } return r + ',' + c; }
var mat = [];
for (var i = 0; i < 40; i++) { var row = []; for (var j = 0; j < 40; j++) row.push(i * 40 + j * 2); mat.push(row); }
var ms = [];
for (var q = 0; q < 200; q++) ms[q % 4] = matrixSearch(mat, [78, 79, 1600, 0][q % 4]);
console.log('matrix', ms.join(' '));
function whileUpdate(n) { var count = 0; for (var i = 0, j = n; i < j; i++, j--) { if (i % 3 === 0) continue; count += j - i; } var k = 0; while (k < n) { k += 3; if (k % 5 === 0) continue; count++; } return count + ':' + k; }
console.log('updates', whileUpdate(1000), whileUpdate(0));
''', cli=cli)


@tiers
def test_destructuring_in_loops(run, workdir, cli):
    """CATCHES: destructuring inside hot loops that mis-applies defaults (only for undefined, not
    null), evaluates default initialisers when not needed, mishandles holes/rest elements/nested
    patterns, computed keys and object rest (must copy own enumerable props, skip the named
    ones), Map entry destructuring in for-of heads, swaps via [a, b] = [b, a], or throws the
    wrong TypeError for null."""
    check_script(run, workdir, G, "destructuring_in_loops", r'''
var inits = 0;
function def(v) { inits++; return v; }
function points(list) {
  var sx = 0, sy = 0, names = [];
  for (var { x, y = def(0), meta: { name = 'anon' } = {} } of list) { sx += x; sy += y; names.push(name); }
  return sx + ',' + sy + ',' + names.slice(0, 4).join('/');
}
var pts = [];
for (var i = 0; i < 500; i++) pts.push(i % 4 === 0 ? { x: i } : i % 4 === 1 ? { x: i, y: null, meta: { name: 'n' + i } } : i % 4 === 2 ? { x: i, y: undefined, meta: {} } : { x: i, y: -i, meta: { name: undefined } });
console.log('object heads', points(pts), inits);
function entries(m) { var out = []; for (var [k, { v = 'd', ...others }] of m) out.push(k + '=' + v + '+' + Object.keys(others).join('')); return out.join(' '); }
var m = new Map([['a', { v: 1, p: 2, q: 3 }], ['b', {}], ['c', { q: 9, v: undefined }]]);
var er;
for (var i = 0; i < 200; i++) er = entries(m);
console.log('map entries', er);
function arrays(rows) {
  var acc = [];
  for (var [first, , third = 'T', ...rest] of rows) acc.push(first + ':' + third + ':' + rest.length);
  return acc.join(' ');
}
var ar;
for (var i = 0; i < 200; i++) ar = arrays([[1, 2, 3, 4, 5], [1], [], [, , null], 'xyzw', new Set([7, 8, 9, 10])]);
console.log('array heads', ar);
function nested(data) { var total = 0; for (var i = 0; i < data.length; i++) { var { a: [p, { q = 10 } = {}] = [], b: { c: [, d = 4] = [] } = {} } = data[i]; total += (p || 0) + q + d; } return total; }
var nd = [];
for (var i = 0; i < 300; i++) nd.push(i % 3 ? { a: [i, { q: 1 }], b: { c: [0, 2] } } : {});
console.log('nested', nested(nd));
function computed(objs, key) { var s = []; for (var o of objs) { var { [key]: v = '?', [key + '2']: w = '!', ...rest } = o; s.push(v + w + Object.keys(rest).length); } return s.join(','); }
var cr;
for (var i = 0; i < 200; i++) cr = computed([{ k: 1, k2: 2, z: 3 }, { k: 0 }, { other: 1, k2: null }, Object.create({ k: 'proto' })], 'k');
console.log('computed', cr);
function swaps(n) { var a = 1, b = 2, c = 3; for (var i = 0; i < n; i++) { [a, b, c] = [c, a, b]; if (i % 7 === 0) [a, c] = [c, a]; } return [a, b, c].join(''); }
function fibPairs(n) { var [x, y] = [0, 1]; for (var i = 0; i < n; i++) [x, y] = [y, (x + y) % 1000007]; return x; }
console.log('swaps', swaps(1000), swaps(1), fibPairs(5000));
function params({ a = 1, b: { c } = { c: 2 } } = {}, [d, e = d * 2] = [5], ...[f, g]) { return [a, c, d, e, f, g].join(','); }
var pr = [];
for (var i = 0; i < 300; i++) pr[0] = params({ a: i, b: { c: i } }, [1], 7, 8);
pr.push(params(), params({}, [], 1), params(undefined, [undefined, 0]));
console.log('param patterns', pr.join(' | '));
function failures() {
  var res = [];
  var cases = [function () { var { x } = null; }, function () { var [y] = {}; }, function () { var { z: { w } } = { z: undefined }; }, function () { for (var [k] of [1]) { } }, function () { var [a] = undefined; }];
  for (var r = 0; r < 20; r++) for (var i = 0; i < cases.length; i++) { try { cases[i](); res[i] = 'ok'; } catch (e) { res[i] = e.name; } }
  return res.join(',');
}
console.log('errors', failures());
function getterOrder() { var log = []; var src = { get a() { log.push('a'); return 1; }, get b() { log.push('b'); return undefined; } }; for (var i = 0; i < 3; i++) { var { b = (log.push('default-b'), 2), a } = src; } return log.join(','); }
console.log('evaluation order', getterOrder());
function capturedAssign(n) {
  var lo = 0, hi = 1, rest, tag = '';
  var step = function (k) { [lo, hi] = [hi, (lo + hi) % 1009]; ({ a: lo = lo, ...rest } = { b: k, c: k * 2 }); return lo; };
  var label = function (k) { return ((s, v) => s.raw[0] + v)`L${k}`; };
  var t = 0;
  for (var i = 0; i < n; i++) { t += step(i); tag = label(i); }
  return t + ':' + lo + ':' + hi + ':' + JSON.stringify(rest) + ':' + tag;
}
console.log('captured destructuring', capturedAssign(500), capturedAssign(1));
''', cli=cli)


@tiers
def test_coercions_in_hot_loops(run, workdir, cli):
    """CATCHES: hot arithmetic/comparison code that short-cuts JS coercions: + with strings vs numbers,
    ToPrimitive order (Symbol.toPrimitive, then valueOf, then toString) with the right hint and
    call counts, loose equality (null == undefined, '' == 0, [] == false, objects ==
    primitives), relational comparison of strings vs numbers, ToNumber of odd strings ('0x1f', '
    12 ', '1e3', '-0', ''), Date/array/object string conversion, and exceptions thrown from
    conversion hooks."""
    check_script(run, workdir, G, "coercions_in_hot_loops", r'''
function toNum(list) { var out = []; for (var i = 0; i < list.length; i++) { var v = list[i]; var n = +v; out.push(Object.is(n, -0) ? '-0' : String(n)); } return out.join(','); }
var strs = ['', ' ', '12', ' 12 ', '0x1f', '0b101', '0o17', '1e3', '-0', '+5', '1_000', '12px', 'Infinity', '-Infinity', 'infinity', '.5', '5.', '0x', null, undefined, true, false, [], [7], [1, 2], {}, '\n\t42\r\n', '1n'];
var tn;
for (var k = 0; k < 100; k++) tn = toNum(strs);
console.log('ToNumber', tn);
var calls = [];
var prim = { [Symbol.toPrimitive]: function (hint) { calls.push(hint); return hint === 'number' ? 42 : hint === 'string' ? 'str' : 'dflt'; } };
var vo = { valueOf: function () { calls.push('valueOf'); return 7; }, toString: function () { calls.push('toString'); return 'ts'; } };
var onlyTs = { valueOf: function () { calls.push('valueOf-obj'); return {}; }, toString: function () { calls.push('toString2'); return '3'; } };
function mix(n) { var r; for (var i = 0; i < n; i++) r = [prim + 1, prim * 2, `${prim}`, prim == 'dflt', vo + 1, `${vo}`, vo * 2, vo > 6, onlyTs * 2, onlyTs + 1, String(vo), [vo] + '']; return r.join('|'); }
var mx = mix(200);
console.log('ToPrimitive', mx, calls.length, calls.slice(0, 14).join(','));
function looseEq(pairs) { var s = ''; for (var i = 0; i < pairs.length; i++) s += pairs[i][0] == pairs[i][1] ? 'T' : 'F'; return s; }
var eqPairs = [[null, undefined], [null, 0], [undefined, 0], ['', 0], ['0', false], [[], false], [[], ''], [[0], false], [[1], 1], [[1, 2], '1,2'], [{}, '[object Object]'], [NaN, NaN], ['1e3', 1000], [1n, 1], [1n, '1'], [0n, false], [Symbol.iterator, Symbol.iterator], [new String('a'), 'a'], [new String('a'), new String('a')], [true, '1'], [2, true], ['\t', 0]];
var le;
for (var k = 0; k < 100; k++) le = looseEq(eqPairs);
console.log('loose equality', le);
function relational(pairs) { var s = ''; for (var i = 0; i < pairs.length; i++) { var a = pairs[i][0], b = pairs[i][1]; s += (a < b ? '<' : '') + (a > b ? '>' : '') + (a <= b ? 'l' : '') + (a >= b ? 'g' : '') + ' '; } return s; }
var relPairs = [['10', '9'], ['10', 9], ['a', 'B'], ['abc', 'abd'], ['', 'a'], [null, 0], [undefined, 0], ['x', 1], [[2], 10], [true, false], [1n, 1.5], ['2', 1n], [-0, 0], ['é', 'z'], ['Z', 'a']];
var rr;
for (var k = 0; k < 100; k++) rr = relational(relPairs);
console.log('relational', rr);
function concatLoop(n) { var s = '', t = 0; for (var i = 0; i < n; i++) { s = i % 2 ? s + i : i + s; t = t + '1' - 1; } return s.length + ':' + s.slice(0, 8) + ':' + typeof t + ':' + t; }
console.log('concat', concatLoop(500), 1 + 2 + '3' + 4 + 5, '3' - '1' + '1', '3' * '4', true + true + '1', [] + [], [] + {}, [1] + [2], null + 1, undefined + 1, 'a' * 1);
function dates() { var out = []; for (var k = 0; k < 50; k++) { var d = new Date(Date.UTC(2020, 1, 29, 12, 30, 15, 250)); out = [d.getTime(), +d, d - 0, d + 0 === d.toString() + '0', d.toISOString(), JSON.stringify(d), d.getUTCDay(), new Date(0).toISOString(), new Date(8.64e15 + 1).getTime(), String(new Date(NaN))]; } return out.join(' '); }
console.log('dates', dates());
var thrower = { valueOf: function () { throw new Error('no convert'); } };
function guarded(n) { var errs = 0, ok = 0; for (var i = 0; i < n; i++) { try { var v = i % 10 === 0 ? thrower * 1 : i * 1; ok += v; } catch (e) { errs++; } } return errs + ':' + ok; }
console.log('throwing hooks', guarded(1000));
try { Symbol() * 1; } catch (e) { console.log(e.name + ': ' + e.message); }
try { ({ [Symbol.toPrimitive]: function () { return {}; } }) + 1; } catch (e) { console.log(e.name + ': ' + e.message); }
try { Object.create(null) + ''; } catch (e) { console.log(e.name + ': ' + e.message); }
''', cli=cli)


@tiers
def test_numeric_kernels(run, workdir, cli):
    """CATCHES: miscompiled numeric kernels (nested loops over plain arrays and Float64Arrays): matrix
    multiply, Mandelbrot escape counts, Game of Life generations with wrap-around indexing, an
    n-body integrator (sqrt and floating-point accumulation order), Gauss-Seidel style stencil
    updates, and integer LCG/modular exponentiation where results must be bit-identical to the
    tree-walker."""
    check_script(run, workdir, G, "numeric_kernels", r'''
function matmul(a, b, n) { var c = []; for (var i = 0; i < n; i++) { var row = []; for (var j = 0; j < n; j++) { var s = 0; for (var k = 0; k < n; k++) s += a[i][k] * b[k][j]; row.push(s); } c.push(row); } return c; }
var n = 16, A = [], B = [];
for (var i = 0; i < n; i++) { A.push([]); B.push([]); for (var j = 0; j < n; j++) { A[i].push((i * 3 + j) % 7 - 3); B[i].push((i + j * 5) % 11 / 4); } }
var C = matmul(A, B, n), tr = 0, cs = 0;
for (var i = 0; i < n; i++) { tr += C[i][i]; for (var j = 0; j < n; j++) cs += C[i][j] * (i + 1) * (j + 2); }
console.log('matmul', tr, cs, C[3][7], C[n - 1][0]);
function mandel(w, h, maxIter) { var counts = [], total = 0; for (var y = 0; y < h; y++) { var line = ''; for (var x = 0; x < w; x++) { var cr = x / w * 3 - 2, ci = y / h * 2 - 1, zr = 0, zi = 0, it = 0; while (it < maxIter && zr * zr + zi * zi <= 4) { var t = zr * zr - zi * zi + cr; zi = 2 * zr * zi + ci; zr = t; it++; } total += it; line += it === maxIter ? '#' : it > 6 ? '+' : '.'; } counts.push(line); } return total + '\n' + counts.join('\n'); }
console.log(mandel(40, 10, 50));
function life(grid, gens) { var h = grid.length, w = grid[0].length; for (var g = 0; g < gens; g++) { var next = []; for (var y = 0; y < h; y++) { var row = []; for (var x = 0; x < w; x++) { var c = 0; for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) if (dy || dx) c += grid[(y + dy + h) % h][(x + dx + w) % w]; row.push(c === 3 || (c === 2 && grid[y][x]) ? 1 : 0); } next.push(row); } grid = next; } return grid; }
var g0 = [];
for (var y = 0; y < 16; y++) { g0.push([]); for (var x = 0; x < 16; x++) g0[y].push(((x * 7 + y * 13) % 5 === 0) | 0); }
var g1 = life(g0, 20), alive = 0;
for (var y = 0; y < 16; y++) for (var x = 0; x < 16; x++) alive += g1[y][x];
console.log('life', alive, g1[0].join(''), g1[8].join(''));
function nbody(steps) {
  var bodies = [[0, 0, 0, 0, 0, 0, 39.47841760435743], [4.84, -1.16, -0.10, 0.606, 2.81, -0.02, 0.037], [8.34, 4.12, -0.40, -1.01, 1.82, 0.008, 0.011], [12.89, -15.11, -0.22, 1.08, 0.868, -0.01, 0.0017], [15.37, -25.9, 0.179, 0.979, 0.594, -0.034, 0.002]];
  var dt = 0.01;
  function energy() { var e = 0; for (var i = 0; i < bodies.length; i++) { var b = bodies[i]; e += 0.5 * b[6] * (b[3] * b[3] + b[4] * b[4] + b[5] * b[5]); for (var j = i + 1; j < bodies.length; j++) { var c = bodies[j], dx = b[0] - c[0], dy = b[1] - c[1], dz = b[2] - c[2]; e -= b[6] * c[6] / Math.sqrt(dx * dx + dy * dy + dz * dz); } } return e; }
  var e0 = energy();
  for (var s = 0; s < steps; s++) {
    for (var i = 0; i < bodies.length; i++) { var b = bodies[i]; for (var j = i + 1; j < bodies.length; j++) { var c = bodies[j], dx = b[0] - c[0], dy = b[1] - c[1], dz = b[2] - c[2], d2 = dx * dx + dy * dy + dz * dz, mag = dt / (d2 * Math.sqrt(d2)); b[3] -= dx * c[6] * mag; b[4] -= dy * c[6] * mag; b[5] -= dz * c[6] * mag; c[3] += dx * b[6] * mag; c[4] += dy * b[6] * mag; c[5] += dz * b[6] * mag; } }
    for (var i = 0; i < bodies.length; i++) { var b = bodies[i]; b[0] += dt * b[3]; b[1] += dt * b[4]; b[2] += dt * b[5]; }
  }
  return e0.toFixed(12) + ' ' + energy().toFixed(12) + ' ' + bodies[1][0].toFixed(12);
}
console.log('nbody', nbody(500));
function stencil(n, iters) { var u = new Float64Array(n * n); for (var i = 0; i < n; i++) u[i] = 1; for (var it = 0; it < iters; it++) for (var y = 1; y < n - 1; y++) for (var x = 1; x < n - 1; x++) { var k = y * n + x; u[k] = (u[k - 1] + u[k + 1] + u[k - n] + u[k + n]) * 0.25; } var s = 0; for (var i = 0; i < u.length; i++) s += u[i]; return s.toFixed(10) + ' ' + u[n + 1].toFixed(12) + ' ' + u[(n >> 1) * n + (n >> 1)].toExponential(8); }
console.log('stencil', stencil(20, 60));
function modpow(b, e, m) { var r = 1; b %= m; while (e > 0) { if (e & 1) r = r * b % m; b = b * b % m; e >>= 1; } return r; }
function lcg(n) { var x = 1, s = 0; for (var i = 0; i < n; i++) { x = (x * 48271) % 2147483647; s = (s + x) % 1000000007; } return x + ' ' + s; }
var mp = [];
for (var i = 1; i < 2000; i += 97) mp.push(modpow(i, 1e6 + i, 65521));
console.log('integers', mp.join(','), lcg(20000));
function primesSieve(n) { var s = new Uint8Array(n + 1), c = 0, last = 0; for (var i = 2; i <= n; i++) { if (!s[i]) { c++; last = i; for (var j = i * i; j <= n; j += i) s[j] = 1; } } return c + ' ' + last; }
console.log('sieve', primesSieve(100000));
''', cli=cli)


@tiers
def test_interpreter_dispatch_loops(run, workdir, cli):
    """CATCHES: switch-dispatch interpreter loops (the classic hot shape:
    while(true){switch(code[pc++])}) that mis-route dense or sparse/string case values, lose the
    operand stack or pc across iterations, mishandle break/continue/return from inside the
    switch, or a recursive-descent parser/evaluator whose mutually recursive hot functions
    produce wrong precedence, associativity or errors."""
    check_script(run, workdir, G, "interpreter_dispatch_loops", r'''
function runVM(code, input) {
  var stack = [], pc = 0, out = [], steps = 0, mem = new Array(8).fill(0);
  while (true) {
    steps++;
    var op = code[pc++];
    switch (op) {
      case 0: return out.join(',') + ' steps=' + steps;
      case 1: stack.push(code[pc++]); break;
      case 2: stack.push(stack.pop() + stack.pop()); break;
      case 3: { var b = stack.pop(), a = stack.pop(); stack.push(a - b); break; }
      case 4: stack.push(stack.pop() * stack.pop()); break;
      case 5: stack.push(stack[stack.length - 1]); break;
      case 6: if (stack.pop() !== 0) pc = code[pc]; else pc++; continue;
      case 7: pc = code[pc]; continue;
      case 8: out.push(stack.pop()); break;
      case 9: mem[code[pc++]] = stack.pop(); break;
      case 10: stack.push(mem[code[pc++]]); break;
      case 11: stack.push(input.shift() | 0); break;
      case 100: { var y = stack.pop(), x = stack.pop(); stack.push(x % y); break; }
      default: throw new Error('bad opcode ' + op + ' at ' + (pc - 1));
    }
  }
}
var OPS = { HALT: 0, PUSH: 1, ADD: 2, SUB: 3, MUL: 4, DUP: 5, JNZ: 6, JMP: 7, PRINT: 8, STORE: 9, LOAD: 10, READ: 11, MOD: 100 };
function assemble(text) {
  var toks = text.trim().split(/\s+/), code = [], labels = {}, fix = [];
  for (var i = 0; i < toks.length; i++) {
    var t = toks[i];
    if (t[t.length - 1] === ':') { labels[t.slice(0, -1)] = code.length; continue; }
    if (t in OPS) code.push(OPS[t]); else if (/^-?\d+$/.test(t)) code.push(+t); else { fix.push(code.length); code.push(t); }
  }
  for (var j = 0; j < fix.length; j++) code[fix[j]] = labels[code[fix[j]]];
  return code;
}
var prog = assemble('READ STORE 0 PUSH 1 STORE 1 PUSH 0 STORE 2 PUSH 1 STORE 3 ' +
  'loop: LOAD 2 LOAD 1 ADD STORE 2 LOAD 3 LOAD 1 MUL PUSH 1000003 MOD STORE 3 ' +
  'LOAD 1 PUSH 100 MOD JNZ skip LOAD 2 PRINT LOAD 3 PRINT ' +
  'skip: LOAD 1 PUSH 1 ADD DUP STORE 1 LOAD 0 SUB PUSH 1 SUB JNZ loop LOAD 2 PRINT HALT');
var vr;
for (var r = 0; r < 8; r++) vr = runVM(prog, [500]);
console.log('vm', prog.length, vr, runVM(prog, [1]));
try { runVM([1, 2, 42], []); } catch (e) { console.log(e.message); }
function bf(src, input) {
  var tape = new Uint8Array(300), ptr = 0, out = '', ip = 0, inp = 0, jump = [], st = [];
  for (var i = 0; i < src.length; i++) { if (src[i] === '[') st.push(i); else if (src[i] === ']') { var j = st.pop(); jump[i] = j; jump[j] = i; } }
  while (ip < src.length) {
    switch (src.charCodeAt(ip)) {
      case 62: ptr++; break;
      case 60: ptr--; break;
      case 43: tape[ptr]++; break;
      case 45: tape[ptr]--; break;
      case 46: out += String.fromCharCode(tape[ptr]); break;
      case 44: tape[ptr] = inp < input.length ? input.charCodeAt(inp++) : 0; break;
      case 91: if (!tape[ptr]) ip = jump[ip]; break;
      case 93: if (tape[ptr]) ip = jump[ip]; break;
    }
    ip++;
  }
  return out;
}
var hello = '++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>.>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.';
var rev = '>,[>,]<[.<]';
console.log('bf', JSON.stringify(bf(hello, '')), bf(rev, 'stressed'), bf('-.', '').charCodeAt(0));
function Parser(src) { this.src = src; this.pos = 0; }
Parser.prototype.peek = function () { while (this.src[this.pos] === ' ') this.pos++; return this.src[this.pos]; };
Parser.prototype.expr = function () { var v = this.term(); for (;;) { var c = this.peek(); if (c === '+') { this.pos++; v += this.term(); } else if (c === '-') { this.pos++; v -= this.term(); } else return v; } };
Parser.prototype.term = function () { var v = this.factor(); for (;;) { var c = this.peek(); if (c === '*') { this.pos++; v *= this.factor(); } else if (c === '/') { this.pos++; var d = this.factor(); if (d === 0) throw new RangeError('division by zero at ' + this.pos); v /= d; } else if (c === '%') { this.pos++; v %= this.factor(); } else return v; } };
Parser.prototype.factor = function () { var c = this.peek(); if (c === '-') { this.pos++; return -this.factor(); } if (c === '(') { this.pos++; var v = this.expr(); if (this.peek() !== ')') throw new SyntaxError('expected ) at ' + this.pos); this.pos++; return v; } var start = this.pos; while (/[0-9.]/.test(this.src[this.pos] || '')) this.pos++; if (start === this.pos) throw new SyntaxError('unexpected ' + JSON.stringify(c === undefined ? 'end' : c) + ' at ' + start); var base = parseFloat(this.src.slice(start, this.pos)); if (this.peek() === '^') { this.pos++; return Math.pow(base, this.factor()); } return base; };
function evaluate(s) { try { var p = new Parser(s); var v = p.expr(); if (p.peek() !== undefined) throw new SyntaxError('trailing at ' + p.pos); return String(v); } catch (e) { return e.name + ': ' + e.message; } }
var exprs = ['1 + 2 * 3', '(1 + 2) * 3', '2 ^ 3 ^ 2', '-2 ^ 2', '10 / 4 - 7 % 3', '1 - 2 - 3', '((((1))))', '1 / 0', '2 * (3 + ', '4 $ 4', '', '0.1 + 0.2', '-(-(-1))', '8 / 2 / 2'];
var ev;
for (var r = 0; r < 60; r++) ev = exprs.map(evaluate);
console.log(ev.join(' | '));
function stringSwitch(words) { var counts = { kw: 0, op: 0, id: 0 }; for (var i = 0; i < words.length; i++) { switch (words[i]) { case 'if': case 'else': case 'while': case 'return': counts.kw++; break; case '+': case '-': case '===': counts.op++; break; default: counts.id++; } } return JSON.stringify(counts); }
var words = 'if x === y return a + b else while z - 1 return q'.split(' ');
var big = [];
for (var i = 0; i < 2000; i++) big.push(words[i % words.length]);
console.log('string switch', stringSwitch(big));
''', cli=cli)


@tiers
def test_object_graph_structures(run, workdir, cli):
    """CATCHES: object-heavy hot code (Splay-style trees, binary heaps with comparators, linked lists,
    union-find, tries) that mis-handles null links, property writes on freshly allocated nodes,
    polymorphic node shapes, or recursion/iteration over pointer graphs; any lost update shows
    up in the printed sizes, orders and checksums."""
    check_script(run, workdir, G, "object_graph_structures", r'''
function SplayTree() { this.root = null; }
function Node(key, value) { this.key = key; this.value = value; this.left = null; this.right = null; }
SplayTree.prototype.splay = function (key) {
  if (!this.root) return;
  var dummy = new Node(null, null), left = dummy, right = dummy, current = this.root;
  while (true) {
    if (key < current.key) {
      if (!current.left) break;
      if (key < current.left.key) { var tmp = current.left; current.left = tmp.right; tmp.right = current; current = tmp; if (!current.left) break; }
      right.left = current; right = current; current = current.left;
    } else if (key > current.key) {
      if (!current.right) break;
      if (key > current.right.key) { var tmp2 = current.right; current.right = tmp2.left; tmp2.left = current; current = tmp2; if (!current.right) break; }
      left.right = current; left = current; current = current.right;
    } else break;
  }
  left.right = current.left; right.left = current.right; current.left = dummy.right; current.right = dummy.left; this.root = current;
};
SplayTree.prototype.insert = function (key, value) {
  if (!this.root) { this.root = new Node(key, value); return; }
  this.splay(key);
  if (this.root.key === key) return;
  var node = new Node(key, value);
  if (key > this.root.key) { node.left = this.root; node.right = this.root.right; this.root.right = null; }
  else { node.right = this.root; node.left = this.root.left; this.root.left = null; }
  this.root = node;
};
SplayTree.prototype.remove = function (key) {
  if (!this.root) return null;
  this.splay(key);
  if (this.root.key !== key) return null;
  var removed = this.root;
  if (!this.root.left) this.root = this.root.right;
  else { var right = this.root.right; this.root = this.root.left; this.splay(key); this.root.right = right; }
  return removed;
};
SplayTree.prototype.find = function (key) { if (!this.root) return null; this.splay(key); return this.root.key === key ? this.root : null; };
SplayTree.prototype.keys = function () { var out = [], stack = [], n = this.root; while (stack.length || n) { if (n) { stack.push(n); n = n.left; } else { n = stack.pop(); out.push(n.key); n = n.right; } } return out; };
var tree = new SplayTree(), x = 42;
for (var i = 0; i < 2000; i++) { x = (x * 1103515245 + 12345) % 2147483648; tree.insert(x % 5000, { i: i, payload: [i] }); if (i % 3 === 0) tree.remove((x >> 3) % 5000); }
var keys = tree.keys(), sorted = true;
for (var i = 1; i < keys.length; i++) if (keys[i - 1] >= keys[i]) sorted = false;
var f = tree.find(keys[10]);
console.log('splay', keys.length, sorted, keys.slice(0, 6).join(','), f && f.value.i, tree.find(-1), tree.root.key);
function Heap(cmp) { this.items = []; this.cmp = cmp; }
Heap.prototype.push = function (v) { var a = this.items, i = a.push(v) - 1; while (i > 0) { var p = (i - 1) >> 1; if (this.cmp(a[i], a[p]) >= 0) break; var t = a[i]; a[i] = a[p]; a[p] = t; i = p; } };
Heap.prototype.pop = function () { var a = this.items, top = a[0], last = a.pop(); if (a.length) { a[0] = last; var i = 0; for (;;) { var l = 2 * i + 1, r = l + 1, m = i; if (l < a.length && this.cmp(a[l], a[m]) < 0) m = l; if (r < a.length && this.cmp(a[r], a[m]) < 0) m = r; if (m === i) break; var t = a[i]; a[i] = a[m]; a[m] = t; i = m; } } return top; };
function dijkstra(n) {
  var adj = []; for (var i = 0; i < n; i++) adj.push([]);
  for (var i = 0; i < n; i++) { adj[i].push({ to: (i + 1) % n, w: 7 }); adj[i].push({ to: (i * 3 + 1) % n, w: (i % 5) + 1 }); adj[i].push({ to: (i * i) % n, w: 11 }); }
  var dist = new Array(n).fill(Infinity), h = new Heap(function (a, b) { return a.d - b.d || a.v - b.v; }), pops = 0;
  dist[0] = 0; h.push({ v: 0, d: 0 });
  while (h.items.length) { var cur = h.pop(); pops++; if (cur.d > dist[cur.v]) continue; var es = adj[cur.v]; for (var k = 0; k < es.length; k++) { var e = es[k], nd = cur.d + e.w; if (nd < dist[e.to]) { dist[e.to] = nd; h.push({ v: e.to, d: nd }); } } }
  var sum = 0, mx = 0; for (var i = 0; i < n; i++) { sum += dist[i]; if (dist[i] > mx) mx = dist[i]; }
  return sum + ' ' + mx + ' ' + pops;
}
console.log("dijkstra", dijkstra(500));
function List() { this.head = null; this.size = 0; }
List.prototype.push = function (v) { this.head = { v: v, next: this.head }; this.size++; return this; };
List.prototype.reverse = function () { var prev = null, cur = this.head; while (cur) { var nx = cur.next; cur.next = prev; prev = cur; cur = nx; } this.head = prev; return this; };
List.prototype.filter = function (p) { var dummy = { next: this.head }, cur = dummy; while (cur.next) { if (!p(cur.next.v)) { cur.next = cur.next.next; this.size--; } else cur = cur.next; } this.head = dummy.next; return this; };
List.prototype.toArray = function () { var out = []; for (var n = this.head; n; n = n.next) out.push(n.v); return out; };
var list = new List();
for (var i = 0; i < 2000; i++) list.push(i);
list.reverse().filter(function (v) { return v % 3 !== 0; });
var la = list.toArray();
console.log('list', list.size, la.length, la.slice(0, 6).join(','), la[la.length - 1]);
function DSU(n) { this.p = []; this.r = []; for (var i = 0; i < n; i++) { this.p.push(i); this.r.push(0); } }
DSU.prototype.find = function (x) { while (this.p[x] !== x) { this.p[x] = this.p[this.p[x]]; x = this.p[x]; } return x; };
DSU.prototype.union = function (a, b) { a = this.find(a); b = this.find(b); if (a === b) return false; if (this.r[a] < this.r[b]) { var t = a; a = b; b = t; } this.p[b] = a; if (this.r[a] === this.r[b]) this.r[a]++; return true; };
var dsu = new DSU(5000), merges = 0;
for (var i = 0; i < 4000; i++) if (dsu.union((i * 7919) % 5000, (i * 104729 + 3) % 5000)) merges++;
var roots = new Set(); for (var i = 0; i < 5000; i++) roots.add(dsu.find(i));
console.log('union-find', merges, roots.size);
function Trie() { this.root = Object.create(null); }
Trie.prototype.add = function (w) { var n = this.root; for (var i = 0; i < w.length; i++) { var c = w[i]; n = n[c] || (n[c] = Object.create(null)); } n.$ = (n.$ || 0) + 1; };
Trie.prototype.count = function (prefix) { var n = this.root; for (var i = 0; i < prefix.length; i++) { n = n[prefix[i]]; if (!n) return 0; } var total = 0, stack = [n]; while (stack.length) { var m = stack.pop(); for (var k in m) { if (k === '$') total += m[k]; else stack.push(m[k]); } } return total; };
var trie = new Trie(), syll = ['ka', 'ri', 'to', 'mu', 'ne', 'so'];
for (var i = 0; i < 3000; i++) trie.add(syll[i % 6] + syll[(i >> 2) % 6] + (i % 5 ? syll[(i >> 4) % 6] : ''));
console.log('trie', trie.count(''), trie.count('ka'), trie.count('kari'), trie.count('zz'), trie.count('sosoka'));
''', cli=cli)


@tiers
def test_async_loops(run, workdir, cli):
    """CATCHES: compiled async functions whose hot loops await (fulfilled values, thenables, rejected
    promises caught by try/catch inside the loop, finally after await), async generators
    consumed by for await with early break (return() must run the generator's finally), and
    microtask ordering between interleaved async loops, Promise.all/allSettled/race and
    queueMicrotask; the global log order must be identical in every tier."""
    check_script(run, workdir, G, "async_loops", r'''
var log = [];
async function summer(n) { var s = 0; for (var i = 0; i < n; i++) { s += await i; if (i % 250 === 0) log.push('summer@' + i); } return s; }
async function thenables(n) { var s = 0; for (var i = 0; i < n; i++) s += await { then: function (res) { res(i * 2); } }; return s; }
async function failing(n) { var caught = 0, fin = 0; for (var i = 0; i < n; i++) { try { if (i % 4 === 0) await Promise.reject(new Error('r' + i)); else await null; } catch (e) { caught++; } finally { fin++; } } return caught + '/' + fin; }
async function* ticker(n) { try { for (var i = 0; i < n; i++) { await null; yield i; } } finally { log.push('ticker finally'); } }
async function consume(limit) { var got = []; for await (var v of ticker(100)) { got.push(v); if (v >= limit) break; } return got.join(''); }
async function interleave(name, n) { for (var i = 0; i < n; i++) { log.push(name + i); await null; } return name; }
async function main() {
  var results = [];
  results.push(await summer(1000));
  results.push(await thenables(500));
  results.push(await failing(400));
  results.push(await consume(5));
  var both = await Promise.all([interleave('a', 3), interleave('b', 3)]);
  results.push(both.join(''));
  var settled = await Promise.allSettled([Promise.resolve(1), Promise.reject(new TypeError('no')), summer(3)]);
  results.push(settled.map(function (s) { return s.status + ':' + (s.value !== undefined ? s.value : s.reason.message); }).join(','));
  results.push(await Promise.race([new Promise(function (r) { setTimeout(r, 50, 'slow'); }), Promise.resolve('fast')]));
  var any = await Promise.any([Promise.reject(1), Promise.resolve('any-ok')]);
  try { await Promise.any([Promise.reject(1), Promise.reject(2)]); } catch (e) { results.push(any + ' ' + e.constructor.name + ' ' + e.errors.join('+')); }
  return results;
}
queueMicrotask(function () { log.push('microtask before main settles'); });
main().then(function (r) { console.log(r.join('\n')); console.log(log.join(' ')); });
Promise.resolve().then(function () { log.push('then1'); }).then(function () { log.push('then2'); });
log.push('sync end');
async function rejectsOut() { for (var i = 0; ; i++) { await null; if (i === 300) throw new RangeError('loop escaped at ' + i); } }
rejectsOut().catch(function (e) { console.log(e.name + ': ' + e.message); });
setTimeout(function () { console.log('timer after', log.length); }, 80);
''', cli=cli)


@tiers
def test_sorting_and_callbacks(run, workdir, cli):
    """CATCHES: hand-written sorts (quicksort, merge sort, insertion sort, heap sort, counting sort)
    and builtin higher-order calls (sort/map/filter/reduce/find/every/flatMap with user
    callbacks, which re-enter compiled code from native code) that produce wrong orders, lose
    stability for equal keys, mishandle comparator results that are NaN/non-numbers, or skip
    holes incorrectly."""
    check_script(run, workdir, G, "sorting_and_callbacks", r'''
function rng(seed) { var s = seed >>> 0; return function () { s = (s * 1664525 + 1013904223) >>> 0; return s; }; }
function data(n, seed) { var r = rng(seed), a = []; for (var i = 0; i < n; i++) a.push(r() % 1000); return a; }
function quick(a, lo, hi) { if (lo >= hi) return; var p = a[(lo + hi) >> 1], i = lo, j = hi; while (i <= j) { while (a[i] < p) i++; while (a[j] > p) j--; if (i <= j) { var t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; } } quick(a, lo, j); quick(a, i, hi); }
function merge(a) { if (a.length < 2) return a; var m = a.length >> 1, l = merge(a.slice(0, m)), r = merge(a.slice(m)), out = [], i = 0, j = 0; while (i < l.length && j < r.length) out.push(l[i] <= r[j] ? l[i++] : r[j++]); while (i < l.length) out.push(l[i++]); while (j < r.length) out.push(r[j++]); return out; }
function insertion(a) { for (var i = 1; i < a.length; i++) { var v = a[i], j = i - 1; while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; } a[j + 1] = v; } return a; }
function heapsort(a) { var n = a.length; function sift(i, n) { for (;;) { var l = 2 * i + 1, r = l + 1, m = i; if (l < n && a[l] > a[m]) m = l; if (r < n && a[r] > a[m]) m = r; if (m === i) return; var t = a[i]; a[i] = a[m]; a[m] = t; i = m; } } for (var i = (n >> 1) - 1; i >= 0; i--) sift(i, n); for (var e = n - 1; e > 0; e--) { var t = a[0]; a[0] = a[e]; a[e] = t; sift(0, e); } return a; }
function counting(a) { var c = new Uint32Array(1000), out = []; for (var i = 0; i < a.length; i++) c[a[i]]++; for (var v = 0; v < 1000; v++) for (var k = 0; k < c[v]; k++) out.push(v); return out; }
function digest(a) { var h = 0; for (var i = 0; i < a.length; i++) h = (h * 31 + a[i]) | 0; return h; }
var base = data(1200, 7), q = base.slice();
quick(q, 0, q.length - 1);
var results = [digest(q), digest(merge(base.slice())), digest(insertion(base.slice(0, 400))), digest(heapsort(base.slice())), digest(counting(base)), digest(base.slice().sort(function (x, y) { return x - y; }))];
console.log('sorts', results.join(' '), q[0], q[600], q[1199]);
var people = [];
var names = ['ann', 'bob', 'cy', 'dee', 'eve', 'fay'];
for (var i = 0; i < 300; i++) people.push({ name: names[i % 6] + i, age: 20 + (i * 7) % 13, idx: i });
var byAge = people.slice().sort(function (a, b) { return a.age - b.age; });
var stable = true;
for (var i = 1; i < byAge.length; i++) if (byAge[i - 1].age === byAge[i].age && byAge[i - 1].idx > byAge[i].idx) stable = false;
console.log('stable', stable, byAge.slice(0, 4).map(function (p) { return p.name; }).join(','), byAge[299].name);
var weird = [5, 1, 4, 2, 3];
var cmpCalls = 0;
console.log('comparators', weird.slice().sort(function () { cmpCalls++; return NaN; }).join(''), weird.slice().sort(function (a, b) { return b > a; }).join(''), weird.slice().sort(function (a, b) { return String(b - a); }).join(''), cmpCalls > 0, [3, , 1, undefined, 2].sort().length, JSON.stringify([3, , 1, undefined, 2].sort(function (a, b) { return a - b; })));
try { [1, 2].sort('nope'); } catch (e) { console.log(e.name + ': ' + e.message); }
var nums = data(1000, 99);
var cb = 0;
var pipeline = nums.map(function (v, i) { cb++; return v * (i % 3 - 1); }).filter(function (v) { cb++; return v > 0; }).reduce(function (acc, v) { cb++; return acc + v; }, 0);
var found = nums.find(function (v) { return v > 990; }), fi = nums.findLastIndex(function (v) { return v < 5; });
var fm = [1, 2, 3].flatMap(function (v) { return [v, [v * 10]]; });
var every = nums.every(function (v) { return v < 1000; }), some = nums.some(function (v) { return v === 500; });
var holes = [1, , 3], visited = [];
holes.forEach(function (v, i) { visited.push(i); });
holes.map(function (v) { return v; });
console.log('callbacks', pipeline, cb, found, fi, JSON.stringify(fm), every, some, visited.join(''), JSON.stringify(holes.map(function (v) { return v * 2; })), [1, 2, 3, 4].reduceRight(function (a, b) { return a + '-' + b; }));
var groups = {};
nums.forEach(function (v) { var k = v % 7; (groups[k] || (groups[k] = [])).push(v); });
console.log('groups', Object.keys(groups).map(function (k) { return k + ':' + groups[k].length; }).join(' '), [..."hello"].toSorted().join(''), [3, 1, 2].toReversed().join(''), [1, 2, 3].with(1, 9).join(''));
''', cli=cli)


@tiers
def test_operators_and_assignments(run, workdir, cli):
    """CATCHES: compiled operator lowering in hot code: every compound assignment (+= -= *= /= %= **=
    <<= >>= >>>= &= |= ^= &&= ||= ??=) on locals, captured variables, globals, properties and
    computed elements (key and receiver evaluated once), short-circuit assignments that must not
    write, optional chaining (?. ?.[] ?.()), tagged templates (cached strings object),
    void/delete/in/comma, and the exact errors for TDZ reads, const assignment, strict delete
    and calls on null."""
    check_script(run, workdir, G, "operators_and_assignments", r'''
function compound(n) {
  var a = 1, b = 1000, c = 7, d = 2 ** 31, e = -9, f = 0, g = null, h = 'x';
  for (var i = 1; i <= n; i++) {
    a += i; b -= i % 7; c *= 3; c %= 1000003; d >>>= 1; d ||= 2 ** 31; e <<= 1; e >>= 1; f ^= i; f |= 1; f &= 0xffff;
    g ??= i; h &&= h + (i % 10); if (h.length > 20) h = 'x';
  }
  var p = 2; p **= 10; var q = 17; q /= 4; var r = -7; r %= 3;
  return [a, b, c, d, e, f, g, h, p, q, r].join(',');
}
var cr;
for (var k = 0; k < 50; k++) cr = compound(300);
console.log('locals', cr);
var counter = 0, glob = 0;
function closureOps() { var cap = 0; function inc() { cap++; ++cap; cap += 2; cap -= 1; cap **= 1; counter++; glob += 2; return cap; } for (var i = 0; i < 300; i++) inc(); return cap; }
console.log('captured/global', closureOps(), counter, glob);
var evals = [];
function key(k) { evals.push('k' + k); return k; }
function obj(o) { evals.push('o'); return o; }
function elems(n) { var t = { a: 1, b: 2, list: [0, 0, 0] }; for (var i = 0; i < n; i++) { obj(t)[key('a')] += 1; obj(t.list)[key(i % 3)] |= 1 << (i % 5); t[key('b')] *= 1; t.c ??= 'set'; t.c ||= 'never'; t.a &&= t.a + 0; } return JSON.stringify(t); }
var er = elems(200);
console.log('elements', er, evals.length, evals.slice(0, 6).join(''));
function shortCircuit() { var writes = 0; var o = { get v() { return 1; }, set v(x) { writes++; } }; var z = { get v() { return 0; }, set v(x) { writes++; } }; var nn = { get v() { return null; }, set v(x) { writes++; } }; for (var i = 0; i < 100; i++) { o.v ||= 5; z.v &&= 5; o.v ??= 5; nn.v ??= 5; z.v ||= 5; } return writes; }
console.log('short-circuit writes', shortCircuit());
function chains(list) { var out = []; for (var i = 0; i < list.length; i++) { var o = list[i]; out.push([o?.a?.b, o?.arr?.[1], o?.fn?.(i), o?.a?.['b'], typeof o?.m?.call].map(String).join('/')); } return out.join(' '); }
var cl;
for (var k = 0; k < 100; k++) cl = chains([null, { a: { b: 1 }, arr: [5, 6], fn: function (x) { return x * 2; }, m: function () { } }, { a: null, arr: null }, { a: {}, arr: 'xy', fn: null }, undefined]);
console.log('optional', cl);
function tag(strings) { var vals = Array.prototype.slice.call(arguments, 1); return strings.raw.join('|') + '#' + vals.join(',') + '#' + strings.length; }
function templates(n) { var sameObj = true, first = null, out; for (var i = 0; i < n; i++) { var s = (function (x) { return x; })`a${i}b\n${i * 2}`; if (first === null) first = s; else if (first !== s) sameObj = false; out = tag`x${i}y${'z'}A`; } return sameObj + ' ' + out + ' ' + Object.isFrozen(first) + ' ' + first.raw[1]; }
console.log('tagged', templates(100), `${1}${'a'}${null}${[1, 2]}${{}}`);
function misc(n) { var r = []; for (var i = 0; i < n; i++) { var o = { a: 1, b: 2 }; delete o.a; r = [void i, 'a' in o, 'b' in o, delete o.zz, (i, i * 2), typeof undeclaredThing, typeof null, typeof function () { }, typeof 1n, typeof Symbol(), -(-i), +true, !!'0', ~~3.7, 2 ** -1, (-2) ** 2, 1 / 0 > 0]; } return r.join(','); }
console.log('misc', misc(100));
function errorsList() {
  var out = [];
  var cases = [
    function () { 'use strict'; var o = {}; Object.defineProperty(o, 'x', { value: 1 }); delete o.x; },
    function () { 'use strict'; delete Object.prototype; },
    function () { const c = 1; c = 2; },
    function () { const c = 1; c += 1; },
    function () { var fn = function () { return t; }; var r = fn(); let t = 1; return r; },
    function () { x2++; let x2 = 1; },
    function () { var o = null; return o.m(); },
    function () { var o = { m: null }; return o.m(); },
    function () { var o; return o[0]; },
    function () { var o = null; return o[1](); },
    function () { var u; u.prop = 1; },
    function () { 'use strict'; undeclaredStrict = 1; },
    function () { return 1 in 5; },
    function () { return ({}) instanceof 5; },
    function () { var s = Symbol(); return `${s}`; },
    function () { new (function () { }.bind(null))().x(); },
  ];
  var nameOnly = [7, 9, 15];
  for (var r = 0; r < 20; r++) for (var i = 0; i < cases.length; i++) { try { cases[i](); out[i] = 'ok'; } catch (e) { out[i] = nameOnly.indexOf(i) >= 0 ? e.name : e.name + ': ' + e.message; } }
  return out.join('\n');
}
console.log(errorsList());
''', cli=cli)
