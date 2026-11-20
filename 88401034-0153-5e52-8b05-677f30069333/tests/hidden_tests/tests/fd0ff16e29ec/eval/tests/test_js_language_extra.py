"""Extra core-language coverage: tree-walker (interp tier) slow paths, primitive/proxy/TypedArray
receivers on [[Set]], `using` in every body kind, decorator context.access objects, ShadowRealm
importValue and wrapped-function CopyNameAndLength, legacy fn.caller/arguments, async iteration
protocol errors, and script/module early errors.

Each engine-heavy program runs under all three execution tiers (JIT, interpreter, bytecode) and
must produce the same golden output in each.
"""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

PROG_USING_MAIN = r"""const log = (...a) => console.log(...a);
const res = (name) => ({ name, [Symbol.dispose]() { log('dispose', name); } });
using top = res('module-top');
log('module body');
function* g() { using r = res('gen'); yield 1; yield 2; }
for (const v of g()) log('gen yields', v);
const it = g(); it.next(); it.return(9); log('after gen return');
async function af() { using r = res('async-fn'); await null; log('async fn body'); return 'af-done'; }
af().then(v => log(v));
class S { static { using r = res('static-block'); log('in static block'); } }
for (using x = res('cfor'), y = res('cfor2'); ; ) { log('cfor body', x.name); break; }
let i = 0;
for (using z = res('cfor-loop'); i < 2; i++) { log('iter', i); }
try { eval('using q = 1;'); } catch (e) { log('eval using', e.name, e.message); }
try { (0, eval)('{ using q = res2; }'); } catch (e) { log('eval2', e.name, e.message); }
label1: label2: for (const a of [1,2]) { if (a === 2) continue label1; log('lab', a); }
async function af2() {
  for (await using w = { async [Symbol.asyncDispose]() { log('async-cfor dispose'); } }; ;) { log('acfor'); break; }
  for await (await using q of [res('fa-await-using')]) log('fa body', q.name);
}
af2();
await null;
log('module end');
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_using_in_every_body_kind(run, workdir, tier):
    """CATCHES: `using`/`await using` disposal that is skipped or misordered in module top-level code, generator bodies (on completion and on .return()), async function bodies, class static blocks, C-style for heads (both resources, reverse order, once per loop not per iteration) and `for (await using ...)` heads; also the script-goal SyntaxError for a top-level `using` in eval code and labelled-continue through nested labels."""
    write_files(workdir, {"main.mjs": PROG_USING_MAIN})
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "using_every_body_kind")

PROG_PRIM_WRITES = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
const seen = [];
Object.defineProperty(Boolean.prototype, 'bset', { set(v) { seen.push('bool:' + typeof this + ':' + v); }, configurable: true });
Object.defineProperty(Symbol.prototype, 'sset', { set(v) { seen.push('sym:' + typeof this + ':' + v); }, configurable: true });
Object.defineProperty(BigInt.prototype, 'nset', { set(v) { seen.push('big:' + typeof this + ':' + v); }, configurable: true });
Object.defineProperty(Number.prototype, 'ro', { get() { return 'ro-get'; }, configurable: true });
show('bool set', () => { true.bset = 1; return seen.join(); });
show('sym set', () => { Symbol('s').sset = 2; return seen.join(); });
show('big set', () => { (10n).nset = 3; return seen.join(); });
show('num getter-only sloppy', () => { (5).ro = 4; return (5).ro; });
show('num getter-only strict', () => { 'use strict'; (5).ro = 4; return 'no throw'; });
show('bool plain sloppy', () => { false.plain = 1; return false.plain; });
show('bool plain strict', () => { 'use strict'; false.plain = 1; return 'no'; });
show('sym plain strict', () => { 'use strict'; Symbol().plain = 1; return 'no'; });
show('big plain strict', () => { 'use strict'; (1n).plain = 1; return 'no'; });
// proxy on primitive prototype chain
const trapLog = [];
const P = new Proxy({}, { set(t, k, v, r) { trapLog.push('set ' + String(k) + '=' + v + ' recv:' + typeof r); return true; }, get(t, k, r) { if (k === 'viaProxy') return 'proxied:' + typeof r; return undefined; } });
Object.setPrototypeOf(Boolean.prototype, P);
show('bool proxy set', () => { true.viaProxySet = 7; return trapLog.join(); });
show('bool proxy get', () => true.viaProxy);
Object.setPrototypeOf(Boolean.prototype, Object.prototype);
// BigInt getter on prototype
Object.defineProperty(BigInt.prototype, 'twice', { get() { return this * 2n; }, configurable: true });
show('bigint getter', () => String((21n).twice));
// typed array on prototype chain
const ta = new Uint8Array(4);
const child = Object.create(ta);
show('ta proto set idx', () => { child[1] = 300; return JSON.stringify([ta[1], Object.keys(child), child.hasOwnProperty(1)]); });
show('ta proto set oob', () => { child[10] = 5; return JSON.stringify([child.hasOwnProperty(10), ta.length]); });
show('ta proto set -0', () => { child['-0'] = 5; return JSON.stringify([child.hasOwnProperty('-0')]); });
show('ta proto set 1.5', () => { child['1.5'] = 5; return JSON.stringify([Object.getOwnPropertyNames(child)]); });
show('ta proto set named', () => { child.foo = 5; return JSON.stringify([Object.getOwnPropertyNames(child)]); });
show('Reflect.set ta recv self', () => { const t = new Int16Array(2); const o = Object.create(t); return JSON.stringify([Reflect.set(o, '0', 70000, t), t[0], Reflect.set(o, '5', 1, t)]); });
// Reflect.set with receivers
show('Reflect.set nonwritable recv', () => { const recv = Object.defineProperty({}, 'x', { value: 1, writable: false }); return Reflect.set({}, 'x', 2, recv) + ',' + recv.x; });
show('Reflect.set accessor recv', () => { const recv = { get x() { return 1; } }; return Reflect.set({}, 'x', 2, recv) + ',' + recv.x; });
show('Reflect.set proxy recv false', () => { const recv = new Proxy({}, { defineProperty() { return false; } }); return Reflect.set({}, 'x', 2, recv); });
show('strict assign via proxy recv false', () => { 'use strict'; const recv = new Proxy({}, { defineProperty() { return false; } }); const o = Object.create(recv); o.y = 1; return 'no'; });
show('Reflect.set prim recv', () => Reflect.set({}, 'x', 2, 5));
// frozen array length
show('length nonwritable sloppy', () => { const a = [1, 2, 3]; Object.defineProperty(a, 'length', { writable: false }); a.length = 0; return a.length; });
show('length nonwritable strict', () => { 'use strict'; const a = [1, 2, 3]; Object.defineProperty(a, 'length', { writable: false }); a.length = 0; return a.length; });
show('push past ro length strict', () => { 'use strict'; const a = [1]; Object.defineProperty(a, 'length', { writable: false }); a[5] = 1; return a.length; });
show('push past ro length sloppy', () => { const a = [1]; Object.defineProperty(a, 'length', { writable: false }); a[5] = 1; return a.length + ':' + a[5]; });
show('assign ro length via frozen', () => { 'use strict'; const a = Object.freeze([1]); a.length = 3; return 'no'; });
show('seen', () => seen.join(' | '));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_primitive_and_typedarray_receivers_on_set(run, tier):
    """CATCHES: [[Set]] on primitive bases (boolean/symbol/bigint/number) that ignores inherited setters, getter-only accessors (sloppy no-op vs strict TypeError) or a Proxy on the primitive prototype chain; TypedArray-on-prototype writes that store into the typed array instead of creating an own property on the receiver (or that create properties for out-of-range/canonical-numeric keys); Reflect.set receiver rules; and non-writable array `length` writes/appends (sloppy false vs strict TypeError messages)."""
    r = run([*tier, "-e", PROG_PRIM_WRITES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "primitive_typedarray_receivers")

PROG_PROXY_CHAIN = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// revoked proxy as prototype
const { proxy: rp, revoke } = Proxy.revocable({ inherited: 1 }, {});
const kid = Object.create(rp);
show('get via live proxy proto', () => kid.inherited);
show('set via live proxy proto', () => { kid.fresh = 2; return Object.keys(kid).join(); });
revoke();
show('get via revoked proto', () => kid.inherited);
show('set via revoked proto', () => { kid.other = 3; return 'no'; });
show('in via revoked proto', () => 'zz' in kid);
// proxy proto with non-callable traps
const bad = new Proxy({}, { get: 5, set: 'x' });
const k2 = Object.create(bad);
show('noncallable get trap', () => k2.foo);
show('noncallable set trap', () => { k2.foo = 1; return 'no'; });
show('direct noncallable get', () => bad.foo);
show('direct noncallable set', () => { bad.foo = 1; return 'no'; });
// proxy without traps on chain delegates
const plain = new Proxy({ base: 'b' }, {});
const k3 = Object.create(plain);
show('passthrough get', () => k3.base);
show('passthrough set', () => { k3.base = 'own'; return k3.base + '/' + plain.base; });
// get invariant with non-configurable accessor without getter
const tgt = {};
Object.defineProperty(tgt, 'acc', { set(v) {}, configurable: false });
Object.defineProperty(tgt, 'acc2', { get() { return 1; }, configurable: false });
Object.defineProperty(tgt, 'fixed', { value: 10, writable: false, configurable: false });
const inv = new Proxy(tgt, { get(t, k) { return 'lie'; }, set() { return true; } });
show('get invariant setter-only', () => inv.acc);
show('get invariant getter ok', () => inv.acc2);
show('get invariant data', () => inv.fixed);
show('get via chain invariant', () => Object.create(inv).acc);
const tgt2 = {};
Object.defineProperty(tgt2, 'gonly', { get() { return 1; }, configurable: false });
Object.defineProperty(tgt2, 'fixed', { value: 10, writable: false, configurable: false });
const inv2 = new Proxy(tgt2, { set() { return true; } });
show('set invariant getter-only', () => { inv2.gonly = 5; return 'no'; });
show('set invariant fixed same', () => { inv2.fixed = 10; return 'same ok'; });
show('set invariant fixed diff', () => { inv2.fixed = 11; return 'no'; });
show('set via chain invariant', () => { Object.create(inv2).gonly = 5; return 'no'; });
// deleteProperty variants
const dt = { a: 1 };
Object.defineProperty(dt, 'nc', { value: 1, configurable: false });
const dp1 = new Proxy(dt, {});
show('delete passthrough', () => [delete dp1.a, delete dp1.nc, delete dp1.missing].join());
show('delete passthrough strict', () => { 'use strict'; return delete dp1.nc; });
const dp2 = new Proxy(dt, { deleteProperty() { return true; } });
show('delete lie nc', () => delete dp2.nc);
const ne = Object.preventExtensions({ q: 1 });
const dp3 = new Proxy(ne, { deleteProperty() { return true; } });
show('delete lie non-extensible', () => delete dp3.q);
show('delete trap false strict', () => { 'use strict'; return delete new Proxy({ z: 1 }, { deleteProperty() { return false; } }).z; });
show('delete noncallable trap', () => delete new Proxy({}, { deleteProperty: 1 }).z);
show('delete revoked', () => { const r = Proxy.revocable({}, {}); r.revoke(); return delete r.proxy.x; });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_proxy_on_prototype_chain_and_invariants(run, tier):
    """CATCHES: proxies reached through an object's prototype chain (live, revoked, trap-less, with non-callable traps) handled differently from direct proxy access; missing get/set invariant checks for non-configurable accessors and read-only data properties; and deleteProperty trap results (passthrough, lying about non-configurable or non-extensible targets, strict-mode false) with their exact TypeError messages."""
    r = run([*tier, "-e", PROG_PROXY_CHAIN])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "proxy_chain_invariants")

