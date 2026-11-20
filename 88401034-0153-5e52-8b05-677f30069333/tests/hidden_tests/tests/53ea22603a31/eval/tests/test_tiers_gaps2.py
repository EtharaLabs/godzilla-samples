"""Second-wave tier coverage, JIT side: numeric loop/chain shapes that the native JIT plans
specially (many locals, many array receivers, comma updates, boolean-valued compares, used
post-increments, constant shifts), oversized constructor frames entered from machine code, a
SHA-256 kernel, pre-increment keyed reads and prototype-chain invalidation, linked-list tail
scans and counter/ring idioms, and the guarded `re.exec(strings[i])` loop helper with every kind
of guard miss. Every program runs on the default JIT tier, --tier=bytecode and --tier=interp
against ONE shared golden, so a tier that diverges from the tree-walker is caught."""
import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)
TIERS = [pytest.param([], id="jit"), pytest.param(["--tier=bytecode"], id="bytecode"),
         pytest.param(["--tier=interp"], id="interp")]
tiers = pytest.mark.parametrize("cli", TIERS)


@tiers
def test_numeric_loop_shapes(run, workdir, cli):
    """CATCHES: JIT numeric loop/chain planning bugs: a nine-variable rotating recurrence (more
    locals than the planner keeps in registers), a five-array element kernel (more receivers
    than pinned registers, so later arrays use the classic store path), two-pointer swaps with
    comma updates, compares whose boolean result is stored and reused, post-increments whose
    old value is consumed, and constant shifts/masks -- plus the same kernels fed doubles,
    numeric strings and short arrays afterwards (guards must fall back, not reuse int paths)."""
    check_script(run, workdir, G, "numeric_loop_shapes", r'''
function nineVars(n) { var a = 1, b = 2, c = 3, d = 4, e = 5, f = 6, g = 7, h = 8, k = 9; for (var i = 0; i < n; i++) { a = (b + c) % 1000; b = (c + d) % 1000; c = (d + e) % 1000; d = (e + f) % 1000; e = (f + g) % 1000; f = (g + h) % 1000; g = (h + k) % 1000; h = (k + a) % 1000; k = (a + b + i) % 1000; } return [a, b, c, d, e, f, g, h, k].join(','); }
function fiveArrays(a, b, c, d, e, n) { var s = 0; for (var i = 0; i < n; i++) { e[i] = a[i] + b[i] * c[i] - d[i]; s += e[i]; } return s + ':' + e.slice(0, 3).join('|'); }
function twoPointers(arr) { var swaps = 0; for (var i = 0, j = arr.length - 1; i < j; i++, j--) { var t = arr[i]; arr[i] = arr[j]; arr[j] = t; swaps++; } return swaps + ':' + arr.slice(0, 5).join(','); }
function flags(n) { var trues = 0, last = false, prev = 0; for (var i = 0; i < n; i++) { var cur = (i * 7) % 11; var up = cur > prev; var eq = cur === prev; if (up) trues++; last = up || eq; prev = cur; } return trues + ':' + last; }
function postUsed(n) { var x = 0, y = 0, s = 0; for (var i = 0; i < n; i++) { s += x++; s -= y--; s += ++x; } return s + ':' + x + ':' + y; }
function shifts(n) { var h = 0, l = 1; for (var i = 0; i < n; i++) { h = (h << 3) ^ (h >> 2) ^ i; l = (l * 3) >>> 1; h = h & 0xffffff; l = l & 0xffff; } return h + ':' + l; }
function mk(n, f) { var x = []; for (var i = 0; i < n; i++) x.push(f(i)); return x; }
var r;
for (var q = 0; q < 6; q++) {
  r = [nineVars(1000), fiveArrays(mk(100, function (i) { return i; }), mk(100, function (i) { return i % 7; }), mk(100, function (i) { return 2; }), mk(100, function (i) { return i >> 1; }), mk(100, function () { return 0; }), 100), twoPointers(mk(101, function (i) { return i * 3; })), flags(500), postUsed(300), shifts(1000)];
}
console.log(r.join('\n'));
console.log(fiveArrays([1.5, 2], ['3', 4], [2, 2], [0, 1], [0, 0], 2));
console.log(fiveArrays([1, 2, 3], [1, 1, 1], [1, 1, 1], [0, 0, 0], [9], 3));
console.log(fiveArrays([1, 2], [1, 1], [1, 1], [0, 0], Object.freeze([5, 5]), 2));
console.log(twoPointers([]), twoPointers(['a', 'b', 'c']), twoPointers([1.5, NaN]), flags(3), postUsed(0), nineVars(0), shifts(0));
''', cli=cli)


