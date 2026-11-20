"""ES module system semantics: namespaces, live bindings, star re-exports, cycles, top-level await,
`import defer`, link/load errors and module-only early errors.

Programs are run under all three execution tiers (JIT, interpreter, bytecode) where the module
bodies do real work, and must produce the same golden output in each.
"""

import json

import pytest

from conftest import golden, outcome, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

NAMESPACE_FILES = {
    "main.mjs": r"""import * as ns from './lib.mjs';
import def, { counter, inc, renamed as alias, 'string name' as strName, Klass } from './lib.mjs';
import { star1, star2, nsReexport, default as libDefault } from './barrel.mjs';
import anonFn from './anon-fn.mjs';
import AnonClass from './anon-class.mjs';
import exprDefault from './expr-default.mjs';
const log = (...a) => console.log(...a);
log('top-level this', this);
log('strict mode', (function () { return this; })() === undefined);
log('default', def, libDefault === def);
log('live binding before', counter);
inc(); inc();
log('live binding after', counter, ns.counter);
try { counter = 5; } catch (e) { log('assign import', e.name + ': ' + e.message); }
try { ns.counter = 5; } catch (e) { log('assign ns prop', e.name + ': ' + e.message); }
try { ns.newProp = 1; } catch (e) { log('add ns prop', e.name + ': ' + e.message); }
try { delete ns.counter; } catch (e) { log('delete ns prop', e.name + ': ' + e.message); }
log('delete missing ns prop', delete ns.nothere);
log('alias & string name', alias, strName, new Klass().who());
log('ns keys', Object.keys(ns).join(','));
log('ns ownKeys', Reflect.ownKeys(ns).map(String).join(','));
log('ns tag', Object.prototype.toString.call(ns), ns[Symbol.toStringTag], Object.getPrototypeOf(ns), Object.isExtensible(ns), Object.isSealed(ns), Object.isFrozen(ns));
log('ns descriptor', JSON.stringify(Object.getOwnPropertyDescriptor(ns, 'counter')));
log('ns in', 'inc' in ns, 'nope' in ns, Object.hasOwn(ns, 'default'));
log('ns define same', Reflect.defineProperty(ns, 'counter', { value: ns.counter }), Reflect.defineProperty(ns, 'counter', { value: 999 }));
log('ns setPrototypeOf', Reflect.setPrototypeOf(ns, null), Reflect.setPrototypeOf(ns, {}));
log('Reflect.set with ns receiver', Reflect.set({}, 'brandNew', 5, ns), ns.counter);
try { Object.defineProperty(ns, 'counter', { value: 1, writable: false }); } catch (e) { log('ns defineProperty incompatible', e.name); }
log('ns getOwnPropertyDescriptor missing', Object.getOwnPropertyDescriptor(ns, 'nope'), Reflect.has(ns, Symbol.toStringTag), Reflect.ownKeys(ns).length);
log('star re-exports', star1, star2, nsReexport.inner, Object.prototype.toString.call(nsReexport));
log('anonymous defaults', anonFn.name, anonFn(), AnonClass.name, new AnonClass().tag, exprDefault);
import { getOrder } from './order.mjs';
log('evaluation order', getOrder());
""",
    "lib.mjs": r"""import { record } from './order.mjs';
record('lib');
export let counter = 0;
export function inc() { counter++; }
const internal = 'renamed-value';
export { internal as renamed, internal as 'string name' };
export class Klass { who() { return 'Klass'; } }
export default 'lib-default';
export var zeta = 'z', alpha = 'a';
""",
    "barrel.mjs": r"""import { record } from './order.mjs';
record('barrel');
export * from './star-a.mjs';
export * from './star-b.mjs';
export * as nsReexport from './inner.mjs';
export { default } from './lib.mjs';
""",
    "star-a.mjs": r"""import { record } from './order.mjs';
record('star-a');
export const star1 = 'from-a';
export const dup = 'a-dup';
export default 'star-a-default-not-reexported';
""",
    "star-b.mjs": r"""import { record } from './order.mjs';
record('star-b');
export const star2 = 'from-b';
export const dup = 'b-dup';
""",
    "inner.mjs": r"""import { record } from './order.mjs';
record('inner');
export const inner = 'inner-value';
""",
    "anon-fn.mjs": r"""export default function () { return 'anon fn called'; }
""",
    "anon-class.mjs": r"""export default class { tag = 'anon class instance'; }
""",
    "expr-default.mjs": r"""let v = 'expr';
export default v + '-default';
v = 'changed';
""",
    "order.mjs": r"""const order = [];
export function record(n) { order.push(n); }
export function getOrder() { return order.join(' > '); }
""",
}

