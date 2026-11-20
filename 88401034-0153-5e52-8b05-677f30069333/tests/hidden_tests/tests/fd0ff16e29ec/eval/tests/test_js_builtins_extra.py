"""Built-ins, extra coverage (core library): TypedArray accessor brand checks, GetPrototypeFromConstructor
fallbacks (bound / proxy / mid-construct-revoked newTargets), Reflect.set/get receivers, proxy descriptor
invariants, integrity levels over proxies and TypedArrays, [[DefineOwnProperty]] corner cases, dead-result
RegExp fast paths and legacy RegExp statics, String methods whose Symbol.* hook is nulled, Promise
combinators with misbehaving thenables (including the keyed combinators), Iterator.concat/zip re-entrancy,
generic Array methods on array-likes, generator states, Map/Set hash-collision chains, JSON edge cases,
numeric/BigInt corners, Array.fromAsync / AsyncDisposableStack, and ShadowRealm.

Every program prints labelled lines (results, or exact error name + message) compared to a golden; the
engine-heavy programs run under all three execution tiers, which must agree. Temporal/Intl corner cases
live in test_js_builtins_extra_2.py.
"""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

PROG_TA_GETTERS_REALM = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, String(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
// TA getters via the %TypedArray% prototype descriptors
const TAP = Object.getPrototypeOf(Int8Array.prototype);
const ta = new Int16Array(new ArrayBuffer(16), 4, 3);
for (const k of ['length','byteLength','byteOffset','buffer']) {
  const g = Object.getOwnPropertyDescriptor(TAP, k).get;
  tryit('ta.' + k, () => { const v = g.call(ta); return v instanceof ArrayBuffer ? 'AB' + v.byteLength : v; });
  tryit('ta.' + k + ' bad', () => g.call({}));
}
// regexp/array construct with weird newTarget
function F() {} F.prototype = 1;
tryit('re F', () => Object.getPrototypeOf(Reflect.construct(RegExp, ['a'], F)) === RegExp.prototype);
const bound = function(){}.bind(null);
tryit('re bound', () => Object.getPrototypeOf(Reflect.construct(RegExp, ['a'], bound)) === RegExp.prototype);
tryit('arr bound', () => Object.getPrototypeOf(Reflect.construct(Array, [3], bound)) === Array.prototype);
const pf = new Proxy(function(){}, { get(t, k) { return k === 'prototype' ? null : t[k]; } });
tryit('arr proxy', () => Object.getPrototypeOf(Reflect.construct(Array, [], pf)) === Array.prototype);
tryit('re proxy', () => Object.getPrototypeOf(Reflect.construct(RegExp, ['x'], pf)) === RegExp.prototype);
tryit('num proxy', () => Object.getPrototypeOf(Reflect.construct(Number, [5], pf)) === Number.prototype);
tryit('str bound', () => Object.getPrototypeOf(Reflect.construct(String, ['s'], bound)) === String.prototype);
tryit('bool bound', () => Object.getPrototypeOf(Reflect.construct(Boolean, [1], bound)) === Boolean.prototype);
tryit('err bound', () => Object.getPrototypeOf(Reflect.construct(TypeError, ['m'], bound)) === TypeError.prototype);
tryit('map bound', () => Object.getPrototypeOf(Reflect.construct(Map, [], bound)) === Map.prototype);
tryit('obj bound', () => Object.getPrototypeOf(Reflect.construct(Object, [], bound)) === Object.prototype);
tryit('fn bound', () => Object.getPrototypeOf(Reflect.construct(Function, [], bound)) === Function.prototype);
tryit('promise bound', () => Object.getPrototypeOf(Reflect.construct(Promise, [()=>{}], bound)) === Promise.prototype);
tryit('iter bound', () => { class I extends Iterator {} ; return Object.getPrototypeOf(Reflect.construct(Iterator, [], bound)) === Iterator.prototype; });
tryit('i8 bound', () => Object.getPrototypeOf(Reflect.construct(Int8Array, [2], bound)) === Int8Array.prototype);
{
  const { proxy, revoke } = Proxy.revocable(function(){}, { get(t, k) { revoke(); return undefined; } });
  tryit('re revoked', () => Reflect.construct(RegExp, ['a'], proxy));
  const r2 = Proxy.revocable(function(){}, { get(t, k) { r2.revoke(); return undefined; } });
  tryit('arr revoked', () => Reflect.construct(Array, [], r2.proxy));
}
console.log(out.join('\n'));
"""

PROG_REFLECT_INTEGRITY = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, String(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const trace = [];
const mkTracing = (target, extra = {}) => new Proxy(target, Object.assign({
  defineProperty(t, k, d) { trace.push('def:' + String(k) + ':' + JSON.stringify(d)); return Reflect.defineProperty(t, k, d); },
  getOwnPropertyDescriptor(t, k) { trace.push('gopd:' + String(k)); return Reflect.getOwnPropertyDescriptor(t, k); },
  ownKeys(t) { trace.push('keys'); return Reflect.ownKeys(t); },
}, extra));
// Reflect.set with a proxy on the chain / proxy receivers / typed array receivers
const p = mkTracing({ x: 1 });
const child = Object.create(p);
const recv = {};
tryit('set via proto proxy', () => Reflect.set(child, 'y', 2, recv) + ' ' + JSON.stringify(recv));
const accRecv = new Proxy({}, { getOwnPropertyDescriptor() { return { get() {}, configurable: true }; } });
tryit('set recv accessor', () => Reflect.set({}, 'q', 1, accRecv));
const roRecv = new Proxy({}, { getOwnPropertyDescriptor() { return { value: 1, writable: false, configurable: true }; } });
tryit('set recv readonly', () => Reflect.set({}, 'q', 1, roRecv));
const ta = new Uint8Array(2);
tryit('set ta recv in range', () => Reflect.set({}, '1', 300, ta) + ' ' + ta[1]);
tryit('set ta recv out of range', () => Reflect.set({}, '5', 7, ta) + ' ' + ta.length);
tryit('set ta recv -0', () => Reflect.set({}, '-0', 7, ta));
tryit('get setter-only', () => Reflect.get(Object.defineProperty({}, 'z', { set(v) {} }), 'z', {}));
tryit('get proxy chain recv', () => Reflect.get(Object.create(new Proxy({}, { get(t, k, r) { return r === recv ? 'recv-ok' : 'bad'; } })), 'w', recv));
// delete through proxies in array mutators
const noDel = new Proxy([1, 2, 3], { deleteProperty() { return false; } });
tryit('pop noDel', () => Array.prototype.pop.call(noDel));
tryit('shift noDel', () => Array.prototype.shift.call(noDel));
tryit('splice noDel', () => Array.prototype.splice.call(noDel, 0, 1));
// defineProperties with proxies
trace.length = 0;
const tgt = mkTracing({});
tryit('defineProperties on proxy', () => JSON.stringify(Object.getOwnPropertyDescriptors(Object.defineProperties(tgt, { a: { value: 1, enumerable: true }, b: { get() { return 2; } } }))));
log('trace', trace.join(' '));
const propsProxy = new Proxy({ a: { value: 1 }, b: { value: 2 } }, { getOwnPropertyDescriptor(t, k) { return k === 'a' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); } });
tryit('defineProperties props proxy', () => JSON.stringify(Object.getOwnPropertyNames(Object.defineProperties({}, propsProxy))));
const rejecting = new Proxy({}, { defineProperty() { return false; } });
tryit('defineProperties rejecting', () => Object.defineProperties(rejecting, { a: { value: 1 } }));
// integrity levels with typed arrays and proxies
tryit('freeze ta', () => Object.freeze(new Uint8Array(2)));
tryit('freeze empty ta', () => Object.isFrozen(Object.freeze(new Uint8Array(0))));
tryit('seal ta', () => Object.seal(new Uint8Array(1)));
tryit('isFrozen ta', () => Object.isFrozen(Object.preventExtensions(new Uint8Array(1))));
tryit('isSealed ta', () => Object.isSealed(Object.preventExtensions(new Uint8Array(1))));
tryit('isFrozen empty ta', () => Object.isFrozen(Object.preventExtensions(new Uint8Array(0))));
trace.length = 0;
const fp = mkTracing({ a: 1, get b() { return 2; } });
tryit('freeze proxy', () => Object.isFrozen(Object.freeze(fp)));
log('trace', trace.join(' '));
const pe = Object.preventExtensions({ a: 1 });
const weird = new Proxy(pe, { getOwnPropertyDescriptor(t, k) { return k === 'a' ? { value: 1, writable: true, configurable: false, enumerable: true } : undefined; } });
Object.defineProperty(pe, 'a', { configurable: false });
tryit('isFrozen writable proxy', () => Object.isFrozen(weird));
tryit('isSealed writable proxy', () => Object.isSealed(weird));
const ghost = new Proxy(Object.preventExtensions({}), { ownKeys() { return []; } });
tryit('isFrozen ghost', () => Object.isFrozen(ghost));
const sealedProxy = new Proxy(Object.seal({ a: 1 }), {});
tryit('isFrozen sealed proxy', () => Object.isFrozen(sealedProxy) + ' ' + Object.isSealed(sealedProxy));
const miss = new Proxy(Object.preventExtensions({}), { ownKeys() { return ['zz']; }, getOwnPropertyDescriptor() { return undefined; } });
tryit('isFrozen missing', () => Object.isFrozen(miss));
console.log(out.join('\n'));
"""

PROG_PROXY_INVARIANTS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, v === undefined ? 'undefined' : JSON.stringify(v)); } catch (e) { log(label, 'throws', e.name, e.message); } };
const gopd = Object.getOwnPropertyDescriptor;
tryit('gopd undefined allowed', () => gopd(new Proxy({ a: 1 }, { getOwnPropertyDescriptor() { return undefined; } }), 'a'));
tryit('gopd new on extensible', () => gopd(new Proxy({}, { getOwnPropertyDescriptor() { return { value: 1, configurable: true }; } }), 'x'));
const nc = Object.defineProperty({}, 'k', { value: 5, enumerable: true, writable: false, configurable: false });
tryit('gopd nonconfig same', () => gopd(new Proxy(nc, { getOwnPropertyDescriptor() { return { value: 5, enumerable: true, configurable: false, writable: false }; } }), 'k'));
tryit('gopd nonconfig diff enum', () => gopd(new Proxy(nc, { getOwnPropertyDescriptor() { return { value: 5, enumerable: false, configurable: false }; } }), 'k'));
tryit('gopd nonconfig diff value', () => gopd(new Proxy(nc, { getOwnPropertyDescriptor() { return { value: 6, configurable: false }; } }), 'k'));
tryit('gopd nonconfig writable', () => gopd(new Proxy(nc, { getOwnPropertyDescriptor() { return { value: 5, writable: true, configurable: false }; } }), 'k'));
tryit('gopd nonconfig accessor shape', () => gopd(new Proxy(nc, { getOwnPropertyDescriptor() { return { get() {}, configurable: false }; } }), 'k'));
tryit('gopd report nonconfig missing', () => gopd(new Proxy({}, { getOwnPropertyDescriptor() { return { value: 1, configurable: false }; } }), 'z'));
tryit('gopd report nonconfig on config', () => gopd(new Proxy({ z: 1 }, { getOwnPropertyDescriptor() { return { value: 1, configurable: false }; } }), 'z'));
tryit('gopd report nonwritable on writable', () => { const t = Object.defineProperty({}, 'w', { value: 1, writable: true, configurable: false }); return gopd(new Proxy(t, { getOwnPropertyDescriptor() { return { value: 1, writable: false, configurable: false }; } }), 'w'); });
const setterOnly = Object.defineProperty({}, 's', { set(v) {}, configurable: false });
tryit('gopd accessor setter mismatch', () => gopd(new Proxy(setterOnly, { getOwnPropertyDescriptor() { return { set() {}, configurable: false }; } }), 's'));
tryit('gopd accessor get undefined', () => typeof gopd(new Proxy(setterOnly, { getOwnPropertyDescriptor(t, k) { const d = Reflect.getOwnPropertyDescriptor(t, k); return { get: undefined, set: d.set, configurable: false }; } }), 's').set);
tryit('gopd trap non-object', () => gopd(new Proxy({}, { getOwnPropertyDescriptor() { return 5; } }), 'q'));
tryit('gopd trap noncallable', () => gopd(new Proxy({}, { getOwnPropertyDescriptor: 7 }), 'q'));
tryit('keys gopd undefined', () => Object.keys(new Proxy({ a: 1, b: 2 }, { getOwnPropertyDescriptor(t, k) { return k === 'a' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); } })));
tryit('entries proxy', () => Object.entries(new Proxy({ a: 1, b: 2 }, { getOwnPropertyDescriptor(t, k) { const d = Reflect.getOwnPropertyDescriptor(t, k); if (k === 'b') d.enumerable = false; return d; } })));
tryit('define trap throws', () => Object.defineProperty(new Proxy({}, { defineProperty() { throw new EvalError('dp'); } }), 'a', { value: 1 }));
tryit('define trap false', () => [Reflect.defineProperty(new Proxy({}, { defineProperty() { return false; } }), 'a', { value: 1 })]);
tryit('define nonconfig accessor ok', () => { const t = Object.defineProperty({}, 'acc', { set: undefined, get: undefined, configurable: false }); return Reflect.defineProperty(new Proxy(t, { defineProperty(tt, k, d) { return true; } }), 'acc', { set: undefined, configurable: false }); });
tryit('define nonconfig accessor bad', () => { const g = () => 1; const t = Object.defineProperty({}, 'acc', { get: g, configurable: false }); return Object.defineProperty(new Proxy(t, { defineProperty() { return true; } }), 'acc', { get: () => 2, configurable: false }); });
tryit('define nonconfig enum mismatch', () => { const t = Object.defineProperty({}, 'p', { value: 1, enumerable: true, configurable: false }); return Object.defineProperty(new Proxy(t, { defineProperty() { return true; } }), 'p', { enumerable: false }); });
tryit('define report nonconfig missing', () => Object.defineProperty(new Proxy({}, { defineProperty() { return true; } }), 'n', { value: 1, configurable: false }));
tryit('define nonextensible new', () => Object.defineProperty(new Proxy(Object.preventExtensions({}), { defineProperty() { return true; } }), 'n', { value: 1 }));
tryit('define nonwritable report', () => { const t = Object.defineProperty({}, 'w', { value: 1, writable: true, configurable: false }); return Object.defineProperty(new Proxy(t, { defineProperty() { return true; } }), 'w', { value: 1, writable: false, configurable: false }); });
tryit('filter species proxy throws', () => { const a = [1, 2]; a.constructor = { [Symbol.species]: function () { return new Proxy({}, { defineProperty() { throw new URIError('species dp'); } }); } }; return a.filter(() => true); });
tryit('setPrototypeOf through proxy chain', () => { const o = {}; const mid = Object.create(new Proxy({}, {})); Object.setPrototypeOf(o, mid); return Object.getPrototypeOf(o) === mid; });
tryit('setPrototypeOf cycle', () => { const a = {}; const b = Object.create(a); return Reflect.setPrototypeOf(a, b); });
tryit('preventExtensions rab ta', () => { const rab = new ArrayBuffer(4, { maxByteLength: 8 }); return [Reflect.preventExtensions(new Uint8Array(rab, 0, 2)), Reflect.preventExtensions(new Uint8Array(rab)), Reflect.preventExtensions(new Uint8Array(new ArrayBuffer(4))), Reflect.preventExtensions(new Uint8Array(new SharedArrayBuffer(4, { maxByteLength: 8 }), 0, 2))]; });
tryit('preventExtensions rab ta throws', () => Object.preventExtensions(new Uint8Array(new ArrayBuffer(4, { maxByteLength: 8 }))));
tryit('seal rab ta', () => Object.seal(new Uint8Array(new ArrayBuffer(0, { maxByteLength: 8 }), 0, 0)));
tryit('ta getters oob', () => { const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const ta = new Uint16Array(rab, 4, 2); rab.resize(2); const P = Object.getPrototypeOf(Uint8Array.prototype); return ['length', 'byteLength', 'byteOffset'].map(k => Object.getOwnPropertyDescriptor(P, k).get.call(ta)).concat([ta.length, ta.byteOffset, ta.byteLength]); });
tryit('ta values expandos', () => { const ta = new Uint8Array([1, 2]); ta.vis = 'v'; Object.defineProperty(ta, 'hid', { value: 'h', enumerable: false }); return [Object.values(ta), Object.entries(ta), Object.keys(ta)]; });
console.log(out.join('\n'));
"""

PROG_REGEXP_DEAD = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
function stat() { return [RegExp.lastMatch, RegExp['$1'], RegExp.leftContext, RegExp.rightContext].join('|'); }
// dead-result global literal replace/match in hot functions
function deadReplace(s) { s.replace(/(a+)/g, 'x'); return stat(); }
function deadReplaceEmpty(s) { s.replace(/(b*)/g, 'x'); return stat(); }
function deadMatch(s) { s.match(/(o+)/g); return stat(); }
function deadMatchEmpty(s) { s.match(/(z*)/g); return stat(); }
const rs = [];
for (let k = 0; k < 300; k++) {
  rs.push(deadReplace('baa-aaa' + (k % 3)), deadReplaceEmpty('abbc' + (k % 2)), deadMatch('foo boooo' + (k % 4)), deadMatchEmpty('qz' + (k % 2)));
}
log('replace', [...new Set(rs)].join(' ; '));
// dead-result exec with odd lastIndex values
function deadExec(re, s) { re.exec(s); return re.lastIndex + ':' + stat(); }
const res2 = [];
for (let k = 0; k < 300; k++) {
  const g = /(\d)/g; g.lastIndex = [1.5, -1, '2', 0, 3][k % 5];
  res2.push(deadExec(g, 'a1b2c3d4'));
  const frozen = /(\w)/y; Object.defineProperty(frozen, 'lastIndex', { writable: false, value: 1 });
  try { deadExec(frozen, 'xyz'); } catch (e) { res2.push(e.name); }
}
log('exec', [...new Set(res2)].join(' ; '));
// dead-result replace with a variable regexp and various customizations
function deadReplVar(s, re, r) { s.replace(re, r); return re.lastIndex + ':' + stat(); }
const res3 = [];
for (let k = 0; k < 300; k++) {
  const plain = /(c)/g; res3.push('plain=' + deadReplVar('abcabc', plain, 'Z'));
  const own = /(c)/g; own.exec = function (s) { return null; }; res3.push('ownexec=' + deadReplVar('acc', own, 'Z'));
  const sticky = /(a)/y; sticky.lastIndex = 'x'; res3.push('sticky=' + deadReplVar('aaa', sticky, 'Z'));
  res3.push('nonstr=' + deadReplVar('abc', /(b)/, 5));
  res3.push('strsearch=' + (() => { 'abc'.replace('b', 'Q'); return stat(); })());
}
log('replvar', [...new Set(res3)].join(' ; '));
console.log(out.join('\n'));
"""