@tiers
def test_oversized_constructor_frames(run, workdir, cli):
    """CATCHES: `new F(...)` issued from compiled code into constructors whose frame exceeds the
    fixed frame buffer (300 locals) or whose `for (var p ...)` head re-declares a parameter: a
    tier that mis-sizes the callee frame, leaks locals between constructions, or skips the
    parameter reset (the reference resets such parameters to undefined at entry -- a deviation
    from ECMAScript pinned as observed) builds objects with different fields."""
    names = ["w%d" % i for i in range(300)]
    source = ("function Wide(a, b) {\n  var " + ", ".join(names) + ";\n"
              "  var fresh = typeof w5;\n  w0 = a; w299 = b; w150 = a + b; w5 = 'used';\n"
              "  this.sum = w0 + w299 + w150; this.tail = typeof w298; this.fresh = fresh;\n}\n"
              "function Reset(n, tag) { var seen = n; for (var n = 0; n < 2; n++); this.seen = seen; this.n = n; this.tag = tag; }\n"
              "function build(k) { var out = []; for (var i = 0; i < k; i++) { var w = new Wide(i, 2 * i); var r = new Reset(i, 't' + i);"
              " out.push([w.sum, w.tail, w.fresh, r.seen, r.n, r.tag].join('/')); } return out; }\n"
              "var res;\nfor (var q = 0; q < 5; q++) res = build(30);\n"
              "console.log(res.slice(0, 3).join(' '));\nconsole.log(res.slice(-2).join(' '));\n"
              "console.log(JSON.stringify(new Wide('x', 'y')), JSON.stringify(new Reset('p', 'q')));\n")
    check_script(run, workdir, G, "oversized_constructor_frames", source, cli=cli)


@tiers
def test_sha256_kernel(run, workdir, cli):
    """CATCHES: hot int32 kernels (SHA-256 message schedule and compression: eight rotating
    variables, >>> / << / ^ / & / ~ with constant shift counts, `| 0` wrapping, array
    reads of a constant table) that lose the unsigned/signed distinction, overflow into
    doubles, or mis-mask shift counts in any tier -- the digests of standard test vectors
    (empty string, 'abc', the quick brown fox, a 300-byte message spanning several blocks,
    UTF-8 input) must be exact."""
    check_script(run, workdir, G, "sha256_kernel", r'''
var K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
function sha256(bytes) {
  var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
  var l = bytes.length, withPad = ((l + 9 + 63) >> 6) << 6;
  var m = new Array(withPad).fill(0);
  for (var i = 0; i < l; i++) m[i] = bytes[i];
  m[l] = 0x80;
  var bits = l * 8;
  m[withPad - 1] = bits & 0xff; m[withPad - 2] = (bits >>> 8) & 0xff; m[withPad - 3] = (bits >>> 16) & 0xff; m[withPad - 4] = (bits >>> 24) & 0xff;
  var W = new Array(64);
  for (var off = 0; off < withPad; off += 64) {
    for (var t = 0; t < 16; t++) W[t] = (m[off + t * 4] << 24) | (m[off + t * 4 + 1] << 16) | (m[off + t * 4 + 2] << 8) | m[off + t * 4 + 3];
    for (t = 16; t < 64; t++) {
      var w15 = W[t - 15], w2 = W[t - 2];
      var s0 = ((w15 >>> 7) | (w15 << 25)) ^ ((w15 >>> 18) | (w15 << 14)) ^ (w15 >>> 3);
      var s1 = ((w2 >>> 17) | (w2 << 15)) ^ ((w2 >>> 19) | (w2 << 13)) ^ (w2 >>> 10);
      W[t] = (W[t - 16] + s0 + W[t - 7] + s1) | 0;
    }
    var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
    for (t = 0; t < 64; t++) {
      var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      var ch = (e & f) ^ (~e & g);
      var T1 = (h + S1 + ch + K[t] + W[t]) | 0;
      var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      var maj = (a & b) ^ (a & c) ^ (b & c);
      var T2 = (S0 + maj) | 0;
      h = g; g = f; f = e; e = (d + T1) | 0; d = c; c = b; b = a; a = (T1 + T2) | 0;
    }
    H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
    H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
  }
  var hex = '';
  for (var j = 0; j < 8; j++) hex += ('00000000' + (H[j] >>> 0).toString(16)).slice(-8);
  return hex;
}
function utf8(s) { return Array.from(new TextEncoder().encode(s)); }
console.log(sha256(utf8('')));
console.log(sha256(utf8('abc')));
console.log(sha256(utf8('The quick brown fox jumps over the lazy dog')));
var long = '';
for (var i = 0; i < 300; i++) long += String.fromCharCode(97 + i % 26);
console.log(sha256(utf8(long)));
console.log(sha256(utf8('héllo wörld ✓')));
console.log(sha256(utf8('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')));
''', cli=cli)


