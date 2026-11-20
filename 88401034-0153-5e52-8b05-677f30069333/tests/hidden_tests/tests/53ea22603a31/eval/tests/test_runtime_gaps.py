"""Second-wave runtime gaps: process metrics/identity/execve, ESM linking corners (re-exported imports,
star-export identity, ambiguous indirect exports, top-level-await detection inside nested statements,
typed-import escaping, scoped packages, CommonJS export-name scanning, import defer vs dynamic import),
uncaught-error rendering for module entries, the JSX transformer (Bun.Transpiler and .jsx entries),
web/node workers (timers, close(), onerror, ref/unref) and the piped REPL."""

import pytest

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)


# ---- process -----------------------------------------------------------------------------------

def test_process_resource_metrics_shape(run, workdir):
    """CATCHES: missing or misnamed process.memoryUsage()/memoryUsage.rss()/cpuUsage()/cpuUsage(prev)/
    resourceUsage()/availableMemory()/constrainedMemory()/uptime() members (Node's exact key names and
    key order), non-numeric or negative counters, a zero RSS, hrtime() not being an integer
    [seconds, nanoseconds] pair (also when diffed against a previous reading whose nanoseconds exceed the
    current ones) or hrtime.bigint() not returning a BigInt. Only shapes are asserted, never values."""
    check_script(run, workdir, G, "process_resource_metrics_shape", r'''
const shape = (o) => Object.keys(o).map((k) => k + ':' + typeof o[k]).join(',');
const mu = process.memoryUsage();
console.log('memoryUsage', shape(mu));
console.log('rss', mu.rss > 0, Number.isInteger(mu.rss), typeof process.memoryUsage.rss(), process.memoryUsage.rss() > 0);
const cu = process.cpuUsage();
console.log('cpuUsage', shape(cu), Number.isInteger(cu.user) && cu.user >= 0, Number.isInteger(cu.system) && cu.system >= 0);
const diff = process.cpuUsage(cu);
console.log('cpuUsage(prev)', shape(diff), diff.user >= 0, diff.system >= 0);
const ru = process.resourceUsage();
console.log('resourceUsage', shape(ru));
console.log('resourceUsage ints', Object.values(ru).every((v) => Number.isInteger(v) && v >= 0), ru.maxRSS > 0);
console.log('memory limits', typeof process.availableMemory(), process.availableMemory() >= 0,
            typeof process.constrainedMemory(), process.constrainedMemory() >= 0);
const up = process.uptime();
console.log('uptime', typeof up, up >= 0, up < 600);
const hr = process.hrtime();
console.log('hrtime', Array.isArray(hr), hr.length, hr.every(Number.isInteger), hr[1] < 1e9);
const d = process.hrtime(hr);
console.log('hrtime(prev)', d.length, d[0] >= 0, d[1] >= 0 && d[1] < 1e9);
const borrow = process.hrtime([0, 999999999]);
console.log('hrtime borrow', borrow.length, borrow[1] >= 0 && borrow[1] < 1e9, borrow.every(Number.isInteger));
const big = process.hrtime.bigint();
console.log('bigint', typeof big, big > 0n, process.hrtime.bigint() >= big);
''')


def test_process_execve_replaces_process(run, workdir):
    """CATCHES: process.execve not validating file/args/env (exact TypeError texts, NUL bytes in args or
    env values), a failing execve not throwing 'execve failed: <OS error>' (ENOENT for a missing program,
    EACCES for a directory), or a successful execve not replacing the process image: output written
    before the call must be flushed, argv must be passed verbatim (argv[0] included), env values must be
    stringified with undefined entries dropped, nothing after the call may run, and the exit status must
    be the new program's."""
    check_script(run, workdir, G, "process_execve", r'''
const tryIt = (label, f) => { try { console.log(label, String(f())); } catch (e) { console.log(label, e.name + ': ' + e.message); } };
tryIt('file-type', () => process.execve(42, [], {}));
tryIt('args-type', () => process.execve('/bin/sh', 'x', {}));
tryIt('env-null', () => process.execve('/bin/sh', [], null));
tryIt('env-array', () => process.execve('/bin/sh', [], []));
tryIt('nul-arg', () => process.execve('/bin/sh', ['a\0b'], {}));
tryIt('nul-env', () => process.execve('/bin/sh', [], { K: 'v\0' }));
tryIt('missing', () => process.execve('./no-such-program', ['x'], {}));
tryIt('directory', () => process.execve('.', ['x'], {}));
console.log('before exec');
process.stdout.write('partial line | ');
process.execve('/bin/sh', ['sh', '-c', 'echo "dollar0=$0 dollar1=$1"; echo "A=$A B=${B-unset} C=$C N=$N"; exit 3', 'first', 'second arg'],
               { A: 1, B: undefined, C: 'x y', N: null });
console.log('never printed');
''', rc=3)


