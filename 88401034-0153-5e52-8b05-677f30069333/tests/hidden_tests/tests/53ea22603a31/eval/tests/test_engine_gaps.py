"""Second-wave gap tests for the evaluation core (tree-walking interpreter in eval.rs/interpreter.rs
and the parser): rarely-taken branches of `with` scoping, destructuring assignment, optional-chain
deletes and calls, BigInt shifts, class elements and decorators, private-name brands, async
iteration protocol errors, dynamic-import options, direct-eval declaration conflicts, REPL global
declaration checks, a catalogue of script/module early errors, property writes through proxies,
typed arrays and foreign receivers, the cycle collector with `with` scopes and import bindings,
`using` disposal, `super` with a null home prototype, proper tail calls, and builtin subclassing.
Most programs run on the tree-walker (`--tier=interp`); where the tiers agree observably a test
is parametrized over tiers against ONE shared golden."""

import json

import pytest

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)

INTERP = ["--tier=interp"]
TWO_TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp")]

# Shared prologue: run a labelled thunk and print its result or the exact error it throws.
PRELUDE = r'''
const out = [];
const t = (label, f) => { try { out.push(label + ': ' + String(f())); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } };
const tA = async (label, f) => { try { out.push(label + ': ' + String(await f())); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } };
'''


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_with_scope_vanishing_bindings_and_primitive_objects(run, workdir, cli):
    """CATCHES: `with` reference semantics done wrong: a property deleted by an @@unscopables getter
    must make strict code throw ReferenceError on read/write but give undefined in sloppy code;
    var/destructuring/for-of writes inside `with` must land on the object; non-configurable,
    inherited and unscopable deletes; proxy has-trap errors and invariants; `with (null)` TypeError.
    Pins reference quirks: strict `typeof` of a vanished with-binding is "undefined" and a
    primitive `with` operand is not boxed (its properties are not in scope)."""
    check_script(run, workdir, G, "with_scope_edges", PRELUDE + r'''
function vanishing() {
  const o = { v: 'here' };
  Object.defineProperty(o, Symbol.unscopables, { get() { delete o.v; return undefined; }, configurable: true });
  return o;
}
var v = 'outer v';
with (vanishing()) { t('sloppy read vanished', () => v); }
with (vanishing()) { t('strict read vanished', () => (function () { 'use strict'; return v; })()); }
let o1; with (o1 = vanishing()) { t('sloppy write vanished', () => { v = 'recreated'; return o1.v; }); }
let o2; with (o2 = vanishing()) { t('strict write vanished', () => (function () { 'use strict'; v = 'nv'; })()); }
t('after strict write', () => 'o2.v=' + String(o2.v) + ' outer v=' + v);
with (vanishing()) { t('strict typeof vanished', () => (function () { 'use strict'; return typeof v; })()); }
const counter = { n: 1 };
with (counter) { t('strict compound via with', () => (function () { 'use strict'; n += 5; n++; return n; })()); }
const wo = { a: 0, b: 0, c: 0, k: 'none' };
with (wo) { var a = 'var-init'; [b, c] = ['d1', 'd2']; for (k of ['x', 'y']) ; var [notOnWo] = ['own var']; }
t('with var/destructure/for-of writes', () => JSON.stringify(wo) + ' a=' + typeof a + ' notOnWo=' + notOnWo);
t('with delete frozen', () => { with (Object.freeze({ fx: 1 })) { return delete fx; } });
t('with delete inherited', () => { const o = Object.create({ inh: 1 }); with (o) { return [delete inh, 'inh' in o].join(); } });
t('with delete unscopable', () => { var us = 'outer'; const o = { us: 1, [Symbol.unscopables]: { us: true } }; with (o) { return [delete us, 'us' in o].join(); } });
t('with unscopables primitive ignored', () => { const q = 'outer q'; with ({ q: 'inner q', [Symbol.unscopables]: 5 }) { return q; } });
t('with unscopables getter throws', () => { with ({ q: 1, get [Symbol.unscopables]() { throw new Error('unscopables getter'); } }) { return q; } });
t('with proxy has trap throws', () => { with (new Proxy({}, { has() { throw new Error('has trap'); } })) { return someName; } });
t('with revoked proxy', () => { const { proxy, revoke } = Proxy.revocable({}, {}); revoke(); with (proxy) { return someName; } });
t('with proxy has not callable', () => { with (new Proxy({}, { has: 1 })) { return someName; } });
t('with proxy hides non-configurable', () => { const tgt = Object.defineProperty({}, 'fixedName', { value: 1 }); with (new Proxy(tgt, { has() { return false; } })) { return fixedName; } });
t('with null', () => { with (null) {} });
t('with undefined', () => { with (undefined) ; });
t('with primitive number', () => { with (5) { return toFixed(1); } });
t('with primitive string', () => { with ('abc') { return charAt(1); } });
t('strict undeclared inside with', () => { with ({}) { return (function () { 'use strict'; undeclaredZ = 1; })(); } });
console.log(out.join('\n'));
''', cli=cli)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_destructuring_assignment_targets_and_iterator_closing(run, workdir, cli):
    """CATCHES: destructuring *assignment* (not declaration) bugs: holes that must step (and close)
    the iterator, nested rest patterns, defaults naming anonymous functions/classes, `__proto__`
    as a plain key, member/super/private targets, getter/setter evaluation order, closing the
    iterator when a generator is returned mid-pattern (and a non-object `return` result), and
    call-expression targets (early SyntaxError in patterns, runtime ReferenceError in sloppy
    plain/compound/update/for-of forms), patterns writing a named function expression's own name
    (silently ignored in sloppy code, TypeError in strict) or a const. Pins reference quirks: the
    message for destructuring `undefined` leaks an internal key ' 1', and a binding deleted by
    the RHS of its own assignment is re-created on the global object."""
    check_script(run, workdir, G, "destructuring_assignment", PRELUDE + r'''
let p, q, r;
t('holes and nested rest', () => { [, , p, ...[q, r]] = 'abcdef'; return [p, q, r].join(); });
t('rest into object pattern', () => { [...{ length: p, 0: q }] = 'xyz'; return [p, q].join(); });
const logIter = (log, limit) => ({ [Symbol.iterator]() { let n = 0; return { next() { log.push('next' + n); return { value: n, done: n++ >= limit }; }, return() { log.push('return'); return {}; } }; } });
t('lone hole closes iterator', () => { const log = []; [,] = logIter(log, 9); return log.join(); });
t('holes past exhaustion', () => { const log = []; [p, , , q] = logIter(log, 1); return log.join() + ' ' + p + ' ' + q; });
t('default fn naming (array)', () => { let f, g; [f = function () {}, g = () => {}] = []; return f.name + ',' + g.name; });
t('default fn naming (object)', () => { let f, g, h; ({ f = function () {}, x: g = class {}, h = async () => {} } = {}); return [f.name, g.name, h.name].join(); });
t('destructure null', () => { ({ p } = null); });
t('destructure undefined iterable', () => { [p] = undefined; });
t('__proto__ as plain key', () => { let pr; ({ __proto__: pr } = []); return pr === Array.prototype; });
t('__proto__ with default', () => { let pr; ({ __proto__: pr = 5 } = Object.create(null)); return pr; });
t('object rest keeps symbols', () => { let rest; ({ a: p, ...rest } = { a: 1, b: 2, [Symbol.for('s')]: 3 }); return JSON.stringify(rest) + ' symbols=' + Object.getOwnPropertySymbols(rest).length; });
t('member targets', () => { const o = {}; [o.x, o['y'], ...o.z] = [1, 2, 3, 4]; ({ m: o.m = 9 } = {}); return JSON.stringify(o); });
t('super targets', () => { const base = { set sx(v) { out.push('  base setter got ' + v); } }; const obj = { __proto__: base, m() { [super.sx, super['sy']] = [1, 2]; ({ k: super.sz } = { k: 3 }); return JSON.stringify(this); } }; return obj.m(); });
t('private targets', () => { class C { #p = 0; m() { [this.#p] = [42]; ({ v: this.#p } = { v: this.#p + 1 }); return this.#p; } } return new C().m(); });
t('get/set order', () => { const log = []; const src = { get a() { log.push('get a'); return 1; }, get b() { log.push('get b'); return 2; } }; const tgt = { set x(v) { log.push('set x ' + v); }, set y(v) { log.push('set y ' + v); } }; ({ a: tgt.x, b: tgt.y } = src); return log.join(); });
const undefIter = (log, ret) => ({ [Symbol.iterator]() { return { next() { return { value: undefined, done: false }; }, return() { log.push('src closed'); return ret; } }; } });
t('generator return during binding default', () => { const log = []; function* g() { const [a = yield 'paused'] = undefIter(log, {}); log.push('unreached'); } const it = g(); log.push(JSON.stringify(it.next())); log.push(JSON.stringify(it.return('R'))); return log.join(' '); });
t('generator return during assignment default', () => { const log = []; let a; function* g() { [a = yield 'paused'] = undefIter(log, {}); } const it = g(); it.next(); log.push(JSON.stringify(it.return('R2'))); return log.join(' '); });
t('return() result not an object (binding)', () => { function* g() { const [a = yield 'p'] = undefIter([], 5); } const it = g(); it.next(); return JSON.stringify(it.return('R3')); });
t('return() result not an object (assignment)', () => { let a; function* g() { [a = yield 'p'] = undefIter([], 5); } const it = g(); it.next(); return JSON.stringify(it.return('R4')); });
t('pattern into named fn expr name', () => { const f = function nm() { [nm] = [5]; ({ k: nm } = { k: 6 }); for (nm in { a: 1 }) ; return typeof nm; }; return f(); });
t('pattern into named fn expr name (strict)', () => { const f = function nm() { 'use strict'; [nm] = [5]; }; return f(); });
t('pattern into const', () => { const c = 1; [c] = [2]; });
t('assign after eval var deleted by RHS', () => { function f() { eval('var evalMade = 1'); evalMade = (delete evalMade, 7); return [evalMade, globalThis.evalMade, delete globalThis.evalMade].join(); } return f(); });
t('call target in pattern', () => eval('function f() {} [f()] = [1];'));
t('call target in for-of', () => eval('function f() {} for (f() of [1]) ;'));
t('plain call target', () => eval('function f() { out.push("  f2 called"); } f() = 1;'));
t('compound call target', () => eval('function f() { out.push("  f called"); } f() += 1;'));
t('update call target', () => eval('function f() { out.push("  f3 called"); } f()++;'));
t('logical call target', () => eval('function f() { return {}; } f() ??= 1;'));
console.log(out.join('\n'));
''', cli=cli)