CYCLE_TLA_FILES = {
    "main.mjs": r"""import { a, useB, fnHoisted } from './cyc-a.mjs';
console.log('main: a =', a, '| useB() =', useB(), '| hoisted from b =', fnHoisted());
console.log('main: tla module values');
import { slow, fast } from './tla-join.mjs';
console.log('main:', slow, fast);
""",
    "cyc-a.mjs": r"""console.log('cyc-a: start');
import { b, readA, fnHoisted } from './cyc-b.mjs';
export let a = 'A';
export function useB() { return b + '+' + readA(); }
export { fnHoisted };
console.log('cyc-a: end, b =', b);
""",
    "cyc-b.mjs": r"""console.log('cyc-b: start');
import { a } from './cyc-a.mjs';
let early;
try { early = a; } catch (e) { early = e.name + ': ' + e.message; }
console.log('cyc-b: reading a during cycle ->', early);
export const b = 'B';
export function readA() { return a; }
export function fnHoisted() { return 'fn-from-b'; }
console.log('cyc-b: end');
""",
    "tla-join.mjs": r"""import { slow } from './tla-slow.mjs';
import { fast } from './tla-fast.mjs';
console.log('tla-join: both deps done');
export { slow, fast };
""",
    "tla-slow.mjs": r"""console.log('tla-slow: before await');
export const slow = await new Promise((r) => setTimeout(() => r('slow-value'), 10));
console.log('tla-slow: after await');
""",
    "tla-fast.mjs": r"""console.log('tla-fast: sync body runs while slow is pending');
await null;
console.log('tla-fast: after await null');
export const fast = 'fast-value';
""",
}

