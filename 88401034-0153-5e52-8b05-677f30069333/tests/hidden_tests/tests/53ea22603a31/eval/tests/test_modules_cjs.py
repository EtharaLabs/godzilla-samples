"""CommonJS as run by lumen-cli: module.exports vs exports, the module wrapper, require cache and
identity, circular requires, JSON and directory modules, node_modules/package.json resolution,
require.resolve, resolution errors and the node:module API (createRequire, _extensions, registerHooks)."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

# Replaces the (realpath'd) working directory with <cwd> in printed strings.
NORM = r'''
const __cwd = require('fs').realpathSync(process.cwd());
const norm = (s) => String(s).split(__cwd).join('<cwd>');
'''


def test_exports_vs_module_exports(run, workdir):
    """CATCHES: a wrapper where reassigning `exports` changes what require() returns, where replacing
    module.exports is ignored, or where `this` at module top level is not the initial exports object."""
    write_files(workdir, {
        "replace.js": "exports.ignored = 1;\nmodule.exports = function replaced() { return 'replaced fn'; };\n"
                      "module.exports.attached = 'prop';\n",
        "rebind.js": "exports = { lost: true };\nexports.alsoLost = 1;\nmodule.exports.kept = 'kept';\n",
        "both.js": "exports.a = 1;\nmodule.exports.b = 2;\nthis.c = 3;\n"
                   "module.exports.same = (exports === module.exports) && (this === exports);\n",
        "primitive.js": "module.exports = 42;\n",
        "nothing.js": "// exports nothing\n",
        "late.js": "setTimeout(() => { module.exports.late = 'set later'; }, 0);\nmodule.exports.early = 'now';\n",
    })
    check_script(run, workdir, G, "cjs_exports_forms", r'''
const r = require('./replace');
console.log(typeof r, r.name, r(), r.attached, r.ignored);
console.log(JSON.stringify(require('./rebind')));
console.log(JSON.stringify(require('./both')));
console.log(require('./primitive'), JSON.stringify(require('./nothing')), Object.getPrototypeOf(require('./nothing')) === Object.prototype);
const late = require('./late');
console.log(JSON.stringify(late));
setTimeout(() => console.log(JSON.stringify(late), JSON.stringify(require('./late'))), 5);
''')


def test_module_wrapper_and_main(run, workdir):
    """CATCHES: missing or misordered wrapper arguments (exports, require, module, __filename, __dirname),
    wrong __filename/__dirname for nested modules, require.main not being the entry module, or a
    required module seeing itself as main."""
    write_files(workdir, {"lib/nested/info.js": r'''
module.exports = {
  file: __filename, dir: __dirname, isMain: require.main === module,
  mainId: require.main.id, id: module.id, argsLen: arguments.length,
  argNames: [typeof arguments[0], typeof arguments[1], typeof arguments[2], typeof arguments[3], typeof arguments[4]],
  parentIsMain: module.parent === require.main,
};
'''})
    check_script(run, workdir, G, "cjs_wrapper_main", NORM + r'''
console.log(norm(__filename), norm(__dirname), require.main === module, module.id, arguments.length);
console.log(arguments[0] === exports, arguments[1] === require, arguments[2] === module, norm(arguments[3]), norm(arguments[4]));
const info = require('./lib/nested/info.js');
console.log(norm(info.file), norm(info.dir), info.isMain, info.mainId, norm(info.id), info.argsLen);
console.log(info.argNames.join(','), info.parentIsMain);
console.log(module.loaded, typeof module.children, module.parent, norm(module.filename));
setTimeout(() => console.log('loaded later:', module.loaded), 0);
''', filename="entry.js")


def test_circular_requires(run, workdir):
    """CATCHES: circular require() that deadlocks, re-executes a module, or hands the cycle closer
    anything but the partially-filled exports object of the module still loading."""
    write_files(workdir, {
        "a.js": "console.log('a starting');\nexports.done = false;\nexports.early = 'a-early';\n"
                "const b = require('./b.js');\nconsole.log('in a, b.done =', b.done);\n"
                "exports.done = true;\nconsole.log('a done');\n",
        "b.js": "console.log('b starting');\nconst a = require('./a.js');\n"
                "console.log('in b, a =', JSON.stringify(a));\nexports.done = true;\nconsole.log('b done');\n",
    })
    check_script(run, workdir, G, "cjs_circular", r'''
console.log('main starting');
const a = require('./a.js');
const b = require('./b.js');
console.log('in main, a.done =', a.done, 'b.done =', b.done, a === require('./a'));
''')


def test_require_cache_and_identity(run, workdir):
    """CATCHES: modules evaluated more than once, require.cache keyed by something other than the
    resolved absolute filename, module.children not tracking first loads, or deleting from the
    require.cache snapshot changing behaviour (the reference returns a fresh snapshot object each time,
    so deletion does not force a reload)."""
    write_files(workdir, {
        "counter.js": "console.log('counter evaluated');\nlet n = 0;\nmodule.exports = { next: () => ++n };\n",
        "sub/user.js": "module.exports = require('../counter.js');\n",
    })
    check_script(run, workdir, G, "cjs_cache", NORM + r'''
const c1 = require('./counter');
const c2 = require('./counter.js');
const c3 = require('./sub/user');
console.log(c1 === c2, c2 === c3, c1.next(), c3.next());
const keys = Object.keys(require.cache).map(norm).sort();
console.log(keys.join('\n'));
const entry = require.cache[require.resolve('./counter')];
console.log(entry.exports === c1, entry.loaded, norm(entry.id), require.cache === require.cache);
delete require.cache[require.resolve('./counter')];
console.log('after delete', require('./counter') === c1, c1.next());
console.log(module.children.map((m) => norm(m.filename)).join(','));
''')


def test_json_and_directory_modules(run, workdir):
    """CATCHES: JSON modules not parsed (or re-parsed per require so mutations vanish), wrong extension
    probing order (.js before .json), directory modules ignoring package.json "main" (including a main
    without extension or pointing at a directory) or index.js, and JSON syntax errors not surfacing."""
    write_files(workdir, {
        "config.json": '{"name": "cfg", "list": [1, "two", null], "nested": {"deep": true}}',
        "bad.json": '{"a": 1,}',
        "both.js": "module.exports = 'both.js wins';\n",
        "both.json": '"both.json loses"',
        "onlyjson.json": '["only", "json"]',
        "dirmod/index.js": "module.exports = 'dirmod/index.js';\n",
        "pkgmain/package.json": '{"main": "lib/start"}',
        "pkgmain/lib/start.js": "module.exports = 'pkgmain main without extension';\n",
        "pkgdir/package.json": '{"main": "./src"}',
        "pkgdir/src/index.js": "module.exports = 'main pointing at a directory';\n",
        "badmain/package.json": '{"main": "missing.js"}',
        "badmain/index.js": "module.exports = 'fell back to index.js';\n",
        "cjsext/thing.cjs": "module.exports = 'probed .cjs';\n",
    })
    check_script(run, workdir, G, "cjs_json_dirs", r'''
const cfg = require('./config.json');
cfg.mutated = 'yes';
console.log(JSON.stringify(require('./config')), require('./config.json') === cfg);
console.log(require('./both'), JSON.stringify(require('./onlyjson')));
console.log(require('./dirmod'), '|', require('./pkgmain'), '|', require('./pkgdir'), '|', require('./badmain'));
console.log(require('./cjsext/thing'));
try { require('./bad.json'); } catch (e) { console.log(e.name + ': ' + e.message); }
''')


def test_node_modules_resolution(run, workdir):
    """CATCHES: require() not walking node_modules up from the requiring file's directory, ignoring the
    "require" condition of package.json exports (or a string exports), not resolving scoped packages
    or literal subpath files, and pins that exports *subpaths* are not supported by require()."""
    write_files(workdir, {
        "node_modules/dual/package.json": '{"name": "dual", "main": "main-field.js", "exports": {".": '
                                          '{"import": "./esm.mjs", "require": "./req.js"}, "./feature": "./feat.js"}}',
        "node_modules/dual/req.js": "module.exports = 'require condition';\n",
        "node_modules/dual/main-field.js": "module.exports = 'main field';\n",
        "node_modules/dual/feat.js": "module.exports = 'feature subpath';\n",
        "node_modules/dual/esm.mjs": "export default 'esm';\n",
        "node_modules/strexp/package.json": '{"exports": "./lib/s.js", "main": "nope.js"}',
        "node_modules/strexp/lib/s.js": "module.exports = 'string exports';\n",
        "node_modules/@org/tool/package.json": '{"main": "./tool.js"}',
        "node_modules/@org/tool/tool.js": "module.exports = 'scoped tool';\n",
        "node_modules/@org/tool/extra/file.js": "module.exports = 'scoped subpath file';\n",
        "node_modules/single.js": "module.exports = 'node_modules/single.js file';\n",
        "app/node_modules/dual/package.json": '{"main": "near.js"}',
        "app/node_modules/dual/near.js": "module.exports = 'nearest node_modules wins';\n",
        "app/deep/er/use.js": "module.exports = [require('dual'), require('strexp'), require('@org/tool'), "
                              "require('@org/tool/extra/file'), require('single')];\n",
    })
    check_script(run, workdir, G, "cjs_node_modules", r'''
console.log(require('dual'), '|', require('strexp'), '|', require('@org/tool'));
console.log(require('./app/deep/er/use.js').join(' | '));
for (const s of ['dual/feature', 'dual/req.js', 'single']) {
  try { console.log(s, '->', require(s)); } catch (e) { console.log(s, '->', e.code, e.message); }
}
''')


def test_resolution_errors_and_require_resolve(run, workdir):
    """CATCHES: different MODULE_NOT_FOUND messages (relative specifiers mention the requiring directory,
    bare ones do not), require.resolve returning unresolved/relative paths or the wrong form for
    builtins, or builtins not resolvable with and without the node: prefix."""
    write_files(workdir, {"lib/a.js": "exports.ok = 1;\n", "lib/b.json": "{}"})
    check_script(run, workdir, G, "cjs_resolve_errors", NORM + r'''
console.log(norm(require.resolve('./lib/a')), norm(require.resolve('./lib/b')), norm(require.resolve('./lib/a.js')));
console.log(require.resolve('fs'), require.resolve('node:path'), require.resolve('node:fs/promises'));
console.log(require('node:fs') === require('fs'), require('fs').promises === require('fs/promises'));
for (const s of ['./nope', '../outside/x', 'no-such-pkg', 'node:no-such-builtin', '', 'lib/a']) {
  try { require(s); console.log('loaded', s); }
  catch (e) { console.log(JSON.stringify(s), e.name, e.code, norm(e.message)); }
}
try { require.resolve('./missing.js'); } catch (e) { console.log('resolve:', e.code, norm(e.message)); }
try { require(); } catch (e) { console.log('no arg:', e.code, e.message); }
''')


def test_failing_module_and_shebang(run, workdir):
    """CATCHES: an exception inside a required module not propagating to the caller, the failed module
    being re-executed on the next require (the reference keeps its partial exports cached), or a
    leading #! line in a required file being a syntax error."""
    write_files(workdir, {
        "throws.js": "console.log('throws.js runs');\nexports.partial = 'set before throw';\n"
                     "throw new RangeError('module failed');\n",
        "tool.js": "#!/usr/bin/env lumen\nmodule.exports = 'shebang stripped';\n",
        "syntax.js": "module.exports = ;\n",
    })
    check_script(run, workdir, G, "cjs_failing_module", r'''
try { require('./throws'); } catch (e) { console.log('first:', e.name + ': ' + e.message); }
try { console.log('second:', JSON.stringify(require('./throws'))); } catch (e) { console.log('second threw', e.message); }
console.log(require('./tool'));
try { require('./syntax'); } catch (e) { console.log(e.name + ': ' + e.message); }
''')


