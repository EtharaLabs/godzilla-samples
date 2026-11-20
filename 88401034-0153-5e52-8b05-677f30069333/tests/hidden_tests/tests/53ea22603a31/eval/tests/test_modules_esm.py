"""ES modules as run by lumen-cli: import/export forms, live bindings, namespaces, re-exports, cycles and
TDZ, top-level await ordering, dynamic import(), import attributes, import.meta, import defer, bare
specifier resolution through node_modules/package.json, CommonJS interop and node: builtins."""

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)

# Prints a string with the (realpath'd) working directory replaced by <cwd>.
NORM = r'''
import { realpathSync as __rp } from 'node:fs';
const __cwd = __rp(process.cwd());
const norm = (s) => String(s).split('file://' + __cwd).join('<url>').split(__cwd).join('<cwd>');
'''


def test_named_default_namespace_imports_and_live_bindings(run, workdir):
    """CATCHES: imports that copy values instead of binding live to the exporter (count must change after
    bump()), a namespace object with the wrong keys/order, missing @@toStringTag 'Module', namespaces
    that are writable/extensible, or a wrong error when assigning to an import binding."""
    write_files(workdir, {"lib.mjs": r'''
export let count = 0;
export function bump(by = 1) { count += by; return count; }
const hidden = 'h';
export { hidden as renamed };
export var later;
later = 'assigned after export';
export default { kind: 'default object' };
export const zeta = 'z', alpha = 'a';
'''})
    check_script(run, workdir, G, "esm_live_bindings", r'''
import lib, { count, bump, renamed as r } from './lib.mjs';
import * as ns from './lib.mjs';
import { count as again } from './lib.mjs';
console.log(lib.kind, count, r, ns.later);
bump(); bump(5);
console.log('after bump:', count, again, ns.count, ns.default === lib);
console.log(Object.keys(ns).join(','));
console.log(Reflect.ownKeys(ns).map(String).join(','));
console.log(ns[Symbol.toStringTag], Object.prototype.toString.call(ns), Object.getPrototypeOf(ns));
console.log(Object.isExtensible(ns), Object.isFrozen(ns), Object.isSealed(ns));
const d = Object.getOwnPropertyDescriptor(ns, 'count');
console.log(JSON.stringify(d));
for (const f of [() => { ns.count = 1; }, () => { ns.extra = 1; }, () => { delete ns.count; },
                 () => { count = 9; }, () => Object.defineProperty(ns, 'count', { value: 1 })]) {
  try { f(); console.log('no error'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
console.log('count' in ns, 'nope' in ns, ns.nope, delete ns.nope);
''', filename="main.mjs")


def test_reexports_star_conflicts_and_default_forms(run, workdir):
    """CATCHES: `export *` re-exporting `default`, conflicting star exports not being dropped from the
    namespace (or not raising the 'ambiguous export' SyntaxError when imported by name), a broken
    `export {a as b} from` of a missing name, wrong names for default-exported functions/classes, and
    `export * as ns` producing a copy instead of the dependency's namespace object or renamed
    re-exports losing liveness."""
    write_files(workdir, {
        "x.mjs": "export const dup = 'from x'; export const onlyX = 'X'; export default 'x default';\n",
        "y.mjs": "export const dup = 'from y'; export const onlyY = 'Y';\n",
        "star.mjs": "export * from './x.mjs';\nexport * from './y.mjs';\nexport const own = 'own';\n"
                    "export const dup2 = 'local wins';\n",
        "agg.mjs": "export * as xs from './x.mjs';\nexport { onlyY as why, default as xDefault } from './x.mjs';\n"
                   "export { default } from './fn.mjs';\n",
        "fn.mjs": "export default function named() { return 'fn result'; }\n",
        "cls.mjs": "export default class Klass { field = 'kf'; static s = 'st'; }\n",
        "anon.mjs": "export default function () { return 'anon'; }\nexport let state = 'before';\nstate = 'after';\n",
        "anoncls.mjs": "export default class { }\n",
        "expr.mjs": "export default [1, 2, 3].map((n) => n * 2);\n",
        "asdefault.mjs": "const v = 'renamed default'; export { v as default, v };\n",
        "amb.mjs": "import { dup } from './star.mjs';\nconsole.log(dup);\n",
    })
    # agg.mjs re-exports `onlyY` from x.mjs, which does not have it: a link error, caught via import().
    check_script(run, workdir, G, "esm_reexports", NORM + r'''
import * as star from './star.mjs';
console.log(Object.keys(star).join(','), 'dup' in star, 'default' in star, star.own);
try { await import('./agg.mjs'); } catch (e) { console.log(e.name + ': ' + norm(e.message)); }
try { await import('./amb.mjs'); } catch (e) { console.log(e.name + ': ' + norm(e.message)); }
import f from './fn.mjs';
import K from './cls.mjs';
import anon, { state } from './anon.mjs';
import AnonClass from './anoncls.mjs';
import arr from './expr.mjs';
import ad, { v } from './asdefault.mjs';
console.log(f.name, f(), K.name, new K().field, K.s);
console.log(JSON.stringify(anon.name), anon(), state, JSON.stringify(AnonClass.name), arr.join('|'), ad, ad === v);
''', filename="main.mjs")
    write_files(workdir, {
        "counter.mjs": "export let n = 0; export const inc = () => ++n; export default 'counter default';\n",
        "hub.mjs": "export * as counterNs from './counter.mjs';\n"
                   "export { n as current, inc as increment, default as label } from './counter.mjs';\n",
    })
    check_script(run, workdir, G, "esm_reexport_namespace", r'''
import * as hub from './hub.mjs';
import * as counter from './counter.mjs';
import { current, increment, label, counterNs } from './hub.mjs';
console.log(Object.keys(hub).join(','));
console.log(counterNs === counter, label, current);
increment(); increment();
console.log(current, counterNs.n, hub.current);
''', filename="main.mjs")