@tiers
def test_keyed_reads_and_prototype_invalidation(run, workdir, cli):
    """CATCHES: fused `arr[++i]` / `arr[--i]` reads that commit the increment when the read falls
    back (holes reaching Array.prototype, accessor elements, array-likes, strings, mixed element
    types), and inline-cached reads of properties found three prototype hops up that keep
    returning stale values after a middle prototype gains a shadowing property, the root value
    changes, a getter replaces a data property, the chain is re-parented, or an instance gains
    an own property."""
    check_script(run, workdir, G, "keyed_reads_and_prototype_invalidation", r'''
function tokenize(chars) { var i = -1, n = chars.length - 1, words = 0, letters = 0; while (i < n) { var c = chars[++i]; if (c === ' ') words++; else letters++; } return words + ':' + letters + ':' + i; }
function backwards(arr) { var i = arr.length, s = 0; while (i > 0) { s = s * 31 + arr[--i] | 0; } return s + '@' + i; }
function skipper(arr) { var i = 0, out = 0; while (i < arr.length - 1) { out += arr[++i]; i++; } return out + '@' + i; }
var text = 'the quick brown fox jumps over the lazy dog'.split('');
var nums = [];
for (var k = 0; k < 200; k++) nums.push(k % 17);
var r;
for (var q = 0; q < 8; q++) r = [tokenize(text), backwards(nums), skipper(nums)];
console.log(r.join(' '));
console.log(tokenize('a b'.split('')), tokenize([]), backwards([1.5, 2.5]), backwards(['a', 'b']), skipper([0, 'x', 1, 'y']));
var holey = [1, , 3, , 5];
Array.prototype[3] = 40;
console.log('holes', backwards(holey), skipper(holey));
delete Array.prototype[3];
var o = { length: 3, 0: 1, 1: 2, 2: 3 };
console.log('array-like', backwards(o), skipper(o), backwards('xyz'), tokenize('x y'));
var counter = 0, getterArr = [1, 2, 3];
Object.defineProperty(getterArr, 2, { get: function () { counter++; return 100; } });
console.log('accessor', backwards(getterArr), skipper(getterArr), counter);
function A() {} A.prototype.k1 = 1; A.prototype.name1 = 'a';
function B() {} B.prototype = Object.create(A.prototype); B.prototype.k2 = 2;
function C() {} C.prototype = Object.create(B.prototype); C.prototype.k3 = 3;
function D() { this.own = 0.5; } D.prototype = Object.create(C.prototype);
D.prototype.total = function () { return this.k1 + this.k2 + this.k3 + this.own; };
D.prototype.label = function () { return this.name1 + this.k3; };
function viaLocal(o) { return o.k1 * 100 + o.k2 * 10 + o.k3; }
function driver(objs, n) { var s = 0, l = ''; for (var i = 0; i < n; i++) { var o = objs[i % objs.length]; s += o.total() + viaLocal(o); l = o.label(); } return s + ':' + l; }
var objs = [new D(), new D(), new D()];
var res = [];
for (var q = 0; q < 5; q++) res.push(driver(objs, 300));
console.log(res.join(' '));
B.prototype.k1 = 10;
console.log('shadow mid', driver(objs, 3));
delete B.prototype.k1; A.prototype.k1 = 5;
console.log('changed root', driver(objs, 3));
Object.defineProperty(C.prototype, 'k2', { get: function () { return -2; }, configurable: true });
console.log('getter', driver(objs, 3));
Object.setPrototypeOf(C.prototype, { k1: 7, k2: 8, name1: 'z' });
console.log('reparent', driver(objs, 3));
objs[1].k3 = 'own';
console.log('own shadow', driver(objs, 3));
''', cli=cli)