def test_optional_chain_delete_calls_and_bigint_operator_edges(run, workdir):
    """CATCHES: short-circuiting optional chains that still evaluate (or throw on) the rest of the
    chain under `delete` and calls, `(a?.b)()` keeping the receiver but throwing when short-
    circuited (after evaluating arguments), deletes of null bases and super properties (key
    evaluated first), BigInt shifts by 2**30+ bits (sign-filled result or RangeError), mixing
    BigInt with Number, loose/relational comparisons of BigInt with strings/objects/infinities,
    instanceof with Symbol.hasInstance / bad prototypes, and proxy deleteProperty invariants."""
    check_script(run, workdir, G, "optional_delete_bigint", PRELUDE + r'''
const n = null, o = { b: { c: 1 }, m() { return this === o; } };
t('delete through short-circuit', () => [delete n?.b.c, delete n?.b?.c, delete n?.[0][1], delete n?.b['c']].join());
t('delete optional on live object', () => { const x = { b: { c: 1 } }; return [delete x?.b.c, JSON.stringify(x)].join(' '); });
t('delete null member', () => delete n.x);
t('delete null index', () => { let k = 0; return delete n[k++]; });
t('delete super index', () => { const obj = { __proto__: { k: 1 }, m() { const keys = []; try { delete super[(keys.push('key evaluated'), 'k')]; } catch (e) { return keys.join() + ' ' + e.name + ': ' + e.message; } } }; return obj.m(); });
t('delete global non-configurable names', () => [delete NaN, delete undefined, delete neverDeclaredAnywhere].join());
t('parenthesized optional call keeps this', () => (o?.m)());
t('parenthesized optional call short-circuits', () => { const log = []; try { (n?.m)(log.push('arg evaluated')); } catch (e) { return log.join() + ' -> ' + e.name + ': ' + e.message; } });
t('optional member call short', () => String(n?.b.c()) + String(n?.b[0]()) + String(n?.b.c.d()));
t('optional mixed results', () => [o.b?.c, o?.m(), o.zz?.(), (n?.b)?.c].join());
t('bigint huge right shifts', () => [1n >> (2n ** 40n), -1n >> (2n ** 40n), -12345n >> (2n ** 31n), 7n << -(2n ** 40n), 0n << (2n ** 40n)].join());
t('bigint huge left shift', () => 1n << (2n ** 31n));
t('bigint plus number', () => 1n + 1);
t('unary plus bigint', () => +1n);
t('unary plus boxed bigint', () => +Object(1n));
t('compound bigint ops', () => { let x = 10n; x **= 2n; x %= 7n; x <<= 3n; x >>= 1n; x &= 0xffn; x |= 1n; x ^= 3n; return x; });
t('loose equality with objects', () => [1n == Object(1n), 2n == { valueOf() { return 2n; } }, 1 == { valueOf() { return 1; } }, Symbol.iterator == Object(Symbol.iterator), 1n == { valueOf() { return '1'; } }, 0 == [[]]].join());
t('loose equality bigint/string', () => [1n == '1', 1n == '1.5', 10n == '0xa', 1n == 'x', 2n == 2.5, 2n == NaN, 1n == true].join());
t('relational bigint', () => [1n < 1.5, 2n > '1', '10' > 9n, 1n < 'x', 1n <= NaN, (2n ** 64n) > Infinity, -Infinity < -(2n ** 64n)].join());
t('instanceof hasInstance', () => { const H = { [Symbol.hasInstance](v) { return v === 1; } }; return [1 instanceof H, 2 instanceof H].join(); });
t('instanceof hasInstance not callable', () => 1 instanceof { [Symbol.hasInstance]: 5 });
t('instanceof primitive rhs', () => 1 instanceof 5);
t('instanceof plain object rhs', () => ({}) instanceof {});
t('instanceof bad prototype', () => { function F() {} F.prototype = 3; return ({}) instanceof F; });
t('proxy delete forwards to nested proxy', () => { const log = []; const inner = new Proxy({ k: 1 }, { deleteProperty(tg, k) { log.push('inner trap ' + k); return delete tg[k]; } }); return [delete new Proxy(inner, {}).k, log.join()].join(' '); });
t('proxy delete forward non-configurable', () => delete new Proxy(Object.defineProperty({}, 'nc', { value: 1 }), {}).nc);
t('proxy delete trap not callable', () => delete new Proxy({}, { deleteProperty: 'x' }).a);
t('proxy delete non-extensible invariant', () => delete new Proxy(Object.preventExtensions({ ne: 1 }), { deleteProperty() { return true; } }).ne);
t('proxy delete revoked', () => { const { proxy, revoke } = Proxy.revocable({}, {}); revoke(); return delete proxy.a; });
console.log(out.join('\n'));
''', cli=INTERP)


def test_class_element_errors_decorators_and_private_brands(run, workdir):
    """CATCHES: missing runtime checks in class definition evaluation: a computed static key equal to
    "prototype", non-callable decorators and decorators returning the wrong kind of value for
    methods/fields/accessors/classes/getters, addInitializer with a non-callable, decorator
    `context.access` get/set (pins that the reference provides no `access.has`), decorated
    static/private auto-accessors and getters, auto-accessor getters/setters called on unrelated
    objects, and private-brand errors via the constructor return-override trick (non-extensible
    targets, methods stamped twice, undeclared/read-only private writes)."""
    check_script(run, workdir, G, "class_decorator_private_errors", PRELUDE + r'''
t('computed static prototype method', () => { const k = 'proto' + 'type'; class C { static [k]() {} } });
t('computed static prototype field', () => { const k = 'prototype'; class C { static [k] = 1; } });
t('computed instance prototype ok', () => { const k = 'prototype'; class C { [k]() { return 'inst'; } } return new C().prototype(); });
t('symbol-keyed static names', () => { const s = Symbol('sym'); class C { static [s]() {} static get [Symbol.iterator]() { return 1; } } return C[s].name + '|' + Object.getOwnPropertyDescriptor(C, Symbol.iterator).get.name; });
t('method decorator not callable', () => { const d = 5; class C { @d m() {} } });
t('field decorator not callable', () => { const d = {}; class C { @d f = 1; } });
t('accessor decorator not callable', () => { const d = 'x'; class C { @d accessor a = 1; } });
t('class decorator not callable', () => { const d = null; @d class C {} });
t('method decorator returns number', () => { class C { @((v) => 5) m() {} } });
t('field decorator returns object', () => { class C { @((v) => ({})) f = 1; } });
t('accessor decorator returns number', () => { class C { @((v) => 7) accessor a = 1; } });
t('class decorator returns string', () => { @((v) => 'str') class C {} });
t('getter decorator returns object', () => { class C { @((v) => ({})) get g() { return 1; } } });
t('addInitializer non-callable', () => { class C { @((v, ctx) => { ctx.addInitializer(42); }) m() {} } });
t('field access get/set', () => { let acc; class C { @((v, ctx) => { acc = ctx.access; }) f = 'field value'; } const c = new C(); const before = acc.get(c); acc.set(c, 'changed'); return [before, c.f, typeof acc.has].join(); });
t('private/static field access', () => { let a1, a2; class C { @((v, ctx) => { a1 = ctx.access; }) static #sp = 's'; @((v, ctx) => { a2 = ctx.access; }) #ip = 'i'; static read(o) { return o.#ip; } } const c = new C(); a2.set(c, 'set via access'); return [a1.get(C), C.read(c)].join(); });
t('getter decorator access', () => { let a; class C { @((v, ctx) => { a = ctx.access; }) get g() { return 'got ' + this.tag; } tag = 't'; } return a.get(new C()) + ' hasSet=' + ('set' in a); });
t('setter decorator access', () => { let a; class C { @((v, ctx) => { a = ctx.access; }) set s(v) { this.stored = v; } } const c = new C(); a.set(c, 9); return c.stored + ' hasGet=' + ('get' in a); });
t('decorated static auto-accessor', () => { class C { @((v, ctx) => ({ get() { return v.get.call(this) * 2; }, set(x) { v.set.call(this, x); }, init(x) { return x + 1; } })) static accessor sa = 10; } const r1 = C.sa; C.sa = 3; return [r1, C.sa].join(); });
t('decorated private auto-accessor', () => { class C { @((v, ctx) => ({ init(x) { return x + '!'; } })) accessor #pa = 'p'; read() { return this.#pa; } } return new C().read(); });
t('decorated static method', () => { class C { @((v, ctx) => function () { return 'wrapped ' + ctx.name + ' static=' + ctx.static; }) static sm() {} } return C.sm(); });
t('decorated private getter', () => { class C { @((v, ctx) => function () { return 'dec ' + v.call(this); }) get #pg() { return 'pg'; } read() { return this.#pg; } } return new C().read(); });
t('decorated static field + initializer', () => { const log = []; class C { @((v, ctx) => { ctx.addInitializer(function () { log.push('static init this=' + (this === C)); }); return (x) => x * 3; }) static sf = 2; } return C.sf + ' ' + log.join(); });
t('auto-accessor getter on unrelated object', () => { class C { accessor a = 1; } return Object.getOwnPropertyDescriptor(C.prototype, 'a').get.call({}); });
t('auto-accessor setter on unrelated object', () => { class C { accessor a = 1; } return Object.getOwnPropertyDescriptor(C.prototype, 'a').set.call({}, 2); });
class Base { constructor(o) { return o; } }
class Stamp extends Base { #f = 1; static read(o) { return o.#f; } }
class Meth extends Base { #m() { return 'm'; } }
class Acc extends Base { get #g() { return 'g'; } }
t('private field on frozen object', () => { new Stamp(Object.freeze({})); });
t('private field on proxy object', () => { const p = new Proxy({}, {}); new Stamp(p); return Stamp.read(p); });
t('private methods stamped twice', () => { const o = {}; new Meth(o); new Meth(o); });
t('private methods on non-extensible', () => { new Meth(Object.preventExtensions({})); });
t('private accessor on sealed', () => { new Acc(Object.seal({})); });
t('static private field after sealing ctor', () => { class C { static a = Object.seal(C); static #p = 1; } });
t('write undeclared private', () => { class A { #x; static w(o) { o.#x = 1; } } A.w({}); });
t('write private method', () => { class A { #m() {} static w(o) { o.#m = 1; } } A.w(new A()); });
t('write getter-only private', () => { class A { get #g() { return 1; } static w(o) { o.#g = 1; } } A.w(new A()); });
t('read setter-only private', () => { class A { set #s(v) {} static r(o) { return o.#s; } } return A.r(new A()); });
console.log(out.join('\n'));
''', cli=INTERP)


