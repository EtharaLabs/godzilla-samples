"""ES-module resolution details for script entries: package.json fields, node_modules walks, CommonJS export detection."""

from conftest import golden, write_files


def _res(r):
    return r.returncode, r.stdout, r.stderr


def test_attribute_imports_relative_parent_and_package(run, workdir):
    """CATCHES: attribute imports (json/text) that only resolve './' specifiers, not '../' paths or bare package files."""
    write_files(workdir, {
        "shared/msg.txt": "from parent dir\n",
        "node_modules/cfg-pkg/data.json": '{"answer": 42}',
        "node_modules/cfg-pkg/package.json": '{"name": "cfg-pkg"}',
        "app/main.mjs": "import t from '../shared/msg.txt' with { type: 'text' };\n"
                        "import cfg from 'cfg-pkg/data.json' with { type: 'json' };\n"
                        "console.log(JSON.stringify(t), cfg.answer);\n"})
    assert _res(run(["app/main.mjs"])) == (0, b'"from parent dir\\n" 42\n', b"")


def test_json_import_special_characters(run, workdir):
    """CATCHES: JSON modules whose text is embedded unsafely (backslashes, CR, tabs, U+2028/2029 must survive exactly)."""
    write_files(workdir, {
        "d.json": '{\r\n\t"path": "C:\\\\dir\\\\file",\r\n\t"ls": "a\u2028b\u2029c",\r\n\t"q": "say \\"hi\\""\r\n}',
        "m.mjs": "import d from './d.json';\nconsole.log(d.path, d.path.length, JSON.stringify(d.ls), d.q);\n"})
    assert _res(run(["m.mjs"])) == (0, b'C:\\dir\\file 11 "a\xe2\x80\xa8b\xe2\x80\xa9c" say "hi"\n', b"")


def test_bytes_import_of_binary_file(run, workdir):
    """CATCHES: bytes imports that lossily decode non-UTF-8 files instead of returning the exact bytes."""
    write_files(workdir, {"blob.bin": bytes([0, 255, 128, 10, 200, 65]),
                          "m.mjs": "import b from './blob.bin' with { type: 'bytes' };\nconsole.log(b.length, Array.from(b).join(','));\n"})
    assert _res(run(["m.mjs"])) == (0, b"6 0,255,128,10,200,65\n", b"")


def test_directory_main_fallbacks(run, workdir):
    """CATCHES: directory imports that do not try main as a directory (main/index) or fall back to index.js when main is missing."""
    write_files(workdir, {
        "a/package.json": '{"main": "lib"}', "a/lib/index.js": "exports.v = 'a: main dir index';\n",
        "b/package.json": '{"main": "missing.js"}', "b/index.js": "exports.v = 'b: fallback index';\n",
        "c/package.json": '{"main": "lib\\/entry"}', "c/lib/entry.mjs": "export const v = 'c: escaped main + ext probe';\n",
        "m.mjs": "import { v as a } from './a';\nimport { v as b } from './b';\nimport { v as c } from './c';\nconsole.log(a);\nconsole.log(b);\nconsole.log(c);\n"})
    assert _res(run(["m.mjs"])) == (0, b"a: main dir index\nb: fallback index\nc: escaped main + ext probe\n", b"")


def test_nested_package_resolves_hoisted_dependency(run, workdir):
    """CATCHES: node_modules walks that look in node_modules/node_modules or stop at the importing package's directory."""
    write_files(workdir, {
        "node_modules/outer/package.json": '{"name": "outer", "type": "module", "main": "index.js"}',
        "node_modules/outer/index.js": "import { dep } from 'hoisted';\nexport const outer = 'outer+' + dep;\n",
        "node_modules/hoisted/package.json": '{"name": "hoisted", "exports": "./main.mjs"}',
        "node_modules/hoisted/main.mjs": "export const dep = 'hoisted via exports string';\n",
        "m.mjs": "import { outer } from 'outer';\nconsole.log(outer);\n"})
    assert _res(run(["m.mjs"])) == (0, b"outer+hoisted via exports string\n", b"")


def test_scoped_package_subpath_exports(run, workdir):
    """CATCHES: subpath exports that ignore scoped package names or the bare-string form of a subpath entry."""
    write_files(workdir, {
        "node_modules/@sc/kit/package.json": '{"name": "@sc/kit", "exports": {".": {"import": "./root.mjs"}, "./feature": "./dist/feature.mjs",'
                                            ' "./obj": {"default": "./dist/obj"}}}',
        "node_modules/@sc/kit/root.mjs": "export const root = 'kit root';\n",
        "node_modules/@sc/kit/dist/feature.mjs": "export const feature = 'kit feature';\n",
        "node_modules/@sc/kit/dist/obj/index.js": "export const obj = 'kit obj index (as ESM via exports)';\n",
        "m.mjs": "import { root } from '@sc/kit';\nimport { feature } from '@sc/kit/feature';\nimport { obj } from '@sc/kit/obj';\n"
                 "console.log(root); console.log(feature); console.log(obj);\n"})
    assert _res(run(["m.mjs"])) == (0, b"kit root\nkit feature\nkit obj index (as ESM via exports)\n", b"")