def test_process_identity_and_signal_errors(run, workdir):
    """CATCHES: setuid/seteuid/setgid/setegid rejecting the process's own ids (always permitted),
    getgroups not returning an integer array, setgroups/initgroups argument validation (non-array,
    non-numeric group, NUL byte in the user name) with the reference's exact TypeError texts, the
    all-ones id 4294967295 not failing with '<call> failed: Invalid argument (os error 22)',
    process.kill(pid, 0) not returning true for the current process, kill of a nonexistent pid (numeric
    or named signal) not throwing 'kill <pid> failed (errno set)', or ppid not being a positive integer."""
    check_script(run, workdir, G, "process_identity", r'''
const tryIt = (label, f) => { try { const v = f(); console.log(label, v === undefined ? 'undefined' : JSON.stringify(v)); } catch (e) { console.log(label, e.name + ': ' + e.message); } };
const uid = process.getuid(), gid = process.getgid();
console.log('ids', typeof uid, Number.isInteger(uid), typeof process.geteuid(), typeof gid, typeof process.getegid());
tryIt('setuid-own', () => process.setuid(uid));
tryIt('seteuid-own', () => process.seteuid(process.geteuid()));
tryIt('setgid-own', () => process.setgid(gid));
tryIt('setegid-own', () => process.setegid(process.getegid()));
const groups = process.getgroups();
console.log('getgroups', Array.isArray(groups), groups.every(Number.isInteger));
tryIt('setgroups-string', () => process.setgroups('0'));
tryIt('setgroups-name', () => process.setgroups(['staff']));
tryIt('initgroups-nul', () => process.initgroups('a\0b', 0));
console.log('ppid', typeof process.ppid, Number.isInteger(process.ppid) && process.ppid > 0, process.ppid !== process.pid);
tryIt('kill-self-0', () => process.kill(process.pid, 0));
tryIt('kill-missing', () => process.kill(2147483646, 0));
tryIt('kill-missing-named', () => process.kill(2147483646, 'SIGUSR2'));
tryIt('kill-missing-default', () => process.kill(2147483646));
for (const f of ['setuid', 'seteuid', 'setgid', 'setegid']) tryIt(f + '-invalid-id', () => process[f](4294967295));
''')


def test_process_cwd_of_deleted_directory_and_chdir_errors(run, workdir):
    """CATCHES: process.cwd() not throwing 'cwd unavailable: <OS error>' once the working directory has
    been removed (instead of returning a stale cached path), chdir back to an absolute path not
    recovering, or chdir failures not using the reference's 'ENOENT: chdir '<dir>': <OS error>' text
    (also for a regular file, where the OS error is ENOTDIR but the prefix stays ENOENT)."""
    check_script(run, workdir, G, "process_cwd_deleted", r'''
const fs = require('fs');
const tryIt = (label, f) => { try { const v = f(); console.log(label, v === undefined ? 'undefined' : JSON.stringify(v)); } catch (e) { console.log(label, e.name + ': ' + e.message); } };
const base = process.cwd();
fs.mkdirSync('sub');
process.chdir('sub');
console.log('in sub', process.cwd() === base + '/sub');
fs.rmdirSync('../sub');
tryIt('cwd-deleted', () => process.cwd());
tryIt('cwd-deleted-again', () => process.cwd());
tryIt('chdir-back', () => process.chdir(base));
tryIt('cwd-restored', () => process.cwd() === base);
tryIt('chdir-missing', () => process.chdir('no/such/dir'));
fs.writeFileSync('f.txt', '');
tryIt('chdir-file', () => process.chdir('f.txt'));
console.log('sub exists', fs.existsSync('sub'));
''')


# ---- ESM linking -------------------------------------------------------------------------------

ESM_NORM = r'''
const norm = (s) => s.split(process.cwd()).join('<cwd>');
const errStr = (e) => e.name + ': ' + norm(e.message);
'''