PROG_REGEXP_LITERAL_DEAD = r"""var subjects = ['baa-aaa', 'xaay', 'nothing', 'aaaaz', 'qq'];
var empties = ['abbc', 'zzz', ''];
function stat() { return [RegExp.lastMatch, RegExp['$1'], RegExp.leftContext, RegExp.rightContext].join('|'); }
function f() { const r = []; for (let i = 0; i < subjects.length; i++) { subjects[i].replace(/(a+)/g, 'x'); r.push(stat()); } return r.join(','); }
function g() { const r = []; for (let i = 0; i < empties.length; i++) { empties[i].replace(/(b*)/g, 'x'); r.push(stat()); } return r.join(','); }
function h() { const r = []; for (let i = 0; i < subjects.length; i++) { subjects[i].match(/(a+)/g); r.push(stat()); } return r.join(','); }
function m() { const r = []; for (let i = 0; i < empties.length; i++) { empties[i].match(/(z*)/g); r.push(stat()); } return r.join(','); }
function e() { const r = []; for (let i = 0; i < subjects.length; i++) { /(a)(a)?/.exec(subjects[i]); r.push(stat()); } return r.join(','); }
const all = new Set();
for (let k = 0; k < 200; k++) { all.add('f=' + f()); all.add('g=' + g()); all.add('h=' + h()); all.add('m=' + m()); all.add('e=' + e()); }
console.log([...all].join('\n'));
"""