def test_cyclic_imports_and_tdz(run, workdir):
    """CATCHES: wrong evaluation order in an import cycle (the dependency that closes the cycle must run
    first), a missing ReferenceError (TDZ) when a cycle member reads an uninitialised `const`/`class`,
    and hoisted function declarations not being callable before their module body runs."""
    write_files(workdir, {
        "a.mjs": r'''
import { b, readA } from './b.mjs';
console.log('a body: b =', b, 'readA() =', readA());
export const a = 'A value';
export class Cls {}
export function hoisted() { return 'hoisted from a'; }
''',
        "b.mjs": r'''
import { a, Cls, hoisted } from './a.mjs';
console.log('b body start');
for (const [name, get] of [['a', () => a], ['Cls', () => Cls]]) {
  try { get(); console.log(name, 'readable'); } catch (e) { console.log(name, '->', e.name + ': ' + e.message); }
}
console.log('hoisted() =', hoisted());
export const b = 'B value';
export function readA() { try { return a; } catch (e) { return e.name; } }
''',
    })
    check_script(run, workdir, G, "esm_cycles", r'''
import { a } from './a.mjs';
import { readA } from './b.mjs';
console.log('main:', a, readA());
''', filename="main.mjs")


def test_top_level_await_ordering(run, workdir):
    """CATCHES: top-level await that blocks sibling modules (independent async siblings must start
    concurrently), a parent module that runs before all its async dependencies have settled, or
    synchronous modules not running in import order."""
    write_files(workdir, {
        "slow.mjs": "console.log('slow start');\nawait new Promise((r) => setTimeout(r, 40));\n"
                    "console.log('slow end');\nexport const slow = 'S';\n",
        "fast.mjs": "console.log('fast start');\nawait null;\nconsole.log('fast after await');\n"
                    "await Promise.resolve();\nconsole.log('fast end');\nexport const fast = 'F';\n",
        "sync.mjs": "console.log('sync module');\nexport const sync = 'Y';\n",
        "uses_slow.mjs": "import { slow } from './slow.mjs';\nconsole.log('uses_slow sees', slow);\n",
    })
    check_script(run, workdir, G, "esm_tla_order", r'''
import './uses_slow.mjs';
import { fast } from './fast.mjs';
import { sync } from './sync.mjs';
console.log('main body', fast, sync);
const v = await new Promise((r) => setTimeout(() => r('timer value'), 10));
console.log('main awaited', v);
''', filename="main.mjs")