LINK_ERROR_FILES = {
    "dyn.mjs": r"""const show = async (label, p) => { try { const v = await p; console.log(label, 'ok', typeof v === 'object' ? Object.keys(v).join(',') : v); } catch (e) { console.log(label, e.name + ': ' + e.message.replaceAll(import.meta.dirname, '<dir>')); } };
await show('missing export', import('./missing.mjs'));
await show('ambiguous import', import('./ambimp.mjs'));
await show('ambiguous ns', import('./ambns.mjs'));
await show('not found', import('./notfound.mjs'));
await show('duplicate export', import('./syn.mjs'));
await show('body throws', import('./throws.mjs'));
await show('body throws again (cached error)', import('./throws.mjs'));
await show('same ns twice', Promise.all([import('./a.mjs'), import('./a.mjs')]).then(([x, y]) => x === y));
await show('non-string specifier', import({ toString() { return './a.mjs'; } }));
await show('dyn options bad', import('./a.mjs', 5));
await show('dyn options undefined', import('./a.mjs', undefined));
await show('dyn with undefined', import('./a.mjs', { with: undefined }));
await show('dyn with non-object', import('./a.mjs', { with: 5 }));
await show('dyn with non-string value', import('./a.mjs', { with: { type: 1 } }));
await show('dyn json attribute', import('./data.json', { with: { type: 'json' } }).then((m) => JSON.stringify(m.default)));
await show('dyn json via proxy attributes', import('./data.json', { with: new Proxy({ type: 'json' }, {}) }).then((m) => m.default.s));
await show('dyn json without attribute', import('./data.json').then((m) => typeof m.default));
await show('text attribute escapes', import('./weird.txt', { with: { type: 'text' } }).then((m) => JSON.stringify(m.default)));
await show('bytes attribute', import('./weird.txt', { with: { type: 'bytes' } }).then((m) => m.default.constructor.name + ' ' + m.default.length + ' ' + m.default[1]));
await show('indirect ambiguous re-export', import('./reexp-amb.mjs'));
await show('unexported await-in-sloppy-fn', import('./awaitfn.mjs'));
await show('undeclared export', import('./undecl.mjs'));
await show('html comment in module', import('./htmlc.mjs'));
await show('import in function', import('./nested-import.mjs'));
await show('source phase of source-text module', import('./srcimp.mjs'));
await show('module code is strict', import('./strictmod.mjs').then((m) => m.results));
console.log('meta', typeof import.meta, Object.getPrototypeOf(import.meta), import.meta.url.startsWith('file://'), import.meta.url.endsWith('/dyn.mjs'), import.meta.filename.endsWith('dyn.mjs'), import.meta.dirname.endsWith('/work'), Object.keys(import.meta).join(','));
""",
    "data.json": r"""{"k": [1, 2], "s": "json"}
""",
    "weird.txt": b'q"uote back\\slash\nline\r\nCRLF\ttab\x01ctl\xe2\x80\xa8ls\xe2\x80\xa9ps end',
    "reexp-amb.mjs": r"""export { dup } from './amb.mjs';
""",
    "a.mjs": r"""export const dup = 1;
""",
    "b.mjs": r"""export const dup = 2;
""",
    "amb.mjs": r"""export * from './a.mjs';
export * from './b.mjs';
export const ok = 'ok';
""",
    "missing.mjs": r"""import { nope } from './a.mjs';
""",
    "ambimp.mjs": r"""import { dup } from './amb.mjs';
""",
    "ambns.mjs": r"""import * as ns from './amb.mjs';
console.log('ambiguous names hidden from namespace:', Object.keys(ns).join(','), 'dup' in ns);
""",
    "notfound.mjs": r"""import './does-not-exist.mjs';
""",
    "syn.mjs": r"""export const x = 1;
export const x = 2;
""",
    "throws.mjs": r"""console.log('throws.mjs running');
throw new RangeError('module body failed');
""",
    "awaitfn.mjs": r"""function f() { await 1; }
""",
    "undecl.mjs": r"""export { notDeclared };
""",
    "htmlc.mjs": r"""const x = 1;
<!-- not a comment in modules
""",
    "nested-import.mjs": r"""function f() { import x from './a.mjs'; }
""",
    "srcimp.mjs": r"""import source s from './a.mjs';
""",
    "strictmod.mjs": r"""const r = [];
try { undeclaredInModule = 1; } catch (e) { r.push(e.name); }
try { Object.freeze([1]).push(2); } catch (e) { r.push(e.name); }
export const results = r.join(',');
""",
}

DEFER_FILES = {
    "main.mjs": r"""import defer * as lazy from './lazy.mjs';
import { log } from './log.mjs';
log('main: after imports (lazy not yet evaluated)');
log('main: typeof lazy =', typeof lazy, Object.prototype.toString.call(lazy));
log('main: touching lazy.value ->', lazy.value);
log('main: second access ->', lazy.value, lazy.other);
log('main: keys', Object.keys(lazy).join(','));
const dyn = await import.defer('./lazy2.mjs');
log('main: got deferred dynamic ns');
log('main: lazy2.x =', dyn.x);
try { const s = await import.source('./lazy.mjs'); log('source phase', typeof s); } catch (e) { log('source phase error', e.name + ': ' + e.message); }
""",
    "log.mjs": r"""export const log = (...a) => console.log(...a);
""",
    "lazy.mjs": r"""import { log } from './log.mjs';
log('lazy.mjs: evaluating now');
export const value = 'lazy-value';
export const other = 'other';
""",
    "lazy2.mjs": r"""console.log('lazy2.mjs: evaluating');
export const x = 'x2';
""",
}