PROG_STRING_SYMBOL_HOOKS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
// regexps whose Symbol.* methods are nulled/undefined fall back to string coercion
const nulled = (re, sym, v) => Object.defineProperty(re, sym, { value: v });
tryit('split null', () => 'a,b,,c'.split(nulled(/(,)/, Symbol.split, null)));
tryit('split null limit', () => 'a1b2c3d'.split(nulled(/(\d)/, Symbol.split, undefined), 4));
tryit('split null empty', () => 'abc'.split(nulled(/(?:)/, Symbol.split, null)));
tryit('split null empty u', () => '😀x😀'.split(nulled(/(?:)/u, Symbol.split, null)));
tryit('split null zero', () => 'a-b'.split(nulled(/-/, Symbol.split, null), 0));
tryit('split null nomatch', () => 'abc'.split(nulled(/z(q)?/, Symbol.split, null)));
tryit('split null groups', () => 'x1y'.split(nulled(/(\d)|(z)/, Symbol.split, null)));
tryit('split null limit groups', () => 'a1b2c'.split(nulled(/(\d)(.)?/, Symbol.split, null), 2));
tryit('replace undef', () => 'a/b/c'.replace(nulled(/b/, Symbol.replace, undefined), 'X'));
tryit('replaceAll undef', () => 'x/a/y/a/'.replaceAll(nulled(/a/g, Symbol.replace, undefined), '-'));
tryit('match null', () => 'p/q/r'.match(nulled(/q/, Symbol.match, null)));
tryit('matchAll null', () => [...'z/q/g/q/g'.matchAll(nulled(/q/g, Symbol.matchAll, null))].map(m => m.index));
tryit('search null', () => 'aa/x/'.search(nulled(/x/, Symbol.search, null)));
tryit('replace noncallable', () => 'abc'.replace({ [Symbol.replace]: 1 }, ''));
tryit('replaceAll noncallable', () => 'abc'.replaceAll({ [Symbol.replace]: 'nope' }, ''));
tryit('split noncallable', () => 'abc'.split({ [Symbol.split]: {} }));
tryit('match noncallable', () => 'abc'.match({ [Symbol.match]: 2 }));
tryit('matchAll noncallable', () => 'abc'.matchAll({ [Symbol.matchAll]: 3 }));
tryit('search noncallable', () => 'abc'.search({ [Symbol.search]: true }));
tryit('custom splitter', () => 'abc'.split({ [Symbol.split](s, lim) { return [s, lim, this.tag]; }, tag: 'T' }, 7));
tryit('custom replacer', () => 'abc'.replaceAll({ [Symbol.replace](s, r) { return s + '|' + r; } }, 'R'));
tryit('substr edge', () => ['abcdef'.substr(-3, 2), 'abcdef'.substr(-10, 2), 'abcdef'.substr(2, NaN), 'abcdef'.substr(1, -1), 'abcdef'.substr(NaN), 'abcdef'.substr(4, Infinity)]);
tryit('at edge', () => ['abc'.at(-4), 'abc'.at(3), 'abc'.at(-1), 'abc'.at(NaN), 'abc'.at(1.9)]);
tryit('fromCharCode odd', () => String.fromCharCode(65.9, -1, 65536 + 66, NaN, Infinity).split('').map(c => c.charCodeAt(0)));
tryit('concat many', () => ''.concat(1, null, undefined, {}, [2, 3]));
tryit('codePointAt surrogates', () => ['😀'.codePointAt(0), '😀'.codePointAt(1), '\ud83d'.codePointAt(0), 'a\ude00'.codePointAt(1), 'x'.codePointAt(5)]);
tryit('iter surrogates', () => [...'a😀\ud800b\udc00'].map(c => c.length));
console.log(out.join('\n'));
"""

PROG_PROMISE_COMBINATORS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const desc = e => e instanceof Error ? e.name + ': ' + e.message + (e.errors ? ' errors=' + JSON.stringify(e.errors) : '') : 'raw ' + JSON.stringify(e);
const keysOf = v => v !== null && typeof v === 'object' ? Reflect.ownKeys(v).map(String).join(',') + (Object.getPrototypeOf(v) === null ? ' nullproto' : ' proto') : typeof v;
const show = (label, p) => p.then(v => log(label, 'ok', JSON.stringify(v, (k, x) => x instanceof Error ? desc(x) : x), keysOf(v)), e => log(label, 'err', desc(e)));
class C extends Promise { static resolve(v) { return v; } }
const twice = { then(f, r) { f('one'); f('two'); r('three'); } };
const settledTwice = { then(f, r) { r('r1'); r('r2'); f('f1'); } };
show('keyed twice', C.allKeyed({ a: twice, b: { then(f) { f('b'); } } }));
show('keyedSettled twice', C.allSettledKeyed({ a: settledTwice, b: twice }));
show('all twice', C.all([twice, { then(f) { f('x'); } }]));
show('all twice ok', C.all([{ then(f) { f('one'); f('two'); } }, { then(f) { f('x'); } }]));
show('allSettled twice', C.allSettled([{ then(f, r) { f(1); f(2); r(3); } }, { then(f, r) { r(9); r(10); f(11); } }]));
show('any twice', C.any([{ then(f, r) { r(1); r(2); f(3); } }]));
show('any rejects', C.any([{ then(f, r) { r(1); r(2); } }, { then(f, r) { r('b'); } }]));
class BadResolve extends Promise {} BadResolve.resolve = 5;
show('keyed bad resolve', BadResolve.allKeyed({ a: 1 }));
show('all bad resolve', BadResolve.all([1]));
show('keyed throwing proxy', Promise.allKeyed(new Proxy({ a: 1 }, { ownKeys() { throw new RangeError('no keys'); } })));
show('keyed proxy', Promise.allKeyed(new Proxy({ a: 1, b: 2, [Symbol('s')]: 3 }, {})));
const hidden = Object.defineProperty({ v: 1 }, 'h', { value: 2, enumerable: false });
const sym = Symbol('k');
show('keyed sym+hidden', Promise.allKeyed({ ...hidden, [sym]: Promise.resolve('S'), z: 'zz' , h2: hidden.h}));
show('keyed getter throws', Promise.allKeyed({ get a() { throw new TypeError('getter'); } }));
class ThenThrows extends Promise { static resolve(v) { return { get then() { throw new EvalError('then getter'); } }; } }
show('keyed then getter throws', ThenThrows.allKeyed({ a: 1 }));
class ThenCallThrows extends Promise { static resolve(v) { return { then() { throw new URIError('then call'); } }; } }
show('keyed then call throws', ThenCallThrows.allSettledKeyed({ a: 1 }));
class ResolveThrows extends Promise { static resolve(v) { throw new SyntaxError('resolve throws'); } }
show('keyed resolve throws', ResolveThrows.allKeyed({ a: 1 }));
show('keyed non-object', Promise.allKeyed(42));
show('keyed empty', Promise.allKeyed({}));
show('settled mix', Promise.allSettledKeyed({ ok: Promise.resolve(1), bad: Promise.reject(new Error('nope')), plain: 3 }));
// capability whose resolve throws: rejection is routed to reject
let rejected = null;
function Cap(exec) { exec(v => { throw new Error('resolve boom'); }, e => { rejected = e; }); }
Cap.resolve = v => v;
Promise.allKeyed.call(Cap, {});
log('cap resolve throws ->', rejected && rejected.message);
setTimeout(() => console.log(out.sort().join('\n')), 0);
"""