def test_esm_reexported_imports_and_star_identity(run, workdir):
    """CATCHES: `import {x}; export {x}` re-exports not resolving to the origin binding (must stay live),
    a re-exported `import * as ns` not being the dependency's own namespace object, a re-exported
    `import defer * as d` not staying the shared 'Deferred Module' (and not evaluating lazily), the same
    binding reached through two `export *` paths being treated as a conflict (it must be kept), an
    ambiguous name nested one star deeper, an ambiguous or missing `export {x} from` being accepted,
    `export *` providing `default`, `export *` cycles looping or losing names, a name provided as a
    local binding by one star and as a namespace by another not being treated as ambiguous, and a
    namespace read of a not-yet-initialized binding inside an import cycle not throwing the TDZ
    ReferenceError."""
    write_files(workdir, {
        "base.mjs": "export let v = 1;\nexport const bump = () => { v++; };\n",
        "lazy.mjs": "console.log('lazy evaluated');\nexport const lz = 'lazy value';\n",
        "relay.mjs": "import { v as iv } from './base.mjs';\nimport * as ns from './base.mjs';\n"
                     "import defer * as dns from './lazy.mjs';\nexport { iv, ns, dns };\n",
        "z.mjs": "export const zv = 'z';\n",
        "x1.mjs": "export * as zns from './z.mjs';\nimport defer * as zd from './lazy.mjs';\nexport { zd };\n"
                  "export { zv as same } from './z.mjs';\n",
        "x2.mjs": "export * as zns from './z.mjs';\nimport defer * as zd from './lazy.mjs';\nexport { zd };\n"
                  "import { zv } from './z.mjs';\nexport { zv as same };\n",
        "both.mjs": "export * from './x1.mjs';\nexport * from './x2.mjs';\n",
        "d1.mjs": "export const dup = 'd1';\n",
        "d2.mjs": "export const dup = 'd2';\n",
        "amb.mjs": "export * from './d1.mjs';\nexport * from './d2.mjs';\n",
        "outer.mjs": "export * from './amb.mjs';\nexport const fine = 'fine';\n",
        "indirect.mjs": "export { dup } from './amb.mjs';\n",
        "staronly.mjs": "export * from './base.mjs';\n",
        "cyca.mjs": "export * from './cycb.mjs';\nexport const a = 'A';\n",
        "cycb.mjs": "export * from './cyca.mjs';\nexport const b = 'B';\n",
        "use_outer.mjs": "import { dup } from './outer.mjs';\nconsole.log('unreachable');\n",
        "use_default.mjs": "import d from './staronly.mjs';\nconsole.log('unreachable');\n",
        "use_cycle.mjs": "import { zzz } from './cyca.mjs';\nconsole.log('unreachable');\n",
        "k1.mjs": "export const shape = 'local binding';\nexport const only1 = 1;\n",
        "k2.mjs": "export * as shape from './k1.mjs';\nexport const only2 = 2;\n",
        "kinds.mjs": "export * from './k1.mjs';\nexport * from './k2.mjs';\n",
        "use_kinds.mjs": "import { shape } from './kinds.mjs';\nconsole.log('unreachable');\n",
        "cy1.mjs": "import * as two from './cy2.mjs';\nexport const fromOne = 'one';\nexport function readTwo() { return two.late; }\n",
        "cy2.mjs": "import * as one from './cy1.mjs';\nlet early;\ntry { early = one.fromOne; } catch (e) { early = e.name + ': ' + e.message; }\n"
                   "console.log('cy2 sees one.fromOne ->', early);\nexport const late = 'two late';\n",
    })
    check_script(run, workdir, G, "esm_reexported_imports", ESM_NORM + r'''
import { iv, ns, dns } from './relay.mjs';
import * as R from './relay.mjs';
import * as base from './base.mjs';
console.log('relay keys', Object.keys(R).join(','));
console.log('ns is base', ns === base, R.ns === base, 'iv', iv);
base.bump();
console.log('iv live', iv, R.iv);
console.log('dns', dns[Symbol.toStringTag], R.dns === dns);
console.log('dns read', dns.lz);
import * as B from './both.mjs';
import { zns, zd, same } from './both.mjs';
import * as Z from './z.mjs';
console.log('both keys', Object.keys(B).join(','), zns === Z, B.zns === Z, same, zd === B.zd, zd[Symbol.toStringTag]);
import * as O from './outer.mjs';
console.log('outer keys', Object.keys(O).join(','));
import * as A from './amb.mjs';
console.log('amb keys', JSON.stringify(Object.keys(A)));
import * as K from './kinds.mjs';
console.log('mixed-kind star conflict keys', Object.keys(K).join(','));
import { fromOne, readTwo } from './cy1.mjs';
console.log('cycle through namespaces', fromOne, readTwo());
for (const spec of ['./indirect.mjs', './use_outer.mjs', './use_default.mjs', './use_cycle.mjs', './use_kinds.mjs']) {
  try { await import(spec); console.log(spec, 'loaded'); } catch (e) { console.log(spec, errStr(e)); }
}
import * as C from './cyca.mjs';
console.log('cycle keys', Object.keys(C).join(','), C.a, C.b);
''', filename="main.mjs")


def test_esm_tla_detection_in_nested_statements(run, workdir):
    """CATCHES: a module whose only top-level `await` sits inside a switch discriminant, a labeled block,
    a while/do-while body or condition, a for-loop init expression, a tagged-template tag or an array
    literal with holes not being treated as an async module: every sibling must start before any of
    them resumes, the importer must wait for all of them, and the awaited values must be correct (also
    for an await in a `case` test or a `case` body)."""
    files = {
        "t_switch.mjs": "console.log('switch start');\nswitch (await Promise.resolve(2)) { case 2: console.log('switch case 2'); }\nexport const k = 'switch';\n",
        "t_label.mjs": "console.log('label start');\nouter: { await null; console.log('label resumed'); break outer; }\nexport const k = 'label';\n",
        "t_while.mjs": "console.log('while start');\nlet i = 0; while (i < 1) { await null; i++; }\nconsole.log('while resumed', i);\nexport const k = 'while';\n",
        "t_dowhile.mjs": "console.log('dowhile start');\nlet i = 0; do { i++; } while (await Promise.resolve(i < 2));\nconsole.log('dowhile resumed', i);\nexport const k = 'dowhile';\n",
        "t_forexpr.mjs": "console.log('forexpr start');\nlet j; for (j = await Promise.resolve(5); j < 6; j++) {}\nconsole.log('forexpr resumed', j);\nexport const k = 'forexpr';\n",
        "t_tagged.mjs": "console.log('tagged start');\nconst r = (await Promise.resolve((s) => s.raw.join('|')))`a${1}b`;\nconsole.log('tagged resumed', r);\nexport const k = 'tagged';\n",
        "t_hole.mjs": "console.log('hole start');\nconst arr = [, await Promise.resolve('x'), , 'y'];\nconsole.log('hole resumed', arr.length, 1 in arr, 0 in arr, arr[1]);\nexport const k = 'hole';\n",
        "t_case.mjs": "console.log('case start');\nswitch (3) { case 1: break; case await Promise.resolve(3): console.log('case matched'); }\nexport const k = 'case';\n",
        "t_casebody.mjs": "console.log('casebody start');\nswitch (1) { case 1: await null; console.log('casebody resumed'); }\nexport const k = 'casebody';\n",
        "t_sync.mjs": "console.log('sync module runs');\nexport const k = 'sync';\n",
    }
    write_files(workdir, files)
    imports = "".join(f"import {{ k as k{i} }} from './{name}';\n" for i, name in enumerate(files))
    check_script(run, workdir, G, "esm_tla_nested", imports +
                 "console.log('main', " + ", ".join(f"k{i}" for i in range(len(files))) + ");\n",
                 filename="main.mjs")