def test_async_iteration_protocol_errors(run, workdir):
    """CATCHES: for-await and (async) yield* not validating the iterator protocol: a non-callable or
    primitive-returning @@asyncIterator, a null @@asyncIterator falling back to the sync iterator,
    sync values whose promise `constructor` getter throws (or that reject) closing the sync source,
    non-callable/non-object `return` on break, `throw`/`return` delegation checks, a rejected
    return() value turned into a throw, and non-object next() results. Pins reference quirks:
    async yield* treats a non-callable `throw` as missing and silently ignores a non-callable
    `return`."""
    check_script(run, workdir, G, "async_iteration_errors", PRELUDE + r'''
const asyncIt = (extra) => ({ [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 1, done: false }); }, ...extra }; } });
const syncIt = (extra, value = 1) => ({ [Symbol.iterator]() { return { next() { return { value, done: false }; }, ...extra }; } });
async function* dg(src) { return yield* src; }
function* sg(src) { return yield* src; }
(async () => {
  await tA('for-await non-callable @@asyncIterator', async () => { for await (const x of { [Symbol.asyncIterator]: 1 }) ; });
  await tA('for-await @@asyncIterator returns primitive', async () => { for await (const x of { [Symbol.asyncIterator]() { return 3; } }) ; });
  await tA('for-await null @@asyncIterator uses sync', async () => { const r = []; for await (const x of { [Symbol.asyncIterator]: null, *[Symbol.iterator]() { yield 'a'; yield Promise.resolve('b'); } }) r.push(x); return r.join(); });
  await tA('for-await poisoned constructor closes sync', async () => {
    const p = Promise.resolve(1); Object.defineProperty(p, 'constructor', { get() { throw new Error('ctor getter'); } });
    const log = []; try { for await (const x of syncIt({ return() { log.push('closed'); return {}; } }, p)) ; } catch (e) { return e.message + ' ' + log.join(); }
  });
  await tA('for-await rejection closes sync', async () => { const log = []; try { for await (const x of syncIt({ return() { log.push('closed'); return {}; } }, Promise.reject(new Error('rej')))) ; } catch (e) { return e.message + ' ' + log.join(); } });
  await tA('break: return not callable', async () => { for await (const x of asyncIt({ return: 5 })) break; });
  await tA('break: return gives primitive', async () => { for await (const x of asyncIt({ return() { return 5; } })) break; });
  await tA('break: sync return gives primitive', async () => { for await (const x of syncIt({ return() { return 5; } })) break; });
  await tA('break: sync return value awaited', async () => { const log = []; for await (const x of syncIt({ return() { log.push('ret'); return { value: Promise.resolve('rv') }; } })) break; return log.join(); });
  await tA('async yield* non-callable @@asyncIterator', async () => { await dg({ [Symbol.asyncIterator]: 7 }).next(); });
  await tA('async yield* @@asyncIterator returns primitive', async () => { await dg({ [Symbol.asyncIterator]() { return 'x'; } }).next(); });
  await tA('async yield* throw not callable', async () => { const g = dg(asyncIt({ throw: 3 })); await g.next(); await g.throw(new Error('E')); });
  await tA('async yield* return not callable', async () => { const g = dg(asyncIt({ return: 3 })); await g.next(); return JSON.stringify(await g.return('R')); });
  await tA('async yield* next gives primitive', async () => { const g = dg({ [Symbol.asyncIterator]() { return { next() { return Promise.resolve(9); } }; } }); await g.next(); });
  await tA('async yield* return(rejected)', async () => { const g = dg(asyncIt({})); await g.next(); return JSON.stringify(await g.return(Promise.reject(new Error('rejected ret')))); });
  await tA('async gen return(rejected) runs finally', async () => { async function* g() { try { yield 1; } finally { out.push('  finally ran'); } } const it = g(); await it.next(); return JSON.stringify(await it.return(Promise.reject(new Error('rr')))); });
  t('sync yield* throw not callable', () => { const g = sg(syncIt({ throw: 4 })); g.next(); g.throw(new Error('E')); });
  t('sync yield* return not callable', () => { const g = sg(syncIt({ return: 4 })); g.next(); g.return('R'); });
  t('sync yield* return gives primitive', () => { const g = sg(syncIt({ return() { return 1; } })); g.next(); g.return('R'); });
  t('sync yield* without return', () => { const g = sg(syncIt({})); g.next(); return JSON.stringify(g.return('R')); });
  t('sync yield* next gives primitive', () => { const g = sg({ [Symbol.iterator]() { return { next() { return 2; } }; } }); g.next(); });
  t('@@iterator returns primitive', () => { for (const x of { [Symbol.iterator]() { return 1; } }) ; });
  t('destructure: return not callable', () => { const [a] = syncIt({ return: 1 }); return a; });
  t('destructure: return gives null', () => { const [a] = syncIt({ return() { return null; } }); return a; });
  t('for-of break: return not callable', () => { for (const x of syncIt({ return: 'str' })) break; });
  t('destructure non-iterable', () => { const [a] = {}; });
  t('spread non-iterable', () => [...{}]);
  t('destructure next gives primitive', () => { const [a] = { [Symbol.iterator]() { return { next() { return 1; } }; } }; });
  console.log(out.join('\n'));
})();
''', cli=INTERP)


