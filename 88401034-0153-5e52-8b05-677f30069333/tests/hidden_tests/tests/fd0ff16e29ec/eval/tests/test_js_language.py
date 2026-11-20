"""Core JavaScript language semantics: parser, lexer, evaluation, generators, async, classes, eval.

Each program is run under all three execution tiers (JIT, interpreter, bytecode) and must give
the same golden output in each.
"""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]


PROG_OPERATORS = r"""const out = [];
const p = (label, v) => out.push(label + '=' + (typeof v === 'string' ? JSON.stringify(v) : String(v)));
// arithmetic & exponent
p('exp-right-assoc', 2 ** 3 ** 2);
p('exp-neg', (-2) ** 3);
p('exp-assign', (() => { let a = 3; a **= 2; return a; })());
p('mod-neg', -7 % 3);
p('mod-float', 5.5 % 2);
p('neg-zero', 1 / -0);
p('nan-cmp', NaN == NaN);
p('div', 7 / 2);
p('int-overflow', 2147483647 + 1);
p('shift', [1 << 31, -1 >>> 0, -16 >> 2, -16 >>> 28, 1 << 32, 5 & 3, 5 | 3, 5 ^ 3, ~5].join());
// string vs number
p('plus-str', 1 + '2');
p('minus-str', '5' - 2);
p('plus-arr', [1, 2] + [3]);
p('plus-obj', ({}) + 1);
p('plus-null', null + 1);
p('plus-undef', undefined + 1);
p('plus-bool', true + true);
p('unary-plus', [+'', +' 12 ', +'0x1f', +'1e3', +[], +[5], +[1, 2], +'abc', +null, +undefined, +true].join());
// comparisons
p('abstract-eq', [null == undefined, null == 0, '' == 0, '0' == false, [] == '', [0] == false, NaN != NaN, 'a' < 'b', 'B' < 'a', '10' < '9', 10 < 9, '10' < 9].join());
p('strict-eq', [0 === -0, Object.is(0, -0), Object.is(NaN, NaN), '1' === 1].join());
// comma & void
let c = (1, 2, 3);
p('comma', c);
p('void', void 'x');
// typeof
p('typeof', [typeof undeclaredVar, typeof null, typeof function () {}, typeof class {}, typeof Symbol(), typeof 1n, typeof [], typeof new String('')].join());
// delete
const o = { a: 1, b: 2 };
p('delete-prop', delete o.a);
p('delete-after', JSON.stringify(o));
p('delete-missing', delete o.zzz);
p('delete-nonref', delete 1);
const arr = [1, 2, 3];
delete arr[1];
p('delete-arr', arr.length + ':' + (1 in arr));
var gv = 1;
p('delete-var', delete globalThis.gv);
// nullish & optional chaining
const n = { x: { y: 0, f() { return this.y + 1; } }, z: null };
p('nullish', [n.z ?? 'd', n.x.y ?? 'd', n.missing ?? 'm', 0 || 'or', '' ?? 'n'].join());
p('optional', [n.z?.y, n.x?.y, n.x?.f(), n.x.g?.(), n.z?.y.q.r, n.x?.['y'], (n.z)?.y].join('|'));
p('optional-call-this', n.x?.f?.());
let cnt = 0;
null?.[cnt++];
p('short-circuit', cnt);
delete n?.x.y;
p('delete-optional', JSON.stringify(n.x));
// logical assignment
let la = null, lb = 0, lc = 1;
la ??= 'set'; lb ||= 'or'; lc &&= 'and';
p('logical-assign', [la, lb, lc].join());
let side = 0;
const lo = { get v() { side++; return 1; }, set v(x) { side += 100; } };
lo.v ||= 5; lo.v &&= 5; lo.v ??= 5;
p('logical-assign-setter', side);
// increments
let i = 5;
p('incr', [i++, i, ++i, i--, --i].join());
const io = { v: '5' };
p('incr-str', [io.v++, io.v].join() + typeof io.v);
// in / instanceof
p('in', ['a' in { a: 1 }, 0 in [9], 'length' in [], 'toString' in {}].join());
p('instanceof', [[] instanceof Array, [] instanceof Object, Object.create(null) instanceof Object].join());
// conditional chain
const grade = (s) => s > 90 ? 'A' : s > 80 ? 'B' : 'C';
p('ternary', [grade(95), grade(85), grade(10)].join());
// numeric formatting
p('numfmt', [0.1 + 0.2, 1e21, 1e-7, 123456789012345680000, -1e-7, 2 ** 53, 0.000001, 1 / 3, 100 / 3, 5e-324].join(' '));
p('tostring-radix', [(255).toString(16), (255).toString(2), (-255).toString(36), (0.5).toString(2)].join());
// BigInt ops
p('bigint', [2n ** 64n, -7n / 2n, -7n % 2n, 1n << 70n, (-1n) >> 3n, 5n & 3n, typeof (1n + 2n), 10n > 9, 1n == 1, 1n === 1].join());
for (const [l, f] of [['mix', () => 1n + 1], ['div0', () => 1n / 0n], ['negexp', () => 2n ** -1n], ['unsigned', () => 1n >>> 1n], ['unary', () => +1n]]) {
  try { f(); p(l, 'no error'); } catch (e) { p(l, e.name + ': ' + e.message); }
}
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_operators(run, tier):
    """CATCHES: wrong operator semantics -- exponent associativity, ToPrimitive/ToNumber coercions, abstract equality, typeof/delete/void results, optional chaining short-circuit, nullish and logical assignment (setter calls), BigInt arithmetic and its TypeError/RangeError messages, number-to-string formatting."""
    r = run([*tier, "-e", PROG_OPERATORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "operators")

PROG_CONTROL_FLOW = r"""const log = [];
// labelled break/continue
outer: for (let i = 0; i < 4; i++) {
  inner: for (let j = 0; j < 4; j++) {
    if (j === 2) continue outer;
    if (i === 3) break outer;
    log.push(i + '' + j);
  }
}
console.log('labels', log.join(' '));
// labelled block
blk: { console.log('in block'); if (true) break blk; console.log('never'); }
// switch fallthrough, default in middle, strict compare
function sw(x) {
  const r = [];
  switch (x) {
    case 1: r.push('one');
    case 2: r.push('two'); break;
    default: r.push('default');
    case 3: r.push('three');
    case '4': r.push('str4'); break;
    case 5: { r.push('five'); }
  }
  return r.join('+');
}
console.log('switch', [1, 2, 3, 4, '4', 5, 6].map(sw).join(' | '));
// switch lexical scope & case evaluation order
let evals = [];
const k = (v) => (evals.push(v), v);
switch (3) { case k(1): case k(2): case k(3): evals.push('hit'); case k(4): evals.push('fall'); }
console.log('case-order', evals.join());
// for-in ordering: integer keys ascending, then strings in insertion order, then proto
const proto = { pz: 1, shared: 1 };
const obj = Object.create(proto);
obj.b = 1; obj[10] = 1; obj.a = 1; obj[2] = 1; obj.shared = 2; obj['-1'] = 1; obj['01'] = 1;
Object.defineProperty(obj, 'hidden', { value: 1, enumerable: false });
obj[Symbol('s')] = 1;
const keys = [];
for (const key in obj) keys.push(key);
console.log('for-in', keys.join(','));
// deletion during for-in
const del = { a: 1, b: 2, c: 3 };
const seen = [];
for (const key in del) { seen.push(key); delete del.b; }
console.log('for-in-delete', seen.join(','));
// for-in over primitives / null
const pk = [];
for (const x in 'ab') pk.push(x);
for (const x in null) pk.push('null!');
for (const x in undefined) pk.push('undef!');
console.log('for-in-prim', pk.join(','));
// for-of with iterator close on break / throw
function mkIter(name) {
  let n = 0;
  return {
    [Symbol.iterator]() { return this; },
    next() { n++; return { value: n, done: n > 5 }; },
    return(v) { console.log(name + ' return called at ' + n); return { done: true }; },
  };
}
for (const v of mkIter('brk')) { if (v === 2) break; }
try { for (const v of mkIter('thr')) { if (v === 3) throw new Error('boom'); } } catch (e) { console.log('caught', e.message); }
for (const v of mkIter('exhaust')) {}
(function () { for (const v of mkIter('ret')) { return v; } })();
lbl: for (const a of [1]) { for (const v of mkIter('cont-outer')) { continue lbl; } }
// per-iteration bindings
const fns = [];
for (let i = 0; i < 3; i++) fns.push(() => i);
for (var vi = 0; vi < 3; vi++) fns.push(() => vi);
for (const q of ['x', 'y']) fns.push(() => q);
console.log('closures', fns.map(f => f()).join());
// closure captures loop var mutated in body
const fns2 = [];
for (let i = 0; i < 6; i++) { fns2.push(() => i); i++; }
console.log('closures2', fns2.map(f => f()).join());
// do-while & while with continue
let dw = 0, dws = [];
do { dw++; if (dw === 2) continue; dws.push(dw); } while (dw < 4);
console.log('do-while', dws.join());
// try/finally overriding
function tf1() { try { return 'try'; } finally { console.log('finally runs'); } }
function tf2() { try { return 'try'; } finally { return 'finally'; } }
function tf3() { try { throw new Error('x'); } catch (e) { return 'catch:' + e.message; } finally { log.length = 0; } }
function tf4() { for (let i = 0; i < 3; i++) { try { if (i === 1) break; } finally { console.log('loop finally', i); } } return 'after'; }
function tf5() { try { try { throw 1; } finally { console.log('inner finally'); } } catch (e) { return 'outer caught ' + e; } }
function tf6() { l: try { return 'never'; } finally { break l; } return 'broke out of finally'; }
console.log(tf1(), tf2(), tf3(), tf4(), tf5(), tf6());
// optional catch binding, catch scope
try { throw 1; } catch { console.log('optional catch binding'); }
try { throw { a: 1, b: [2] }; } catch ({ a, b: [bb] }) { console.log('destructured catch', a, bb); }
// completion values via eval
console.log('completion', [
  eval('1; if (true) { 2; }'),
  eval('3; if (false) { 4; }'),
  eval('5; do { 6; break; } while (false)'),
  eval('7; try { 8 } finally { 9 }'),
  eval('let z = 10; z'),
  eval('switch (1) { case 1: "s1"; case 2: "s2"; break; }'),
  eval('for (var ii = 0; ii < 2; ii++) ii * 10'),
  eval('lbl: { "a"; break lbl; "b" }'),
  String(eval('var nothing = 1')),
  String(eval('function decl() {}')),
].join());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_control_flow(run, tier):
    """CATCHES: broken labelled break/continue, switch fallthrough with a middle default and case-evaluation order, for-in key ordering/deletion/primitives, iterator return() on early loop exit, per-iteration let bindings, try/finally completion overriding, and statement completion values seen through eval."""
    r = run([*tier, "-e", PROG_CONTROL_FLOW])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "control_flow")