def test_esm_typed_imports_escaping_and_bytes(run, workdir):
    """CATCHES: `type: 'text'` imports mangling quotes, backslashes, CR, U+2028/U+2029 or control
    characters (they must round-trip exactly), JSON imports (with attributes, and an attribute-less
    CRLF/tab-indented file holding a raw U+2028) mis-decoding escapes, and the byte view of
    `type: 'bytes'` imports. Pins a reference quirk: a valid UTF-8 file whose characters all fit in
    Latin-1 ('café') is imported as one byte per character (233), while a file with a character above
    U+00FF ('€') yields its UTF-8 bytes; static and dynamic bytes imports agree."""
    write_files(workdir, {
        "esc.txt": 'say "hi"\\path\r\nline\u2028sep\u2029para\x01\x1f\tend'.encode(),
        "esc.json": b'{"s": "a\\\\b\\u2028c", "n": "x\\ty", "q": "\\"quoted\\""}',
        "latin.txt": "café".encode(),
        "euro.txt": "€ uro".encode(),
        "crlf.json": '{\r\n\t"path": "C:\\\\dir",\r\n\t"sep": "a\u2028b",\r\n\t"quote": "\\"q\\""\r\n}\r\n'.encode(),
    })
    check_script(run, workdir, G, "esm_typed_imports_escaping", r'''
import esc from './esc.txt' with { type: 'text' };
console.log(JSON.stringify(esc), esc.length);
import j from './esc.json' with { type: 'json' };
console.log(JSON.stringify(j), j.s.length);
import lb from './latin.txt' with { type: 'bytes' };
import eb from './euro.txt' with { type: 'bytes' };
import et from './euro.txt' with { type: 'text' };
import lt from './latin.txt' with { type: 'text' };
console.log(lb.constructor.name, Array.from(lb).join(','), '|', Array.from(eb).join(','), '|', et, lt);
const d = await import('./latin.txt', { with: { type: 'bytes' } });
console.log(Array.from(d.default).join(','), d.default === lb);
import plain from './crlf.json';
console.log(JSON.stringify(plain), plain.sep.length);
''', filename="main.mjs")


def test_esm_package_resolution_scoped_and_fallbacks(run, workdir):
    """CATCHES: scoped `@scope/name` packages not resolving their root or an `exports` subpath mapped by a
    plain string, a package whose `main` points at a missing file not falling back to index.js, a
    package inside node_modules not finding a sibling package (the walk must skip node_modules
    directories themselves), JSON string escapes (`\\/`) and `./` segments in package.json `main` or
    in an `exports` condition object not being decoded/normalized, or missing subpaths/packages not
    failing with the reference's
    'module not found: <spec> (imported from <url>)' TypeError."""
    write_files(workdir, {
        "node_modules/@acme/kit/package.json": '{ "name": "@acme/kit", "type": "module", "main": "./lib/main.js",\n'
            '  "exports": { ".": "./lib/main.js", "./feature": "./lib/feat.js", "./missing": "./lib/nope.js" } }\n',
        "node_modules/@acme/kit/lib/main.js": "export const main = 'kit main';\n",
        "node_modules/@acme/kit/lib/feat.js": "export const feat = 'kit feature via exports string';\n",
        "node_modules/@acme/kit/feature/README": "a directory with the subpath's name but no entry\n",
        "node_modules/brokenmain/package.json": '{ "name": "brokenmain", "main": "./dist/gone.js" }\n',
        "node_modules/brokenmain/index.js": "module.exports = { from: 'brokenmain index fallback' };\n",
        "node_modules/sib/package.json": '{ "name": "sib", "type": "module", "main": "index.js" }\n',
        "node_modules/sib/index.js": "import { h } from 'helper';\nexport const viaSibling = 'sib sees ' + h;\n",
        "node_modules/helper/package.json": '{ "name": "helper", "type": "module", "main": "./h.js" }\n',
        "node_modules/helper/h.js": "export const h = 'helper';\n",
        "node_modules/esc/package.json": '{ "name": "esc", "main": ".\\/lib\\/.\\/entry.js" }',
        "node_modules/esc/lib/entry.js": "module.exports = 'esc entry via escaped main';\n",
        "node_modules/escx/package.json": '{ "name": "escx", "type": "module", "exports": { ".": "./dist/main.js", '
                                          '"./sub": { "import": "./dist\\/sub.js", "default": "./nope.js" } } }',
        "node_modules/escx/dist/main.js": "export const main = 1;\n",
        "node_modules/escx/dist/sub.js": "export const sub = 'escx sub via import condition';\n",
    })
    check_script(run, workdir, G, "esm_package_resolution", ESM_NORM + r'''
import { main } from '@acme/kit';
import { feat } from '@acme/kit/feature';
import bm from 'brokenmain';
import { viaSibling } from 'sib';
console.log(main, '|', feat, '|', bm.from, '|', viaSibling);
import esc from 'esc';
import { sub } from 'escx/sub';
console.log(esc, '|', sub);
for (const s of ['@acme/kit/missing', '@acme/other', 'nopkg/x']) {
  try { await import(s); console.log('loaded', s); } catch (e) { console.log(s, errStr(e)); }
}
''', filename="main.mjs")