@tiers
def test_linked_scan_and_ring_idioms(run, workdir, cli):
    """CATCHES: specialised JIT regions for `while ((peek = next.link) != null) next = peek` and
    for a `this.count++ / reset / owner.slots[i] = this.count` loop bounded by a global limit,
    when the data stops matching the fast shape: nodes of different shapes, a terminal link
    inherited from a prototype, an undefined terminal (== null but !== null), a getter link, a
    fractional or string limit, a string counter and a frozen destination array."""
    check_script(run, workdir, G, "linked_scan_and_ring_idioms", r'''
function Node(v, link) { this.v = v; this.link = link; }
function tail(list) { var peek, next = list; while ((peek = next.link) != null) next = peek; return next.v; }
function tailStrict(list) { var peek, next = list; while ((peek = next.link) !== null) next = peek; return next.v; }
function build(n) { var l = null; for (var i = n; i > 0; i--) l = new Node(i, l); return l; }
var lst = build(50);
var r = [];
for (var q = 0; q < 8; q++) r = [tail(lst), tail(build(3)), tailStrict(lst)];
console.log('tail', r.join(','));
var mixed = build(5);
mixed.link.link = { v: 'other', link: { v: 'shape', extra: 1, link: null } };
var m;
for (var q = 0; q < 8; q++) m = [tail(mixed), tailStrict(mixed)];
console.log('mixed shapes', m.join(','));
function PNode(v) { this.v = v; }
PNode.prototype.link = null;
var pl = new Node(1, new Node(2, new PNode(3)));
var pr;
for (var q = 0; q < 8; q++) pr = [tail(pl), tail(new PNode('solo'))];
console.log('proto terminal', pr.join(','));
var undefTerminal = new Node(1, new Node(2, undefined));
console.log('undefined terminal', tail(undefTerminal));
try { tailStrict(undefTerminal); } catch (e) { console.log('strict scan', e.constructor.name); }
var getterNode = new Node(1, null), gets = 0;
Object.defineProperty(getterNode, 'link', { get: function () { gets++; return gets < 3 ? new Node('g' + gets, null) : null; } });
console.log('getter link', tail(getterNode), tail(getterNode), tail(getterNode), gets);
var LIMIT = 64;
function Ring(size) { this.count = 0; this.slots = new Array(size).fill(0); }
Ring.prototype.fill = function (owner) { for (var i = 0; i < LIMIT; i++) { this.count++; if (this.count > 9) this.count = 0; owner.slots[i] = this.count; } return owner.slots.slice(0, 12).join(''); };
var ring = new Ring(64), f;
for (var q = 0; q < 6; q++) f = ring.fill(ring);
console.log('ring', f, ring.count);
LIMIT = 10.5;
console.log('fractional limit', ring.fill(ring), ring.count);
LIMIT = '12';
console.log('string limit', ring.fill(ring), ring.count);
var other = { count: 'x', slots: [] };
LIMIT = 3;
console.log('string counter', Ring.prototype.fill.call(other, ring), other.count);
var frozenOwner = { slots: Object.freeze([7, 7, 7]) };
console.log('frozen owner', ring.fill(frozenOwner), ring.count);
''', cli=cli)