def test_dependency_failures(run, workdir):
    """CATCHES: a failing dependency (one that throws during evaluation, or fails to parse) that lets
    the importer run anyway, a wrong exit code, or a different stderr report: for a throw the reference
    prints two 'Uncaught (in promise)' lines and a final 'Uncaught'; for a parse error nothing in the
    graph runs and only the SyntaxError is printed."""
    write_files(workdir, {"thr.mjs": "console.log('dependency runs');\nthrow new RangeError('dep failed');\n"})
    check_script(run, workdir, G, "esm_dep_throws", "import './thr.mjs';\nconsole.log('main never');\n",
                 filename="main.mjs", rc=1,
                 stderr="Uncaught (in promise) RangeError: dep failed\nUncaught (in promise) RangeError: dep failed\n"
                        "Uncaught RangeError: dep failed\n")
    write_files(workdir, {"dep.mjs": "console.log('dep must not run');\nlet x = ;\n",
                          "main.mjs": "console.log('main must not run');\nimport './dep.mjs';\n"})
    r = run(["main.mjs"])
    assert r.stdout == b""
    assert r.stderr == b'Uncaught SyntaxError: unexpected token Punct(";")\n'
    assert r.returncode == 1


def test_dynamic_import(run, workdir):
    """CATCHES: import() that re-evaluates a module or returns a fresh namespace each time, does not reject
    with the reference's messages for a missing file / missing export / throwing module (a throwing
    module must keep rejecting with the same error), or cannot load builtins and CommonJS files."""
    write_files(workdir, {
        "once.mjs": "console.log('once evaluated');\nexport const v = 1;\n",
        "thr.mjs": "console.log('thr evaluated');\nthrow new TypeError('thrown during evaluation');\n",
        "badname.mjs": "import { nope } from './once.mjs';\n",
        "legacy.cjs": "module.exports = { fromCjs: true, n: 7 };\n",
        "sub/rel.mjs": "export const who = 'sub/rel';\nexport const load = () => import('./sibling.mjs');\n",
        "sub/sibling.mjs": "export const who = 'sub/sibling';\n",
    })
    check_script(run, workdir, G, "esm_dynamic_import", NORM + r'''
console.log('before');
const p1 = import('./once.mjs');
const p2 = import('./once.mjs');
console.log('promises', p1 instanceof Promise, p1 === p2);
const [n1, n2] = await Promise.all([p1, p2]);
const n3 = await import('./once.mjs');
console.log(n1 === n2, n2 === n3, n1.v, Object.keys(n1).join(','));
for (const spec of ['./missing.mjs', './badname.mjs', './thr.mjs', './thr.mjs', 'no-such-package']) {
  try { await import(spec); console.log('loaded', spec); }
  catch (e) { console.log(spec, '->', e.name + ': ' + norm(e.message)); }
}
const fs = await import('node:fs');
const path = await import('path');
console.log(typeof fs.readFileSync, fs.default.readFileSync === fs.readFileSync, path.join('a', 'b'));
const cjs = await import('./legacy.cjs');
console.log(JSON.stringify(cjs.default), cjs.n);
const rel = await import('./sub/rel.mjs');
console.log(rel.who, (await rel.load()).who);
const spec = './once' + '.mjs';
console.log((await import(spec)) === n1);
''', filename="main.mjs")


def test_import_attributes_json_text_bytes(run, workdir):
    """CATCHES: JSON modules not parsed with JSON.parse semantics (a "__proto__" key must stay an own
    property), the BOM not being stripped, `type: "text"`/`"bytes"` imports returning the wrong kind of
    value, the same file under different attribute types sharing one module, or parse errors not
    surfacing as SyntaxError. Also pins that a BOM is only stripped for attribute imports: a plain
    `import('./x.json')` of a BOM-prefixed file fails to parse in the reference."""
    write_files(workdir, {
        "data.json": '﻿{"name": "lumen", "list": [1, 2, 3], "__proto__": {"polluted": true}, "nested": {"x": null}}\n',
        "bad.json": '{"a": 1,}\n',
        "plain.json": '{"k": "v", "arr": []}',
        "notes.txt": "line one\nline two é\n",
        "blob.bin": b"\x00\x01\xfe\xffABC",
    })
    check_script(run, workdir, G, "esm_import_attributes", r'''
import data from './data.json' with { type: 'json' };
import text from './notes.txt' with { type: 'text' };
import bytes from './blob.bin' with { type: 'bytes' };
import * as jsonNs from './data.json' with { type: 'json' };
console.log(data.name, data.list.length, data.nested.x, Object.keys(data).join(','));
console.log(Object.getPrototypeOf(data) === Object.prototype, data.polluted, JSON.stringify(data.__proto__));
console.log(Object.keys(jsonNs).join(','), jsonNs.default === data);
console.log(JSON.stringify(text), text.length);
console.log(bytes.constructor.name, bytes.length, Array.from(bytes).join(','));
const again = await import('./data.json', { with: { type: 'json' } });
console.log(again.default === data);
const asText = await import('./data.json', { with: { type: 'text' } });
console.log(typeof asText.default, asText.default.length, asText.default.startsWith('{'));
const viaAttr = await import('./plain.json', { with: { type: 'json' } });
const viaExt = await import('./plain.json');
console.log(viaAttr.default === viaExt.default, viaExt.default.k, JSON.stringify(viaAttr.default));
try { await import('./data.json'); console.log('BOM json loaded without attributes'); } catch (e) { console.log('BOM json without attributes:', e.name + ': ' + e.message); }
try { await import('./bad.json', { with: { type: 'json' } }); } catch (e) { console.log(e.name + ': ' + e.message); }
''', filename="main.mjs")