def test_dynamic_import_options_attributes_and_phases(run, workdir):
    """CATCHES: import() not validating its options bag (non-object options or `with`, non-string
    attribute values), not ignoring undefined/symbol-keyed/non-enumerable attributes, not walking a
    Proxy `with` object via ownKeys/getOwnPropertyDescriptor/get, swallowing abrupt specifier or
    `with` getter completions instead of rejecting, string-keyed attribute clauses, plus
    `import.source` rejecting with SyntaxError while `import.defer` evaluates on first access."""
    write_files(workdir, {
        "dep.mjs": "export const v = 'dep value';\n",
        "data.json": '{"k": "json k"}\n',
        "static_attr.mjs": "import x from './data.json' with { \"type\": \"json\" };\nexport default x.k;\n",
    })
    check_script(run, workdir, G, "dynamic_import_options", PRELUDE + r'''
await tA('options primitive', () => import('./dep.mjs', 5));
await tA('options undefined', async () => (await import('./dep.mjs', undefined)).v);
await tA('with undefined', async () => (await import('./dep.mjs', { with: undefined })).v);
await tA('with primitive', () => import('./dep.mjs', { with: 'json' }));
await tA('attribute value not a string', () => import('./dep.mjs', { with: { type: 1 } }));
await tA('json attribute', async () => JSON.stringify((await import('./data.json', { with: { type: 'json' } })).default));
await tA('proxy with object', async () => { const log = []; const p = new Proxy({ type: 'json' }, { ownKeys(tg) { log.push('ownKeys'); return Reflect.ownKeys(tg); }, getOwnPropertyDescriptor(tg, k) { log.push('gopd ' + String(k)); return Reflect.getOwnPropertyDescriptor(tg, k); }, get(tg, k) { log.push('get ' + String(k)); return tg[k]; } }); const m = await import('./data.json', { with: p }); return log.join() + ' -> ' + m.default.k; });
await tA('proxy with bad value', () => import('./dep.mjs', { with: new Proxy({ type: 2 }, {}) }));
await tA('proxy with skips non-enumerable', async () => (await import('./dep.mjs', { with: new Proxy(Object.defineProperty({}, 'type', { value: 1, enumerable: false }), {}) })).v);
await tA('non-enumerable attribute skipped', async () => (await import('./dep.mjs', { with: Object.defineProperty({}, 'type', { value: 1, enumerable: false }) })).v);
await tA('symbol attribute ignored', async () => (await import('./dep.mjs', { with: { [Symbol('s')]: 1 } })).v);
await tA('specifier toString throws', () => import({ toString() { throw new Error('spec boom'); } }));
await tA('with getter throws', () => import('./dep.mjs', { get with() { throw new Error('with boom'); } }));
await tA('string-keyed static attributes', async () => (await import('./static_attr.mjs')).default);
await tA('source phase', () => import.source('./dep.mjs'));
await tA('defer phase', async () => { const ns = await import.defer('./dep.mjs'); return ns.v; });
console.log(out.join('\n'));
''', filename="dynamic_import_options.mjs", cli=INTERP)


def test_direct_eval_declaration_conflicts_and_contexts(run, workdir):
    """CATCHES: direct eval not enforcing EvalDeclarationInstantiation: a var/function hoisting over
    a block let/const or a parameter-scope `arguments` (catch params and `with` are exempt),
    `arguments` inside class field initializers (an arrow does not shield, a function does),
    super()/super.x/new.target availability by context, strict indirect eval getting its own var
    scope, non-string arguments returned as-is, completion values, private names, Annex B block
    functions re-created after their eval-made var binding was deleted."""
    check_script(run, workdir, G, "direct_eval_contexts", PRELUDE + r'''
t('var over block let', () => { { let blk = 1; eval('var blk = 2'); } });
t('function over block const', () => { { const kk = 1; eval('function kk() {}'); } });
t('var over catch param is allowed', () => { try { throw 1; } catch (cp) { eval('var cp = 5'); return cp; } });
t('var inside with is allowed', () => { with ({}) { eval('var inWith = 3'); } return inWith; });
t('var arguments in parameter scope', () => (function (a = eval('var arguments = 1')) { return typeof arguments; })());
t('arguments in field initializer', () => { class C { f = eval('arguments'); } new C(); });
t('arguments in field arrow', () => { class C { f = () => eval('arguments.length'); } return new C().f(); });
t('arguments shielded by function', () => { class C { f = function () { return eval('arguments.length'); }; } return new C().f(1, 2); });
t('super() in method', () => { class B {} class D extends B { m() { return eval('super()'); } } new D().m(); });
t('super() in plain function', () => { function f() { eval('super()'); } f(); });
t('super.x in plain function', () => { function f() { return eval('super.x'); } f(); });
t('super.x in arrow in method', () => { const o = { __proto__: { x: 'px' }, m() { return (() => eval('super.x'))(); } }; return o.m(); });
t('super.x in field initializer', () => { class B { get bx() { return 'bx'; } } class D extends B { f = eval('super.bx'); } return new D().f; });
t('super() via arrow in constructor', () => { class B { constructor() { this.b = 1; } } class D extends B { constructor() { const go = () => eval('super()'); go(); } } return new D().b; });
t('new.target in arrow', () => { function F() { return (() => eval('new.target'))() === F; } return new F() instanceof F; });
t('new.target at global', () => (0, eval)('new.target'));
t('strict indirect eval var scope', () => { (0, eval)('"use strict"; var strictIndirect = 1'); return typeof strictIndirect; });
t('non-string arguments', () => [eval(5), eval({ a: 1 }).a, eval(), typeof eval(Symbol.iterator), typeof eval(new String('1+1'))].join());
t('completion values', () => [eval('1; if (true) {}'), eval('2; do { 3; break; } while (false)'), eval('var zz = 9'), eval('l: { 4; break l; }')].join('|'));
t('param default eval var', () => (function (a = eval('var pv = 7'), b = pv) { return b + typeof pv; })());
t('private name via eval', () => { class C { #p = 'priv'; m() { return eval('this.#p'); } } return new C().m(); });
t('undeclared private via eval', () => { class C { m() { return eval('this.#nope'); } } return new C().m(); });
t('Annex B fn var re-created after delete', () => { function f() { eval('delete bf; { function bf() { return "bf"; } }'); return typeof bf + ' ' + bf() + ' ' + delete bf + ' ' + typeof bf; } return f(); });
t('Annex B global fn re-created after delete', () => { (0, eval)('delete annexG; { function annexG() { return "ag"; } }'); return typeof annexG + ' ' + Object.getOwnPropertyDescriptor(globalThis, 'annexG').configurable; });
console.log(out.join('\n'));
''', cli=INTERP)


def test_repl_global_declaration_checks(run):
    """CATCHES: script-level GlobalDeclarationInstantiation across REPL inputs: a function declared
    over an existing configurable global must be redefined (enumerable, typeof function), one over
    a non-configurable read-only property (or NaN) is a TypeError, and once the global object is
    non-extensible new vars/functions are TypeErrors while redeclaring an existing var works; a
    top-level `using` in script code is a SyntaxError."""
    src = (
        'globalThis.cfgFn = 1\n'
        'function cfgFn() { return "fn"; }\n'
        'typeof cfgFn + " " + Object.getOwnPropertyDescriptor(globalThis, "cfgFn").enumerable\n'
        'Object.defineProperty(globalThis, "ro", { value: 1, writable: false, configurable: false }), "defined"\n'
        'function ro() {}\n'
        'function NaN() {}\n'
        'Object.preventExtensions(globalThis), "prevented"\n'
        'var brandNew = 1\n'
        'function brandNewFn() {}\n'
        'var cfgFn = 5\n'
        'cfgFn\n'
        'typeof brandNew + " " + typeof brandNewFn\n'
        'using topLevelUsing = null\n'
    )
    assert_result(run(["repl"], input=src), G / "repl_global_declarations.golden")


SCRIPT_SYNTAX_CASES = {
    "statements": [
        '({if})', '"use strict"; ({implements})', 'function* g() { ({yield}); }', 'async function g() { ({await}); }',
        'debugger; return "after debugger"', 'l: function* g() {}', 'l1: l2: function* g() {}',
        'l: async function f() {}', 'if (1) l: function f() {}', 'using [a] = null;', 'do x; foo',
        'for (const x; ;) ;', 'for (let [let] of []) ;', 'for (async of []) ;', 'switch (1) { foo: 1 }', '#x: 1',
        'function #x() {}', 'let #x = 1;', 'function* g() { var yield; }', 'function f(a) { let a; }',
        '(a) => { let a; }', 'function f(implements) { "use strict"; }', 'class implements {}',
        'class C extends (function () { with ({}) {} }) {}', '{ var y; function y() {} }', 'l: function f( {}',
        'let { "a" } = {};', 'return function (o) { return #x in o; }',
        'class C { ;;; m() { return "m"; } ;; } return new C().m();',
    ],
    "expressions": [
        'async function f() { aw\\u0061it 1; }', 'async function f() { await 2 ** 2; }', 'return delete undefined',
        'class B {} class C extends B { m() { return super.#x; } }', 'function f() { new.t\\u0061rget; }',
        'async function f() { new await 1; }', 'new import("x")', 'new a?.b()', '({ async\n m() {} })',
        '({ async x: 1 })', '({ *x: 1 })', '({ m() { super(); } })', '(function* yield() {})',
        '(async function await() {})', 'class C { f = arguments; }', 'class C { static { arguments; } }',
        'class C { static { super(); } }', 'class C { m() { this.#nope; } }', '({"a"} = {})', '++(a, b)',
        '"use strict"; f()++', 'a?.b`x`', 'var x; (x) = function () {}; return JSON.stringify(x.name);',
        'var x; (x) = class {}; return x.name + "|" + (x = class {}).name;',
        'var x; (x) ??= function () {}; return JSON.stringify(x.name);', 'class C { @if m() {} }',
        'class C { @1 m() {} }', 'function* g() { yi\\u0065ld; }', '"use strict"; function f() { let package; }',
        'class C { static { return; } }',
    ],
}


@pytest.mark.parametrize("group", ["statements", "expressions"])
def test_script_syntax_errors_catalogue(run, workdir, group):
    """CATCHES: a parser that accepts (or reports with different messages) rare early errors:
    reserved/contextual words as shorthand properties, labelled generators, `using` followed by
    `[` (a member expression, not a declaration), for-head declarations, switch bodies, private
    names as labels/bindings, escaped keywords, `await`/`yield` misuse, `new` with
    import()/optional chains/await, async/generator method syntax, super outside methods,
    parameter/body lexical clashes, strict-reserved class/parameter names, class-element
    `arguments`/super() rules, plus valid oddities (`debugger`, `delete undefined`, parenthesized
    assignment targets that must NOT name anonymous functions, stray class-body semicolons). Pins
    reference quirks: a keyword after `@` parses as an identifier decorator, and an escaped
    `yield` inside a generator is accepted."""
    check_script(run, workdir, G, f"script_syntax_errors_{group}", r'''
const cases = %s;
for (const src of cases) {
  let r;
  try { r = 'ok ' + String(new Function(src)()); } catch (e) { r = e.name + ': ' + e.message; }
  console.log(JSON.stringify(src) + ' -> ' + r);
}
''' % json.dumps(SCRIPT_SYNTAX_CASES[group]), cli=INTERP)