PROG_LEGACY_CALLER = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
function inner() { return inner.caller; }
function outer() { return inner(); }
show('caller is outer', () => outer() === outer);
show('caller top', () => inner() === null ? 'null' : typeof inner());
function strictOuter() { 'use strict'; return inner(); }
function argsReader(a, b) { return readArgs(); }
function readArgs() { const x = argsReader.arguments; return x ? Array.from(x).join('+') : String(x); }
show('fn.arguments live', () => argsReader(1, 2));
show('fn.arguments idle', () => argsReader.arguments);
function noArgsNamed(p) { return noArgsNamed.arguments.length + ':' + noArgsNamed.arguments[0]; }
show('fn.arguments self', () => noArgsNamed('z'));
const arrow = () => 1;
show('arrow caller', () => { try { return arrow.caller; } catch (e) { return e.name; } });
class K { m() { return 1; } }
show('method caller', () => { try { return new K().m.caller; } catch (e) { return e.name; } });
function* gen() {}
show('gen caller', () => { try { return gen.caller; } catch (e) { return e.name; } });
async function asy() {}
show('async caller', () => { try { return asy.caller; } catch (e) { return e.name; } });
function sloppyStrictBody() { 'use strict'; return 1; }
show('strict fn caller', () => { try { return sloppyStrictBody.caller; } catch (e) { return e.name + ':' + e.message; } });
function rec(n) { if (n === 0) return rec.caller === rec; return rec(n - 1); }
show('recursive caller', () => rec(2));
function viaCall() { return inner.call(null); }
show('caller via call', () => viaCall() === viaCall);
function wrapper() { return [1].map(function cb() { return cb.caller; })[0]; }
show('caller from native', () => { const c = wrapper(); return c === null ? 'null' : typeof c; });
// duplicate param mapped arguments
function dup(a, a) { arguments[0] = 'A0'; arguments[1] = 'A1'; return a + ',' + Array.from(arguments).join(); }
show('dup params mapped', () => dup(1, 2));
function dup3(a, b, a) { b = 'B'; return Array.from(arguments).join() + '|' + a; }
show('dup3', () => dup3(1, 2, 3));
function destr({ x }, y) { y = 9; return arguments[1]; }
show('non-simple unmapped', () => destr({ x: 1 }, 2));
console.log('top-level caller', inner() === null, argsReader.arguments === null);
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_legacy_caller_arguments_and_mapped_duplicates(run, tier):
    """CATCHES: engines without the legacy sloppy-function `fn.caller` / `fn.arguments` reflection (null when inactive, the live arguments object, the calling function, TypeError for strict/arrow/method/generator/async functions) and wrong arguments-object mapping when parameter names are duplicated (the last same-named parameter wins the alias)."""
    r = run([*tier, "-e", PROG_LEGACY_CALLER])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "legacy_caller_arguments")