def test_node_module_api(run, workdir):
    """CATCHES: a node:module that is not the Module constructor itself, a wrong builtinModules/isBuiltin,
    wrapper/wrap text differing from Node's, createRequire not resolving relative to the given file
    (path or file: URL), or Module._extensions not being consulted for unknown extensions."""
    write_files(workdir, {
        "sub/inner.js": "exports.where = 'sub/inner.js';\n",
        "note.txt": "hello text\n",
    })
    check_script(run, workdir, G, "cjs_module_api", r'''
const Module = require('module');
console.log(Module === require('node:module'), Module.Module === Module, typeof Module);
console.log(Module.builtinModules.includes('fs'), Module.builtinModules.includes('node:fs'), Module.builtinModules.includes('module'));
console.log(['fs', 'node:fs', 'fs/promises', 'node:path/posix', 'nope', 'node:nope', 42].map((s) => Module.isBuiltin(s)).join(','));
console.log(JSON.stringify(Module.wrapper));
console.log(JSON.stringify(Module.wrap('return 1;')), Object.keys(Module).includes('wrap'));
const r1 = Module.createRequire(__dirname + '/sub/anything.js');
const r2 = Module.createRequire('file://' + __dirname + '/sub/');
console.log(r1('./inner').where, r1('./inner') === r2('./inner'), r1('./inner') === require('./sub/inner'));
Module._extensions['.txt'] = (module, filename) => {
  module.exports = require('fs').readFileSync(filename, 'utf8').trim().toUpperCase();
};
console.log(require('./note.txt'), typeof Module._extensions['.js'], Object.keys(Module._extensions).sort().join(','));
console.log(JSON.stringify(Module._nodeModulePaths('/a/node_modules/b/c')));
console.log(Module.findPackageJSON === undefined ? 'none' : typeof Module.findPackageJSON);
''')