def test_esm_cjs_export_scanner_chains_and_names(run, workdir):
    """CATCHES: a CommonJS export-name scanner for ESM imports that follows re-export chains deeper than
    the reference (names from the 6th file on stay reachable only via default), does not resolve
    `require('./dir')` to dir/index.js or `require('./c1')` by appending .js, follows bare-package
    re-exports, treats `const x = require(...)` as a re-export, accepts computed defineProperty names,
    `__esModule`, non-identifier or reserved keys from `module.exports = {...}`; also files whose names
    contain a double quote, a backslash or a newline must still load."""
    files = {
        "lib/c0.cjs": "exports.n0 = 0; module.exports = Object.assign(module.exports, require('./c1'));\n",
        "lib/c6.js": "exports.n6 = 6;\n",
        "lib/todir.cjs": "module.exports = require('./dir');\n",
        "lib/dir/index.js": "exports.fromIndex = 'index.js of dir'; const helper = require('./helper.js'); exports.helped = helper.v;\n",
        "lib/dir/helper.js": "exports.v = 'helper value';\n",
        "lib/bare.cjs": "module.exports = require('ext');\n",
        "node_modules/ext/index.js": "exports.extName = 'ext';\n",
        "lib/define.cjs": "const NAME = 'computed';\n"
                          "Object.defineProperty(exports, '__esModule', { value: true });\n"
                          "Object.defineProperty(exports, NAME, { value: 'by var', enumerable: true });\n"
                          "Object.defineProperty(exports, \"literal\", { value: 'by literal', enumerable: true });\n"
                          "if (false) { Object.defineProperty(exports); __export(exports, someObject); }\n"
                          "module.exports = { \"esc\\\"aped\": 1, 'single': 2, \"1abc\": 3, \"foo-bar\": 4, ok: 5, $dollar: 6, _u: 7, \"let\": 8 };\n",
        'lib/q"uote.cjs': "exports.quoted = 'file name with a quote';\n",
        "lib/back\\slash.cjs": "exports.slashed = 'file name with a backslash';\n",
        "lib/new\nline.cjs": "exports.newlined = 'file name with a newline';\n",
    }
    for i in range(1, 6):
        files[f"lib/c{i}.js"] = f"exports.n{i} = {i}; Object.assign(exports, require('./c{i + 1}'));\n"
    write_files(workdir, files)
    check_script(run, workdir, G, "esm_cjs_export_scanner", r'''
import * as c0 from './lib/c0.cjs';
console.log('chain names', Object.keys(c0).join(','));
console.log('default sees all', Object.keys(c0.default).sort().join(','));
import * as td from './lib/todir.cjs';
console.log('todir', Object.keys(td).join(','), td.fromIndex, td.helped);
import * as bare from './lib/bare.cjs';
console.log('bare', Object.keys(bare).join(','), bare.default.extName);
import * as def from './lib/define.cjs';
console.log('define', Object.keys(def).join(','));
console.log('define default', JSON.stringify(def.default));
import { quoted } from './lib/q"uote.cjs';
import { slashed } from './lib/back\\slash.cjs';
import { newlined } from './lib/new\nline.cjs';
console.log(quoted, '|', slashed, '|', newlined);
''', filename="main.mjs")