PROG_DECORATOR_ACCESS = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
const ctxs = {};
const grab = (tag) => (v, c) => { ctxs[tag] = c; };
const ns = { deco: { nested: (v, c) => { ctxs.nested = c; } } };
const sym = Symbol('symKey');
class A {
  @grab('field') pub = 1;
  @grab('sfield') static sf = 2;
  @grab('priv') #p = 3;
  @grab('method') meth() { return 'm'; }
  @grab('pmeth') #pm() { return 'pm'; }
  @grab('getter') get g() { return 'g'; }
  @grab('setter') set g(v) { this._g = v; }
  @grab('acc') accessor ac = 'acc';
  @grab('sacc') static accessor sac = 'sacc';
  @grab('pacc') accessor #pac = 'pacc';
  @grab('sym') [sym]() { return 'sym'; }
  @ns.deco.nested nn() {}
  @grab('pget') get #pg() { return 'pg'; }
  @grab('pset') set #pg(v) { this._pg = v; }
  @grab('smeth') static sm() { return 'sm'; }
  @grab('spm') static #spm() { return 'spm'; }
  @grab('sget') static get sg() { return 'sg'; }
  static callSpm() { return A.#spm(); }
  readP() { return this.#p; }
  readPac() { return this.#pac; }
}
const a = new A();
for (const k of Object.keys(ctxs)) {
  const c = ctxs[k];
  const acc = c.access || {};
  console.log(k, c.kind, typeof c.name === 'symbol' ? c.name.toString() : c.name, c.static, c.private, 'has' in acc, 'get' in acc, 'set' in acc);
}
show('field get', () => ctxs.field.access.get(a));
show('field set', () => { ctxs.field.access.set(a, 10); return a.pub; });
show('priv get', () => ctxs.priv.access.get(a));
show('priv set', () => { ctxs.priv.access.set(a, 30); return a.readP(); });
show('priv get foreign', () => ctxs.priv.access.get({}));
show('method get', () => ctxs.method.access.get(a).call(a));
show('pmeth get', () => ctxs.pmeth.access.get(a).call(a));
show('getter get', () => ctxs.getter.access.get(a));
show('setter set', () => { ctxs.setter.access.set(a, 'S'); return a._g; });
show('acc get/set', () => { ctxs.acc.access.set(a, 'acc2'); return ctxs.acc.access.get(a) + '/' + a.ac; });
show('sacc get', () => ctxs.sacc.access.get(A));
show('pacc get/set', () => { ctxs.pacc.access.set(a, 'pacc2'); return ctxs.pacc.access.get(a) + '/' + a.readPac(); });
show('sym get', () => ctxs.sym.access.get(a).call(a));
show('pget', () => ctxs.pget.access.get(a));
show('pset', () => { ctxs.pset.access.set(a, 'PS'); return a._pg; });
show('smeth', () => ctxs.smeth.access.get(A)());
show('spm', () => ctxs.spm.access.get(A)() + ',' + A.callSpm());
show('sget', () => ctxs.sget.access.get(A));
show('sfield get', () => ctxs.sfield.access.get(A));
show('field get on prim', () => ctxs.field.access.get(5));
show('field set on other', () => { const o = {}; ctxs.field.access.set(o, 4); return JSON.stringify(o); });
// accessor backing field from unrelated object
const d = Object.getOwnPropertyDescriptor(A.prototype, 'ac');
show('accessor get unrelated', () => d.get.call({}));
show('accessor set unrelated', () => d.set.call({}, 1));
// decorator errors
const errs = [
  'class X { @(5) m() {} }',
  'class X { @(5) f = 1; }',
  'class X { @(5) accessor q = 1; }',
  'class X { @((v,c) => 5) f = 1; }',
  'class X { @((v,c) => 5) accessor q = 1; }',
  'class X { @((v,c) => ({get: 5, set: 6, init: 7})) accessor q = 1; }',
  'class X { @((v,c) => undefined) accessor q = 1; }; new X().q',
  'class X { @((v,c) => {}) static m() {} }; typeof X.m',
  'class X { @((v,c) => {}) static get m() { return 1 } }; X.m',
  'class X { @((v,c) => { c.addInitializer(function() { this.inited = true; }); }) static accessor sa = 1; }; X.inited',
  'class X { @((v,c) => { c.addInitializer(function() { this.inited = "inst"; }); }) f = 1; }; new X().inited',
  'class X { @((v,c) => { c.addInitializer(function() { this.sinit = "static-field"; }); }) static f = 1; }; X.sinit',
];
for (const src of errs) show(src.slice(0, 50), () => eval(src));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_decorator_context_access_and_errors(run, tier):
    """CATCHES: decorator context objects with wrong kind/name/static/private values or missing `access.get`/`access.set` functions for fields, private fields, methods, accessors and static members; auto-accessor getters/setters that accept unrelated receivers; and the TypeError messages for non-callable decorators and bad field/accessor decorator return values; addInitializer timing for static/instance elements."""
    r = run([*tier, "-e", PROG_DECORATOR_ACCESS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "decorator_context_access")

PROG_SHADOW_DRIVER = r"""(async () => {
const log = (...a) => console.log(...a);
const r = new ShadowRealm();
const show = async (label, p) => { try { const v = await p; log(label, typeof v, typeof v === 'function' ? v.name + '/' + v.length : String(v)); } catch (e) { log(label, '!' + e.name + ': ' + e.message); } };
await show('import answer', r.importValue('./exp.mjs', 'answer'));
const g = await r.importValue('./exp.mjs', 'greet');
log('imported fn', g('realm'));
await show('import default', r.importValue('./exp.mjs', 'default'));
await show('import object', r.importValue('./exp.mjs', 'obj'));
await show('import missing', r.importValue('./exp.mjs', 'nope'));
await show('import undefined binding', r.importValue('./exp.mjs', 'undef'));
await show('import throwing module', r.importValue('./bad.mjs', 'x'));
await show('import not found', r.importValue('./missing.mjs', 'x'));
try { r.importValue('./exp.mjs', 5); } catch (e) { log('sync exportName check', e.name + ': ' + e.message); }
try { ShadowRealm.prototype.importValue.call({}, './exp.mjs', 'x'); } catch (e) { log('sync brand check', e.name + ': ' + e.message); }
log('realm counter isolated', r.evaluate('typeof answer'));
// wrapped function name/length edge cases
const mk = (src) => { try { const f = r.evaluate(src); return f.name + '|' + f.length; } catch (e) { return '!' + e.name + ': ' + e.message; } };
log('len non-number', mk('const f = function(a,b){}; Object.defineProperty(f, "length", {value: "3"}); f'));
log('len infinity', mk('const f = function(){}; Object.defineProperty(f, "length", {value: Infinity}); f'));
log('len -infinity', mk('const f = function(){}; Object.defineProperty(f, "length", {value: -Infinity}); f'));
log('len negative', mk('const f = function(){}; Object.defineProperty(f, "length", {value: -5}); f'));
log('len fraction', mk('const f = function(){}; Object.defineProperty(f, "length", {value: 2.7}); f'));
log('len deleted', mk('const f = function(a){}; delete f.length; f'));
log('len throws', mk('const f = function(){}; Object.defineProperty(f, "length", {get() { throw new Error("len") }}); f'));
log('name non-string', mk('const f = function(){}; Object.defineProperty(f, "name", {value: 42}); f'));
log('name throws', mk('const f = function(){}; Object.defineProperty(f, "name", {get() { throw new Error("nm") }}); f'));
log('bound fn', mk('function base(a,b,c){}; base.bind(null, 1)'));
log('proxy fn', mk('new Proxy(function pf(a){}, {})'));
const retObj = r.evaluate('() => ({})');
try { retObj(); } catch (e) { log('wrapped returns object', e.name + ': ' + e.message); }
log('evaluate strict directive', r.evaluate('"use strict"; (function() { return this === undefined; })()'));
log('evaluate sloppy this', r.evaluate('(function() { return typeof this; })()'));
log('evaluate empty', String(r.evaluate('')), String(r.evaluate(';')), String(r.evaluate('if (true) {}')));
log('evaluate using in block', r.evaluate('{ using x = { [Symbol.dispose]() { globalThis.disposed = 1; } }; } disposed'));
})();
"""

SHADOW_EXP = r"""export const answer = 42;
export function greet(n) { return 'hello ' + n; }
export const obj = { a: 1 };
export let undef;
export default 'dflt';
"""

SHADOW_BAD = r"""throw new Error('module boom');
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_shadowrealm_import_value_and_wrapped_names(run, workdir, tier):
    """CATCHES: ShadowRealm.prototype.importValue that is missing, resolves modules in the caller realm, lets objects cross, or reports wrong errors (missing export, failed evaluation, unknown module, bad exportName/receiver); and wrapped-function CopyNameAndLength that mishandles non-number/infinite/negative/fractional lengths, non-string names, or throwing length/name getters; evaluate() strictness and empty-completion results."""
    write_files(workdir, {"driver.cjs": PROG_SHADOW_DRIVER, "exp.mjs": SHADOW_EXP, "bad.mjs": SHADOW_BAD})
    r = run([*tier, "driver.cjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "shadowrealm_import_value")

PROG_EARLY_ERRORS = r"""const cases = [
  'using [a] = x;',
  '{ using {a} = x; }',
  '{ using a; }',
  'switch (1) { foo: }',
  'switch (1) { case 1: break; bogus }',
  '#x: 1',
  'l1: while (0) { break\nl1; }',
  'var f; (f) = function(){}; f.name',
  'var g; (g) = class {}; g.name',
  'var h; h = function(){}; h.name',
  'var k; (k) ||= function(){}; k.name',
  'delete undefined',
  'class A { m() { super.#x; } }',
  'class A { #x; m() { super.#x; } }',
  'n\\u0065w Object()',
  'new a?.b()',
  'new (a?.b)()',
  '\\u0069mport("x")',
  'function* g() { yi\\u0065ld; }',
  'function* g() { var yi\\u0065ld; }',
  'async function f() { class A { static { await 1; } } }',
  'class A { static { await; } }',
  '({ m() { super(); } })',
  'function f() { super(); }',
  'function f() { super.x; }',
  'class A { m() { super(); } }',
  'class A { constructor() { super(); } }',
  'class A extends Object { [super()] = 1 }',
  'class A { [arguments] = 1 }',
  'class A { x = arguments; }',
  'class A { static { arguments; } }',
  'class A { static { return; } }',
  'class A { static { super(); } }',
  '#x',
  'class A { #x; m() { return #x; } }',
  'class A { #x; m() { return !#x; } }',
  'function f(interface) { "use strict"; }',
  'function f(a, implements) { "use strict"; }',
  '"use strict"; (package) => 1',
  '"use strict"; var { a: [static] } = {};',
  '"use strict"; [eval] = [1];',
  '"use strict"; ({ a: arguments } = {});',
  '"use strict"; ({ __proto__: eval } = {});',
  '"use strict"; ({ __proto__: eval = 1 } = {});',
  '"use strict"; [...eval] = [];',
  '"use strict"; [ , eval = 1] = [];',
  '"use strict"; ({...arguments} = {});',
  '[a, , b] = [1, 2, 3];',
  '({ __proto__: a } = {});',
  '({ __proto__: a = 5 } = {}); a',
  '[...a, ] = []',
  '({ ...{a} } = {})',
  '({ m() {} } = {})',
  '({ get x() {} } = {})',
  '@dec.prop class Q {}',
  '@(dec) class Q {}',
  'class Q { @this m() {} }',
  'class Q { @x.y.z m() {} }',
  'class Q { accessor y }',
  'class Q { accessor\n y }',
  'for (using of = null;;) break;',
  'for (using of [1]) ;',
  'async function f() { for (await using x of []) ; }',
  'async function f() { for (await using of []) ; }',
  'x\n/foo/g',
  'let a = 1\n/2/g',
  'label: function f() {}',
  'if (1) label: function f() {}',
  'while (1) function f() {}',
  'if (1) class C {}',
  'if (1) let x = 1;',
  'do function f(){} while(0)',
  'a\n++\nb',
  'async\nfunction f(){}',
  'yield = 1',
  'function* g() { yield\n* 2 }',
  '({ async: 1, await: 2, get: 3, set: 4, static: 5 }).async',
  '({ async, get, set } = { async: 1, get: 2, set: 3 }); async + get + set',
  '({ async *gen() { yield 1; } }).gen().next().constructor.name',
  'async () => { await: 1 }',
  'function f() { "use strict"; 010 }',
  '"use strict"; "\\08"',
  'function f() { "\\07"; "use strict"; }',
  '`\\07`',
  'String.raw`\\07`',
  '(function(){ return typeof (x => x) })()',
  'let [a, ...b,] = []',
  'let {a, ...b,} = {}',
  'for (let [a] = [1], b of []) ;',
  'for (var i, j of []) ;',
  'for (let x of [], []) ;',
  'for (x => x in {}) ;',
  'import.meta',
  'export var x = 1;',
  'import x from "y";',
  'new.target',
  'function f() { new.t\\u0061rget }',
  'a?.b = 1',
  'a?.b++',
  'a?.`x`',
  '({a: 1} = 1)',
  '(a, b) = 1',
  'a + 1 = 2',
  '++(a + 1)',
  'for ((a, b) of []) ;',
  'arguments => { "use strict" }',
  'class C extends D { constructor() { super()?.x; } }',
  'let x; { var x; }',
  'try {} catch ([e]) { var e; }',
  'try {} catch (e) { let e; }',
  'try {} catch (e) { for (var e of []); }',
  'function f(a = super.x) {}',
  '({ f(a = super.x) { return a; } })',
];
for (const src of cases) {
  let msg;
  try { const v = (0, eval)(src); msg = 'ok ' + (typeof v === 'string' ? JSON.stringify(v) : typeof v === 'function' ? 'fn' : String(v)); }
  catch (e) { msg = e instanceof SyntaxError ? 'SyntaxError: ' + e.message : '(runtime) ' + e.name + ': ' + e.message; }
  console.log(JSON.stringify(src).padEnd(52) + ' -> ' + msg);
}
"""


def test_script_early_errors_extra(run):
    """CATCHES: a parser that accepts (or rejects with different SyntaxError messages) ~110 script-goal edge cases: `using` binding forms, bad switch clauses, private-name labels/expressions, `super` outside methods, `arguments` in field initializers/static blocks, strict reserved parameter names introduced by a "use strict" body, strict eval/arguments assignment patterns, decorator member expressions, `for (using of ...)` disambiguation, regex-vs-division after newlines, single-statement-context declarations, and NamedEvaluation not applying to parenthesized targets."""
    r = run(["-e", PROG_EARLY_ERRORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "script_early_errors_extra")

MODULE_ERROR_CASES = {
    'lexerr': "export const s = 'abc;\n",
    'privname': "class A { m() { return this.#nope; } }\nexport default A;\n",
    'varlex': "let dupe = 1;\nvar dupe = 2;\n",
    'varlex2': "var dupe2 = 1;\nlet dupe2 = 2;\n",
    'importvar': "import { a } from './ok.mjs';\nvar a;\n",
    'lonesur': "const x = 1;\nexport { x as '\\uD800' };\n",
    'escfrom': "import { a } \\u0066rom './ok.mjs';\n",
    'nonstrspec': "import x from y;\n",
    'assertnl': "import { a } from './ok.mjs'\nassert({ type: 'json' });\n",
    'strkeyattr': "import j from './data.json' with { \"type\": \"json\" };\nexport default j;\nconsole.log('strkeyattr json', JSON.stringify(j));\n",
    'escas': "import { a \\u0061s b } from './ok.mjs';\n",
    'reserved': "import { package } from './ok.mjs';\n",
    'escdefault': "export \\u0064efault 1;\n",
    'asyncdefault': "export default async function () { return 'adf'; }\n",
    'escstaras': "export * \\u0061s ns from './ok.mjs';\n",
    'escnamedas': "const q = 1;\nexport { q \\u0061s r };\n",
    'escnamedfrom': "export { a } \\u0066rom './ok.mjs';\n",
    'strlocal': "export { 'a' };\n",
    'strlocal2': "export { 'a' as b };\n",
    'importmeta_esc': "console.log(import.m\\u0065ta.url);\n",
    'awaitlabel': "await: 1;\n",
    'awaitident': "var await = 1;\n",
    'with': "with ({}) {}\n",
    'htmlcomment': "<!-- comment\nexport const z = 1;\n",
    'dupexport': "export const a = 1;\nexport { a };\n",
    'unresolved': "export { nothere };\n",
    'newtarget': "new.target;\n",
    'returntop': "return 1;\n",
    'yieldtop': "yield 1;\n",
    'superprop': "super.x;\n",
    'deletestrict': "var v; delete v;\n",
    'octal': "export const o = 010;\n",
    'source_default': "import source from './ok.mjs';\nconsole.log('source default import', source);\n",
}


def test_module_early_errors_extra(run, workdir):
    """CATCHES: module-goal parsing/linking that accepts invalid modules or words errors differently: lexer errors in a module, undeclared private names, var/lexical and import/var clashes, lone-surrogate export names, escaped contextual keywords (from/as/default/import.meta), non-string specifiers, a newline before legacy `assert`, string-keyed import attributes, strict reserved import bindings, string-literal local exports, `await`/`with`/HTML comments/legacy octal in modules, and `import source from` as an ordinary default import named `source`."""
    names = list(MODULE_ERROR_CASES)
    files = {f"{n}.mjs": src for n, src in MODULE_ERROR_CASES.items()}
    files["ok.mjs"] = "export const a = 'A';\nexport default 'okdefault';\n"
    files["data.json"] = '{"k": [1, 2]}'
    files["main.mjs"] = (
        "const names = " + repr(names).replace("'", '"') + ";\n"
        "for (const n of names) {\n"
        "  try { const ns = await import('./' + n + '.mjs'); console.log(n.padEnd(16), 'ok', JSON.stringify(Object.keys(ns)), typeof ns.default === 'function' ? await ns.default() : ''); }\n"
        "  catch (e) { console.log(n.padEnd(16), e.name + ': ' + e.message); }\n"
        "}\n"
    )
    write_files(workdir, files)
    r = run(["main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "module_early_errors_extra")

PROG_TREE_WALKER = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// destructuring defaults name anonymous functions
show('arr pattern default fn name', () => { const [f = function () {}, g = () => {}, c = class {}] = []; return [f.name, g.name, c.name].join(); });
show('obj pattern default fn name', () => { const { f = function () {}, g = () => {} } = {}; return f.name + ',' + g.name; });
show('assign arr default fn name', () => { let f, g; [f = function () {}, g = class {}] = []; return f.name + ',' + g.name; });
show('assign obj default fn name', () => { let f, g; ({ f = function () {}, x: g = () => {} } = {}); return f.name + ',' + g.name; });
show('param default fn name', () => { function p(f = function () {}, { g = () => {} } = {}) { return f.name + ',' + g.name; } return p(); });
show('logical assign fn name', () => { let a, b = 0, c = null; a ||= function () {}; b ||= () => {}; c ??= class {}; return [a.name, b.name, c.name].join(); });
show('assign class name', () => { let K; K = class {}; return K.name; });
show('var class name', () => { var K2 = class {}; let K3 = class { static n = this.name; }; return K2.name + ',' + K3.n; });
show('export-like default naming', () => { const o = { ['comp' + 1]: function () {}, [Symbol('desc')]: () => {}, [Symbol()]: function () {} }; return Reflect.ownKeys(o).map(k => o[k].name).join('|'); });
// destructuring iterator close on abrupt
show('array destr close on throw', () => { const log = []; const it = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { log.push('ret'); return {}; } }; } }; try { const [a = (() => { throw new Error('dflt'); })()] = [undefined]; } catch (e) { log.push(e.message); } try { let x; [x, (() => { throw new Error('tgt'); })().y] = it; } catch (e) { log.push(e.message); } return log.join(); });
show('array assign elision exhausts', () => { let a, b; const it = { [Symbol.iterator]() { let n = 0; return { next() { n++; return { value: n, done: n > 1 }; } }; } }; [, , a, b] = it; return a + ',' + b; });
show('array destr break closes', () => { const log = []; const it = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { log.push('closed'); return {}; } }; } }; for (const [x] of [it]) { log.push(x); } outer: for (const q of [1]) { const [y] = it; log.push('y' + y); break outer; } return log.join(); });
show('for-of destr return', () => { const log = []; function f() { for (const [a, b] of [[1, 2]]) { return a + b; } } return f(); });
// with statements
show('with null', () => { with (null) {} });
show('with undefined', () => { with (undefined) {} });
show('with assign unscopable', () => { const o = { x: 1, [Symbol.unscopables]: { y: true }, y: 2 }; var y = 'outer'; with (o) { x = 10; y = 'set'; } return o.x + ',' + o.y + ',' + y; });
show('with delete in body', () => { const o = { z: 1 }; with (o) { delete o.z; z = 5; } return o.z + ',' + typeof z; });
show('with function call this', () => { const o = { f() { return this === o; } }; with (o) { return f(); } });
show('with strict-mode ref', () => { const o = { q: 1 }; with (o) { return (function () { 'use strict'; return q; })(); } });
// labels
show('nested labels', () => { let s = ''; a: b: c: for (let i = 0; i < 3; i++) { if (i === 1) continue a; s += i; } return s; });
show('labeled block break', () => { let s = 'x'; blk: { s += '1'; break blk; } return s; });
show('label continue while', () => { let i = 0, s = ''; L: while (i < 4) { i++; if (i % 2) continue L; s += i; } return s; });
show('label do-while', () => { let i = 0; L1: L2: do { i++; if (i < 3) continue L1; break L2; } while (true); return i; });
// for with test false initially
show('for test false', () => { let n = 0; for (let i = 5; i < 3; i++) n++; return n; });
show('for let closure', () => { const fs = []; for (let i = 0; i < 3; i++) fs.push(() => i); return fs.map(f => f()).join(); });
// tagged templates with member/index tags
show('tagged member', () => { const o = { t(s, ...v) { return this === o ? s.raw.join('|') + v.join() : 'bad'; } }; return o.t`a${1}b`; });
show('tagged index', () => { const o = { t(s) { return this === o; } }; return o['t']`x`; });
show('tagged nonfn', () => { const o = { t: 5 }; return o.t`x`; });
show('tagged nonfn index', () => { const o = {}; return o['q']`x`; });
show('tagged call', () => { const mk = () => (s) => s[0]; return mk()`hey`; });
show('tagged cache', () => { const f = (s) => s; const g = () => f`same`; return g() === g(); });
// strict tail calls with tagged templates and call-expression callees
show('tail tagged', () => { 'use strict'; function t(s, n) { return n === 0 ? 'done' : t`x${n - 1}`; } return t`x${50}`; });
show('tail member tagged', () => { 'use strict'; const o = { t(s, n) { return n === 0 ? 'm-done' : o.t`x${n - 1}`; } }; return o.t`x${20}`; });
show('tail call-callee', () => { 'use strict'; const mk = () => (n) => n === 0 ? 'cc-done' : mk()(n - 1); return mk()(30); });
show('tail logical', () => { 'use strict'; function f(n) { return n === 0 ? 'l' : (n > 1000 || f(n - 1)); } return f(40); });
show('tail nullish', () => { 'use strict'; function f(n) { return n === 0 ? 'nn' : (null ?? f(n - 1)); } return f(40); });
show('tail and', () => { 'use strict'; function f(n) { return n === 0 ? 'and' : (true && f(n - 1)); } return f(40); });
show('tail optional base null', () => { 'use strict'; const o = null; function f() { return o?.m(); } return String(f()); });
show('tail member base null', () => { 'use strict'; const o = null; function f() { return o.m(); } return f(); });
show('tail non-callable', () => { 'use strict'; const o = { m: 1 }; function f() { return o.m(); } return f(); });
show('tail comma', () => { 'use strict'; function f(n) { return n === 0 ? 'seq' : (0, f(n - 1)); } return f(30); });
// optional chain calls
show('opt call short', () => { const o = null; return String(o?.a.b.c()); });
show('opt index short', () => { const o = undefined; return String(o?.[(() => { throw 1; })()]); });
show('opt index call', () => { const o = { f() { return this === o; } }; return o?.['f'](); });
show('opt call on undefined fn', () => { const o = {}; return String(o.f?.()); });
show('opt deep', () => { const o = { a: null }; return String(o.a?.b.c.d); });
show('opt in call args', () => { const o = null; return String((o?.x)?.y); });
show('delete opt', () => { const o = null; const p = { x: 1 }; return [delete o?.x, delete o?.[0], delete p?.x, 'x' in p].join(); });
show('delete opt chain short', () => { const o = { a: null }; return delete o.a?.b.c; });
show('delete paren', () => { const o = { x: 1 }; return delete (o.x) + ',' + ('x' in o); });
show('delete super', () => { class A { m() { return delete super.x; } } return new A().m(); });
show('delete super idx', () => { class A { m() { return delete super[(() => 'k')()]; } } return new A().m(); });
show('delete null base', () => { const o = null; return delete o.x; });
show('delete null idx', () => { const o = null; return delete o[0]; });
show('delete ta index', () => { const t = new Uint8Array(2); return [delete t[0], delete t[5], delete t['-0'], delete t.foo].join(); });
show('delete ta index strict', () => { 'use strict'; const t = new Uint8Array(2); return delete t[0]; });
show('delete global prop', () => { globalThis.tmpGlobal = 1; return [delete tmpGlobal, typeof tmpGlobal, delete NaN, delete undefinedVarXYZ].join(); });
// binary coercions in tree walker
show('bitops coerced', () => [ '6' & '3', '6' ^ 3, '1' << '4', ({ valueOf() { return 12; } }) >> 1, '-8' >>> 28].join());
show('exp nan', () => [1 ** NaN, (-1) ** Infinity, ({ valueOf: () => 1 }) ** Infinity, 2 ** -1074].join());
show('mod edge', () => [5 % Infinity, -0 % 5, Infinity % 2, 5 % 0, ({ valueOf: () => 7 }) % 0].map(x => Object.is(x, -0) ? '-0' : String(x)).join());
show('bigint shift huge', () => [String(-5n >> 1073741824n), String(5n >> 1073741824n), String(-5n << -1073741824n)].join());
show('bigint obj eq', () => [10n == Object(10n), Object(3n) == 3n, 1n == { valueOf: () => 1n }, 2n == { toString: () => '2' }].join());
show('bigint mixed unary', () => +1n);
show('instanceof non-obj', () => 1 instanceof 5);
show('instanceof non-callable', () => ({}) instanceof {});
show('instanceof hasInstance', () => [1 instanceof { [Symbol.hasInstance]: (v) => v === 1 }, ({}) instanceof Object].join());
show('instanceof hasInstance noncallable', () => ({}) instanceof { [Symbol.hasInstance]: 5 });
show('in non-obj', () => 'a' in 'abc');
show('string wrapper in', () => ['length' in Object('ab'), '1' in Object('ab'), '5' in Object('ab')].join());
show('to string objects', () => `${{ toString: () => 'ts' }}` + String({ [Symbol.toPrimitive]: () => 'tp' }));
show('to prim object result', () => `${{ toString: () => ({}), valueOf: () => ({}) }}`);
show('sym key via toPrimitive', () => { const s = Symbol('k'); const o = { [s]: 'found' }; return o[{ [Symbol.toPrimitive]: () => s }]; });
show('zero to string', () => [String(-0), (-0).toString(), `${-0}`, [-0] + ''].join());
show('update via with', () => { const o = { c: 1 }; with (o) { c++; ++c; } return o.c; });
show('compound super idx', () => { class B { } B.prototype.k = 5; class D extends B { m() { super['k'] += 1; return this.k; } } return new D().m(); });
show('super set member', () => { class B { set v(x) { this._v = 'B' + x; } } class D extends B { m() { super.v = 1; super['v'] = 2; return this._v; } } return new D().m(); });
show('super private set', () => { class D { #p = 1; m(o) { o.#p = 5; return o.#p; } } return new D().m(new D()); });
show('private set foreign', () => { class D { #p = 1; m(o) { o.#p = 5; } } return new D().m({}); });
show('private set prim', () => { class D { #p = 1; m(o) { o.#p = 5; } } return new D().m(3); });
show('private get prim', () => { class D { #p = 1; m(o) { return o.#p; } } return new D().m(3); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_tree_walker_semantics(run, tier):
    """CATCHES: wrong NamedEvaluation for destructuring defaults and logical assignment, missing IteratorClose on abrupt destructuring, `with` (null/undefined objects, @@unscopables, vanished bindings), nested labels, tagged templates with member/index/call tags (this binding, TypeError for non-callables), strict tail calls through tagged templates/logical/comma/call-expression callees, optional-chain short-circuiting in calls/deletes, delete forms (super, null base, TypedArray indices, globals), ToPrimitive-based bitwise/exponent/modulo/BigInt coercions and instanceof/in errors, super/private member assignment."""
    r = run([*tier, "-e", PROG_TREE_WALKER])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "tree_walker_semantics")

PROG_ASYNC_ITER = r"""const log = (...a) => console.log(...a);
const run = async (label, f) => { try { const v = await f(); log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { log(label, '!' + e.name + ': ' + e.message); } };
const badCtorPromise = () => { const p = Promise.resolve('v'); Object.defineProperty(p, 'constructor', { get() { throw new Error('ctor getter'); } }); return p; };
(async () => {
  await run('asyncIterator returns prim', async () => { for await (const x of { [Symbol.asyncIterator]() { return 5; } }) ; });
  await run('asyncIterator noncallable', async () => { for await (const x of { [Symbol.asyncIterator]: 5 }) ; });
  await run('sync value ctor throws', async () => { const out = []; try { for await (const x of [1, badCtorPromise(), 3]) out.push(x); } catch (e) { out.push('caught ' + e.message); } return out.join(); });
  await run('sync value rejects closes', async () => { const log2 = []; const it = { [Symbol.iterator]() { let i = 0; return { next() { i++; return { value: i === 2 ? Promise.reject(new Error('rej')) : i, done: i > 3 }; }, return() { log2.push('closed'); return {}; } }; } }; try { for await (const x of it) log2.push(x); } catch (e) { log2.push(e.message); } return log2.join(); });
  await run('async next returns prim', async () => { for await (const x of { [Symbol.asyncIterator]() { return { next() { return 1; } }; } }) ; });
  await run('break closes async iter', async () => { const l = []; const it = { [Symbol.asyncIterator]() { return { next() { return Promise.resolve({ value: 1, done: false }); }, return() { l.push('ret'); return Promise.resolve({ done: true }); } }; } }; for await (const x of it) { l.push(x); break; } return l.join(); });
  await run('break closes, return noncallable', async () => { const it = { [Symbol.asyncIterator]() { return { next() { return { value: 1, done: false }; }, return: 5 }; } }; for await (const x of it) break; });
  await run('break closes, return gives prim', async () => { const it = { [Symbol.asyncIterator]() { return { next() { return { value: 1, done: false }; }, return() { return 7; } }; } }; for await (const x of it) break; });
  await run('break sync source close prim', async () => { const it = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { return 7; } }; } }; for await (const x of it) break; });
  await run('break sync source close value', async () => { const l = []; const it = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { l.push('sync-ret'); return { value: Promise.resolve('rv') }; } }; } }; for await (const x of it) break; return l.join(); });
  await run('throw in body swallows close err', async () => { const it = { [Symbol.asyncIterator]() { return { next() { return { value: 1, done: false }; }, return() { throw new Error('close err'); } }; } }; try { for await (const x of it) throw new Error('body'); } catch (e) { return e.message; } });
  // yield* in async generator with weird iterators
  await run('yield* throw no throw method', async () => { const inner = { [Symbol.asyncIterator]() { return { next() { return { value: 'i', done: false }; }, return() { return { done: true }; } }; } }; async function* g() { yield* inner; } const it = g(); await it.next(); return await it.throw(new Error('t')); });
  await run('yield* throw done', async () => { const inner = { [Symbol.asyncIterator]() { return { next() { return { value: 'i', done: false }; }, throw(e) { return { value: 'thrown-done', done: true }; } }; } }; async function* g() { const r = yield* inner; return 'g:' + r; } const it = g(); await it.next(); return JSON.stringify(await it.throw(new Error('t'))); });
  await run('yield* return not done', async () => { const inner = { [Symbol.asyncIterator]() { return { next() { return { value: 'i', done: false }; }, return(v) { return { value: 'still', done: false }; } }; } }; async function* g() { yield* inner; } const it = g(); await it.next(); const r1 = await it.return('x'); return JSON.stringify(r1); });
  await run('yield* asyncIterator noncallable', async () => { async function* g() { yield* { [Symbol.asyncIterator]: 5 }; } return (await g().next()).value; });
  await run('yield* asyncIterator returns prim', async () => { async function* g() { yield* { [Symbol.asyncIterator]() { return 1; } }; } return (await g().next()).value; });
  await run('sync yield* throw noncallable', async () => { const inner = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, throw: 5, return() { return {}; } }; } }; function* g() { yield* inner; } const it = g(); it.next(); it.throw(new Error('x')); });
  await run('sync yield* return noncallable', async () => { const inner = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return: 5 }; } }; function* g() { yield* inner; } const it = g(); it.next(); it.return(1); });
  await run('sync yield* result prim', async () => { const inner = { [Symbol.iterator]() { return { next() { return 3; } }; } }; function* g() { yield* inner; } g().next(); });
  await run('sync yield* return missing', async () => { const inner = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; } }; } }; function* g() { try { yield* inner; } finally { log('  finally ran'); } } const it = g(); it.next(); return JSON.stringify(it.return(42)); });
  // await on promise with throwing constructor
  await run('await bad ctor', async () => { await badCtorPromise(); return 'no'; });
  await run('async gen await bad ctor', async () => { async function* g() { yield await badCtorPromise(); } return (await g().next()).value; });
  await run('async gen yield bad ctor', async () => { async function* g() { yield badCtorPromise(); } return (await g().next()).value; });
  await run('async gen return bad ctor', async () => { async function* g() { yield 1; } const it = g(); await it.next(); return await it.return(badCtorPromise()); });
  await run('async gen return bad ctor done', async () => { async function* g() { } const it = g(); await it.next(); return await it.return(badCtorPromise()); });
  await run('async gen throw after done', async () => { async function* g() { } const it = g(); await it.next(); await it.throw(new Error('late')); });
  await run('async gen return value after done', async () => { async function* g() { } const it = g(); await it.next(); return JSON.stringify(await it.return(Promise.resolve('rv'))); });
  await run('async gen return in finally await', async () => { async function* g() { try { yield 1; } finally { await null; log('  ag finally'); } } const it = g(); await it.next(); return JSON.stringify(await it.return('R')); });
  await run('await thenable obj', async () => await { then(r) { r('thenable-val'); } });
  await run('await thenable throws', async () => await { then() { throw new Error('then threw'); } });
  await run('await then getter throws', async () => await { get then() { throw new Error('then getter'); } });
  await run('await non-thenable obj', async () => (await { x: 1 }).x);
  log('done');
})();
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_async_iteration_protocol_errors(run, tier):
    """CATCHES: for-await and yield* implementations that skip GetMethod/result-object checks (non-callable @@asyncIterator, primitive iterators/results, non-callable return/throw), fail to close sync iterators when an awaited value rejects or when the PromiseResolve constructor lookup throws, mishandle AsyncIteratorClose on break (sync sources included) and throw completions, and async generators whose await/yield/return of a promise with a throwing `constructor` getter, throw() after completion, or return() with an awaiting finally settle wrongly; await of thenables."""
    r = run([*tier, "-e", PROG_ASYNC_ITER])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "async_iteration_protocol_errors")