def test_register_hooks(run, workdir):
    """CATCHES: module.registerHooks resolve/load chains not running (or running in the wrong order),
    nextResolve/nextLoad not reaching the default steps, deregister() not removing the hooks, and the
    exact TypeErrors for invalid hooks or a hook that neither calls next nor short-circuits."""
    write_files(workdir, {
        "greet.src": "raw greeting\n",
        "plain.js": "exports.v = 'plain';\n",
    })
    check_script(run, workdir, G, "cjs_register_hooks", r'''
const Module = require('module');
const seen = [];
const h = Module.registerHooks({
  resolve(spec, ctx, next) {
    seen.push('resolve ' + spec + ' ' + ctx.conditions.join('/'));
    if (spec === 'virtual:greet') return { url: 'file://' + __dirname + '/greet.src', shortCircuit: true };
    return next(spec, ctx);
  },
  load(url, ctx, next) {
    seen.push('load ' + url.slice(url.lastIndexOf('/') + 1) + ' ' + ctx.format);
    const r = next(url, ctx);
    if (url.endsWith('.src')) {
      return { format: 'commonjs', source: 'module.exports = ' + JSON.stringify(String(r.source).trim() + '!') + ';', shortCircuit: true };
    }
    return r;
  },
});
console.log(require('virtual:greet'), require('./plain').v, require('fs') === require('node:fs'));
h.deregister();
console.log(seen.join('\n'));
try { require('virtual:greet'); } catch (e) { console.log('after deregister:', e.code, e.message); }
for (const bad of [{ resolve: 5 }, null]) {
  try { Module.registerHooks(bad); } catch (e) { console.log(e.name, e.code, e.message); }
}
const noNext = Module.registerHooks({ resolve: () => ({ url: 'file:///x' }) });
try { require('./zzz'); } catch (e) { console.log(e.name, e.code, e.message); }
noNext.deregister();
const notObj = Module.registerHooks({ resolve: () => 'str' });
try { require('./zzz'); } catch (e) { console.log(e.name, e.code, e.message); }
notObj.deregister();
''')