@tiers
def test_regexp_exec_loop_guards(run, workdir, cli):
    """CATCHES: the JIT's batched `for (var i = 0; i < N; i++) re.exec(strings[i]);` helper (re and
    strings are globals) when one of its guards fails: a different method name (test), a
    fractional constant limit, a start index that is fractional/negative/past the limit/a
    string, an undeclared array (ReferenceError), holes and non-string elements, an array-like,
    a fake regexp object, an own or patched exec, a read-only lastIndex (TypeError), a
    fractional lastIndex, sticky and non-global regexps and a null regexp -- the loop index,
    lastIndex and RegExp.lastMatch must match the plain loop exactly."""
    check_script(run, workdir, G, "regexp_exec_loop_guards", r'''
var re = /(\d)(\w)/g;
var strings = ['1a 2b', '3c', 'x', '4d5e6f'];
function scan4() { for (var i = 0; i < 4; i++) re.exec(strings[i]); return i + ':' + re.lastIndex + ':' + RegExp.lastMatch; }
function scanTest() { for (var i = 0; i < 4; i++) re.test(strings[i]); return i + ':' + re.lastIndex + ':' + RegExp.lastMatch; }
function scanFrac() { for (var i = 0; i < 2.5; i++) re.exec(strings[i]); return i + ':' + re.lastIndex; }
function scanFrom(start) { for (var i = start; i < 4; i++) re.exec(strings[i]); return i + ':' + re.lastIndex; }
function scanMissing() { for (var i = 0; i < 2; i++) re.exec(missingList[i]); return i; }
function show(label, f) { var out; try { for (var k = 0; k < 6; k++) { re.lastIndex = 0; out = f(); } } catch (e) { out = e.constructor.name; } console.log(label, out); }
show('plain', scan4);
show('test method', scanTest);
show('fractional limit', scanFrac);
show('start 1', function () { return scanFrom(1); });
show('start 1.5', function () { return scanFrom(1.5); });
show('start -1', function () { return scanFrom(-1); });
show('start 9', function () { return scanFrom(9); });
show('start str', function () { return scanFrom('2'); });
show('missing global', scanMissing);
strings = ['5g', , '6h', '7i'];
show('hole', scan4);
strings = ['5g', 8, '6h', null];
show('non-string', scan4);
strings = { 0: '1q', 1: '2w', 2: '3e', 3: '4r', length: 4 };
show('array-like', scan4);
strings = ['1a 2b', '3c', 'x', '4d5e6f'];
re = { exec: function (s) { return this.n = (this.n || 0) + s.length; }, lastIndex: 'n/a' };
show('fake regexp', scan4);
console.log('fake n', re.n);
re = /(\d)(\w)/g;
re.exec = function (s) { return RegExp.prototype.exec.call(this, s + '0z'); };
show('own exec', scan4);
re = /(\d)(\w)/g;
var origExec = RegExp.prototype.exec, n = 0;
RegExp.prototype.exec = function (s) { n++; return origExec.call(this, s); };
show('patched proto exec', scan4);
console.log('patched calls', n);
RegExp.prototype.exec = origExec;
re = /(\d)(\w)/g;
Object.defineProperty(re, 'lastIndex', { writable: false, value: 0 });
show('readonly lastIndex', scan4);
re = /(\d)(\w)/g;
re.lastIndex = 1.5;
console.log('fractional lastIndex', scan4(), re.lastIndex);
re = /(\d)(\w)/y;
show('sticky', scan4);
re = /\d/;
show('non-global', scan4);
re = null;
show('null regexp', scan4);
''', cli=cli)


