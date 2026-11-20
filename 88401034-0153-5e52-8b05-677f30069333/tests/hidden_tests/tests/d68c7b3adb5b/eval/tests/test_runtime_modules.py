"""Module loading through the CLI: ES modules (static/dynamic import, top-level await, cycles,
live bindings, namespaces, import attributes, `import defer`, errors), CommonJS (`require`,
caches, resolution, cycles), CJS<->ESM interop, `node_modules` packages written inline, entry
module-kind selection, the JSX and TypeScript entry hooks, and the `node:module` API.

All module trees are written into the per-test workdir; programs print only relative paths, and
absolute paths that the runtime embeds in error messages are replaced by `<wd>` in Python.
"""

import pytest

from conftest import err, out

TIERS = [pytest.param((), id="jit"), pytest.param(("--tier=bytecode",), id="bytecode"),
         pytest.param(("--tier=interp",), id="interp")]


def write(root, files):
    """Create `files` ({relative path: text or bytes}) under `root`."""
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")


def norm(text, workdir):
    """Replace the (canonical) workdir path embedded in runtime messages with `<wd>`."""
    return text.replace(str(workdir.resolve()), "<wd>").replace(str(workdir), "<wd>")


# ------------------------------------------------------------------------------- ES modules
@pytest.mark.parametrize("tier", TIERS)
def test_esm_static_imports_live_bindings_and_import_meta(js, workdir, golden, tier):
    """CATCHES: an ES module loader that copies exported values instead of binding them live,
    mis-wires default/renamed imports, builds the namespace with unsorted or missing keys, gives
    import.meta a non-file:// url or wrong filename/dirname, or re-evaluates a module that a
    dynamic import already loaded."""
    write(workdir, {
        "anon-class.mjs": "export default class { static k = 'anonymous default class'; }\n",
        "anon-fn.mjs": "export default function () { return 'anonymous default function'; }\n",
        "named-fn.mjs": "export default function named() { return 'named default function ' + typeof named; }\n"
                        "export async function af() {}\nexport class C {}\nexport function* gen() {}\n",
        "lib.mjs": "export let counter = 0;\nexport function inc() { counter++; }\n"
                   "export const named = 'N';\nexport default 'D';\nexport class K { static tag = 'k'; }\n"
                   "console.log('lib evaluated');\n",
    })
    code = r"""
import def, { counter, inc, named as alias, K } from './lib.mjs';
import * as ns from './lib.mjs';
import path from 'node:path';
import AnonClass from './anon-class.mjs';
import anonFn from './anon-fn.mjs';
import namedFn, * as namedNs from './named-fn.mjs';
console.log(def, counter, alias, K.tag);
console.log(AnonClass.k, AnonClass.name, anonFn(), anonFn.name, namedFn(), Object.keys(namedNs).join(','));
inc(); inc();
console.log('live', counter, ns.counter, ns.default);
console.log(Object.keys(ns).join(','), String(ns[Symbol.toStringTag]));
const url = import.meta.url;
console.log(url.startsWith('file:///'), url.endsWith('/main.mjs'), url === 'file://' + import.meta.filename);
console.log(path.basename(import.meta.filename), import.meta.dirname === path.dirname(import.meta.filename));
console.log(import.meta.dirname === process.cwd() || import.meta.dirname === require('fs').realpathSync(process.cwd()));
console.log(Object.getPrototypeOf(import.meta), Object.keys(import.meta).join(','));
const again = await import('./lib.mjs');
console.log(again === ns, again.counter);
inc();
console.log(counter, again.counter);
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("static_imports")
    assert (r.returncode, r.stderr) == (0, b"")


def test_namespace_object_is_an_exotic_sealed_view(js, workdir, golden):
    """CATCHES: a module namespace object that is extensible, has a prototype, allows assignment,
    deletion or defineProperty of exports, reports wrong property descriptors, or omits the
    Symbol.toStringTag key from Reflect.ownKeys."""
    write(workdir, {"m.mjs": "export let b = 2; export const a = 1; export function c() {}\n"})
    code = r"""
import * as ns from './m.mjs';
const d = Object.getOwnPropertyDescriptor(ns, 'b');
console.log(JSON.stringify(d), Reflect.ownKeys(ns).map(String).join(','));
console.log(Object.isExtensible(ns), Object.isSealed(ns), Object.isFrozen(ns), 'a' in ns, 'zz' in ns);
console.log(Object.getPrototypeOf(ns), delete ns.nonexistent, Reflect.set(ns, 'a', 5), Reflect.deleteProperty(ns, 'a'));
for (const f of [() => { ns.a = 5; }, () => { delete ns.a; }, () => Object.defineProperty(ns, 'x', { value: 1 }),
                 () => { ns.newProp = 1; }]) {
  try { f(); console.log('no throw'); } catch (e) { console.log(e.constructor.name); }
}
console.log(JSON.stringify(Object.entries(ns).map(([k, v]) => [k, typeof v])));
console.log(Object.prototype.toString.call(ns), Object.getOwnPropertyDescriptor(ns, Symbol.toStringTag).value);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("namespace_semantics")
    assert (r.returncode, r.stderr) == (0, b"")


def test_top_level_await_dependencies_do_not_block_siblings(js, workdir, golden):
    """CATCHES: a module graph that evaluates async (top-level await) dependencies strictly one
    after another, runs the importer before its async dependencies finish, or evaluates a
    shared dependency twice."""
    write(workdir, {
        "a.mjs": "import './shared.mjs';\nconsole.log('a start');\nawait new Promise((r) => setTimeout(r, 30));\n"
                 "console.log('a end');\nexport const a = 'A';\n",
        "b.mjs": "import './shared.mjs';\nconsole.log('b start');\nawait null;\nconsole.log('b end');\n"
                 "export const b = 'B';\n",
        "c.mjs": "console.log('c sync');\nexport const c = 'C';\n",
        "shared.mjs": "console.log('shared once');\n",
    })
    code = r"""
import { a } from './a.mjs';
import { b } from './b.mjs';
import { c } from './c.mjs';
console.log('main', a, b, c);
const late = await new Promise((r) => setTimeout(() => r('timer result'), 5));
console.log('main after own await', late);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("tla_order")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_cyclic_imports_hoist_functions_and_guard_lexicals(js, workdir, golden, tier):
    """CATCHES: cycle handling that evaluates a module twice, fails to hoist function
    declarations across the cycle, does not throw a TDZ ReferenceError for a not-yet-initialised
    `let` export, or evaluates the cycle in the wrong post-order."""
    write(workdir, {
        "cyc-a.mjs": "import { pong } from './cyc-b.mjs';\nexport let count = 0;\n"
                     "export function ping(n) { count++; return n <= 0 ? 'done' : pong(n - 1); }\n"
                     "console.log('cyc-a evaluated');\n",
        "cyc-b.mjs": "import { ping, count } from './cyc-a.mjs';\nexport function pong(n) { return ping(n); }\n"
                     "console.log('cyc-b evaluated, ping hoisted:', typeof ping);\n"
                     "try { console.log(count); } catch (e) { console.log('TDZ:', e.constructor.name, e.message); }\n"
                     "import * as aNs from './cyc-a.mjs';\n"
                     "try { console.log(aNs.count); } catch (e) { console.log('TDZ via namespace:', e.constructor.name); }\n"
                     "console.log('own keys before init:', Reflect.ownKeys(aNs).map(String).join(','));\n"
                     "try { Object.keys(aNs); } catch (e) { console.log('Object.keys in TDZ:', e.constructor.name); }\n"
                     "export const lateRead = () => count;\n",
    })
    code = r"""
import { ping, count } from './cyc-a.mjs';
import { lateRead } from './cyc-b.mjs';
console.log('main');
console.log(ping(3), count, lateRead());
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("cycles")
    assert (r.returncode, r.stderr) == (0, b"")


