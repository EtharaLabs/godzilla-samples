"""Extra core-language coverage, part 2: tree-walker assignment/iteration corner cases, GC with
live `with` scopes / mapped arguments / import bindings, the RegExp program cache, dynamic-import
options validation and `export default` NamedEvaluation, lexer escape/numeric edge cases, and
`import defer` of modules whose top-level await hides in unusual positions.
"""

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

PROG_TREE_WALKER_2 = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// sparse spreads and object literal __proto__
show('hole after spread', () => { const a = [...[1], , 3]; return a.length + ':' + (1 in a) + ':' + JSON.stringify(a); });
show('proto literal prim', () => Object.getPrototypeOf({ __proto__: 5 }) === Object.prototype);
show('proto literal null', () => Object.getPrototypeOf({ __proto__: null }));
show('setter then getter literal', () => { const o = { set a(v) { this._a = v; }, get a() { return 'got' + this._a; } }; o.a = 1; return o.a; });
show('getter twice literal', () => ({ get a() { return 1; }, get a() { return 2; } }).a);
// strict tail-position tagged templates falling back
show('tail tagged null base', () => { 'use strict'; const o = null; function f() { return o.t`x`; } return f(); });
show('tail tagged index tag', () => { 'use strict'; const o = { t(s) { return 'idx:' + s[0]; } }; function f() { return o['t']`y`; } return f(); });
show('tail tagged nonfn', () => { 'use strict'; const o = { t: 5 }; function f() { return o.t`x`; } return f(); });
show('tail tagged paren tag', () => { 'use strict'; const t = (s) => 'paren:' + s[0]; function f() { return (0, t)`z`; } return f(); });
show('tail call short-circuit callee', () => { 'use strict'; const mk = null; function f() { return mk?.()(1); } return String(f()); });
show('tail optional call result', () => { 'use strict'; const o = { m: null }; function f() { return o.m?.(); } return String(f()); });
// optional chain calls with short-circuited callees
show('opt idx call short', () => { const o = null; return String(o?.x[0]()); });
show('opt idx base short', () => { const o = null; return String(o?.[0]()); });
show('opt call call short', () => { const a = null; return String(a?.b()()); });
show('delete nested opt', () => { const a = null; return [delete a?.b?.c, delete a?.b?.[0], delete a?.b[0]].join(); });
// compound/destructuring assignment corner cases
show('const compound', () => { const c = 1; c += 1; });
show('const compound strict', () => { 'use strict'; const c = 1; c **= 2; });
show('undeclared compound', () => { undeclaredCompound += 1; });
show('call compound', () => { const f = () => ({}); eval('f() += 1'); });
show('call assign', () => { const f = () => ({}); eval('f() = 1'); });
show('call destr target', () => { let hit = 0; const f = () => { hit++; return {}; }; try { eval('[f()] = [1]'); } catch (e) { return hit + ' ' + e.name + ': ' + e.message; } });
show('super destr assign', () => { class B {} class D extends B { m() { [super.x, super['y']] = [1, 2]; ({ a: super.z } = { a: 3 }); return [this.x, this.y, this.z].join(); } } return new D().m(); });
show('private destr assign', () => { class P { #p = 0; m() { [this.#p] = [5]; ({ q: this.#p } = { q: this.#p + 1 }); return this.#p; } } return new P().m(); });
show('nested pattern defaults', () => { let a, y, z; [[a] = [1]] = []; ({ x: { y } = { y: 2 } } = {}); ({ k: [z] = [3] } = {}); return [a, y, z].join(); });
show('destr keys kinds', () => { let a, b, c, d; const k = 'dyn'; ({ 'str': a, 7: b, [k]: c, 0: d } = { str: 's', 7: 'seven', dyn: 'D', 0: 'zero' }); return [a, b, c, d].join(); });
show('obj rest from string excl', () => { const { 0: first, ...rest } = 'abc'; return first + JSON.stringify(rest); });
show('obj rest proxy ghost', () => { const p = new Proxy({ a: 1, h: 2 }, { ownKeys() { return ['a', 'ghost', 'h']; }, getOwnPropertyDescriptor(t, k) { if (k === 'ghost') return undefined; if (k === 'h') return { value: 2, enumerable: false, configurable: true }; return Reflect.getOwnPropertyDescriptor(t, k); } }); const { ...r } = p; return JSON.stringify(r); });
show('gen return during destr', () => { function* g() { let a; [a = yield 'paused'] = [undefined]; return a; } const it = g(); it.next(); return JSON.stringify(it.return('R')); });
show('gen return during destr close', () => { const log = []; const src = { [Symbol.iterator]() { return { next() { return { value: undefined, done: false }; }, return() { log.push('closed'); return {}; } }; } }; function* g() { let a; [a = yield 'p'] = src; } const it = g(); it.next(); it.return(1); return log.join(); });
show('gen return close throws', () => { const src = { [Symbol.iterator]() { return { next() { return { value: undefined, done: false }; }, return() { throw new Error('close-throw'); } }; } }; function* g() { let a; [a = yield 'p'] = src; } const it = g(); it.next(); it.return(1); });
show('gen return close prim', () => { const src = { [Symbol.iterator]() { return { next() { return { value: undefined, done: false }; }, return() { return 1; } }; } }; function* g() { let a; [a = yield 'p'] = src; } const it = g(); it.next(); it.return(1); });
show('for-of return close prim', () => { const src = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return() { return 1; } }; } }; for (const x of src) break; });
show('for-of return noncallable', () => { const src = { [Symbol.iterator]() { return { next() { return { value: 1, done: false }; }, return: 5 }; } }; for (const x of src) break; });
show('spread result prim', () => [...{ [Symbol.iterator]() { return { next() { return 1; } }; } }]);
show('spread not iterable', () => [...{ [Symbol.iterator]: 5 }]);
show('spread non-obj iterator', () => [...{ [Symbol.iterator]() { return 5; } }]);
// with-scope GetValue/PutValue when the binding vanishes
show('with compound vanish', () => { const o = { get [Symbol.unscopables]() { delete o.x; return {}; }, x: 1 }; with (o) { x += 1; } return JSON.stringify(o); });
show('strict global vanish', () => { 'use strict'; globalThis.gvanish = 1; gvanish = (delete globalThis.gvanish, 2); });
show('super null base compound', () => { const home = { m() { return super.x += 1; } }; Object.setPrototypeOf(home, null); return home.m(); });
show('super null base get', () => { const home = { m() { return super.x; } }; Object.setPrototypeOf(home, null); return home.m(); });
// instanceof without @@hasInstance on the chain
show('instanceof null-proto fn', () => { function F() {} Object.setPrototypeOf(F, null); return [({}) instanceof F, Object.create(F.prototype) instanceof F].join(); });
show('instanceof bound', () => { function F() {} const B = F.bind(null); return new F() instanceof B; });
// numbers to strings
show('exp coerced', () => ['2' ** '3', ({ valueOf: () => 3 }) ** 2, 2 ** '-1'].join());
show('num keys', () => { const { 0: z, 1e21: big, 0.5: half } = { 0: 'z', 1e21: 'big', 0.5: 'h' }; return z + big + half; });
// array length coercion that freezes
show('length freeze during coercion', () => { const a = [1, 2, 3]; a.length = { valueOf() { Object.freeze(a); return 1; } }; return a.length; });
show('length freeze during coercion strict', () => { 'use strict'; const a = [1, 2, 3]; a.length = { valueOf() { Object.freeze(a); return 1; } }; return a.length; });
// Reflect.set from strict code with failing receivers
show('strict Reflect.set proxy recv', () => { 'use strict'; return Reflect.set({}, 'x', 2, new Proxy({}, { defineProperty() { return false; } })); });
show('strict Reflect.set ro recv', () => { 'use strict'; return Reflect.set({}, 'x', 2, Object.defineProperty({}, 'x', { value: 1 })); });
// annex B block functions
show('annexB generator not hoisted', () => { { function* blockGen() {} async function blockAsync() {} function blockPlain() {} } return [typeof blockGen, typeof blockAsync, typeof blockPlain].join(); });
show('annexB in switch', () => { switch (1) { case 1: function inSwitch() { return 's'; } } return inSwitch(); });
show('annexB shadowed by let', () => { let shadowed = 'let'; { function shadowed() {} } return typeof shadowed; });
// unary on variables
show('unary bigint var', () => { const x = 1n; return +x; });
show('unary minus bigint var', () => { const x = 5n; return String(-x) + String(~x); });
// subclassed builtins in interp
show('DataView subclass', () => { class DV extends DataView { tag() { return 'dv' + this.byteLength; } } const d = new DV(new ArrayBuffer(4)); d.setInt8(0, 7); return d.tag() + ':' + d.getInt8(0) + ':' + (d instanceof DataView); });
show('PlainDate subclass', () => { class PD extends Temporal.PlainDate { tag() { return 'pd:' + this.toString(); } } return new PD(2020, 2, 29).tag(); });
show('super into bound parent', () => { class Base { constructor(a, b) { this.args = a + ',' + b; } } const BB = Base.bind(null, 'bound'); Object.defineProperty(BB, 'prototype', { value: Base.prototype }); class C extends BB { constructor() { super('passed'); } } const c = new C(); return c.args + ',' + (c instanceof Base); });
show('RegExp nt proto prim', () => { function G() {} G.prototype = 3; const r = Reflect.construct(RegExp, ['a+'], G); return Object.getPrototypeOf(r) === RegExp.prototype && r.test('caa'); });
show('field init arrow arguments', () => { eval('class A { x = (a = arguments) => a }'); });
show('field init arrow super call', () => { eval('class B {} class A extends B { x = () => super() }'); });
show('eval field init exprs', () => { class A { #p = 1; x = eval('let n = 0; for (n = 1; n < 3; n++); (0, n); `${n}`; ({ ...{ a: n } }); [, n]; #p in this; String.raw`r`; ({ m() { return arguments; } }); n'); } return new A().x; });
show('param expr + same-name fn decl', () => { function f(a = 1, b = () => a) { function a() {} var b; return typeof a + ',' + typeof b + ',' + typeof b(); } return f(); });
show('param expr + same-name var', () => { function f(a = 1, b = 2) { var a; var b = b + 1; return a + ',' + b; } return f(undefined, 5); });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_assignment_iteration_and_construction_corners(run, tier):
    """CATCHES: holes after spread elements filled instead of preserved, non-object `__proto__` literal values not ignored, strict tail calls through tagged templates whose tag is an index/paren/non-callable/null-based expression, optional-chain call/delete short-circuits through nested chains, const/undeclared/call-expression compound assignment errors, destructuring assignment into super/private targets and nested-pattern defaults, generator return() during destructuring (IteratorClose results), with-scope GetValue on vanished bindings, null super bases, instanceof without @@hasInstance, length coercion freezing the array, Annex B block-function rules, subclassed DataView/Temporal/bound parents, and arguments/super checks in field-initializer arrows."""
    r = run([*tier, "-e", PROG_TREE_WALKER_2])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "assignment_iteration_construction")

GC_MAIN = r"""import { counter, bump, shared } from './dep.mjs';
import * as depNs from './dep.mjs';
// sloppy-mode helpers (module code is strict): a mapped arguments object and a `with` scope
// captured by a closure, both kept alive across collections
const sloppyMapped = Function('a', 'b', 'return arguments;');
const scopeObj = { inWith: 'yes' };
const withReader = Function('o', 'with (o) { return function () { return inWith; }; }')(scopeObj);
const argsObjs = [];
for (let i = 0; i < 40; i++) argsObjs.push(sloppyMapped(i, { v: i }));
function churn(n, keepN) {
  const keep = [];
  function node(i) { const a = { i }; const b = { a }; a.b = b; return a; }
  for (let i = 0; i < n; i++) { keep.push(node(i)); if (i % 1000 === 0) bump(); }
  keep.length = keepN;
  return keep;
}
let kept = churn(70000, 1000);
kept = kept.concat(churn(70000, 1000));
console.log('kept', kept.length, 'sample', kept[999].i, kept[1500].b.a.i);
console.log('mapped args survive', argsObjs[7][0], argsObjs[39][1].v, argsObjs.length);
argsObjs[3][0] = 'rewritten';
console.log('mapped arg write', argsObjs[3][0]);
console.log('with closure survives', withReader());
console.log('imports survive', counter, depNs.counter, shared.tag);
"""

GC_DEP = r"""export let counter = 0;
export function bump() { counter++; return counter; }
export const shared = { tag: 'shared' };
"""


@pytest.mark.parametrize("tier", [[], ["--tier=bytecode"]], ids=["jit", "bytecode"])
def test_cycle_collection_keeps_scopes_arguments_and_imports(run, workdir, tier):
    """CATCHES: a cycle collector (triggered here by >100k live objects in reference cycles) that frees objects only reachable through a `with` object environment captured by a closure, a sloppy mapped arguments object's parameter environment, or a module's live import bindings / namespace -- or that loses surviving array elements after truncation."""
    write_files(workdir, {"gc.mjs": GC_MAIN, "dep.mjs": GC_DEP})
    r = run([*tier, "gc.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "gc_live_scopes")

PROG_REGEXP_CACHE = r"""// More than 256 distinct RegExp sources: the compiled-program cache is evicted and rebuilt, and
// every regex (old and new) must keep matching correctly.
const out = [];
const made = [];
for (let i = 0; i < 300; i++) made.push(new RegExp('^x' + i + '(y+)$'));
let ok = 0;
for (let i = 0; i < 300; i++) { const m = made[i].exec('x' + i + 'yyy'); if (m && m[1] === 'yyy' && !made[i].test('x' + i + 'z')) ok++; }
out.push('first pass ok ' + ok);
// re-create early sources after eviction and use literals too
let ok2 = 0;
for (let i = 0; i < 20; i++) { const r = new RegExp('^x' + i + '(y+)$', 'g'); r.lastIndex = 0; if (r.exec('x' + i + 'yy')[1] === 'yy' && r.lastIndex === ('x' + i + 'yy').length) ok2++; }
out.push('recreated ok ' + ok2);
const words = [];
for (let i = 0; i < 280; i++) words.push(('w' + i).replace(new RegExp('w(' + i + ')'), '<$1>'));
out.push(words.slice(0, 3).join(' ') + ' ... ' + words.slice(-2).join(' '));
out.push('split ' + 'a1b22c333d'.split(/\d+/).join('|') + ' match ' + JSON.stringify('k=v;x=y'.match(/(\w)=(\w)/g)));
console.log(out.join('\n'));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_regexp_program_cache_eviction(run, tier):
    """CATCHES: a compiled-RegExp cache that returns stale or wrong programs after more than 256 distinct sources evict it (wrong captures, lastIndex, replace/split/match results for regexes created before and after the eviction)."""
    r = run([*tier, "-e", PROG_REGEXP_CACHE])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "regexp_cache_eviction")

IMPORT_OPTION_FILES = {
    'r.mjs': r"""const show = async (label, p) => { try { const v = await p; console.log(label, JSON.stringify(v.default ?? v.v ?? Object.keys(v))); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
await show('opts prim', import('./data.json', 5));
await show('with prim', import('./data.json', { with: 1 }));
await show('with undefined', import('./m.mjs', { with: undefined }));
await show('json via with', import('./data.json', { with: { type: 'json' } }));
await show('non-string attr', import('./data.json', { with: { type: 1 } }));
await show('non-enumerable attr', import('./m.mjs', { with: Object.defineProperty({}, 'type', { value: 7, enumerable: false }) }));
await show('symbol attr ignored', import('./m.mjs', { with: { [Symbol('s')]: 1 } }));
await show('proxy attrs', import('./data.json', { with: new Proxy({ type: 'json', extra: 'x' }, {}) }));
await show('proxy attrs sym/ghost/hidden', import('./m.mjs', { with: new Proxy({ hidden: 2 }, { ownKeys() { return [Symbol('q'), 'ghost', 'hidden']; }, getOwnPropertyDescriptor(t, k) { if (k === 'hidden') return { value: 2, enumerable: false, configurable: true }; return undefined; } }) }));
await show('proxy attr non-string', import('./m.mjs', { with: new Proxy({ type: 5 }, {}) }));
await show('options getter throws', import('./m.mjs', { get with() { throw new Error('with getter'); } }));
await show('specifier toString throws', import({ toString() { throw new Error('spec toString'); } }));
await show('specifier object', import({ toString() { return './m.mjs'; } }));
await show('json without attr', import('./data.json'));
await show('unknown type', import('./m.mjs', { with: { type: 'css' } }));
export default (class {});
export const arrowName = (() => {}).name;
""",
    'r2.mjs': r"""import cls from './r.mjs';
import fnDefault from './r3.mjs';
import arrowDefault from './r4.mjs';
console.log('default class name', cls.name, 'fn', fnDefault.name, 'arrow', arrowDefault.name);
""",
    'r3.mjs': r"""export default (function () {});
""",
    'r4.mjs': r"""export default () => 1;
""",
    'm.mjs': r"""export const v = "mod";
""",
    'data.json': r"""{"j": 1}
""",
}


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_dynamic_import_options_and_default_export_names(run, workdir, tier):
    """CATCHES: dynamic import() that does not validate its options bag (non-object options/with, non-string attribute values incl. via a Proxy's ownKeys/getOwnPropertyDescriptor traps, skipping symbol keys, non-enumerable and ghost keys), lets a throwing `with` getter or specifier toString escape synchronously instead of rejecting, and `export default` of anonymous class/function/arrow expressions that are not named "default"."""
    write_files(workdir, IMPORT_OPTION_FILES)
    r = run([*tier, "r2.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "dynamic_import_options")

PROG_LEXER_EDGES = r"""const cases = [
  'var a\\u{zz} = 1',
  'var \\u00zz = 1',
  'var \\u{110000}x = 1',
  'var x\\u0030y = 7; x0y',
  '"abc\\',
  '"\\uD83D\\u{DE00"',
  '"\\uD83D\\uZZZZ"',
  '"\\uD83D\\u{DE00}".codePointAt(0)',
  '"\\uDBFE\\uDC00".codePointAt(0)',
  '"\\uDBFE\\uDC00".length',
  '"\\u{10F800}" === "\\uDBFE\\uDC00"',
  '"\\uDBFF\\uDFFF".codePointAt(0)',
  '"\\uDBFE\\uDC00x".slice(2)',
  'encodeURIComponent("\\uDBFE\\uDC00")',
  '"\\uDBFE\\uDC00".normalize("NFC").length',
  '"\\uD800\\uDC00".codePointAt(0)',
  '(s => s[0] === undefined)`\\u{g}`',
  '(s => s.raw[0])`\\u{12g}`',
  '(s => String(s[0]))`\\u{110000}`',
  '`\\u{g}`',
  '`\\x`',
  '08.5',
  '09 + 1',
  '07 + 1',
  '0_7',
  '08n',
  '1_000_000',
  '1__0',
  '0x_1',
  '.5e-3',
  '5.e2',
  '0b102',
  '0o78',
  '1n.toString()',
  '1.toString()',
  '1..toString()',
  'typeof 1.e',
  'a\u2028b',
  'a\u2029b',
  '"a\u2028b".length',
  '/[/]/.source',
  '/a/gg',
  '/(?<n>a)\\k<n>/.test("aa")',
  '"\\u2028\\u2029".length',
  '`a\\\nb`',
  '`a\r\nb`.length',
  '"line1\\\nline2"',
];
for (const src of cases) {
  let msg;
  try { const v = (0, eval)(src); msg = 'ok ' + (typeof v === 'string' ? JSON.stringify(v) : String(v)); }
  catch (e) { msg = e instanceof SyntaxError ? 'SyntaxError: ' + e.message : '(runtime) ' + e.name + ': ' + e.message; }
  console.log(JSON.stringify(src).padEnd(40) + ' -> ' + msg);
}
"""


def test_lexer_escape_and_numeric_edges(run):
    """CATCHES: lexers that accept malformed `\\u` escapes in identifiers, mis-combine surrogate-pair escapes (incl. code points at U+10F800 and U+10FFFF), report wrong SyntaxError messages for unterminated/bad escapes, mishandle invalid escapes in tagged vs untagged templates, legacy octal / non-octal-decimal / separator / BigInt literal rules, `1.toString` vs `1..toString`, duplicate regex flags, U+2028/U+2029 as line terminators (ASI) and inside string literals, and line continuations."""
    r = run(["-e", PROG_LEXER_EDGES])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "lexer_escape_numeric_edges")

DEFER_TLA_FILES = {
    'main.mjs': r"""import defer * as d1 from './forinit.mjs';
import defer * as d2 from './importawait.mjs';
import defer * as d3 from './labeled.mjs';
import defer * as d4 from './syncdefer.mjs';
console.log('main body starts');
console.log('d1', d1.done, 'd2', d2.leafValue, 'd3', d3.lab);
console.log('before touching d4');
console.log('d4', d4.lazy);
""",
    'forinit.mjs': r"""console.log('forinit.mjs evaluating');
let i;
for (i = await Promise.resolve(2); i < 3; i++) console.log('forinit loop', i);
export const done = 'forinit-done';
""",
    'importawait.mjs': r"""console.log('importawait.mjs evaluating');
const nsP = import(await Promise.resolve('./leaf.mjs'));
const ns = await nsP;
export const leafValue = ns.leaf;
""",
    'labeled.mjs': r"""console.log('labeled.mjs evaluating');
outer: { const v = [, await 1]; console.log('labeled sparse', v.length); break outer; }
export const lab = 'lab';
""",
    'syncdefer.mjs': r"""console.log('syncdefer.mjs evaluating (only on first access)');
export const lazy = 'lazy-value';
""",
    'leaf.mjs': r"""export const leaf = 'leaf!';
""",
}


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_import_defer_detects_hidden_top_level_await(run, workdir, tier):
    """CATCHES: `import defer` that fails to recognise a deferred module as async (and so evaluate it eagerly, before the importer) when its only top-level await sits in a for-loop initializer expression, inside an import() argument, or in a sparse array literal inside a labelled block; while a synchronous deferred module still evaluates lazily on first property access."""
    write_files(workdir, DEFER_TLA_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "import_defer_hidden_tla")


PROG_REST_TARGETS_MISC = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
// rest targets assign straight to identifiers (with scopes, consts, immutable fn names, strict)
show('with rest target', () => { const o = { x: 0, y: 0 }; with (o) { [...x] = [1, 2]; ({ ...y } = { k: 3 }); } return JSON.stringify(o); });
show('with rest unscopable', () => { const o = { x: 0, [Symbol.unscopables]: { x: true } }; var x = 'outer'; with (o) { [...x] = [9]; } return JSON.stringify(o) + '|' + x; });
show('const rest target', () => { const c = 1; [...c] = [1]; });
show('nfe rest target sloppy', () => (function nfe() { [...nfe] = [1]; return typeof nfe; })());
show('nfe rest target strict', () => (function nfe() { 'use strict'; [...nfe] = [1]; return typeof nfe; })());
show('strict undeclared rest', () => { 'use strict'; [...undeclaredRestTarget] = []; });
show('sloppy undeclared rest', () => { (function () { ({ ...undeclaredObjRest } = { q: 1 }); })(); return JSON.stringify(undeclaredObjRest); });
show('nfe compound sloppy', () => (function nfe2() { nfe2 += 1; return typeof nfe2; })());
show('nfe compound strict', () => (function nfe3() { 'use strict'; nfe3 += 1; return typeof nfe3; })());
show('global accessor read', () => { Object.defineProperty(globalThis, 'globalAcc', { get() { return 'from-getter'; }, configurable: true }); return globalAcc; });
show('global inherited read', () => { Object.prototype.inheritedGlobalName = 'inherited'; const v = inheritedGlobalName; delete Object.prototype.inheritedGlobalName; return v; });
show('for-of super target', () => { class B {} class D extends B { m() { for (super.x of [1, 2]); for (super['y'] in { k: 1 }); return this.x + ',' + this.y; } } return new D().m(); });
show('for-of private target', () => { class P { #p = 0; m() { for (this.#p of [7, 8]); return this.#p; } } return new P().m(); });
show('for-in member target', () => { const o = {}; for (o.k in { a: 1, b: 2 }); return o.k; });
show('array-like length NaN', () => [Reflect.apply(function () { return arguments.length; }, null, { length: NaN }), Reflect.apply(function () { return arguments.length; }, null, { length: -3 }), Function.prototype.apply.call(function () { return arguments.length; }, null, { length: '2' })].join());
show('fake eval call', () => { function f() { var eval = (x) => 'fake ' + x; return eval('1'); } return f(); });
show('arrow super after ctor', () => { class B {} class D extends B { constructor() { super(); this.again = () => super(); } } const d = new D(); try { d.again(); } catch (e) { return e.name + ': ' + e.message; } });
show('arrow super before', () => { class B { constructor() { this.b = 1; } } class D extends B { constructor() { const f = () => super(); f(); this.d = 2; } } const d = new D(); return d.b + d.d; });
show('static block using throws', () => { const log = []; try { class A { static { using r = { [Symbol.dispose]() { log.push('disposed'); } }; throw new Error('sb'); } } } catch (e) { log.push(e.message); } return log.join(); });
show('nested obj pattern no default', () => { let y; ({ x: { y } } = { x: undefined }); });
show('hasInstance undefined', () => { function F() {} Object.defineProperty(F, Symbol.hasInstance, { value: undefined }); return (new F() instanceof F) + ',' + ({} instanceof F); });
show('toPrimitive null', () => ({ [Symbol.toPrimitive]: null, valueOf() { return 4; } }) + 1);
show('toPrimitive undefined', () => `${{ [Symbol.toPrimitive]: undefined, toString() { return 'ts'; } }}`);
show('toPrimitive noncallable', () => ({ [Symbol.toPrimitive]: 5 }) + 1);
show('sym anon names', () => { const s1 = Symbol(), s2 = Symbol('d'); const o = { [s1]: () => {}, [s2]: class {} }; return JSON.stringify([o[s1].name, o[s2].name]); });
show('getter name sym', () => { const s = Symbol('gs'); const o = { get [s]() { return 1; }, set [s](v) {} }; const d = Object.getOwnPropertyDescriptor(o, s); return d.get.name + '|' + d.set.name; });
show('class sym method names', () => { const s = Symbol(); class C { [s]() {} static [Symbol('st')]() {} } return JSON.stringify([C.prototype[s].name, C[Object.getOwnPropertySymbols(C)[0]].name]); });
// function bodies containing class decorators, `...arguments` rest bindings, import() options
const scanDec = (v, c) => { c.addInitializer(function () { this.decorated = c.kind; }); };
function withClassDecorator() { @scanDec class Inner {} return Inner.decorated; }
function withRestArguments(o) { const { ...arguments } = o; return JSON.stringify(arguments); }
function withImportOptions() { return import('./never-loaded.mjs', { with: 1 }).then(() => 'loaded', (e) => e.name + ': ' + e.message); }
show('fn with class decorator', () => withClassDecorator());
show('fn with rest arguments', () => withRestArguments({ p: 1, q: 2 }));
withImportOptions().then((r) => console.log('fn with import options', r));
(async () => {
  const as = new AsyncDisposableStack();
  await as.disposeAsync();
  try { as.adopt(1, async () => {}); } catch (e) { console.log('adopt after dispose', e.name + ': ' + e.message); }
  try { as.defer(async () => {}); } catch (e) { console.log('defer after dispose', e.name + ': ' + e.message); }
  try { as.use({ [Symbol.asyncDispose]() {} }); } catch (e) { console.log('use after dispose', e.name + ': ' + e.message); }
  const s2 = new AsyncDisposableStack();
  const bad = Promise.resolve('x');
  Object.defineProperty(bad, 'constructor', { get() { throw new Error('ctor getter in disposer'); } });
  s2.defer(() => bad);
  s2.defer(() => { throw new Error('sync disposer throw'); });
  try { await s2.disposeAsync(); console.log('no error'); } catch (e) { console.log('disposeAsync error', e.name, e.message, e.error && e.error.message, e.suppressed && e.suppressed.message); }
})();
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_rest_targets_global_lookup_and_disposal_stacks(run, tier):
    """CATCHES: array/object rest elements assigned to plain identifiers that bypass `with` object environments (and @@unscopables), const / named-function-expression immutability (sloppy no-op vs strict TypeError) or strict undeclared ReferenceErrors; global reads of accessor or inherited global-object properties; for-in/of heads targeting super/private/member references; CreateListFromArrayLike length coercion; a shadowing local `eval` treated as direct eval; arrow `super()` after the constructor finished; static-block `using` disposal on throw; explicit undefined/null @@hasInstance/@@toPrimitive; symbol-keyed function names; AsyncDisposableStack adopt/defer/use after disposal and disposeAsync error aggregation when a disposer's promise has a throwing constructor getter."""
    r = run([*tier, "-e", PROG_REST_TARGETS_MISC])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "rest_targets_global_lookup_disposal")

IMPORT_BINDING_FILES = {
    'main.mjs': r"""import './a.mjs';
import { counter, fixed, inc } from './dep.mjs';
import * as ns from './dep.mjs';
const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
show('typeof import', () => typeof counter + ',' + typeof fixed + ',' + typeof missingName);
show('compound on import', () => { counter += 1; });
show('logical on import', () => { counter ||= 5; return counter; });
show('nullish on import', () => { counter ??= 5; });
show('update on import', () => { counter++; });
show('assign on import', () => { fixed = 'x'; });
show('destructure into import', () => { [counter] = [9]; });
show('live after inc', () => { inc(); return counter + ',' + ns.counter; });
show('ns assign', () => { ns.counter = 5; });
show('ns delete', () => delete ns.counter);
show('ns define', () => Object.defineProperty(ns, 'counter', { value: 1 }));
show('Reflect.set ns recv new key', () => Reflect.set({}, 'brandNew', 1, ns));
show('ns has/keys', () => ['counter' in ns, 'nope' in ns, Object.keys(ns).join(), Reflect.ownKeys(ns).length].join('|'));
show('ns getOwnPropertyDescriptor', () => JSON.stringify(Object.getOwnPropertyDescriptor(ns, 'fixed')));
show('ns extensible/frozen', () => [Object.isExtensible(ns), Object.isFrozen(ns), Object.isSealed(ns)].join());
show('ns proto set', () => [Reflect.setPrototypeOf(ns, {}), Reflect.setPrototypeOf(ns, null)].join());
""",
    'a.mjs': r"""import { bVal, readA } from './b.mjs';
export let aVal = 'a-initialized';
console.log('a.mjs body: typeof bVal', typeof bVal, bVal, 'readA()', readA());
""",
    'b.mjs': r"""import { aVal } from './a.mjs';
let tdz;
try { tdz = typeof aVal; } catch (e) { tdz = e.name + ': ' + e.message; }
console.log('b.mjs body (a not yet evaluated): typeof aVal ->', tdz);
export const bVal = 'b-value';
export function readA() { return aVal; }
""",
    'dep.mjs': r"""export let counter = 1;
export const fixed = 'F';
export function inc() { counter++; }
""",
}


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_import_binding_tdz_and_immutability(run, workdir, tier):
    """CATCHES: `typeof` of an imported binding that does not follow the import to the exporter's binding (no TDZ ReferenceError inside a cycle, wrong type afterwards), compound/update/destructuring assignment to import bindings that silently succeed or report a different TypeError, logical assignment that writes when it should short-circuit, and module namespace objects whose [[Set]]/[[Delete]]/[[DefineOwnProperty]]/[[SetPrototypeOf]]/integrity answers deviate."""
    write_files(workdir, IMPORT_BINDING_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "import_binding_tdz_immutability")

PROG_SHARED_RESIZABLE_TA = r"""const show = (label, f) => { try { const v = f(); console.log(label, typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { console.log(label, '!' + e.name + ': ' + e.message); } };
const sab = new SharedArrayBuffer(32);
const i32 = new Int32Array(sab);
const u8 = new Uint8Array(sab);
const f64 = new Float64Array(sab, 8, 2);
const b64 = new BigInt64Array(sab, 24, 1);
show('sab write/read', () => { i32[0] = -2; u8[4] = 255; f64[0] = 1.5; b64[0] = -9n; return [i32[0], u8[4], f64[0], String(b64[0]), u8[0], u8[3]].join(); });
show('sab views share', () => { const again = new Uint32Array(sab); return again[0] + ',' + again[1]; });
show('sab set/slice', () => { const t = new Uint8Array(4); t.set(u8.subarray(0, 4)); const sl = u8.slice(0, 5); return Array.from(t).join() + '|' + Array.from(sl).join(); });
show('sab set from', () => { const dst = new Int32Array(sab, 16, 2); dst.set([7, 8]); return Array.from(new Int32Array(sab, 16, 2)).join(); });
show('sab atomics', () => [Atomics.add(i32, 0, 5), Atomics.load(i32, 0), Atomics.exchange(i32, 0, 1), Atomics.compareExchange(i32, 0, 1, 2), i32[0], String(Atomics.add(b64, 0, 10n)), String(b64[0])].join());
show('sab fill/copyWithin/sort', () => { const t = new Int8Array(sab, 0, 8); t.fill(3); t[1] = -1; t.copyWithin(4, 0, 2); return Array.from(t.sort()).join(); });
show('sab DataView', () => { const dv = new DataView(sab); dv.setInt16(0, -300); dv.setBigUint64(8, 2n ** 63n); return dv.getInt16(0) + ',' + dv.getBigUint64(8) + ',' + dv.getUint8(0); });
show('sab TextDecoder', () => { const t = new Uint8Array(new SharedArrayBuffer(3)); t.set([104, 105, 33]); return String.fromCharCode(...t); });
// resizable ArrayBuffer: out-of-bounds after shrink
show('rab shrink oob', () => { const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const fixed = new Uint8Array(rab, 0, 8); const track = new Uint16Array(rab); fixed[7] = 5; rab.resize(4); return [fixed.length, track.length, fixed[7], String(track[3]), fixed.byteOffset].join(); });
show('rab oob writes ignored', () => { const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const t = new Float32Array(rab); const tb = new BigUint64Array(rab); rab.resize(2); t[1] = 3; tb[0] = 5n; rab.resize(8); return Array.from(t).join() + '|' + String(tb[0]); });
show('rab oob methods', () => { const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const t = new Uint8Array(rab, 4, 4); rab.resize(2); return t.length + ',' + t.byteLength + ',' + t.byteOffset; });
show('rab oob method throws', () => { const rab = new ArrayBuffer(8, { maxByteLength: 16 }); const t = new Uint8Array(rab, 4, 4); rab.resize(2); return t.fill(1); });
show('detached reads', () => { const ab = new ArrayBuffer(8); const t = new Int16Array(ab); const tb = new BigInt64Array(ab); ab.transfer(); t[0] = 1; tb[0] = 1n; return [t.length, String(t[0]), String(tb[0]), ab.detached].join(); });
// immutable ArrayBuffer (transferToImmutable)
show('immutable buffer', () => { if (typeof ArrayBuffer.prototype.transferToImmutable !== 'function') return 'n/a'; const ab = new ArrayBuffer(4); new Uint8Array(ab)[0] = 7; const im = ab.transferToImmutable(); const t = new Uint8Array(im); t[0] = 9; return [im.immutable, t[0]].join(); });
show('immutable buffer strict', () => { 'use strict'; if (typeof ArrayBuffer.prototype.transferToImmutable !== 'function') return 'n/a'; const t = new Uint8Array(new ArrayBuffer(2).transferToImmutable()); t[0] = 1; return 'no throw'; });
show('immutable bigint strict', () => { 'use strict'; if (typeof ArrayBuffer.prototype.transferToImmutable !== 'function') return 'n/a'; const t = new BigInt64Array(new ArrayBuffer(8).transferToImmutable()); t[0] = 1n; return 'no throw'; });
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_typed_arrays_over_shared_resizable_immutable_buffers(run, tier):
    """CATCHES: TypedArray/DataView/Atomics element access over SharedArrayBuffer storage that does not share bytes between views (incl. BigInt64 and Float64 views at offsets, set/slice/fill/copyWithin/sort), length-tracking vs fixed views over a shrunk resizable ArrayBuffer (out-of-bounds lengths, ignored writes, TypeError from methods), detached buffers, and writes through an immutable ArrayBuffer (ignored in sloppy code, TypeError in strict code)."""
    r = run([*tier, "-e", PROG_SHARED_RESIZABLE_TA])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "shared_resizable_immutable_typed_arrays")