def test_module_syntax_errors_catalogue(run, workdir):
    """CATCHES: module-goal parsing gaps reported through a failing import(): nested import
    declarations, non-string specifiers, duplicate attribute keys, a newline before legacy
    `assert`, strict-reserved/escaped `as`/`from`/`default`, string-literal local exports,
    lexical/var clashes, undeclared private names, lexer errors in module code (bad code points,
    unterminated strings, HTML comments), escaped `import.meta`/`from`/`as`/`async`, an import
    binding redeclared by `var`, source-phase imports of source-text modules, and module-only
    acceptances (top-level await and `using`, anonymous default exports named "default")."""
    cases = [
        "{ import x from './ok.mjs'; }",
        "if (1) import('./ok.mjs'); export const ok = 1;",
        "import x from 5;",
        "import x from './ok.json' with { type: 'json', type: 'json' };",
        "import { v } from './ok.mjs'\nassert({});",
        "import { v as yield } from './ok.mjs';",
        "import { implements } from './ok.mjs';",
        "import { v a\\u0073 w } from './ok.mjs';",
        "export { v a\\u0073 w } from './ok.mjs';",
        "export { \"str\" };",
        "export { v } fr\\u006fm './ok.mjs';",
        "export d\\u0065fault 1;",
        "export async function af() {} export default 1;",
        "let dup; var dup;",
        "var vdup; let vdup;",
        "this.#x;",
        "'\\u{110000}'",
        "let s = 'unterminated",
        "<!-- html comment",
        "import.m\\u0065ta;",
        "await 1; export const av = 'top-level await ok';",
        "using x = null; export const u = 'using at module top';",
        "export { undeclared };",
        "export default class { static nm = this.name; };",
        "export default (class { static nm = this.name; });",
        "import { v } from './ok.mjs'; var v;",
        "import source s from './ok.mjs';",
        "export * fr\\u006fm './ok.mjs';",
        "export * \\u0061s q from './ok.mjs';",
        "export default \\u0061sync function f() {}",
    ]
    files = {"ok.mjs": "export const v = 1;\n", "ok.json": '{"k": 1}\n'}
    for i, src in enumerate(cases):
        files[f"case{i}.mjs"] = src
    write_files(workdir, files)
    runner = r'''
const cases = %s;
for (let i = 0; i < cases.length; i++) {
  let r;
  try {
    const ns = await import(`./case${i}.mjs`);
    const d = ns.default;
    r = 'ok keys=' + Object.keys(ns).join(',') + (d === undefined ? '' : ' default=' + (typeof d === 'function' ? 'fn:' + d.name + '/' + d.nm : d)) + (ns.av ? ' ' + ns.av : '') + (ns.u ? ' ' + ns.u : '');
  } catch (e) { r = e.name + ': ' + e.message; }
  console.log(JSON.stringify(cases[i]) + ' -> ' + r);
}
''' % json.dumps(cases)
    check_script(run, workdir, G, "module_syntax_errors", runner, filename="module_syntax_errors.mjs", cli=INTERP)


def test_property_access_through_proto_proxies_and_foreign_receivers(run, workdir):
    """CATCHES: [[Get]]/[[Set]] slow paths that skip a Proxy sitting on the prototype chain (revoked,
    null/non-callable/throwing traps, receiver forwarding, false results in strict code, set
    invariants) or on the object itself, and OrdinarySet onto a receiver that differs from the
    base (super.x = v / Reflect.set): own accessors and non-writable properties reject the write,
    a non-extensible receiver rejects new properties, and a Proxy receiver gets the property via
    its getOwnPropertyDescriptor + defineProperty traps (false result or a throwing trap)."""
    check_script(run, workdir, G, "proto_proxies_and_receivers", PRELUDE + r'''
const { proxy: rp, revoke } = Proxy.revocable({}, {}); revoke();
const viaRevoked = Object.create(rp);
t('get through revoked proto', () => viaRevoked.x);
t('set through revoked proto', () => { viaRevoked.x = 1; });
t('get: proto proxy null trap', () => Object.create(new Proxy({ x: 'target x' }, { get: null })).x);
t('get: proto proxy bad trap', () => Object.create(new Proxy({}, { get: 5 })).x);
t('get: proto proxy trap throws', () => Object.create(new Proxy({}, { get() { throw new Error('get trap threw'); } })).x);
t('get: proto proxy receiver', () => { const child = Object.create(new Proxy({}, { get(tg, k, r) { return r === child ? 'receiver is child' : 'other'; } })); return child.k; });
t('set: proto proxy undefined trap', () => { const tgt = {}; const c = Object.create(new Proxy(tgt, { set: undefined })); c.y = 2; return JSON.stringify([c, tgt]); });
t('set: proto proxy bad trap', () => { Object.create(new Proxy({}, { set: 'nope' })).y = 2; });
t('set: proto proxy trap throws', () => { Object.create(new Proxy({}, { set() { throw new Error('set trap threw'); } })).y = 2; });
t('set: proto proxy false in strict', () => { 'use strict'; Object.create(new Proxy({}, { set() { return false; } })).y = 2; });
t('set: proto proxy invariant', () => { const tgt = Object.defineProperty({}, 'fz', { value: 1 }); Object.create(new Proxy(tgt, { set() { return true; } })).fz = 2; });
t('set: own proxy bad trap', () => { new Proxy({}, { set: 1 }).q = 3; });
t('super set onto own getter (strict)', () => { 'use strict'; const o = { __proto__: {}, get x() { return 1; }, m() { super.x = 2; } }; o.m(); });
t('super set onto own getter (sloppy)', () => { const o = { __proto__: {}, get x() { return 1; }, m() { super.x = 2; return this.x; } }; return o.m(); });
t('Reflect.set non-writable receiver', () => { const r = Object.defineProperty({}, 'k', { value: 1 }); return [Reflect.set({}, 'k', 2, r), r.k].join(); });
t('Reflect.set accessor receiver', () => Reflect.set({}, 'k', 2, { get k() { return 'g'; } }));
t('super set on non-extensible this', () => { 'use strict'; class A { m() { super.added = 1; } } A.prototype.m.call(Object.preventExtensions(new A())); });
t('Reflect.set proxy receiver', () => { const log = []; const pr = new Proxy({}, { defineProperty(tg, k, d) { log.push('define ' + k + ' ' + JSON.stringify(d)); return Reflect.defineProperty(tg, k, d); }, getOwnPropertyDescriptor(tg, k) { log.push('gopd ' + k); return Reflect.getOwnPropertyDescriptor(tg, k); } }); return Reflect.set({}, 'w', 9, pr) + ' ' + log.join('; '); });
t('super set: proxy this refuses define', () => { 'use strict'; class A { m() { super.v = 1; } } A.prototype.m.call(new Proxy(new A(), { defineProperty() { return false; } })); });
t('set: own proxy trap throws', () => { new Proxy({}, { set() { throw new RangeError('own set trap'); } }).q = 3; });
t('super set: proxy this define trap throws', () => { 'use strict'; class A { m() { super.v = 1; } } A.prototype.m.call(new Proxy(new A(), { defineProperty() { throw new Error('define trap threw'); } })); });
console.log(out.join('\n'));
''', cli=INTERP)