@tiers
def test_linear_numeric_loops(run, workdir, cli):
    """CATCHES: the JIT's linear numeric-loop planner on shapes at its limits: `!==` / `!=` loop
    conditions, an expression nested deeper than its register stack, an array local that is
    swapped inside the loop (a pinned receiver must be re-validated), fourteen live integer
    locals (register pressure forces demotion), variable and constant shift counts, a discarded
    expression statement, and constant multiplications/divisions -- results must be identical
    to the plain loop, including when later called with doubles, strings, BigInts and short
    arrays."""
    check_script(run, workdir, G, "linear_numeric_loops", r'''
function neLoop(a, n) { var s = 0; for (var i = 0; i !== n; i++) s = s + a[i]; return s; }
function looseNe(a, n) { var s = 0; for (var i = 0; i != n; i++) s = s + a[i] * 2; return s; }
function deepExpr(a, n) { var s = 0; for (var i = 0; i < n; i++) { var x = a[i]; s = s + (x + (x * 2 + (x * 3 + (x * 4 + (x * 5 + (x * 6 + (x * 7 + (x * 8 + x)))))))); } return s; }
function swapRecv(a, b, n) { var s = 0; for (var i = 0; i < n; i++) { s = s + a[i]; var t = a; a = b; b = t; } return s; }
function manyInts(n) { var a = 1, b = 2, c = 3, d = 4, e = 5, f = 6, g = 7, h = 8, j = 9, k = 10, l = 11, m = 12, p = 13, q = 14; for (var i = 0; i < n; i++) { a = (a + b) & 1023; b = (b ^ c) + 1; c = (c + d) & 2047; d = (d | e) & 255; e = (e + f) ^ 3; f = (f + g) & 4095; g = (g ^ h) + 2; h = (h + j) & 511; j = (j + k) & 8191; k = (k ^ l) + 5; l = (l + m) & 1023; m = (m + p) & 63; p = (p ^ q) + i; q = (q + a) & 16383; } return [a, b, c, d, e, f, g, h, j, k, l, m, p, q].join(','); }
function varShift(a, n, k) { var s = 0; for (var i = 0; i < n; i++) s = (s + (a[i] << k) + (a[i] >> (k + 1)) + (a[i] >>> 2) + (i << 3)) | 0; return s; }
function popStmt(a, n) { var s = 0; for (var i = 0; i < n; i++) { s = s + a[i]; a[i] * 2; } return s; }
function constMul(a, n) { var s = 0; for (var i = 0; i < n; i++) { s = s + a[i] * 3 - 7 + a[i] / 2; } return s; }
var arr = [];
for (var z = 0; z < 64; z++) arr.push(z % 9);
var brr = [];
for (var z = 0; z < 64; z++) brr.push(z * 0.5);
var r;
for (var q = 0; q < 6; q++) r = [neLoop(arr, 64), looseNe(arr, 32), deepExpr(arr, 64), swapRecv(arr, brr, 64), manyInts(500), varShift(arr, 64, 3), popStmt(arr, 64), constMul(arr, 64)];
console.log(r.join('\n'));
console.log(neLoop([1, 2], 2), looseNe(['1', 2], 2), deepExpr([0.5], 1), swapRecv([1], [2], 2), varShift([1.5, -1], 2, 33), popStmt([], 0), constMul([1n], 0), manyInts(0));
console.log(neLoop([1.5, '2'], 2), deepExpr(['1'], 1), swapRecv(arr, ['x'], 3), varShift([2 ** 31, -(2 ** 31)], 2, 1), constMul([0.25, -0.5], 2));
try { constMul([1n], 1); } catch (e) { console.log(e.constructor.name); }
''', cli=cli)


@tiers
def test_string_length_limit(run, workdir, cli):
    """CATCHES: hot string concatenation (`s = s + s` in a compiled loop, `a + b + c` chains) that
    does not enforce the engine's maximum string length of 2^26 code units exactly: a string of
    exactly 67108864 characters must still be created, the next concatenation must throw
    `RangeError: Invalid string length` (catchable, leaving the variable intact), in every
    tier."""
    check_script(run, workdir, G, "string_length_limit", r'''
function grow(seed) { var s = seed, steps = 0; try { for (var i = 0; i < 40; i++) { s = s + s; steps++; } return 'no error'; } catch (e) { return e.name + ': ' + e.message + ' after ' + steps + ' len=' + s.length + ' head=' + s.slice(0, 4); } }
console.log(grow('ab'));
function growConcat() { var s = 'q'.repeat(1 << 25); try { var t = s + s + 'x'; return t.length; } catch (e) { return e.name + ': ' + e.message + ' ' + s.length; } }
console.log(growConcat());
''', cli=cli)