CJS_DYNAMIC_FILES = {
    "s.cjs": r"""console.log('before import call');
const p = import('./dep.mjs');
console.log('after import call', p instanceof Promise);
p.then((ns) => { console.log('resolved', ns.v, ns.default.name, ns.default()); return import('./c.cjs'); }).then((c) => console.log('cjs ns', Object.keys(c).join(), c.default.cjs, c.extra));
""",
    "dep.mjs": r"""console.log("dep evaluated"); export const v = "dep-v"; export default function hello() { return "hello" }
""",
    "c.cjs": r"""module.exports = { cjs: true, n: 1 }; module.exports.extra = "x";
""",
}

FAILING_GRAPH_FILES = {
    "main.mjs": r"""import "./mid.mjs";
console.log("main never runs");
""",
    "mid.mjs": r"""import "./leaf.mjs";
console.log("mid never runs");
""",
    "leaf.mjs": r"""console.log("leaf runs");
throw new TypeError("leaf failed");
""",
    "main2.mjs": r"""import "./bad-syntax.mjs";
console.log("never");
""",
    "bad-syntax.mjs": r"""console.log("not run");
let x = ;
""",
    "main3.mjs": r"""import { x } from "./tla-reject.mjs";
""",
    "tla-reject.mjs": r"""await Promise.resolve();
throw new Error("tla rejected");
export const x = 1;
""",
}

REEXPORT_FILES = {
    "main.mjs": r"""import * as hub from './hub.mjs';
import { nsAlias, renamedA, a, shared, onlyC, deferredReexport, setA } from './hub.mjs';
import * as s1 from './s1.mjs';
const log = (...x) => console.log(...x);
log('hub keys', Object.keys(hub).join(','));
log('ns re-export is the same object', nsAlias === hub.nsAlias, Object.prototype.toString.call(nsAlias), nsAlias.a);
log('re-exported import is live', renamedA, a);
setA('A2');
log('after setA', renamedA, a, hub.a, nsAlias.a);
log('same binding via two star paths', shared, onlyC);
log('deferred re-export tag', Object.prototype.toString.call(deferredReexport));
log('star cycle keys', Object.keys(s1).join(','));
try { await import('./x.mjs'); } catch (e) { log('re-export cycle', e.name + ': ' + e.message); }
log('lazy value', deferredReexport.lazyValue);
const again = await import('./a.mjs');
log('dynamic import of evaluated module', again.a, again === nsAlias);
const lazyAgain = await import('./lazy.mjs');
log('dynamic import of evaluated deferred module', lazyAgain.lazyValue);
""",
    "hub.mjs": r"""import * as nsA from './a.mjs';
import { a as importedA } from './a.mjs';
import defer * as lazyNs from './lazy.mjs';
export { nsA as nsAlias, importedA as renamedA, lazyNs as deferredReexport };
export * from './a.mjs';
export * from './c.mjs';
export { a } from './a.mjs';
""",
    "a.mjs": r"""export let a = 'a';
export const shared = 'shared-from-a';
export function setA(v) { a = v; }
""",
    "c.mjs": r"""export { shared } from './a.mjs';
export const onlyC = 'only-c';
""",
    "lazy.mjs": r"""console.log('lazy.mjs evaluated');
export const lazyValue = 'lazy!';
""",
    "s1.mjs": r"""export * from './s2.mjs';
export const s1 = 1;
""",
    "s2.mjs": r"""export * from './s1.mjs';
export const s2 = 2;
""",
    "x.mjs": r"""export { loop } from './y.mjs';
""",
    "y.mjs": r"""export { loop } from './x.mjs';
""",
}