def test_esm_defer_then_dynamic_import(run, workdir):
    """CATCHES: a module that failed while being evaluated through an `import defer` namespace not
    making a later dynamic import() reject with the same error (it must not re-run), a module evaluated
    through a deferred namespace being evaluated again by import() (the namespaces must still differ),
    import.defer() of a module with an async dependency not starting that dependency eagerly or
    evaluating the module's sync dependencies before first access. Also pins the reference resolving the
    import.defer() promise before the async dependency finishes, so an immediate access throws the
    'module graph is evaluating' TypeError while a later access succeeds."""
    write_files(workdir, {
        "thr.mjs": "console.log('thr body runs');\nthrow new Error('thr failed');\nexport const x = 1;\n",
        "ok.mjs": "console.log('ok body runs');\nexport const y = 'ok value';\n",
        "tla.mjs": "console.log('tla start');\nawait new Promise((r) => setTimeout(r, 5));\nconsole.log('tla end');\nexport const t = 'tla value';\n",
        "mid.mjs": "import { t } from './tla.mjs';\nimport { leaf } from './leaf.mjs';\nconsole.log('mid body runs');\n"
                   "export const m = 'mid sees ' + t + ' and ' + leaf;\n",
        "leaf.mjs": "console.log('leaf body runs');\nexport const leaf = 'leaf';\n",
    })
    check_script(run, workdir, G, "esm_defer_then_dynamic", r'''
import defer * as thr from './thr.mjs';
import defer * as ok from './ok.mjs';
console.log('main start');
try { thr.x; } catch (e) { console.log('deferred access threw', e.message); }
try { thr.x; } catch (e) { console.log('second access threw', e.message); }
try { await import('./thr.mjs'); } catch (e) { console.log('dynamic import after deferred failure rejects:', e.message); }
console.log('ok via defer', ok.y);
const okNs = await import('./ok.mjs');
console.log('dynamic import after deferred eval', okNs.y, okNs === ok);
const dm = await import.defer('./mid.mjs');
console.log('import.defer(mid) resolved', dm[Symbol.toStringTag]);
try { dm.m; } catch (e) { console.log('touch while tla pending:', e.name + ': ' + e.message); }
await new Promise((r) => setTimeout(r, 60));
console.log('touch mid later', dm.m);
const dt = await import.defer('./tla.mjs');
console.log('import.defer(tla) of evaluated module', dt.t);
''', filename="main.mjs")


@pytest.mark.parametrize("filename,source,stderr", [
    ("throw_number.mjs", "console.log('start');\nthrow 42;\n",
     "Uncaught (in promise) 42\nUncaught Number: 42\n"),
    ("throw_nameless.mjs", "console.log('start');\nthrow { name: '', message: 'plain message' };\n",
     "Uncaught (in promise) : plain message\nUncaught plain message\n"),
    ("throw_empty_message.mjs", "console.log('start');\nconst e = new Error(''); e.name = 'Custom';\nthrow e;\n",
     "Uncaught (in promise) Custom\nUncaught Custom: \n"),
    ("throw_empty_message.cjs", "console.log('start');\nconst e = new Error(''); e.name = 'Custom';\nthrow e;\n",
     "Uncaught Custom\n"),
], ids=["esm-number", "esm-empty-name", "esm-empty-message", "cjs-empty-message"])
def test_entry_uncaught_error_rendering(run, workdir, filename, source, stderr):
    """CATCHES: wrong uncaught-error lines for entry scripts: an ES module entry reports the rejection
    ('Uncaught (in promise) ...') and then the fatal line, a thrown primitive renders with its type
    name ('Uncaught Number: 42'), an object with an empty `name` renders just its message, an error
    with an empty message renders as its bare name (CommonJS) or 'Name: ' (module fatal line); output
    printed before the throw must survive and the exit code must be 1."""
    (workdir / filename).write_text(source)
    r = run([filename])
    assert (r.stdout, r.stderr.decode(), r.returncode) == (b"start\n", stderr, 1)


# ---- JSX ---------------------------------------------------------------------------------------

def test_bun_transpiler_jsx_lexing(run, workdir):
    """CATCHES: the JSX transformer (as exposed by Bun.Transpiler's jsx loader) misreading `<` inside
    quoted strings, template literals (including escaped backticks and JSX nested in `${}`), line
    comments and regex literals (escaped slashes, character classes, flags); element-valued attributes
    (`attr=<X/>`), comments between attributes, quote/backslash/tab/newline/CR escaping in attribute
    strings and text children, multi-line text whitespace collapsing, `< ` with a space being a
    comparison, member-expression and dashed/namespaced names, and the exact SyntaxError messages for a
    missing element name, a missing attribute name, unterminated `{` and an unterminated opening tag."""
    check_script(run, workdir, G, "bun_transpiler_jsx_lexing", r'''
const t = new Bun.Transpiler({ loader: 'jsx' });
const show = (s) => { try { console.log(JSON.stringify(t.transformSync(s))); } catch (e) { console.log(e.name + ': ' + e.message); } };
show("const s = '<notjsx>' + \"<b>\\\"</b>\"; const el = <i/>;");
show("const tpl = `a<b>${<em>{x}</em>}\\`</b>`; // <comment> stays\nconst y = <hr/>;");
show("// leading line comment <x>\nconst r = /<a\\/[<>]+/gi.test(s) ? <yes/> : <no/>;");
show("<Card header=<Title text='hi'/> footer={<p>f</p>}/>");
show("<div /* inline */ a=\"1\" // line\n b>x</div>");
show("<a title='say \"hi\"' path='C:\\dir' tab='a\tb' nl='l1\nl2' cr='x\ry'/>");
show("<p>\n  first line\n\n    second   line  \n  <b/>\n  tail\n</p>");
show("<p>a\tb\r\n  c\r\n</p>");
show("<p>  \t  </p>");
show("<pre>a\\b \"q\"</pre>");
show("< >x</>");
show("x = a</b>/i;");
show("<this.Comp/>");
show("<Foo.Bar.Baz/>");
show("<a-b c:d='e'/>");
show("const x = </div>;");
show("<div title=\"say \\\"hi\\\"\"/>");
show("<div =\"x\"/>");
show("<div>{a</div>");
show("<div a={1}");
''')


