"""Final gap-closing pass, part two: tier-agreement checks for rarely compiled shapes -- class
accessor pairs declared setter-first (public, static and private), decorators on symbol-keyed
members, `delete` of parenthesised/optional references, optional-index calls, `using` inside
eval, ArraySetLength when a valueOf freezes the array mid-assignment, Function.prototype.caller /
arguments reflection, mapped-arguments aliasing after delete/defineProperty, JIT-to-JIT direct
calls (deep recursion that overflows the frame pool, surplus arguments, exceptions unwinding
through compiled frames), sloppy `this` boxing for closures that need an activation, dead-result
sticky RegExp replace/split/match statements with non-integer lastIndex, and loop regions that
contain destructuring declarations, switch cases and labelled jumps."""

import pytest

from conftest import check_script, resources_for

G = resources_for(__file__)

TIERS = [pytest.param([], id="jit"), pytest.param(["--tier=bytecode"], id="bytecode"),
         pytest.param(["--tier=interp"], id="interp")]

PRELUDE = r'''
const T = (label, f) => {
  let out;
  try { out = String(f()); } catch (e) { out = 'threw ' + e.name + ': ' + e.message; }
  console.log(label + ' => ' + out);
};
'''


def check_js(run, workdir, name, body, **kw):
    """Run PRELUDE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRELUDE + body, **kw)


@pytest.mark.parametrize("cli", TIERS)
def test_class_accessor_pairs_decorators_and_delete_forms(run, workdir, cli):
    """CATCHES: class bodies where a getter declared AFTER its setter (public instance, static and
    private `#x`) replaces the setter instead of completing the accessor pair, decorators on
    symbol-keyed methods receiving a string name instead of the symbol, accessor decorators that
    return undefined breaking the auto-accessor, `delete (o.x)` / `delete o?.a?.b` mis-evaluated,
    optional element calls that do not short-circuit, `using` inside eval not disposing (while a
    top-level script `using` is a SyntaxError), Function.prototype.apply with negative/NaN
    lengths, and spread followed by a hole."""
    check_js(run, workdir, "accessor_pairs_decorators_delete", r'''
function cnt() { return arguments.length; }
T('apply odd lengths', () => [cnt.apply(null, { length: -1 }), cnt.apply(null, { length: NaN }), Reflect.apply(cnt, null, { length: -5 }), cnt.apply(null, { length: 2.7 })].join());
T('spread then hole', () => { const a = [1, 2]; const r = [...a, , 3]; return [r.length, 1 in r, 2 in r, r[2]].join(); });
T('hole then spread', () => { const r = [, ...'ab']; return [r.length, 0 in r, r.join('-')].join(); });
class C1 { set #x(v) { this.v = v; } get #x() { return 'got'; } t() { this.#x = 5; return this.#x + this.v; } }
T('private setter then getter', () => new C1().t());
class C2 { set x(v) { this.v = v; } get x() { return 'g'; } static set y(v) { this.w = v; } static get y() { return 'sy'; } }
T('accessor setter then getter', () => { const c = new C2(); c.x = 3; C2.y = 4; return [c.x, c.v, C2.y, C2.w].join(); });
T('accessor descriptor', () => { const d = Object.getOwnPropertyDescriptor(C2.prototype, 'x'); return [typeof d.get, typeof d.set, d.enumerable, d.configurable].join(); });
T('delete parenthesised', () => { const o = { x: 1, y: 2 }; return [delete (o.x), delete ((o['y'])), JSON.stringify(o)].join(); });
T('delete optional', () => { const o = { a: { b: 1 } }; const n = null; return [delete o?.a?.b, delete n?.a.b, delete o?.z?.q, JSON.stringify(o)].join(); });
T('optional index call', () => { const o = null; const k = 'f'; return [o?.[k](), o?.[k].g, ({ f() { return 'called'; } })?.[k]()].join(); });
T('eval using block', () => eval("{ using x = { [Symbol.dispose]() { console.log('  disposed in eval'); } }; 'v'; }"));
T('eval using top level', () => eval("using y = { [Symbol.dispose]() {} }; 7"));
function dec(v, ctx) { console.log('  dec ' + typeof ctx.name + ' ' + String(ctx.name) + ' ' + ctx.kind + ' static=' + ctx.static); }
const s = Symbol('sym');
T('decorator on symbol keys', () => { class D { @dec [s]() { return 1; } @dec static [Symbol()]() {} } return new D()[s](); });
T('accessor decorator returning undefined', () => { function ad(v, ctx) { return undefined; } class E { @ad accessor z = 3; } const e = new E(); const before = e.z; e.z = 4; return before + ',' + e.z; });
T('static block throws', () => { class F { static { throw new Error('in static'); } } return 'unreachable'; });
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_array_length_freeze_and_caller_reflection(run, workdir, cli):
    """CATCHES: ArraySetLength that checks writability before coercing the new length (a valueOf
    that freezes the array must make the write fail: silently in sloppy code, TypeError in strict,
    false from Reflect.set), length writes on a non-writable length, f.caller/f.arguments
    reflection from the running function, and mapped arguments objects that keep aliasing after
    `delete arguments[0]` or after defineProperty made the index non-writable."""
    check_js(run, workdir, "length_freeze_caller_reflection", r'''
T('freeze in valueOf (sloppy)', () => { const a = [1, 2, 3]; a.length = { valueOf() { Object.freeze(a); return 1; } }; return a.length + ' ' + Object.isFrozen(a); });
T('freeze in valueOf (strict)', () => { 'use strict'; const a = [1, 2, 3]; a.length = { valueOf() { Object.freeze(a); return 1; } }; return a.length; });
T('non-writable length (sloppy)', () => { const a = [1, 2]; Object.defineProperty(a, 'length', { writable: false }); a.length = 0; return a.length; });
T('non-writable length (strict)', () => { 'use strict'; const a = [1, 2]; Object.defineProperty(a, 'length', { writable: false }); a.length = 0; return a.length; });
T('Reflect.set length frozen by valueOf', () => { const a = [1]; return Reflect.set(a, 'length', { valueOf() { Object.freeze(a); return 0; } }) + ' ' + a.length; });
function top() { return top.caller; }
function viaSloppy() { return top(); }
T('caller is the sloppy caller', () => viaSloppy() === viaSloppy);
T('caller after return', () => top.caller === null);
function argsOf() { return argsOf.arguments; }
T('fn.arguments', () => { const a = argsOf(1, 2); return a.length + ',' + a[1]; });
function argsLazy(x) { return inner(); function inner() { return argsLazy.arguments[0]; } }
T('fn.arguments from inner', () => argsLazy('lz'));
T('mapped write and length', () => { function f(a, b) { arguments[0] = 'A'; arguments[5] = 'X'; arguments.length = 1; return [a, b, arguments[5], arguments.length].join(); } return f(1, 2); });
T('mapped delete then write', () => { function f(a) { delete arguments[0]; arguments[0] = 'n'; return a + arguments[0]; } return f('o'); });
T('mapped defineProperty', () => { function f(a) { Object.defineProperty(arguments, '0', { value: 'd' }); const r1 = a; Object.defineProperty(arguments, '0', { writable: false }); a = 'z'; return r1 + arguments[0] + a; } return f('o'); });
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_compiled_direct_calls_depth_arity_and_unwinding(run, workdir, cli):
    """CATCHES: compiled direct calls that mishandle 100-deep recursion (frame buffers beyond the
    pool must be released, results summed exactly), callees invoked with surplus arguments (extra
    values must be dropped, not shifted into locals), exceptions thrown inside compiled callees
    that leave the caller's operand stack inconsistent (try/catch inside a hot loop must resume
    with the right partial sums) and errors propagating through 100 compiled frames."""
    check_js(run, workdir, "direct_calls_depth_arity", r'''
function depth(n) { if (n === 0) return 0; let s = 0; for (let i = 0; i < 1; i++) s += depth(n - 1); return s + 1; }
let t = 0; for (let i = 0; i < 50; i++) t += depth(100);
console.log('depth', t);
function two(a, b) { let s = a; for (let i = 0; i < 2; i++) s += b; return s; }
function callsExtra(n) { let s = 0; for (let i = 0; i < n; i++) s += two(i, 1, 'extra', {}, [i]); return s; }
console.log('extra args', callsExtra(500));
function callsFew(n) { let s = ''; for (let i = 0; i < n; i++) s = String(two(i)); return s; }
console.log('missing args', callsFew(300));
function thrower(x) { for (let i = 0; i < 1; i++) { if (x % 7 === 0) throw new Error('at ' + x); } return x; }
function mid(n) { let s = 0, last = ''; for (let i = 0; i < n; i++) { try { s += 1 + thrower(i) * 2 + [i, i].length; } catch (e) { s += 1000; last = e.message; } } return s + ' ' + last; }
console.log('throws', mid(300));
function deepThrow(n) { for (let i = 0; i < 1; i++) { if (n === 0) throw new RangeError('bottom'); } return 1 + deepThrow(n - 1); }
let caught = 0, msg = ''; for (let i = 0; i < 30; i++) { try { deepThrow(100); } catch (e) { caught++; msg = e.name + ': ' + e.message; } }
console.log('deepThrow', caught, msg);
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_sloppy_this_for_closures_with_activations(run, workdir, cli):
    """CATCHES: compiled sloppy-mode functions that need an activation environment (they create
    closures over their locals) but skip OrdinaryCallBindThis -- a primitive receiver must be boxed
    (typeof this === 'object', instanceof String), an undefined receiver must become globalThis,
    while strict functions keep undefined / the raw receiver."""
    check_js(run, workdir, "sloppy_this_with_activation", r'''
String.prototype.envThis = function () { let c = 0; const g = () => c++; for (let i = 0; i < 2; i++) g(); return typeof this + ':' + (this instanceof String) + ':' + this.length + ':' + c; };
Number.prototype.envThis = function () { let c = 0; const g = () => c += 2; for (let i = 0; i < 1; i++) g(); return typeof this + ':' + (this + c); };
Boolean.prototype.envThis = function () { let c = 0; const g = () => c++; g(); return typeof this + ':' + (this.valueOf() === true) + ':' + c; };
function plainEnv() { let c = 0; const g = () => c++; for (let i = 0; i < 1; i++) g(); return (this === globalThis) + ':' + c; }
function drive(n) { let r = ''; for (let i = 0; i < n; i++) { r = 'abc'.envThis() + ' ' + (5).envThis() + ' ' + true.envThis() + ' ' + plainEnv(); } return r; }
console.log(drive(400));
function strictEnv() { 'use strict'; let c = 0; const g = () => c++; for (let i = 0; i < 1; i++) g(); return (this === undefined ? 'undef' : typeof this) + c; }
String.prototype.strictEnv = strictEnv;
const o = { strictEnv };
function drive2(n) { let r = ''; for (let i = 0; i < n; i++) r = strictEnv() + ' ' + o.strictEnv() + ' ' + 'x'.strictEnv(); return r; }
console.log(drive2(400));
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_dead_result_sticky_regexp_statements(run, workdir, cli):
    """CATCHES: optimised dead-result `s.replace(re, 'x');` / `s.split(re);` / `s.match(re);`
    statements in hot loops that assume a sticky RegExp's lastIndex is a non-negative integer:
    1.5, -1, 'x' and Infinity must go through ToLength exactly like the generic path (advancing,
    resetting to 0 on failure), and RegExp.lastMatch / leftContext must reflect the last success."""
    check_js(run, workdir, "dead_result_sticky_regexp", r'''
function run(re, s, n) { for (let i = 0; i < n; i++) { s.replace(re, 'x'); } return re.lastIndex; }
for (const li of [1.5, -1, 'x', 2, 7, Infinity]) {
  const re = /a/y; re.lastIndex = li; const r = run(re, 'baaab', 3);
  const re2 = /a/y; re2.lastIndex = li; const r2 = run(re2, 'baaab', 300);
  console.log(String(li), r, r2, RegExp.lastMatch, RegExp.leftContext);
}
const g = /a/gy; g.lastIndex = 1.5; console.log('gy', run(g, 'aab', 300), RegExp.lastMatch);
function splitRun(re, s, n) { for (let i = 0; i < n; i++) { s.split(re); } return re.lastIndex; }
const sy = /b/y; sy.lastIndex = 3; console.log('split sticky', splitRun(sy, 'abcabc', 300), RegExp.lastMatch);
function matchRun(re, s, n) { for (let i = 0; i < n; i++) { s.match(re); } return re.lastIndex; }
const my = /c/y; my.lastIndex = -2; console.log('match sticky', matchRun(my, 'cabc', 300), RegExp.lastMatch);
const mg = /c/g; mg.lastIndex = 2; console.log('match global', matchRun(mg, 'cabc', 300), RegExp.lastMatch);
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_loop_regions_with_destructuring_switch_and_labels(run, workdir, cli):
    """CATCHES: compiled loop regions that cannot carry a destructuring declaration (its
    null/undefined guard must still throw inside the loop and be catchable per iteration), loops
    nested in switch cases and default clauses, nested for-of/for-in with inner counted loops,
    nested conditional expressions in loop bodies, and labelled continue/break across two loops."""
    check_js(run, workdir, "loop_regions_shapes", r'''
function destrLoop(arr) { let s = 0; for (let i = 0; i < arr.length; i++) { const { a, b } = arr[i]; s += a * b; } return s; }
const data = Array.from({ length: 50 }, (_, i) => ({ a: i, b: 2 }));
let t = 0; for (let k = 0; k < 20; k++) t += destrLoop(data); console.log('destr', t);
function destrNull(arr) { let s = 0, msg = ''; for (let i = 0; i < arr.length; i++) { try { const { a } = arr[i]; s += a; } catch (e) { s += 100; msg = e.name; } } return s + ' ' + msg; }
console.log('destrNull', destrNull([{ a: 1 }, null, { a: 2 }, undefined]));
function arrDestrLoop(rows) { let s = 0; for (let i = 0; i < rows.length; i++) { const [x, , z = 10] = rows[i]; s += x + z; } return s; }
console.log('arrDestr', arrDestrLoop([[1, 2, 3], [4, 5], [6]]));
function switchLoop(k, n) { let s = 0; switch (k) { case 1: for (let i = 0; i < n; i++) s += i; break; case 2: { let j = n; while (j--) s += 2; } break; default: do { s++; } while (s < n); } return s; }
console.log('switch', switchLoop(1, 100), switchLoop(2, 100), switchLoop(3, 100));
function forOfInLoop(xs) { let s = 0; for (const x of xs) { for (let i = 0; i < x; i++) s += i; } for (const k in { a: 1, bb: 2 }) { for (let i = 0; i < 3; i++) s += k.length; } return s; }
console.log('forOfIn', forOfInLoop([10, 20, 30]));
function condLoop(n) { let s = 0; for (let i = 0; i < n; i++) s += (i & 1 ? (i % 3 ? 1 : 2) : 3) + (s > 50 && i < 80 ? 1 : 0); return s; }
console.log('cond', condLoop(200));
function labeled(n) { let s = 0; outer: for (let i = 0; i < n; i++) { for (let j = 0; j < n; j++) { if (j > i) continue outer; if (i * j > 50) break outer; s += j; } } return s; }
console.log('labeled', labeled(20));
''', cli=cli)


@pytest.mark.parametrize("cli", TIERS)
def test_parameter_hoisting_and_annex_b_shapes(run, workdir, cli):
    """CATCHES: compiled functions that mishandle a defaulted parameter followed by a destructured
    one, a `var` redeclaring a defaulted parameter (must keep the parameter value), a function
    declaration shadowing a parameter, Annex B block-function promotion (promoted when executed,
    undefined otherwise, NOT promoted past an intervening `let` of the same name, promoted out of a
    catch block), lexical array patterns with holes/defaults, object defaults and rest, and async
    generator request queues (next/return/throw interleaved before and after completion)."""
    check_js(run, workdir, "parameter_hoisting_annex_b", r'''
const out = [];
function paramDefaultDestr(a = 1, { b } = { b: 2 }) { let s = 0; for (let i = 0; i < 2; i++) s += a + b; return s; }
out.push('pdd ' + paramDefaultDestr() + ' ' + paramDefaultDestr(5, { b: 1 }));
function varRedeclParam(a = 3) { var a; let s = 0; for (let i = 0; i < 2; i++) s += a; return s; }
out.push('vrp ' + varRedeclParam() + ' ' + varRedeclParam(4));
function fnShadowsParam(g) { function g() { return 'decl'; } let s = ''; for (let i = 0; i < 2; i++) s += g(); return s; }
out.push('fsp ' + fnShadowsParam(() => 'arg'));
function annexB(flag) { if (flag) { function inner() { return 'inner'; } } let s = 0; for (let i = 0; i < 2; i++) s++; return typeof inner + s + (flag ? inner() : ''); }
out.push('annexB ' + annexB(true) + ' ' + annexB(false));
function blockedByLet() { let g = 1; { function g() { return 'fn'; } } return typeof g; }
function blockedInner() { { function h() { return 'h'; } } { let h = 2; { function h() {} } } return typeof h; }
function fromCatch() { try { throw 0; } catch (k) { { function k() {} } } return typeof k; }
out.push('annexB blocked ' + [blockedByLet(), blockedInner(), fromCatch()].join());
function holes(arr) { let [p, , q] = arr; const [r, , , t] = arr; let s = 0; for (let i = 0; i < 2; i++) s += p + q + r + (t ?? 0); return s; }
out.push('holes ' + holes([1, 2, 3, 4]) + ' ' + holes([1, 2, 3]));
function arrDefaults(arr) { let [p = 10, q = 20] = arr; let s = 0; for (let i = 0; i < 2; i++) s += p + q; return s; }
out.push('arrDefaults ' + arrDefaults([1]) + ' ' + arrDefaults([]));
function objDefaults(o) { const { p = 1, q: { r = 2 } = {} } = o; let s = 0; for (let i = 0; i < 2; i++) s += p + r; return s; }
out.push('objDefaults ' + objDefaults({}) + ' ' + objDefaults({ p: 5, q: { r: 6 } }));
function objRest(o) { const { p, ...rest } = o; let s = 0; for (let i = 0; i < 2; i++) s += p; return s + JSON.stringify(rest); }
out.push('objRest ' + objRest({ p: 1, z: 2, y: 3 }));
console.log(out.join('\n'));
async function* gen() { yield 1; yield 2; }
(async () => {
  const g = gen();
  console.log('queued', JSON.stringify(await Promise.all([g.next(), g.next(), g.next(), g.next(), g.return(9), g.next()])));
  const g2 = gen();
  console.log('early return', JSON.stringify(await g2.return(5)), JSON.stringify(await g2.next()), await g2.throw(new Error('x')).catch(e => 'rejected ' + e.message));
  const g3 = gen();
  await g3.next(); await g3.next(); await g3.next();
  console.log('after done', JSON.stringify(await Promise.all([g3.next(), g3.return(1), g3.next()])));
})();
''', cli=cli)


def test_shared_buffer_backed_typed_arrays(run, workdir):
    """CATCHES: TypedArray/DataView/Atomics paths that read or write a SharedArrayBuffer's bytes
    through a private copy instead of the shared block: BigInt64/BigUint64 element stores, fill,
    set, with/toReversed, Atomics add/exchange/compareExchange on BigInt elements, aliasing views of
    different widths over one SharedArrayBuffer, copyWithin/search methods, and a @@species
    constructor that hands back a view over a fresh SharedArrayBuffer (slice must copy the bytes
    into it; subarray passes (buffer, offset, length) to the same species function)."""
    check_js(run, workdir, "shared_buffer_typed_arrays", r'''
const sab = new SharedArrayBuffer(32);
const b64 = new BigInt64Array(sab); b64[0] = 5n; b64[1] = -7n; b64.fill(3n, 2, 3);
console.log(b64.join(), Atomics.add(b64, 0, 2n), Atomics.load(b64, 0), Atomics.exchange(b64, 1, 9n), Atomics.compareExchange(b64, 1, 9n, 1n), b64.join());
const f64 = new Float64Array(sab); f64[3] = 1.5; console.log(f64[3], new Uint8Array(sab, 24, 8).join());
const u16 = new Uint16Array(sab, 0, 4); u16.set([1, 2, 3, 4]); u16.reverse(); u16.sort(); console.log(u16.join(), u16.map(x => x * 2).join(), u16.slice(1, 3).join(), u16.subarray(2).join());
const dv = new DataView(sab); dv.setBigUint64(8, 2n ** 64n - 1n); dv.setInt16(0, -2, true); console.log(dv.getBigUint64(8), dv.getInt16(0, true), b64[1]);
const c = new Uint8Array(sab); c.copyWithin(0, 8, 12); console.log(c.subarray(0, 4).join(), c.indexOf(255), c.lastIndexOf(255), c.includes(255));
const bu = new BigUint64Array(sab, 0, 2); bu.set([1n, 2n]); console.log(bu.join(), Array.from(bu.entries()).join('|'), bu.toReversed().join(), bu.with(0, 8n).join());
class S extends Uint8Array { static get [Symbol.species]() { return function (len) { return new Uint8Array(new SharedArrayBuffer(len)); }; } }
const s = new S([1, 2, 3, 4]); const sl = s.slice(1, 3);
console.log(sl.constructor.name, sl.buffer instanceof SharedArrayBuffer, sl.join(), s.map(x => x * 3).join(), s.filter(x => x & 1).join(), 'subarray:' + s.subarray(1).length);
''')


def test_trapless_proxy_of_proxy_forwarding(run, workdir):
    """CATCHES: a proxy without traps whose target is itself a proxy, where the outer layer reads
    the inner proxy's (empty) own storage instead of forwarding each internal method through it:
    [[OwnPropertyKeys]] order (indices, strings, symbols), enumerability (Object.keys/entries,
    spread, Object.assign, for-in, JSON.stringify), [[GetOwnProperty]], [[DefineOwnProperty]],
    [[GetPrototypeOf]], preventExtensions/freeze reaching the real target, and traps on the INNER
    proxy (ownKeys, getPrototypeOf, getOwnPropertyDescriptor) being honoured through the outer."""
    check_js(run, workdir, "proxy_of_proxy_forwarding", r'''
const base = { b: 2, a: 1, 1: 'one', [Symbol('s')]: 3 };
Object.defineProperty(base, 'hid', { value: 0, enumerable: false });
const outer = new Proxy(new Proxy(base, {}), {});
T('ownKeys', () => Reflect.ownKeys(outer).map(String).join());
T('keys', () => Object.keys(outer).join());
T('entries', () => JSON.stringify(Object.entries(outer)));
T('gOPD', () => JSON.stringify(Object.getOwnPropertyDescriptor(outer, 'hid')));
T('gOPD missing', () => Object.getOwnPropertyDescriptor(outer, 'zz'));
T('defineProperty', () => { Object.defineProperty(outer, 'n', { value: 5, enumerable: true }); return base.n + ',' + Object.keys(base).join(); });
T('getPrototypeOf', () => Object.getPrototypeOf(outer) === Object.prototype);
T('Object.assign', () => JSON.stringify(Object.assign({}, outer)));
T('spread', () => JSON.stringify({ ...outer }));
T('for-in', () => { const ks = []; for (const k in outer) ks.push(k); return ks.join(); });
T('JSON', () => JSON.stringify(outer));
T('preventExtensions', () => { Object.preventExtensions(outer); return [Object.isExtensible(base), Object.isExtensible(outer), Object.isFrozen(outer)].join(); });
T('freeze', () => { Object.freeze(outer); return [Object.isFrozen(base), Object.isSealed(outer)].join(); });
const trapKeys = new Proxy(new Proxy({ x: 1, y: 2 }, { ownKeys() { return ['y', 'x']; } }), {});
T('inner ownKeys trap', () => Reflect.ownKeys(trapKeys).join() + ' ' + Object.keys(trapKeys).join());
const gp = new Proxy(new Proxy({}, { getPrototypeOf() { return Array.prototype; } }), {});
T('inner getPrototypeOf trap', () => [Object.getPrototypeOf(gp) === Array.prototype, gp instanceof Array, Array.prototype.isPrototypeOf(gp)].join());
const en = new Proxy(new Proxy({ e: 1, f: 2 }, { getOwnPropertyDescriptor(t, k) { const d = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'e') d.enumerable = false; return d; } }), {});
T('inner gOPD trap', () => Object.keys(en).join() + ' ' + JSON.stringify(en) + ' ' + Object.prototype.propertyIsEnumerable.call(en, 'e'));
''')