PROG_DESTRUCTURING = r"""const J = JSON.stringify;
// array patterns: holes, defaults, rest, nested
const [a, , b = 10, [c, d = 'dd'] = ['cc'], ...rest] = [1, 2, undefined, undefined, 5, 6];
console.log('array', a, b, c, d, J(rest));
// defaults only on undefined, not null
const [n1 = 'def', n2 = 'def'] = [null, undefined];
console.log('null-vs-undef', n1, n2);
// default evaluation order & laziness
const order = [];
const t = (x) => (order.push(x), x);
const [x1 = t('x1'), x2 = t('x2'), x3 = t('x3')] = [undefined, 2];
console.log('lazy-defaults', x1, x2, x3, order.join());
// defaults referencing earlier bindings
const [p1 = 1, p2 = p1 * 2, p3 = p1 + p2] = [];
console.log('chained-defaults', p1, p2, p3);
// object patterns: rename, defaults, computed, rest excludes, nested
const key = 'dyn';
const { q: renamed, r = 'rdef', [key]: dynv, ['comp' + 'uted']: cv = 'cdef', s: { deep } = { deep: 'deepdef' }, ...orest } = { q: 'Q', dyn: 'D', other: 1, more: 2 };
console.log('object', renamed, r, dynv, cv, deep, J(orest));
// object rest copies own enumerable only, includes symbols
const sym = Symbol('k');
const src = Object.create({ inherited: 1 }, { own: { value: 1, enumerable: true }, hidden: { value: 2, enumerable: false } });
src[sym] = 'symval';
const { ...copy } = src;
console.log('rest-own', J(copy), copy[sym], 'inherited' in copy);
// destructuring primitives
const { length } = 'hello';
const [ch1, ...chs] = 'héllo';
const { toFixed } = 5;
console.log('primitives', length, ch1, chs.join(''), typeof toFixed);
// iterator closing in array destructuring
function it(limit) {
  let i = 0;
  return { [Symbol.iterator]() { return this; }, next() { return { value: i++, done: i > limit }; }, return() { console.log('  closed at', i); return {}; } };
}
const [i1, i2] = it(10);
console.log('partial', i1, i2);
const [...all] = it(3);
console.log('exhausted', J(all));
const [] = it(5);
// assignment patterns (not declarations)
let m, nn, oo = {};
[m, nn] = [nn, m] = [1, 2];
console.log('chained-assign', m, nn);
({ a: oo.x, b: oo['y'], c: [oo.z] = [9] } = { a: 'ax', b: 'by' });
console.log('assign-targets', J(oo));
let sw1 = 1, sw2 = 2;
[sw1, sw2] = [sw2, sw1];
console.log('swap', sw1, sw2);
// function params destructuring
function f({ a = 1, b: [b1, b2 = 'b2d'] = [] } = {}, ...[r1, r2]) { return [a, b1, b2, r1, r2].join('/'); }
console.log('params', f(), f({ a: 'A', b: ['B'] }, 'r1', 'r2', 'r3'));
console.log('fn-length', f.length, ((a, b = 1, c) => 0).length, ((...a) => 0).length, (function (a, b) {}).length);
// for-of destructuring
const pairs = [];
for (const [k, { v = 'nv' }] of [['a', { v: 1 }], ['b', {}]]) pairs.push(k + v);
for (const { length: L } of ['xx', 'yyy']) pairs.push(L);
console.log('for-of-destr', pairs.join());
// errors
const errs = [
  () => { const { z } = null; },
  () => { const [z] = {}; },
  () => { const [z] = 5; },
  () => { let { a: { b } } = { a: undefined }; },
  () => { ({ z } = undefined); },
  () => { const [{ x }] = [null]; },
];
for (const e of errs) { try { e(); console.log('no error'); } catch (err) { console.log(err.name + ': ' + err.message); } }
// getter call order during destructuring
const evs = [];
const prox = new Proxy({ a: 1, b: 2 }, { get(t, k) { evs.push('get:' + String(k)); return t[k]; }, ownKeys(t) { evs.push('ownKeys'); return Reflect.ownKeys(t); }, getOwnPropertyDescriptor(t, k) { evs.push('gopd:' + String(k)); return Reflect.getOwnPropertyDescriptor(t, k); } });
const { b: pb, ...prest } = prox;
console.log('proxy-order', evs.join(' '), J(prest));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_destructuring(run, tier):
    """CATCHES: destructuring that mishandles holes, defaults (only on undefined, lazily, in order), rest elements/properties (own enumerable incl. symbols), iterator closing, assignment-pattern targets, parameter patterns, function length, the exact TypeError messages for null/non-iterable sources and the proxy trap order of object rest."""
    r = run([*tier, "-e", PROG_DESTRUCTURING])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "destructuring")

PROG_FUNCTIONS = r"""const show = (label, f) => { try { console.log(label, f()); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// hoisting
show('fn-hoist', () => hoisted());
function hoisted() { return 'hoisted ok'; }
show('var-hoist', () => { const r = typeof vv; var vv = 1; return r; });
// TDZ
show('tdz-let', () => { const r = tl; let tl = 1; return r; });
show('tdz-typeof', () => { typeof tdzv; let tdzv; });
show('tdz-closure', () => { const g = () => later; try { return g(); } finally { } let later = 1; });
show('tdz-class', () => { new K(); class K {} });
show('tdz-self-ref', () => { let s = s + 1; });
show('tdz-default-param', () => (function (a = b, b = 1) { return a; })());
show('tdz-switch', () => { switch (1) { case 0: let sx = 1; case 1: return sx; } });
show('const-assign', () => { const c = 1; c = 2; });
show('const-assign-compound', () => { const c = 1; c += 2; });
show('const-in-loop', () => { for (const i = 0; i < 2; i++) {} });
show('fn-name-binding', () => { const f = function g() { g = 1; return typeof g; }; return f(); });
show('fn-name-binding-strict', () => { const f = function g() { 'use strict'; g = 1; }; return f(); });
// closure counter & shared env
function counter() { let n = 0; return { inc: () => ++n, get: () => n }; }
const c1 = counter(), c2 = counter();
c1.inc(); c1.inc(); c2.inc();
show('closures', () => [c1.get(), c2.get()].join());
// default params scope: separate from body var
show('param-scope', () => { var x = 'outer'; function f(a = () => x, x = 'param') { var x = 'body'; return a(); } return f(); });
show('param-arguments', () => (function (a, b = 2) { return arguments.length + ':' + b; })(1));
// arguments object mapping
function sloppyMapped(a, b) { arguments[0] = 'changed'; b = 'b2'; return [a, arguments[1], arguments.length].join(); }
function strictUnmapped(a, b) { 'use strict'; arguments[0] = 'changed'; b = 'b2'; return [a, arguments[1], arguments.length].join(); }
function defaultUnmapped(a, b = 0) { arguments[0] = 'changed'; return a; }
function restUnmapped(a, ...r) { a = 'changed'; return arguments[0]; }
show('args-sloppy', () => sloppyMapped(1, 2));
show('args-strict', () => strictUnmapped(1, 2));
show('args-default', () => defaultUnmapped(1));
show('args-rest', () => restUnmapped(1));
show('args-extra', () => (function (a) { arguments[1] = 'x'; return arguments.length + ':' + Array.from(arguments).join(); })(1, 2, 3));
show('args-unpassed', () => (function (a, b) { arguments[1] = 'set'; return String(b) + ':' + arguments.length; })(1));
show('args-tag', () => (function () { return Object.prototype.toString.call(arguments) + typeof arguments[Symbol.iterator]; })());
show('args-callee', () => (function me() { return arguments.callee === me; })());
show('args-callee-strict', () => (function () { 'use strict'; return arguments.callee; })());
show('args-arrow', () => (function () { return (() => arguments[0])(); })('outerArg'));
show('args-delete', () => (function (a) { delete arguments[0]; arguments[0] = 'new'; return a; })('orig'));
// this binding
const obj = { name: 'obj', regular() { return this?.name; }, arrow: () => typeof this, nested() { return [1].map(function () { return this; })[0]; }, nestedArrow() { return [1].map(() => this.name)[0]; } };
show('this-method', () => obj.regular());
const detached = obj.regular;
show('this-detached', () => detached());
show('this-nested-sloppy', () => obj.nested() === globalThis);
show('this-nested-arrow', () => obj.nestedArrow());
show('this-strict-call', () => (function () { 'use strict'; return this; }).call(5));
show('this-sloppy-call', () => typeof (function () { return this; }).call(5));
show('this-sloppy-null', () => (function () { return this; }).call(null) === globalThis);
show('this-paren', () => (obj.regular)());
show('this-comma', () => String((0, obj.regular)()));
// call/apply/bind
function sum(a, b, c) { return this.base + a + b + c; }
show('call', () => sum.call({ base: 100 }, 1, 2, 3));
show('apply', () => sum.apply({ base: 200 }, [1, 2, 3]));
const bound = sum.bind({ base: 300 }, 1);
show('bind', () => [bound(2, 3), bound.name, bound.length].join());
function Pt(x, y) { this.x = x; this.y = y; }
const BP = Pt.bind(null, 7);
show('bind-new', () => { const p = new BP(8); return [p.x, p.y, p instanceof Pt].join(); });
// function names
const anon = function () {};
const arrowN = () => {};
const o2 = { m() {}, ['c' + 'k']: () => {}, get gg() { return 1; }, [Symbol('desc')]: function () {} };
show('names', () => [anon.name, arrowN.name, o2.m.name, o2.ck.name, Object.getOwnPropertyDescriptor(o2, 'gg').get.name, o2[Object.getOwnPropertySymbols(o2)[0]].name, (function () {}).name === '', new Function('a', 'return a').name, (class {}).name === ''].join('|'));
// new.target
function NT() { return new.target === NT ? 'new' : String(new.target); }
show('new-target', () => [new NT() instanceof NT, NT()].join());
// recursion & mutual recursion
const isEven = (n) => n === 0 ? true : isOdd(n - 1);
const isOdd = (n) => n === 0 ? false : isEven(n - 1);
show('mutual', () => [isEven(10), isOdd(7)].join());
// IIFE variants
show('iife', () => [(function () { return 1; })(), (() => 2)(), !function () {}(), void function () {}()].join());
// function declarations in blocks (Annex B sloppy)
show('annexb', () => { { function blockFn() { return 'inner'; } } return typeof blockFn; });
show('annexb-strict', () => { 'use strict'; { function blockFn2() {} } return typeof blockFn2; });
show('call-non-fn', () => { const x = {}; x.foo(); });
show('call-undef-var', () => { let u; u(); });
show('call-number', () => (5)());
show('new-arrow', () => new (() => {})());
show('new-method', () => new ({ m() {} }).m());
show('undefined-var', () => notDefinedAnywhere + 1);
show('assign-undeclared-strict', () => { 'use strict'; undeclaredStrict = 1; });
show('assign-undeclared-sloppy', () => { undeclaredSloppy = 1; return globalThis.undeclaredSloppy; });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_functions_closures(run, tier):
    """CATCHES: hoisting/TDZ errors with exact ReferenceError text, const reassignment TypeErrors, default-parameter scope, mapped vs unmapped arguments objects, this binding for sloppy/strict/arrow/bound calls, function name inference, new.target, Annex B block functions, stack overflow RangeError and call-a-non-function messages."""
    r = run([*tier, "-e", PROG_FUNCTIONS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "functions_closures")

PROG_CLASSES = r"""const show = (label, f) => { try { console.log(label, f()); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
const order = [];
class Base {
  static count = 0;
  static #registry = [];
  #id;
  pub = (order.push('Base field'), 'pubval');
  static { order.push('Base static block'); this.tag = 'T' + Base.count; }
  constructor(id) { order.push('Base ctor'); this.#id = id; Base.count++; Base.#registry.push(id); }
  get id() { return this.#id; }
  set id(v) { throw new Error('readonly id'); }
  #secret() { return 'secret-' + this.#id; }
  reveal() { return this.#secret(); }
  static registry() { return Base.#registry.join(','); }
  static isBase(o) { return #id in o; }
  get #priv() { return 'privget'; }
  set #priv(v) { order.push('privset ' + v); }
  usePriv() { this.#priv = 'x'; return this.#priv; }
  toString() { return 'Base(' + this.#id + ')'; }
  static create(...a) { return new this(...a); }
}
class Derived extends Base {
  extra = (order.push('Derived field'), this.id * 10);
  #own = 'own';
  constructor(id) { order.push('Derived ctor before super'); super(id); order.push('Derived ctor after super'); }
  get id() { return super.id + 1000; }
  reveal() { return 'D:' + super.reveal(); }
  static create(...a) { const o = super.create(...a); o.via = 'Derived.create'; return o; }
  hasOwn(o) { return #own in o; }
  toString() { return 'Derived<' + super.toString() + '>'; }
}
const d = new Derived(7);
console.log('init-order', order.join(' > '));
order.length = 0;
show('getters', () => [d.id, d.pub, d.extra, d.reveal(), String(d)].join(' '));
show('static', () => [Base.count, Base.tag, Derived.count, Base.registry(), Object.hasOwn(Derived, 'count')].join(' '));
show('brand', () => [Base.isBase(d), Base.isBase({}), d.hasOwn(d), d.hasOwn(new Base(1))].join(' '));
show('priv-accessor', () => d.usePriv() + ' ' + order.join());
show('static-inherit', () => { const x = Derived.create(3); return [x.constructor.name, x.via, x.id].join(' '); });
show('readonly-setter', () => { d.id = 5; });
show('priv-on-wrong-obj', () => Base.prototype.reveal.call({}));
show('priv-read-wrong', () => Object.getOwnPropertyDescriptor(Base.prototype, 'id').get.call({}));
show('priv-static-wrong', () => Base.registry.call(Derived) && Base.isBase(5));
show('class-call', () => Base());
show('class-proto-methods', () => [Object.getOwnPropertyNames(Base.prototype).join(), Object.getOwnPropertyDescriptor(Base.prototype, 'reveal').enumerable, typeof Object.getOwnPropertyDescriptor(Base, 'prototype').writable].join(' | '));
// derived without super / return override
class NoSuper extends Base { constructor() { } }
show('no-super', () => new NoSuper());
class ReturnsObj extends Base { constructor() { return { custom: true }; } }
show('return-obj', () => JSON.stringify(new ReturnsObj()));
class ReturnsPrim extends Base { constructor() { super(1); return 5; } }
show('return-prim-after-super', () => new ReturnsPrim() instanceof ReturnsPrim);
class ReturnsPrimNoSuper extends Base { constructor() { return 5; } }
show('return-prim-derived', () => new ReturnsPrimNoSuper());
class Plain { constructor() { order.push("Plain ctor"); } }
class SuperTwice extends Plain { constructor() { super(); super(); } }
show('super-twice', () => { order.length = 0; try { new SuperTwice(); } finally { console.log(order.join()); } });
class ThisBeforeSuper extends Base { constructor() { this.x = 1; super(1); } }
show('this-before-super', () => new ThisBeforeSuper());
class SuperInArrow extends Base { constructor() { const f = () => super(42); f(); } }
show('super-in-arrow', () => new SuperInArrow().id);
// extends null / expressions / non-constructors
show('extends-null', () => { class N extends null {} return Object.getPrototypeOf(N.prototype) === null; });
show('extends-null-new', () => { class N extends null {} return new N(); });
show('extends-expr', () => { const mixin = (B) => class extends B { mixed() { return 'mixed ' + this.id; } }; return new (mixin(Base))(9).mixed(); });
show('extends-non-ctor', () => { class X extends 5 {} });
show('extends-arrow', () => { class X extends (() => {}) {} });
show('extends-bad-proto', () => { function F() {} F.prototype = 3; class X extends F {} });
// new.target in classes
class NTBase { constructor() { this.nt = new.target.name; } }
class NTDerived extends NTBase {}
show('new-target', () => [new NTBase().nt, new NTDerived().nt].join());
show('reflect-construct', () => { function Other() {} const o = Reflect.construct(NTBase, [], Other); return [o.nt, Object.getPrototypeOf(o) === Other.prototype].join(); });
// class name binding is const inside, class expressions
show('inner-name-const', () => { class C { static m() { C = 1; } } C.m(); });
show('outer-rebind', () => { let C = class Inner { static who() { return Inner.name; } }; const saved = C; C = null; return saved.who(); });
// accessors, computed keys, static/instance same name, symbol methods
let counter = 0;
class Comp {
  static [`s${++counter}`]() { return 's'; }
  [`m${++counter}`]() { return 'm'; }
  static ['x'] = 1; ['x'] = 2;
  *[Symbol.iterator]() { yield 1; yield 2; }
  async am() { return 'async'; }
  static async *ag() { yield 'ag'; }
  'quoted key'() { return 'q'; }
  42() { return 'num'; }
  static accessor = 'notkeyword';
}
show('computed', () => [typeof Comp.s1, typeof new Comp().m2, Comp.x, new Comp().x, [...new Comp()].join(), new Comp()['quoted key'](), new Comp()[42](), Comp.accessor].join(' '));
// field initializers: this, arrow capture, computed key evaluated once
let keyEvals = 0;
class Fields { [(keyEvals++, 'k')] = this; arrow = () => this; static s = this; static t = Fields.s === Fields; }
const f1 = new Fields(), f2 = new Fields();
show('fields', () => [keyEvals, f1.k === f1, f1.arrow() === f1, Fields.s === Fields, Fields.t].join());
// private methods are not writable
show('priv-method-assign', () => { class PM { #m() {} assign() { this.#m = 1; } } new PM().assign(); });
show('priv-getter-only', () => { class PG { get #g() { return 1; } assign() { this.#g = 1; } } new PG().assign(); });
show('priv-setter-only', () => { class PS { set #s(v) {} read() { return this.#s; } } new PS().read(); });
show('priv-double-init', () => { class Stamp extends class { constructor(o) { return o; } } { #stamp = 1; static has(o) { return #stamp in o; } } const o = {}; new Stamp(o); const r = Stamp.has(o); new Stamp(o); return r; });
show('in-non-object', () => { class Q { #p; static t(v) { return #p in v; } } return Q.t(1); });
// instanceof with Symbol.hasInstance
class Even { static [Symbol.hasInstance](n) { return n % 2 === 0; } }
show('hasInstance', () => [2 instanceof Even, 3 instanceof Even].join());
// species
class MyArr extends Array { static get [Symbol.species]() { return Array; } }
const ma = MyArr.from([1, 2, 3]);
show('species', () => [ma instanceof MyArr, ma.map(x => x) instanceof MyArr, ma.length, MyArr.of(1).constructor.name].join());
class Arr2 extends Array {}
show('subclass-array', () => { const a = new Arr2(); a.push(1, 2); a[5] = 6; return [a.length, a.filter(Boolean) instanceof Arr2, Array.isArray(a)].join(); });
class MyErr extends Error { constructor(m) { super(m); this.name = 'MyErr'; } }
show('subclass-error', () => { const e = new MyErr('bad'); return [e instanceof Error, e.message, String(e), Object.prototype.toString.call(e)].join(' | '); });
// object literal super / __proto__
const protoObj = { greet() { return 'proto greet'; } };
const lit = { __proto__: protoObj, greet() { return 'lit+' + super.greet(); }, ['__proto__']: 'computed is own' };
show('object-super', () => [lit.greet(), Object.getPrototypeOf(lit) === protoObj, Object.hasOwn(lit, '__proto__')].join(' | '));
show('getter-setter-literal', () => { const o = { _v: 1, get v() { return this._v * 2; }, set v(x) { this._v = x; } }; o.v = 21; return o.v; });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_classes(run, tier):
    """CATCHES: class semantics errors -- field/static-block/constructor initialisation order, private methods/accessors/brand checks (#x in o), super property and super() rules, derived-constructor return rules, extends null/expressions, species, Symbol.hasInstance, computed keys, and the exact TypeError/ReferenceError messages for each misuse."""
    r = run([*tier, "-e", PROG_CLASSES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "classes")

PROG_GENERATORS = r"""const J = JSON.stringify;
const R = (r) => J(r);
function* g1() {
  const x = yield 1;
  console.log('  got', x);
  try {
    yield 2;
  } finally {
    console.log('  g1 finally');
  }
  return 'end';
}
let it = g1();
console.log('basic', R(it.next('ignored')), R(it.next('X')), R(it.next()), R(it.next()), R(it.next()));
it = g1();
it.next(); it.next('a');
console.log('return-in-try', R(it.return('early')), R(it.next()));
it = g1();
console.log('return-before-start', R(it.return('r0')), R(it.next()));
it = g1();
try { it.throw(new Error('before start')); } catch (e) { console.log('throw-before-start', e.message, R(it.next())); }
// throw caught inside generator
function* g2() { while (true) { try { yield 'waiting'; } catch (e) { console.log('  caught inside', e); yield 'recovered'; } } }
it = g2();
console.log('throw-caught', R(it.next()), R(it.throw('E1')), R(it.next()), R(it.return('done')));
// finally that yields during return
function* g3() { try { yield 1; } finally { yield 'from-finally'; console.log('  after finally yield'); } }
it = g3();
console.log('yield-in-finally', R(it.next()), R(it.return('R')), R(it.next()), R(it.next()));
// finally overriding return
function* g4() { try { yield 1; } finally { return 'override'; } }
it = g4(); it.next();
console.log('finally-override', R(it.return('orig')));
// yield* delegation with return value, and to arrays/strings
function* inner() { const r = yield 'i1'; console.log('  inner received', r); yield 'i2'; return 'inner-ret'; }
function* outer() { const v = yield* inner(); yield 'outer got ' + v; yield* [10, 20]; yield* 'ab'; }
console.log('delegate', [...outer()].join());
it = outer(); it.next(); 
console.log('delegate-next-arg', R(it.next('sent')));
// yield* forwards throw/return to inner iterator
const logIter = {
  [Symbol.iterator]() { return this; },
  i: 0,
  next(v) { console.log('  logIter.next', v); return { value: 'n' + this.i++, done: false }; },
  throw(e) { console.log('  logIter.throw', e); return { value: 'thrown-handled', done: false }; },
  return(v) { console.log('  logIter.return', v); return { value: 'ret-' + v, done: true }; },
};
function* del() { const r = yield* logIter; console.log('  del resumed with', r); return r; }
it = del();
console.log('fwd', R(it.next('first')), R(it.next('second')), R(it.throw('T')), R(it.return('Z')));
// yield* to iterator without throw: closes then TypeError
const noThrow = { [Symbol.iterator]() { return this; }, next() { return { value: 1, done: false }; }, return() { console.log('  noThrow.return called'); return {}; } };
function* del2() { yield* noThrow; }
it = del2(); it.next();
try { it.throw('x'); } catch (e) { console.log('no-throw-method', e.name + ': ' + e.message); }
// generator state errors
function* selfRef() { it2.next(); yield 1; }
const it2 = selfRef();
try { it2.next(); } catch (e) { console.log('reentrant', e.name + ': ' + e.message); }
try { new g1(); } catch (e) { console.log('new-gen', e.name + ': ' + e.message); }
// generator prototype chain & toString tag
const GenProto = Object.getPrototypeOf(g1);
console.log('proto', Object.prototype.toString.call(g1()), GenProto[Symbol.toStringTag], g1.prototype === Object.getPrototypeOf(g1()), typeof g1().next, g1()[Symbol.iterator]() instanceof g1);
// infinite generator with take
function* nat() { let n = 0; while (true) yield n++; }
const take = (n, gen) => { const out = []; for (const v of gen) { if (out.length >= n) break; out.push(v); } return out; };
console.log('take', take(5, nat()).join());
// generator methods, args, this
const obj = { base: 100, *gen(a, b) { yield this.base + a; yield arguments.length + b; } };
console.log('method-gen', [...obj.gen(1, 2)].join());
// spread, destructure, Array.from consume generator
function* abc() { yield 'a'; yield 'b'; yield 'c'; }
const [first, ...others] = abc();
console.log('consume', first, others.join(), Array.from(abc(), (x) => x.toUpperCase()).join(), Math.max(...(function* () { yield 3; yield 9; yield 4; })()));
// yield precedence & expressions
function* prec() { const a = yield 1 + 1; const b = (yield) || 'default'; yield [a, b]; yield yield 'nested'; }
it = prec();
console.log('precedence', R(it.next()), R(it.next('A')), R(it.next()), R(it.next()), R(it.next('inner-sent')), R(it.next('outer-sent')));
// throw from generator body propagates, then done
function* boom() { yield 1; throw new Error('gen boom'); }
it = boom(); it.next();
try { it.next(); } catch (e) { console.log('gen-throw', e.message, R(it.next())); }
// iterator helpers on generators (if present)
console.log('helpers', typeof nat().map === 'function' ? nat().filter((x) => x % 2).map((x) => x * x).take(4).toArray().join() : 'none');
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_generators(run, tier):
    """CATCHES: generator protocol bugs -- next/return/throw before start, in try/finally, yields inside finally, finally overriding return, yield* forwarding of next/throw/return and its missing-throw TypeError, reentrancy errors, yield precedence and iterator helpers on generator objects."""
    r = run([*tier, "-e", PROG_GENERATORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "generators")

PROG_ASYNC = r"""const log = (...a) => console.log(...a);
log('sync start');
setTimeout(() => log('timeout 0'), 0);
queueMicrotask(() => log('microtask 1'));
Promise.resolve().then(() => log('then 1')).then(() => log('then 2')).then(() => log('then 3'));
(async () => {
  log('async fn body (sync part)');
  await null;
  log('after await null');
  await new Promise((r) => setTimeout(r, 0));
  log('after await timeout');
  await section2();
})();
// await thenable takes extra ticks
(async () => { await { then(r) { log('thenable.then called'); r('T'); } }; log('after await thenable'); })();
// async return of promise takes 2 extra ticks compared to plain value
async function retPromise() { return Promise.resolve('rp'); }
async function retValue() { return 'rv'; }
retPromise().then((v) => log('resolved', v));
retValue().then((v) => log('resolved', v));
// rejection & try/catch in async
async function thrower() { await 1; throw new TypeError('async boom'); }
(async () => { try { await thrower(); } catch (e) { log('caught async', e.name, e.message); } finally { log('async finally'); } })();
// Promise combinators
Promise.all([1, Promise.resolve(2), { then(r) { r(3); } }]).then((v) => log('all', v.join()));
Promise.all([1, Promise.reject(new Error('all-rejects')), new Promise(() => {})]).catch((e) => log('all-reject', e.message));
Promise.allSettled([Promise.reject(new Error('no')), 'ok']).then((rs) => log('allSettled', JSON.stringify(rs.map((r) => r.status + ':' + (r.value ?? r.reason.message)))));
Promise.race([new Promise(() => {}), Promise.resolve('settled-first'), 'plain-later']).then((v) => log('race', v));
Promise.any([Promise.reject(1), Promise.reject(2)]).catch((e) => log('any', e.constructor.name, e.errors.join(), e.message));
log('sync end');
// async generators & for await
async function* agen() {
  try {
    yield 'a1';
    yield await Promise.resolve('a2');
    yield Promise.resolve('a3-unwrapped');
  } finally {
    log('agen finally');
  }
}
async function section2() {
  log('--- async iteration');
  const got = [];
  for await (const v of agen()) got.push(v);
  log('for-await', got.join());
  // for await over sync iterable of promises
  const got2 = [];
  for await (const v of [Promise.resolve('p1'), 'plain', Promise.resolve('p2')]) got2.push(v);
  log('for-await-sync', got2.join());
  // break closes the async generator
  for await (const v of agen()) { log('first only', v); break; }
  // async generator queueing: requests are queued
  const ag = agen();
  const ps = [ag.next(), ag.next(), ag.return('R'), ag.next()];
  const rs = await Promise.all(ps);
  log('queued', JSON.stringify(rs));
  // throw into async generator
  async function* catcher() { while (true) { try { yield 'ready'; } catch (e) { log('agen caught', e); return 'stopped'; } } }
  const c = catcher();
  log('agen-throw', JSON.stringify(await c.next()), JSON.stringify(await c.throw('X')), JSON.stringify(await c.next()));
  // yield* in async generator delegating to sync and async iterables
  async function* delegator() { yield* ['s1', 's2']; const r = yield* agen(); yield 'after'; }
  const dv = [];
  for await (const v of delegator()) dv.push(v);
  log('async-delegate', dv.join());
  // custom async iterator
  const custom = { [Symbol.asyncIterator]() { let i = 0; return { next: () => Promise.resolve({ value: i * i, done: i++ >= 3 }), return: () => { log('custom return'); return Promise.resolve({ done: true }); } }; } };
  const cv = [];
  for await (const v of custom) cv.push(v);
  log('custom-async', cv.join());
  // errors
  try { for await (const v of { [Symbol.asyncIterator]: 5 }) {} } catch (e) { log('err1', e.name + ': ' + e.message); }
  try { for await (const v of 42) {} } catch (e) { log('err2', e.name + ': ' + e.message); }
  try { for await (const v of { [Symbol.asyncIterator]() { return { next() { return 5; } }; } }) {} } catch (e) { log('err3', e.name + ': ' + e.message); }
  // await in various positions
  const arr = [await 1, await Promise.resolve(2)];
  const objv = { a: await 'x', [await 'k']: await 'v' };
  log('await-positions', arr.join(), JSON.stringify(objv), (await 3) + (await 4), `${await 'tpl'}`);
  // promise ordering between two async functions interleaving
  const trace = [];
  async function A() { trace.push('A1'); await null; trace.push('A2'); await null; trace.push('A3'); }
  async function B() { trace.push('B1'); await null; trace.push('B2'); await null; trace.push('B3'); }
  A(); B();
  await new Promise((r) => setTimeout(r, 0));
  log('interleave', trace.join());
  // async yield* forwards throw/return to the inner async iterator
  const innerLog = [];
  const inner = {
    [Symbol.asyncIterator]() { return this; },
    i: 0,
    next(v) { innerLog.push('next:' + v); return Promise.resolve({ value: 'in' + this.i++, done: false }); },
    throw(e) { innerLog.push('throw:' + e); return Promise.resolve({ value: 'handled-' + e, done: false }); },
    return(v) { innerLog.push('return:' + v); return Promise.resolve({ value: 'ret-' + v, done: true }); },
  };
  async function* outerDel() { const r = yield* inner; innerLog.push('resumed ' + r); }
  const od = outerDel();
  const steps = [await od.next('a'), await od.next('b'), await od.throw('T'), await od.return('Z'), await od.next()];
  log('async-yield*-forward', JSON.stringify(steps), innerLog.join(' '));
  // inner async iterator without throw(): it is closed and the outer gets a TypeError
  const closed = [];
  const noThrow = { [Symbol.asyncIterator]() { return this; }, next() { return Promise.resolve({ value: 1, done: false }); }, return() { closed.push('closed'); return Promise.resolve({ done: true }); } };
  async function* del2() { yield* noThrow; }
  const d2 = del2();
  await d2.next();
  try { await d2.throw('x'); } catch (e) { log('async-no-throw', e.name + ': ' + e.message, closed.join()); }
  // inner without return(): outer return completes with the given value
  const noReturn = { [Symbol.asyncIterator]() { return this; }, next() { return Promise.resolve({ value: 'nr', done: false }); } };
  async function* del3() { try { yield* noReturn; } finally { log('del3 finally'); } }
  const d3 = del3();
  await d3.next();
  log('async-no-return', JSON.stringify(await d3.return('early')));
  // yield* over a sync iterable inside an async generator awaits each value
  async function* del4() { const r = yield* [Promise.resolve('sync-p1'), 'sync-v2']; return r; }
  const got4 = [];
  for await (const v of del4()) got4.push(v);
  log('async-yield*-sync', got4.join());
}
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_async_ordering(run, tier):
    """CATCHES: wrong microtask/macrotask interleaving of await, thenables, async return of promises, promise combinators, async generators (queued requests, return/throw, finally on break), for-await over sync and async iterables, and the async-iteration TypeError messages."""
    r = run([*tier, "-e", PROG_ASYNC])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "async_ordering")

PROG_EVAL = r"""const show = (label, f) => { try { console.log(label, f()); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
var gvar = 'global';
// direct vs indirect eval scope
function scopes() {
  var gvar = 'local';
  const direct = eval('gvar');
  const indirect = (0, eval)('gvar');
  const viaAlias = (() => { const e = eval; return e('gvar'); })();
  const viaGlobalThis = globalThis.eval('gvar');
  return [direct, indirect, viaAlias, viaGlobalThis].join();
}
show('eval-scope', scopes);
// var leakage from sloppy direct eval, not from strict
show('eval-var-leak', () => { eval('var leaked = 1'); return typeof leaked; });
show('eval-let-noleak', () => { eval('let notLeaked = 1'); return typeof notLeaked; });
show('eval-strict-noleak', () => { 'use strict'; eval('var sv = 1'); return typeof sv; });
show('eval-strict-inner', () => { eval('"use strict"; var sv2 = 1'); return typeof sv2; });
show('eval-fn-decl-leak', () => { eval('function evf() { return "evf" }'); return evf(); });
show('indirect-creates-global', () => { (0, eval)('var madeGlobal = 42'); return globalThis.madeGlobal; });
show('eval-this', () => { const o = { m() { return eval('this.tag'); }, tag: 'obj-this' }; return o.m(); });
show('eval-arguments', () => (function () { return eval('arguments.length'); })(1, 2, 3));
show('eval-new-target', () => { function F() { return eval('new.target === F'); } return new F() instanceof F; });
show('eval-non-string', () => [eval(42), typeof eval({ a: 1 }), eval()].join());
show('eval-returns-last', () => eval('var q = 1; q + 1; if (q) { "branch" }'));
show('eval-syntax-err', () => eval('var 1x'));
show('eval-closure-capture', () => { let captured = 'cap'; return eval('() => captured')(); });
show('eval-modify-local', () => { let m = 1; eval('m = 99'); return m; });
show('eval-let-conflict', () => { var conflict; eval('let conflict = 2'); return conflict; });
show('eval-var-conflict', () => { let conflict2 = 1; { eval('var conflict2 = 2'); } });
show('eval-super', () => { const p = { who() { return 'proto'; } }; const o = { __proto__: p, who() { return eval('super.who()'); } }; return o.who(); });
// Function constructor
show('fn-ctor', () => new Function('a', 'b', 'return a * b')(6, 7));
show('fn-ctor-params', () => Function('a, b = 2', '...c', 'return a + b + c.length')(1));
show('fn-ctor-global-scope', () => { var gvar = 'shadow'; return Function('return gvar')(); });
show('fn-ctor-sloppy-this', () => Function('return this')() === globalThis);
show('fn-ctor-tostring', () => JSON.stringify(Function('a', 'b', 'return a').toString()));
show('fn-ctor-syntax', () => Function('return ('));
show('fn-ctor-bad-param', () => Function('a b', 'return 1'));
show('fn-ctor-injection', () => Function('/*', '*/){'));
show('generator-fn-ctor', () => { const GF = Object.getPrototypeOf(function* () {}).constructor; return [...GF('a', 'yield a; yield a * 2')(5)].join(); });
show('async-fn-ctor', () => { const AF = Object.getPrototypeOf(async function () {}).constructor; return AF.name + ':' + typeof AF('return 1')().then; });
// Function.prototype.toString preserves source
function   spaced ( a,b ) { /* c */ return a+b }
show('fn-tostring', () => JSON.stringify([spaced.toString(), (x => x * 2).toString(), (class Q { m() {} }).toString(), ({ m(a) { } }).m.toString(), Math.max.toString(), (function () {}).bind().toString()]));
// with statement
show('with', () => {
  const o = { a: 1, b: 2 };
  let res;
  with (o) { res = a + b; a = 10; var declaredInWith = 'v'; c = 'leak?'; }
  return [res, o.a, declaredInWith, typeof o.c, typeof globalThis.c].join();
});
show('with-unscopables', () => { const arr = [1, 2]; const values = 'outer-values'; with (arr) { return [values, typeof push, length].join(); } });
show('with-proto-chain', () => { const o = Object.create({ inherited: 'inh' }); with (o) { return inherited; } });
show('with-fn-call-this', () => { const o = { name: 'withobj', f() { return this.name; } }; with (o) { return f(); } });
show('with-proxy-has', () => { const seen = []; const p = new Proxy({ x: 1 }, { has(t, k) { seen.push(String(k)); return k in t; } }); with (p) { x; typeof y; } return seen.join(); });
// globalThis
show('globalThis', () => [typeof globalThis, globalThis === this || 'module-this', globalThis.globalThis === globalThis, Object.getOwnPropertyDescriptor(globalThis, 'globalThis').enumerable].join());
show('global-props', () => [typeof globalThis.undefined, Object.getOwnPropertyDescriptor(globalThis, 'NaN').writable, Object.getOwnPropertyDescriptor(globalThis, 'Infinity').configurable].join());
show('global-fn-decl', () => { (0, eval)('function globalDecl() { return 1 }'); return typeof globalThis.globalDecl; });
show('undefined-readonly', () => { undefined = 5; return String(undefined); });
show('undefined-readonly-strict', () => { 'use strict'; undefined = 5; });
show('NaN-assign-strict', () => { 'use strict'; NaN = 1; });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_eval_function_with(run, tier):
    """CATCHES: direct vs indirect eval scoping, var leakage rules (sloppy/strict eval), eval/var conflicts, Function constructor scope and synthesized source text, Function.prototype.toString source preservation, with-statement lookups (unscopables, proxies, call this) and read-only global assignments."""
    r = run([*tier, "-e", PROG_EVAL])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "eval_function_with")

PROG_EARLY_ERRORS = r"""const cases = [
  'let a; let a;',
  'const a = 1; var a;',
  'let let = 1;',
  'const c;',
  'for (const x; ;) {}',
  'a => { "use strict"; delete a; }',
  '"use strict"; delete x;',
  '"use strict"; with (o) {}',
  '"use strict"; var eval = 1;',
  '"use strict"; arguments = 1;',
  '"use strict"; eval++;',
  '"use strict"; var yield;',
  '"use strict"; var let = 1;',
  '"use strict"; implements = 1;',
  '"use strict"; 010',
  '"use strict"; "\\01"',
  '"use strict"; function f(a, a) {}',
  'function f(a, a) { "use strict" }',
  '(a, a) => 1',
  'function f(a = 1) { "use strict" }',
  'function* g() { var yield; }',
  'function* g() { yield = 1; }',
  'async function f() { var await; }',
  'async function f(a = await 1) {}',
  'function* g(a = yield) {}',
  'return 1',
  'break;',
  'continue;',
  'x: while (1) { (() => { break x; })(); }',
  'x: { continue x; }',
  'x: x: ;',
  'while (1) { break nope; }',
  'if (1) let x = 1;',
  'if (1) function* g() {}',
  'while (0) function f() {}',
  'label: function* g() {}',
  'try {}',
  'switch (1) { default: default: }',
  'new.target',
  'super.x',
  'function f() { super(); }',
  'class A { constructor() { super(); } }',
  'class A { constructor() {} constructor() {} }',
  'class A { get constructor() {} }',
  'class A { *constructor() {} }',
  'class A { static prototype() {} }',
  'class A { #x; #x; }',
  'class A { #constructor; }',
  'class A { m() { this.#y; } }',
  'this.#z',
  'class A { #p; m() { delete this.#p; } }',
  'class A { #q; m() { super.#q; } }',
  'class A { static { return; } }',
  'class A { static { await 1; } }',
  'class A { static { arguments; } }',
  'class A { get g(a) {} }',
  'class A { set s() {} }',
  'class A { set s(...r) {} }',
  'class A extends B { x = super(); }',
  '({ a: 1 } = 1);',
  '1 = 2;',
  'a + 1 = 2;',
  '++a++;',
  '(a, b) = 1;',
  '[...a, b] = c;',
  'for (let x of [], []) {}',
  'for (var i = 0 of []) {}',
  'for (let [a] = 1 in {}) {}',
  'for await (const x of []) {}',
  'async function f() { for await (x in y) {} }',
  'a ?? b || c',
  '-2 ** 2',
  'async function f() { await 2 ** 2 }',
  'new a?.b()',
  'a?.`tpl`',
  'a?.b = 1',
  'import.meta',
  'import x from "y";',
  'export const e = 1;',
  'yield => 1; function* g() { yield => 1; }',
  'var obj = { get x(a) {} };',
  'var obj = { async *[x] () {} , async\n m() {} };',
  '({ a = 1 });',
  'let [a, a] = [];',
  'try {} catch ([e, e]) {}',
  'try {} catch (e) { let e; }',
  '`\\unicode`',
  '"unterminated',
  '/unterminated',
  '/a/gg',
  '0b12',
  '1__0',
  '1_',
  '08n',
  '.5n',
  '1e5n',
  'var a\\u0020b;',
  'v\\u0061r x = 1;',
  'throw\nnew Error()',
  'a\n=>1',
  'async x\n=> 1',
  '({ async\nfoo() {} })',
  'let\nlet = 1',
  'function f() { "use strict"; 0777 }',
  '"use strict"; ({ eval } = {});',
  '"use strict"; function eval() {}',
  '"use strict"; (function arguments() {})',
  '"use strict"; label: function f() {}',
  'class let {}',
  'class A { [super.x]() {} }',
  '(async function await() {})',
  '(function* yield() {})',
  'using x = 1;',
  '{ using x; }',
  'switch (1) { case 1: using y = null; }',
  'for (using x in {}) {}',
  '{ using [a] = b; }',
  '@dec function f() {}',
  'x = { __proto__: 1, __proto__: 2 }',
  'let x = 1; { var x; }',
  'function f(a) { let a; }',
  'eval => { "use strict" }; (eval) => { "use strict" }',
  '((a)) => 1',
  '({}) => 1',
  'async (a = await 1) => a',
  '(...a, b) => 1',
  'function f(...a,) {}',
  'a ? b',
  '[a, b',
  '{',
  'f(',
  'new.foo',
  'import.foo',
  'x = 1 +',
  '"\\u{110000}"',
  '"\\u{zz}"',
  '"\\x0"',
];
for (const src of cases) {
  let msg;
  try { (0, eval)(src); msg = 'no error'; }
  catch (e) { msg = e instanceof SyntaxError ? 'SyntaxError: ' + e.message : '(runtime) ' + e.name + ': ' + e.message; }
  console.log(JSON.stringify(src).padEnd(48) + ' -> ' + msg);
}
"""


def test_early_errors(run):
    """CATCHES: a parser that accepts invalid programs or reports different SyntaxError messages for ~140 early-error cases (redeclarations, strict-mode restrictions, class/private-name rules, invalid assignment targets, label/break/continue validation, using-declaration placement, numeric/escape lexing errors)."""
    r = run(["-e", PROG_EARLY_ERRORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "early_errors")

PROG_EARLY_ERRORS_2 = r"""const cases = [
  'class A { #x = 1; m() { return eval("this.#x"); } } new A().m()',
  'class A { #x = 1; m() { return eval("this.#y"); } } new A().m()',
  'class A { m() { eval("super()"); } } new A().m()',
  'class A extends Object { constructor() { super(); eval("super.toString"); } } new A(); "ok"',
  '(function () { eval("new.target"); })(); "ok"',
  'eval("new.target")',
  '{ let f; function f() {} }',
  '{ function f() {} let f; }',
  '{ async function f() {} function f() {} }',
  '{ function* g() {} function* g() {} }',
  '{ function h() {} function h() {} } "sloppy dup ok"',
  '"use strict"; { function h() {} function h() {} }',
  '{ class C {} let C; }',
  '({ if })',
  '({ \\u0069f })',
  '"use strict"; ({ implements })',
  'async function f() { ({ await }); }',
  'function* g() { ({ yield }); }',
  'while (1) { continue nope; }',
  'function* g() { a: yield: ; }',
  'async function f() { await: ; }',
  '"use strict"; let: ;',
  '"use strict"; static: ;',
  'a: b: function* g() {}',
  'l: async function f() {}',
  'var #a;',
  'function f(#a) {}',
  'const { "str" } = {};',
  '({ 1 } = {});',
  'if (1) label: function f() {}',
  'while (1) class C {}',
  'do x; foo',
  'for (let [let] of []) {}',
  'for (const let of []) {}',
  'for (let let = 0;;) {}',
  'for (async of []) {}',
  'for ({ a: 1 } of []) {}',
  'for (f() in {}) {}',
  'for (1 of []) {}',
  '"use strict"; for (eval of []) {}',
  '"use strict"; for (arguments in {}) {}',
  'for (var i = 0 in {}) {} "annex-b ok"',
  '"use strict"; for (var i = 0 in {}) {}',
  'for (let x = 1 of []) {}',
  'for (x of [], 1) {}',
  'async function f() { for await (var x in []) {} }',
  '`${a`',
  '({ a: 1, b })',
  'x = { get a() {}, get a() {} }; "dup getters ok"',
  '({ async *g() { yield await 1; } }); "ok"',
  '({ get [1 + 1]() { return 2; } })[2]',
  '(a = 1) => { "use strict"; }',
  '(function (a = 1) { "use strict"; })',
  'class A { constructor() {} ["constructor"]() {} } "computed ctor name ok"',
  'class A { static constructor() {} } "static constructor ok"',
  'class A { get #a() {} set #a(v) {} } "accessor pair ok"',
  'class A { get #a() {} get #a() {} }',
  'class A { #a; static #a; }',
  'class A { m() { class B { [this.#x]; } } #x; }',
  'class A { static { var await; } }',
  'class A { static { yield; } } "yield ident in static block ok"',
  'class A { static { super(); } }',
  'class A { x = arguments; }',
  'class A extends B { constructor() { (() => super())(); } } "arrow super ok"',
  'function f() { (() => super.x)(); }',
  'a?.b++',
  '++a?.b',
  'new a?.()',
  'new import("x")',
  'async () => { new await x; }',
  'n\\u0065w Object()',
  'new.t\\u0061rget',
  '(async function () { aw\\u0061it 1; })',
  '#x in {}',
  'class A { #f; m() { return #f in #f in {}; } }',
  'class A { #f; m() { return (#f) in {}; } }',
  'a ?? b && c',
  'a && b ?? c',
  '(a ?? b) || c; "parenthesized ok"',
  '(a = function () {}) => a',
  '((a)) = 1; "parenthesized ident assign ok"',
  '({ a }) = 1',
  '([a]) = 1',
  '[...a,] = []',
  '[(a)] = [1]; "parenthesized element ok"',
  '[(a = 1)] = []',
  '({ a: (b) } = {}); "parenthesized prop target ok"',
  '({ a: (b = 1) } = {})',
  'f() = 1',
  '"use strict"; f() = 1',
  'f()++',
  '"use strict"; f()++',
  'for (f() of []) {}',
  'import("x", {}, 3)',
  'import()',
  'import(...a)',
  'super.#x',
  'class A { #x; m() { super.#x; } }',
  'x = a?.b`tpl`',
  'export default 1',
  'yield',
  'function* g() { yield\n* 2; }',
  'function* g() { var o = { [yield]: 1 }; } "computed yield ok"',
  'function* g(x = yield) {}',
  'async function* g() { yield* await x; } "ok"',
  'let [a, ...b,] = [];',
  'let { ...{ a } } = {};',
  'let [...[a, b]] = [1, 2]; [a, b].join()',
  '({ ...{ a } } = {})',
  'var a = 1, a = 2; a',
  'let a, a;',
  'label: { label2: { break label; } } "ok"',
  'x: while (0) { y: { continue x; } } "ok"',
  'switch (1) { case 1: let a; case 2: let a; }',
  'switch (1) { case 1: var v; case 2: var v; } "ok"',
  'try {} catch (e) { var e; } "annex b ok"',
  'try {} catch (e) { for (var e in {}) {} } "annex b for-in ok"',
  'function f() { "use strict"; with (a) {} }',
  '0n.toString()',
  '1.e5n',
  '0x_1',
  '0b',
  '0o8',
  '09.5; "non-octal decimal float ok"',
  '"use strict"; 09',
  '"use strict"; "\\8"',
  '`\\8`',
  '"\\u{1F600}".length',
  '"\\u{}"',
  'a\\u{62}c = 3; abc',
  'var \\u{1F600} = 1;',
  '/(?<n>a)\\k<n>/.test("aa")',
  '/[/',
  '/a/\\u0067',
  'x = 1 /* unterminated',
  '"\\\r\nline continuation crlf"',
  'q = 5; q',
  '1 ?.5 : 2',
  '[1] ?.[0]',
  'a ¬ b',
  '@',
  'x = function () {} / 2; String(x)',
  'x = class {} / 2; String(x)',
  'x = {} / 2',
  '({} / 2)',
];
for (const src of cases) {
  let msg;
  try { const v = (0, eval)(src); msg = 'ok ' + (typeof v === 'string' ? JSON.stringify(v) : String(v)); }
  catch (e) { msg = (e instanceof SyntaxError ? 'SyntaxError: ' : '(runtime) ' + e.name + ': ') + e.message; }
  console.log(JSON.stringify(src).padEnd(66) + ' -> ' + msg);
}
"""


def test_early_errors_contextual(run):
    """CATCHES: parsers that get contextual early errors wrong -- private names through direct eval, block-level function/lexical clashes (sloppy vs strict), reserved shorthand properties, contextual labels, for-in/of head restrictions, Annex B allowances, escaped keywords, optional-chain/new/import() restrictions, ?? mixing, parenthesised assignment targets, numeric/regex/escape lexing errors and regex-vs-division after function/class expressions."""
    r = run(["-e", PROG_EARLY_ERRORS_2])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "early_errors_contextual")

PROG_EARLY_ERRORS_3 = r"""const cases = [
  'x = tru\\u0065',
  '({ m() { super; } })',
  'im\\u0070ort("x")',
  '`${ 1 + "\\u{zz}" }`',
  'String.raw`${ "\\x" }`',
  '({ #x: 1 })',
  '({ #m() {} })',
  '({ async *x })',
  '({ *g })',
  '({ m() { super(); } })',
  '({ a b })',
  '({ 1n: "big" })[1]',
  '({ % })',
  'function #f() {}',
  'async function f() { async function await() {} }',
  'function* g() { function* yield() {} }',
  '"use strict"; function yield() {}',
  'function f(implements) { "use strict"; }',
  'function f(eval) { "use strict"; }',
  'function f(a = super()) {}',
  'function f() { return super.x; }',
  'async function f() { class await {} }',
  'class A extends ( {}',
  'class A { ; ; m() { return "m"; } ; } new A().m()',
  'class A { m(a, a) {} }',
  '({ m(a, a) {} })',
  '({ m(a) { let a; } })',
  '"use strict"; (implements) => 1',
  'async (await) => 1',
  'async await => 1',
  'function* g() { (yield) => 1; }',
  '(a) => { let a; }',
  '"use strict"; (interface) => 1',
  'for ([a, ...b] of [[1, 2, 3]]) {} [a, b.join()].join("|")',
  'for ([...c, d] of []) {}',
  'for ({ ...o.p } of [{ k: 1 }]) {}',
  'for ({ ...{ a } } of []) {}',
  'for ([a = 1, [b] = [2]] of [[]]) {} a + b',
  'for ({ a = 5 } of [{}]) {} a',
  '"use strict"; for ([eval] of []) {}',
  '"use strict"; for ({ x: arguments } of []) {}',
  'for ({ __proto__: p } of [{ __proto__: null }]) {} String(p)',
  '[{ a = 0 }.x] = []',
  '({ a = 0 });',
  '({ a = 0 } = {}); a',
  '[{ b = 1 }] = [{}]; b',
  '({ c: { d = 1 } = {} } = {}); d',
  'x = { e = 1 }',
  '[a.b = 1] = []; "member default ok"',
  '[...a.b] = [1, 2]; a.b.join()',
  '[...[e, f]] = [3, 4]; e + f',
  '({ ...rest } = { a: 1, b: 2 }); JSON.stringify(rest)',
  '({ ...rest.inner } = { q: 1 })',
  '"use strict"; [arguments] = [];',
  '"use strict"; ({ eval = 1 } = {});',
  '"use strict"; ({ a: eval } = {});',
  '"use strict"; [...eval] = [];',
  '(a, b) => { "use strict"; }; "simple params ok"',
  '({ a, ...b }) => { "use strict"; }',
  'class A { static async *#m() {} static get #g() { return 1; } static s() { return A.#g; } } A.s()',
  'class A { static #x; static { this.#x = 7; } static g() { return A.#x; } } A.g()',
  'class A { accessor #p = 3; get p() { return this.#p; } } new A().p',
  'class A { accessor = 1; } new A().accessor',
  'class A { static accessor; } "static field named accessor ok"',
  'class A { accessor\n x = 1; } "accessor newline makes two fields"',
  'class A { get\n x() { return 1; } } new A().x',
  'class A { static\n m() { return "static via newline"; } } A.m()',
  'class A { async\n m() {} }',
  'class A { "constructor"() { this.q = 1; } } new A().q',
  'class A { get ["constructor"]() { return 1; } } "computed accessor named constructor ok"',
  'class A { static prototype = 1; }',
  'class A { static ["prototype"] = 1; }',
  'class A { constructor = 1; }',
  'class A { #constructor() {} }',
  'class A { static #a() {} #a; }',
  'class A { set #s(v) {} static get #s() {} }',
  'class A { m() { return #missing in this; } }',
  '"use strict"; with ({}) {}',
  'function f() { "use strict"; 08; }',
  'function f() { "\\07"; "use strict"; }',
  'function f() { "use strict"; "\\07"; }',
  'function f() { "a"; "\\07"; "use strict"; }',
];
for (const src of cases) {
  let msg;
  try { const v = (0, eval)(src); msg = 'ok ' + (typeof v === 'string' ? JSON.stringify(v) : String(v)); }
  catch (e) { msg = (e instanceof SyntaxError ? 'SyntaxError: ' : '(runtime) ' + e.name + ': ') + e.message; }
  console.log(JSON.stringify(src).padEnd(66) + ' -> ' + msg);
}
"""


def test_early_errors_patterns_classes(run):
    """CATCHES: early-error gaps in escaped keywords, template-substitution lexing, object-literal method/key rules, function/class/parameter naming in strict, async and generator contexts, arrow parameter bindings, destructuring-assignment and for-of pattern validation (cover grammar, rest position, eval/arguments targets), class element naming rules (constructor/prototype/private duplicates, accessor/get/static/async line breaks) and directive-prologue octal checks."""
    r = run(["-e", PROG_EARLY_ERRORS_3])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "early_errors_patterns_classes")

PROG_RUNTIME_ERRORS = r"""const cases = {
  'read-prop-undef': () => { let u; return u.x; },
  'read-prop-null-computed': () => { const n = null; return n['k' + 1]; },
  'write-prop-undef': () => { let u; u.x = 1; },
  'call-method-missing': () => { const o = { a: 1 }; o.missing(); },
  'call-nested-missing': () => { const o = { a: { b: {} } }; o.a.b.c(); },
  'call-computed-missing': () => { const o = {}; o['dyn' + 'amic'](); },
  'call-number-prop': () => { const o = { n: 5 }; o.n(); },
  'call-global-undef': () => { globalThis.nope(); },
  'call-result': () => { const f = () => 1; f()(); },
  'call-string': () => { 'str'(); },
  'new-non-ctor-var': () => { const x = 1; new x(); },
  'new-math-fn': () => new Math.max(),
  'new-symbol': () => new Symbol(),
  'new-bigint': () => new BigInt(1),
  'new-async-fn': () => { async function af() {} new af(); },
  'new-bound-arrow': () => { const a = () => {}; new (a.bind(null))(); },
  'in-primitive': () => 'x' in 'string',
  'instanceof-non-callable': () => ({}) instanceof {},
  'instanceof-bad-proto': () => { function F() {} F.prototype = 1; return ({}) instanceof F; },
  'hasInstance-not-callable': () => { const C = { [Symbol.hasInstance]: 1 }; return 1 instanceof C; },
  'spread-non-iterable': () => [...{}],
  'spread-call-non-iterable': () => Math.max(...5),
  'for-of-non-iterable': () => { for (const x of {}) {} },
  'iterator-next-not-object': () => { for (const x of { [Symbol.iterator]() { return { next() { return 1; } }; } }) {} },
  'iterator-returns-primitive': () => { for (const x of { [Symbol.iterator]() { return 5; } }) {} },
  'symbol-to-string': () => Symbol('s') + '',
  'symbol-to-number': () => Symbol('s') * 1,
  'symbol-template': () => `${Symbol('t')}`,
  'bigint-mix': () => 1n * 1,
  'toPrimitive-not-callable': () => +{ [Symbol.toPrimitive]: 'x' },
  'toPrimitive-returns-object': () => +{ [Symbol.toPrimitive]() { return {}; } },
  'valueOf-toString-objects': () => `${{ toString() { return {}; }, valueOf() { return {}; } }}`,
  'null-proto-to-string': () => String(Object.create(null)),
  'object-freeze-strict': () => { 'use strict'; const o = Object.freeze({ a: 1 }); o.a = 2; },
  'nonextensible-add-strict': () => { 'use strict'; const o = Object.preventExtensions({}); o.b = 1; },
  'getter-only-strict': () => { 'use strict'; const o = { get g() { return 1; } }; o.g = 2; },
  'delete-nonconfig-strict': () => { 'use strict'; delete Object.prototype; },
  'array-length-readonly': () => { 'use strict'; const a = Object.freeze([1]); a.push(2); },
  'invalid-array-length': () => new Array(-1),
  'invalid-array-length-set': () => { const a = []; a.length = 1.5; },
  'repeat-negative': () => 'x'.repeat(-1),
  'toFixed-range': () => (1).toFixed(101),
  'string-too-long': () => 'x'.repeat(2 ** 30).repeat(2 ** 10),
  'json-cycle': () => { const o = {}; o.self = o; JSON.stringify(o); },
  'json-bigint': () => JSON.stringify({ b: 1n }),
  'json-parse': () => JSON.parse('{bad'),
  'define-on-frozen': () => Object.defineProperty(Object.freeze({}), 'x', { value: 1 }),
  'set-proto-cycle': () => { const a = {}; const b = Object.create(a); Object.setPrototypeOf(a, b); },
  'reduce-empty': () => [].reduce((a, b) => a + b),
  'super-prop-null-proto': () => { const o = { m() { return super.x; } }; Object.setPrototypeOf(o, null); return o.m(); },
  'throw-in-getter': () => { const o = { get boom() { throw new RangeError('from getter'); } }; return o.boom; },
  'error-cause': () => { throw new Error('outer', { cause: 'the cause' }); },
  'aggregate': () => { throw new AggregateError([new Error('a')], 'agg msg'); },
};
for (const [name, fn] of Object.entries(cases)) {
  try { const v = fn(); console.log(name.padEnd(28), '=> returned', typeof v === 'string' ? JSON.stringify(v) : String(v)); }
  catch (e) {
    const extra = e && e.cause !== undefined ? ' cause=' + e.cause : (e instanceof AggregateError ? ' errors=' + e.errors.length : '');
    console.log(name.padEnd(28), '=>', e instanceof Error ? e.constructor.name + '/' + e.name + ': ' + e.message + extra : 'non-error ' + String(e));
  }
}
// errors thrown inside catch / finally, nested
try { try { throw new Error('first'); } finally { console.log('finally sees pending error'); } } catch (e) { console.log('outer got', e.message); }
try { try { throw new Error('first'); } catch (e) { throw new Error('second from catch'); } } catch (e) { console.log('outer got', e.message); }
try { try { throw new Error('first'); } finally { throw new Error('finally wins'); } } catch (e) { console.log('outer got', e.message); }
// Error properties
const e = new TypeError('msg');
console.log('error-props', e.name, e.message, e instanceof Error, Object.prototype.hasOwnProperty.call(e, 'message'), Object.keys(e).length, typeof e.stack, String(e), e.toString === Error.prototype.toString);
console.log('error-toString', Error.prototype.toString.call({ name: 'N', message: 'M' }), Error.prototype.toString.call({}), Error.prototype.toString.call({ name: '', message: 'only msg' }), Error.prototype.toString.call({ name: 'only name', message: '' }));
console.log('error-call-no-new', Error('x') instanceof Error, RangeError('r').name, new Error(undefined).hasOwnProperty('message'), String(new Error()));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_runtime_error_messages(run, tier):
    """CATCHES: runtime errors with the wrong constructor or message text -- property access on null/undefined, calling/constructing non-callables, in/instanceof misuse, non-iterables, Symbol/BigInt conversions, frozen/sealed writes in strict mode, RangeErrors, recursion limits, and try/catch/finally propagation."""
    r = run([*tier, "-e", PROG_RUNTIME_ERRORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "runtime_error_messages")

PROG_PROTOCOLS = r"""const log = (...a) => console.log(...a);
// Symbol.toPrimitive with hints
const tp = { [Symbol.toPrimitive](hint) { log('  hint', hint); return hint === 'number' ? 42 : hint === 'string' ? 'str' : 'dflt'; } };
log('toPrimitive', +tp, `${tp}`, tp + '', tp * 2, tp == 'dflt', String(tp), [tp] + '', Number(tp));
// valueOf / toString order
const vo = { valueOf() { log('  valueOf'); return 7; }, toString() { log('  toString'); return 'ts'; } };
log('valueOf-order', vo + 1, `${vo}`, vo > 6, [1, 2][vo - 6]);
const vo2 = { valueOf() { return {}; }, toString() { return '9'; } };
log('valueOf-fallback', vo2 * 2);
// Date default hint is string
const d = new Date(0);
log('date-hint', typeof (d + 1), typeof (d - 1));
// Symbol.iterator custom
class Range { constructor(a, b) { this.a = a; this.b = b; } *[Symbol.iterator]() { for (let i = this.a; i < this.b; i++) yield i; } }
log('iterator', [...new Range(1, 4)].join(), Array.from(new Range(0, 3)).join(), new Map([[1, 'a']].values()).size);
// Symbol.isConcatSpreadable
const spreadable = { length: 2, 0: 'x', 1: 'y', [Symbol.isConcatSpreadable]: true };
const notSpread = [3, 4]; notSpread[Symbol.isConcatSpreadable] = false;
log('concatSpreadable', JSON.stringify([1].concat(spreadable, notSpread)));
// Symbol.toStringTag
class Tagged { get [Symbol.toStringTag]() { return 'MyTag'; } }
log('toStringTag', Object.prototype.toString.call(new Tagged()), String(new Tagged()), Object.prototype.toString.call(null), Object.prototype.toString.call([]), Object.prototype.toString.call(function* () {}));
// Symbol.unscopables tested elsewhere; Symbol.match/replace/search/split
const matcher = { [Symbol.match](s) { return ['custom match ' + s]; }, [Symbol.replace](s, r) { return 'replaced ' + s + ' with ' + r; }, [Symbol.search]() { return 99; }, [Symbol.split](s) { return s.split('').reverse(); } };
log('regexp-symbols', 'abc'.match(matcher)[0], 'abc'.replace(matcher, 'X'), 'abc'.search(matcher), 'abc'.split(matcher).join(''));
const notRegex = /x/; notRegex[Symbol.match] = false;
log('isRegExp-false', '/x/'.startsWith(notRegex));
// Symbol registry
log('symbols', Symbol.for('k') === Symbol.for('k'), Symbol.keyFor(Symbol.for('k')), Symbol.keyFor(Symbol('k')), Symbol('desc').description, Symbol().description, Symbol.iterator.toString(), typeof Object(Symbol()));
// getters/setters on prototype chain
const base = {
  _v: 'base',
  get v() { return 'get:' + this._v; },
  set v(x) { log('  setter on proto, this is child?', this !== base); this._v = x; },
};
const child = Object.create(base);
child.v = 'childval';
log('proto-setter', child.v, base.v, Object.hasOwn(child, 'v'), Object.hasOwn(child, '_v'));
// non-writable on proto blocks assignment (sloppy silent), defineProperty bypasses
const roProto = Object.defineProperty({}, 'ro', { value: 'proto-ro', writable: false });
const roChild = Object.create(roProto);
roChild.ro = 'attempt';
log('proto-readonly-sloppy', roChild.ro, Object.hasOwn(roChild, 'ro'));
try { (function () { 'use strict'; roChild.ro = 'strict attempt'; })(); } catch (e) { log('proto-readonly-strict', e.name + ': ' + e.message); }
Object.defineProperty(roChild, 'ro', { value: 'own-defined', writable: true, enumerable: true, configurable: true });
log('defineProperty-shadow', roChild.ro, roProto.ro);
// getter-only on proto: assignment ignored
const gOnly = Object.create({ get g() { return 'proto-g'; } });
gOnly.g = 'nope';
log('getter-only-proto', gOnly.g, Object.keys(gOnly).length);
// setter receiving via Reflect.set with receiver
const recv = {};
Reflect.set(base, 'v', 'via-reflect', recv);
log('reflect-set-receiver', recv._v, base._v);
// property enumeration order
const ord = { z: 1, 10: 1, a: 1, 1: 1, [Symbol('s')]: 1, '1.5': 1, '4294967295': 1, '4294967294': 1 };
log('own-keys-order', Reflect.ownKeys(ord).map(String).join(), Object.keys(ord).join(), JSON.stringify(ord));
// __proto__ accessor & setPrototypeOf
const pp = {}; pp.__proto__ = Array.prototype;
log('__proto__', pp instanceof Array, Object.getPrototypeOf(Object.create(null)), ({ __proto__: null }) instanceof Object, '__proto__' in Object.create(null));
// defineProperty getter/setter, enumerable defaults
const dp = {};
Object.defineProperty(dp, 'acc', { get() { return 'acc-val'; }, configurable: true });
log('defineProperty-defaults', JSON.stringify(Object.getOwnPropertyDescriptor(dp, 'acc'), (k, v) => typeof v === 'function' ? 'fn' : v === undefined ? 'undef' : v), Object.keys(dp).length);
// Object.defineProperties / getOwnPropertyDescriptors / freeze / seal semantics
const fz = Object.freeze({ a: 1, nested: { b: 2 } });
fz.a = 99; fz.nested.b = 3; fz.added = 1;
log('freeze', fz.a, fz.nested.b, fz.added, Object.isFrozen(fz), Object.isFrozen(fz.nested), Object.isSealed(fz));
const sl = Object.seal({ a: 1 }); sl.a = 2; delete sl.a; sl.b = 1;
log('seal', JSON.stringify(sl), Object.isSealed(sl), Object.isExtensible(sl));
// accessor inheritance in classes with static and instance
class Temp { static #count = 0; #c = 0; get celsius() { return this.#c; } set celsius(v) { Temp.#count++; this.#c = v; } get fahrenheit() { return this.#c * 9 / 5 + 32; } set fahrenheit(f) { this.celsius = (f - 32) * 5 / 9; } static get sets() { return Temp.#count; } }
const tt = new Temp(); tt.fahrenheit = 212;
log('accessor-chain', tt.celsius, tt.fahrenheit, Temp.sets);
// Symbol.asyncIterator presence & well-known symbols are non-writable
log('well-known', typeof Symbol.asyncIterator, Object.getOwnPropertyDescriptor(Symbol, 'iterator').writable, Symbol.iterator in Array.prototype, Symbol.asyncIterator in (async function* () {})());
// instanceof uses Function.prototype[Symbol.hasInstance], bound functions
function F() {}
const BF = F.bind(null);
log('instanceof-bound', new F() instanceof BF, Function.prototype[Symbol.hasInstance].call(F, new F()), Object[Symbol.hasInstance]({}));
// Symbol.species for Promise
class MyP extends Promise {}
const mp = MyP.resolve(1).then((x) => x);
log('promise-species', mp instanceof MyP, MyP.resolve(1) instanceof MyP, Promise.resolve(mp) === mp);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_protocols_prototypes(run, tier):
    """CATCHES: well-known symbol hooks (toPrimitive hints, valueOf/toString order, iterator, isConcatSpreadable, toStringTag, match/replace/search/split, species, hasInstance) and prototype-chain accessor semantics (inherited setters, read-only inherited properties, Reflect.set receiver, own-key ordering, freeze/seal)."""
    r = run([*tier, "-e", PROG_PROTOCOLS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "protocols_prototypes")

PROG_USING = r"""const log = (...a) => console.log(...a);
const res = (name, opts = {}) => ({
  name,
  [Symbol.dispose]() { log('  dispose', name); if (opts.throws) throw new Error('dispose-fail ' + name); },
});
{
  using a = res('a'), b = res('b');
  using nul = null;
  using und = undefined;
  log('block body', a.name, b.name);
}
log('after block');
function early() {
  using r = res('fn-res');
  return 'returned ' + r.name;
}
log(early());
for (const n of ['x', 'y']) { using it = res('loop-' + n); log('iter', n); }
for (using fo of [res('for-of-1'), res('for-of-2')]) log('for-using body', fo.name);
// errors during body + dispose -> SuppressedError
try {
  using e1 = res('e1', { throws: true });
  using e2 = res('e2', { throws: true });
  throw new Error('body-error');
} catch (e) {
  log('caught', e.constructor.name, e.message);
  log('  error:', e.error.constructor.name, e.error.message);
  log('  suppressed:', e.suppressed.constructor.name, JSON.stringify(e.suppressed.message), e.suppressed.error.message, e.suppressed.suppressed.message);
}
try { using bad = { notDisposable: true }; } catch (e) { log('not disposable', e.name + ': ' + e.message); }
try { using bad2 = { [Symbol.dispose]: 5 }; } catch (e) { log('non-callable dispose', e.name + ': ' + e.message); }
try { (() => { using c = res('c'); c = 1; })(); } catch (e) { log('reassign using', e.name + ': ' + e.message); }
// DisposableStack
const stack = new DisposableStack();
stack.use(res('stack-use'));
stack.defer(() => log('  deferred fn'));
const adopted = stack.adopt('adopted-value', (v) => log('  adopt cleanup', v));
log('adopt returns', adopted, 'disposed?', stack.disposed);
const moved = stack.move();
log('after move', stack.disposed, moved.disposed);
moved.dispose();
moved.dispose();
log('moved disposed', moved.disposed);
try { moved.use(res('late')); } catch (e) { log('use after dispose', e.name + ': ' + e.message); }
{ using s2 = new DisposableStack(); s2.defer(() => log('  stack via using')); }
const se = new SuppressedError(new Error('err'), new Error('sup'), 'msg');
log('SuppressedError', se.name, se.message, se.error.message, se.suppressed.message, se instanceof Error);
// await using & AsyncDisposableStack
(async () => {
  {
    await using ar = { async [Symbol.asyncDispose]() { await null; log('  async dispose ar'); } };
    await using sr = res('sync-fallback-in-await-using');
    log('async block body');
  }
  log('after async block');
  const as = new AsyncDisposableStack();
  as.defer(async () => { log('  async deferred 1'); });
  as.use({ [Symbol.asyncDispose]: async () => log('  async use') });
  as.adopt(5, async (v) => log('  async adopt', v));
  await as.disposeAsync();
  log('async stack disposed', as.disposed);
  try {
    await using x = { async [Symbol.asyncDispose]() { throw new Error('async dispose err'); } };
  } catch (e) { log('async dispose error', e.message); }
  for await (using fa of [res('for-await-using')]) log('for await using body');
  log('done');
})();
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_using_disposable(run, tier):
    """CATCHES: explicit resource management bugs -- using/await using disposal order and timing, null/undefined resources, SuppressedError chaining, non-disposable TypeErrors, DisposableStack/AsyncDisposableStack use/defer/adopt/move/dispose semantics."""
    r = run([*tier, "-e", PROG_USING])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "using_disposable")

PROG_LEXER = r"""#!/usr/bin/env lumen-cli this hashbang line is ignored
const out = (l, v) => console.log(l, typeof v === 'string' ? JSON.stringify(v) : String(v));
// numeric literals
out('separators', [1_000_000, 0xf_f, 0b1010_1010, 0o7_7, 1_0.5_5, 1e1_0].join());
out('bases', [0xFF, 0b11, 0o17, 017, 019, 08, 0.5e1, .5, 5., 0X1f, 0B1, 0O7].join());
out('bigint-lits', [0x1fn, 0b11n, 0o17n, 1_000n, 12345678901234567890n].join() + ' ' + typeof 0n);
out('number-member', [1..toString(), 1.5.toFixed(1), 1 .toString(), (1).constructor.name, 5e-7.toString()].join());
// string escapes
out('escapes', '\x41\u0042\u{43}\u{1F600}\t|\v|\0|\b|\f|\'|\"|\\|\
continued');
out('legacy-octal-escape', '\101\60\7'.split('').map((c) => c.charCodeAt(0)).join());
out('line-sep-in-string', '\u2028'.length + eval('"a\u2028b"').length);
// unicode identifiers
const \u0061bc = 'escaped ident';
const ünïcödé = 'unicode ident', $dollar = 1, _under = 2, ℮x = 3;
var \u{62}\u{63} = 'bc';
out('unicode-idents', [abc, ünïcödé, $dollar + _under + ℮x, bc].join());
const obj = { \u0069f: 'escaped keyword as prop', class: 'kw prop', new: 1 };
out('keyword-props', [obj.if, obj.class, obj.new, obj.\u0063lass].join());
// regex vs division ambiguity
const a = 10, b = 2, g = 5, i = 1;
out('division', a / b / g);
out('div-regex-like', a /b/ g);
const r1 = /[/]/.source, r2 = /a\/b/.source, r3 = /=/g.flags, r4 = /(?<y>\d{4})/.exec('in 2024').groups.y;
out('regex-literals', [r1, r2, r3, r4].join(' '));
const x = 1;
const t1 = x
/2/i;
out('asi-no-regex', t1);
const arr = [4];
out('regex-after-bracket', arr[0] /2/ 1);
out('regex-after-brace-stmt', eval('{}/foo/.source'));
out('regex-after-brace-expr', eval('({}) / 2'));
out('regex-after-return', (function () { return /ret/.source; })());
out('regex-after-typeof', typeof /x/);
out('regex-in-template', `${/a}b/.source}`);
out('division-assign', (() => { let d = 8; d /= 2; d /=2; return d; })());
out('regex-class-slash', /[\]/]+/.exec('a]/]b')[0]);
// increments and ASI
let p = 1, q = 2;
p
++q
out('asi-prefix-incr', p + ',' + q);
const hz = function () { return 'hazard-called:' + typeof arguments[0] }
const res = hz
(function () { return 'iife' })
out('asi-no-insert-before-paren', res);
const hz2 = [1, 2]
const res2 = hz2
[0, 1]
out('asi-no-insert-before-bracket', res2);
function retAsi() {
  return
  'never';
}
out('return-asi', retAsi());
let counter = 0
;[1, 2].forEach(() => counter++)
out('leading-semicolon', counter);
const tpl = 'x'
out('no-asi-in-ternary', true
  ? 'yes'
  : 'no');
let y = 5
y
--
y
out('asi-postfix', y);
// HTML-like comments (script only)
<!-- this is a comment
out('html-open-comment', 'ok');
--> this is also a comment at line start
/* multi
line */ --> also a comment after multiline comment
out('html-close-comment', 'ok');
out('html-in-expr', eval('1 <!-- 2\n'));
out('arrow-ops', eval('let z = 3; z-->0') + ',' + eval('let w = 2; w --> 1 ? "gt" : "le"'));
// template literals
const name = 'W';
out('template', `a${1 + 1}b${name}${`nested ${name}`}\${escaped}\n${''}`);
out('template-multiline', `l1
l2\
l3`);
out('template-crlf', eval('`a\r\nb\rc`').split('').map((ch) => ch.charCodeAt(0)).join());
function tag(strs, ...vals) { return JSON.stringify({ cooked: strs, raw: strs.raw, vals, frozen: Object.isFrozen(strs) }); }
out('tagged', tag`x${1}y\n${2}\u0041`);
out('tagged-invalid-escape', tag`\unicode and \xZ and \01`);
out('string-raw', String.raw`C:\new\table${1 + 1}\u` + '|' + String.raw({ raw: ['a', 'b', 'c'] }, 1, 2, 3, 4) + '|' + String.raw({ raw: { length: 2, 0: 'p', 1: 'q' } }, '-', '+'));
const sites = [];
function capture(s) { sites.push(s); return s; }
for (let k = 0; k < 2; k++) capture`same site ${k}`;
capture`same site ${0}`;
out('template-identity', [sites[0] === sites[1], sites[0] === sites[2]].join());
out('tag-member-call', (function () { const o = { t(s, v) { return this.n + s[0] + v; }, n: 'N' }; return o.t`pre${'V'}`; })());
out('tag-chain', ((s) => (s2) => s[0] + s2[0])`first``second`);
// comments in odd places
out('comments', 1 /* inline */ + /* another */ 2 // trailing
);
out('comment-asi', (function () { return /*
  */ 'after multiline comment with newline'; })());
// template substitutions containing comments, strings, regexes, braces and nested templates
const tn = 'N';
out('nested-templates', `L1 ${`L2 ${`L3 ${tn}`} back2`} back1`);
out('substitution-lexing', `${ /* comment with } and ` inside */ 'c1' }|${ 'str with } and `' }|${ "dq }" }|${ // line comment }
'lc' }|${ /}`/.source }|${ { a: { b: '}' } }.a.b }|${ ((x) => { return x + '}'; })('fn') }`);
out('substitution-division', `${ 10 / 2 / 1 }|${ [4][0] / 2 }|${ `\`` }|${ '\'' }`);
out('substitution-raw', ((s) => s.raw.join('#'))`\u{110000}${1}\x4${2}\08${3}\9`);
out('substitution-cooked', ((s) => s.map(String).join('#'))`\u{110000}${1}ok${2}\u{}`);
out('template-escapes', `\0|\u{41}|\x42|C`.split('').map((c) => c.charCodeAt(0)).join());
out('hashbang-in-eval', eval('#! hashbang comment allowed at the start of eval code\n42'));
for (const src of ['`${ /* never closed', '`${ `never closed', '`${ /never closed', '`${ "never closed', '`${ 1 ', '`${ 1 }', '`\\u{110000}`', '`\\u{}`', '`\\x4`', '`\\08`',
  '"\\u{41"', '"\\u{zz}"', '"line\nbreak"', '01_0', '/re\ngex/', '/re\\\ngex/', '/unterminated\\', 'Function("#!x\\nreturn 1")', 'var \\u0030x']) {
  try { eval(src); out('lex-error ' + JSON.stringify(src), 'no error'); } catch (e) { out('lex-error ' + JSON.stringify(src), e.name + ': ' + e.message); }
}
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_lexer_asi_templates(run, workdir, tier):
    """CATCHES: lexer/parser bugs -- hashbang and HTML-like comments in scripts, numeric separators/legacy octal/BigInt literals, string escapes, Unicode-escaped identifiers and keyword property names, regex-vs-division decisions, ASI hazards (return, ++, leading paren/bracket), template literal cooking, tagged templates (raw strings, invalid escapes, call-site identity) and String.raw."""
    write_files(workdir, {"prog.js": PROG_LEXER.encode()})
    r = run([*tier, "prog.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "lexer_asi_templates")

PROG_SLOPPY = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// identifiers that are only reserved in strict mode / special contexts
var let_ = 1;
show('let-as-ident', () => eval('var let = 5; let'));
show('yield-as-ident', () => eval('var yield = 6; yield'));
show('await-as-ident', () => eval('var await = 7; await'));
show('static-implements', () => eval('var static = 1, implements = 2, package = 3, interface = 4; static + implements + package + interface'));
show('async-as-ident', () => eval('var async = (x) => x * 3; async(3)'));
show('of-get-set-as-ident', () => eval('var of = 1, get = 2, set = 3, target = 4; of + get + set + target'));
show('let-asi', () => eval('var let = [10]; let\n[0]'));
show('let-member', () => eval('var let = { x: 11 }; let.x'));
show('eval-arguments-names', () => eval('var eval_ = 1; (function (eval) { return typeof eval; })(5)'));
// sloppy silent failures vs strict TypeErrors
const frozen = Object.freeze({ a: 1 });
show('sloppy-frozen-write', () => { frozen.a = 2; return frozen.a; });
show('strict-frozen-write', () => { 'use strict'; frozen.a = 2; });
show('sloppy-delete-nonconfig', () => delete Object.prototype);
show('sloppy-delete-var', () => eval('var dv = 1; delete dv'));
show('sloppy-delete-eval-var', () => { eval('var ev = 1'); return [delete ev, typeof ev].join(); });
show('sloppy-primitive-prop', () => { const s = 'str'; s.prop = 1; return s.prop; });
show('strict-primitive-prop', () => { 'use strict'; const s = 'str'; s.prop = 1; });
show('sloppy-getter-only', () => { const o = { get g() { return 1; } }; o.g = 5; return o.g; });
show('sloppy-nonextensible', () => { const o = Object.preventExtensions({}); o.x = 1; return o.x; });
show('sloppy-readonly-length', () => { const f = function (a, b) {}; f.length = 10; return f.length; });
show('strict-readonly-length', () => { 'use strict'; const f = function (a, b) {}; f.length = 10; });
show('sloppy-implicit-global', () => { (function () { implicitG = 'made'; })(); return globalThis.implicitG + ':' + delete globalThis.implicitG; });
// this boxing
show('this-boxing', () => [typeof function () { return this; }.call('s'), typeof function () { 'use strict'; return this; }.call('s'), (function () { return this; }).call(undefined) === globalThis, (function () { 'use strict'; return this; }).call(undefined)].join());
show('this-in-getter-on-primitive', () => { Object.defineProperty(Number.prototype, 'selfType', { get() { return typeof this; }, configurable: true }); Object.defineProperty(Number.prototype, 'selfTypeStrict', { get() { 'use strict'; return typeof this; }, configurable: true }); return (5).selfType + ',' + (5).selfTypeStrict; });
// arguments.callee / caller restrictions
show('fn-caller-strict', () => { 'use strict'; function f() {} return f.caller; });
show('fn-arguments-prop-strict', () => { function f() { 'use strict'; } return f.arguments; });
show('fn-caller-sloppy-type', () => { function f() { return typeof f.caller; } return f(); });
show('restricted-props-on-proto', () => { const d = Object.getOwnPropertyDescriptor(Function.prototype, 'caller'); return [typeof d.get, d.get === d.set, Object.hasOwn(function () {}, 'caller'), Object.hasOwn(function () { 'use strict'; }, 'caller')].join(); });
// Annex B: function in block semantics
show('annexb-before-block', () => { const before = typeof inner; { function inner() {} } return before + ',' + typeof inner; });
show('annexb-if', () => { if (true) function viaIf() { return 'if-fn'; } return viaIf(); });
show('annexb-no-hoist-over-let', () => { let blocked = 'let'; { function blocked() {} } return typeof blocked; });
show('annexb-for-in-init', () => eval('var r = []; for (var k = "init" in {}) {} k'));
show('annexb-html-comment', () => eval('var hc = 1; hc <!-- ignored\n + 1'));
show('annexb-escape', () => [escape('a b+é'), unescape('%u0041%41')].join());
show('annexb-legacy-regexp', () => [/\1(a)/.exec('a')?.[0], /[\d-z]/.test('-'), /a{/.test('a{'), /\c/.test('\\c'), /]/.test(']')].join());
show('annexb-defineGetter', () => { const o = {}; o.__defineGetter__('dg', () => 'dg-val'); return [o.dg, typeof o.__lookupGetter__('dg'), Object.prototype.__lookupSetter__.call(o, 'dg')].join(); });
show('annexb-string-html', () => ['x'.anchor('a"b'), 'y'.bold(), 'z'.substr(-2, 1)].join());
show('annexb-date-getYear', () => new Date(Date.UTC(1999, 0, 1)).getYear());
// strictness scoping
show('strict-function-in-sloppy', () => { function s() { 'use strict'; return (function () { return this; })(); } return String(s()); });
show('class-body-strict', () => { class C { m() { return (function () { return this; })(); } } return String(new C().m()); });
show('directive-after-statement', () => { function f() { 1; 'use strict'; return this === undefined; } return f(); });
show('directive-escaped', () => { function f() { 'use\x20strict'; return this === undefined; } return f(); });
show('directive-not-first-string', () => { function f() { 'a'; 'use strict'; return this === undefined; } return f(); });
show('eval-in-strict-fn', () => { 'use strict'; eval('var leaked2 = 1'); return typeof leaked2; });
show('strict-arguments-assign', () => { 'use strict'; return (function (a) { a = 2; return arguments[0]; })(1); });
show('sloppy-octal-escape', () => '\08'.length + ':' + '\8'.charCodeAt(0));
// labelled continue in nested loops, label on block with function
show('labels', () => { const r = []; a: for (const i of [1, 2, 3]) { b: { if (i === 2) break b; r.push('b' + i); } c: do { if (i === 3) continue a; r.push('c' + i); } while (false); } return r.join(); });
// object spread / literal semantics
show('object-spread', () => { let calls = 0; const src = { get g() { calls++; return 'g'; }, a: 1 }; const o = { a: 0, ...src, ...null, ...undefined, ...'hi', ...[9], b: 2 }; return JSON.stringify(o) + ' calls=' + calls; });
show('object-dup-keys', () => JSON.stringify({ a: 1, b: 2, a: 3, get c() { return 'get'; }, c: 'data' }));
show('object-numeric-keys', () => JSON.stringify(Object.keys({ 1e3: 'a', 0x10: 'b', 1.50: 'c', '01': 'd', [-0]: 'e' })));
show('spread-holes', () => { const a = [1, , 3]; return [JSON.stringify([...a]), [...a].hasOwnProperty(1), a.hasOwnProperty(1), Math.max(...[1, 5], ...new Set([7]))].join(' '); });
show('new-spread', () => { function P(...args) { this.args = args; } return new P(...'ab', ...[1]).args.join(); });
// delete semantics
show('delete-optional-null', () => { const n = null; const o = { a: { b: 1 } }; return [delete n?.x, delete n?.['k'], delete n?.x.y.z, delete o?.a.b, JSON.stringify(o), delete o.a?.['missing']].join(); });
show('delete-string-props', () => { const s = 'abc'; return [delete s.length, delete s[1], delete s[5], delete s.foo, delete 'xyz'['0'], delete 'xyz'['01']].join(); });
show('delete-string-strict', () => { 'use strict'; const s = 'abc'; delete s[0]; });
show('delete-array-length', () => { const a = [1, 2]; return [delete a.length, a.length].join(); });
show('delete-with-binding', () => { const o = { wb: 1 }; Object.defineProperty(o, 'fixed', { value: 2, configurable: false }); with (o) { return [delete wb, 'wb' in o, delete fixed, 'fixed' in o].join(); } });
show('delete-with-inherited', () => { const o = Object.create({ inh: 1 }); with (o) { return [delete inh, 'inh' in o].join(); } });
show('delete-global-property', () => { globalThis.deletableProp = 1; return [delete globalThis.deletableProp, typeof deletableProp].join(); });
show('delete-function-name-length', () => { function f(a) {} return [delete f.name, delete f.length, f.name, f.length, delete f.prototype].join(); });
show('delete-returns-true-for-nonref', () => [delete 0, delete 'str', delete (() => 1)(), delete [].nope].join());
show('delete-super-strict', () => { class D { m() { 'use strict'; return delete super.x; } } return new D().m(); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_strict_sloppy_annexb(run, tier):
    """CATCHES: strict-vs-sloppy differences done wrong -- contextual keywords usable as identifiers, `let [` lookahead, silent sloppy write failures vs strict TypeErrors, this boxing, restricted caller/arguments properties, Annex B block functions/for-in initialisers/legacy regexp/escape/__defineGetter__/HTML string methods, directive prologue detection, object spread and literal key ordering."""
    r = run([*tier, "-e", PROG_SLOPPY])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "strict_sloppy_annexb")

PROG_DECORATORS = r"""const log = [];
function logged(value, context) {
  log.push(`decorate ${context.kind} ${String(context.name)} static=${context.static} private=${context.private}`);
  if (context.kind === 'method') {
    return function (...args) { log.push(`call ${String(context.name)}(${args.join(',')})`); return value.apply(this, args); };
  }
  if (context.kind === 'field') {
    return (init) => { log.push(`init field ${String(context.name)} = ${init}`); return init * 10; };
  }
  if (context.kind === 'class') {
    context.addInitializer(function () { log.push('class initializer for ' + this.name); });
    return class extends value { static decorated = true; };
  }
  if (context.kind === 'getter' || context.kind === 'setter') {
    return function (...a) { log.push(context.kind + ' ' + String(context.name)); return value.apply(this, a); };
  }
  if (context.kind === 'accessor') {
    return { get() { const v = value.get.call(this); log.push('accessor get ' + String(context.name) + '=' + v); return v; }, set(v) { log.push('accessor set ' + v); value.set.call(this, v); }, init(v) { log.push('accessor init ' + v); return v + 1; } };
  }
}
function tagged(tag) { return (value, context) => { log.push('tag ' + tag + ' on ' + String(context.name)); }; }
@logged
class Widget {
  @logged @tagged('outer') count = 4;
  @logged static sfield = 2;
  @logged accessor size = 7;
  @logged #secret = 3;
  @logged greet(name) { return 'hi ' + name + ' #' + this.#secret; }
  @logged static make() { return new this(); }
  @logged get label() { return 'L' + this.count; }
  @logged set label(v) { this._label = v; }
  @logged #hidden() { return 'hidden'; }
  callHidden() { return this.#hidden(); }
}
log.push('--- class defined');
const w = Widget.make();
log.push('greet -> ' + w.greet('bob'));
log.push('count -> ' + w.count + ', sfield -> ' + Widget.sfield + ', decorated -> ' + Widget.decorated);
log.push('size -> ' + w.size);
w.size = 20;
log.push('size after set -> ' + w.size);
log.push('label -> ' + w.label);
w.label = 'x';
log.push('hidden -> ' + w.callHidden());
console.log(log.join('\n'));
// errors
for (const src of ['@5 class A {}', 'class B { @((v, c) => 42) m() {} }', 'class C { @((v, c) => { c.addInitializer(5); }) m() {} }']) {
  try { eval(src); console.log('no error'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
// auto-accessor without decorators, static accessor, private accessor
class Auto { accessor a = 1; static accessor s = 'S'; accessor #p = 'P'; getP() { return this.#p; } setP(v) { this.#p = v; } }
const au = new Auto();
au.a = 5; au.setP('Q');
console.log('auto-accessor', au.a, Auto.s, au.getP(), Object.getOwnPropertyNames(Auto.prototype).join(), typeof Object.getOwnPropertyDescriptor(Auto.prototype, 'a').get, Object.keys(au).length);
debugger;
console.log('after debugger statement');
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_decorators_auto_accessors(run, tier):
    """CATCHES: missing or misordered decorator evaluation (element vs class decorators, right-to-left application, field initializer transforms, accessor get/set/init wrappers, addInitializer), the decorator TypeError/SyntaxError messages, and auto-accessor (`accessor` keyword) storage semantics."""
    r = run([*tier, "-e", PROG_DECORATORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "decorators_auto_accessors")

PROG_COROUTINES = r"""// many simultaneously-suspended generators
function* counter(id) { let n = 0; while (true) { const cmd = yield id * 1000 + n++; if (cmd === 'stop') return 'stopped ' + id; } }
const gens = Array.from({ length: 300 }, (_, i) => counter(i));
let sum = 0;
for (let round = 0; round < 3; round++) for (const g of gens) sum += g.next().value;
console.log('300 live generators sum', sum);
console.log('stop some', gens[0].next('stop').value, gens[299].next('stop').value, JSON.stringify(gens[299].next()));
// abandoned generators with pending finally blocks never run them
function* withFinally() { try { yield 1; yield 2; } finally { console.log('THIS SHOULD NOT PRINT'); } }
const abandoned = []; for (let i = 0; i < 50; i++) { const g = withFinally(); g.next(); abandoned.push(g); }
// nested generators: generator that drives another generator inside its body
function* outerDriver() { const inner = counter(7); for (let i = 0; i < 3; i++) yield 'outer sees ' + inner.next().value; }
console.log([...outerDriver()].join(' | '));
// recursion inside a generator body
function* recursive(n) { if (n > 0) yield* recursive(n - 1); yield n; }
console.log('recursive yield*', [...recursive(50)].length);
// many concurrent async functions awaiting the same promise
let release;
const gate = new Promise((r) => { release = r; });
const results = [];
const tasks = Array.from({ length: 200 }, (_, i) => (async () => { const v = await gate; results.push(i); return v + i; })());
console.log('tasks pending', results.length);
release(1000);
Promise.all(tasks).then((vals) => {
  console.log('tasks done', results.length, results.slice(0, 5).join(), vals.reduce((a, b) => a + b, 0));
  // async recursion
  const asum = async (n) => (n === 0 ? 0 : n + (await asum(n - 1)));
  return asum(100);
}).then((v) => console.log('async recursion', v));
// generator thrown from within its own body during next() of another generator
function* thrower() { yield 1; throw new Error('inner gen error'); }
function* wrapper() { try { yield* thrower(); } catch (e) { yield 'wrapped: ' + e.message; } }
console.log([...wrapper()].join(' / '));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_coroutines_many_live(run, tier):
    """CATCHES: coroutine/generator machinery that cannot keep hundreds of generators or async functions suspended at once, runs finally blocks of abandoned generators at exit, mishandles nested generator driving, recursive yield*, or errors escaping a delegated generator."""
    r = run([*tier, "-e", PROG_COROUTINES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "coroutines_many_live")

PROG_ORDER = r"""const trace = [];
const t = (label, v) => (trace.push(label), v);
const dump = (label) => { console.log(label.padEnd(24), trace.join(' ')); trace.length = 0; };
// binary operands left to right, including ToPrimitive timing
const L = { valueOf() { trace.push('L.valueOf'); return 1; } }, R = { valueOf() { trace.push('R.valueOf'); return 2; } };
t('a', L) + t('b', R); dump('binary +');
t('a', L) < t('b', R); dump('less-than');
t('a', L) > t('b', R); dump('greater-than (no swap)');
t('a', 2) ** t('b', 3) ** t('c', 2); dump('exponent');
// assignment target evaluated before RHS
const obj = {};
let i = 0;
const arr = [];
arr[t('index', i++)] = t('rhs', i); dump('member assign');
console.log('  arr', JSON.stringify(arr));
t('objexpr', obj)[t('key', 'k')] = t('value', 1); dump('computed assign');
// compound assignment reads target once
const counted = { _v: 1, get v() { trace.push('get v'); return this._v; }, set v(x) { trace.push('set v=' + x); this._v = x; } };
counted.v += t('rhs', 10); dump('compound +=');
counted.v ??= t('never', 0); dump('??= no set');
counted.v++; dump('postfix ++');
// call: callee, this, args left to right; args evaluated before checking callability
try { t('callee', undefined)(t('arg1', 1), t('arg2', 2)); } catch (e) { trace.push(e.constructor.name); } dump('call non-fn');
const o2 = { get m() { trace.push('get m'); return (...a) => trace.push('call m ' + a.join()); } };
o2.m(t('x', 'x'), t('y', 'y')); dump('method call');
// new: callee then args
function C(a) { trace.push('C body ' + a); }
new (t('ctor', C))(t('arg', 'A')); dump('new');
// object literal key/value order and computed keys
const lit = { [t('k1', 'a')]: t('v1', 1), b: t('v2', 2), [t('k3', 'c')]: t('v3', 3), ...t('spread', { d: 4 }) }; dump('object literal');
console.log('  keys', Object.keys(lit).join());
// array literal & spread order
[t('e0', 0), ...t('spreadsrc', [1, 2]), t('e3', 3)]; dump('array literal');
// template literal order and ToString timing
const ts = { toString() { trace.push('ts.toString'); return 'T'; } };
`${t('first', ts)}-${t('second', 2)}`; dump('template');
// conditional/logical short circuit
t('cond', false) ? t('yes', 1) : t('no', 2); dump('conditional');
t('l', 0) && t('r', 1); dump('&& short');
t('l', 1) || t('r', 1); dump('|| short');
t('l', null) ?? t('r', 1); dump('?? evaluates right');
// destructuring assignment order: getter, default, target
const src = { get a() { trace.push('get a'); return undefined; }, get b() { trace.push('get b'); return 'B'; } };
const tgt = {};
({ a: tgt[t('ta', 'x')] = t('default a', 'A'), b: tgt[t('tb', 'y')] } = src); dump('destructure assign');
console.log('  tgt', JSON.stringify(tgt));
// property key ToPropertyKey timing
const keyObj = { toString() { trace.push('key.toString'); return 'kk'; } };
const holder = {};
holder[t('keyexpr', keyObj)] = t('val', 1); dump('ToPropertyKey');
// in / instanceof / typeof order
t('lhs', 'x') in t('rhs', {}); dump('in');
// comma, void, delete
(t('c1', 1), t('c2', 2)); void t('void', 0); delete t('delobj', {})[t('delkey', 'k')]; dump('comma/void/delete');
// class element evaluation order (computed keys at definition time, fields at construction)
class K {
  [t('key m', 'm')]() {}
  static [t('key s', 's')] = t('static init', 1);
  [t('key f', 'f')] = t('field init', 2);
  static { trace.push('static block'); }
}
dump('class definition');
new K(); dump('class construction');
// switch: discriminant once, cases in order until match
switch (t('disc', 2)) { case t('case1', 1): break; case t('case2', 2): trace.push('body2'); case t('case3', 3): trace.push('body3 (fallthrough)'); } dump('switch');
// for loop parts
for (let j = t('init', 0); t('test' + j, j < 2); t('update' + j, j++)) trace.push('body' + j); dump('for loop');
// for-in: object evaluated once, keys snapshot
const fi = { a: 1, b: 2 };
for (const k in t('forin obj', fi)) { trace.push('key ' + k); if (k === 'a') fi.c = 3; } dump('for-in adds key');
// argument defaults evaluated left-to-right at call time
function defs(a = t('def a', 1), b = t('def b', a + 1)) { return a + b; }
defs(); defs(5); dump('param defaults');
// tagged template: tag, then substitutions
const tagFn = (s, ...v) => trace.push('tag called with ' + v.join());
t('tag', tagFn)`x${t('sub1', 1)}y${t('sub2', 2)}`; dump('tagged template');
// optional chaining with side effects
const oc = { a: null, b: { c: () => 'called' } };
oc.a?.[t('never', 'x')]; oc.b?.c?.(t('arg', 1)); dump('optional chain');
// exceptions in middle of evaluation abort the rest
try { [t('before', 1), (() => { throw new Error('mid'); })(), t('after', 3)]; } catch (e) { trace.push('caught ' + e.message); } dump('abrupt middle');
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_evaluation_order(run, tier):
    """CATCHES: engines that evaluate operands, assignment targets, call arguments, object/array/class element keys, template substitutions, destructuring targets/defaults, switch cases, loop clauses, parameter defaults or tagged-template parts in a different order than the spec (or call ToPrimitive/ToString/getters at the wrong time)."""
    r = run([*tier, "-e", PROG_ORDER])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "evaluation_order")

PROG_ITERATION = r"""const log = (...a) => console.log(...a);
// string iteration by code points
log('string-iter', [...'a😀b'].length, 'a😀b'.length, Array.from('é😀').map((c) => c.codePointAt(0).toString(16)).join());
// lone surrogates
log('lone-surrogate', [...'\uD800x'].length, JSON.stringify('\uD800'));
// Map/Set live iteration: entries added during iteration are visited, deleted ones skipped
const m = new Map([[1, 'a'], [2, 'b'], [3, 'c']]);
const seen = [];
for (const [k, v] of m) { seen.push(k + v); if (k === 1) { m.delete(2); m.set(4, 'd'); } }
log('map-live', seen.join());
const s = new Set([1, 2]);
const sseen = [];
for (const v of s) { sseen.push(v); if (v < 5) s.add(v + 2); }
log('set-live', sseen.join());
// array iteration is live w.r.t. length
const a = [1, 2, 3];
const aseen = [];
for (const v of a) { aseen.push(v); if (v === 1) a.push(4); if (v === 2) a.length = 3; }
log('array-live', aseen.join());
// holes become undefined in for-of, skipped in forEach
const holes = [1, , 3];
const hseen = []; for (const v of holes) hseen.push(String(v));
const fseen = []; holes.forEach((v) => fseen.push(v));
log('holes', hseen.join(), fseen.join(), Object.keys(holes).join(), 1 in holes);
// array length semantics
const arr = [1, 2, 3, 4, 5];
arr.length = 2;
log('length-truncate', JSON.stringify(arr), arr[3]);
arr[9] = 'x';
log('length-extend', arr.length, JSON.stringify(arr));
const big = []; big[4294967294] = 'max'; big[4294967295] = 'not-index';
log('max-index', big.length, Object.keys(big).join());
try { big.push(1, 2); } catch (e) { log('push-overflow', e.name + ': ' + e.message); }
// arguments object is iterable and array-like
(function () { log('arguments-iter', [...arguments].join(), Array.prototype.slice.call(arguments, 1).join(), arguments.length); })(1, 2, 3);
// iterator protocol: next called with no args by for-of, value getter only read when not done
const prot = { [Symbol.iterator]() { let n = 0; return { next(...args) { log('  next args', args.length); n++; return { get done() { log('  done read'); return n > 2; }, get value() { log('  value read'); return n; } }; } }; } };
for (const v of prot) log('  body', v);
// iterator closed when destructuring throws in default
const closer = { [Symbol.iterator]() { return { next: () => ({ value: undefined, done: false }), return() { log('  closed by throw in default'); return {}; } }; } };
try { const [x = (() => { throw new Error('default threw'); })()] = closer; } catch (e) { log('destructure-throw', e.message); }
// iterator return() result must be an object when closing
const badReturn = { [Symbol.iterator]() { return { next: () => ({ value: 1, done: false }), return: () => 5 }; } };
try { for (const v of badReturn) break; } catch (e) { log('bad-return', e.name + ': ' + e.message); }
// if body throws, a bad return() is ignored and the body error wins
try { for (const v of badReturn) throw new Error('body error wins'); } catch (e) { log('throw-wins', e.message); }
// return() not called when iterator completes normally or when next throws
const nextThrows = { [Symbol.iterator]() { return { next() { throw new Error('next threw'); }, return() { log('  SHOULD NOT CLOSE'); return {}; } }; } };
try { for (const v of nextThrows); } catch (e) { log('next-throws', e.message); }
// Array.from with iterable vs array-like, map fn with index
log('array-from', Array.from({ length: 3, 0: 'a', 2: 'c' }).join('|'), Array.from(new Set(['x', 'y']), (v, i) => v + i).join(), Array.from(new Map([[1, 2]])).join(';'));
// spread into calls with many arguments
log('spread-many', Math.max(...Array.from({ length: 5000 }, (_, i) => i)));
// entries/keys/values iterators
log('array-iters', [...['a', 'b'].entries()].join(';'), [...['a', 'b'].keys()].join(), Object.prototype.toString.call([].values()), typeof [][Symbol.iterator]().next);
// generator return value not included in spread / for-of
function* withReturn() { yield 1; return 2; }
log('return-not-spread', [...withReturn()].join(), Array.from(withReturn()).length);
// Iterator helpers and Iterator.from
const it = Iterator.from({ next() { return { value: 1, done: false }; } });
log('iterator-from', it.take(3).toArray().join(), typeof Iterator.prototype.map, [1, 2, 3].values().reduce((x, y) => x + y), [1, 2, 3, 4].values().drop(1).filter((x) => x % 2 === 0).toArray().join());
log('flatMap', [1, 2].values().flatMap((x) => [x, x * 10]).toArray().join(), [5, 6].values().some((x) => x > 5), [5, 6].values().every((x) => x > 5), [5, 6].values().find((x) => x > 5));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_iteration_protocol(run, tier):
    """CATCHES: iteration bugs -- code-point string iteration, live Map/Set/Array iteration, holes, array length truncation/extension and index limits, the exact next/done/value access sequence, iterator closing rules (throw in default, bad return() result, body error precedence, no close when next throws), Array.from, and iterator helpers."""
    r = run([*tier, "-e", PROG_ITERATION])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "iteration_protocol")

PROG_SUPER = r"""const show = (label, f) => { try { console.log(label, f()); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
class A {
  constructor() { this.tag = 'A-ctor'; }
  who() { return 'A.who(' + this.tag + ')'; }
  static sw() { return 'A.sw(' + this.name + ')'; }
  get g() { return 'A.g(' + this.tag + ')'; }
  set s(v) { this._s = 'A.s:' + v; }
}
class B extends A {
  field = super.who();
  arrowField = () => super.who();
  constructor() { super(); this.tag = 'B-inst'; }
  who() { return 'B>' + super.who(); }
  static sw() { return 'B>' + super.sw(); }
  get g() { return 'B>' + super.g; }
  set s(v) { super.s = v + '!'; }
  assignSuper() { super.plain = 'assigned via super'; return Object.hasOwn(this, 'plain') + ':' + this.plain + ':' + ('plain' in A.prototype); }
  arrowSuper() { return [1].map(() => super.who())[0]; }
  evalSuper() { return eval('super.who()'); }
  deleteSuper() { delete super.who; }
  computedSuper(k) { return super[k](); }
  superIncr() { super.counter = 1; super.counter++; super.counter += 10; return this.counter; }
}
const b = new B();
show('method', () => b.who());
show('static', () => B.sw());
show('getter', () => b.g);
show('setter', () => { b.s = 'x'; return b._s; });
show('field-init-super', () => b.field);
show('arrow-field-super', () => b.arrowField());
show('assign-super', () => b.assignSuper());
show('arrow-super', () => b.arrowSuper());
show('eval-super', () => b.evalSuper());
show('delete-super', () => b.deleteSuper());
show('computed-super', () => b.computedSuper('who'));
show('super-incr', () => b.superIncr());
// home object is fixed at definition, not dynamic
const borrowed = B.prototype.who;
show('borrowed-method', () => borrowed.call({ tag: 'plain-obj' }));
const otherProto = { who() { return 'other'; } };
const lit = { who() { return 'lit>' + super.who(); } };
Object.setPrototypeOf(lit, otherProto);
show('object-super-dynamic-proto', () => lit.who());
Object.setPrototypeOf(lit, { who() { return 'swapped'; } });
show('object-super-after-swap', () => lit.who());
// changing the class prototype chain after definition
class C1 { m() { return 'C1'; } }
class C2 extends C1 { m() { return 'C2>' + super.m(); } }
Object.setPrototypeOf(C2.prototype, { m() { return 'replaced-parent'; } });
show('reparented', () => new C2().m());
// super constructor determined dynamically from [[GetPrototypeOf]] of the constructor
class P1 { constructor() { this.from = 'P1'; } }
class P2 { constructor() { this.from = 'P2'; } }
class Kid extends P1 {}
Object.setPrototypeOf(Kid, P2);
show('dynamic-super-ctor', () => new Kid().from + ' proto-still-P1=' + (Object.getPrototypeOf(Kid.prototype) === P1.prototype));
// super in static block and static field
class S extends A { static sf = super.sw(); static { this.sb = super.sw(); } }
show('static-field-super', () => S.sf + ' | ' + S.sb);
// super in getter defined on object literal with __proto__
const base = { get v() { return 'base-v:' + this.id; } };
const derived = { __proto__: base, id: 'D', get v() { return 'derived>' + super.v; } };
show('literal-getter-super', () => derived.v);
// super property on primitive this
show('super-this-primitive', () => { const o = { __proto__: { t() { return typeof this; } }, m() { 'use strict'; return super.t.call(5); } }; return o.m(); });
// default derived constructor forwards all args
class Args { constructor(...a) { this.args = a; } }
class Fwd extends Args {}
show('default-ctor-forwards', () => new Fwd(1, 2, 3).args.join());
// default derived constructor does not use Array.prototype[Symbol.iterator]
show('default-ctor-no-iter', () => { const saved = Array.prototype[Symbol.iterator]; Array.prototype[Symbol.iterator] = function () { throw new Error('iterated!'); }; try { return new Fwd('a', 'b').args.length; } finally { Array.prototype[Symbol.iterator] = saved; } });
// class with accessor pair split across static/instance
class Pair { static get x() { return 'static-x'; } get x() { return 'inst-x'; } static set x(v) { Pair._sx = v; } }
Pair.x = 9;
show('static-vs-instance', () => [Pair.x, new Pair().x, Pair._sx].join());
// getters/setters with Symbol keys and numeric keys in classes
const sym = Symbol('acc');
class Keys { get [sym]() { return 'sym-get'; } static get 0() { return 'zero'; } get 'str key'() { return 'str'; } }
show('accessor-keys', () => [new Keys()[sym], Keys[0], new Keys()['str key']].join());
// instanceof with Symbol.hasInstance inherited statically
class Base2 { static [Symbol.hasInstance](x) { return x === 'magic'; } }
class Derived2 extends Base2 {}
show('inherited-hasInstance', () => ['magic' instanceof Derived2, {} instanceof Derived2].join());
// class constructor .prototype non-writable; methods non-enumerable; class name property
show('class-props', () => { class Q { static m() {} } const d = Object.getOwnPropertyDescriptor(Q, 'prototype'); return [d.writable, d.enumerable, d.configurable, Object.getOwnPropertyDescriptor(Q, 'name').value, Object.keys(Q).length, typeof Q.m].join(); });
show('class-toString', () => { class T extends Object { m() { return 1; } } return T.toString(); });
// parenthesized optional chains as callees keep the receiver; short-circuit then call throws
const oc = { v: 'recv', m() { return this.v; } };
const nul = null;
show('paren-optional-callee', () => [(oc?.m)(), (oc.m)(), (oc?.['m'])()].join());
show('paren-optional-short', () => { let c = 0; try { (nul?.m)(c++); } catch (e) { return e.name + ': ' + e.message + ' args-evaluated=' + c; } });
// super with a null home-object prototype
show('super-computed-null-base', () => ({ __proto__: null, m() { return super['x']; } }).m());
show('super-set-null-base', () => { const r = { m() { super.y = 1; } }; Object.setPrototypeOf(r, null); r.m(); });
// legacy fn.arguments materialises the live arguments object of an active sloppy call
show('fn-arguments-legacy', () => { function legacy(a, b) { return legacy.arguments.length + ':' + legacy.arguments[1]; } return legacy('x', 'y', 'z'); });
show('fn-arguments-inactive', () => { function idle() {} return String(idle.arguments); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_super_and_home_objects(run, tier):
    """CATCHES: super property semantics done wrong -- super in methods/statics/getters/setters/field initialisers/arrows/eval, super assignment writing to this, super++ reading the parent, fixed [[HomeObject]] with dynamic prototype lookup, dynamic super constructor, default derived constructors, accessor/static pairs and class descriptor attributes."""
    r = run([*tier, "-e", PROG_SUPER])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "super_and_home_objects")

PROG_FUNCTION_PROTO = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// bind length/name edge cases
function three(a, b, c) { return [this?.id, a, b, c].join('/'); }
show('bind-basic', () => { const b = three.bind({ id: 'T' }, 1); return [b(2, 3), b.length, b.name].join(' '); });
show('bind-overbind', () => { const b = three.bind(null, 1, 2, 3, 4); return b.length; });
show('bind-of-bind', () => { const b = three.bind({ id: 'first' }, 'x').bind({ id: 'second' }, 'y'); return [b('z'), b.name, b.length].join(' '); });
show('bind-infinity-length', () => { const f = function () {}; Object.defineProperty(f, 'length', { value: Infinity }); return [f.bind().length, (Object.defineProperty(function () {}, 'length', { value: -Infinity })).bind().length, (Object.defineProperty(function () {}, 'length', { value: 2.7 })).bind().length, (Object.defineProperty(function () {}, 'length', { value: '3' })).bind().length].join(); });
show('bind-nonstring-name', () => { const f = function () {}; Object.defineProperty(f, 'name', { value: 42 }); return JSON.stringify(f.bind().name); });
show('bind-non-callable', () => Function.prototype.bind.call({}));
show('bind-new-ignores-this', () => { function P() { this.v = 'constructed'; } const B = P.bind({ v: 'ignored' }); const o = new B(); return o.v + ' ' + (o instanceof P) + ' ' + (o instanceof B) + ' ' + ('prototype' in B); });
show('bind-arrow-not-ctor', () => { const B = (() => {}).bind(); new B(); });
show('bind-class', () => { class K { constructor(a) { this.a = a; } } const BK = K.bind(null, 'bound-arg'); return new BK().a + ' ' + (() => { try { BK(); } catch (e) { return e.name; } })(); });
// call/apply edge cases
show('apply-arraylike', () => three.apply({ id: 'AL' }, { length: 2, 0: 'p', 1: 'q' }));
show('apply-null-args', () => three.apply({ id: 'N' }, null));
show('apply-bad-args', () => three.apply(null, 5));
show('apply-string-args', () => three.apply(null, 'str'));
show('call-non-function', () => Function.prototype.call.call(5));
show('apply-many', () => Math.max.apply(null, Array.from({ length: 10000 }, (_, i) => i)));
show('call-primitive-this', () => function () { 'use strict'; return typeof this; }.call(1n));
// toString variants
show('toString-native-getter', () => Object.getOwnPropertyDescriptor(Map.prototype, 'size').get.toString());
show('toString-symbol-method', () => ({ [Symbol.iterator]() {} })[Symbol.iterator].toString());
show('toString-native-symbol', () => Array.prototype[Symbol.iterator].toString());
show('toString-bound', () => three.bind().toString());
show('toString-proxy', () => new Proxy(function named() {}, {}).toString());
show('toString-non-fn', () => Function.prototype.toString.call({}));
show('toString-async-gen', () => (async function* ag(x) { yield x; }).toString());
show('toString-getter', () => Object.getOwnPropertyDescriptor({ get prop() { return 1; } }, 'prop').get.toString());
show('toString-class-static', () => (class { static m() { return 'S'; } }).m.toString());
show('toString-arrow-async', () => (async (a, b) => a + b).toString());
show('toString-computed-method', () => ({ ['comp' + 'uted'](a) { return a; } }).computed.toString());
// %ThrowTypeError% identity
show('throwTypeError', () => { const d1 = Object.getOwnPropertyDescriptor(Function.prototype, 'caller'); const d2 = Object.getOwnPropertyDescriptor(Function.prototype, 'arguments'); const strictArgs = (function () { 'use strict'; return arguments; })(); const d3 = Object.getOwnPropertyDescriptor(strictArgs, 'callee'); return [d1.get === d2.get, d1.get === d3.get, d1.get.length, JSON.stringify(d1.get.name), Object.isFrozen(d1.get)].join(); });
// Function.prototype itself
show('fp-itself', () => [typeof Function.prototype, Function.prototype(), Function.prototype.length, JSON.stringify(Function.prototype.name), Object.getPrototypeOf(Function.prototype) === Object.prototype].join());
show('fp-not-ctor', () => new Function.prototype());
// Function constructor details
show('fn-ctor-no-args', () => Function().toString());
show('fn-ctor-param-order', () => { const order = []; const p = (n) => ({ toString() { order.push(n); return n; } }); Function(p('a'), p('b'), p('return a + b')); return order.join(); });
show('fn-ctor-new-target-proto', () => { class MyFn extends Function {} const f = new MyFn('return 7'); return [f(), f instanceof MyFn, Object.getPrototypeOf(f) === MyFn.prototype].join(); });
show('gen-fn-ctor-proto', () => { const GF = Object.getPrototypeOf(function* () {}).constructor; return [GF.name, GF.length, Object.getPrototypeOf(GF) === Function, GF.prototype[Symbol.toStringTag], GF('yield 1')().next().value].join(); });
show('async-gen-fn-ctor', () => { const AGF = Object.getPrototypeOf(async function* () {}).constructor; return [AGF.name, typeof AGF('yield 1')()[Symbol.asyncIterator]].join(); });
show('fn-ctor-strict-body', () => Function('"use strict"; return this')());
show('fn-ctor-use-strict-dupe', () => Function('a', 'a', '"use strict";'));
show('fn-ctor-super', () => Function('super.x'));
show('fn-ctor-param-close', () => Function('a) { return 1; } (function (', ''));
// globals: parseInt / parseFloat / isNaN / isFinite / URI functions
show('parseInt', () => [parseInt('  42px'), parseInt('0x1F'), parseInt('0x1F', 16), parseInt('0x1F', 10), parseInt('-0'), parseInt('z', 36), parseInt('10', 37), parseInt('10', 1), parseInt('', 10), parseInt('1e3'), parseInt(0.0000005), parseInt('  -12abc', 8), parseInt('  7')].join());
show('parseFloat', () => [parseFloat('3.14abc'), parseFloat('.5'), parseFloat('-.5e-3x'), parseFloat('Infinityx'), parseFloat('-Infinity'), parseFloat('0x10'), parseFloat('1e'), parseFloat('e5'), parseFloat('  \n 12')].join());
show('Number.parse-same', () => Number.parseInt === parseInt && Number.parseFloat === parseFloat);
show('isNaN-isFinite', () => [isNaN('abc'), isNaN(''), isNaN(undefined), isFinite('12'), isFinite(null), isFinite(Infinity), Number.isNaN('abc'), Number.isFinite('12')].join());
show('isNaN-symbol', () => isNaN(Symbol()));
show('encodeURIComponent', () => encodeURIComponent('a b&c/d?é😀;,') + ' ' + encodeURI('http://x.y/a b?q=1&r=é#h'));
show('decodeURI', () => [decodeURIComponent('%E2%82%AC%20%2F'), decodeURI('%E2%82%AC%20%2F%23'), decodeURIComponent('%F0%9F%98%80')].join(' | '));
show('decode-malformed', () => decodeURIComponent('%E2%82'));
show('decode-bad-hex', () => decodeURIComponent('%zz'));
show('encode-lone-surrogate', () => encodeURIComponent('\uD800'));
show('escape-unescape', () => [escape('ä€ @*_+-./'), unescape('%E4%u20AC%zz%u12'), unescape('%')].join(' | '));
show('global-descriptors', () => ['parseInt', 'eval', 'globalThis', 'NaN'].map((k) => { const d = Object.getOwnPropertyDescriptor(globalThis, k); return k + ':' + [d.writable, d.enumerable, d.configurable].map(Number).join(''); }).join(' '));
show('eval-props', () => [eval.name, eval.length, typeof eval.prototype, (() => { try { new eval('1'); } catch (e) { return e.name; } })()].join());
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_function_proto_and_globals(run, tier):
    """CATCHES: Function.prototype.bind/call/apply edge cases (bound length/name/new, array-likes), Function.prototype.toString rendering for user, native, bound, proxy, accessor and computed functions, %ThrowTypeError% identity, dynamic Function/GeneratorFunction constructors, and global parseInt/parseFloat/isNaN/URI/escape functions and their errors."""
    r = run([*tier, "-e", PROG_FUNCTION_PROTO])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "function_proto_and_globals")

PROG_SCOPES = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
show('param-eval-var', () => (function (a = eval('var pv = "from-param-eval"; 1'), b = () => pv) { return b(); })());
show('param-eval-arguments', () => (function (a, b = eval('arguments.length')) { return b; })(1, undefined, 3));
show('var-redeclares-param', () => (function (p) { var p; return p; })('kept'));
show('var-init-param', () => (function (p) { var p = 'body'; return [p, arguments[0]].join(); })('arg'));
show('fn-decl-over-var', () => { var hv = 1; function hv() {} return typeof hv; });
show('fn-decl-hoist-before-var', () => { const r = typeof hv2; var hv2 = 1; function hv2() {} return r; });
show('arguments-shadow-param', () => (function (arguments) { return arguments; })('param-arguments'));
show('arguments-shadow-fn', () => (function () { function arguments() {} return typeof arguments; })());
show('arguments-var-no-shadow', () => (function () { var arguments; return typeof arguments; })(1));
show('named-fn-expr-shadowed-by-param', () => (function f(f) { return typeof f; })(1));
show('named-fn-expr-shadowed-by-var', () => (function g() { var g = 'var'; return g; })());
show('catch-param-closure', () => { const fns = []; for (const v of [1, 2]) { try { throw v; } catch (e) { fns.push(() => e); } } return fns.map((f) => f()).join(); });
show('catch-var-same-name', () => { try { throw 'thrown'; } catch (e) { var e = 'assigned in catch'; } return String(e); });
show('class-heritage-tdz', () => { class C extends (typeof C, Object) {} });
show('for-of-head-tdz', () => { let x = [1]; for (let x of x) {} });
show('for-in-head-tdz', () => { let y = {}; for (const y in y) {} });
show('for-let-closure-init', () => { const fs = []; for (let i = 0, f = () => i; i < 2; i++) fs.push(f); return fs.map((f) => f()).join(); });
show('block-shadow', () => { let s = 'outer'; { let s = 'inner'; } { const s = 'inner2'; } return s; });
show('switch-block-shared', () => { switch (2) { case 1: let sv = 'one'; case 2: sv = 'assigned'; return sv; } });
show('global-let-vs-var-eval', () => { (0, eval)('let globalLet1 = 1;'); (0, eval)('var globalLet1 = 2;'); });
show('global-let-not-on-globalThis', () => { (0, eval)('let globalLet2 = "lex";'); return [typeof globalThis.globalLet2, (0, eval)('globalLet2')].join(); });
show('global-let-shadows-property', () => { globalThis.shadowMe = 'prop'; (0, eval)('let shadowMe = "lexical";'); return [(0, eval)('shadowMe'), globalThis.shadowMe].join(); });
show('global-fn-redecl-nonconfig', () => { (0, eval)('function NaN() {}'); });
show('global-var-nonwritable', () => { (0, eval)('var Infinity = 5;'); return Infinity; });
show('implicit-global-in-with', () => { const o = {}; with (o) { implicitInWith = 1; } return [typeof o.implicitInWith, typeof globalThis.implicitInWith].join(); });
show('with-closure', () => { const o = { v: 'first' }; let f; with (o) { f = () => v; } o.v = 'second'; return f(); });
show('with-deleted-binding', () => { const o = { w: 'w' }; with (o) { delete o.w; return typeof w; } });
show('with-let-in-block', () => { const o = { lv: 'obj' }; with (o) { let lv = 'block'; return lv; } });
show('with-var-init', () => { const o = { wv: 'obj' }; with (o) { var wv = 'assigned-to-obj'; } return [o.wv, typeof wv].join(); });
show('eval-var-in-block-fn', () => { function f() { { eval('var bev = 1'); } return typeof bev; } return f(); });
show('eval-function-in-block', () => { function f() { eval('{ function ebf() { return "ebf"; } }'); return typeof ebf; } return f(); });
show('closure-counter-shared', () => { const make = () => { let n = 0; return [() => ++n, () => n]; }; const [inc, get] = make(); inc(); inc(); return get(); });
show('iife-loop-capture', () => { var fs = []; for (var i = 0; i < 3; i++) (function (j) { fs.push(() => j); })(i); return fs.map((f) => f()).join(); });
show('let-in-loop-body-closure', () => { const fs = []; let k = 0; while (k < 3) { let captured = k; fs.push(() => captured); k++; } return fs.map((f) => f()).join(); });
show('delete-binding', () => { var dv = 1; return [delete dv, typeof dv].join(); });
show('typeof-undeclared-member', () => { try { return typeof undeclaredThing.prop; } catch (e) { return e.name; } });
show('const-object-mutable', () => { const co = { a: 1 }; co.a = 2; return co.a; });
show('generator-arguments', () => { function* g() { yield arguments.length; yield arguments[1]; } return [...g('a', 'b')].join(); });
show('arrow-new-target', () => { function F() { return (() => new.target)(); } return [new F() === undefined, F() === undefined, typeof new F()].join(); });
show('arrow-this-in-class-field', () => { class W { name = 'W'; getName = () => this.name; } const { getName } = new W(); return getName(); });
show('nested-class-private-shadow', () => { class Outer { #x = 'outer'; static make() { return class Inner { #x = 'inner'; read(o) { return o.#x; } }; } } const I = Outer.make(); try { return new I().read(new Outer()); } catch (e) { return e.name + ': ' + e.message; } });
show('private-static-subclass', () => { class SP { static #p = 1; static read() { return this.#p; } } class SubSP extends SP {} return SubSP.read(); });
show('private-in-proxy', () => { class PP { #q; static has(o) { return #q in o; } } return [PP.has(new PP()), PP.has(new Proxy(new PP(), {}))].join(); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_scopes_and_bindings(run, tier):
    """CATCHES: scope-analysis bugs -- eval in parameter defaults, var/param/function/arguments shadowing, named function-expression bindings, catch-parameter Annex B var, heritage and for-in/of head TDZ, for-let initialiser closures, indirect-eval lexical isolation, global declaration errors, with-statement var/let/closure resolution, and private-name shadowing in nested classes."""
    r = run([*tier, "-e", PROG_SCOPES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "scopes_and_bindings")

PROG_LOOP_HEADS = r"""const out = [];
const o = {};
for (o.prop of ['m1', 'm2']) out.push('member-of:' + o.prop);
for (o['k' + 1] in { a: 1, b: 2 }) out.push('member-in:' + o.k1);
let a, b;
for ([a, b = 'def'] of [[1], [2, 3]]) out.push('pattern-of:' + a + b);
for ({ x: a, ...b } of [{ x: 'X', y: 'Y' }]) out.push('obj-pattern-of:' + a + JSON.stringify(b));
for (var [va] in { ab: 1 }) out.push('var-pattern-in:' + va);
for (const [k, v] of Object.entries({ p: 1, q: 2 })) out.push('entries:' + k + v);
for (let { length } of ['abc', 'de']) out.push('let-pattern:' + length);
let n = 0;
for (;;) { if (++n > 2) break; out.push('infinite-for:' + n); }
for (var i = 0, j = 10; i < j; i += 4, j -= 4) out.push('two-vars:' + i + '-' + j);
for (let x = 0; x < 2; x++) { setTimeout(() => {}, 0); }
const arr = [1, 2, 3];
for (const idx in arr) out.push('array-for-in:' + idx + typeof idx);
Array.prototype.extraEnumerable = 'bad';
for (const idx in [7]) out.push('proto-enum:' + idx);
delete Array.prototype.extraEnumerable;
const sparse = []; sparse[5] = 'five'; sparse[1] = 'one';
for (const idx in sparse) out.push('sparse-in:' + idx);
for (const ch of 'hi') out.push('str-of:' + ch);
const typed = new Uint8Array([9, 8]);
for (const t of typed) out.push('typed-of:' + t);
for (const [k, v] of new Map([['mk', 'mv']])) out.push('map-of:' + k + v);
lbl: for (const p of [1, 2, 3]) { for (const q of [1, 2, 3]) { if (q === 2) continue lbl; if (p === 3) break lbl; out.push('labelled:' + p + q); } }
let w = 0;
while (true) { w++; if (w % 2) continue; if (w > 5) break; out.push('while-continue:' + w); }
do out.push('do-once'); while (false);
let count = 0;
outer: while (true) { inner: do { count++; if (count === 3) break outer; continue outer; } while (true); }
out.push('nested-labels:' + count);
(async () => {
  for await (o.awaited of [Promise.resolve('aw1')]) out.push('for-await-member:' + o.awaited);
  for await (const [x, y] of [Promise.resolve(['ax', 'ay'])]) out.push('for-await-pattern:' + x + y);
  lab: for await (const v of [1, 2, 3]) { if (v === 2) continue lab; if (v === 3) break lab; out.push('for-await-label:' + v); }
  console.log(out.join('\n'));
})();
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_loop_heads(run, tier):
    """CATCHES: for-in/for-of/for-await heads with member-expression and destructuring-assignment targets, var patterns, multiple declarators, inherited enumerable keys, sparse arrays, typed arrays and Maps, plus labelled continue/break across nested while/do-while/for-await loops."""
    r = run([*tier, "-e", PROG_LOOP_HEADS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "loop_heads")

PROG_GC = r"""// Allocate well over 100k objects in reference cycles (with calls in the loops, where the engine
// polls its collector) so the cycle collector runs several times while other data must survive.
const keep = [];
let checksum = 0;
for (let i = 0; i < 45000; i++) {
  const a = { i, peer: null };
  const b = { a, fn: null };
  a.peer = b;
  b.fn = () => a.i + b.a.i;
  if (i % 15000 === 0) keep.push(b);
  checksum += b.fn() % 7;
}
console.log('checksum', checksum, 'kept', keep.length, keep.map((b) => b.fn()).join(), keep[1].a.peer === keep[1]);
// closures whose scopes form cycles, with a getter that returns its own object
function makeCycle(n) { const self = { n, get me() { return self; } }; const f = () => self; self.f = f; return f; }
let last;
const sampled = [];
for (let i = 0; i < 40000; i++) { last = makeCycle(i); if (i % 20000 === 7) sampled.push(last); }
console.log('closures', last().n, last().me.f === last, sampled.map((f) => f().me.n).join());
// Map values in cycles; overwritten entries become garbage
const m = new Map();
const mk = (i) => { const k = { i }; k.self = k; return k; };
for (let i = 0; i < 110000; i++) m.set(i % 100, mk(i));
console.log('map', m.size, m.get(99).i, m.get(99).self === m.get(99), m.get(0).i);
// a suspended generator, a pending promise chain and a WeakMap key survive collections
function* g() { let x = 0; while (true) yield x++; }
const it = g(); it.next();
const wm = new WeakMap();
const wkey = { tag: 'weak-key' };
wm.set(wkey, { payload: 'weak-value' });
let resolveLater;
const pending = new Promise((r) => { resolveLater = r; }).then((v) => v + ' (after gc)');
const churn = () => { const o = [{}]; o[0].back = o; return o; };
for (let i = 0; i < 110000; i++) churn();
console.log('survivors', it.next().value, it.next().value, wm.get(wkey).payload, wm.has({}));
// scopes with many bindings, and a function scope extended by sloppy direct eval, captured
// by closures that must survive another round of collections
function manyLocals(seed) {
  let v0 = seed, v1 = v0 + 1, v2 = v1 + 1, v3 = v2 + 1, v4 = v3 + 1, v5 = v4 + 1, v6 = v5 + 1, v7 = v6 + 1;
  let v8 = v7 + 1, v9 = v8 + 1, v10 = v9 + 1, v11 = v10 + 1, v12 = v11 + 1, v13 = v12 + 1, v14 = v13 + 1, v15 = v14 + 1;
  let v16 = v15 + 1, v17 = v16 + 1, v18 = v17 + 1, v19 = v18 + 1, v20 = v19 + 1;
  return () => v0 + v5 + v10 + v15 + v20;
}
function evalExtended(tag) { const base = 'base-' + tag; eval('var added = base + "+eval"'); return () => added; }
const manyFn = manyLocals(100);
const evalFn = evalExtended('E');
for (let i = 0; i < 110000; i++) churn();
console.log('scope survivors', manyFn(), evalFn());
resolveLater('promise resolved');
pending.then((v) => console.log(v));
"""


@pytest.mark.parametrize("tier", [[], ["--tier=bytecode"]], ids=["jit", "bytecode"])  # interp is too slow for 100k+ allocations
def test_cycle_collector_survivors(run, tier):
    """CATCHES: a cycle collector (triggered by >100k cyclic objects, closures and Map entries) that frees still-reachable objects, closures, captured scopes, suspended generators or pending promises, or corrupts values kept alive across collections."""
    r = run([*tier, "-e", PROG_GC])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "cycle_collector_survivors")

PROG_TAIL = r"""'use strict';
// Values computed through calls in tail position (strict mode): results must be identical in
// every tier whether or not the engine eliminates the tail calls.
const out = [];
function direct(n, acc) { return n === 0 ? acc : direct(n - 1, acc + n); }
out.push('direct ' + direct(100, 0));
function viaCall(n, acc) { return n === 0 ? acc : viaCall.call(null, n - 1, acc + n); }
out.push('call ' + viaCall(100, 0));
function viaApply(n, acc) { return n === 0 ? acc : viaApply.apply(null, [n - 1, acc + n]); }
out.push('apply ' + viaApply(100, 0));
function viaReflect(n, acc) { return n === 0 ? acc : Reflect.apply(viaReflect, undefined, [n - 1, acc * 2 % 1000003]); }
out.push('reflect ' + viaReflect(100, 1));
const bound = function (n, acc) { return n === 0 ? acc : bound(n - 1, acc + 'b'); }.bind(null);
out.push('bound ' + bound(5, ''));
const arrow = (n, acc = []) => (n === 0 ? acc.join('') : arrow(n - 1, [...acc, n % 10]));
out.push('arrow ' + arrow(12));
function logical(n) { return n <= 0 || logical(n - 1); }
function logicalAnd(n) { return n > 0 && logicalAnd(n - 1) || 'bottom'; }
out.push('logical ' + logical(100) + ' ' + logicalAnd(100));
function comma(n) { return (n, n === 0 ? 'comma-done' : comma(n - 1)); }
out.push('comma ' + comma(100));
function getF() { return tagged; }
function tagged(strings, n) { return n === 0 ? strings.raw[0] : getF()`t${n - 1}`; }
out.push('tagged ' + tagged`start${50}`);
function method(n) { return n === 0 ? this.label : method.call(this, n - 1); }
out.push('this-preserved ' + method.call({ label: 'LBL' }, 50));
function mutualA(n) { return n === 0 ? 'A' : mutualB(n - 1); }
function mutualB(n) { return n === 0 ? 'B' : mutualA(n - 1); }
out.push('mutual ' + mutualA(101) + mutualB(101));
function ctorTail(n) { return n === 0 ? new Date(0).toISOString() : ctorTail(n - 1); }
out.push('builtin-at-bottom ' + ctorTail(10));
function throwsAtBottom(n) { if (n === 0) throw new Error('bottom error at depth'); return throwsAtBottom(n - 1); }
try { throwsAtBottom(100); } catch (e) { out.push('throw ' + e.message); }
function inTry(n) { try { return n === 0 ? 'try-done' : inTry(n - 1); } finally { if (n === 50) out.push('finally ran at 50'); } }
out.push('in-try ' + inTry(100));
function genTail(n) { return n === 0 ? [...(function* () { yield 'g1'; yield 'g2'; })()].join() : genTail(n - 1); }
out.push('generator-at-bottom ' + genTail(20));
function makeObj(tag) { return { tag }; }
function makePrim() { return 42; }
function CtorObj() { this.own = 'instance'; return makeObj('from-tail-call'); }
function CtorPrim() { this.own = 'instance'; return makePrim(); }
out.push('construct-tail ' + JSON.stringify(new CtorObj()) + ' ' + JSON.stringify(new CtorPrim()));
class TailBase { constructor() { this.base = true; } }
class TailDerived extends TailBase { constructor() { super(); return makeObj('derived-override'); } }
out.push('derived-tail ' + JSON.stringify(new TailDerived()));
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_strict_tail_positions(run, tier):
    """CATCHES: strict-mode calls in tail position (direct, call/apply/Reflect.apply, bound, arrow, logical/comma/conditional operands, tagged templates, mutual recursion, inside try/finally) that compute wrong values, lose the this binding, or mishandle exceptions and finally blocks when the engine trampolines them."""
    r = run([*tier, "-e", PROG_TAIL])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "strict_tail_positions")

PROG_EDGE = r"""// global function declarations over existing global properties (CreateGlobalFunctionBinding)
function isNaN(x) { return 'script-level isNaN(' + x + ')'; }
var nonConfigVar = 'declared var';
const descOf = (k) => { const d = Object.getOwnPropertyDescriptor(globalThis, k); return [typeof d.value, d.writable, d.enumerable, d.configurable].join('/'); };
console.log('global fn over builtin', isNaN(1), descOf('isNaN'));
(0, eval)('function nonConfigVar() { return "now a function"; }');
console.log('eval fn over non-configurable var', nonConfigVar(), descOf('nonConfigVar'));
globalThis.configurableProp = 'plain property';
(0, eval)('function configurableProp() { return "redefined"; }');
console.log('eval fn over configurable prop', configurableProp(), descOf('configurableProp'));
try { (0, eval)('function undefined() {}'); } catch (e) { console.log('eval fn over undefined', e.name + ': ' + e.message); }
try { (0, eval)('var x1 = 1; let x1 = 2;'); } catch (e) { console.log('eval var/let clash', e.name + ': ' + e.message); }
async function af({ x }) { return x; }
let r1;
try { r1 = af(); console.log('no sync throw', r1 instanceof Promise); } catch (e) { console.log('sync throw', e.message); }
r1.catch((e) => console.log('rejected', e.name + ': ' + e.message));
async function ad(a = (() => { throw new Error('param default threw'); })()) {}
ad().catch((e) => console.log('rejected2', e.message));
// for-await over sync iterator yielding a rejected promise
const syncIt = { [Symbol.iterator]() { let i = 0; return { next() { i++; return i === 1 ? { value: 'ok1', done: false } : { value: Promise.reject(new Error('rejected value')), done: false }; }, return() { console.log('sync iterator closed'); return {}; } }; } };
(async () => { try { for await (const v of syncIt) console.log('got', v); } catch (e) { console.log('for-await caught', e.message); } })();
// await using null still awaits once
(async () => {
  const order = [];
  Promise.resolve().then(() => order.push('tick1')).then(() => order.push('tick2'));
  { await using n = null; order.push('in block'); }
  order.push('after block');
  await null; await null;
  console.log('await-using-null', order.join());
})();
// with + unscopables getter deleting the property
const o = { wx: 'present', get [Symbol.unscopables]() { delete this.wx; return {}; } };
with (o) { console.log('sloppy read after vanish', typeof wx === 'undefined' ? 'undefined' : wx); }
const o2 = { wy: 1, get [Symbol.unscopables]() { delete o2.wy; return {}; } };
with (o2) { try { (function () { 'use strict'; return wy; })(); console.log('strict read no error'); } catch (e) { console.log('strict read', e.name + ': ' + e.message); } }
const o3 = { wz: 1, get [Symbol.unscopables]() { delete o3.wz; return {}; } };
with (o3) { wz = 'recreated'; }
console.log('sloppy write after vanish', o3.wz);
const o4 = { wq: 1, get [Symbol.unscopables]() { delete o4.wq; return {}; } };
with (o4) { try { (function () { 'use strict'; wq = 2; })(); console.log('strict write ok', o4.wq); } catch (e) { console.log('strict write', e.name + ': ' + e.message); } }
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_global_bindings_and_edge_semantics(run, tier):
    """CATCHES: CreateGlobalFunctionBinding descriptor rules for script/eval functions over builtins, vars and plain properties, eval var/let clashes, async functions rejecting (not throwing) on parameter-binding errors, for-await closing a sync iterator on a rejected value, `await using null` still awaiting, and with-scope reads/writes after @@unscopables deletes the binding."""
    r = run([*tier, "-e", PROG_EDGE])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "global_bindings_and_edge_semantics")

PROG_SHADOWREALM = r"""const log = (...a) => console.log(...a);
const r = new ShadowRealm();
log('typeof', typeof ShadowRealm, Object.prototype.toString.call(r));
log('evaluate prim', r.evaluate('1 + 2'), r.evaluate('"s" + "t"'), r.evaluate('undefined'), r.evaluate('null'), typeof r.evaluate('Symbol("x")'), r.evaluate('10n') + 1n);
r.evaluate('globalThis.counter = 0; var declared = "realm-var";');
log('isolated globals', typeof globalThis.counter, r.evaluate('typeof declared'), r.evaluate('globalThis.Array === undefined'), r.evaluate('typeof console'));
const inc = r.evaluate('(x) => { counter += x; return counter; }');
log('wrapped fn', typeof inc, inc(5), inc(2), inc.name, inc.length);
const named = r.evaluate('function namedFn(a, b, c) {} namedFn');
log('wrapped props', named.name, named.length, named instanceof Function, Object.getPrototypeOf(named) === Function.prototype);
try { r.evaluate('({})'); } catch (e) { log('object result', e.name + ': ' + e.message); }
try { r.evaluate('[1,2]'); } catch (e) { log('array result', e.name); }
try { r.evaluate('throw new Error("inside")'); } catch (e) { log('inner throw', e.name + ': ' + e.message, e instanceof TypeError); }
try { r.evaluate('this is bad syntax'); } catch (e) { log('syntax', e.name, e instanceof SyntaxError); }
try { r.evaluate(5); } catch (e) { log('non-string', e.name + ': ' + e.message); }
const passFn = r.evaluate('(cb) => cb(21) * 2');
log('callback across', passFn((x) => x));
try { passFn(() => ({})); } catch (e) { log('callback returns obj', e.name + ': ' + e.message); }
try { r.evaluate('(o) => o')({}); } catch (e) { log('pass object', e.name + ': ' + e.message); }
const r2 = new ShadowRealm();
log('separate realms', r2.evaluate('typeof counter'), r.evaluate('counter'));
const throwsInner = r.evaluate('() => { throw new RangeError("inner range") }');
try { throwsInner(); } catch (e) { log('wrapped throw', e.name + ': ' + e.message); }
try { ShadowRealm(); } catch (e) { log('call without new', e.name); }
log('instanceof checks', r.evaluate('[] instanceof Array'), r.evaluate('Object.getPrototypeOf([]) === Array.prototype'));
// callables crossing in both directions get wrapped again
const adder = r.evaluate('(makeOuter) => { const outerFn = makeOuter(); return outerFn(2) + 1; }');
log('wrap-of-wrap', adder(() => (x) => x * 10));
const returnsFn = r.evaluate('() => (y) => "inner-made:" + y');
const madeInside = returnsFn();
log('function returned from realm', typeof madeInside, madeInside('arg'), madeInside.name, madeInside.length);
const takesFn = r.evaluate('(f) => typeof f + ":" + f(1, 2)');
log('outer function seen inside', takesFn(function outerNamed(a, b) { return a + b; }));
try { r.evaluate('(f) => f()')(() => { throw new SyntaxError('outer threw'); }); } catch (e) { log('outer throw seen outside', e.name + ': ' + e.message); }
const catcher = r.evaluate('(f) => { try { f(); return "no throw"; } catch (e) { return "caught inside: " + e.constructor.name + " " + (e instanceof TypeError); } }');
log('outer throw seen inside', catcher(() => { throw new RangeError('x'); }));
// nested ShadowRealm inside a ShadowRealm
log('nested realm', r.evaluate('new ShadowRealm().evaluate("typeof counter + \'/\' + (40 + 2)")'));
// realm intrinsics are distinct
log('distinct intrinsics', r.evaluate('Array') === Array, typeof r.evaluate('Array'), r.evaluate('(Array.prototype.myExt = 1, "patched inside")'), typeof [].myExt);
// symbols cannot cross? (they are primitives)
const sym = r.evaluate('Symbol.for("shared-key")');
log('registered symbol crosses', typeof sym, sym === Symbol.for('shared-key'), r.evaluate('Symbol.iterator') === Symbol.iterator);
try { ShadowRealm.prototype.evaluate.call({}, '1'); } catch (e) { log('bad receiver', e.name + ': ' + e.message); }
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_shadowrealm(run, tier):
    """CATCHES: ShadowRealm implementations that leak globals between realms, let objects cross the boundary, or produce different wrapped-function names/lengths and TypeError messages for errors thrown inside the realm."""
    r = run([*tier, "-e", PROG_SHADOWREALM])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "shadowrealm")