def test_jsx_entry_lexing_and_attribute_strings(run, workdir):
    """CATCHES: a .jsx entry whose transform misfires on `<`/`>` inside single/double-quoted strings
    with escapes, template literals with escaped backticks and JSX inside `${}`, regex literals with
    escaped slashes/character classes/flags, or line comments; comments inside an opening tag breaking
    attribute parsing; element-valued attributes not producing elements; and attribute strings with
    raw newlines/tabs not reaching props unchanged (rendered via a tiny classic-runtime React shim)."""
    check_script(run, workdir, G, "jsx_entry_lexing", r'''
const React = {
  Fragment: Symbol('Fragment'),
  createElement(type, props, ...children) { return { type, props, children }; },
};
const render = (n) => {
  if (n === null || n === undefined || n === false) return '';
  if (typeof n !== 'object') return String(n);
  if (Array.isArray(n)) return n.map(render).join('');
  if (n.type === React.Fragment) return n.children.map(render).join('');
  if (typeof n.type === 'function') return render(n.type({ ...(n.props || {}), children: n.children }));
  const attrs = Object.entries(n.props || {}).map(([k, v]) => ' ' + k + '=' + JSON.stringify(typeof v === 'object' ? render(v) : v)).join('');
  return '<' + n.type + attrs + '>' + n.children.map(render).join('') + '</' + n.type + '>';
};
const quote = 'it\'s <not> a tag \\ "really"';
const dq = "<b>\"</b>";
const tpl = `tick \` and ${<em>{'nested'}</em> && 'jsx in template'} <i>`;
const re = /<\/?[a-z]+[^>]*>/gi;
const cls = /[<>]/;
const stripped = '<p>keep</p>'.replace(re, '');
// a line comment mentioning <span> must not become JSX
const Card = ({ header, children }) => <section>{header}{children}</section>;
const el = (
  <Card /* block comment inside the tag */ header=<h1 title='multi
line' tab='a	b'>Title</h1> // line comment inside the tag
  >
    <p data-kind="x">a	b</p>
    {quote}|{dq}|{tpl}|{stripped}|{String(cls.test('<'))}
  </Card>
);
console.log(render(el));
console.log(JSON.stringify(el.props.header.props), el.props.header.children.length);
console.log(JSON.stringify(el.children.slice(1, 4)));
''', filename="app.jsx")


# ---- workers -----------------------------------------------------------------------------------

def test_web_worker_timers_close_and_onerror(run, workdir):
    """CATCHES: a web Worker whose own event loop does not run microtasks, timers and message handlers
    in order (sync reply, then microtask, then timer), an uncaught exception thrown from a worker timer
    not reaching the parent's onerror as an ErrorEvent whose message is 'Uncaught RangeError: ...', or
    close() not stopping the worker (the rest of the current handler still runs, so its message still
    arrives) -- the parent has nothing else pending, so it must exit as soon as the closed worker is gone."""
    write_files(workdir, {"wk.js": r'''
self.onmessage = (e) => {
  if (e.data === 'boom') { setTimeout(() => { throw new RangeError('timer boom'); }, 0); return; }
  if (e.data === 'close') { postMessage('closing'); close(); postMessage('after close call'); return; }
  queueMicrotask(() => postMessage('micro ' + e.data));
  setTimeout(() => postMessage('timer ' + e.data), 5);
  postMessage('sync ' + e.data);
};
postMessage('ready');
'''})
    check_script(run, workdir, G, "web_worker_timers_close", r'''
const w = new Worker('./wk.js');
w.onmessage = (e) => {
  console.log('main got', e.data);
  if (e.data === 'ready') w.postMessage('a');
  if (e.data === 'timer a') w.postMessage('boom');
  if (e.data === 'after close call') console.log('main done: the closed worker must not keep the process alive');
};
w.onerror = (e) => {
  console.log('main onerror', e.constructor.name, e.type, JSON.stringify(e.message));
  w.postMessage('close');
};
''')


def test_web_worker_missing_script(run, workdir):
    """CATCHES: a web Worker pointed at a nonexistent script throwing synchronously or exiting silently
    instead of firing onerror with 'cannot load worker script <path>: <OS error>' (the path exactly as
    given); terminate() from the handler must then let the parent exit cleanly."""
    check_script(run, workdir, G, "web_worker_missing_script", r'''
const w = new Worker('./missing-worker.js');
console.log('constructed');
w.onmessage = (e) => console.log('unexpected message', e.data);
w.onerror = (e) => {
  console.log('onerror', e.type, JSON.stringify(e.message));
  w.terminate();
  console.log('terminated');
};
''')