def test_import_meta(run, workdir):
    """CATCHES: import.meta.url/filename/dirname not being per-module (a nested module must see its own
    path), missing the file:// scheme, a non-null-prototype or wrongly-keyed import.meta object, or
    import.meta not being the same object on every access within a module."""
    write_files(workdir, {"deep/er/inner.mjs": r'''
export const meta = import.meta;
export const info = [import.meta.url, import.meta.filename, import.meta.dirname];
'''})
    check_script(run, workdir, G, "esm_import_meta", NORM + r'''
import { meta, info } from './deep/er/inner.mjs';
console.log(norm(import.meta.url));
console.log(norm(import.meta.filename), norm(import.meta.dirname));
console.log(info.map(norm).join(' | '));
console.log(Object.keys(import.meta).join(','), Object.getPrototypeOf(import.meta), import.meta === import.meta);
console.log(meta === import.meta, typeof import.meta.resolve, import.meta.main);
console.log(new URL('./x/y.txt', import.meta.url).pathname.endsWith('/x/y.txt'));
''', filename="main.mjs")


def test_import_defer_and_source_phase(run, workdir):
    """CATCHES: `import defer` evaluating the deferred module eagerly (it must run only on the first
    string-keyed access, exactly once, while async modules in its graph -- or a deferred module that
    itself uses top-level await -- are still evaluated eagerly; also the dynamic import.defer()), a
    deferred namespace that is not one shared 'Deferred Module' object distinct from the ordinary
    namespace, a throwing deferred module not rethrowing on each access, a missing TypeError when a
    deferred namespace is touched during its own evaluation, or source-phase imports of JS modules
    not failing with the reference's SyntaxError."""
    write_files(workdir, {
        "lazy.mjs": "console.log('lazy evaluated');\nexport const value = 42;\nexport const other = 'o';\n",
        "eager.mjs": "console.log('eager evaluated');\n",
        "thr.mjs": "console.log('thr evaluated');\nthrow new Error('deferred boom');\nexport const x = 1;\n",
        "cyc.mjs": "import defer * as self from './cyc.mjs';\nconsole.log('cyc evaluated');\nlet r;\n"
                   "try { r = typeof self.read; } catch (e) { r = e.name + ': ' + e.message; }\n"
                   "export const read = () => 'cyc saw: ' + r;\n",
        "with_tla.mjs": "import './tla_dep.mjs';\nconsole.log('with_tla evaluated');\nexport const v = 'tla value';\n",
        "tla_dep.mjs": "console.log('tla_dep start');\nawait null;\nconsole.log('tla_dep end');\n",
        "src.mjs": "import source s from './eager.mjs';\nconsole.log(typeof s);\n",
        "dyn_lazy.mjs": "console.log('dyn_lazy evaluated');\nexport const dv = 'dynamic deferred';\n",
        "async_mod.mjs": "console.log('async_mod start');\nif (true) { for (let i = 0; i < 1; i++) { await null; } }\n"
                         "console.log('async_mod end');\nexport const w = 'async w';\n",
    })
    check_script(run, workdir, G, "esm_import_defer", r'''
import defer * as asyncMod from './async_mod.mjs';
import defer * as lazy from './lazy.mjs';
import defer * as lazy2 from './lazy.mjs';
import defer * as thr from './thr.mjs';
import defer * as cyc from './cyc.mjs';
import defer * as withTla from './with_tla.mjs';
import './eager.mjs';
console.log('main start');
console.log(lazy === lazy2, lazy[Symbol.toStringTag], Object.prototype.toString.call(lazy), 'symbol access is lazy');
console.log('first touch', lazy.value);
console.log('second touch', lazy.other, Object.keys(lazy).join(','));
const ordinary = await import('./lazy.mjs');
console.log(ordinary === lazy, ordinary[Symbol.toStringTag], ordinary.value);
for (let i = 0; i < 2; i++) {
  try { console.log(thr.x); } catch (e) { console.log('thr access', i, e.name + ': ' + e.message); }
}
console.log(cyc.read());
console.log(withTla.v);
const dyn = await import.defer('./dyn_lazy.mjs');
console.log('import.defer resolved', dyn[Symbol.toStringTag]);
console.log('touch', dyn.dv, asyncMod.w, (await import.defer('./async_mod.mjs')) === asyncMod);
try { await import('./src.mjs'); } catch (e) { console.log(e.name + ': ' + e.message); }
''', filename="main.mjs")