PROG_ITERATOR_REENTRANCY = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, String(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const mkIt = (name, n, extra = {}) => ({
  [Symbol.iterator]() {
    let k = 0;
    return Object.assign({
      next() { k++; log(name + '.next', k); return k <= n ? { value: name + k, done: false } : { value: undefined, done: true }; },
      return() { log(name + '.return'); return {}; },
    }, extra);
  }
});
// Iterator.concat: re-entrant return during the inner close
{
  let cc;
  const inner = mkIt('in', 3, { return() { log('inner.return'); try { cc.return(); } catch (e) { log('nested', e.name, e.message); } return {}; } });
  cc = Iterator.concat(inner);
  tryit('cc.next', () => JSON.stringify(cc.next()));
  tryit('cc.return', () => JSON.stringify(cc.return()));
  tryit('cc.next after', () => JSON.stringify(cc.next()));
}
// helper re-entrancy
{
  let h;
  h = [1, 2, 3].values().map(x => { try { h.return(); } catch (e) { log('helper nested', e.name, e.message); } return x * 10; });
  tryit('h.next', () => JSON.stringify(h.next()));
  let h2; h2 = [1, 2].values().filter(x => { try { h2.next(); } catch (e) { log('helper next nested', e.name, e.message); } return true; });
  tryit('h2.next', () => JSON.stringify(h2.next()));
}
// zip: return when finished / running / strict mismatch errors
{
  const z = Iterator.zip([[1, 2], [3, 4]]);
  tryit('z all', () => JSON.stringify([...z]));
  tryit('z.return finished', () => JSON.stringify(z.return()));
  let z2;
  z2 = Iterator.zip([mkIt('a', 2, { next() { try { z2.return(); } catch (e) { log('zip nested return', e.name, e.message); } try { z2.next(); } catch (e) { log('zip nested next', e.name, e.message); } return { value: 'a', done: false }; } })]);
  tryit('z2.next', () => JSON.stringify(z2.next()));
  const s1 = Iterator.zip([[], { [Symbol.iterator]() { return { next: 5, return() { log('s1 ret'); return {}; } }; } }], { mode: 'strict' });
  tryit('strict next not fn', () => JSON.stringify(s1.next()));
  const s2 = Iterator.zip([[], { [Symbol.iterator]() { return { next() { return 7; }, return() { log('s2 ret'); return {}; } }; } }], { mode: 'strict' });
  tryit('strict result non-object', () => JSON.stringify(s2.next()));
  const s3 = Iterator.zip([[], { [Symbol.iterator]() { return { next() { throw new RangeError('boom'); }, return() { log('s3 ret'); return {}; } }; } }], { mode: 'strict' });
  tryit('strict next throws', () => JSON.stringify(s3.next()));
  const s4 = Iterator.zip([[1], [2, 3]], { mode: 'strict' });
  tryit('strict mismatch', () => JSON.stringify([...s4]));
  const s5 = Iterator.zip([[1], [2]], { mode: 'strict' });
  tryit('strict ok', () => JSON.stringify([...s5]));
}
// zip longest padding edge cases
{
  tryit('pad iter throws', () => Iterator.zip([mkIt('p', 1)], { mode: 'longest', padding: { [Symbol.iterator]() { throw new TypeError('no pad'); } } }));
  tryit('pad short', () => JSON.stringify([...Iterator.zip([[1], [2, 3], [4, 5, 6]], { mode: 'longest', padding: ['x'] })]));
  tryit('pad close throws', () => Iterator.zip([mkIt('q', 1)], { mode: 'longest', padding: { [Symbol.iterator]() { return { next() { return { value: 'P', done: false }; }, return() { throw new SyntaxError('pad close'); } }; } } }));
  tryit('pad next throws', () => Iterator.zip([mkIt('r', 1)], { mode: 'longest', padding: { [Symbol.iterator]() { return { next() { throw new EvalError('pad next'); } }; } } }));
  tryit('keyed pad getter throws', () => Iterator.zipKeyed({ a: [1] }, { mode: 'longest', padding: { get a() { throw new URIError('pad get'); } } }));
  tryit('keyed longest', () => JSON.stringify([...Iterator.zipKeyed({ a: [1, 2], b: [3] , 7: [9]}, { mode: 'longest', padding: { b: 'B' } })]));
  tryit('keyed gopd throws', () => Iterator.zipKeyed(new Proxy({ a: [1] }, { getOwnPropertyDescriptor() { throw new Error('gopd'); } })));
  tryit('keyed proxy skip', () => JSON.stringify([...Iterator.zipKeyed(new Proxy({ a: [1], b: [2] }, { getOwnPropertyDescriptor(t, k) { return k === 'a' ? undefined : Reflect.getOwnPropertyDescriptor(t, k); } }))]));
  tryit('keyed get throws', () => Iterator.zipKeyed({ get a() { throw new Error('get a'); } }));
  tryit('keyed open fails', () => Iterator.zipKeyed({ a: mkIt('k', 1), b: 5 }));
  tryit('zip open fails', () => Iterator.zip([mkIt('m', 1), 5]));
  const symk = Symbol('sk');
  tryit('keyed sym', () => { const r = Iterator.zipKeyed({ [symk]: [1], x: [2] }).next().value; return Reflect.ownKeys(r).map(String).join(',') + ' proto=' + Object.getPrototypeOf(r); });
}
console.log(out.join('\n'));
"""

PROG_ARRAY_GENERIC = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, String(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const AP = Array.prototype;
const al = { length: 3, 0: 'a', 1: 'b', 2: 'c' };
const boom = () => { throw new RangeError('cb'); };
for (const m of ['forEach', 'map', 'filter', 'some', 'every', 'find', 'findIndex', 'findLast', 'findLastIndex', 'flatMap', 'reduce', 'reduceRight']) {
  tryit(m + ' throws', () => m.startsWith('reduce') ? AP[m].call(al, boom, 0) : AP[m].call(al, boom));
}
tryit('map huge', () => AP.map.call({ length: 2 ** 32 }, x => x));
tryit('filter huge species', () => { const a = []; a.constructor = { [Symbol.species]: function (n) { return { length: 0 }; } }; return JSON.stringify(AP.filter.call(a, x => x)); });
tryit('species undefined ctor', () => { const a = [1, 2]; a.constructor = undefined; return Array.isArray(a.map(x => x)); });
tryit('species null', () => { const a = [1, 2]; a.constructor = { [Symbol.species]: null }; return Array.isArray(a.map(x => x * 2)) + ' ' + a.map(x => x * 2); });
tryit('species non-object ctor', () => { const a = [1]; a.constructor = 5; return a.map(x => x); });
tryit('indexOf +Inf', () => AP.indexOf.call(al, 'a', Infinity));
tryit('lastIndexOf -Inf', () => AP.lastIndexOf.call(al, 'a', -Infinity));
tryit('flat Infinity', () => JSON.stringify(AP.flat.call({ length: 2, 0: [1, [2, [3, [4]]]], 1: 5 }, Infinity)));
tryit('toString bool', () => AP.toString.call(new Boolean(true)));
tryit('toString num', () => AP.toString.call(new Number(1)));
tryit('toString nojoin array', () => AP.toString.call(Object.assign([1, 2], { join: null })));
tryit('toString tagged', () => AP.toString.call({ join: 1, [Symbol.toStringTag]: 'Tagged' }));
tryit('toString proxy array', () => AP.toString.call(new Proxy(Object.assign([1], { join: 0 }), {})));
tryit('Array.of non-ctor', () => JSON.stringify(Array.of.call(undefined, 1, 2)));
tryit('Array.of frozen', () => Array.of.call(function () { return Object.freeze({}); }, 1));
tryit('Array.from non-ctor arraylike', () => JSON.stringify(Array.from.call(undefined, { length: 2, 0: 'x' })));
tryit('Array.from non-ctor iterable', () => JSON.stringify(Array.from.call({}, new Set([1, 2]))));
tryit('Array.from mapper throws', () => Array.from({ length: 2 }, boom));
tryit('Array.from huge non-ctor', () => Array.from.call(undefined, { length: 2 ** 32 }));
tryit('concat spreadable', () => JSON.stringify([0].concat({ [Symbol.isConcatSpreadable]: true, length: 2, 0: 'p', 1: 'q' }, Object.assign([9], { [Symbol.isConcatSpreadable]: false }))));
tryit('concat too long', () => [].concat([7], { [Symbol.isConcatSpreadable]: true, length: 2 ** 53 - 1 }));
tryit('fill huge', () => { const a = []; a.length = 2 ** 31; return a.fill(0); });
tryit('toSpliced huge', () => AP.toSpliced.call({ length: 2 ** 40 }, 0, 0));
tryit('toSpliced too long', () => AP.toSpliced.call({ length: 2 ** 53 - 1 }, 0, 0, 1));
tryit('unshift generic', () => { const o = { length: 2, 0: 'a', 1: 'b' }; const n = AP.unshift.call(o, 'x', 'y'); return n + ' ' + JSON.stringify(o); });
tryit('unshift holes', () => { const o = { length: 3, 0: 'a', 2: 'c' }; AP.unshift.call(o, 'z'); return JSON.stringify(o); });
tryit('splice generic', () => { const o = { length: 4, 0: 1, 1: 2, 2: 3, 3: 4 }; const r = AP.splice.call(o, 1, 2, 'n'); return JSON.stringify(r) + JSON.stringify(o); });
tryit('splice frozen len', () => { const o = Object.defineProperty({ 0: 1 }, 'length', { value: 1, writable: false }); return AP.splice.call(o, 0, 1); });
tryit('push frozen arr', () => AP.push.call(Object.freeze([1]), 2));
tryit('push len nonwritable', () => { const a = [1]; Object.defineProperty(a, 'length', { writable: false }); return a.push(2); });
tryit('flatMap proxy target', () => JSON.stringify(AP.flatMap.call(new Proxy([1, [2]], {}), x => x)));
tryit('lookupGetter proxy', () => { const g = () => 1; const p = new Proxy(Object.create({ get k() { return 1; } }), {}); return typeof Object.prototype.__lookupGetter__.call(p, 'k') + ' ' + Object.prototype.__lookupSetter__.call(new Proxy({}, { getOwnPropertyDescriptor() { return { value: 1, configurable: true }; } }), 'z'); });
tryit('lookupGetter plain chain', () => { const o = Object.create(Object.create({ set s(v) {} })); return typeof o.__lookupSetter__('s') + ' ' + o.__lookupGetter__('s') + ' ' + o.__lookupGetter__('nope'); });
tryit('Object toString bool', () => Object.prototype.toString.call(new Boolean(false)) + Object.prototype.toString.call(Object.assign(new Number(1), { [Symbol.toStringTag]: 7 })));
tryit('groupBy throws', () => Object.groupBy([1], boom));
tryit('groupBy key throws', () => Object.groupBy([1], () => ({ toString() { throw new EvalError('key'); } })));
tryit('Map.groupBy', () => JSON.stringify([...Map.groupBy([1, 2, 3, 4], x => x % 2 ? 'odd' : 'even')]));
console.log(out.join('\n'));
"""

PROG_DEFINE_PROPERTY = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
function mapped(a, b) {
  Object.defineProperty(arguments, '0', { value: 'frozen', writable: false, configurable: false });
  const r1 = Reflect.defineProperty(arguments, '0', { value: 'changed' });
  const r2 = Reflect.defineProperty(arguments, '0', { value: 'frozen' });
  a = 'param';
  const r3 = Reflect.defineProperty(arguments, '1', { get() { return 'acc'; }, configurable: true });
  b = 'b2';
  return [r1, r2, arguments[0], a, r3, arguments[1], b];
}
tryit('mapped arguments define', () => mapped('x', 'y'));
function mapped2(a) { Object.defineProperty(arguments, '0', { value: 'v' }); a = 'later'; return [arguments[0], a]; }
tryit('mapped arguments value define', () => mapped2('orig'));
tryit('ta define no value', () => { const ta = new Uint8Array([7, 8]); return [Reflect.defineProperty(ta, '0', {}), Reflect.defineProperty(ta, '1', { writable: true, enumerable: true, configurable: true }), Reflect.defineProperty(ta, '0', { configurable: false }), Reflect.defineProperty(ta, '0', { get() {} }), Reflect.defineProperty(ta, '5', { value: 1 }), Reflect.defineProperty(ta, '-0', { value: 1 }), Reflect.defineProperty(ta, '1.5', { value: 1 }), [...ta]]; });
tryit('nonconfigurable redefine', () => { const o = {}; Object.defineProperty(o, 'x', { value: 1, enumerable: false, configurable: false, writable: true }); return [Reflect.defineProperty(o, 'x', { enumerable: false, value: 2 }), Reflect.defineProperty(o, 'x', { enumerable: true }), Reflect.defineProperty(o, 'x', { configurable: true }), Reflect.defineProperty(o, 'x', { get() {} }), Reflect.defineProperty(o, 'x', { writable: false }), Reflect.defineProperty(o, 'x', { writable: true }), Reflect.defineProperty(o, 'x', { value: 3 }), o.x]; });
tryit('nonconfigurable accessor redefine', () => { const g = () => 1; const o = {}; Object.defineProperty(o, 'y', { get: g, configurable: false }); return [Reflect.defineProperty(o, 'y', { get: g }), Reflect.defineProperty(o, 'y', { get: () => 2 }), Reflect.defineProperty(o, 'y', { set: undefined }), Reflect.defineProperty(o, 'y', { set() {} }), Reflect.defineProperty(o, 'y', { value: 1 })]; });
tryit('array length define', () => { const a = [1, 2, 3]; return [Reflect.defineProperty(a, 'length', { configurable: true }), Reflect.defineProperty(a, 'length', { enumerable: true }), Reflect.defineProperty(a, 'length', { get() {} }), Reflect.defineProperty(a, 'length', { value: 1 }), a.length, Reflect.defineProperty(a, 'length', { writable: false }), Reflect.defineProperty(a, 'length', { value: 5 }), Reflect.defineProperty(a, 'length', { value: 1 }), a.length]; });
tryit('array length define bad', () => Object.defineProperty([], 'length', { value: -1 }));
tryit('array length define coercion', () => { const a = [1, 2]; let n = 0; Object.defineProperty(a, 'length', { value: { valueOf() { n++; return 1; } } }); return [a.length, n]; });
function pushMax() { const a = []; a.length = 2 ** 32 - 1; let err = 'none'; for (let k = 0; k < 300; k++) { try { a.push(k); } catch (e) { err = e.name + ': ' + e.message; } } return [err, a.length, a[4294967295]]; }
tryit('push at max length', pushMax);
function popLoop() { const a = [1, 2, 3]; const r = []; for (let k = 0; k < 300; k++) { r.push(a.pop()); if (a.length === 0) a.push(k, k + 1); } return r.slice(0, 8).concat(r.length); }
tryit('pop loop', popLoop);
console.log(out.join('\n'));
"""

PROG_MISC_BUILTINS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const d = new Date(Date.UTC(2021, 4, 6, 7, 8, 9));
tryit('toLocaleString prim opts', () => d.toLocaleString('en', 5));
tryit('toLocaleDateString prim opts', () => d.toLocaleDateString('en', 'x'));
tryit('toLocaleTimeString prim opts', () => d.toLocaleTimeString('en', true));
tryit('toLocaleString tz only', () => d.toLocaleString('en', { timeZone: 'Asia/Tokyo' }));
tryit('toLocaleString hour only', () => d.toLocaleString('en', { hour: 'numeric', timeZone: 'UTC' }));
tryit('toLocaleDateString with time comp', () => d.toLocaleDateString('en', { hour: 'numeric', timeZone: 'UTC' }));
tryit('toLocaleTimeString with date comp', () => d.toLocaleTimeString('en', { year: 'numeric', timeZone: 'UTC' }));
tryit('toLocaleTimeString with dayPeriod', () => d.toLocaleTimeString('en', { dayPeriod: 'short', timeZone: 'UTC' }));
tryit('toLocaleTimeString with timeStyle', () => d.toLocaleTimeString('en', { timeStyle: 'short', timeZone: 'UTC' }));
// species constructor lookups
tryit('then ctor undefined', () => { const p = Promise.resolve(1); p.constructor = undefined; return p.then() instanceof Promise; });
tryit('then ctor prim', () => { const p = Promise.resolve(1); p.constructor = 5; return p.then(); });
tryit('finally ctor undefined', () => { const p = Promise.resolve(1); p.constructor = undefined; return p.finally() instanceof Promise; });
tryit('finally species null', () => { const p = Promise.resolve(1); p.constructor = { [Symbol.species]: null }; return p.finally(() => {}) instanceof Promise; });
tryit('ab slice ctor undefined', () => { const b = new ArrayBuffer(8); b.constructor = undefined; return b.slice(2).byteLength; });
tryit('ab slice ctor prim', () => { const b = new ArrayBuffer(8); b.constructor = 'x'; return b.slice(2); });
tryit('re split ctor undefined', () => { const r = /,/; r.constructor = undefined; return 'a,b'.split(r); });
tryit('re split species', () => { const r = /,/; r.constructor = { [Symbol.species]: function (src, fl) { log('species called', src, fl); return new RegExp(src, fl); } }; return 'a,b'.split(r); });
tryit('matchAll ctor undefined', () => { const r = /a/g; r.constructor = undefined; return [...'aa'.matchAll(r)].length; });
// flatMap/filter results through proxies / non-extensible species results
tryit('filter species frozen', () => { const a = [1, 2]; a.constructor = { [Symbol.species]: function () { return Object.freeze({}); } }; return a.filter(x => true); });
tryit('map species proxy', () => { const a = [1, 2]; const log2 = []; a.constructor = { [Symbol.species]: function (n) { return new Proxy([], { defineProperty(t, k, d) { log2.push(k); return Reflect.defineProperty(t, k, d); } }); } }; const r = a.map(x => x * 3); return [Array.from(r), log2]; });
tryit('flat species proxy reject', () => { const a = [[1], 2]; a.constructor = { [Symbol.species]: function (n) { return new Proxy([], { defineProperty() { return false; } }); } }; return a.flat(); });
tryit('splice species proxy reject', () => { const a = [1, 2, 3]; a.constructor = { [Symbol.species]: function (n) { return new Proxy({}, { defineProperty() { return false; } }); } }; return a.splice(0, 2); });
tryit('concat species proxy', () => { const a = [1]; a.constructor = { [Symbol.species]: function (n) { return new Proxy({}, { defineProperty(t, k, d) { return k !== '1' && Reflect.defineProperty(t, k, d); } }); } }; return a.concat([2]); });
tryit('slice species proxy ok', () => { const a = [1, 2, 3]; a.constructor = { [Symbol.species]: function (n) { return new Proxy({ length: 0 }, {}); } }; const r = a.slice(1); return [r[0], r[1], r.length]; });
tryit('some holes arraylike', () => { const seen = []; Array.prototype.some.call({ length: 3, 1: 'x' }, (v, k) => { seen.push(k); return false; }); return seen; });
tryit('every holes arraylike', () => { const seen = []; Array.prototype.every.call({ length: 4, 0: 1, 3: 2 }, (v, k) => { seen.push(k); return true; }); return seen; });
// zipKeyed with numeric-looking keys, receivers
tryit('zipKeyed key order', () => Reflect.ownKeys(Iterator.zipKeyed({ b: [1], '01': [2], '4294967295': [3], 2: [4], 1: [5], a: [6] }).next().value));
tryit('zip next bad recv', () => { const z = Iterator.zip([[1]]); return z.next.call(5); });
tryit('zip return bad recv', () => { const z = Iterator.zip([[1]]); return z.return.call({}); });
tryit('concat next bad recv', () => { const c = Iterator.concat([1]); return c.next.call(5); });
tryit('helper next bad recv', () => { const h = [1].values().map(x => x); return Object.getPrototypeOf(h).next.call(5); });
tryit('helper return bad recv', () => { const h = [1].values().map(x => x); return Object.getPrototypeOf(h).return.call({}); });
// locale casing
tryit('lt lower', () => ['Ì', 'Ì', 'J́', 'Į̃', 'I'].map(s => [...s.toLocaleLowerCase('lt')].map(c => c.codePointAt(0).toString(16)).join(' ')));
tryit('lt upper soft-dotted', () => ['i̇', 'j̇', 'ⅈ̇', '\u{1D422}̇', '\u{1D456}̇x', 'ḭ̇', 'í̇', '\u{1DF1A}̇', '\u{1E04C}̇', 'ị̇', 'i֢̇'].map(s => [...s.toLocaleUpperCase('lt')].map(c => c.codePointAt(0).toString(16)).join(' ')));
tryit('tr az casing', () => ['I', 'i', 'İ', 'İ'].map(s => s.toLocaleLowerCase('tr') + '/' + s.toLocaleUpperCase('az') + '/' + s.toLocaleLowerCase('az')));
tryit('split huge', () => 'x'.repeat(2 ** 20 + 1).split(''));
tryit('split huge sep', () => 'x'.repeat(2 ** 20 + 1).split('y').length);
tryit('substr wide', () => ['abcdef'.substr(-10, 12), 'abcdef'.substr(-3), 'abcdef'.substr(-7, 3)]);
tryit('toExponential pad', () => [(1).toExponential(5), (123.456).toExponential(20), (0.5).toExponential(25), (5e-324).toExponential(10), (1.5e300).toExponential(30), (-0).toExponential(3), (9.999).toExponential(2)]);
tryit('toPrecision pad', () => [(1).toPrecision(21), (123.456).toPrecision(30), (5e-324).toPrecision(5), (1e21).toPrecision(25)]);
tryit('toFixed', () => [(1.005).toFixed(2), (1e21).toFixed(2), (123.456).toFixed(20), (-1.5).toFixed(0), (0.000001).toFixed(7)]);
tryit('replace fn throws', () => 'abc'.replace('b', () => { throw new EvalError('repl'); }));
tryit('replaceAll fn throws', () => 'abcb'.replaceAll('b', () => { throw new URIError('replAll'); }));
tryit('replace fn args', () => 'xaby'.replace('ab', (...a) => JSON.stringify(a)));
tryit('replaceAll empty', () => 'abc'.replaceAll('', '-'));
tryit('at surrogate', () => ['a😀'.at(1).charCodeAt(0), 'a😀'.at(-1).charCodeAt(0)]);
console.log(out.join('\n'));
"""

PROG_ASYNC_BUILTINS = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const desc = e => e instanceof Error ? e.name + ': ' + e.message : 'raw ' + String(e);
const t = async (label, f) => { try { log(label, JSON.stringify(await f())); } catch (e) { log(label, 'rejects', desc(e)); } };
const asyncIt = (vals, extra = {}) => ({ [Symbol.asyncIterator]() { let k = 0; return Object.assign({ next() { return Promise.resolve(k < vals.length ? { value: vals[k++], done: false } : { done: true }); }, return() { log('async return called'); return Promise.resolve({ done: true }); } }, extra); } });
(async () => {
  await t('fromAsync nonctor async', () => Array.fromAsync.call(undefined, asyncIt([1, 2])));
  await t('fromAsync nonctor sync', () => Array.fromAsync.call({}, new Set(['a', Promise.resolve('b')])));
  await t('fromAsync nonctor arraylike', () => Array.fromAsync.call(undefined, { length: 2, 0: Promise.resolve('x'), 1: 'y' }));
  await t('fromAsync arraylike huge', () => Array.fromAsync.call(undefined, { length: 2 ** 32 }));
  await t('fromAsync ctor arraylike', () => Array.fromAsync.call(function C(n) { this.made = n; }, { length: 1, 0: 'q' }).then(r => [r.made, r[0], r.length]));
  await t('fromAsync mapper throws async', () => Array.fromAsync(asyncIt([1, 2]), () => { throw new RangeError('map'); }));
  await t('fromAsync mapper rejects sync', () => Array.fromAsync([1, 2], async () => { throw new EvalError('amap'); }));
  await t('fromAsync return throws', () => Array.fromAsync(asyncIt([1], { return() { throw new Error('ret'); } }), () => { throw new TypeError('map2'); }));
  await t('fromAsync return noncallable', () => Array.fromAsync(asyncIt([1], { return: 5 }), () => { throw new TypeError('map3'); }));
  await t('fromAsync bad mapfn', () => Array.fromAsync([1], 5));
  await t('fromAsync bad asyncIterator', () => Array.fromAsync({ [Symbol.asyncIterator]: 5 }));
  await t('fromAsync result non-object', () => Array.fromAsync({ [Symbol.asyncIterator]() { return { next() { return 5; } }; } }));
  await t('fromAsync frozen ctor', () => Array.fromAsync.call(function () { return Object.freeze([]); }, asyncIt([1])));
  await t('fromAsync thisArg', () => Array.fromAsync([1, 2], function (v, k) { return this.m * v + k; }, { m: 10 }));
  // AsyncDisposableStack misuse after disposal
  const ads = new AsyncDisposableStack();
  await ads.disposeAsync();
  for (const m of ['use', 'adopt', 'defer', 'move']) await t('ads.' + m + ' after dispose', () => ads[m](m === 'adopt' ? 1 : (() => {}), () => {}));
  const ads2 = new AsyncDisposableStack();
  ads2.adopt('v', async v => { log('adopt dispose', v); });
  ads2.defer(() => { throw new Error('sync defer'); });
  ads2.use({ [Symbol.asyncDispose]() { return { then(f, r) { r(new Error('bad thenable')); } }; } });
  ads2.use({ [Symbol.dispose]() { log('sync dispose used'); } });
  await t('ads2 dispose errors', () => ads2.disposeAsync());
  const ads3 = new AsyncDisposableStack();
  ads3.defer(() => 42);
  ads3.use({ get [Symbol.asyncDispose]() { return undefined; }, [Symbol.dispose]() { log('fallback sync dispose'); return 'ignored'; } });
  await t('ads3 dispose', () => ads3.disposeAsync());
  const ads4 = new AsyncDisposableStack();
  ads4.defer(() => { log('ads4 first-registered ran'); });
  ads4.defer(() => { const p = Promise.resolve('x'); Object.defineProperty(p, 'constructor', { get() { throw new RangeError('ctor getter'); } }); return p; });
  ads4.defer(() => { throw new TypeError('sync throw'); });
  await t('ads4 dispose', () => ads4.disposeAsync().catch(e => [e.name, e.error.name, e.error.message, e.suppressed.name, e.suppressed.message]));
  await t('ads4 suppressed', () => { const s = new AsyncDisposableStack(); s.defer(() => { throw new Error('inner'); }); s.defer(() => { throw new Error('outer'); }); return s.disposeAsync().catch(e => [e.name, e.error.message, e.suppressed.message]); });
  await t('ads after dispose disposed', async () => { const s = new AsyncDisposableStack(); await s.disposeAsync(); return [s.disposed, await s.disposeAsync()]; });
  await t('ads adopt noncallable', () => new AsyncDisposableStack().adopt(1, 5));
  await t('ads defer noncallable', () => new AsyncDisposableStack().defer(5));
  // FinalizationRegistry unregister
  const fr = new FinalizationRegistry(() => {});
  const tok = {};
  fr.register({}, 'h', tok);
  await t('fr unregister', () => [fr.unregister(tok), fr.unregister(tok), fr.unregister({}), new FinalizationRegistry(() => {}).unregister(Symbol('s'))]);
  await t('fr unregister bad', () => fr.unregister(1));
  await t('fr unregister bad recv', () => FinalizationRegistry.prototype.unregister.call({}, tok));
  // Atomics.wait on the main agent
  await t('atomics wait main', () => Atomics.wait(new Int32Array(new SharedArrayBuffer(8)), 0, 0, 0));
  await t('atomics wait mismatch', () => Atomics.wait(new Int32Array(new SharedArrayBuffer(8)), 0, 1, 0));
  await t('atomics waitAsync', async () => { const r = Atomics.waitAsync(new Int32Array(new SharedArrayBuffer(8)), 0, 1); return [r.async, r.value]; });
  await t('atomics waitAsync timeout', async () => { const r = Atomics.waitAsync(new Int32Array(new SharedArrayBuffer(8)), 0, 0, 0); return [r.async, r.value]; });
  await t('bigint asIntN huge', () => [String(BigInt.asIntN(2 ** 27, 5n)), String(BigInt.asUintN(2 ** 27, 5n))]);
  await t('bigint asIntN huge neg', () => String(BigInt.asUintN(2 ** 27, -1n)));
  await t('bigint asIntN huge2', () => String(BigInt.asIntN(2 ** 27, -(2n ** 70n))));
  await t('promise race sync', () => { class C extends Promise { static resolve(v) { return v; } } return C.race([{ then(f) { f('first'); } }, { then(f) { f('second'); } }]); });
  await t('allSettled sync complete', () => { class C extends Promise { static resolve(v) { return v; } } return C.allSettled([{ then(f) { f('a'); } }, { then(f, r) { r('b'); } }]); });
  await t('all sync complete', () => { class C extends Promise { static resolve(v) { return v; } } return C.all([{ then(f) { f('a'); } }]); });
  await t('any sync complete', () => { class C extends Promise { static resolve(v) { return v; } } return C.any([{ then(f, r) { r('a'); } }]).catch(e => e.errors); });
  console.log(out.join('\n'));
})();
"""

PROG_GENERATOR_STATES = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, String(f())); } catch (e) { log(label, 'throws', e.name, String(e.message)); } };
function* g() { yield 1; return 2; }
const it = g();
tryit('n1', () => JSON.stringify(it.next()));
tryit('n2', () => JSON.stringify(it.next()));
tryit('ret after done', () => JSON.stringify(it.return(42)));
tryit('throw after done', () => it.throw(new TypeError('late')));
tryit('next after done', () => JSON.stringify(it.next()));
const G = Object.getPrototypeOf(g).prototype;
tryit('next on prim', () => G.next.call(5));
tryit('next on obj', () => G.next.call({}));
tryit('return on obj', () => G.return.call({}));
const fresh = g();
tryit('fresh return', () => JSON.stringify(fresh.return('r')) + JSON.stringify(fresh.next()));
const fresh2 = g();
tryit('fresh throw', () => fresh2.throw(new RangeError('early')));
tryit('rsi next bad', () => { const RSI = Object.getPrototypeOf('a'.matchAll(/a/g)); return RSI.next.call({}); });
tryit('si next bad', () => { const SI = Object.getPrototypeOf(''[Symbol.iterator]()); return SI.next.call({}); });
tryit('ai next bad', () => { const AI = Object.getPrototypeOf([][Symbol.iterator]()); return AI.next.call({}); });
async function* ag() { yield 1; }
const agi = ag();
agi.next().then(v => log('ag1', JSON.stringify(v)));
agi.return(Promise.reject(new Error('ret rej'))).then(v => log('ag ret', JSON.stringify(v)), e => log('ag ret rej', e.message));
agi.next().then(v => log('ag after', JSON.stringify(v)));
const agi2 = ag();
agi2.return(Promise.resolve('rv')).then(v => log('ag2 ret', JSON.stringify(v)));
setTimeout(() => console.log(out.join('\n')), 0);
"""

PROG_COLLECTIONS_HASHING = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const dv = new DataView(new ArrayBuffer(8));
const fromBits = b => { dv.setBigUint64(0, b); return dv.getFloat64(0); };
// Doubles whose engine hash equals that of a string key (exercise collision chains).
const pairs = [['collision', fromBits(0xeede71dd2e83e150n)], ['key', fromBits(0x0dfb2423e70fbcban)], ['alpha', fromBits(0x4a981ac6467b0912n)]];
for (const [s, n] of pairs) {
  const m = new Map();
  m.set(s, 'S'); m.set(n, 'N');
  const r = [m.size, m.get(s), m.get(n), m.has(s), m.has(n)];
  m.set(s, 'S2'); m.set(n, 'N2');
  r.push(m.get(s), m.get(n), m.size);
  r.push(m.delete(s), m.has(s), m.get(n), m.delete(s), m.size);
  m.set(s, 'S3');
  r.push([...m.keys()].map(k => typeof k).join(','));
  r.push(m.delete(n), m.get(s), m.has(n), m.delete(n), m.size);
  const m2 = new Map([[n, 1]]);
  r.push(m2.get(s), m2.has(s), m2.delete(s), m2.size);
  const m3 = new Map([[s, 'a'], [n, 'b']]);
  r.push(m3.delete(n), m3.get(s), m3.get(n), m3.size, m3.delete(s), m3.size);
  const st = new Set([n, s, n, s]);
  r.push(st.size, st.has(s), st.has(n), st.delete(n), st.has(s), st.size, [...st].join());
  log(s, JSON.stringify(r), String(n));
}
// WeakMap / WeakSet compaction after many deletes
const keys = Array.from({ length: 12 }, (_, k) => ({ k }));
const wm = new WeakMap(keys.map(k => [k, k.k * 10]));
const ws = new WeakSet(keys);
const r = [];
for (let k = 0; k < 9; k++) r.push(wm.delete(keys[k]), ws.delete(keys[k]));
r.push(keys.map(k => wm.has(k) ? wm.get(k) : '-').join(','), keys.map(k => ws.has(k) ? 1 : 0).join(''));
wm.set(keys[0], 'back'); ws.add(keys[0]);
r.push(wm.get(keys[0]), ws.has(keys[0]), wm.delete({}), ws.delete({}));
log('weak', JSON.stringify(r));
const sym = Symbol('s');
const wm2 = new WeakMap([[sym, 1]]);
for (let k = 0; k < 5; k++) wm2.set(keys[k], k);
for (let k = 0; k < 5; k++) wm2.delete(keys[k]);
log('weak sym', wm2.get(sym), wm2.has(keys[1]));
tryit('map get on set', () => Map.prototype.get.call(new Set([1]), 1));
tryit('set has on map', () => Set.prototype.has.call(new Map(), 1));
tryit('weakmap get on map', () => WeakMap.prototype.get.call(new Map(), {}));
tryit('Map.groupBy throws', () => Map.groupBy([1, 2], () => { throw new RangeError('grp'); }));
tryit('set keys is values', () => Set.prototype.keys === Set.prototype.values);
tryit('set entries', () => [...new Set(['a', 'b']).entries()]);
tryit('set union bad keys', () => new Set([1]).union({ size: 1, has() { return true; }, keys() { return { next: 5 }; } }));
tryit('set union bad result', () => new Set([1]).union({ size: 1, has() { return true; }, keys() { return { next() { return 5; } }; } }));
tryit('set difference', () => [...new Set([1, 2, 3, 4]).difference({ size: 10, has(v) { return v % 2 === 0; }, keys() { throw new Error('unused'); } })]);
tryit('set isSubsetOf big', () => new Set([1, 2]).isSubsetOf({ size: 1, has() { return true; }, keys() { return [][Symbol.iterator](); } }));
tryit('set isDisjointFrom iter', () => new Set([1, 2, 3]).isDisjointFrom({ size: 1, has() { throw new Error('nohas'); }, keys() { return [5, 3][Symbol.iterator](); } }));
tryit('set isSupersetOf early', () => { const seen = []; const r = new Set([1]).isSupersetOf({ size: 3, has() { return true; }, keys() { let k = 0; return { next() { k++; seen.push(k); return { value: k, done: k > 3 }; }, return() { seen.push('ret'); return {}; } }; } }); return [r, seen]; });
tryit('set symmetricDifference', () => [...new Set([1, 2]).symmetricDifference(new Map([[2, 'x'], [3, 'y']]))]);
tryit('set intersection mutate', () => { const s = new Set([1, 2, 3]); return [...s.intersection({ size: 2, has(v) { s.delete(3); return true; }, keys() { return [1, 3][Symbol.iterator](); } })]; });
console.log(out.join('\n'));
"""

PROG_JSON_EDGES = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { log(label, JSON.stringify(f())); } catch (e) { log(label, 'throws', e.name, e.message); } };
const units = s => [...Array(s.length).keys()].map(k => s.charCodeAt(k).toString(16)).join(' ');
tryit('stringify replacer throws', () => JSON.stringify({ a: 1 }, () => { throw new RangeError('rep'); }));
tryit('stringify nested replacer throws', () => JSON.stringify({ a: { b: 1 } }, function (k, v) { if (k === 'b') throw new EvalError('deep'); return v; }));
tryit('stringify proxy sym keys', () => JSON.stringify(new Proxy({ a: 1, [Symbol('s')]: 2, b: [1, { c: 3 }] }, {})));
tryit('stringify proxy array replacer', () => JSON.stringify({ x: 1, y: 2, z: 3 }, new Proxy(['z', 'x'], {})));
tryit('stringify proxy arraylike replacer len', () => JSON.stringify({ a: 1, b: 2 }, new Proxy(['b', 'a'], { get(t, k) { return k === 'length' ? 1 : t[k]; } })));
tryit('stringify smuggled pair', () => units(JSON.stringify('\uDBFE' + '\uDC00')) + ' / ' + units(JSON.stringify('\u{10F800}x\u{10FFFF}')));
tryit('smuggled roundtrip', () => { const s = '\uDBFE' + '\uDC00'; const t = JSON.parse(JSON.stringify(s)); return [t === s, t.length, units(t), s.codePointAt(0).toString(16)]; });
tryit('parse missing comma', () => JSON.parse('{"a":1 "b":2}'));
tryit('parse missing comma reviver', () => JSON.parse('{"a":1 "b":2}', (k, v) => v));
tryit('parse trailing comma', () => JSON.parse('{"a":1,}'));
tryit('parse bad array', () => JSON.parse('[1 2]'));
tryit('parse surrogate escapes', () => units(JSON.parse('"\\ud83d\\ude00\\ud800x\\udc00"')));
tryit('parse surrogate key', () => Object.keys(JSON.parse('{"\\ud83d\\ude00":1,"\\ud800":2}')).map(units));
tryit('parse surrogate reviver', () => JSON.parse('{"k":"\\ud83d\\ude00\\ud83d"}', (k, v) => typeof v === 'string' ? units(v) : v));
tryit('parse long escapes', () => JSON.parse('"' + 'ab\\n'.repeat(30) + '\\ud83d\\ude00' + '"').length);
tryit('reviver proxy holder', () => JSON.stringify(JSON.parse('{"a":1,"b":{"c":2,"d":3}}', function (k, v) {
  if (k === 'a') { this.b = new Proxy({ c: 20, d: 30, [Symbol('q')]: 1 }, { defineProperty(t, key, desc) { log('proxy define', key, JSON.stringify(desc)); return Reflect.defineProperty(t, key, desc); } }); }
  return typeof v === 'number' ? v + 1 : v;
})));
tryit('reviver proxy array', () => JSON.stringify(JSON.parse('{"a":1,"b":[5,6]}', function (k, v) {
  if (k === 'a') { this.b = new Proxy([7, 8], {}); }
  return Array.isArray(v) ? v.length : v;
})));
tryit('reviver nonconfigurable undefined', () => { const r = JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') Object.defineProperty(this, 'b', { value: 9, configurable: false, enumerable: true }); return k === 'b' ? undefined : v; }); return [r.b, Object.keys(r)]; });
tryit('reviver nonconfigurable define', () => { const r = JSON.parse('{"a":1,"b":2}', function (k, v) { if (k === 'a') Object.defineProperty(this, 'b', { value: 9, configurable: false, writable: false, enumerable: true }); return k === 'b' ? 'new' : v; }); return r.b; });
tryit('reviver source', () => JSON.parse('{"n":12345678901234567890,"s":"x"}', (k, v, ctx) => k ? [typeof v, ctx && ctx.source] : v));
tryit('rawJSON', () => [JSON.stringify({ big: JSON.rawJSON('12345678901234567890') }), JSON.isRawJSON(JSON.rawJSON('1')), JSON.isRawJSON({})]);
tryit('rawJSON bad', () => JSON.rawJSON('{}'));
console.log(out.join('\n'));
"""

PROG_NUMERIC_BIGINT_ITER = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const tryit = (label, f) => { try { const v = f(); log(label, typeof v === 'bigint' ? v + 'n' : JSON.stringify(v, (k, x) => typeof x === 'bigint' ? x + 'n' : Object.is(x, -0) ? '-0' : x)); } catch (e) { log(label, 'throws', e.name, e.message); } };
tryit('min apply nan', () => [Math.min.apply(null, [1, NaN, 2]), Math.max.apply(null, [1, NaN, 2]), Reflect.apply(Math.min, null, [3, 1, -0, 0]), Math.min.call(null, 0, -0), Math.max.apply(null, [-0, 0])]);
tryit('min coercion order', () => { const seen = []; const v = n => ({ valueOf() { seen.push(n); return n === 2 ? NaN : n; } }); return [Math.min(v(1), v(2), v(3)), seen]; });
tryit('sumPrecise half-even', () => [Math.sumPrecise([1, 2 ** -53, 2 ** -106]), Math.sumPrecise([1, -(2 ** -53), -(2 ** -106)]), Math.sumPrecise([2 ** 53, 1, 2 ** -60]), Math.sumPrecise([-(2 ** 53), -1, -(2 ** -60)]), Math.sumPrecise([1e308, 1e308, -1e308]), Math.sumPrecise([0.1, 0.2, 0.3, -0.6])]);
tryit('sumPrecise misc', () => [Math.sumPrecise([]), Math.sumPrecise([-0, -0]), Math.sumPrecise([-0, 0]), Math.sumPrecise([Infinity, 1]), Math.sumPrecise([1e300, 1e300, 1e300, -1e300, -1e300])]);
tryit('sumPrecise bad', () => Math.sumPrecise([1, '2']));
tryit('bigint shifts', () => [0n << 5n, 0n >> 100n, (-(2n ** 64n)) >> 1n, 5n << 0n, (-1n) >> 200n, (2n ** 100n) >> 99n]);
tryit('bigint bitops neg multi', () => [String((-(2n ** 64n)) & (2n ** 70n - 1n)), String((-(2n ** 128n) + 1n) | 3n), String((-(2n ** 64n) - 5n) ^ (2n ** 65n)), String(~(2n ** 64n)), String((-(2n ** 64n)) & -(2n ** 64n))]);
tryit('bigint asUintN', () => [String(BigInt.asUintN(64, -(2n ** 64n) - 1n)), String(BigInt.asIntN(65, 2n ** 64n)), String(BigInt.asIntN(1, 1n)), String(BigInt.asUintN(0, 5n))]);
tryit('epochNs extremes', () => [2n ** 200n, -(2n ** 127n) - 1n, 2n ** 127n, 8640000000000000000000n, -8640000000000000000001n, -8640000000000000000000n].map(n => { try { return Temporal.Instant.fromEpochNanoseconds(n).toString(); } catch (e) { return e.name + ': ' + e.message; } }));
tryit('bigint compare double', () => [1n < 5e-324, 0n < 5e-324, -1n < -5e-324, 2n ** 64n == 2 ** 64, 2n ** 64n < 2 ** 64 + 4096, (2n ** 1024n) > Number.MAX_VALUE, -(2n ** 1024n) < -Number.MAX_VALUE, 9007199254740993n > 9007199254740992]);
tryit('bigint toString radix', () => [(2n ** 70n).toString(36), (-(2n ** 65n)).toString(2).length, (255n).toString(16), BigInt.asUintN(128, -1n).toString(7)]);
tryit('bigint from strings', () => [BigInt('0x' + 'f'.repeat(40)), BigInt('  -123  '), BigInt('0b101'), BigInt('0o777')].map(String));
tryit('BigInt64Array big', () => { const a = new BigInt64Array(2); a[0] = 2n ** 63n; a[1] = -(2n ** 64n) - 1n; return [String(a[0]), String(a[1])]; });
tryit('bind null proto', () => { const f = function named() { return 1; }; Object.setPrototypeOf(f, null); const b = Function.prototype.bind.call(f); return [Object.getPrototypeOf(b), b.name, b()]; });
tryit('bind proxy proto', () => { const p = new Proxy(function () {}, { getPrototypeOf() { log('trap getPrototypeOf'); return Array.prototype; } }); const b = p.bind(); return [Object.getPrototypeOf(b) === Array.prototype, b.name]; });
tryit('fn toString natives', () => [Function.prototype.toString.call(Math.max), Function.prototype.toString.call(function () {}.bind()), Function.prototype.toString.call(new Proxy(function () {}, {})), Function.prototype.toString.call(Object.getOwnPropertyDescriptor(Map.prototype, 'size').get), Function.prototype.toString.call(Array.prototype[Symbol.iterator])]);
tryit('fn toString bad', () => Function.prototype.toString.call({}));
tryit('array iter oob', () => { const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const ta = new Uint8Array(rab, 4, 4); const it = ta.values(); const a = it.next(); rab.resize(2); try { it.next(); } catch (e) { return [a, e.name, e.message]; } });
tryit('array iter tracking', () => { const rab = new ArrayBuffer(4, { maxByteLength: 16 }); const ta = new Uint8Array(rab); const it = ta.keys(); const r = [it.next().value]; rab.resize(1); r.push(it.next()); rab.resize(8); r.push(it.next()); return r; });
tryit('array iter decorated', () => { const it = [10, 20, 30].entries(); Object.defineProperty(it, 'extra', { get() { return 1; } }); const r = [it.next().value]; it.x = 1; delete it.extra; r.push(it.next().value, it.next().value, it.next().done); return r; });
tryit('array iter proto swap', () => { const it = ['a', 'b'].values(); Object.setPrototypeOf(it, Object.getPrototypeOf([].values())); const r = [it.next().value]; Object.preventExtensions(it); r.push(it.next().value, it.next().done); return r; });
tryit('array iter proxy target', () => { const it = Array.prototype.values.call(new Proxy([1, 2], { get(t, k) { if (k === 'length') log('len read'); return t[k]; } })); return [...{ [Symbol.iterator]() { return it; } }]; });
tryit('array iter string target', () => [...Array.prototype.keys.call('ab😀')]);
tryit('array iter num target', () => [...Array.prototype.values.call(5)]);
tryit('captureStackTrace frozen', () => { try { Error.captureStackTrace(Object.freeze({})); } catch (e) { return e.name; } return 'ok'; });
tryit('symbol registry', () => [Symbol.for('app') === Symbol.for('app'), Symbol.keyFor(Symbol.for('app')), Symbol.keyFor(Symbol.iterator), Symbol.keyFor(Symbol('x')), String(Symbol.asyncDispose), Symbol.metadata?.toString()]);
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_typedarray_getters_and_constructor_prototype_fallback(run, tier):
    """CATCHES: engines whose %TypedArray%.prototype length/byteLength/byteOffset/buffer getters skip the brand check or misreport a view, or that mishandle GetPrototypeFromConstructor for bound/proxy newTargets with a non-object prototype (wrong prototype, or no TypeError when the proxy is revoked while reading 'prototype')."""
    r = run([*tier, "-e", PROG_TA_GETTERS_REALM])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "ta_getters_realm")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_reflect_receivers_and_integrity_levels(run, tier):
    """CATCHES: wrong Reflect.set/Reflect.get receiver semantics (proxy on the chain, proxy or TypedArray receivers, setter-only accessors), array mutators that ignore a deleteProperty trap returning false, Object.defineProperties/freeze/isFrozen that bypass proxy traps or treat non-empty TypedArrays as freezable."""
    r = run([*tier, "-e", PROG_REFLECT_INTEGRITY])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "reflect_integrity")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_proxy_descriptor_invariants_and_typedarray_extensibility(run, tier):
    """CATCHES: Proxy getOwnPropertyDescriptor/defineProperty traps whose invariants (non-configurable/non-writable/accessor shape, non-extensible targets, missing target keys) are not enforced with the exact TypeError, Object.keys/entries ignoring trap-reported enumerability, setPrototypeOf cycle detection through proxies, TypedArray [[PreventExtensions]] on resizable/length-tracking buffers, out-of-bounds TypedArray accessors and Object.values/entries over TypedArray expandos."""
    r = run([*tier, "-e", PROG_PROXY_INVARIANTS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "proxy_invariants")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_regexp_dead_result_calls_keep_side_effects(run, tier):
    """CATCHES: optimisations that drop observable side effects (lastIndex updates, RegExp.lastMatch/$1/leftContext/rightContext) when the result of String#replace/match or RegExp#exec is discarded, including non-integer lastIndex values, sticky regexps and an own exec override."""
    r = run([*tier, "-e", PROG_REGEXP_DEAD])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "regexp_dead")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_regexp_literal_dead_result_loops(run, tier):
    """CATCHES: hot loops calling arr[i].replace(/lit/g, 's'), arr[i].match(/lit/g) or /lit/.exec(arr[i]) as statements whose fused fast path forgets to advance past empty matches or to update the legacy RegExp statics."""
    r = run([*tier, "-e", PROG_REGEXP_LITERAL_DEAD])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "regexp_literal_dead")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_string_methods_with_nulled_symbol_hooks(run, tier):
    """CATCHES: String split/replace/replaceAll/match/matchAll/search that mishandle a RegExp whose Symbol.* method is null/undefined, accept non-callable Symbol.* hooks without a TypeError, or get substr/at/fromCharCode/codePointAt edge cases wrong."""
    r = run([*tier, "-e", PROG_STRING_SYMBOL_HOOKS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "string_symbol_hooks")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_promise_combinators_with_misbehaving_thenables(run, tier):
    """CATCHES: Promise.all/allSettled/any/allKeyed/allSettledKeyed that honour a second call of the same element resolver, do not reject on a non-callable or throwing C.resolve / then getter / ownKeys trap, lose symbol keys or the null prototype of keyed results, or let a throwing capability resolve escape."""
    r = run([*tier, "-e", PROG_PROMISE_COMBINATORS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "promise_combinators")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_iterator_concat_zip_reentrancy_and_padding(run, tier):
    """CATCHES: Iterator.concat / iterator helpers / Iterator.zip(Keyed) that allow re-entrant next/return while running, do not validate strict-mode inner iterators, or mishandle longest-mode padding iterators (errors, closing, short padding) and setup failures (closing already-open inputs)."""
    r = run([*tier, "-e", PROG_ITERATOR_REENTRANCY])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "iterator_reentrancy")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_array_methods_on_array_likes(run, tier):
    """CATCHES: generic Array.prototype methods on array-likes that swallow callback exceptions, skip ArraySpeciesCreate length/constructor checks, mishandle +-Infinity fromIndex, Array.of/from with non-constructor receivers, concat/toSpliced/fill length limits, or Array.prototype.toString without a callable join."""
    r = run([*tier, "-e", PROG_ARRAY_GENERIC])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "array_generic")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_define_property_validation_and_array_length(run, tier):
    """CATCHES: [[DefineOwnProperty]] bugs: mapped arguments aliasing after writable:false / accessor redefinition, TypedArray index descriptors (no value, non-configurable, accessor, out-of-range, -0, non-integer keys), redefinition of non-configurable data/accessor properties, Array length descriptors (configurable/enumerable/accessor, non-writable, double ToNumber coercion), and push/pop at the 2^32-1 length limit inside hot loops."""
    r = run([*tier, "-e", PROG_DEFINE_PROPERTY])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "define_property")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_misc_species_locale_casing_and_number_formatting(run, tier):
    """CATCHES: Date#toLocale*String option defaulting (primitive options, partial component sets), SpeciesConstructor with undefined/primitive constructors (Promise then/finally, ArrayBuffer slice, RegExp split/matchAll), CreateDataPropertyOrThrow on rejecting species results, Lithuanian/Turkish casing of soft-dotted letters, split length limits and toExponential/toPrecision/toFixed digit padding."""
    r = run([*tier, "-e", PROG_MISC_BUILTINS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "misc_builtins")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_async_builtins_fromasync_disposablestack_atomics(run, tier):
    """CATCHES: Array.fromAsync with non-constructor receivers, array-likes, throwing mappers and iterator closing, AsyncDisposableStack use/adopt/defer/move after disposal and error suppression, FinalizationRegistry.unregister results, Atomics.wait/waitAsync outcomes, BigInt.asIntN/asUintN with huge widths and synchronously-settling combinator thenables."""
    r = run([*tier, "-e", PROG_ASYNC_BUILTINS])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "async_builtins")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_generator_and_iterator_brand_checks(run, tier):
    """CATCHES: generators that mishandle next/return/throw after completion or before start, iterator prototypes' next() without receiver brand checks, and async generator return() with rejected/fulfilled promises."""
    r = run([*tier, "-e", PROG_GENERATOR_STATES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "generator_states")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_map_set_colliding_keys_and_weak_compaction(run, tier):
    """CATCHES: Map/Set implementations that confuse a string key with a double key of the same internal hash (wrong get/has/delete/size or iteration order after updates and deletions in either order), WeakMap/WeakSet that lose live entries when compacting after many deletes, missing brand checks across Map/Set/WeakMap methods, and set-methods that accept malformed set-like keys() iterators."""
    r = run([*tier, "-e", PROG_COLLECTIONS_HASHING])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "collections_hashing")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_json_replacer_reviver_and_surrogate_edges(run, tier):
    """CATCHES: JSON.stringify that swallows replacer exceptions, includes symbol keys of proxies or ignores proxy array replacers, mangles surrogate pairs that encode U+10F800..U+10FFFF; JSON.parse with wrong SyntaxError messages, broken surrogate escapes, or reviver handling of proxy holders, non-configurable properties, source text and JSON.rawJSON."""
    r = run([*tier, "-e", PROG_JSON_EDGES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "json_edges")

@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_numeric_bigint_function_and_array_iterator_edges(run, tier):
    """CATCHES: Math.min/max NaN and -0 handling via apply, Math.sumPrecise round-half-even and -0 results, BigInt shifts/bitwise ops on multi-limb negatives, asIntN/asUintN, out-of-range epochNanoseconds, BigInt/Number comparisons, Function.prototype.bind prototype lookup (null, proxy trap), native toString rendering, and Array iterators over shrinking resizable buffers, proxies, strings and decorated iterator objects."""
    r = run([*tier, "-e", PROG_NUMERIC_BIGINT_ITER])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "numeric_bigint_iter")

