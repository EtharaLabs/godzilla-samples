"""Entry-point module kind (.mjs/.cjs/.js + package.json "type"), package.json lookup and module resolution."""

import pytest

from conftest import golden, write_files

KIND = "console.log(typeof require, typeof module, typeof exports);\n"
CJS = b"function object object\n"
ESM = b"function undefined undefined\n"


def _res(r):
    return r.returncode, r.stdout, r.stderr


def test_js_without_package_json_is_commonjs(run, workdir):
    """CATCHES: implementations that run a plain .js entry as an ES module when no package.json says so."""
    write_files(workdir, {"a.js": KIND})
    assert _res(run(["a.js"])) == (0, CJS, b"")


def test_mjs_is_always_esm(run, workdir):
    """CATCHES: .mjs entries run as CommonJS, or classified by package.json instead of by extension."""
    write_files(workdir, {"package.json": '{"type": "commonjs"}\n', "a.mjs": KIND})
    assert _res(run(["a.mjs"])) == (0, ESM, b"")


def test_cjs_is_always_commonjs(run, workdir):
    """CATCHES: .cjs entries run as ES modules when package.json says type module."""
    write_files(workdir, {"package.json": '{"type": "module"}\n', "a.cjs": KIND})
    assert _res(run(["a.cjs"])) == (0, CJS, b"")