def test_star_exports_and_ambiguous_names(js, workdir, golden):
    """CATCHES: `export *` that re-exports `default`, keeps a name exported by two star sources
    (it must be dropped from the namespace), loses `export * as ns`, or lets an explicit import
    of the ambiguous name link instead of failing with a SyntaxError."""
    write(workdir, {
        "s1.mjs": "export const shared = 1, only1 = 'o1';\nexport default 'not re-exported';\n",
        "s2.mjs": "export const shared = 2, only2 = 'o2';\n",
        "star.mjs": "export * from './s1.mjs';\nexport * from './s2.mjs';\nexport * as nsx from './s1.mjs';\n"
                    "export { only2 as renamed } from './s2.mjs';\n",
        "bad.mjs": "import { shared } from './star.mjs';\nconsole.log(shared);\n",
    })
    code = r"""
import * as star from './star.mjs';
import { nsx, renamed } from './star.mjs';
console.log(Object.keys(star).join(','), 'shared' in star, 'default' in star);
console.log(Object.keys(nsx).join(','), nsx.default, renamed);
try { await import('./bad.mjs'); } catch (e) { console.log(e.constructor.name + ': ' + e.message); }
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("star_exports")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("files,expected", [
    ({"main.mjs": "import x from './nope.mjs';\nconsole.log(x);\n"},
     "Uncaught TypeError: module not found: ./nope.mjs (imported from <wd>/main.mjs)\n"),
    ({"main.mjs": "import x from 'not-installed-pkg';\nconsole.log(x);\n"},
     "Uncaught TypeError: module not found: not-installed-pkg (imported from <wd>/main.mjs)\n"),
    ({"main.mjs": "import { zzz } from './lib.mjs';\nconsole.log(zzz);\n", "lib.mjs": "export const a = 1;\n"},
     "Uncaught SyntaxError: the requested module '<wd>/lib.mjs' does not provide an export named 'zzz'\n"),
    ({"main.mjs": "export { gone } from './lib.mjs';\nconsole.log('x');\n", "lib.mjs": "export const a = 1;\n"},
     "Uncaught SyntaxError: the requested module does not provide an export named 'gone'\n"),
    ({"main.mjs": "export { shared } from './star.mjs';\n", "star.mjs": "export * from './s1.mjs';\nexport * from './s2.mjs';\n",
      "s1.mjs": "export const shared = 1;\n", "s2.mjs": "export const shared = 2;\n"},
     "Uncaught SyntaxError: the requested module provides an ambiguous export named 'shared'\n"),
    ({"main.mjs": "import d from './star-only.mjs';\n", "star-only.mjs": "export * from './lib.mjs';\n",
      "lib.mjs": "export default 1;\nexport const a = 2;\n"},
     "Uncaught SyntaxError: the requested module '<wd>/star-only.mjs' does not provide an export named 'default'\n"),
    ({"main.mjs": "import { shared } from './outer.mjs';\n", "outer.mjs": "export * from './star.mjs';\n",
      "star.mjs": "export * from './s1.mjs';\nexport * from './s2.mjs';\n",
      "s1.mjs": "export const shared = 1;\n", "s2.mjs": "export const shared = 2;\n"},
     "Uncaught SyntaxError: the requested module provides an ambiguous export named 'shared'\n"),
    ({"main.mjs": "import './dep.mjs';\nconsole.log('x');\n", "dep.mjs": "let x = ;\n"},
     'Uncaught SyntaxError: unexpected token Punct(";")\n'),
    ({"main.mjs": "import source s from './lib.mjs';\nconsole.log(s);\n", "lib.mjs": "export const a = 1;\n"},
     "Uncaught SyntaxError: source-text modules have no module source\n"),
], ids=["missing-relative", "missing-bare", "missing-export", "missing-indirect", "ambiguous-indirect",
        "default-not-via-star", "nested-ambiguous-star", "dep-syntax", "source-phase"])
def test_link_errors_abort_before_any_module_runs(run, workdir, files, expected):
    """CATCHES: an ESM loader that starts evaluating modules before the whole graph has linked,
    reports a missing file/package/export or a dependency syntax error with the wrong error type
    or message, or exits 0 on a link failure."""
    write(workdir, {**files, "side.mjs": "console.log('must not run');\n"})
    main = (workdir / "main.mjs").read_text()
    (workdir / "main.mjs").write_text("import './side.mjs';\n" + main)
    r = run(["main.mjs"])
    assert (r.returncode, out(r)) == (1, "")
    assert norm(err(r), workdir) == expected


def test_uncaught_errors_from_module_evaluation(js, workdir):
    """CATCHES: a module runner that exits 0 when the entry or an async dependency throws or
    rejects, loses output printed before the failure, or reports the wrong error. (A sibling
    module installs onunhandledrejection to silence the per-module promise reports, leaving only
    the CLI's final report.)"""
    write(workdir, {
        "quiet.mjs": "globalThis.onunhandledrejection = (ev) => ev.preventDefault();\n",
        "rejects.mjs": "console.log('dep starts');\nawait null;\nthrow new RangeError('async dep failed');\n",
        "entry-throw.mjs": "import './quiet.mjs';\nconsole.log('before');\nthrow new TypeError('entry threw');\n",
        "entry-tla.mjs": "import './quiet.mjs';\nconsole.log('before');\n"
                         "await Promise.reject(new SyntaxError('awaited rejection'));\n",
        "entry-dep.mjs": "import './quiet.mjs';\nimport './rejects.mjs';\nconsole.log('unreachable');\n",
    })
    for entry, stdout, stderr in [
        ("entry-throw.mjs", "before\n", "Uncaught TypeError: entry threw\n"),
        ("entry-tla.mjs", "before\n", "Uncaught SyntaxError: awaited rejection\n"),
        ("entry-dep.mjs", "dep starts\n", "Uncaught RangeError: async dep failed\n"),
    ]:
        r = js((workdir / entry).read_text(), name=entry)
        assert (r.returncode, out(r), err(r)) == (1, stdout, stderr)


def test_dynamic_import_variants(js, workdir, golden):
    """CATCHES: import() that does not return the same namespace for repeated calls, re-runs a
    rejected async module instead of re-rejecting, ignores import attributes, cannot load node:
    builtins, or resolves relative specifiers against the cwd instead of the importing file."""
    write(workdir, {
        "rejects.mjs": "console.log('rejects.mjs evaluated');\nawait null;\nthrow new RangeError('async module failed');\n",
        "data.json": '{"plain": true, "list": [1, 2]}',
        "sub/inner.mjs": "export const where = 'inner';\nexport const load = () => import('./sibling.mjs');\n",
        "sub/sibling.mjs": "export default 'sibling of inner';\n",
        "lazy.mjs": "await new Promise((r) => setTimeout(r, 5));\nexport const v = 'lazy with tla';\n",
        "two-fail.mjs": "import './fail-a.mjs';\nimport './fail-b.mjs';\nimport './ok-c.mjs';\n"
                        "console.log('two-fail body must not run');\n",
        "fail-a.mjs": "console.log('fail-a starts');\nawait null;\nthrow new Error('fail-a rejected');\n",
        "fail-b.mjs": "console.log('fail-b starts');\nawait null;\nawait null;\nthrow new Error('fail-b rejected');\n",
        "ok-c.mjs": "console.log('ok-c starts');\nawait new Promise((r) => setTimeout(r, 10));\nconsole.log('ok-c done');\n",
    })
    code = r"""
globalThis.onunhandledrejection = (ev) => ev.preventDefault();
const a = await import('./lazy.mjs');
const b = await import('./lazy.mjs');
console.log(a === b, a.v, Object.keys(a).join(','));
for (let i = 0; i < 2; i++) {
  try { await import('./rejects.mjs'); } catch (e) { console.log('reject', i, e.constructor.name, e.message); }
}
const j = await import('./data.json', { with: { type: 'json' } });
console.log(JSON.stringify(j.default), Object.keys(j).join(','));
const fsns = await import('node:fs');
const fsBare = await import('fs');
console.log(typeof fsns.readFileSync, fsns.default === fsBare.default, typeof (await import('node:events')).default);
const inner = await import('./sub/inner.mjs');
console.log(inner.where, (await inner.load()).default);
const [x, y] = await Promise.all([import('./lazy.mjs'), import('./sub/sibling.mjs')]);
console.log(x === a, y.default);
try { await import('./sub/missing.mjs'); } catch (e) { console.log(e.constructor.name, e.message.split(' (imported')[0]); }
for (let i = 0; i < 2; i++) {
  try { await import('./two-fail.mjs'); } catch (e) { console.log('two-fail rejected', i, e.message); }
}
await new Promise((r) => setTimeout(r, 30));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("dynamic_import")
    assert (r.returncode, r.stderr) == (0, b"")


def test_import_defer_evaluates_on_first_access(js, workdir, golden):
    """CATCHES: `import defer` that evaluates the module eagerly (or never), does not expose a
    'Deferred Module' namespace, evaluates it twice, or fails to pre-evaluate its asynchronous
    dependencies before the importer runs."""
    write(workdir, {
        "lazy.mjs": "console.log('lazy evaluated');\nexport const value = 'L';\nexport const other = 2;\n",
        "lazy2.mjs": "import { v0 } from './lazy2dep.mjs';\nconsole.log('lazy2 evaluated');\n"
                     "export const v = v0 + '!';\n",
        "lazy2dep.mjs": "console.log('lazy2dep (async) evaluated');\nawait 0;\nexport const v0 = 'async-dep';\n",
    })
    code = r"""
import defer * as lazy from './lazy.mjs';
import defer * as lazyAsyncDep from './lazy2.mjs';
console.log('main body start');
console.log(typeof lazy, Object.prototype.toString.call(lazy));
console.log('value:', lazy.value);
console.log('again:', lazy.value, Object.keys(lazy).join(','), 'other' in lazy);
console.log('lazy2:', lazyAsyncDep.v);
const eager = await import('./lazy.mjs');
console.log(eager.other, eager === lazy);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("import_defer")
    assert (r.returncode, r.stderr) == (0, b"")


def test_reexport_chains_resolve_to_the_original_bindings(js, workdir, golden):
    """CATCHES: re-export resolution that treats a name reachable through two `export *` paths
    to the SAME binding as ambiguous, copies re-exported imports instead of keeping them live,
    gives a re-exported namespace a new identity, or loses the deferred-ness of a re-exported
    `import defer` namespace."""
    write(workdir, {
        "base.mjs": "export let v = 1;\nexport function bump() { v++; }\n",
        "s1.mjs": "export * from './base.mjs';\nimport * as nsA from './base.mjs';\nexport { nsA as sharedNs };\n"
                  "export const clash = 's1';\n",
        "s2.mjs": "export * from './base.mjs';\nimport * as nsB from './base.mjs';\nexport { nsB as sharedNs };\n"
                  "export const clash = 's2';\n",
        "outer.mjs": "export * from './diamond.mjs';\nexport const own = 'outer';\n",
        "diamond.mjs": "export * from './s1.mjs';\nexport * from './s2.mjs';\n",
        "nsre.mjs": "import * as baseNs from './base.mjs';\nimport { v as iv } from './base.mjs';\n"
                    "export { baseNs, iv as renamedV };\nexport * as starNs from './base.mjs';\n",
        "lazy.mjs": "console.log('lazy evaluated');\nexport const x = 'lazy x';\n",
        "defer-re.mjs": "import defer * as lazyNs from './lazy.mjs';\nexport { lazyNs };\n",
    })
    code = r"""
import { v, bump } from './diamond.mjs';
import * as diamond from './diamond.mjs';
import * as outer from './outer.mjs';
import { sharedNs } from './diamond.mjs';
import { baseNs, renamedV, starNs } from './nsre.mjs';
import * as base from './base.mjs';
import { lazyNs } from './defer-re.mjs';
import * as deferRe from './defer-re.mjs';
console.log(Object.keys(diamond).join(','), baseNs === base, starNs === base, sharedNs === base, Object.keys(deferRe).join(','));
console.log('outer:', Object.keys(outer).join(','));
bump(); bump();
console.log(v, renamedV, diamond.v, baseNs.v);
console.log(Object.prototype.toString.call(lazyNs), deferRe.lazyNs === lazyNs);
console.log('before touching lazyNs');
console.log(lazyNs.x);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("reexport_chains")
    assert (r.returncode, r.stderr) == (0, b"")


def test_deferred_namespace_errors_and_import_defer_calls(js, workdir, golden):
    """CATCHES: a deferred module whose evaluation error is not rethrown on every access (or that
    is re-evaluated), touching a deferred namespace whose graph is still evaluating without a
    TypeError, `import.defer()` that evaluates eagerly or returns a fresh namespace each time,
    or dynamic re-imports of a module that threw synchronously that do not re-reject."""
    write(workdir, {
        "lazy3.mjs": "console.log('lazy3 evaluated');\nexport const z = 'Z';\n",
        "throwing.mjs": "console.log('throwing evaluated');\nthrow new RangeError('deferred module threw');\n",
        "d.mjs": "import './main.mjs';\nexport const x = 1;\n",
        "sync-throw.mjs": "console.log('sync-throw evaluated');\nthrow new TypeError('sync boom');\n",
    })
    code = r"""
import defer * as t from './throwing.mjs';
import defer * as d from './d.mjs';
for (let i = 0; i < 2; i++) { try { t.x; } catch (e) { console.log('deferred error', i, e.constructor.name, e.message); } }
try { await import('./throwing.mjs'); } catch (e) { console.log('dynamic import of failed deferred module:', e.message); }
try { d.x; } catch (e) { console.log(e.constructor.name, e.message); }
const ns = await import.defer('./lazy3.mjs');
console.log('import.defer resolved', Object.prototype.toString.call(ns));
console.log(ns.z);
const ns2 = await import.defer('./lazy3.mjs');
console.log(ns2 === ns, (await import('./lazy3.mjs')) === ns);
const txt = await import('./lazy3.mjs', { with: { type: 'text' } });
console.log(JSON.stringify(txt.default));
for (let i = 0; i < 2; i++) { try { await import('./sync-throw.mjs'); } catch (e) { console.log('dyn sync throw', i, e.message); } }
setTimeout(() => console.log('after main finished, d.x =', d.x), 0);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("defer_errors")
    assert (r.returncode, r.stderr) == (0, b"")


TLA_FORMS = {
    "if": "if (true) { await null; }",
    "for-body": "for (let i = 0; i < 1; i++) { await null; }",
    "for-init": "for (let i = await 0; i < 1; i++) {}",
    "for-test": "for (let i = 0; await (i < 1); i++) {}",
    "for-update": "for (let i = 0; i < 2; i = await (i + 1)) {}",
    "while": "let n = 0; while (await (n++ < 1)) {}",
    "do-while": "do { await null; } while (false);",
    "for-of-right": "for (const x of await Promise.resolve([1])) {}",
    "for-await": "for await (const x of [1]) {}",
    "catch": "try { throw 1; } catch { await null; }",
    "finally": "try {} finally { await null; }",
    "switch-case": "switch (1) { case 1: await null; }",
    "switch-test": "switch (1) { case await 1: break; }",
    "labeled": "lbl: { await null; }",
    "array": "const arr = [await null];",
    "object": "const obj = { k: await null, ...(await Promise.resolve({})) };",
    "call-arg": "Math.max(await 1, 2);",
    "cond": "const c = true ? await null : 0;",
    "binary": "const b = 1 + (await 1);",
    "logical": "const l = false || await 1;",
    "member": "const p = (await Promise.resolve({ p: 1 })).p;",
    "index": "const q = [1][await 0];",
    "new": "new (await Promise.resolve(Object))();",
    "tagged": "(await Promise.resolve(String.raw))`x`;",
    "seq": "(0, await null);",
    "unary": "typeof await null;",
    "assign": "let z; z = await 1;",
    "throw": "try { throw await Promise.resolve(new Error('t')); } catch {}",
    "export-const": "export const ev = await Promise.resolve(1);",
    "export-default": "export default await Promise.resolve('d');",
    "import-call": "import(await Promise.resolve('./plain.mjs'));",
    "optional": "(await Promise.resolve(null))?.x;",
    "update-expr": "let u = [0]; u[await 0]++;",
    "for-init-expr": "let fi; for (fi = await 0; fi < 1; fi++) {}",
    "array-hole": "const holes = [, , await null];",
    "object-method": "const om = { m() {}, get g() { return 1; }, k: await null };",
    "call-spread": "Math.max(...(await Promise.resolve([1, 2])));",
    "new-args": "new Array(await 1);",
}


@pytest.mark.parametrize("tier", TIERS)
def test_top_level_await_detected_in_every_statement_position(js, workdir, golden, tier):
    """CATCHES: async-module detection that only looks for a top-level `await` statement and
    misses awaits nested in control flow, loop heads, try/switch/labeled blocks, literals, calls,
    operators or export declarations; a missed module would block its siblings (or fail) instead
    of parking at the await while the synchronous sibling runs."""
    files = {"plain.mjs": "export const plain = 1;\n",
             "sync.mjs": "console.log('sync sibling runs while the others are parked');\n"}
    imports = []
    for name, body in TLA_FORMS.items():
        files[f"tla-{name}.mjs"] = (f"if (true) {{ var nothing = 0; }}\nconsole.log('{name} start');\n{body}\n"
                                    f"console.log('{name} end');\n")
        imports.append(f"import './tla-{name}.mjs';")
    write(workdir, files)
    code = "\n".join(imports) + "\nimport './sync.mjs';\nconsole.log('main runs last');\n"
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("tla_positions")
    assert (r.returncode, r.stderr) == (0, b"")


def test_json_text_and_bytes_imports(js, workdir, golden):
    """CATCHES: attribute imports that run JSON through a JS object literal (`__proto__` would
    set the prototype), do not strip a UTF-8 BOM for text/json, re-encode non-UTF-8 bytes, cache
    a text import and a bytes import of the same file as one module, or accept an unsupported
    import type."""
    write(workdir, {
        "data.json": '{"a": [1, 2], "__proto__": {"polluted": true}, "s": "\\u00e9"}',
        "bom.json": '﻿{"bom": "stripped"}',
        "notes.txt": "﻿hello\ntext é\n",
        "seps.txt": "a\u2028b\u2029c\r\n\x01\"\\",
        "blob.bin": bytes([0, 255, 128, 10, 0xC3, 0x28]),
        "code.js": "export const notRun = 1; console.log('code.js must not execute');\n",
    })
    code = r"""
import data from './data.json' with { type: 'json' };
import plain from './data.json';
import bom from './bom.json' with { type: 'json' };
import txt from './notes.txt' with { type: 'text' };
import bytes from './notes.txt' with { type: 'bytes' };
import blob from './blob.bin' with { type: 'bytes' };
import src from './code.js' with { type: 'text' };
import seps from './seps.txt' with { type: 'text' };
console.log(JSON.stringify(data), Object.getPrototypeOf(data) === Object.prototype, Object.keys(data).join(','));
console.log(({}).polluted, data.__proto__.polluted, plain.s, plain === data, bom.bom);
console.log(JSON.stringify(txt), bytes.constructor.name, bytes.length, Array.from(bytes.slice(0, 4)).join(','));
console.log(blob.length, Array.from(blob).join(','));
console.log(JSON.stringify(src), JSON.stringify(seps), seps.length);
try { await import('./notes.txt', { with: { type: 'css' } }); } catch (e) { console.log(e.constructor.name); }
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("attribute_imports")
    assert (r.returncode, r.stderr) == (0, b"")


def test_esm_named_imports_from_node_builtins(js, golden):
    """CATCHES: synthetic node: builtin modules that lack named exports, differ between the
    `node:` and bare spellings, expose a different default than require(), or miss the fixed
    process export list."""
    code = r"""
import fs, { readFileSync, existsSync } from 'node:fs';
import { join, sep, posix } from 'path';
import { EventEmitter, once } from 'node:events';
import { promisify, format } from 'node:util';
import { argv, env, nextTick } from 'node:process';
import process from 'process';
import { setTimeout as sleep } from 'node:timers/promises';
import { Buffer } from 'node:buffer';
import { createRequire, builtinModules } from 'node:module';
const require = createRequire(import.meta.url);
console.log(fs === require('fs'), readFileSync === require('fs').readFileSync, existsSync('main.mjs'));
console.log(join('a', 'b'), sep, posix.join('x', '..', 'y'));
const e = new EventEmitter();
setTimeout(() => e.emit('ready', 42), 1);
console.log('once', (await once(e, 'ready'))[0], await sleep(1, 'slept'));
console.log(typeof promisify, format('%s-%d', 'v', 3), Array.isArray(argv), typeof env, typeof nextTick, process === globalThis.process);
console.log(Buffer.from('hi').toString('hex'), builtinModules.includes('fs'), builtinModules.includes('node:fs'));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("builtin_named_imports")
    assert (r.returncode, r.stderr) == (0, b"")


# --------------------------------------------------------------------------- CJS <-> ESM interop
def test_commonjs_named_exports_detected_for_esm_importers(js, workdir, golden):
    """CATCHES: CJS interop that only offers a default export, misses one of the lexer shapes
    (exports.X=, module.exports.X=, defineProperty, object-literal module.exports, esbuild's
    __export, transitive module.exports = require() re-exports), or exports reserved words /
    `default` / `__esModule` as names."""
    write(workdir, {
        "shapes.cjs": "exports.direct = 'D';\nmodule.exports.viaModule = 'VM';\n"
                      "Object.defineProperty(exports, \"defined\", { enumerable: true, get() { return 'DEF'; } });\n"
                      "Object.defineProperty(exports, '__esModule', { value: true });\n"
                      "exports.$dollar = '$';\nexports._under = '_';\nexports.default = 'explicit default prop';\n"
                      "exports.class = 'reserved word';\nexports.counter = 0;\nexports.bump = () => { exports.counter++; };\n"
                      "if (exports.direct == 'D') {}\nconst arrow = (exports) => exports.notAnExport;\n",
        "literal.cjs": "const shortA = 'SA';\nmodule.exports = { shortA, keyB: { nested: [1, 2] }.nested.length, "
                       "'strKey': \"S\", fn() { return { inner: 1 }; } };\n",
        "bundled.cjs": "var __export = (target, all) => { for (var name in all) Object.defineProperty(target, name, "
                       "{ get: all[name], enumerable: true }); };\nvar exp = {};\n"
                       "__export(exp, { fromBundler: () => fromBundler, other: () => other });\n"
                       "const fromBundler = 'FB', other = 'OT';\nmodule.exports = exp;\n"
                       "0 && (module.exports = { fromBundler, other });\n",
        "reexport.cjs": "module.exports = require('./inner.cjs');\n",
        "inner.cjs": "exports.reexported = 'R';\nObject.assign(module.exports, require('./inner2.js'));\n",
        "inner2.js": "exports.viaAssign = 'VA';\n",
        "fn.cjs": "module.exports = function (x) { return x * 21; };\n",
        "plain.js": "exports.fromJs = 'js is CommonJS without type:module';\n",
    })
    code = r"""
import d1, { direct, viaModule, defined, $dollar, _under } from './shapes.cjs';
import d2, { shortA, keyB, strKey } from './literal.cjs';
import { fromBundler, other } from './bundled.cjs';
import d4, { reexported, viaAssign } from './reexport.cjs';
import * as nsCjs from './shapes.cjs';
import fnDefault from './fn.cjs';
import { fromJs } from './plain.js';
console.log(direct, viaModule, defined, $dollar, _under, d1.direct === direct, d1.default);
console.log(shortA, keyB, strKey, Object.keys(d2).join(','));
console.log(fromBundler, other, reexported, viaAssign, Object.keys(d4).join(','));
console.log(Object.keys(nsCjs).join(','));
console.log(typeof fnDefault, fnDefault(2), fromJs);
d1.bump();
console.log('named export is a snapshot:', nsCjs.counter, d1.counter);
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("cjs_named_exports")
    assert (r.returncode, r.stderr) == (0, b"")


def test_node_modules_packages_resolve_for_esm(js, workdir, golden):
    """CATCHES: bare-specifier resolution that ignores package.json `exports` import conditions,
    the `module` field, string `exports`, subpath `exports` maps, scoped packages, or literal
    subpath files, loads an ESM package as CommonJS (or vice versa), or does not walk up to a
    parent node_modules."""
    nm = "node_modules/"
    write(workdir, {
        nm + "esm-pkg/package.json": '{"name":"esm-pkg","type":"module","main":"./cjs-fallback.js",'
                                     '"exports":{".":{"types":"./x.d.ts","import":"./dist/index.js","require":"./cjs-fallback.js"}}}',
        nm + "esm-pkg/dist/index.js": 'export default "esm-default"; export const kind = "esm-import-condition";\n',
        nm + "esm-pkg/cjs-fallback.js": 'module.exports = "wrong: require condition";\n',
        nm + "@scope/tool/package.json": '{"name":"@scope/tool","main":"lib/index.js"}',
        nm + "@scope/tool/lib/index.js": 'module.exports = "scoped-cjs";\n',
        nm + "@scope/tool/lib/helper.js": 'exports.helper = "helper-subpath-file";\n',
        nm + "cjs-pkg/package.json": '{"name":"cjs-pkg"}',
        nm + "cjs-pkg/index.js": 'module.exports = { name: "cjs-index", n: 1 };\n',
        nm + "mod-field/package.json": '{"name":"mod-field","main":"main.cjs","module":"esm.mjs"}',
        nm + "mod-field/esm.mjs": 'export const viaModuleField = "module-field";\n',
        nm + "sub-exp/package.json": '{"name":"sub-exp","exports":{".":"./dist/index.js",'
                                     '"./feature":{"import":"./dist/feature/index.js","default":"./dist/feature/cjs.js"},'
                                     '"./plain":"./dist/plain.js"}}',
        nm + "sub-exp/dist/feature/index.js": 'export const feature = "subpath-exports";\n',
        nm + "sub-exp/dist/plain.js": 'export const plain = "subpath-string";\n',
        nm + "typed-pkg/package.json": '{"name":"typed-pkg","type":"module","exports":"./src/entry.js"}',
        nm + "typed-pkg/src/entry.js": 'export const tv = "exports-string";\n',
        nm + "dir-main/package.json": '{"name":"dir-main","main":"lib"}',
        nm + "dir-main/lib/index.js": 'module.exports = "main points at a directory";\n',
    })
    code = r"""
import esm, { kind } from 'esm-pkg';
import scoped from '@scope/tool';
import { helper } from '@scope/tool/lib/helper.js';
import cjsDefault from 'cjs-pkg';
import * as cjsNs from 'cjs-pkg';
import { viaModuleField } from 'mod-field';
import { feature } from 'sub-exp/feature';
import { plain } from 'sub-exp/plain';
import { tv } from 'typed-pkg';
import dirMain from 'dir-main';
import { fromParent } from './app/deep/use-parent.mjs';
console.log(esm, kind, scoped, helper, JSON.stringify(cjsDefault), Object.keys(cjsNs).join(','));
console.log(viaModuleField, feature, plain, tv, dirMain, fromParent);
try { await import('sub-exp/missing'); } catch (e) { console.log(e.message.split(' (imported')[0]); }
"""
    write(workdir, {"app/deep/use-parent.mjs": "import t from '@scope/tool';\nexport const fromParent = 'walked up: ' + t;\n"})
    r = js(code, name="main.mjs")
    assert out(r) == golden("node_modules_esm")
    assert (r.returncode, r.stderr) == (0, b"")


def test_esm_resolution_edge_cases(js, workdir, golden):
    """CATCHES: an ESM resolver that cannot import a directory (index file / package.json main
    with fallback to index.js), mis-handles `..` segments, JSON escapes in package.json, attribute
    imports of `../` or bare specifiers, scoped-package subpath exports, bare files directly in
    node_modules, a package importing another package from a nested node_modules directory, file
    names containing quotes, CRLF/tab/U+2028 JSON text, or CJS re-export chains and lexer shapes."""
    write(workdir, {
        "sub/deeper/use.mjs": "import data from '../../conf/data.json' with { type: 'json' };\n"
                              "import pkgJson from 'esm-dep/package.json' with { type: 'json' };\n"
                              "import { up } from '../up.mjs';\nexport const info = [data.k, pkgJson.name, up].join(' ');\n",
        "sub/up.mjs": "export const up = 'parent-dir import';\n",
        "conf/data.json": "{\r\n\t\"k\": \"crlf\\u0041\u2028tab\",\r\n\t\"sep\": \" \"\r\n}\r\n",
        "dirmod/index.mjs": "export const fromDir = 'directory index.mjs';\n",
        "badmain/package.json": '{"main": "missing.js"}',
        "badmain/index.js": "exports.fallback = 'main missing -> index.js';\n",
        "escmain/package.json": '{"description": "the \\"main\\" key", "main": "lib\\/entry.js"}',
        "escmain/lib/entry.js": "exports.esc = 'escaped main path';\n",
        "node_modules/esm-dep/package.json": '{"name":"esm-dep","type":"module","main":"index.js"}',
        "node_modules/esm-dep/index.js": "import other from 'cjs-dep';\nexport default 'esm-dep sees ' + other;\n",
        "node_modules/cjs-dep/index.js": "module.exports = 'cjs-dep from root node_modules';\n",
        "node_modules/@sc/kit/package.json": '{"name":"@sc/kit","exports":{".":"./main.js","./feature":{"import":"./feat/index.js"}}}',
        "node_modules/@sc/kit/feat/index.js": "export const feat = 'scoped subpath export';\n",
        "node_modules/single.mjs": "export const single = 'bare file in node_modules';\n",
        'q"uote.cjs': "exports.quoted = 'file name with a quote';\n",
        **{f"chain{i}.cjs": f"module.exports = require('./chain{i + 1}.cjs');\n" for i in range(1, 6)},
        "chain6.cjs": "exports.deep = 'six levels down';\n",
        "lexer.cjs": "Object.assign(exports, require('./assign-src'));\n"
                     "Object.defineProperty(module.exports, 'viaModuleDefine', { enumerable: true, value: 'MD' });\n"
                     "Object.defineProperty(exports, 'has-dash', { enumerable: true, value: 1 });\n"
                     "Object.defineProperty(exports, '1digit', { enumerable: true, value: 1 });\n"
                     "module.exports.bareReexport = require('cjs-dep');\n"
                     "const dyn = './x'; try { require(dyn); } catch {}\n"
                     "if (exports.eq == 1 || exports.arrowish) {}\nexports.real = 'real';\n"
                     "const __export = () => {}; __export(exports)\n",
        "assign-src/index.js": "exports.assigned = 'via Object.assign(exports, require(dir))';\n",
        "objkeys.cjs": "module.exports = { 'quo\\'ted': 1, plain: 2, nested: { inner: 3 }, list: [1, { x: 2 }], "
                       "fn: (a, b) => ({ a }), \"dq\": 4 };\n",
        "pkgreexport.cjs": "module.exports = require('cjs-dep');\n",
        "missing-reexport.cjs": "module.exports = require('./nowhere');\n",
    })
    code = r"""
import { info } from './sub/deeper/use.mjs';
import { fromDir } from './dirmod';
import badmain from './badmain';
import escmain from './escmain';
import esmDep from 'esm-dep';
import { feat } from '@sc/kit/feature';
import { single } from 'single.mjs';
import { quoted } from './q"uote.cjs';
import chain, * as chainNs from './chain1.cjs';
import * as lexer from './lexer.cjs';
import * as objkeys from './objkeys.cjs';
import pkgre from './pkgreexport.cjs';
import data from './conf/data.json';
console.log(JSON.stringify(info));
console.log(fromDir, JSON.stringify(badmain), JSON.stringify(escmain), esmDep, feat, single, quoted);
console.log(JSON.stringify(chain), Object.keys(chainNs).join(','), Object.keys(lexer).join(','), Object.keys(objkeys).join(','), pkgre);
console.log(JSON.stringify(data), data.k.charCodeAt(5).toString(16));
try { await import('./missing-reexport.cjs'); } catch (e) { console.log(e.code, e.message.includes("Cannot find module './nowhere'")); }
try { await import('./sub'); } catch (e) { console.log(e.message.split(' (imported')[0]); }
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("resolution_edges")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("entry,expected", [
    ("esmpkg/deep/er/main.js", "module kind: esm\nesm dependency loaded\n"),
    ("esmpkg/legacy.cjs", "module kind: commonjs\n"),
    ("cjspkg/m.mjs", "module kind: esm\n"),
    ("cjspkg/main.js", "module kind: commonjs\ndynamic import from cjs: esm\n"),
    ("nopkg/main.js", "module kind: commonjs\n"),
    ("oddpkg/main.js", "module kind: commonjs\n"),
], ids=["js-type-module-ancestor", "cjs-in-module-pkg", "mjs-in-commonjs-pkg", "js-type-commonjs", "no-type",
        "type-not-string"])
def test_entry_module_kind_follows_extension_and_package_type(run, workdir, entry, expected):
    """CATCHES: entry-point classification that ignores the nearest package.json `"type"`
    (searching only the script's own directory, or not stopping at the nearest one), treats
    .cjs/.mjs by package type instead of by extension, or mis-parses `"type"` values."""
    probe = "console.log('module kind: ' + (typeof module === 'undefined' ? 'esm' : 'commonjs'));\n"
    write(workdir, {
        "package.json": '{"type": "module"}',
        "esmpkg/package.json": '{ "name": "x",  "type" :  "module" }',
        "esmpkg/deep/er/main.js": probe + "const { v } = await import('./dep.js');\nconsole.log(v);\n",
        "esmpkg/deep/er/dep.js": "export const v = 'esm dependency loaded';\n",
        "esmpkg/legacy.cjs": probe,
        "cjspkg/package.json": '{"type":"commonjs"}',
        "cjspkg/m.mjs": probe + "export {};\n",
        "cjspkg/main.js": probe + "import('./m2.mjs').then((ns) => console.log('dynamic import from cjs:', ns.kind));\n",
        "cjspkg/m2.mjs": "export const kind = typeof module === 'undefined' ? 'esm' : 'commonjs';\n",
        "nopkg/package.json": '{"name": "no type field"}',
        "nopkg/main.js": probe,
        "oddpkg/package.json": '{"type": 5}',
        "oddpkg/main.js": probe,
    })
    r = run([entry])
    assert (r.returncode, out(r), r.stderr) == (0, expected, b"")


# ----------------------------------------------------------------------------------- CommonJS
@pytest.mark.parametrize("tier", TIERS)
def test_commonjs_require_cache_resolution_and_cycles(js, workdir, golden, tier):
    """CATCHES: a require() that re-evaluates cached modules, resolves extensions or directory
    index files wrongly, gives the wrong __filename/__dirname/module.id/require.main, leaks
    partially-initialised exports differently in a cycle, or throws something other than
    MODULE_NOT_FOUND for missing modules."""
    write(workdir, {
        "a.js": "exports.name = 'A'; globalThis.aLoads = (globalThis.aLoads || 0) + 1;\n",
        "conf.json": '{"k": [1, {"n": null}]}',
        "lib/index.js": "module.exports = { fromIndex: 'idx', file: require('path').relative(process.cwd(), __filename) };\n",
        "cyc1.js": "exports.done = false;\nconst b = require('./cyc2');\nexports.sawB = b.v;\nexports.done = true;\n",
        "cyc2.js": "const a = require('./cyc1');\nexports.v = 'b saw done=' + a.done;\n",
        "replace.js": "exports.lost = true;\nmodule.exports = { replaced: true };\nexports.ignored = true;\n",
        "shebang.js": "#!/usr/bin/env lumen\nmodule.exports = 'shebang stripped';\n",
        "this.js": "module.exports = { same: this === exports, strict: (function () { return this; })() === undefined };\n",
    })
    code = r"""
const path = require('path');
const rel = (p) => path.relative(process.cwd(), p);
const a = require('./a'), a2 = require('./a.js'), a3 = require(path.join(__dirname, 'a.js'));
console.log(a === a2 && a2 === a3, a.name, globalThis.aLoads, require.main === module, module.id);
console.log(rel(__filename), rel(__dirname) === '', rel(require.resolve('./a')), rel(require.resolve('./lib')));
console.log(JSON.stringify(require('./conf.json')), JSON.stringify(require('./lib')));
const c1 = require('./cyc1');
console.log('cycle', c1.done, c1.sawB);
console.log(JSON.stringify(require('./replace')), require('./shebang'), JSON.stringify(require('./this')));
for (const spec of ['./nope', 'nopkg', './lib/missing.js']) {
  try { require(spec); } catch (e) { console.log(e.code, e.message.split(process.cwd()).join('<cwd>')); }
}
console.log(Object.keys(require.cache).map(rel).sort().join(','));
console.log(typeof module.exports, this === module.exports, typeof exports, module.loaded, module.parent);
console.log(require('node:path') === require('path'), require('fs') === require('node:fs'), require.resolve('fs'));
"""
    r = js(code, *tier)
    assert out(r) == golden("cjs_require")
    assert (r.returncode, r.stderr) == (0, b"")


def test_commonjs_packages_main_exports_and_parent_walk(js, workdir, golden):
    """CATCHES: CommonJS package resolution that ignores `main`, prefers the `import` condition
    over `require`, does not fall back to index.js, fails to walk up node_modules from a nested
    module, or reports a malformed package.json with the wrong message."""
    nm = "node_modules/"
    write(workdir, {
        nm + "pkg-main/package.json": '{"name":"pkg-main","main":"lib/entry.js"}',
        nm + "pkg-main/lib/entry.js": 'module.exports.who = "main-entry";\n',
        nm + "pkg-exp/package.json": '{"name":"pkg-exp","main":"wrong.js","exports":{".":{"import":"./esm.mjs","require":"./req.js"}}}',
        nm + "pkg-exp/req.js": 'module.exports.who = "exports-require";\n',
        nm + "pkg-node/package.json": '{"exports":{".":{"node":"./node.js","default":"./default.js"}}}',
        nm + "pkg-node/node.js": 'module.exports.who = "exports-node";\n',
        nm + "pkg-str/package.json": '{"exports":"./s.js"}',
        nm + "pkg-str/s.js": 'module.exports.who = "exports-string";\n',
        nm + "pkg-index/package.json": '{"name":"no main"}',
        nm + "pkg-index/index.js": 'module.exports.who = "index-fallback";\n',
        nm + "pkg-file.js": 'module.exports.who = "bare file in node_modules";\n',
        nm + "broken/package.json": '{"main": ',
        nm + "pkg-main/node_modules/nested-dep/index.js": 'module.exports = "nested dep of pkg-main";\n',
        "src/deep/user.js": "module.exports = require('pkg-index').who + ' (from src/deep)';\n",
    })
    code = r"""
for (const name of ['pkg-main', 'pkg-exp', 'pkg-node', 'pkg-str', 'pkg-index', 'pkg-file']) console.log(name, require(name).who);
console.log(require('./src/deep/user.js'));
try { require('nested-dep'); } catch (e) { console.log('nested-dep not visible from root:', e.code); }
try { require('broken'); } catch (e) { console.log(e.message.split(process.cwd()).join('<cwd>').replace(/: .*$/, ': <json error>')); }
console.log(require('path').relative(process.cwd(), require.resolve('pkg-exp')));
"""
    r = js(code)
    assert out(r) == golden("cjs_packages")
    assert (r.returncode, r.stderr) == (0, b"")


def test_node_module_api_hooks_extensions_and_helpers(js, workdir, golden):
    """CATCHES: node:module helpers that are missing or wrong: registerHooks resolve/load chains
    that are not consulted (or not removed by deregister), Module._extensions overrides that are
    ignored, a wrong wrap() preamble, isBuiltin/builtinModules mismatches, or argument validation
    that accepts non-function hooks."""
    write(workdir, {"target.js": 'module.exports = "orig";\n', "package.json": '{"name":"m"}'})
    code = r"""
const Module = require('module');
const path = require('path');
console.log(Module === require('node:module'), Module.Module === Module, Module.isBuiltin('fs'), Module.isBuiltin('node:fs'),
  Module.isBuiltin('nope'), Module.isBuiltin(5), Module.builtinModules.includes('path'), Module.builtinModules.includes('module'));
console.log(JSON.stringify(Module.wrap('x')));
const seen = [];
const h = Module.registerHooks({
  resolve(spec, ctx, next) {
    seen.push('resolve ' + spec + ' ' + ctx.conditions.join('/'));
    if (spec === 'virtual:hello') return { url: 'file://' + __dirname + '/target.js', shortCircuit: true };
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    const r = next(url, ctx);
    seen.push('load ' + path.basename(url) + ' ' + r.format);
    if (url.endsWith('/target.js')) return { ...r, source: 'module.exports = "rewritten by load hook";' };
    return r;
  },
});
console.log(require('virtual:hello'), require('node:os') === require('os'));
console.log(seen.join(' | '));
h.deregister();
try { require('virtual:hello'); } catch (e) { console.log('after deregister', e.code); }
console.log(path.relative(__dirname, Module.findPackageJSON('./target.js', __filename)), Module.findPackageJSON('fs'));
Module._extensions['.txt'] = (m, filename) => { m.exports = require('fs').readFileSync(filename, 'utf8').trim().toUpperCase(); };
require('fs').writeFileSync('note.txt', 'custom loader\n');
console.log(require('./note.txt'), typeof Module._load, Module._resolveFilename('fs'), Module._resolveFilename('node:fs'));
console.log(path.basename(Module._resolveFilename('./target', module)), Module._resolveLookupPaths('./x'), Module._findPath('nothing-here', [__dirname]));
console.log(Module.enableCompileCache().status === Module.constants.compileCacheStatus.DISABLED, Module.getCompileCacheDir());
console.log(JSON.stringify(Module.getSourceMapsSupport()), Module.findSourceMap('x'));
const req = Module.createRequire(path.join(__dirname, 'target.js'));
console.log(req('./target'), Module._nodeModulePaths('/a/b').join(','));
try { Module.register('x'); } catch (e) { console.log(e.message); }
for (const bad of [null, { resolve: 5 }]) {
  try { Module.registerHooks(bad); } catch (e) { console.log(e.constructor.name, e.code, e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("module_api")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------- JSX / TypeScript
def test_jsx_entry_and_jsx_imports_are_transpiled(js, workdir, golden):
    """CATCHES: a .jsx entry that is not run through the JSX transform (or not as ESM), imported
    .jsx modules left untransformed, or a transform that mishandles attributes (string, expression,
    boolean, spread, quoted keys), fragments, member-expression components, nested JSX inside
    expressions, JSX text whitespace, or `<`/`/` inside strings, templates and regexes."""
    write(workdir, {
        "card.jsx": "export function Card({ title, n, children }) {\n"
                    "  return <section data-n={n}><h1>{title}</h1>{children.length}</section>;\n}\n",
    })
    code = r"""
import { Card } from './card.jsx';
const React = {
  createElement(type, props, ...children) {
    if (typeof type === 'function') return type({ ...props, children });
    const name = type === React.Fragment ? '#frag' : type;
    const attrs = props ? Object.entries(props).map(([k, v]) => ` ${k}=${JSON.stringify(v)}`).join('') : '';
    return `<${name}${attrs}>${children.flat().join('')}</${name}>`;
  },
  Fragment: Symbol('frag'),
};
globalThis.React = React;
const ui = { Badge: function Badge({ label }) { return '[badge ' + label + ']'; } };
const items = ['a', 'b'];
const flag = true;
const rest = { 'data-x': 1, title: 't' };
const el = (
  <div className="box" id={'i' + 1} hidden aria-label='q"uote'>
    Text   with   spaces
    <span {...rest}>{items.map((x) => <b key={x}>{x}</b>)}</span>
    {flag && <i>yes</i>}
    {flag ? <em>t</em> : <em>f</em>}
    <>
      <br />frag
    </>
    <Card title="T" n={2} />
    {`tmpl ${1 + 1} <notjsx>`}
    {1 < 2 ? 'lt' : 'ge'}
    <ui.Badge label="m" />
  </div>
);
console.log(el);
const re = /<div>/g;
console.log('regex', re.test('<div>'), 4 / 2 / 1, '</notjsx>', typeof module);
// a line comment with <tags/> in it
/* a block comment with <div> */
const q = 'it\'s <b>', tq = `a\`<b>${'<c>'}`, rx = /[/<]\/x/.test('</x');
const commented = <div // line comment inside a tag
  a="1" /* block comment */ b={2} el=<i />>{'x'}</div>;
const escaped = <p title="tab<TAB>here">back\slash "quoted"</p>;
console.log(q, tq, rx, commented, escaped);
""".replace("<TAB>", "\t")
    r = js(code, name="app.jsx")
    assert out(r) == golden("jsx_entry")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("src,message", [
    ("const x = <div><span>unclosed</div>;\n", "unterminated JSX element"),
    ("const x = <div a={1;\n", "unterminated `{ … }` in JSX"),
    ("const x = <div;\n", "expected a JSX attribute name"),
    ("const x = <div a=b />;\n", "expected a JSX attribute value"),
    ("const x = <div a='1'\n", "unterminated JSX opening tag"),
    ("const x = </div>;\n", "expected a JSX element name after `<`"),
    ("const x = <div>{1 + 2</div>;\n", "unterminated `{ … }` in JSX"),
])
def test_jsx_transform_errors_abort_the_entry(js, src, message):
    """CATCHES: a JSX transform that silently emits broken code (or crashes) for malformed JSX
    instead of failing the .jsx entry with `Uncaught JSX transform failed for <file>: <reason>`
    and exit code 1."""
    r = js("console.log('must not run');\n" + src, name="bad.jsx")
    assert (r.returncode, out(r), err(r)) == (1, "", f"Uncaught JSX transform failed for bad.jsx: {message}\n")


def test_jsx_transform_output_via_transpiler(js, golden):
    """CATCHES: JSX lowering that emits the wrong factory calls: intrinsic vs component element
    types, quoting of dashed attribute keys, `true` for bare attributes, spread placement,
    element-valued attributes, JSX whitespace collapsing across lines, escaping in string
    literals, or rewriting `<` inside strings/templates/regexes/comments."""
    code = r"""
const t = new Bun.Transpiler({ loader: 'jsx' });
const cases = [
  'const a = <div className="x" data-id={1} disabled>hi {name}!</div>;',
  'const b = <><A.B c="d" {...rest} /><img src=\'q\' /></>;',
  'const c = cond ? <p>yes</p> : null; const d = x < y && y > z;',
  'function f() { return <ul>\n  {items.map(i => <li key={i}>{i}</li>)}\n  </ul>; }',
  'const e = <Foo render={() => <Bar />} el=<i /> label="a\\b" />;',
  'const s = "<notjsx>"; const t = `<${tag}>`; const r = /<re>/g; // <comment>\n/* <block> */',
  'const multi = <p>\n    first line\n    second   line\n\n  </p>;',
  'const ent = <p a="x\ty">tab\there {}{ }</p>;',
  'async function* g() { yield <a/>; await <b/>; return typeof <c/>; }',
  'const z = [<x-y key="1"/>, <_P/>, <$d/>];',
  "const q = 'it\\'s <b>', tq = `a\\`<b>${'<c>'}`, rx = /[/<]\\/x/;",
  'const k = <div // line comment\n  a="1" /* block */ b={2}>{"x"}</div>;',
  'const esc = <p title=\'say "hi"\'>back\\slash "quoted"\r</p>;',
];
for (const c of cases) console.log(t.transformSync(c));
for (const bad of ['<div>', '</div>', '<div a=b />', '<div a={1', '<div;', '<div a="1"']) {
  try { t.transformSync(bad); console.log('no error for', bad); } catch (e) { console.log('error:', e.message); }
}
"""
    r = js(code)
    assert out(r) == golden("jsx_transpiler")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typescript_entries_and_requires_strip_types(js, workdir, golden):
    """CATCHES: .ts/.cts entries or required .ts files that are run without erasing type
    annotations, interfaces, type aliases, `as`/`satisfies` and `import type`, a .cts entry that
    is not CommonJS, or an ESM import of a .ts file that is not bridged through require()."""
    write(workdir, {
        "geo.ts": "export interface Rect { w: number; h: number }\n"
                  "module.exports = { area: (r: { w: number; h: number }): number => r.w * r.h };\n",
        "types.ts": "export type Shape = { w: number; h: number };\n",
        "esm.mjs": "import geo from './geo.ts';\nconsole.log('mjs imports ts via require:', geo.area({ w: 4, h: 5 }));\n",
    })
    code = r"""
import type { Shape } from './types';
const { area } = require('./geo');
interface Point { x: number; y?: number }
type Pair = [string, string];
function sum(...xs: number[]): number { return xs.reduce((a: number, b: number) => a + b, 0); }
const p: Point = { x: 1, y: 2 } as Point;
const pair: Pair = ['a', 'b'];
const sat = { k: 1 } satisfies Record<string, number>;
function fmt(v: unknown, opt?: { upper: boolean }): string { if (opt && opt.upper) return String(v).toUpperCase(); return String(v); }
console.log(sum(1, 2, 3), p.x, pair.join(''), sat.k, area({ w: 2, h: 3 } as Shape), fmt('ts', { upper: true }));
console.log(typeof module, require.main === module, require('path').basename(__filename));
"""
    for name in ("main.ts", "main.cts"):
        r = js(code, name=name)
        assert out(r) == golden("typescript_" + name.replace(".", "_"))
        assert (r.returncode, r.stderr) == (0, b"")
    r = js((workdir / "esm.mjs").read_text(), name="esm.mjs")
    assert (r.returncode, out(r), r.stderr) == (0, "mjs imports ts via require: 20\n", b"")


# ------------------------------------------------------------------ node: builtin JS glue modules
def test_node_path_posix_and_win32(js, golden):
    """CATCHES: node:path helpers that normalise `..`/`.`/duplicate separators wrongly, compute
    relative paths or extnames incorrectly (dotfiles, trailing dots), mis-parse/format path
    objects, or use the wrong separator/delimiter for the win32 flavour."""
    code = r"""
const path = require('path');
const p = path.posix, w = path.win32;
console.log(p.join('/a/b', '../c', './d'), p.normalize('a//b/../c/.'), p.normalize(''), p.join(''), p.isAbsolute('/x'), p.isAbsolute('x'));
console.log(p.dirname('/a/b/c.txt'), p.basename('/a/b/c.txt', '.txt'), p.extname('x.tar.gz'), JSON.stringify(p.extname('.bashrc')), p.extname('a.'), p.basename('/a/b/'));
console.log(JSON.stringify(p.parse('/home/u/file.txt')), p.format({ dir: '/x', name: 'n', ext: '.e' }), p.format({ root: '/', base: 'b.js' }));
console.log(p.relative('/a/b/c', '/a/d'), p.relative('/a', '/a/b/c'), JSON.stringify(p.relative('/a/b', '/a/b')), p.resolve('/r', 's', '../t'), p.sep, p.delimiter);
console.log(p.normalize('/../x'), p.join('a', '', 'b'), p.dirname('a'), p.dirname('/'), JSON.stringify(p.basename('')), p.relative('/x/y', '/x/y/z/w'));
console.log(w.join('a', 'b', '..\\c'), w.normalize('a/b//c'), w.basename('x\\y.txt', '.txt'), w.extname('f.TXT'), w.relative('\\a\\b', '\\a\\c'));
console.log(JSON.stringify(w.parse('\\dir\\f.ext')), w.isAbsolute('\\\\server\\share'), w.isAbsolute('C:\\x'), w.isAbsolute('C:x'), w.sep, w.delimiter);
console.log(path === p, path.posix === p.posix, typeof path.toNamespacedPath, require('path/posix') === p, require('node:path/win32') === w);
"""
    r = js(code)
    assert out(r) == golden("node_path")
    assert (r.returncode, r.stderr) == (0, b"")


def test_node_events_emitter_semantics(js, golden):
    """CATCHES: an EventEmitter with wrong listener order (prepend/once), `emit` return values,
    newListener notifications, `this` binding, removal, unhandled 'error' throwing, listener
    introspection, or an events.once() that does not resolve with the argument array / reject on
    'error'."""
    code = r"""
const EventEmitter = require('events');
const { once, getEventListeners } = require('events');
const e = new EventEmitter();
const log = [];
e.on('x', (a, b) => log.push('on1 ' + a + b));
e.prependListener('x', () => log.push('prepended'));
e.once('x', () => log.push('once'));
e.on('newListener', (n) => log.push('newListener ' + n));
e.on('y', function () { log.push('this ok ' + (this === e)); });
console.log(e.emit('x', 1, 2), e.emit('x', 3, 4), e.emit('nothing'), e.listenerCount('x'), e.eventNames().join(','));
e.emit('y');
const h = () => log.push('removed listener ran');
e.on('z', h); e.off('z', h); e.emit('z');
try { e.emit('error', new Error('unhandled emitter error')); } catch (err) { log.push('threw ' + err.message); }
e.on('error', (err) => log.push('handled ' + err.message));
e.emit('error', new Error('second'));
console.log(log.join('\n'));
console.log(EventEmitter.defaultMaxListeners, e.getMaxListeners(), e.rawListeners('x').length, getEventListeners(e, 'x').length);
e.removeAllListeners('x');
console.log(e.listenerCount('x'), EventEmitter.EventEmitter === EventEmitter);
class Sub extends EventEmitter {}
const s = new Sub();
(async () => {
  setTimeout(() => s.emit('ready', 'v1', 'v2'), 1);
  console.log('once ->', JSON.stringify(await once(s, 'ready')));
  setTimeout(() => s.emit('error', new Error('rejects once')), 1);
  try { await once(s, 'ready'); } catch (err) { console.log('once rejected', err.message); }
})();
"""
    r = js(code)
    assert out(r) == golden("node_events")
    assert (r.returncode, r.stderr) == (0, b"")


def test_node_util_format_inspect_types_promisify(js, golden):
    """CATCHES: util.format with wrong %s/%d/%i/%f/%j/%O/%% handling or extra-argument joining,
    util.inspect with wrong depth cut-off, Map/Set/class/custom-inspect rendering, util.types
    predicates (including isProxy), deep equality, or promisify/callbackify plumbing."""
    code = r"""
const util = require('util');
console.log(util.format('%s|%d|%i|%f|%j|%O|%%|%c.', 'str', 42.5, 42.9, '1.5', { a: 1 }, { b: 2 }, 'css'), util.format('extra', 1, 'two'), util.format(1, 2));
console.log(util.inspect({ a: 1, s: 'q', n: null, u: undefined, arr: [1, [2, [3, [4]]]] }));
console.log(util.inspect({ fn() {}, sym: Symbol('x'), big: 10n, re: /x/g }), util.inspect(new Date(0)));
console.log(util.inspect(new Map([[1, { a: 1 }]])), util.inspect(new Set(['a'])), util.inspect({ deep: { a: { b: { c: {} } } } }, { depth: 1 }));
class Foo { constructor() { this.x = 1; } }
console.log(util.inspect(new Foo()), util.inspect([new Foo()]), util.inspect({ [util.inspect.custom]() { return 'CUSTOM'; } }));
console.log(util.types.isPromise(Promise.resolve()), util.types.isRegExp(/a/), util.types.isDate(new Date()),
  util.types.isProxy(new Proxy({}, {})), util.types.isProxy({}), util.types.isUint8Array(new Uint8Array()));
console.log(util.isDeepStrictEqual({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] }), util.isDeepStrictEqual([1], ['1']));
const p = util.promisify((x, cb) => setTimeout(() => cb(null, x * 2), 1));
const pf = util.promisify((cb) => cb(new Error('pfail')));
const cbf = util.callbackify(async (x) => x + 1);
p(21).then((v) => { console.log('promisify', v); return pf(); }).catch((e) => {
  console.log('promisify reject', e.message);
  cbf(1, (err, v) => console.log('callbackify', err, v));
});
console.log(typeof util.TextEncoder, util.stripVTControlCharacters('\u001b[31mred\u001b[0m'), util.inherits.length);
"""
    r = js(code)
    assert out(r) == golden("node_util")
    assert (r.returncode, r.stderr) == (0, b"")


def test_node_stream_pipeline_transform_objectmode(js, golden):
    """CATCHES: node:stream primitives that break async iteration of Readable.from, lose
    Transform push/flush output, mishandle objectMode piping, fail to propagate a transform error
    to the pipeline callback, decode multi-byte chunks with setEncoding wrongly, or never emit
    'drain' after write() returned false."""
    code = r"""