SHADOW_MAIN = r"""const out = [];
const log = (...a) => out.push(a.join(' '));
const r = new ShadowRealm();
const tryp = async (label, f) => {
  try { const v = await f(); log(label + ':', typeof v, typeof v === 'function' ? v(2, 3) : String(v)); }
  catch (e) { log(label + ':', 'rejects', e.name, e.message); }
};
(async () => {
  await tryp('number export', () => r.importValue('./mod.mjs', 'answer'));
  await tryp('function export', () => r.importValue('./mod.mjs', 'add'));
  await tryp('object export', () => r.importValue('./mod.mjs', 'obj'));
  await tryp('missing export', () => r.importValue('./mod.mjs', 'nope'));
  await tryp('missing module', () => r.importValue('./missing-module.mjs', 'x'));
  await tryp('throwing module', () => r.importValue('./bad.mjs', 'x'));
  await tryp('same realm state', async () => { const inc = await r.importValue('./mod.mjs', 'inc'); inc(); inc(); return (await r.importValue('./mod.mjs', 'count'))(); });
  try { r.importValue('./mod.mjs', 5); } catch (e) { log('sync name:', e.name, e.message); }
  try { ShadowRealm.prototype.importValue.call({}, './mod.mjs', 'x'); } catch (e) { log('sync brand:', e.name, e.message); }
  try { r.importValue({ toString() { throw new RangeError('specifier coercion'); } }, 'x'); } catch (e) { log('sync spec:', e.name, e.message); }
  const pending = r.importValue('./missing-module.mjs', 'y');
  log('promise kind:', Object.prototype.toString.call(pending));
  await pending.catch(() => {});
  log('eval strict:', r.evaluate('"use strict"; (function () { return this === undefined; })()'));
  log('eval sloppy:', r.evaluate('(function () { return typeof this; })()'));
  log('eval empty:', String(r.evaluate('')), String(r.evaluate(';')), String(r.evaluate('var zz = 1')), r.evaluate('zz + 1'));
  log('eval fn:', typeof r.evaluate('(x) => x * 2'), r.evaluate('(x) => x * 2')(21));
  try { r.evaluate('({})'); } catch (e) { log('eval object:', e.name, e.message); }
  console.log(out.join('\n'));
})();
"""

SHADOW_MOD = """export const answer = 42;
export function add(a, b) { return a + b; }
export const obj = { a: 1 };
let n = 0;
export function inc() { n++; }
export function count() { return n; }
"""


def test_shadowrealm_import_value_errors_and_evaluate(run, workdir):
    """CATCHES: ShadowRealm.prototype.importValue (from a CommonJS entry, resolving ./mod.mjs next to it) that fails to marshal primitive/callable exports, lets objects cross, does not reject for missing exports/modules or throwing modules, re-evaluates the module per call, throws synchronously instead of rejecting, or skips the brand/exportName/specifier checks; and ShadowRealm.prototype.evaluate that ignores a 'use strict' directive, returns non-undefined completions for empty programs, or lets objects cross the realm boundary."""
    write_files(workdir, {
        "main.cjs": SHADOW_MAIN,
        "mod.mjs": SHADOW_MOD,
        "bad.mjs": "throw new Error('module boom');\n",
    })
    r = run(["main.cjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "shadowrealm")