PROG_EVAL_CLASS = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
let globalLex = 1;
show('indirect eval var over global let', () => (0, eval)('var globalLex = 2;'));
show('direct eval var over block let', () => { { let bx = 1; eval('var bx = 2;'); } });
show('direct eval var over param', () => { function f(a) { { let a2; } eval('var a = 5'); return a; } return f(1); });
show('direct eval in catch param ok', () => { try { throw 1; } catch (ce) { eval('var ce = 2'); return ce; } });
show('strict indirect eval isolation', () => { (0, eval)('"use strict"; var strictVar = 1; function strictFn() {}'); return typeof strictVar + ',' + typeof strictFn; });
show('sloppy indirect eval leaks', () => { (0, eval)('var sloppyVar = 1; function sloppyFn() {}'); return typeof sloppyVar + ',' + typeof sloppyFn; });
show('eval super in method', () => { const o = { __proto__: { v: 'proto-v' }, m() { return eval('super.v'); } }; return o.m(); });
show('eval super in arrow in method', () => { const o = { __proto__: { v: 'pv2' }, m() { return (() => eval('super.v'))(); } }; return o.m(); });
show('eval super in nested function', () => { const o = { __proto__: { v: 1 }, m() { return (function () { return eval('super.v'); })(); } }; return o.m(); });
show('eval super at top', () => eval('super.x'));
show('eval super() in method', () => { const o = { m() { return eval('super()'); } }; return o.m(); });
show('eval super() in derived ctor', () => { class B { constructor() { this.b = 'base'; } } class D extends B { constructor() { eval('super()'); } } return new D().b; });
show('eval arguments in field', () => { class A { x = eval('arguments'); } return new A().x; });
show('eval arguments in field arrow', () => { class A { x = () => eval('arguments.length'); } return new A().x(); });
show('eval arguments in field fn', () => { class A { x = function () { return eval('arguments.length'); }; } return new A().x(1, 2); });
show('eval new.target in field', () => { class A { x = eval('new.target'); } return String(new A().x); });
// assignment to const / named fn expr
show('const assign sloppy', () => { const c = 1; c = 2; });
show('named fn expr assign sloppy', () => (function nfe() { nfe = 1; return typeof nfe; })());
show('named fn expr assign strict', () => (function nfe() { 'use strict'; nfe = 1; return typeof nfe; })());
show('const assign in eval', () => { const c2 = 1; eval('c2 = 2'); });
show('named fn expr via eval', () => (function nfe2() { eval('nfe2 = 1'); return typeof nfe2; })());
show('strict undeclared', () => { 'use strict'; undeclaredStrictVar = 1; });
show('strict undeclared via eval', () => { 'use strict'; eval('undeclaredStrict2 = 1'); });
show('sloppy undeclared', () => { (function () { undeclaredSloppy = 3; })(); return undeclaredSloppy; });
show('with strict vanish', () => { const o = { get [Symbol.unscopables]() { delete o.w; return {}; }, w: 1 }; with (o) { (function () { 'use strict'; })(); w = 2; } return JSON.stringify(o); });
show('with getbinding vanish', () => { const o = { get [Symbol.unscopables]() { delete o.v; return {}; }, v: 1 }; with (o) { return String(v); } });
// class edges
show('extends null proto', () => { class N extends null {} return Object.getPrototypeOf(N.prototype); });
show('extends fn proto null', () => { function F() {} F.prototype = null; class C extends F {} return Object.getPrototypeOf(C.prototype); });
show('extends fn proto prim', () => { function F() {} F.prototype = 3; class C extends F {} });
show('extends non-ctor', () => { class C extends Math.max {} });
show('extends arrow', () => { class C extends (() => {}) {} });
show('extends proxy ctor', () => { const P = new Proxy(class Base { constructor() { this.tag = 'base'; } }, { construct(t, a, nt) { const o = Reflect.construct(t, a, nt); o.trapped = true; return o; } }); class C extends P { constructor() { super(); this.own = 1; } } const c = new C(); return [c.tag, c.trapped, c.own, c instanceof C].join(); });
show('extends bound ctor', () => { class Base { constructor(a, b) { this.args = a + ',' + b; } } const BB = Base.bind(null, 'bound'); class C extends BB { constructor() { super('passed'); } } const c = new C(); return c.args + ',' + (c instanceof C); });
show('private methods twice', () => { class B { constructor(o) { return o; } } class C extends B { #m() {} constructor(o) { super(o); } } const o = {}; new C(o); new C(o); });
show('private methods non-extensible', () => { class B { constructor(o) { return o; } } class C extends B { #m() {} constructor(o) { super(o); } } new C(Object.preventExtensions({})); });
show('private field non-extensible', () => { class B { constructor(o) { return o; } } class C extends B { #f = 1; constructor(o) { super(o); } } new C(Object.freeze({})); });
show('private field twice', () => { class B { constructor(o) { return o; } } class C extends B { #f = 1; constructor(o) { super(o); } } const o = {}; new C(o); new C(o); });
show('static private on frozen', () => { class C { static x = Object.freeze(this); static #p = 1; } });
show('private getter+setter pair', () => { class C { get #a() { return this._a; } set #a(v) { this._a = v * 2; } run() { this.#a = 4; return this.#a; } } return new C().run(); });
show('private setter then getter', () => { class C { set #a(v) { this._a = v; } get #a() { return 'g' + this._a; } run() { this.#a = 1; return this.#a; } } return new C().run(); });
show('static accessor pair', () => { class C { static set q(v) { this._q = v; } static get q() { return 'Q' + this._q; } } C.q = 1; return C.q; });
show('getter then setter same key', () => { const o = { get k() { return 1; }, set k(v) { this.kk = v; } }; o.k = 9; return o.k + ',' + o.kk; });
show('ctor field anonymous fn name', () => { class C { f = function () {}; #g = () => {}; static h = class {}; getG() { return this.#g; } } const c = new C(); return [c.f.name, c.getG().name, C.h.name].join(); });
show('static block var this', () => { class C { static { var sbv = this.name; C.got = sbv; } } return C.got; });
show('class field this', () => { class C { a = this; } const c = new C(); return c.a === c; });
show('derived ctor returns prim', () => { class B {} class D extends B { constructor() { super(); return 1; } } return typeof new D(); });
show('derived ctor returns undefined no super', () => { class B {} class D extends B { constructor() { } } new D(); });
show('derived ctor returns obj no super', () => { class B {} class D extends B { constructor() { return { o: 1 }; } } return new D().o; });
show('super twice', () => { class B {} class D extends B { constructor() { super(); super(); } } new D(); });
show('new.target undefined', () => { function F() { return String(new.target); } return F(); });
show('class ctor call', () => { class C {} C(); });
show('setPrototypeOf class then super', () => { class A { constructor() { this.from = 'A'; } } class B { constructor() { this.from = 'B'; } } class C extends A { constructor() { super(); } } Object.setPrototypeOf(C, B); return new C().from; });
show('super ctor null', () => { class A {} class C extends A { constructor() { super(); } } Object.setPrototypeOf(C, null); new C(); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_eval_declarations_and_class_construction(run, tier):
    """CATCHES: eval var hoisting that ignores clashes with global/block lexicals, strict indirect eval leaking declarations, `super`/`arguments` validity checks inside direct eval (methods, arrows, nested functions, field initializers), const and named-function-expression assignment rules, strict undeclared assignment, class heritage validation (null/primitive prototypes, non-constructors, proxy and bound parents), private member initialization errors (twice, non-extensible receivers, static on frozen class), derived constructor return/super rules."""
    r = run([*tier, "-e", PROG_EVAL_CLASS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "eval_declarations_class_construction")

PROG_LEXER_CTORS = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// templates with regex literals inside substitutions
show('regex in template', () => `a${/[/]x\//.source}b${/q/gi.flags}c${'/'.match(/\//)[0]}`);
show('nested template regex', () => `${`${/\}/.test('}')}`}`);
show('template regex class bracket', () => `${/[\]}]/.test('}')}|${/a\/b/.source}`);
show('template division', () => { const a = 6, b = 2, g = 1; return `${a / b / g}`; });
show('template obj literal', () => `${{ a: '}' }.a}${(() => { return '`'; })()}`);
// unicode escapes in identifiers/strings
show('ident escapes', () => { const abc = 1, \u{62}cd = 2; return abc + bcd; });
show('surrogate pair escapes', () => ['😀'.length, '😀'.codePointAt(0), '\uD83D\u{DE00}'.codePointAt(0), '\u{D83D}\u{DE00}'.length].join());
show('lone surrogate escape', () => ['\uD83Dx'.length, '\uD83DA'.charCodeAt(1), '\uDE00'.charCodeAt(0)].join());
show('template surrogates', () => `😀`.codePointAt(0) + ',' + String.raw`\uD83D`.length);
show('tagged invalid escapes', () => ((s) => s[0] === undefined && s.raw[0])`\u{110000}\x1\01`);
show('tagged invalid u{', () => ((s) => JSON.stringify([s[0], s.raw[0]]))`\u{12345678901}`);
show('yield as ident division', () => { var yield_ = 0; return eval('var yield = 12, g = 3; yield /2/g'); });
show('await as ident division', () => eval('var await = 8, h = 2; await /2/h'));
// new with non-object prototype
show('new F proto prim', () => { function F() {} F.prototype = 5; return Object.getPrototypeOf(new F()) === Object.prototype; });
show('Reflect.construct nt proto prim', () => { function F() { this.x = 1; } function G() {} G.prototype = 'str'; return Object.getPrototypeOf(Reflect.construct(F, [], G)) === Object.prototype; });
show('Reflect.construct bound nt', () => { function F() {} function G() {} G.prototype = null; const BG = G.bind(null); return Object.getPrototypeOf(Reflect.construct(F, [], BG)) === Object.prototype; });
show('Reflect.construct proxy nt', () => { function F() {} const PG = new Proxy(function () {}, { get(t, k) { return k === 'prototype' ? 7 : t[k]; } }); return Object.getPrototypeOf(Reflect.construct(F, [], PG)) === Object.prototype; });
show('Function ctor nt proto prim', () => { function G() {} G.prototype = 1; const f = Reflect.construct(Function, ['return 1'], G); return Object.getPrototypeOf(f) === Function.prototype && f(); });
show('Function ctor bad params', () => Function('a,', 'return a'));
show('Function ctor comment param', () => Function('a //', 'return a')(5));
show('Function ctor super', () => Function('super()'));
show('new arrow', () => new (() => {})());
show('new method', () => new ({ m() {} }).m());
show('new gen', () => { function* g() {} return new g(); });
show('new async', () => { async function a() {} return new a(); });
show('new Math.max', () => new Math.max());
show('new Symbol', () => new Symbol());
show('new bound arrow', () => new ((() => {}).bind(null))());
// function.prototype edges
show('bind null-proto fn', () => { const f = function () { return 'b'; }; Object.setPrototypeOf(f, null); const b = Function.prototype.bind.call(f); return Object.getPrototypeOf(b) + ',' + b(); });
show('bind custom proto', () => { const P = Object.create(Function.prototype); const f = function () {}; Object.setPrototypeOf(f, P); return Object.getPrototypeOf(f.bind()) === P; });
show('toString native', () => Function.prototype.toString.call(Math.max));
show('toString bound', () => Function.prototype.toString.call(function q() {}.bind()));
show('toString class', () => Function.prototype.toString.call(class Q { m() {} }));
show('toString method', () => ({ m(a) { return a; } }).m.toString());
show('toString getter', () => Object.getOwnPropertyDescriptor({ get g() { return 1; } }, 'g').get.toString());
show('toString proxy', () => Function.prototype.toString.call(new Proxy(function () {}, {})));
show('toString nonfn', () => Function.prototype.toString.call({}));
show('toString Function ctor', () => Function('a', 'b', 'return a+b').toString());
// globals
show('parseFloat identity', () => parseFloat === Number.parseFloat && parseInt === Number.parseInt);
show('isNaN/isFinite coercion', () => [isNaN('x'), isNaN('1'), isFinite('1e3'), isFinite(null), isNaN({ valueOf: () => NaN })].join());
show('globalThis props', () => ['NaN', 'Infinity', 'undefined'].map(k => JSON.stringify(Object.getOwnPropertyDescriptor(globalThis, k))).join(' '));
show('encode/decode', () => [encodeURIComponent('a b&ü'), decodeURIComponent('%E2%82%AC'), encodeURI('http://x/a b?q=1#f'), decodeURI('%3B%2F')].join(' '));
show('decode malformed', () => decodeURIComponent('%E2%82'));
show('escape/unescape', () => escape('a b+ü€') + ' ' + unescape('%u20AC%41%zz'));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_lexer_templates_constructors_function_tostring(run, tier):
    """CATCHES: lexers that mis-scan regex literals (classes, escapes, flags) inside template substitutions, mishandle surrogate-pair/lone-surrogate escapes and invalid escapes in tagged templates, or treat `/` after identifier `yield`/`await` as a regex; [[Construct]] that ignores a non-object new.target prototype (incl. bound/proxy new.target), wrong not-a-constructor errors, Function-constructor parameter/comment handling, bind() prototype inheritance, Function.prototype.toString output for natives/bound/classes/methods/accessors, and global function coercions."""
    r = run([*tier, "-e", PROG_LEXER_CTORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "lexer_templates_constructors")



REPL_GLOBAL_DECLS = (
    "let x = 1;\n"
    "var x;\n"
    "Object.defineProperty(globalThis, 'q', {value: 1, writable: false, enumerable: false, configurable: false}), 'defined';\n"
    "function q() {}\n"
    "var zz = 5\n"
    "function zz() { return 7 }\n"
    "zz()\n"
    "let yy = 2\n"
    "function yy() {}\n"
    "class Cls {}\n"
    "let Cls = 1\n"
    "var NaN = 1\n"
    "let undefined = 2\n"
    "Object.preventExtensions(globalThis), 'sealed';\n"
    "var nv\n"
    "function nf() {}\n"
    "zz = 'still writable'\n"
    "typeof nv + ',' + typeof nf + ',' + zz\n"
)


def test_repl_global_declaration_instantiation(run):
    """CATCHES: a REPL whose per-input GlobalDeclarationInstantiation misses clashes with earlier inputs (let vs var/function/class, restricted non-configurable globals like NaN/undefined), allows functions over non-writable non-configurable globals or new vars/functions on a non-extensible global, or fails to overwrite an existing writable global var with a later function declaration; each failure reported as an Uncaught TypeError/SyntaxError line while the session continues."""
    r = run(["repl"], input=REPL_GLOBAL_DECLS.encode())
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "repl_global_declarations")