def test_evaluation_order_and_module_semantics(run, workdir):
    """CATCHES: modules evaluated more than once when imported from several places, a non post-order
    evaluation, sloppy-mode module code (modules are strict and `this` is undefined), or top-level
    declarations leaking onto globalThis."""
    write_files(workdir, {
        "o1.mjs": "import './o3.mjs';\nconsole.log('o1');\n",
        "o2.mjs": "import './o3.mjs';\nimport './o1.mjs';\nconsole.log('o2');\n",
        "o3.mjs": "console.log('o3', typeof this);\nvar leaked = 1;\nexport const three = 3;\n",
    })
    check_script(run, workdir, G, "esm_eval_order", r'''
import './o1.mjs';
import './o2.mjs';
import { three } from './o3.mjs';
console.log('main', three, typeof this, typeof globalThis.leaked);
try { undeclared = 5; console.log('sloppy'); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log((function () { return this; })() === undefined ? 'strict functions' : 'sloppy functions');
console.log(typeof require, typeof module, typeof exports, typeof __filename);
''', filename="main.mjs")


def test_bare_specifiers_and_package_exports(run, workdir):
    """CATCHES: wrong node_modules resolution for ESM imports: the `exports` "import" condition must win
    over "require"/"main", subpath exports ("./feature") must map, scoped packages and `type: module`
    packages must load as ESM, "module"/"main" fallbacks and directory-walking up to an ancestor
    node_modules must work."""
    write_files(workdir, {
        "node_modules/dual/package.json": '{"name": "dual", "main": "./lib/main.cjs", "exports": {".": {'
                                          '"require": "./lib/main.cjs", "import": "./lib/esm.mjs"}, "./feature": '
                                          '{"import": "./lib/feature.mjs", "default": "./lib/feature.cjs"}}}',
        "node_modules/dual/lib/esm.mjs": "export const kind = 'esm build';\nexport default 'dual default';\n",
        "node_modules/dual/lib/main.cjs": "exports.kind = 'cjs build';\n",
        "node_modules/dual/lib/feature.mjs": "export const feat = 'esm feature';\n",
        "node_modules/dual/lib/feature.cjs": "exports.feat = 'cjs feature';\n",
        "node_modules/@scope/util/package.json": '{"name": "@scope/util", "type": "module", "exports": "./src/u.js"}',
        "node_modules/@scope/util/src/u.js": "export const u = 'scoped util';\nexport default (s) => `<${s}>`;\n",
        "node_modules/modfield/package.json": '{"name": "modfield", "type": "module", "module": "esm/index.js", "main": "cjs/index.js"}',
        "node_modules/modfield/esm/index.js": "export const which = 'module field';\n",
        "node_modules/modfield/cjs/index.js": "exports.which = 'main field';\n",
        "node_modules/plainmain/package.json": '{"name": "plainmain", "main": "entry"}',
        "node_modules/plainmain/entry.js": "module.exports = { which: 'main without extension' };\n",
        "node_modules/indexonly/index.mjs": "export const which = 'index.mjs probe';\n",
        "node_modules/withfile/extra.mjs": "export const which = 'direct file in package';\n",
        "app/src/deep/main.mjs": r'''
import dual, { kind } from 'dual';
import { feat } from 'dual/feature';
import wrap, { u } from '@scope/util';
import { which as mod } from 'modfield';
import pm from 'plainmain';
import { which as idx } from 'indexonly';
import { which as wf } from 'withfile/extra.mjs';
console.log(dual, '|', kind, '|', feat);
console.log(wrap(u), '|', mod, '|', pm.which, '|', idx, '|', wf);
try { await import('dual/missing-subpath'); } catch (e) { console.log(e.name, e.message.startsWith('module not found: dual/missing-subpath')); }
''',
    })
    r = run(["app/src/deep/main.mjs"])
    assert_result(r, G / "esm_bare_specifiers.golden")