@tiers
def test_for_of_array_iteration_edges(run, workdir, cli):
    """CATCHES: compiled for-of over arrays that takes a dense shortcut where the Array Iterator
    protocol is observable: holes (and holes filled by Array.prototype), accessor elements,
    typed arrays, keys()/entries() iterators, strings with non-ASCII characters, arrays shrinking
    or growing during iteration, a partially consumed iterator resumed by for-of, a patched
    %ArrayIteratorPrototype%.next and an iterator with its own next."""
    check_script(run, workdir, G, "for_of_array_iteration_edges", r'''
function collect(it) { var out = []; for (var v of it) out.push(v === undefined ? 'u' : String(v)); return out.join(''); }
function shrinking(arr) { var out = []; for (var v of arr) { out.push(v); if (v === 2) arr.length = 3; } return out.join(''); }
function growing(arr) { var out = []; for (var v of arr) { out.push(v); if (arr.length < 6) arr.push(v * 10); } return out.join(','); }
var acc = [1, 2, 3];
Object.defineProperty(acc, 1, { get: function () { return 'G'; } });
var r;
for (var k = 0; k < 10; k++) r = [collect([1, 2, 3]), collect([1, , 3]), collect(acc), collect(new Uint8Array([7, 8])), collect([5, 6].keys()), collect([5, 6].entries()), collect('héllo'), collect(new Set([1, 1, 2])), shrinking([1, 2, 3, 4, 5]), growing([1, 2])];
console.log(r.join(' '));
Array.prototype[1] = 'P';
console.log('proto hole', collect([1, , 3]));
delete Array.prototype[1];
var it = [1, 2, 3][Symbol.iterator]();
it.next();
console.log('resumed', collect(it), JSON.stringify(collect(it)));
var AIP = Object.getPrototypeOf([][Symbol.iterator]());
var origNext = AIP.next, calls = 0;
AIP.next = function () { calls++; return origNext.call(this); };
console.log('patched', collect([4, 5, 6]), calls);
AIP.next = origNext;
var weird = [1, 2, 3][Symbol.iterator]();
Object.defineProperty(weird, 'next', { value: function () { return { done: this.n++ > 1, value: 'W' }; } });
weird.n = 0;
console.log('own next', collect(weird));
''', cli=cli)


@tiers
def test_inlined_call_sites(run, workdir, cli):
    """CATCHES: the one-shot inline recompile of a hot caller (called >100 times from compiled code)
    splicing callees it must not splice or splicing them wrongly: a call with more than eight
    arguments, a plain call to a `this`-using function, a callee reading a global that the
    caller shadows with a local of the same name, method calls with surplus or missing
    arguments, hoisted vars inside the callee, defaulted/rest parameters -- and stale splices
    after the call site turns polymorphic or the callee/method is replaced."""
    check_script(run, workdir, G, "inlined_call_sites", r'''
var SCALE = 3;
function two(a, b) { return a * 10 + b; }
function usesThis(x) { return (this === undefined || this === globalThis ? 'g' : 'o') + x; }
function readsGlobal(x) { return x * SCALE; }
var obj = {
  k: 2,
  one: function (a) { return this.k + a; },
  pair: function (a, b) { return this.k + ':' + a + ':' + b; },
  hoisty: function (a) { var t = a * 2; if (t > 4) { var u = t - 1; return u; } return t; },
  dflt: function (a, b = 5) { return a + b; },
  rest: function (a, ...r) { return a + r.length; },
};
function caller(i, o) {
  var SCALE = 100;
  return [two(i, 1, 2, 3, 4, 5, 6, 7, 8, 9), usesThis(i), readsGlobal(i), two(i, 2), o.one(i, 'extra', 'more'), o.pair(i), o.pair(), o.hoisty(i), o.dflt(i), o.rest(i, 1, 2), SCALE].join(':');
}
function driver(n, o) { var last; for (var i = 0; i < n; i++) last = caller(i % 5, o); return last; }
var out = [];
for (var k = 0; k < 4; k++) out.push(driver(150, obj));
console.log(out.join('\n'));
var other = { k: 'K', one: obj.one, pair: function (a, b) { return 'other' + a + b; }, hoisty: obj.hoisty, dflt: obj.dflt, rest: obj.rest };
console.log(driver(4, other));
for (var k = 0; k < 2; k++) console.log(driver(150, k ? obj : other));
SCALE = 5;
two = function (a, b) { return a - b; };
obj.one = function (a) { return 'swapped' + a; };
console.log(driver(3, obj));
console.log(caller(7, obj));
''', cli=cli)