DEFER_EDGE_FILES = {
    "main.mjs": r"""import defer * as asyncDep from './async-dep.mjs';
import defer * as throwing from './throwing.mjs';
import defer * as cyc from './cyc.mjs';
import defer * as again from './async-dep.mjs';
import defer * as wrapper from './wrapper.mjs';
console.log('main body starts');
console.log('same deferred object for repeated import defer', asyncDep === again);
console.log('async dep already evaluated eagerly:', globalThis.asyncDepRan === true);
console.log('async dep value', asyncDep.v);
for (let i = 0; i < 2; i++) {
  try { throwing.x; } catch (e) { console.log('throwing access', i, e.name + ': ' + e.message); }
}
console.log('in operator on deferred', 'value' in cyc, globalThis.cycRan);
console.log('cyc value', cyc.value);
console.log('wrapper (sync, deferred) over TLA dependency', wrapper.w, wrapper.inner);
try { await import.defer('./missing-deferred.mjs'); } catch (e) { console.log('import.defer missing', e.name + ': ' + e.message.replaceAll(import.meta.dirname, '<dir>')); }
const dd = await import.defer('./wrapper.mjs');
console.log('import.defer of already-evaluated module', dd === wrapper, dd.w);
""",
    "async-dep.mjs": r"""console.log('async-dep: start (has top-level await)');
await null;
globalThis.asyncDepRan = true;
export const v = 'async-v';
""",
    "throwing.mjs": r"""console.log('throwing.mjs runs once');
throw new EvalError('deferred module failed');
export const x = 1;
""",
    "cyc.mjs": r"""import { peek } from './cyc-helper.mjs';
globalThis.cycRan = true;
console.log('cyc.mjs evaluating; peek from helper ->', peek());
export const value = 'cyc-value';
""",
    "cyc-helper.mjs": r"""import defer * as back from './cyc.mjs';
export function peek() { try { return back.value; } catch (e) { return e.name + ': ' + e.message; } }
""",
    "wrapper.mjs": r"""console.log('wrapper.mjs evaluated (lazily)');
export { inner } from './tla-inner.mjs';
export const w = 'wrapper';
""",
    "tla-inner.mjs": r"""console.log('tla-inner.mjs: evaluated eagerly despite defer');
await null;
export const inner = 'inner-value';
""",
}

MODULE_EARLY_CASES = [
  "var await = 1;",
  "export default 1; export default 2;",
  "export const a = 1; export { a };",
  "const a = 1; export { a as b, a as b };",
  "with ({}) {}",
  "var x = 010;",
  "delete x;",
  "export { x };",
  "import { a, a } from './ok.mjs';",
  "import { a } from './ok.mjs'; let a;",
  "new.target;",
  "return 1;",
  "arguments;",
  "label: label: ;",
  "export * as default from './ok.mjs'; export default 1;",
  "import { 'not-identifier' } from './ok.mjs';",
  "export { 'str' } from './ok.mjs';",
  "export { a as 'x' }; const a = 1;",
  "import x, * as y, { z } from './ok.mjs';",
  "import * as ns from './ok.mjs'; ns = 1;",
  "export let let1 = 1; yield = 1;",
  "if (1) { export const z = 1; }",
  "import x from './ok.mjs' with { type: 'json', type: 'json' };",
  "import x from './ok.mjs' with { type: 1 };",
  "await;",
  "export async function f() {} export function f() {}",
  "const x = import.meta; import.meta = 1;",
  "function f() { return import.meta.url.length > 0; } export const ok = f();",
  "export const ok = typeof this;",
  "export const ok = (() => typeof arguments)();",
]