def test_js_with_type_module_is_esm(run, workdir):
    """CATCHES: implementations that ignore package.json "type": "module" for a .js entry."""
    write_files(workdir, {"package.json": '{"name": "x", "type": "module"}\n', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, ESM, b"")


def test_js_with_type_commonjs(run, workdir):
    """CATCHES: implementations that treat any package.json "type" value as ESM."""
    write_files(workdir, {"package.json": '{"type": "commonjs"}\n', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, CJS, b"")


def test_type_module_found_in_ancestor_directory(run, workdir):
    """CATCHES: package.json lookup that only inspects the script's own directory instead of walking up."""
    write_files(workdir, {"package.json": '{"type":"module"}', "src/lib/deep/a.js": KIND})
    assert _res(run(["src/lib/deep/a.js"])) == (0, ESM, b"")


def test_nearest_package_json_wins(run, workdir):
    """CATCHES: lookups that keep walking past the nearest package.json (one without "type" means CommonJS)."""
    write_files(workdir, {"package.json": '{"type": "module"}', "sub/package.json": '{"name": "sub"}', "sub/a.js": KIND})
    assert _res(run(["sub/a.js"])) == (0, CJS, b"")


def test_nearest_package_json_module_overrides_parent(run, workdir):
    """CATCHES: lookups that let an outer package.json override a nearer "type": "module"."""
    write_files(workdir, {"package.json": '{"type": "commonjs"}', "sub/package.json": '{"type": "module"}', "sub/a.js": KIND})
    assert _res(run(["sub/a.js"])) == (0, ESM, b"")


def test_package_json_directory_is_skipped(run, workdir):
    """CATCHES: lookups that treat a directory named package.json as the nearest manifest."""
    write_files(workdir, {"package.json": '{"type":"module"}', "x/package.json/keep": "", "x/a.js": KIND})
    assert _res(run(["x/a.js"])) == (0, ESM, b"")


def test_type_field_spacing(run, workdir):
    """CATCHES: a "type" scan that cannot handle whitespace and newlines around the colon."""
    write_files(workdir, {"package.json": '{\n  "type"\n    :\n  "module"\n}\n', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, ESM, b"")


def test_type_value_is_case_sensitive(run, workdir):
    """CATCHES: case-insensitive matching of the "type" value ("Module" is not "module")."""
    write_files(workdir, {"package.json": '{"type": "Module"}', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, CJS, b"")


def test_type_key_is_case_sensitive(run, workdir):
    """CATCHES: case-insensitive matching of the "type" key."""
    write_files(workdir, {"package.json": '{"Type": "module"}', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, CJS, b"")


def test_non_string_type_is_commonjs(run, workdir):
    """CATCHES: a non-string "type" value being treated as module."""
    write_files(workdir, {"package.json": '{"type": 1}', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, CJS, b"")


def test_malformed_package_json_still_scanned(run, workdir):
    """CATCHES: implementations that fail on (or ignore) a syntactically broken package.json; the entry check only scans for "type"."""
    write_files(workdir, {"package.json": '{"type": "module",, oops', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, ESM, b"")


def test_empty_package_json_is_commonjs(run, workdir):
    """CATCHES: an empty package.json causing an error or being skipped in favour of an outer manifest."""
    write_files(workdir, {"package.json": '{"type": "module"}', "sub/package.json": "", "sub/a.js": KIND})
    assert _res(run(["sub/a.js"])) == (0, CJS, b"")


def test_entry_type_scan_uses_first_type_occurrence(run, workdir):
    """CATCHES: a full JSON parser for the entry check; the entry scan reads the first "type" token, so a "type" value earlier in the file hides the key."""
    write_files(workdir, {"package.json": '{"name": "type", "type": "module"}', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, CJS, b"")


def test_entry_type_scan_sees_nested_type(run, workdir):
    """CATCHES: a full JSON parser for the entry check; a nested "type": "module" is the first occurrence and makes the entry ESM."""
    write_files(workdir, {"package.json": '{"config": {"type": "module"}}', "a.js": KIND})
    assert _res(run(["a.js"])) == (0, ESM, b"")


def test_commonjs_entry_globals(run, workdir):
    """CATCHES: CommonJS entries without require.main === module, or with wrong __filename/__dirname."""
    write_files(workdir, {"dir/main.js": "const path = require('path');\n"
                          "console.log(require.main === module, path.basename(__filename), path.basename(__dirname),"
                          " path.isAbsolute(__filename), this === module.exports);\n"})
    assert _res(run(["dir/main.js"])) == (0, b"true main.js dir true true\n", b"")


def test_esm_entry_import_meta(run, workdir):
    """CATCHES: ES module entries without a file:// import.meta.url, or with CommonJS-only bindings in scope."""
    write_files(workdir, {"m.mjs": "console.log(import.meta.url.startsWith('file:///'), import.meta.url.endsWith('/m.mjs'),"
                          " typeof __filename, this === undefined);\n"})
    assert _res(run(["m.mjs"])) == (0, b"true true undefined true\n", b"")


def test_esm_top_level_await_and_timers(run, workdir):
    """CATCHES: ES module entries whose top-level await does not drive timers before the process exits."""
    write_files(workdir, {"t.mjs": "console.log('a');\nawait new Promise(r => setTimeout(r, 10));\nconsole.log('b');\n"
                          "setTimeout(() => console.log('d'), 5);\nconsole.log('c');\n"})
    assert _res(run(["t.mjs"])) == (0, b"a\nb\nc\nd\n", b"")


def test_typescript_entry_commonjs(run, workdir):
    """CATCHES: .ts entries whose type annotations are not stripped, or that are not run as CommonJS by default."""
    write_files(workdir, {"a.ts": "interface Pt { x: number; y: number }\ntype S = string | number;\n"
                          "function show(p: Pt, label: S): string { return `${label}:${p.x + p.y}` }\n"
                          "const n: number = 41;\nconsole.log(show({ x: n, y: 1 } as Pt, 'sum'), typeof module);\n"})
    assert _res(run(["a.ts"])) == (0, b"sum:42 object\n", b"")


def test_cts_entry_requires_ts_dependency(run, workdir):
    """CATCHES: .cts entries that are not CommonJS, or whose require() cannot load an extensionless .ts dependency."""
    write_files(workdir, {"value.ts": "const value: number = 41; module.exports = value;\n",
                          "main.cts": "const value: number = require('./value'); console.log(value + 1);\n"})
    assert _res(run(["main.cts"])) == (0, b"42\n", b"")


def test_typescript_entry_with_type_module(run, workdir):
    """CATCHES: .ts entries that ignore package.json "type": "module"."""
    write_files(workdir, {"package.json": '{"type": "module"}', "a.ts": KIND})
    assert _res(run(["a.ts"])) == (0, ESM, b"")


def test_jsx_entry_uses_react_create_element(run, workdir):
    """CATCHES: .jsx entries that are not transformed to React.createElement calls (classic runtime) or not run as ESM."""
    src = ("globalThis.React = { createElement: (t, p, ...c) => ({ t, p, c }), Fragment: 'frag' };\n"
           "const name = 'world';\n"
           "const el = <div className=\"x\" id={name}>hello {name}<br/><>frag</></div>;\n"
           "console.log(JSON.stringify(el), typeof module);\n")
    write_files(workdir, {"a.jsx": src})
    r = run(["a.jsx"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "jsx_entry")


def test_jsx_entry_without_react(run, workdir):
    """CATCHES: JSX entries that use an automatic runtime instead of requiring a React binding."""
    write_files(workdir, {"a.jsx": "const el = <p>hi</p>;\n"})
    assert _res(run(["a.jsx"])) == (1, b"", b"Uncaught (in promise) ReferenceError: React is not defined\n"
                                            b"Uncaught ReferenceError: React is not defined\n")


def test_esm_imports_commonjs_named_exports(run, workdir):
    """CATCHES: ESM-to-CommonJS interop that only exposes a default export (static export-name detection for exports.X / defineProperty)."""
    write_files(workdir, {
        "lib.cjs": "exports.alpha = 1;\nmodule.exports.beta = function () { return 2 };\n"
                   "Object.defineProperty(exports, 'gamma', { enumerable: true, get() { return 3 } });\nexports.notAssigned == 4;\n",
        "m.mjs": "import lib, { alpha, beta, gamma } from './lib.cjs';\nimport * as ns from './lib.cjs';\n"
                 "console.log(alpha, beta(), gamma, typeof lib, Object.keys(ns).sort().join(','));\n"})
    assert _res(run(["m.mjs"])) == (0, b"1 2 3 object alpha,beta,default,gamma\n", b"")


def test_esm_imports_object_literal_exports(run, workdir):
    """CATCHES: interop that misses names from `module.exports = { a, b: ... }` or follows re-exports incorrectly."""
    write_files(workdir, {
        "inner.js": "exports.deep = 'deep value';\n",
        "lib.js": "const helper = () => 'h';\nmodule.exports = { helper, 'quoted': 1, nested: { skip: true }, fn() { return 'f' } };\n",
        "re.js": "module.exports = require('./inner');\n",
        "m.mjs": "import * as lib from './lib.js';\nimport { deep } from './re.js';\n"
                 "console.log(Object.keys(lib).sort().join(','), lib.helper(), lib.fn(), deep);\n"})
    assert _res(run(["m.mjs"])) == (0, b"default,fn,helper,nested,quoted h f deep value\n", b"")


def test_esm_imports_json_and_builtins(run, workdir):
    """CATCHES: ESM loaders that cannot import .json files (default export via JSON.parse) or named exports of node: builtins."""
    write_files(workdir, {
        "d.json": '{"x": [1, 2], "__proto__": {"polluted": true}}',
        "m.mjs": "import data from './d.json';\nimport { join } from 'node:path';\nimport { existsSync } from 'fs';\n"
                 "console.log(JSON.stringify(data), Object.keys(data).join(','), ({}).polluted, join('a', 'b'), existsSync('m.mjs'));\n"})
    r = run(["m.mjs"])
    assert _res(r) == (0, b'{"x":[1,2],"__proto__":{"polluted":true}} x,__proto__ undefined a/b true\n', b"")


def test_esm_import_attributes(run, workdir):
    """CATCHES: import attributes (type json/text/bytes) not honoured, a BOM not stripped for text, or bytes not exact."""
    write_files(workdir, {
        "t.txt": b"\xef\xbb\xbfhi\n",
        "d.json": '{"x": [1, 2]}',
        "m.mjs": "import txt from './t.txt' with { type: 'text' };\nimport j from './d.json' with { type: 'json' };\n"
                 "import b from './t.txt' with { type: 'bytes' };\n"
                 "console.log(JSON.stringify(txt), j.x.length, b.constructor.name, Array.from(b).join(','));\n"})
    assert _res(run(["m.mjs"])) == (0, b'"hi\\n" 2 Uint8Array 239,187,191,104,105,10\n', b"")


def test_esm_extension_and_index_resolution(run, workdir):
    """CATCHES: relative ESM specifiers that are not probed with extensions (.mjs before .js) or directory index/main files."""
    write_files(workdir, {
        "lib.mjs": "export const which = 'lib.mjs';\n",
        "lib.js": "exports.which = 'lib.js';\n",
        "only.js": "exports.which = 'only.js';\n",
        "dir/index.js": "exports.which = 'dir/index.js';\n",
        "pkgdir/package.json": '{"main": "start.js"}',
        "pkgdir/start.js": "exports.which = 'pkgdir/start.js';\n",
        "m.mjs": "import { which as a } from './lib';\nimport { which as b } from './only';\nimport { which as c } from './dir';\n"
                 "import { which as d } from './pkgdir';\nconsole.log(a, b, c, d);\n"})
    assert _res(run(["m.mjs"])) == (0, b"lib.mjs only.js dir/index.js pkgdir/start.js\n", b"")


def test_esm_relative_js_follows_package_type(run, workdir):
    """CATCHES: imported .js files classified by the entry's kind rather than their own nearest package.json."""
    write_files(workdir, {
        "esm/package.json": '{"type": "module"}',
        "esm/x.js": "export const kind = typeof module;\n",
        "cjs/x.js": "exports.kind = typeof module;\n",
        "m.mjs": "import { kind as a } from './esm/x.js';\nimport { kind as b } from './cjs/x.js';\nconsole.log(a, b);\n"})
    assert _res(run(["m.mjs"])) == (0, b"undefined object\n", b"")


@pytest.fixture
def node_modules(workdir):
    write_files(workdir, {
        "node_modules/cjs-pkg/package.json": '{"name": "cjs-pkg", "main": "lib/entry.js"}',
        "node_modules/cjs-pkg/lib/entry.js": "exports.hello = (n) => 'hello ' + n; exports.kind = 'cjs';\n",
        "node_modules/esm-pkg/package.json": '{"name": "esm-pkg", "type": "module", "main": "dist/index.js"}',
        "node_modules/esm-pkg/dist/index.js": "export const kind = 'esm'; export default function greet() { return 'esm default' }\n",
        "node_modules/@scope/thing/package.json": '{"name": "@scope/thing"}',
        "node_modules/@scope/thing/index.js": "module.exports = { scoped: true, name: 'thing' };\n",
        "node_modules/exp-pkg/package.json": '{"name": "exp-pkg", "exports": {".": {"types": "./x.d.ts", "import": "./dist/esm.mjs", '
                                             '"require": "./dist/cjs.js"}, "./sub": {"import": "./dist/sub/index.mjs"}}}',
        "node_modules/exp-pkg/dist/esm.mjs": "export const via = 'import condition';\n",
        "node_modules/exp-pkg/dist/cjs.js": "exports.via = 'require condition';\n",
        "node_modules/exp-pkg/dist/sub/index.mjs": "export const sub = 'subpath export';\n",
        "node_modules/mod-field/package.json": '{"name": "mod-field", "main": "main.js", "module": "module.mjs"}',
        "node_modules/mod-field/main.js": "exports.from = 'main';\n",
        "node_modules/mod-field/module.mjs": "export const from = 'module';\n",
        "node_modules/file-pkg/extra.js": "exports.extra = 'literal file';\n",
    })
    return workdir


def test_esm_node_modules_resolution(run, node_modules):
    """CATCHES: bare-specifier resolution that ignores main/module/exports(import condition)/subpath exports/scoped packages."""
    write_files(node_modules, {"main.mjs": (
        "import cjs, { hello, kind } from 'cjs-pkg';\nimport greet, { kind as ekind } from 'esm-pkg';\n"
        "import thing from '@scope/thing';\nimport { via } from 'exp-pkg';\nimport { sub } from 'exp-pkg/sub';\n"
        "import { from } from 'mod-field';\nimport { extra } from 'file-pkg/extra.js';\n"
        "console.log(typeof cjs, hello('x'), kind, greet(), ekind, JSON.stringify(thing), via, sub, from, extra);\n")})
    r = run(["main.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "esm_node_modules")


def test_cjs_node_modules_resolution(run, node_modules):
    """CATCHES: CommonJS require() resolution that ignores main, the exports require condition, or scoped packages; or dynamic import() from CJS."""
    write_files(node_modules, {"sub/dir/main.js": (
        "const c = require('cjs-pkg'); console.log(c.hello('w'), c.kind);\n"
        "console.log(JSON.stringify(require('@scope/thing')));\n"
        "console.log(require('exp-pkg').via, require('mod-field').from);\n"
        "import('esm-pkg').then(m => console.log('dynamic', m.kind, m.default()));\n")})
    r = run(["sub/dir/main.js"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "cjs_node_modules")


def test_esm_missing_package(run, workdir):
    """CATCHES: a missing bare package reported with a different message from the ESM loader."""
    write_files(workdir, {"m.mjs": "import x from 'no-such-pkg';\n"})
    r = run(["m.mjs"])
    assert (r.returncode, r.stdout) == (1, b"")
    assert r.stderr.replace(str(workdir).encode(), b"<WORKDIR>") == (
        b"Uncaught TypeError: module not found: no-such-pkg (imported from <WORKDIR>/m.mjs)\n")


def test_cjs_require_json_and_directory(run, workdir):
    """CATCHES: CommonJS require() that cannot load .json files or a directory's index.js, or does not cache modules."""
    write_files(workdir, {
        "conf.json": '{"port": 8080, "tags": ["a", "b"]}',
        "lib/index.js": "let n = 0; exports.next = () => ++n;\n",
        "main.js": "const c = require('./conf.json'); console.log(c.port, c.tags.join('+'));\n"
                   "const a = require('./lib'), b = require('./lib/index.js');\n"
                   "a.next(); console.log(a === b, b.next(), require.cache !== undefined);\n"})
    assert _res(run(["main.js"])) == (0, b"8080 a+b\ntrue 2 true\n", b"")


def test_cjs_circular_require(run, workdir):
    """CATCHES: CommonJS loaders that loop forever or hide the partially-initialised exports during a require cycle."""
    write_files(workdir, {
        "a.js": "exports.done = false; const b = require('./b'); console.log('in a, b.done =', b.done); exports.done = true;\n",
        "b.js": "exports.done = false; const a = require('./a'); console.log('in b, a.done =', a.done); exports.done = true;\n",
        "main.js": "const a = require('./a'); const b = require('./b'); console.log('main', a.done, b.done);\n"})
    assert _res(run(["main.js"])) == (0, b"in b, a.done = false\nin a, b.done = true\nmain true true\n", b"")


def test_esm_module_graph_order_and_dedupe(run, workdir):
    """CATCHES: module graphs evaluated in the wrong (non post-order) sequence or a shared dependency evaluated twice."""
    write_files(workdir, {
        "shared.mjs": "console.log('shared'); export let count = 0; export function bump() { count++ }\n",
        "a.mjs": "import { bump } from './shared.mjs'; console.log('a'); bump();\n",
        "b.mjs": "import { bump, count } from './shared.mjs'; console.log('b'); bump(); export { count };\n",
        "main.mjs": "import './a.mjs'; import { count } from './b.mjs'; import * as s from './shared.mjs';\n"
                    "console.log('main', count, s.count, Object.keys(s).join(','));\n"})
    assert _res(run(["main.mjs"])) == (0, b"shared\na\nb\nmain 2 2 bump,count\n", b"")


def test_esm_dynamic_import_namespace(run, workdir):
    """CATCHES: dynamic import() from an ES module that does not resolve relative to the importer or returns a wrong namespace."""
    write_files(workdir, {
        "lib/util.mjs": "export const twice = (x) => x * 2; export default 'util-default';\n",
        "main.mjs": "const m = await import('./lib/util.mjs');\nconsole.log(m.twice(21), m.default, Object.keys(m).join(','));\n"
                    "try { await import('./nope.mjs') } catch (e) { console.log(e.name) }\n"})
    assert _res(run(["main.mjs"])) == (0, b"42 util-default default,twice\nTypeError\n", b"")