const { Readable, Writable, Transform, PassThrough, pipeline, finished } = require('stream');
const sp = require('stream/promises');
const log = [];
(async () => {
  const chunks = [];
  for await (const c of Readable.from(['a', 'b', 'c'])) chunks.push(c);
  log.push('from+asyncIter ' + chunks.join(''));
  const sink = [];
  const w = new Writable({ write(chunk, enc, cb) { sink.push(chunk.toString()); cb(); } });
  const t = new Transform({ transform(chunk, enc, cb) { this.push(chunk.toString().toUpperCase()); this.push('-'); cb(); }, flush(cb) { this.push('END'); cb(); } });
  await sp.pipeline(Readable.from(['x', 'y']), t, new PassThrough(), w);
  log.push('pipeline ' + sink.join(''));
  const objs = [];
  const ow = new Writable({ objectMode: true, write(o, enc, cb) { objs.push(o.n); cb(); } });
  const r = new Readable({ objectMode: true, read() {} });
  r.pipe(ow);
  r.push({ n: 1 }); r.push({ n: 2 }); r.push(null);
  await new Promise((res) => ow.on('finish', res));
  log.push('objectMode ' + objs.join(','));
  const bad = new Transform({ transform(c, e, cb) { cb(new Error('transform failed')); } });
  await new Promise((res) => pipeline(Readable.from(['q']), bad, new PassThrough(), (err) => { log.push('pipeline error ' + (err && err.message)); res(); }));
  const pr = new Readable({ read() {} });
  pr.setEncoding('utf8');
  pr.push(Buffer.from('é'));
  pr.push(null);
  let got = '';
  pr.on('data', (d) => (got += d));
  await new Promise((res) => finished(pr, (err) => { log.push('finished ' + err + ' ' + got); res(); }));
  const paused = new Readable({ read() {} });
  paused.push('p1'); paused.push('p2'); paused.push(null);
  log.push('read() ' + paused.read().toString());
  const wr = new Writable({ highWaterMark: 2, write(c, e, cb) { setTimeout(cb, 1); } });
  log.push('write returns ' + wr.write('abc'));
  wr.once('drain', () => { log.push('drain'); console.log(log.join('\n')); });
})();
"""
    r = js(code)
    assert out(r) == golden("node_stream")
    assert (r.returncode, r.stderr) == (0, b"")


def test_node_vm_contexts_and_scripts(js):
    """CATCHES: node:vm that evaluates in the wrong scope (context variables invisible, `var`
    declarations not landing on the contextified object), a Script that cannot be re-run in the
    same context, compileFunction with wrong parameters, or errors that are not thrown to the
    caller."""
    code = r"""
const vm = require('vm');
const ctx = vm.createContext({ x: 2 });
console.log(vm.runInContext('x * 21', ctx), vm.isContext(ctx), vm.isContext({}));
vm.runInContext('var y = x + 1;', ctx);
console.log(ctx.y, vm.runInNewContext('a + b', { a: 'A', b: 'B' }));
const s = new vm.Script('n = (typeof n === "number" ? n : 0) + 1');
const c2 = vm.createContext({});
s.runInContext(c2); s.runInContext(c2);
console.log(c2.n, vm.compileFunction('return a + b', ['a', 'b'])(2, 3));
const sb = { count: 0 };
vm.runInNewContext('count += 5', sb);
console.log(sb.count);
try { vm.runInNewContext('throw new TypeError("inside vm")'); } catch (e) { console.log(e.name, e.message); }
try { new vm.Script('let = ;'); } catch (e) { console.log(e.name); }
"""
    r = js(code)
    assert out(r) == "42 true false\n3 AB\n2 5\n5\nTypeError inside vm\nSyntaxError\n"
    assert (r.returncode, r.stderr) == (0, b"")