MODULE_EARLY_MAIN = r"""const cases = CASES_PLACEHOLDER;
for (let i = 0; i < cases.length; i++) {
  let msg;
  try { const ns = await import('./c' + String(i).padStart(2, '0') + '.mjs'); msg = 'ok ' + JSON.stringify(ns.ok ?? null); }
  catch (e) { msg = e.name + ': ' + e.message.replaceAll(import.meta.dirname, '<dir>'); }
  console.log(JSON.stringify(cases[i]).padEnd(60), '->', msg);
}
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_namespace_objects_and_live_bindings(run, workdir, tier):
    """CATCHES: module namespace objects with wrong exotic behaviour (sorted keys, @@toStringTag 'Module', null proto, non-extensible, writable-but-unassignable props, defineProperty/setPrototypeOf results), stale (non-live) imported bindings, broken string export names, export * conflict hiding, export * as ns, anonymous default names, and wrong dependency evaluation order."""
    write_files(workdir, NAMESPACE_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "namespace_live_bindings")


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_cycles_and_top_level_await(run, workdir, tier):
    """CATCHES: cyclic module graphs evaluated in the wrong order or without TDZ for not-yet-initialised imports, hoisted function exports unavailable inside a cycle, and top-level await that blocks sibling modules or lets dependents run before their async dependencies settle."""
    write_files(workdir, CYCLE_TLA_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "cycles_tla")


def test_link_and_load_errors(run, workdir):
    """CATCHES: module loaders that report missing/ambiguous exports, missing files, duplicate exports, module-body throws (and their cached re-throw), bad import() options and `with` attributes (non-object, non-string values, proxies, JSON type), module-only syntax errors, source-phase imports of source-text modules or import.meta shape with different error classes or messages."""
    write_files(workdir, LINK_ERROR_FILES)
    r = run(["dyn.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "link_load_errors")


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_import_defer(run, workdir, tier):
    """CATCHES: `import defer` that evaluates the deferred module eagerly (or never), a deferred namespace without the 'Deferred Module' tag, import.defer() that evaluates on load instead of first property access, and import.source of a plain module not rejecting with SyntaxError."""
    write_files(workdir, DEFER_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "import_defer")


def test_module_only_early_errors(run, workdir):
    """CATCHES: module parsing that does not apply module-goal rules -- await as identifier, implicit strict mode (with, octal, delete), duplicate/undeclared exports, import binding clashes, export placement, import attribute validation, module-level this/arguments, import.meta assignment -- or reports different messages."""
    files = {f"c{i:02d}.mjs": src + "\n" for i, src in enumerate(MODULE_EARLY_CASES)}
    files["ok.mjs"] = "export const a = 1, z = 2; export default 'd';\n"
    files["main.mjs"] = MODULE_EARLY_MAIN.replace("CASES_PLACEHOLDER", json.dumps(MODULE_EARLY_CASES))
    write_files(workdir, files)
    r = run(["main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "module_early_errors")


def test_dynamic_import_from_commonjs_and_eval(run, workdir):
    """CATCHES: import() from a CommonJS script that does not return a promise, evaluates the ES module at a different time, exposes a CommonJS module without default+named keys, or an -e script whose import() does not reject with the 'no module loader configured' TypeError."""
    write_files(workdir, CJS_DYNAMIC_FILES)
    r = run(["s.cjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    r2 = run(["-e", "import('./dep.mjs').then(() => console.log('loaded'), (e) => console.log('rejected', e.name + ': ' + e.message))"])
    assert (r2.returncode, r2.stderr) == (0, b"")
    assert r.stdout + b"--- -e\n" + r2.stdout == golden(__file__, "dynamic_import_cjs_eval")


def test_failing_dependency_reporting(run, workdir):
    """CATCHES: module graphs whose failing leaf (body throw, syntax error, rejected top-level await) still runs dependents, exits 0, or reports a different set of 'Uncaught (in promise)' / 'Uncaught' lines on stderr."""
    write_files(workdir, FAILING_GRAPH_FILES)
    blob = b"".join(b"=== " + m.encode() + b"\n" + outcome(run([m])) for m in ["main.mjs", "main2.mjs", "main3.mjs"])
    assert blob == golden(__file__, "failing_dependency_reporting")


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_reexport_resolution(run, workdir, tier):
    """CATCHES: export resolution bugs -- re-exported namespace imports and named imports that are not the original live binding, the same binding reached through two `export *` paths treated as ambiguous, cyclic `export *` graphs, cyclic named re-exports not reported as a missing export, and deferred namespaces re-exported or evaluated too early."""
    write_files(workdir, REEXPORT_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "reexport_resolution")


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_import_defer_edge_cases(run, workdir, tier):
    """CATCHES: `import defer` that does not eagerly evaluate deferred modules with top-level await, returns different objects for repeated deferred imports of one module, re-runs (or swallows) a throwing deferred module, or lets a module read its own deferred namespace mid-evaluation instead of throwing a TypeError."""
    write_files(workdir, DEFER_EDGE_FILES)
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "import_defer_edge_cases")


TLA_POSITIONS = {
  "if-test": "if (await Promise.resolve(true)) { log('in if'); }",
  "for-init": "for (let i = await 0; i < 1; i++) { log('in for'); }",
  "while-test": "let w = 0; while (await (w++ < 1)) { log('in while'); }",
  "do-while": "let d = 0; do { log('in do'); } while (await (++d < 1));",
  "switch-disc": "switch (await 'k') { case 'k': log('in switch'); }",
  "switch-case-body": "switch (1) { case 1: await null; log('in case'); }",
  "try-block": "try { await null; log('in try'); } catch {}",
  "catch-block": "try { throw 1; } catch { await null; log('in catch'); }",
  "finally-block": "try {} finally { await null; log('in finally'); }",
  "object-literal": "const o = { k: await 'v' }; log('obj', o.k);",
  "object-spread": "const o2 = { ...(await { s: 1 }) }; log('spread', o2.s);",
  "array-literal": "const a = [1, await 2]; log('arr', a.join());",
  "call-spread": "log('call-spread', ...(await ['x', 'y']));",
  "new-args": "const dt = new Date(await 0); log('new', dt.getTime());",
  "tagged-tag": "const t = (await ((s) => 'tagged ' + s[0]))`tpl`; log(t);",
  "conditional": "log('cond', true ? await 'c' : 0);",
  "sequence": "const sq = (0, await 'seq'); log(sq);",
  "member-base": "log('member', (await 'abc').length);",
  "index-expr": "log('index', [10, 20][await 1]);",
  "logical-assign": "let la = null; la ??= await 'la'; log(la);",
  "unary": "log('unary', -(await 5), typeof await 'x');",
  "template-sub": "log(`tpl ${await 'sub'}`);",
  "labelled-block": "lbl: { await null; log('labelled'); break lbl; }",
  "for-of-iterable": "for (const v of await [1]) log('for-of', v);",
  "for-in-object": "for (const k in await { kk: 1 }) log('for-in', k);",
  "for-await": "for await (const v of [Promise.resolve('fa')]) log('for-await', v);",
  "export-const": "export const ex = await 'exported';",
  "arrow-not-tla": "const f = async () => { await null; }; log('arrow only: module is sync');",
  "binary": "log('binary', 1 + await 2);",
  "assign": "let as; as = await 'assigned'; log(as);",
}


def _tla_position_files():
    files = {"log.mjs": "export const log = (...a) => console.log(...a);\n",
             "sync-sibling.mjs": "import { log } from './log.mjs';\nlog('sync sibling runs');\n"}
    for i, (name, body) in enumerate(TLA_POSITIONS.items()):
        files[f"p{i:02d}.mjs"] = f"import {{ log }} from './log.mjs';\nlog('start {name}');\n{body}\nlog('end {name}');\n"
    files["main.mjs"] = ("".join(f"import './p{i:02d}.mjs';\n" for i in range(len(TLA_POSITIONS)))
                         + "import './sync-sibling.mjs';\nimport { log } from './log.mjs';\nlog('main body');\n")
    return files


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_top_level_await_detection(run, workdir, tier):
    """CATCHES: top-level-await detection that misses `await` in some syntactic position (if/while/do/for heads, switch, try/catch/finally, literals, spreads, new/call args, tags, conditionals, templates, labels, for-of/in/await, exports), so a module runs synchronously or its siblings and dependents resume in a different order."""
    write_files(workdir, _tla_position_files())
    r = run([*tier, "main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "top_level_await_detection")