def test_property_writes_typed_arrays_primitives_and_namespaces(run, workdir):
    """CATCHES: typed arrays reached through the prototype chain (a valid index creates an own data
    property on an ordinary receiver, numeric non-indices are inert, a TA receiver stores coerced
    values or rejects a Number for a BigInt array), sealed/frozen array index additions and
    non-writable lengths, writes to primitives whose wrapper prototype has a setter, a proxy, a
    data property or a getter-only accessor, String-wrapper index reads, a 33k-subject regexp
    workload, and module-namespace writes/deletes (silent in sloppy code, TypeError in strict).
    Pins a reference quirk: a String wrapper also answers the non-canonical index '01'."""
    write_files(workdir, {"ns.mjs": "export let late = 1;\n"})
    check_script(run, workdir, G, "ta_primitive_namespace_writes", PRELUDE + r'''
const ta = new Uint8Array(2), taChild = Object.create(ta);
t('TA proto: valid index', () => { taChild[0] = 300; return JSON.stringify(Object.getOwnPropertyDescriptor(taChild, '0')) + ' ta[0]=' + ta[0]; });
t('TA proto: invalid indices inert', () => { taChild[5] = 1; taChild['-0'] = 1; taChild['1.5'] = 1; return Object.keys(taChild).join() + ' len=' + ta.length; });
t('TA proto: named property', () => { taChild.named = 'n'; return taChild.named + ' ' + ('named' in ta); });
t('Reflect.set TA receiver', () => [Reflect.set(taChild, '1', 77, ta), ta[1], Reflect.set(taChild, '9', 1, ta)].join());
t('Reflect.set BigInt TA receiver', () => { const b = new BigInt64Array(1); return [Reflect.set(Object.create(b), '0', 5n, b), String(b[0])].join(); });
t('Reflect.set BigInt TA bad value', () => { const b = new BigInt64Array(1); return Reflect.set(Object.create(b), '0', 5, b); });
t('frozen array length via Reflect.set', () => { const a = Object.freeze([1, 2]); return [Reflect.set(a, 'length', 0), a.length].join(); });
t('non-writable length (strict)', () => { 'use strict'; const a = [1, 2]; Object.defineProperty(a, 'length', { writable: false }); a.length = 1; });
t('non-writable length append (sloppy)', () => { const a = [1]; Object.defineProperty(a, 'length', { writable: false }); a[1] = 5; return a.length + ' ' + a[1]; });
t('BigInt primitive via proto setter', () => { Object.defineProperty(BigInt.prototype, 'tagx', { set(v) { out.push('  setter this type ' + typeof this); }, configurable: true }); 5n.tagx = 1; delete BigInt.prototype.tagx; return 'done'; });
t('BigInt primitive write (strict)', () => { 'use strict'; 5n.foo = 1; });
t('Symbol primitive write (strict)', () => { 'use strict'; Symbol().foo = 1; });
t('Number proto chain proxy', () => { const saved = Object.getPrototypeOf(Number.prototype); Object.setPrototypeOf(Number.prototype, new Proxy({}, { set(tg, k, v, r) { out.push('  proxy set ' + k + ' receiver ' + typeof r); return true; } })); (5).viaProxy = 1; Object.setPrototypeOf(Number.prototype, saved); return 'ok'; });
t('String proto getter-only (strict)', () => { 'use strict'; Object.defineProperty(String.prototype, 'ro', { get() { return 1; }, configurable: true }); try { 'abc'.ro = 2; } finally { delete String.prototype.ro; } });
t('TA on chain, receiver is the TA', () => { const ta2 = new Uint8Array(2); const mid = Object.create(ta2); const home = { __proto__: mid, m() { super[0] = 300; super[5] = 1; super['1.5'] = 2; return [ta2[0], ta2.length, Object.keys(mid).length].join(); } }; return home.m.call(ta2); });
t('BigInt TA on chain, receiver is the TA', () => { const b = new BigInt64Array(1); const home = { __proto__: Object.create(b), m() { super[0] = 9n; return String(b[0]); } }; return home.m.call(b); });
t('strict add index to sealed array', () => { 'use strict'; Object.seal([1])[1] = 2; });
t('sloppy add index to frozen array', () => { const a = Object.freeze([1]); a[1] = 2; return a.length; });
t('primitive with shadowed data prop (sloppy)', () => { (5).toFixed = 1; return typeof (5).toFixed; });
t('primitive with shadowed data prop (strict)', () => { 'use strict'; (5).toFixed = 1; });
t('String wrapper indices', () => { const s = new String('ab'); return [s[7], s[1], s['01'], s[-1]].join('|'); });
t('33000 distinct regexp subjects', () => { let n = 0; for (let i = 0; i < 33000; i++) if (/7$/.test('s' + i)) n++; return n; });
(async () => {
  const ns = await import('./ns.mjs');
  t('sloppy namespace write', () => { ns.late = 5; ns.fresh = 1; return ns.late + ' ' + ('fresh' in ns); });
  t('sloppy super set with namespace this', () => { const o = { m() { super.late = 1; return 'no throw'; } }; return o.m.call(ns); });
  t('strict super set with namespace this', () => { 'use strict'; const o = { m() { super.late = 1; } }; o.m.call(ns); });
  t('strict namespace write', () => { 'use strict'; ns.late = 5; });
  t('strict namespace delete', () => { 'use strict'; delete ns.late; });
  t('Reflect.set namespace', () => Reflect.set(ns, 'late', 9));
  console.log(out.join('\n'));
})();
''', cli=INTERP)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_gc_keeps_with_scopes_arguments_and_import_bindings(run, workdir, cli):
    """CATCHES: a cycle collector that frees (or clears the bindings of) scopes still reachable only
    through a `with` object environment, a mapped `arguments` object, or module import bindings
    while >100k cyclic objects and closure<->scope cycles are being reclaimed (including the
    activation scopes of hot, compiled closure factories); the surviving closures must still read
    their live values afterwards, on every tier."""
    write_files(workdir, {
        "lib.mjs": "export let counter = 0;\nexport function bump() { counter++; return counter; }\nexport const label = 'exported label';\n",
        "sloppy.cjs": r'''
function sloppyArgs(a, b) { return () => { a = a + '!'; return arguments[0] + ' ' + arguments.length; }; }
const ka = sloppyArgs('arg', 2);
function viaWith(o) { with (o) { return () => v + ' / ' + typeof w; } }
const kw = viaWith({ v: 'with v', w: 1 });
for (let i = 0; i < 35000; i++) { const a = { i }, b = { a }; a.b = b; let x = { n: i }; x.f = () => x; }
module.exports = ['mapped arguments: ' + ka(), 'mapped arguments again: ' + ka(), 'with scope: ' + kw()];
''',
    })
    check_script(run, workdir, G, "gc_scopes_imports", r'''
import { counter, bump, label } from './lib.mjs';
import { createRequire } from 'node:module';
const readImport = () => label + ' counter=' + counter;
const before = readImport();
const box = { tag: 'box' };
const readBox = () => box.tag;
let cyc = 0;
for (let round = 0; round < 1; round++) {
  for (let i = 0; i < 30000; i++) {
    const a = { i }, b = { a }; a.b = b;
    let x = { n: i }; x.f = () => x.n;
    if (i % 10000 === 0) cyc += x.f();
  }
  bump();
  box.tag = 'box after round ' + round;
}
console.log('before:', before);
console.log('after:', readImport());
console.log('closure over module scope:', readBox());
console.log('cycle closures summed:', cyc);
function mk(i) { let x = { i }; let y = i * 2; x.f = () => x.i + y; return x; }
const kept = []; let parity = 0;
for (let i = 0; i < 40000; i++) { const o = mk(i); if (i % 20000 === 0) kept.push(o); else parity += o.f() & 1; }
console.log('hot closure scopes kept:', kept.map((o) => o.f()).join(), parity);
const results = createRequire(import.meta.url)('./sloppy.cjs');
for (const r of results) console.log(r);
''', filename="gc_scopes_imports.mjs", cli=cli)