def test_worker_threads_ref_after_unref_and_loop_sources(run, workdir):
    """CATCHES: worker.ref() after unref() not keeping the parent alive until the worker's late message
    arrives, or a worker_threads worker whose event loop mishandles its own task sources: a promise job
    runs before a nextTick callback queued in the same turn, then a timer, an fs.promises read
    completion, and a setImmediate scheduled from it, with exit code 0 once the worker goes idle."""
    write_files(workdir, {"data.txt": "payload from disk\n"})
    check_script(run, workdir, G, "worker_threads_ref_loop", r'''
const { Worker } = require('worker_threads');
const w = new Worker(`const { parentPort } = require('worker_threads');
  const fs = require('fs');
  const order = [];
  process.nextTick(() => order.push('tick'));
  Promise.resolve().then(() => order.push('micro'));
  setTimeout(() => {
    order.push('timeout');
    fs.promises.readFile('data.txt', 'utf8').then((t) => {
      order.push('read:' + t.trim());
      setImmediate(() => { order.push('immediate'); setTimeout(() => parentPort.postMessage(order.join(' | ')), 120); });
    });
  }, 10);
  parentPort.postMessage('sync done');`, { eval: true });
w.unref();
w.ref();
w.on('message', (m) => console.log('got', m));
w.on('exit', (c) => console.log('exit', c));
''')


def test_worker_threads_port_ref_toggles(run, workdir):
    """CATCHES: parentPort.ref()/unref() inside a worker not controlling whether its 'message' listener
    keeps the worker alive (after unref() the idle worker must exit with code 0 even though a listener
    is still attached), ref()/unref() on an exited Worker throwing, or an unref()'d worker's messages
    not being delivered while something else keeps the parent alive."""
    check_script(run, workdir, G, "worker_threads_port_ref_toggles", r'''
const { Worker } = require('worker_threads');
const w = new Worker(`const { parentPort } = require('worker_threads');
  parentPort.on('message', (m) => {
    if (m === 'go-idle') { parentPort.unref(); parentPort.postMessage('worker unref-ed its port'); }
  });
  setTimeout(() => { parentPort.ref(); parentPort.unref(); parentPort.ref(); parentPort.postMessage('toggled'); }, 0);`, { eval: true });
w.on('message', (m) => { console.log('main got', m); if (m === 'toggled') w.postMessage('go-idle'); });
w.on('exit', (c) => {
  console.log('exit', c);
  w.ref(); w.unref();
  console.log('ref/unref after exit ok');
  const u = new Worker(`require('worker_threads').parentPort.postMessage('hello from an unref-ed worker');`, { eval: true });
  u.unref();
  const keep = setTimeout(() => console.log('timeout: message never arrived'), 8000);
  u.on('message', (m) => { console.log('second worker:', m); clearTimeout(keep); });
});
''')


# ---- REPL --------------------------------------------------------------------------------------

def test_repl_dot_commands_await_and_errors(run):
    """CATCHES: a piped REPL that mishandles unknown dot commands ('unknown command .x (try .help)'),
    treats '..' as a command, cannot report a never-settling top-level await ('[promise never
    settled]'), renders awaited rejections differently from sync throws, leaks `const` bindings from an
    awaited statement into the global scope, reports unfixable await syntax with the wrong SyntaxError,
    or renders results (quoted strings, `_`, arrays, objects, null, undefined, symbols, BigInts,
    multi-line functions) differently."""
    src = "\n".join([
        ".foo", ".break", "..", "await new Promise(() => {})",
        "await Promise.reject(new TypeError('nope'))", "await Promise.reject(42)",
        "const v = await Promise.resolve(3)", "typeof v", "let = ;", "await )", "x = await 5; x + 1",
        "'s' + 1", "_", "[1, [2, 3]]", "({ a: 1 })", "null", "undefined", "Symbol('q')", "10n ** 3n",
        "function f() {", "  return 7", "}", "f()", "_ * 2",
    ]) + "\n"
    r = run(["repl"], input=src)
    assert_result(r, G / "repl_dot_commands_await.golden")


# ---- timers ------------------------------------------------------------------------------------

def test_timer_argument_edge_cases(run, workdir):
    """CATCHES: setTimeout without a delay not firing, an `undefined` delay with extra arguments not
    passing them to the callback, clearTimeout/clearInterval throwing for garbage ids (strings, negative,
    NaN, objects, nothing) instead of ignoring them, clearTimeout of a numeric id coerced from a value
    not cancelling, or a non-function callback not throwing 'setTimeout/setInterval expects a function'."""
    check_script(run, workdir, G, "timer_argument_edge_cases", r'''
const t = setTimeout(() => console.log('no-delay fired'));
console.log('id type', typeof t);
for (const bad of ['abc', -1, undefined, null, {}, NaN]) clearTimeout(bad);
clearTimeout();
clearInterval(NaN);
const t2 = setTimeout(() => console.log('cancelled timer fired!'), 5);
clearTimeout(String(t2));
setTimeout(console.log, undefined, 'extra', 'args', 3);
for (const f of [() => setTimeout('code string'), () => setInterval(), () => setTimeout(null, 1)]) {
  try { f(); console.log('no throw'); } catch (e) { console.log(e.name + ': ' + e.message); }
}
''', filename="timers.cjs")