def test_esm_imports_commonjs(run, workdir):
    """CATCHES: CommonJS interop that does not expose module.exports as the default export, misses the
    statically detectable named exports (exports.x =, module.exports = {a, b}, defineProperty), makes
    named exports live (the reference snapshots them at import time) or evaluates the CJS file twice."""
    write_files(workdir, {
        "counter.cjs": r'''
console.log('counter.cjs evaluated');
let count = 0;
exports.inc = () => ++count;
exports.label = 'counter';
Object.defineProperty(exports, 'current', { enumerable: true, get() { return count; } });
''',
        "shape.cjs": "const a = 1, b = 2;\nmodule.exports = { a, b, sum: a + b, 'quoted': 'q' };\n",
        "fn.cjs": "module.exports = function greet(n) { return 'hi ' + n; };\nmodule.exports.extra = 'prop on fn';\n",
        "transpiled.cjs": 'Object.defineProperty(exports, "__esModule", { value: true });\n'
                          'exports.default = "transpiled default";\nexports.named = "transpiled named";\n',
        "legacy/package.json": '{"name": "legacy"}',
        "legacy/old.js": "exports.fromJs = 'plain .js with no type is CommonJS';\n",
        "data.json": '{"fromJson": [1, 2]}',
    })
    check_script(run, workdir, G, "esm_imports_cjs", r'''
import counter, { inc, label, current } from './counter.cjs';
import * as counterNs from './counter.cjs';
import shape, { a, b, sum, quoted } from './shape.cjs';
import greet, { extra } from './fn.cjs';
import tr, { named } from './transpiled.cjs';
import { fromJs } from './legacy/old.js';
import json from './data.json';
console.log(label, inc(), inc(), 'named snapshot:', current, 'live via default:', counter.current);
console.log(Object.keys(counterNs).sort().join(','), counterNs.default === counter);
console.log(JSON.stringify(shape), a, b, sum, quoted);
console.log(greet('x'), extra, typeof greet);
console.log(JSON.stringify(tr), named);
console.log(fromJs, JSON.stringify(json));
const again = await import('./counter.cjs');
console.log(again.default === counter, again.default.current);
''', filename="main.mjs")


def test_node_builtin_imports(run, workdir):
    """CATCHES: builtins only importable with or without the `node:` prefix, missing named exports of
    builtins (fs, path, events, util, process), named exports that are not the same functions as the
    default export's members, or unknown node: specifiers not rejecting."""
    check_script(run, workdir, G, "esm_builtins", r'''
import fs, { readFileSync, writeFileSync, promises } from 'node:fs';
import { readFile } from 'fs/promises';
import path, { join, basename } from 'path';
import { EventEmitter } from 'node:events';
import EE from 'events';
import { format } from 'node:util';
import process2, { argv, env } from 'node:process';
import * as osNs from 'node:os';
writeFileSync('out.txt', 'written by esm');
console.log(readFileSync('out.txt', 'utf8'), fs.readFileSync === readFileSync, promises.readFile === readFile);
console.log(path.join === join, basename('/a/b/c.txt'), EE === EventEmitter, typeof EventEmitter.prototype.on);
console.log(format('%s=%d', 'n', 42), process2 === process, argv === process.argv, env === process.env);
console.log(typeof osNs.default, typeof osNs.EOL, JSON.stringify(osNs.EOL));
for (const s of ['node:nope', 'node:fs/nope']) {
  try { await import(s); console.log('loaded', s); } catch (e) { console.log(s, '->', e.name + ': ' + e.message.split(' (imported')[0]); }
}
''', filename="main.mjs")
    assert (workdir / "out.txt").read_bytes() == b"written by esm"