def test_async_functions_generators_and_using_disposal(run, workdir):
    """CATCHES: async functions that throw synchronously on parameter-binding failures instead of
    returning a rejected promise, awaits/yields/return() of a promise whose `constructor` getter
    throws, async-generator request queues and completed-state handling, and `using`/`await using`
    disposal (generators, async functions/generators, static blocks, switch blocks, for-of heads,
    @@dispose fallback, SuppressedError chains, a disposal error over `return`). Pins reference
    quirks: a disposal error raised while a `break` leaves the block is dropped, and a `using`
    binding names an anonymous class only after its static initializers ran."""
    check_script(run, workdir, G, "async_and_using", PRELUDE + r'''
const poisoned = () => { const p = Promise.resolve('poisoned value'); Object.defineProperty(p, 'constructor', { get() { throw new Error('constructor getter'); } }); return p; };
const res = (name, log, fail) => ({ [Symbol.dispose]() { log.push('dispose ' + name); if (fail) throw new Error(fail); } });
const errText = (e) => e.name + ': ' + e.message + (e instanceof SuppressedError ? ' [error=' + e.error.message + ' suppressed=' + e.suppressed.message + ']' : '');
(async () => {
  await tA('async param destructure fails', () => { async function f({ a }) { return a; } const p = f(); out.push('  call returned a promise: ' + (p instanceof Promise)); return p; });
  await tA('async param default throws', () => { async function f(x = (() => { throw new RangeError('default threw'); })()) {} return f(); });
  await tA('async arrow array param fails', () => { const f = async ([a]) => a; return f(null); });
  await tA('await poisoned promise', async () => { async function f() { try { await poisoned(); } catch (e) { return 'caught ' + e.message; } } return f(); });
  await tA('async gen await poisoned', async () => { async function* g() { try { await poisoned(); } catch (e) { yield 'gen caught ' + e.message; } } return JSON.stringify(await g().next()); });
  await tA('async gen yield poisoned', async () => { async function* g() { try { yield poisoned(); } catch (e) { yield 'yield caught ' + e.message; } } return JSON.stringify(await g().next()); });
  await tA('async gen return(poisoned) before start', async () => { async function* g() { yield 1; } return JSON.stringify(await g().return(poisoned())); });
  await tA('async gen return(poisoned) after done', async () => { async function* g() {} const it = g(); await it.next(); return JSON.stringify(await it.return(poisoned())); });
  await tA('async gen throw after done', async () => { async function* g() {} const it = g(); await it.next(); return JSON.stringify(await it.throw(new Error('thrown after done'))); });
  await tA('async gen queued requests', async () => { async function* g() { yield 1; yield 2; } const it = g(); return JSON.stringify(await Promise.all([it.next(), it.return('early'), it.next()])); });
  t('generator using: dispose at end', () => { const log = []; function* g() { using r = res('r', log); log.push('body'); yield 1; log.push('after yield'); } const it = g(); it.next(); it.next(); return log.join(); });
  t('generator using: dispose on return()', () => { const log = []; function* g() { using r = res('r', log); yield 1; log.push('unreached'); } const it = g(); it.next(); it.return(5); return log.join(); });
  t('generator using: dispose throws', () => { const g = (function* () { using r = res('r', [], 'dispose failed'); yield 1; })(); g.next(); g.next(); });
  await tA('async gen await using', async () => { const log = []; async function* g() { await using r = { async [Symbol.asyncDispose]() { log.push('async disposed'); } }; yield 'v'; } for await (const v of g()) log.push(v); return log.join(); });
  await tA('async gen await using on return()', async () => { const log = []; async function* g() { await using r = { async [Symbol.asyncDispose]() { log.push('gen adisposed'); } }; yield 1; } const it = g(); await it.next(); return JSON.stringify(await it.return('early')) + ' ' + log.join(); });
  await tA('async fn using', async () => { const log = []; async function f() { using r = res('sync-in-async', log); await null; return 'ret'; } return (await f()) + ' ' + log.join(); });
  await tA('await using falls back to @@dispose', async () => { const log = []; { await using r = { [Symbol.asyncDispose]: undefined, [Symbol.dispose]() { log.push('sync dispose used'); return 'ignored'; } }; } return log.join(); });
  await tA('await using async dispose rejects', async () => { { await using r = { async [Symbol.asyncDispose]() { throw new Error('async dispose rejected'); } }; } });
  t('using non-disposable', () => { function f() { using r = {}; } f(); });
  t('using @@dispose not callable', () => { function f() { using r = { [Symbol.dispose]: 1 }; } f(); });
  t('static block using', () => { const log = []; class C { static { using r = res('static', log); log.push('in block'); } } return log.join(); });
  t('switch block using order', () => { const log = []; switch (1) { case 1: { using a = res('a', log); using b = res('b', log); } } return log.join(); });
  t('for (using x of ...)', () => { const log = []; for (using x of [res('x1', log), res('x2', log)]) log.push('iter'); return log.join(); });
  try { (function () { using r = res('r', [], 'dispose failed'); return 'returned'; })(); } catch (e) { out.push('dispose error over return: ' + errText(e)); }
  try { (function () { using r = res('r', [], 'second'); throw new Error('first'); })(); } catch (e) { out.push('dispose error over throw: ' + errText(e)); }
  try { (function () { using a = res('a', [], 'from a'); using b = res('b', [], 'from b'); })(); } catch (e) { out.push('two disposal errors: ' + errText(e)); }
  t('dispose error over break (dropped)', () => { const log = []; for (const i of [1]) { using r = res('r', log, 'dispose in loop'); break; } return log.join(); });
  t('using names anonymous class late', () => { function f() { using K = class { static [Symbol.dispose]() {} static nm = this.name; }; return JSON.stringify(K.nm) + '/' + K.name; } return f(); });
  t('var names anonymous class early', () => { var VK = class { static nm = this.name; }; return VK.nm; });
  console.log(out.join('\n'));
})();
''', cli=INTERP)


@pytest.mark.parametrize("cli", TWO_TIERS)
def test_super_null_base_and_tail_position_calls(run, workdir, cli):
    """CATCHES: `super` property reads/writes/calls/compound assignment with a null home-object
    prototype not throwing the right TypeError (pinned quirk: a for-of whose target is `super.x`
    with a null home prototype completes without error), for-in/of heads assigning to super,
    private and pattern targets (setters, defaults naming functions, holes), and strict
    tail-position calls mishandled: indexed
    and member tagged templates keeping `this`, null/non-callable callees and tags, optional,
    direct-eval, private and curried calls, tail calls inside try/catch/finally (finally overriding
    or throwing), and logical/comma tails. Pins a reference bug: a tagged template whose tag is a
    `super` property throws "SyntaxError: 'super' keyword unexpected here"."""
    check_script(run, workdir, G, "super_null_and_tail_calls", r'''
'use strict';
''' + PRELUDE + r'''
t('super[k] with null base', () => { const o = { m() { return super['x' + 1]; } }; Object.setPrototypeOf(o, null); return o.m(); });
t('super.x with null base', () => { const o = { m() { return super.x; } }; Object.setPrototypeOf(o, null); return o.m(); });
t('super.x = v with null base', () => { const o = { m() { super.x = 1; } }; Object.setPrototypeOf(o, null); return o.m(); });
t('super[k] = v with null base', () => { const o = { m() { super['y'] = 1; } }; Object.setPrototypeOf(o, null); return o.m(); });
t('super.m() with null base', () => { const o = { m() { return super.toString(); } }; Object.setPrototypeOf(o, null); return o.m(); });
t('super.n += 1 with null base', () => { const o = { m() { super.n += 1; } }; Object.setPrototypeOf(o, null); return o.m(); });
t('for-of/in with super targets', () => { const base = { set sx(v) { out.push('  base setter ' + v); } }; const o = { __proto__: base, m() { for (super.sx of [1, 2]) ; for (super['sy'] in { k1: 1 }) ; return JSON.stringify(this); } }; return o.m(); });
t('for-of super target with null base (no error)', () => { const o = { m() { for (super.x of [1]) ; return 'completed'; } }; Object.setPrototypeOf(o, null); return o.m(); });
t('for-of private target', () => { class C { #p = 0; m() { for (this.#p of [1, 2, 3]) ; return this.#p; } } return new C().m(); });
t('for-of object pattern defaults', () => { let a, b; const r = []; for ({ a = 'da', b: b = function () {} } of [{}, { a: 1, b: 2 }]) r.push(a + ':' + (typeof b === 'function' ? b.name : b)); return r.join(); });
t('for-of array pattern holes/defaults', () => { let x, y; const r = []; for ([x, , y = 'dy'] of ['ab', 'abc']) r.push(x + y); return r.join(); });
const tag = (s, ...v) => s.raw.join('|') + ':' + v.join();
const holder = { tag(s, v) { return 'method tag this=' + (this === holder) + ' ' + v; }, k: 'tag' };
function idxTag(n) { return holder[holder.k]`a${n}b`; }
function memberTag(n) { return holder.tag`x${n}`; }
function nullTag() { const n = null; return n.tag`x`; }
function badTag() { const o = { tag: 5 }; return o.tag`x`; }
function callTag() { return (() => tag)()`c${3}`; }
class B { stag(s) { return 'super tag ' + s[0]; } sm() { return 'super method'; } }
class D extends B { viaSuperTag() { return super.stag`zz`; } viaSuper() { return super.sm(); } }
class P { #pm() { return 'private method ' + (this instanceof P); } go() { return this.#pm(); } }
function optTail(o) { return o?.m(); }
function evalTail() { return eval('"direct eval in tail"'); }
function nullCallee() { const n = null; return n.m(); }
function shortCallee() { const n = null; return n?.f()(); }
function getF() { return (x) => 'curried ' + x; }
function curried() { return getF()(7); }
function deepFinally(n, log) { try { return n === 0 ? 'bottom' : deepFinally(n - 1, log); } finally { log.push(n); } }
function finallyOverride() { try { return getF()('try'); } finally { return getF()('finally'); } }
function finallyThrows() { try { return getF()('try'); } finally { throw new Error('finally threw'); } }
function catchTail() { try { throw 1; } catch { return getF()('catch'); } }
const holder2 = { a: (s, n) => recTag(n), b: (s, n) => recTag(n) };
function recTag(n) { return n === 0 ? 'recursion done' : holder2[n % 2 ? 'a' : 'b']`${n - 1}`; }
t('indexed tag', () => idxTag(1));
t('member tag', () => memberTag(2));
t('null base tag', nullTag);
t('non-callable tag', badTag);
t('call-expression tag', callTag);
t('super tag', () => new D().viaSuperTag());
t('super method', () => new D().viaSuper());
t('private method', () => new P().go());
t('optional call', () => String(optTail(null)) + ' ' + optTail({ m() { return 'opt m'; } }));
t('direct eval', evalTail);
t('null base call', nullCallee);
t('short-circuited callee', shortCallee);
t('curried call', curried);
t('try/finally tail', () => { const log = []; return deepFinally(3, log) + ' ' + log.join(); });
t('finally overrides', finallyOverride);
t('finally throws', finallyThrows);
t('catch tail', catchTail);
t('indexed tag recursion', () => recTag(40));
t('nullish/and/comma tails', () => [((x) => x ?? getF()('nullish'))(undefined), ((x) => x && getF()('and'))(0), (out.length, getF()('comma'))].join(' / '));
console.log(out.join('\n'));
''', cli=cli)