def test_unresolvable_subpath_export(run, workdir):
    """CATCHES: an exports entry pointing at a missing file being reported differently from any other missing module."""
    write_files(workdir, {
        "node_modules/half/package.json": '{"name": "half", "exports": {"./gone": "./not-there.mjs"}}',
        "node_modules/half/index.js": "exports.x = 1;\n",
        "m.mjs": "import x from 'half/gone';\n"})
    r = run(["m.mjs"])
    assert (r.returncode, r.stdout) == (1, b"")
    assert r.stderr.replace(str(workdir).encode(), b"<WORKDIR>") == (
        b"Uncaught TypeError: module not found: half/gone (imported from <WORKDIR>/m.mjs)\n")


def test_path_normalisation_in_specifiers(run, workdir):
    """CATCHES: specifiers with '.' and '..' segments resolving to different (duplicate) module instances."""
    write_files(workdir, {
        "lib/counter.mjs": "console.log('counter evaluated'); export let n = 0; export const inc = () => ++n;\n",
        "lib/sub/user.mjs": "import { inc } from '../counter.mjs'; inc(); export { inc };\n",
        "m.mjs": "import { inc } from './lib/./sub/../counter.mjs';\nimport './lib/sub/user.mjs';\nimport * as c from './lib//counter.mjs';\n"
                 "inc(); console.log(c.n, c.inc === inc);\n"})
    assert _res(run(["m.mjs"])) == (0, b"counter evaluated\n2 true\n", b"")


def test_cjs_reexport_chains(run, workdir):
    """CATCHES: CommonJS named-export detection that does not follow require() re-export chains (bounded depth) or Object.assign re-exports."""
    write_files(workdir, {
        "chain/l0.js": "module.exports = require('./l1');\n",
        "chain/l1.js": "module.exports=require('./l2.js');\n",
        "chain/l2.js": "module.exports = require('./l3');\n",
        "chain/l3.js": "module.exports = require('./l4');\n",
        "chain/l4.js": "module.exports = require('./l5');\n",
        "chain/l5.js": "exports.tooDeep = 'deep';\n",
        "assign.js": "Object.assign(module.exports, require('./parts/a'));\nObject.assign(exports, require('./parts'));\n"
                     "const cfg = require('./parts/c.json'); exports.j = cfg.j;\n",
        "dyn.js": "const name = './parts/a';\nmodule.exports = require(name);\n",
        "parts/a.cjs": "exports.fromA = 'A';\n",
        "parts/index.js": "exports.fromIndex = 'I';\n",
        "parts/c.json": '{"j": 1}',
        "m.mjs": "import * as chain from './chain/l0.js';\nimport * as asg from './assign.js';\nimport * as dyn from './dyn.js';\n"
                 "console.log(Object.keys(chain).join(','), chain.tooDeep, chain.default.tooDeep);\n"
                 "console.log(Object.keys(asg).join(','), asg.fromA, asg.fromIndex, asg.j);\n"
                 "console.log(Object.keys(dyn).join(','), dyn.default.fromA);\n"})
    r = run(["m.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "cjs_reexport_chains")


def test_cjs_export_name_heuristics(run, workdir):
    """CATCHES: CommonJS export scanning that accepts reserved words/invalid identifiers, misses __export helpers, or misreads string keys."""
    write_files(workdir, {
        "lib.js": "\n".join([
            "Object.defineProperty(exports, '__esModule', { value: true });",
            "Object.defineProperty(exports, 'viaDefine', { enumerable: true, get: () => 'define' });",
            "exports.notThis = {}; const other = {};",
            "Object.defineProperty(exports.notThis, 'x', { value: 1 });",
            "Object.defineProperty(other, 'nope', { value: 1 });",
            "__export(exports, { helperA: () => helperA, 'helperB': () => 2 });",
            "function __export(t, m) { for (const k in m) Object.defineProperty(t, k, { enumerable: true, get: m[k] }) }",
            "function helperA() { return 'A' }",
            "exports.default = 'dflt';",
            "exports.class = 'reserved';",
            "exports.ok$_1 = 'ident';",
            "exports.cmp == 1;",
            "exports.eq === 2;",
            "module.exports.extra = 'extra';",
            "0 && (module.exports = { hinted, 'str\\'key': 1, '1bad': 2, 'a-b': 3, nested: { inner: 1 }, [computed]: 4 });",
        ]) + "\n",
        "m.mjs": "import * as lib from './lib.js';\nimport d from './lib.js';\n"
                 "console.log(Object.keys(lib).join(','));\nconsole.log(lib.viaDefine, lib.helperA(), lib.ok$_1, lib.extra, typeof d, d.default);\n"})
    r = run(["m.mjs"])
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "cjs_export_heuristics")


def test_cjs_bridge_in_odd_directory_names(run, workdir):
    """CATCHES: the CommonJS bridge embedding the file path unescaped (quotes, backslashes or newlines in directory names)."""
    odd = 'we"ird\\dir\nline'
    write_files(workdir, {f"{odd}/lib.cjs": "exports.value = 'escaped path ok';\n",
                          "m.mjs": "import { value } from './we\"ird\\\\dir\\nline/lib.cjs';\nconsole.log(value);\n"})
    assert _res(run(["m.mjs"])) == (0, b"escaped path ok\n", b"")


def test_bare_cjs_reexport_not_followed(run, workdir):
    """CATCHES: export detection that follows bare-package re-exports (only relative re-exports are followed)."""
    write_files(workdir, {
        "node_modules/inner-pkg/index.js": "exports.innerName = 'inner';\n",
        "wrap.js": "module.exports = require('inner-pkg');\n",
        "m.mjs": "import * as w from './wrap.js';\nconsole.log(Object.keys(w).join(','), w.default.innerName);\n"})
    assert _res(run(["m.mjs"])) == (0, b"default inner\n", b"")