def test_dynamic_import_from_commonjs(run, workdir):
    """CATCHES: import() unavailable in CommonJS scripts, resolving relative to the cwd instead of the
    calling file, or not loading ESM packages; also pins that require() of an ES module fails with the
    parser's SyntaxError (no require(esm) support)."""
    write_files(workdir, {
        "lib/esm.mjs": "export const v = 'esm value';\nexport default function f() { return 'default fn'; }\n",
        "lib/entry.cjs": r'''
console.log('cjs entry start');
import('./esm.mjs').then((ns) => {
  console.log('dynamic', ns.v, ns.default(), Object.keys(ns).join(','));
  return import('./esm.mjs').then((again) => console.log('same namespace', again === ns));
});
try { require('./esm.mjs'); } catch (e) { console.log('require(esm):', e.name + ': ' + e.message); }
console.log('cjs entry end');
''',
    })
    r = run(["lib/entry.cjs"])
    assert_result(r, G / "esm_dynamic_from_cjs.golden")


def test_entry_type_module_package(run, workdir):
    """CATCHES: a `.js` entry inside a `"type": "module"` package not running as ESM, or such a module's
    relative `.js` imports being treated as CommonJS (no named exports), and extensionless relative
    specifiers not probing .mjs/.js like the reference does."""
    write_files(workdir, {
        "pkg/package.json": '{"name": "p", "type": "module"}',
        "pkg/util.js": "export const util = 'util.js as ESM';\nexport default 'util default';\n",
        "pkg/probe.mjs": "export const probe = 'found by extension probe';\n",
        "pkg/dir/index.js": "export const idx = 'directory index.js';\n",
        "pkg/main.js": r'''
import def, { util } from './util.js';
import { probe } from './probe';
import { idx } from './dir';
console.log(def, '|', util, '|', probe, '|', idx);
console.log(typeof require, typeof module, import.meta.url.endsWith('/pkg/main.js'));
''',
    })
    r = run(["pkg/main.js"])
    assert_result(r, G / "esm_type_module_entry.golden")


def test_cjs_named_export_detection(run, workdir):
    """CATCHES: a CommonJS export-name scanner that differs from the reference's: it must follow
    `module.exports = require('./x')` and `Object.assign(module.exports, require('./x'))` re-exports,
    read esbuild's `__export(target, {...})` and `0 && (module.exports = {...})` hints (a hinted name
    with no value is still exported as undefined), skip `exports.x ==` comparisons, bracket
    assignments and reserved words; plus JSON attribute imports resolved from a bare package path."""
    write_files(workdir, {
        "node_modules/pkg/package.json": '{"name": "pkg", "version": "1.2.3"}',
        "node_modules/pkg/data.json": '{"pkgData": true}',
        "lib/inner.cjs": "exports.innerA = 'A';\nexports.innerB = 'B';\n",
        "lib/reexp.cjs": "module.exports = require('./inner.cjs');\n",
        "lib/assign.cjs": "Object.assign(module.exports, require('./inner.cjs'), { extra: 1 });\nexports.own = 'own';\n",
        "lib/bundled.cjs": r'''
var __defProp = Object.defineProperty;
var __export = (target, all) => { for (var name in all) __defProp(target, name, { get: all[name], enumerable: true }); };
var exports_mod = {};
__export(exports_mod, { alpha: () => alpha, beta: () => beta, "default": () => def });
const alpha = 'alpha', beta = 'beta', def = 'bundled default';
module.exports = exports_mod;
0 && (module.exports = { alpha, beta, gamma });
''',
        "lib/tricky.cjs": "exports.eq == 1;\nexports.arrowish = 1;\nexports['bracket'] = 2;\n"
                          "module.exports.chained = exports.other = 3;\nexports.class = 'reserved';\n",
    })
    check_script(run, workdir, G, "esm_cjs_export_detection", r'''
import data from 'pkg/data.json' with { type: 'json' };
import pkgJson from 'pkg/package.json' with { type: 'json' };
import * as reexp from './lib/reexp.cjs';
import * as assign from './lib/assign.cjs';
import * as bundled from './lib/bundled.cjs';
import * as tricky from './lib/tricky.cjs';
console.log(JSON.stringify(data), pkgJson.version);
const show = (ns) => Object.keys(ns).filter((k) => k !== 'default').sort().map((k) => k + '=' + JSON.stringify(ns[k])).join(' ');
console.log('reexp', show(reexp));
console.log('assign', show(assign), JSON.stringify(assign.default));
console.log('bundled', show(bundled), JSON.stringify(bundled.default));
console.log('tricky', show(tricky), JSON.stringify(tricky.default));
''', filename="main.mjs")