def test_class_heritage_and_builtin_subclassing(run, workdir):
    """CATCHES: `extends` / super() handling of unusual parents: Proxy constructors (construct trap
    gets new.target), bound constructors (bound args prepended), null and non-constructor parents
    (including a parent swapped after definition), double/missing super() and derived return
    values, and subclassing every builtin with internal slots (Promise, Map, Set, DataView,
    ArrayBuffer, typed arrays, RegExp, Error, Function, Array, Date, wrappers) so instances keep
    both their slots and the subclass prototype; also object rest from proxies/strings and
    RegExp construction with a newTarget whose prototype is not an object."""
    check_script(run, workdir, G, "class_heritage_builtins", PRELUDE + r'''
t('extends proxy ctor', () => { const log = []; const PB = new Proxy(class Base { constructor(a) { this.a = a; } }, { construct(tg, args, nt) { log.push('construct trap ' + args.join() + ' nt=' + nt.name); return Reflect.construct(tg, args, nt); } }); class D extends PB { constructor() { super(7); this.d = 1; } } const d = new D(); return log.join() + ' ' + JSON.stringify(d) + ' ' + (d instanceof D); });
t('extends bound ctor', () => { class Base { constructor(...a) { this.args = a.join(); } } const BB = Base.bind(null, 'bound1'); BB.prototype = Base.prototype; class D extends BB { constructor() { super('own'); } } return new D().args; });
t('extends bound ctor without prototype', () => { class Base {} class D extends Base.bind(null) {} });
t('extends null', () => { class N extends null {} return Object.getPrototypeOf(N.prototype) + ' ' + typeof N; });
t('new on extends null', () => { class N extends null {} new N(); });
t('extends null returning object', () => { class N extends null { constructor() { return Object.create(N.prototype); } } return new N() instanceof N; });
t('extends non-constructor', () => { class X extends Math.max {} });
t('extends generator function', () => { function* g() {} class X extends g {} });
t('parent swapped to non-constructor', () => { class A {} class B2 extends A { constructor() { super(); } } Object.setPrototypeOf(B2, Math.max); new B2(); });
t('super() twice', () => { class A {} class B2 extends A { constructor() { super(); super(); } } new B2(); });
t('this before super()', () => { class A {} class B2 extends A { constructor() { this.x = 1; super(); } } new B2(); });
t('no super() call', () => { class A {} class B2 extends A { constructor() {} } new B2(); });
t('derived returns primitive', () => { class A {} class B2 extends A { constructor() { super(); return 1; } } new B2(); });
t('derived returns object without super()', () => { class A {} class B2 extends A { constructor() { return { own: 'obj' }; } } return JSON.stringify(new B2()); });
t('Promise subclass', () => { class MyP extends Promise {} const p = new MyP((r) => r(5)); return (p instanceof MyP) + ' ' + (p.then(() => {}) instanceof MyP); });
t('Map subclass', () => { class MyM extends Map { constructor() { super([[1, 'one']]); } } const m = new MyM(); return m.get(1) + ' ' + m.size; });
t('DataView subclass', () => { class DV extends DataView {} const dv = new DV(new ArrayBuffer(4)); dv.setUint16(0, 258); return dv.getUint8(1) + ' ' + dv.byteLength + ' ' + (dv instanceof DV); });
t('ArrayBuffer subclass', () => { class AB extends ArrayBuffer {} const ab = new AB(8); return ab.byteLength + ' ' + (ab instanceof AB) + ' ' + ab.slice(2).byteLength; });
t('Uint8Array subclass', () => { class U extends Uint8Array {} const u = new U([1, 2, 300]); return u.join() + ' ' + (u.map((x) => x * 2) instanceof U) + ' ' + u.buffer.byteLength; });
t('RegExp subclass', () => { class R extends RegExp { exec(s) { return super.exec(s); } } return new R('a(b)').exec('xab')[1]; });
t('Error subclass', () => { class E extends Error { constructor(m) { super(m); this.name = 'E'; } } const e = new E('msg'); return e.message + ' ' + (e instanceof Error) + ' ' + Object.prototype.toString.call(e); });
t('Function subclass', () => { class F extends Function {} const f = new F('a', 'return a * 2'); return f(4) + ' ' + (f instanceof F); });
t('Array subclass', () => { class A2 extends Array {} const a = new A2(3); a.push(1); return a.length + ' ' + (a.slice() instanceof A2) + ' ' + Array.isArray(a); });
t('Date and wrapper subclasses', () => { class Dt extends Date {} class Bo extends Boolean {} class Nu extends Number {} class St extends String {} return [new Dt(0).toISOString(), new Bo(false).valueOf(), new Nu(4) + 1, new St('ab').length].join(); });
t('Set subclass via super() in arrow', () => { class S extends Set { constructor() { const go = () => super([1, 2]); go(); } } return new S().size; });
t('object rest from proxy', () => { const log = []; const p = new Proxy({ a: 1, b: 2, c: 3 }, { ownKeys(tg) { log.push('ownKeys'); return Reflect.ownKeys(tg); }, getOwnPropertyDescriptor(tg, k) { log.push('gopd ' + k); return k === 'c' ? undefined : Reflect.getOwnPropertyDescriptor(tg, k); }, get(tg, k) { log.push('get ' + k); return tg[k]; } }); const { a, ...rest } = p; return JSON.stringify(rest) + ' ' + log.join(); });
t('object rest from string and number', () => { const { 0: first, ...rest } = 'abc'; const { ...none } = 5; return first + JSON.stringify(rest) + JSON.stringify(none); });
t('RegExp newTarget with primitive prototype', () => { const re = Reflect.construct(RegExp, ['a+', 'g'], Object.assign(function NT() {}, { prototype: 5 })); return (Object.getPrototypeOf(re) === RegExp.prototype) + ' ' + re.source + re.flags; });
t('300 distinct dynamic regexps', () => { let matched = 0; for (let i = 0; i < 300; i++) { if (new RegExp('^x' + i + '$').test('x' + i)) matched++; } return matched + ' ' + /^x5$/.test('x5'); });
console.log(out.join('\n'));
''', cli=INTERP)


def test_array_element_storage_transitions(run, workdir):
    """CATCHES: Array.prototype.pop/shift/push/splice/reverse/sort fast paths that ignore the
    element storage state: trailing holes, accessor or non-configurable last elements (TypeError
    "Cannot delete property"), far/sparse indices, arrays that also carry named properties,
    dictionary-mode arrays after many deletes, frozen/sealed arrays, setters invoked while elements
    shift, plus own-key ordering (integer indices ascending, then strings; 2**32-1 is not an index)
    for objects mixing many named and indexed properties."""
    check_script(run, workdir, G, "array_element_storage", PRELUDE + r'''
const big = (n) => Array.from({ length: n }, (_, i) => i);
t('pop trailing hole', () => { const a = [1, 2, , ]; const r = a.pop(); return String(r) + ' ' + a.length; });
t('pop accessor last', () => { const a = [1, 2, 3]; Object.defineProperty(a, 2, { get() { return 'getter'; }, configurable: true }); return a.pop() + ' ' + a.length + ' ' + (2 in a); });
t('pop non-configurable last', () => { const a = [1, 2, 3]; Object.defineProperty(a, 2, { value: 3, configurable: false }); a.pop(); });
t('pop with far index', () => { const a = [1, 2]; a[5000000] = 'far'; return a.pop() + ' ' + a.length; });
t('pop after named prop', () => { const a = big(40); a.foo = 1; return a.pop() + ' ' + a.length + ' ' + a.foo; });
t('pop large dense until empty', () => { const a = big(50); let s = 0; while (a.length) s += a.pop(); return s + ' ' + a.length; });
t('pop large with hole', () => { const a = big(50); delete a[49]; return String(a.pop()) + ' ' + a.length; });
t('pop large accessor', () => { const a = big(50); Object.defineProperty(a, 49, { get() { return 'g49'; }, configurable: true }); return a.pop() + ' ' + a.length; });
t('pop large non-configurable', () => { const a = big(50); Object.defineProperty(a, 49, { value: 49, configurable: false }); a.pop(); });
t('shift/pop sparse', () => { const a = []; a[100] = 'x'; a[3] = 'y'; return a.pop() + ' ' + a.length + ' ' + a.shift() + ' ' + a.length; });
t('push after delete', () => { const a = big(40); delete a[10]; a.push('p'); return a.length + ' ' + (10 in a) + ' ' + a[40]; });
t('dictionary-mode array', () => { const a = big(40); for (let i = 0; i < 40; i += 2) delete a[i]; a.length = 100; a[99] = 'end'; const p = a.pop(); return p + ' ' + a.length + ' ' + Object.keys(a).length; });
t('frozen pop', () => { Object.freeze([1, 2]).pop(); });
t('sealed pop', () => { Object.seal([1, 2]).pop(); });
t('many named then indexed keys', () => { const o = {}; for (let i = 0; i < 100; i++) o['k' + i] = i; for (let i = 0; i < 50; i++) o[i] = i; delete o.k5; delete o[3]; const k = Object.keys(o); return k.length + ' ' + k.slice(0, 5).join() + ' ' + k.slice(48, 51).join() + ' ' + k.slice(-2).join(); });
t('array own key ordering', () => { const a = []; a[5] = 5; a[1] = 1; a.x = 'x'; a[3] = 3; a[4294967295] = 'not index'; return Object.keys(a).join() + ' len=' + a.length; });
t('splice over accessor element', () => { const a = big(10); Object.defineProperty(a, 5, { get() { return 'g5'; }, set(v) { out.push('  set5 ' + v); }, configurable: true }); a.splice(2, 2); return a.join() + ' len=' + a.length; });
t('reverse with holes', () => { const a = [1, , 3, , 5]; a.reverse(); return JSON.stringify(a) + ' keys=' + Object.keys(a).join(); });
t('sort writes through accessor', () => { const a = [3, 1, 2]; Object.defineProperty(a, 0, { get() { return 9; }, set(v) { out.push('  sort set ' + v); }, configurable: true }); a.sort(); return a.join(); });
console.log(out.join('\n'));
''')
