"""N-API native addons: `require('./addon.node')` dlopens a compiled C library, calls its
`napi_register_module_v1`, and resolves the addon's `napi_*` symbols against the lumen executable.

Every test compiles a small addon from inline C (the N-API ABI is declared inline below, exactly like
examples/native-addon/addon.c — no Node headers), loads it from a JS program and prints what the
native side observed. Status codes returned by `napi_*` calls are handed back to JS as numbers (never
printed from C) so stdout ordering stays deterministic; no pointer values ever reach the output.
"""

import shutil

import pytest

from conftest import build_addon, err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# The N-API C ABI, declared inline (types, the functions lumen exports, a few it does not export),
# plus tiny helpers shared by every addon below. Declaring an extern that is never called creates no
# undefined-symbol reference, so only the functions an addon actually calls must resolve at load.
NAPI_H = r"""
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>

typedef void *napi_env;
typedef void *napi_value;
typedef void *napi_callback_info;
typedef void *napi_ref;
typedef void *napi_handle_scope;
typedef void *napi_deferred;
typedef void *napi_async_work;
typedef void *napi_threadsafe_function;
typedef int napi_status;
typedef napi_value (*napi_callback)(napi_env, napi_callback_info);
typedef void (*napi_finalize)(napi_env, void *, void *);
typedef void (*napi_async_execute_callback)(napi_env, void *);
typedef void (*napi_async_complete_callback)(napi_env, napi_status, void *);
typedef struct {
  const char *utf8name;
  napi_value name;
  napi_callback method;
  napi_callback getter;
  napi_callback setter;
  napi_value value;
  int attributes;
  void *data;
} napi_property_descriptor;

#define NAPI_AUTO_LENGTH ((size_t)-1)
#define napi_enumerable 2
#define napi_static 1024

extern napi_status napi_get_undefined(napi_env, napi_value *);
extern napi_status napi_get_null(napi_env, napi_value *);
extern napi_status napi_get_global(napi_env, napi_value *);
extern napi_status napi_get_boolean(napi_env, bool, napi_value *);
extern napi_status napi_create_double(napi_env, double, napi_value *);
extern napi_status napi_create_int32(napi_env, int32_t, napi_value *);
extern napi_status napi_create_uint32(napi_env, uint32_t, napi_value *);
extern napi_status napi_create_int64(napi_env, int64_t, napi_value *);
extern napi_status napi_create_string_utf8(napi_env, const char *, size_t, napi_value *);
extern napi_status napi_create_object(napi_env, napi_value *);
extern napi_status napi_create_array(napi_env, napi_value *);
extern napi_status napi_create_array_with_length(napi_env, size_t, napi_value *);
extern napi_status napi_create_function(napi_env, const char *, size_t, napi_callback, void *, napi_value *);
extern napi_status napi_typeof(napi_env, napi_value, int *);
extern napi_status napi_get_value_double(napi_env, napi_value, double *);
extern napi_status napi_get_value_int32(napi_env, napi_value, int32_t *);
extern napi_status napi_get_value_uint32(napi_env, napi_value, uint32_t *);
extern napi_status napi_get_value_bool(napi_env, napi_value, bool *);
extern napi_status napi_get_value_string_utf8(napi_env, napi_value, char *, size_t, size_t *);
extern napi_status napi_coerce_to_string(napi_env, napi_value, napi_value *);
extern napi_status napi_set_named_property(napi_env, napi_value, const char *, napi_value);
extern napi_status napi_get_named_property(napi_env, napi_value, const char *, napi_value *);
extern napi_status napi_has_named_property(napi_env, napi_value, const char *, bool *);
extern napi_status napi_set_property(napi_env, napi_value, napi_value, napi_value);
extern napi_status napi_get_property(napi_env, napi_value, napi_value, napi_value *);
extern napi_status napi_set_element(napi_env, napi_value, uint32_t, napi_value);
extern napi_status napi_get_element(napi_env, napi_value, uint32_t, napi_value *);
extern napi_status napi_get_cb_info(napi_env, napi_callback_info, size_t *, napi_value *, napi_value *, void **);
extern napi_status napi_call_function(napi_env, napi_value, napi_value, size_t, const napi_value *, napi_value *);
extern napi_status napi_throw(napi_env, napi_value);
extern napi_status napi_throw_error(napi_env, const char *, const char *);
extern napi_status napi_throw_type_error(napi_env, const char *, const char *);
extern napi_status napi_throw_range_error(napi_env, const char *, const char *);
extern napi_status napi_create_error(napi_env, napi_value, napi_value, napi_value *);
extern napi_status napi_is_exception_pending(napi_env, bool *);
extern napi_status napi_get_and_clear_last_exception(napi_env, napi_value *);
extern napi_status napi_open_handle_scope(napi_env, napi_handle_scope *);
extern napi_status napi_close_handle_scope(napi_env, napi_handle_scope);
extern napi_status napi_get_version(napi_env, uint32_t *);
extern napi_status napi_strict_equals(napi_env, napi_value, napi_value, bool *);
extern napi_status napi_is_error(napi_env, napi_value, bool *);
extern napi_status napi_get_prototype(napi_env, napi_value, napi_value *);
extern napi_status napi_create_reference(napi_env, napi_value, uint32_t, napi_ref *);
extern napi_status napi_delete_reference(napi_env, napi_ref);
extern napi_status napi_get_reference_value(napi_env, napi_ref, napi_value *);
extern napi_status napi_reference_ref(napi_env, napi_ref, uint32_t *);
extern napi_status napi_reference_unref(napi_env, napi_ref, uint32_t *);
extern napi_status napi_wrap(napi_env, napi_value, void *, napi_finalize, void *, napi_ref *);
extern napi_status napi_unwrap(napi_env, napi_value, void **);
extern napi_status napi_remove_wrap(napi_env, napi_value, void **);
extern napi_status napi_define_class(napi_env, const char *, size_t, napi_callback, void *, size_t,
                                     const napi_property_descriptor *, napi_value *);
extern napi_status napi_new_instance(napi_env, napi_value, size_t, const napi_value *, napi_value *);
extern napi_status napi_create_promise(napi_env, napi_deferred *, napi_value *);
extern napi_status napi_resolve_deferred(napi_env, napi_deferred, napi_value);
extern napi_status napi_reject_deferred(napi_env, napi_deferred, napi_value);
extern napi_status napi_create_buffer_copy(napi_env, size_t, const void *, void **, napi_value *);
extern napi_status napi_create_external_buffer(napi_env, size_t, void *, napi_finalize, void *, napi_value *);
extern napi_status napi_get_typedarray_info(napi_env, napi_value, int *, size_t *, void **, napi_value *, size_t *);
extern napi_status napi_create_async_work(napi_env, napi_value, napi_value, napi_async_execute_callback,
                                          napi_async_complete_callback, void *, napi_async_work *);
extern napi_status napi_queue_async_work(napi_env, napi_async_work);
extern napi_status napi_delete_async_work(napi_env, napi_async_work);
extern napi_status napi_cancel_async_work(napi_env, napi_async_work);
extern napi_status napi_create_threadsafe_function(napi_env, napi_value, napi_value, napi_value, size_t, size_t,
                                                   void *, void *, void *, void *, napi_threadsafe_function *);
extern napi_status napi_unref_threadsafe_function(napi_env, napi_threadsafe_function);
/* part of Node-API, but not exported by lumen */
extern napi_status napi_create_bigint_int64(napi_env, int64_t, napi_value *);
extern napi_status napi_get_property_names(napi_env, napi_value, napi_value *);
extern napi_status napi_set_instance_data(napi_env, void *, napi_finalize, void *);

static napi_value num(napi_env env, double d) { napi_value v; napi_create_double(env, d, &v); return v; }
static napi_value str(napi_env env, const char *s) {
  napi_value v; napi_create_string_utf8(env, s, NAPI_AUTO_LENGTH, &v); return v;
}
static napi_value boolean(napi_env env, bool b) { napi_value v; napi_get_boolean(env, b, &v); return v; }
static napi_value arg(napi_env env, napi_callback_info info, size_t i) {
  size_t argc = 8; napi_value argv[8];
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  return argv[i];
}
static uint32_t arg_u32(napi_env env, napi_callback_info info, size_t i) {
  uint32_t v = 0; napi_get_value_uint32(env, arg(env, info, i), &v); return v;
}
static void export_fn(napi_env env, napi_value exports, const char *name, napi_callback cb) {
  napi_value fn; napi_create_function(env, name, NAPI_AUTO_LENGTH, cb, NULL, &fn);
  napi_set_named_property(env, exports, name, fn);
}
/* {status, pending[, error]} — reports a call's status and clears (and returns) any pending exception */
static napi_value report(napi_env env, napi_status s) {
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "status", num(env, s));
  bool pending = false; napi_is_exception_pending(env, &pending);
  napi_set_named_property(env, o, "pending", boolean(env, pending));
  if (pending) {
    napi_value e; napi_get_and_clear_last_exception(env, &e);
    napi_set_named_property(env, o, "error", e);
  }
  return o;
}
"""


def addon(workdir, body, name="addon.node"):
    """Compile NAPI_H + body into workdir/<name>."""
    return build_addon(NAPI_H + body, workdir / name)


# JS helper used by several programs: a stable one-line rendering of report() objects and values.
SHOW_JS = r"""
const show = (v) => JSON.stringify(v, (k, x) =>
  x instanceof Error ? `<${x.name}: ${x.message}>` :
  x === undefined ? '<undefined>' :
  typeof x === 'bigint' ? `${x}n` :
  typeof x === 'symbol' ? x.toString() :
  typeof x === 'function' ? `<function ${x.name}>` : x);
"""


# ------------------------------------------------------------------------------------ basic loading
EXAMPLE_C = r"""
static napi_value hello(napi_env env, napi_callback_info info) {
  napi_value s;
  napi_create_string_utf8(env, "world from native code", NAPI_AUTO_LENGTH, &s);
  return s;
}
static napi_value add(napi_env env, napi_callback_info info) {
  size_t argc = 2;
  napi_value argv[2];
  napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  if (argc < 2) {
    napi_throw_error(env, NULL, "add(a, b) expects two numbers");
    return NULL;
  }
  double a = 0, b = 0;
  napi_get_value_double(env, argv[0], &a);
  napi_get_value_double(env, argv[1], &b);
  napi_value result;
  napi_create_double(env, a + b, &result);
  return result;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  napi_value fn, version;
  napi_create_function(env, "hello", NAPI_AUTO_LENGTH, hello, NULL, &fn);
  napi_set_named_property(env, exports, "hello", fn);
  napi_create_function(env, "add", NAPI_AUTO_LENGTH, add, NULL, &fn);
  napi_set_named_property(env, exports, "add", fn);
  napi_create_string_utf8(env, "1.0.0", NAPI_AUTO_LENGTH, &version);
  napi_set_named_property(env, exports, "version", version);
  return exports;
}
"""


def test_example_addon_exports_functions_and_values(js, workdir):
    """CATCHES: a loader that does not call napi_register_module_v1 with a fresh exports object, or
    native functions whose arguments, return values or thrown errors are not bridged back to JS."""
    addon(workdir, EXAMPLE_C)
    code = r"""
const addon = require('./addon.node');
console.log('addon.version   =>', addon.version);
console.log('addon.hello()   =>', addon.hello());
console.log('addon.add(2, 3) =>', addon.add(2, 3));
console.log('addon.add(0.1, 0.2) =>', addon.add(0.1, 0.2));
console.log('typeof add      =>', typeof addon.add);
console.log('keys            =>', Object.keys(addon).sort().join(','));
try {
  addon.add(1);
} catch (e) {
  console.log('addon.add(1)    => threw:', e.message, e instanceof Error);
}
"""
    r = js(code)
    assert out(r) == (
        "addon.version   => 1.0.0\n"
        "addon.hello()   => world from native code\n"
        "addon.add(2, 3) => 5\n"
        "addon.add(0.1, 0.2) => 0.30000000000000004\n"
        "typeof add      => function\n"
        "keys            => add,hello,version\n"
        "addon.add(1)    => threw: add(a, b) expects two numbers true\n"
    )
    assert (r.returncode, r.stderr) == (0, b"")


def test_addon_loads_through_esm_import_and_extensionless_require(js, workdir, golden):
    """CATCHES: module resolution that only dlopens addons for an explicit `.node` CommonJS require,
    breaking ESM `import` of an addon, createRequire, or extension probing of `require('./addon')`."""
    addon(workdir, EXAMPLE_C)
    (workdir / "cjs.cjs").write_text("module.exports = require('./addon');\n", encoding="utf-8")
    code = r"""
import addon from './addon.node';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const viaRequire = require('./addon.node');
const viaCjs = require('./cjs.cjs');
console.log('import:', addon.hello(), addon.add(40, 2), addon.version);
console.log('same module object:', viaRequire === addon, viaCjs === addon);
console.log('extensionless:', viaCjs.add(1.5, 1.5));
"""
    r = js(code, name="main.mjs")
    assert out(r) == golden("esm_import")
    assert (r.returncode, r.stderr) == (0, b"")


def test_addon_loads_from_eval_string(run, workdir):
    """CATCHES: a runtime that only wires the `.node` loader for script files, so `lumen-cli -e`
    programs cannot require a native addon relative to the working directory."""
    addon(workdir, EXAMPLE_C)
    r = run(["-e", "const a = require('./addon.node'); console.log(a.hello(), a.add(20, 22), a.version);"])
    assert out(r) == "world from native code 42 1.0.0\n"
    assert (r.returncode, r.stderr) == (0, b"")


def test_two_addons_and_a_copy_keep_separate_native_state(js, workdir, golden):
    """CATCHES: an addon registry that caches by symbol or shares one library handle across paths, so
    two different addons (or a copy of one at another path) clobber each other's exports or statics."""
    counter = r"""
static int calls = 0;
static napi_value bump(napi_env env, napi_callback_info info) { calls++; return num(env, calls); }
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "bump", bump);
  napi_set_named_property(env, exports, "flavor", str(env, FLAVOR));
  return exports;
}
"""
    addon(workdir, '#define FLAVOR "first"\n' + counter, "first.node")
    addon(workdir, '#define FLAVOR "second"\n' + counter, "second.node")
    shutil.copy(workdir / "first.node", workdir / "copy.node")
    code = r"""
const a = require('./first.node');
const b = require('./second.node');
const c = require('./copy.node');
console.log(a.flavor, b.flavor, c.flavor);
console.log('a', a.bump(), a.bump(), a.bump());
console.log('b', b.bump());
console.log('copy', c.bump(), c.bump());
console.log('a again', a.bump(), require('./first.node') === a, require('./first.node').bump());
console.log('distinct', a !== c, a.bump !== c.bump);
"""
    r = js(code)
    assert out(r) == golden("two_addons")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- registration result
REGISTER_C = r"""
static napi_value hi(napi_env env, napi_callback_info info) { return str(env, "hi from the replacement"); }
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  napi_value g, mode; napi_get_global(env, &g);
  napi_get_named_property(env, g, "ADDON_MODE", &mode);
  char m[16] = ""; size_t n; napi_get_value_string_utf8(env, mode, m, sizeof m, &n);
  if (!strcmp(m, "null")) {
    napi_set_named_property(env, exports, "filled", str(env, "in place, NULL returned"));
    return NULL;
  }
  if (!strcmp(m, "function")) {
    napi_value f; napi_create_function(env, "replacement", NAPI_AUTO_LENGTH, hi, NULL, &f);
    napi_set_named_property(env, exports, "lost", str(env, "never visible"));
    return f;
  }
  if (!strcmp(m, "number")) return num(env, 7.5);
  if (!strcmp(m, "throw")) { napi_throw_range_error(env, NULL, "registration refused"); return exports; }
  if (!strcmp(m, "throwvalue")) { napi_throw(env, str(env, "a bare string")); return NULL; }
  napi_set_named_property(env, exports, "filled", str(env, "returned exports"));
  return exports;
}
"""


@pytest.mark.parametrize("mode", ["null", "function", "number", "exports"])
def test_register_return_value_becomes_module_exports(js, workdir, golden, mode):
    """CATCHES: a loader that ignores what napi_register_module_v1 returns (always using the passed
    exports), or that does not fall back to the populated exports object when NULL is returned."""
    addon(workdir, REGISTER_C)
    code = f"globalThis.ADDON_MODE = '{mode}';\n" + r"""
const m = require('./addon.node');
console.log(typeof m, typeof m === 'function' ? m.name + ': ' + m() : JSON.stringify(m));
console.log('cached:', require('./addon.node') === m, require.cache[require.resolve('./addon.node')].exports === m);
"""
    r = js(code)
    assert out(r) == golden(f"register_{mode}")
    assert (r.returncode, r.stderr) == (0, b"")


def test_exception_thrown_during_registration_is_uncaught(js, workdir):
    """CATCHES: a loader that drops an exception left pending by napi_register_module_v1 and returns
    the exports anyway, instead of making require() throw it (uncaught: exit 1 with the error)."""
    addon(workdir, REGISTER_C)
    r = js("globalThis.ADDON_MODE = 'throw';\nconsole.log('loading');\nrequire('./addon.node');\nconsole.log('unreachable');\n")
    assert out(r) == "loading\n"
    assert (r.returncode, err(r)) == (1, "Uncaught RangeError: registration refused\n")


@pytest.mark.parametrize("mode,expected", [
    pytest.param("throw", "caught object true RangeError: registration refused\n", id="range_error"),
    pytest.param("throwvalue", 'caught string false "a bare string"\n', id="bare_string"),
])
def test_exception_thrown_during_registration_is_catchable(js, workdir, mode, expected):
    """CATCHES: registration exceptions that lose their type or value on the way out of require(), e.g.
    a native RangeError turned into a generic Error or a bare thrown string wrapped into an Error."""
    addon(workdir, REGISTER_C)
    code = f"globalThis.ADDON_MODE = '{mode}';\n" + r"""
try { require('./addon.node'); console.log('no throw'); }
catch (e) { console.log('caught', typeof e, e instanceof RangeError, e instanceof Error ? `${e.name}: ${e.message}` : JSON.stringify(e)); }
"""
    r = js(code)
    assert out(r) == expected
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------ load failures
@pytest.mark.parametrize("symbol,call", [
    pytest.param("napi_create_bigint_int64", "napi_create_bigint_int64(env, 5, &v);", id="bigint"),
    pytest.param("napi_get_property_names", "napi_get_property_names(env, arg(env, info, 0), &v);", id="property_names"),
    pytest.param("napi_set_instance_data", "napi_set_instance_data(env, NULL, NULL, NULL); v = NULL;", id="instance_data"),
])
def test_unimplemented_napi_symbol_fails_at_load(js, workdir, symbol, call):
    """CATCHES: lazily-bound addon loading (no RTLD_NOW) or a host that silently stubs unknown napi_*
    functions: an addon merely referencing an unexported function must fail at require() naming it."""
    addon(workdir, r"""
static napi_value never_called(napi_env env, napi_callback_info info) { napi_value v; %s return v; }
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "neverCalled", never_called);
  return exports;
}
""" % call)
    r = js("console.log('before require');\nconst a = require('./addon.node');\nconsole.log('loaded', typeof a);\n")
    assert out(r) == "before require\n"
    assert r.returncode == 1
    assert err(r).replace(str(workdir), "<WORKDIR>") == (
        "Uncaught Error: cannot load native addon '<WORKDIR>/addon.node': "
        f"<WORKDIR>/addon.node: undefined symbol: {symbol}\n")


def test_load_failure_is_a_catchable_error(js, workdir):
    """CATCHES: a load failure that aborts the process or throws a non-Error, instead of an Error the
    program can catch and keep running after (message naming the addon path and missing symbol)."""
    addon(workdir, r"""
static napi_value never_called(napi_env env, napi_callback_info info) { napi_value v; napi_create_bigint_int64(env, 1, &v); return v; }
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "neverCalled", never_called);
  return exports;
}
""")
    code = r"""
try { require('./addon.node'); console.log('loaded?'); }
catch (e) { console.log(e instanceof Error, e.name, '|', e.message.split(process.cwd()).join('<CWD>')); }
console.log('still running');
"""
    r = js(code)
    assert out(r) == ("true Error | cannot load native addon '<CWD>/addon.node': <CWD>/addon.node: "
                      "undefined symbol: napi_create_bigint_int64\nstill running\n")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("content,reason", [
    pytest.param(b"this is plainly not a shared library, just text\n" * 4, "invalid ELF header", id="text"),
    pytest.param(b"", "file too short", id="empty"),
])
def test_non_library_node_file_fails_to_load(js, workdir, content, reason):
    """CATCHES: a loader that treats a garbage or empty `.node` file as JS/JSON or crashes, instead of
    surfacing the dynamic linker's error in an uncaught `cannot load native addon` Error (exit 1)."""
    (workdir / "addon.node").write_bytes(content)
    r = js("console.log('start');\nrequire('./addon.node');\n")
    assert out(r) == "start\n"
    assert r.returncode == 1
    assert err(r).replace(str(workdir), "<WORKDIR>") == (
        f"Uncaught Error: cannot load native addon '<WORKDIR>/addon.node': <WORKDIR>/addon.node: {reason}\n")


def test_library_without_register_entry_point_is_rejected(js, workdir):
    """CATCHES: a loader that calls a NULL or garbage entry point (crash) when a valid shared library
    lacks napi_register_module_v1, instead of throwing a clear `is not an N-API addon` Error."""
    build_addon("int not_an_addon(void) { return 42; }\n", workdir / "plain.node")
    r = js("console.log('start');\nrequire('./plain.node');\n")
    assert out(r) == "start\n"
    assert r.returncode == 1
    assert err(r).replace(str(workdir), "<WORKDIR>") == (
        "Uncaught Error: '<WORKDIR>/plain.node' is not an N-API addon (no napi_register_module_v1)\n")


# --------------------------------------------------------------------------------- value creation
def test_primitive_value_creation(js, workdir, golden):
    """CATCHES: wrong primitive construction — e.g. int32/uint32 extremes sign-confused, int64 not
    rounded to the nearest double, -0/Infinity/NaN lost, or napi_get_global not being globalThis."""
    addon(workdir, r"""
static napi_value make_values(napi_env env, napi_callback_info info) {
  napi_value arr, v; napi_create_array(env, &arr);
  uint32_t i = 0;
  napi_get_undefined(env, &v); napi_set_element(env, arr, i++, v);
  napi_get_null(env, &v); napi_set_element(env, arr, i++, v);
  napi_get_boolean(env, true, &v); napi_set_element(env, arr, i++, v);
  napi_get_boolean(env, false, &v); napi_set_element(env, arr, i++, v);
  napi_create_double(env, -0.0, &v); napi_set_element(env, arr, i++, v);
  napi_create_double(env, 1.0 / 0.0, &v); napi_set_element(env, arr, i++, v);
  napi_create_double(env, 0.0 / 0.0, &v); napi_set_element(env, arr, i++, v);
  napi_create_double(env, 6.02214076e23, &v); napi_set_element(env, arr, i++, v);
  napi_create_int32(env, -2147483647 - 1, &v); napi_set_element(env, arr, i++, v);
  napi_create_int32(env, 2147483647, &v); napi_set_element(env, arr, i++, v);
  napi_create_uint32(env, 4294967295u, &v); napi_set_element(env, arr, i++, v);
  napi_create_int64(env, 9007199254740993LL, &v); napi_set_element(env, arr, i++, v);
  napi_create_int64(env, -9007199254740991LL, &v); napi_set_element(env, arr, i++, v);
  napi_create_int64(env, INT64_MAX, &v); napi_set_element(env, arr, i++, v);
  napi_get_global(env, &v); napi_set_element(env, arr, i++, v);
  return arr;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "makeValues", make_values);
  return exports;
}
""")
    code = r"""
const vals = require('./addon.node').makeValues();
console.log('count', vals.length);
vals.forEach((v, i) => console.log(i, typeof v,
  v === globalThis ? 'globalThis' : Object.is(v, -0) ? '-0' : String(v), Number.isInteger(v) ? 'int' : ''));
"""
    r = js(code)
    assert out(r) == golden("primitives")
    assert (r.returncode, r.stderr) == (0, b"")


def test_string_creation_lengths_and_utf8(js, workdir, golden):
    """CATCHES: napi_create_string_utf8 that ignores an explicit byte length, mis-decodes multi-byte
    UTF-8, rejects invalid bytes instead of substituting U+FFFD, or stops at an embedded NUL."""
    addon(workdir, r"""
static napi_value make_strings(napi_env env, napi_callback_info info) {
  napi_value arr, v; napi_create_array(env, &arr);
  uint32_t i = 0;
  napi_create_string_utf8(env, "hello world", 5, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, "hello world", NAPI_AUTO_LENGTH, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, "caf\xc3\xa9 \xe2\x82\xac \xf0\x9f\x98\x80", NAPI_AUTO_LENGTH, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, "bad\xff\xfe!", NAPI_AUTO_LENGTH, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, NULL, 0, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, "", NAPI_AUTO_LENGTH, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, "a\0b", 3, &v); napi_set_element(env, arr, i++, v);
  napi_create_string_utf8(env, "abcdef", 0, &v); napi_set_element(env, arr, i++, v);
  return arr;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "makeStrings", make_strings);
  return exports;
}
""")
    code = r"""
const strs = require('./addon.node').makeStrings();
for (const s of strs)
  console.log(typeof s, s.length, JSON.stringify(s), Array.from(s, (c) => c.codePointAt(0).toString(16)).join(' '));
"""
    r = js(code)
    assert out(r) == golden("strings")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------ inspecting values
def test_typeof_and_get_value_bool(js, workdir, golden):
    """CATCHES: napi_typeof mapping null to object, functions/classes/proxies or bigint/symbol to the
    wrong napi_valuetype, or napi_get_value_bool accepting truthy non-booleans instead of status 7."""
    addon(workdir, r"""
static napi_value type_of(napi_env env, napi_callback_info info) {
  int t = -1; napi_status s = napi_typeof(env, arg(env, info, 0), &t);
  return num(env, s * 100 + t);
}
static napi_value get_bool(napi_env env, napi_callback_info info) {
  bool d = true; napi_status s = napi_get_value_bool(env, arg(env, info, 0), &d);
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "status", num(env, s));
  napi_set_named_property(env, o, "value", boolean(env, d));
  return o;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "typeOf", type_of);
  export_fn(env, exports, "getBool", get_bool);
  return exports;
}
""")
    code = SHOW_JS + r"""
const a = require('./addon.node');
const vals = [undefined, null, true, 0, NaN, 'x', '', Symbol('s'), {}, [], () => 1, function f() {}, 5n,
  new Date(0), /r/, class K {}, Object(1), new Proxy({}, {}), new Proxy(function () {}, {}), Math.max];
console.log(vals.map((v) => a.typeOf(v)).join(','));
console.log('no argument:', a.typeOf());
for (const v of [true, false, 0, 1, 'true', null, undefined, {}])
  console.log('bool', show(v), show(a.getBool(v)));
"""
    r = js(code)
    assert out(r) == golden("typeof_bool")
    assert (r.returncode, r.stderr) == (0, b"")


def test_number_extraction_status_and_int32_wrapping(js, workdir, golden):
    """CATCHES: napi_get_value_double/int32/uint32 that coerce non-numbers instead of returning
    napi_number_expected (6), clamp or saturate instead of ToInt32 modular wrapping, or mishandle NaN."""
    addon(workdir, r"""
#define GETTER(NAME, CTYPE, FN, INIT) \
static napi_value NAME(napi_env env, napi_callback_info info) { \
  CTYPE d = INIT; napi_status s = FN(env, arg(env, info, 0), &d); \
  napi_value o; napi_create_object(env, &o); \
  napi_set_named_property(env, o, "status", num(env, s)); \
  napi_set_named_property(env, o, "value", num(env, (double)d)); \
  return o; \
}
GETTER(get_double, double, napi_get_value_double, -1.0)
GETTER(get_int32, int32_t, napi_get_value_int32, -7)
GETTER(get_uint32, uint32_t, napi_get_value_uint32, 7)
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "getDouble", get_double);
  export_fn(env, exports, "getInt32", get_int32);
  export_fn(env, exports, "getUint32", get_uint32);
  return exports;
}
""")
    code = SHOW_JS + r"""
const a = require('./addon.node');
const label = (v) => typeof v === 'string' ? JSON.stringify(v) : typeof v === 'bigint' ? v + 'n' : Object.is(v, -0) ? '-0'
  : typeof v === 'object' && v !== null ? 'object:' + String(v) : String(v);
const fmt = (r) => `status=${r.status} value=${Object.is(r.value, -0) ? '-0' : r.value}`;
for (const v of [3.75, -0, NaN, Infinity, -1e-300, '12', true, null, undefined, {}, 10n, new Number(4)])
  console.log('double', label(v), fmt(a.getDouble(v)));
for (const v of [42.9, -42.9, -1, 2147483647, 2147483648, 4294967297, -2147483649, 1e20, -0.5, Infinity, -Infinity, NaN, '5', false])
  console.log('int32', label(v), fmt(a.getInt32(v)));
for (const v of [-1, 3.99, 4294967295, 4294967296, 4294967301, -4294967297, NaN, '5', null])
  console.log('uint32', label(v), fmt(a.getUint32(v)));
"""
    r = js(code)
    assert out(r) == golden("numbers")
    assert (r.returncode, r.stderr) == (0, b"")


STRING_PROBE_C = r"""
static napi_value probe(napi_env env, napi_callback_info info) {
  napi_value v = arg(env, info, 0);
  uint32_t cap = arg_u32(env, info, 1);
  napi_value o; napi_create_object(env, &o);
  size_t len = 12345;
  napi_status s = napi_get_value_string_utf8(env, v, NULL, 0, &len);
  napi_set_named_property(env, o, "measureStatus", num(env, s));
  napi_set_named_property(env, o, "measured", num(env, (double)len));
  if (s != 0) {
    bool pending = false; napi_is_exception_pending(env, &pending);
    napi_set_named_property(env, o, "pending", boolean(env, pending));
    napi_value e; napi_get_and_clear_last_exception(env, &e);
    napi_set_named_property(env, o, "error", e);
    return o;
  }
  char buf[64]; memset(buf, 'Z', sizeof buf);
  size_t copied = 999;
  s = napi_get_value_string_utf8(env, v, buf, cap, &copied);
  napi_set_named_property(env, o, "copyStatus", num(env, s));
  napi_set_named_property(env, o, "copied", num(env, (double)copied));
  if (cap > 0) {
    napi_set_named_property(env, o, "text", str(env, buf));
    napi_set_named_property(env, o, "nulAt", num(env, (double)strlen(buf)));
  } else {
    char t[2] = {buf[0], 0};
    napi_set_named_property(env, o, "untouched", str(env, t));
  }
  s = napi_get_value_string_utf8(env, v, buf, sizeof buf, NULL);
  napi_set_named_property(env, o, "noResultPtrStatus", num(env, s));
  s = napi_get_value_string_utf8(env, v, NULL, 0, NULL);
  napi_set_named_property(env, o, "measureNoResultStatus", num(env, s));
  return o;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "probe", probe);
  return exports;
}
"""


def test_get_value_string_utf8_measure_copy_and_truncate(js, workdir, golden):
    """CATCHES: napi_get_value_string_utf8 that reports UTF-16 units instead of UTF-8 bytes in
    measurement mode, overruns or forgets the NUL when truncating, or writes into a zero-size buffer."""
    addon(workdir, STRING_PROBE_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
console.log(show(a.probe('hello', 64)));
console.log(show(a.probe('hello', 6)));
console.log(show(a.probe('hello', 5)));
console.log(show(a.probe('hello', 3)));
console.log(show(a.probe('hello', 1)));
console.log(show(a.probe('hello', 0)));
console.log(show(a.probe('héllo€', 64)));
console.log(show(a.probe('😀!', 64)));
console.log(show(a.probe('', 64)));
"""
    r = js(code)
    assert out(r) == golden("string_utf8")
    assert (r.returncode, r.stderr) == (0, b"")


def test_get_value_string_utf8_converts_via_tostring(js, workdir, golden):
    """CATCHES: string extraction that does not run JS ToString for non-strings, or swallows an
    exception thrown by toString instead of returning napi_pending_exception (10) with it pending."""
    addon(workdir, STRING_PROBE_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
console.log(show(a.probe(12.5, 64)));
console.log(show(a.probe(null, 64)));
console.log(show(a.probe([1, [2, 3]], 64)));
console.log(show(a.probe({ toString() { return 'custom'; } }, 64)));
console.log(show(a.probe({ toString() { throw new RangeError('toString refused'); } }, 64)));
console.log(show(a.probe(Symbol('q'), 64)));
"""
    r = js(code)
    assert out(r) == golden("string_coerce")
    assert (r.returncode, r.stderr) == (0, b"")


def test_coerce_to_string(js, workdir, golden):
    """CATCHES: napi_coerce_to_string that skips user toString/valueOf, formats numbers differently
    from String(), or fails to leave a pending exception (status 10) that reaches JS for Symbols."""
    addon(workdir, r"""
static napi_value coerce(napi_env env, napi_callback_info info) {
  napi_value r = NULL; napi_status s = napi_coerce_to_string(env, arg(env, info, 0), &r);
  napi_value o = report(env, s);
  if (s == 0) napi_set_named_property(env, o, "result", r);
  return o;
}
static napi_value coerce_leave(napi_env env, napi_callback_info info) {
  napi_value r = NULL; napi_status s = napi_coerce_to_string(env, arg(env, info, 0), &r);
  return s == 0 ? r : num(env, s);  /* on failure the exception stays pending and wins */
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "coerce", coerce);
  export_fn(env, exports, "coerceLeave", coerce_leave);
  return exports;
}
""")
    code = SHOW_JS + r"""
const a = require('./addon.node');
for (const v of [1.5, -0, 1e21, 0.000001, true, null, undefined, [1, [2, 3]], { a: 1 }, 10n, 'same',
  { toString() { return 'obj!'; } }, { valueOf() { return 1; }, toString() { return 'ts wins'; } }])
  console.log(show(a.coerce(v)));
console.log(show(a.coerce(Symbol('sym'))));
console.log(a.coerceLeave(255));
try { a.coerceLeave(Symbol('x')); console.log('no throw'); } catch (e) { console.log('caught', e.name, e.message); }
try { a.coerceLeave({ toString() { throw new Error('from toString'); } }); } catch (e) { console.log('caught', e.name, e.message); }
"""
    r = js(code)
    assert out(r) == golden("coerce")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------- properties
PROPS_C = r"""
static void name_of(napi_env env, napi_callback_info info, size_t i, char *name, size_t cap) {
  size_t n; napi_get_value_string_utf8(env, arg(env, info, i), name, cap, &n);
}
static napi_value get_named(napi_env env, napi_callback_info info) {
  char name[64]; name_of(env, info, 1, name, sizeof name);
  napi_value r = NULL; napi_status s = napi_get_named_property(env, arg(env, info, 0), name, &r);
  napi_value o = report(env, s); if (s == 0) napi_set_named_property(env, o, "value", r);
  return o;
}
static napi_value set_named(napi_env env, napi_callback_info info) {
  char name[64]; name_of(env, info, 1, name, sizeof name);
  return report(env, napi_set_named_property(env, arg(env, info, 0), name, arg(env, info, 2)));
}
static napi_value has_named(napi_env env, napi_callback_info info) {
  char name[64]; name_of(env, info, 1, name, sizeof name);
  bool b = false; napi_status s = napi_has_named_property(env, arg(env, info, 0), name, &b);
  napi_value o = report(env, s); napi_set_named_property(env, o, "value", boolean(env, b));
  return o;
}
static napi_value get_prop(napi_env env, napi_callback_info info) {
  napi_value r = NULL; napi_status s = napi_get_property(env, arg(env, info, 0), arg(env, info, 1), &r);
  napi_value o = report(env, s); if (s == 0) napi_set_named_property(env, o, "value", r);
  return o;
}
static napi_value set_prop(napi_env env, napi_callback_info info) {
  return report(env, napi_set_property(env, arg(env, info, 0), arg(env, info, 1), arg(env, info, 2)));
}
static napi_value get_el(napi_env env, napi_callback_info info) {
  napi_value r = NULL; napi_status s = napi_get_element(env, arg(env, info, 0), arg_u32(env, info, 1), &r);
  napi_value o = report(env, s); if (s == 0) napi_set_named_property(env, o, "value", r);
  return o;
}
static napi_value set_el(napi_env env, napi_callback_info info) {
  return report(env, napi_set_element(env, arg(env, info, 0), arg_u32(env, info, 1), arg(env, info, 2)));
}
static napi_value mk_arrays(napi_env env, napi_callback_info info) {
  napi_value o, a, b, c; napi_create_object(env, &o);
  napi_create_array(env, &a);
  napi_create_array_with_length(env, 3, &b);
  napi_create_array_with_length(env, 0, &c);
  napi_set_element(env, a, 2, str(env, "two"));
  napi_set_element(env, b, 1, num(env, 1));
  napi_set_named_property(env, o, "a", a);
  napi_set_named_property(env, o, "b", b);
  napi_set_named_property(env, o, "c", c);
  return o;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "getNamed", get_named);
  export_fn(env, exports, "setNamed", set_named);
  export_fn(env, exports, "hasNamed", has_named);
  export_fn(env, exports, "getProp", get_prop);
  export_fn(env, exports, "setProp", set_prop);
  export_fn(env, exports, "getEl", get_el);
  export_fn(env, exports, "setEl", set_el);
  export_fn(env, exports, "mkArrays", mk_arrays);
  return exports;
}
"""


def test_named_properties_get_set_has(js, workdir, golden):
    """CATCHES: named property access that ignores the prototype chain, primitives' wrapper properties,
    getters/setters, or reports a throwing accessor as success instead of status 10 with the error."""
    addon(workdir, PROPS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
const log = [];
const o = { x: 1, get boom() { throw new TypeError('getter boom'); }, set trap(v) { throw new RangeError('setter ' + v); },
  get computed() { log.push('getter ran'); return this.x * 10; }, set store(v) { log.push('setter got ' + v); this._s = v; } };
const child = Object.create({ inherited: 'from proto' });
console.log('get own', show(a.getNamed(o, 'x')));
console.log('get missing', show(a.getNamed(o, 'missing')));
console.log('get inherited', show(a.getNamed(child, 'inherited')));
console.log('get getter', show(a.getNamed(o, 'computed')));
console.log('get throwing', show(a.getNamed(o, 'boom')));
console.log('get primitive', show(a.getNamed('four', 'length')), show(a.getNamed(5, 'toFixed')));
console.log('has', show(a.hasNamed(o, 'x')), show(a.hasNamed(o, 'nope')), show(a.hasNamed(child, 'inherited')), show(a.hasNamed([], 'length')));
console.log('set new', show(a.setNamed(o, 'y', 22)), o.y);
console.log('set overwrite', show(a.setNamed(o, 'x', 'changed')), o.x);
console.log('set setter', show(a.setNamed(o, 'store', [1, 2])), JSON.stringify(o._s));
console.log('set throwing', show(a.setNamed(o, 'trap', 5)));
console.log('utf8 name', show(a.setNamed(o, 'clé', 'v')), JSON.stringify(Object.keys(o).filter((k) => k.length === 3)));
console.log(log.join('; '));
"""
    r = js(code)
    assert out(r) == golden("named_props")
    assert (r.returncode, r.stderr) == (0, b"")


def test_keyed_properties_coerce_keys(js, workdir, golden):
    """CATCHES: napi_get_property/napi_set_property that do not apply ToPropertyKey to number, null
    and object keys, or that ignore a key whose toString throws instead of returning status 10."""
    addon(workdir, PROPS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
const o = { x: 1, '1.5': 'float key', null: 'null key', '7': 'seven', get boom() { throw new Error('keyed getter'); },
  set trap(v) { throw new RangeError('keyed setter ' + v); } };
console.log(show(a.getProp(o, 'x')), show(a.getProp([10, 20], 1)), show(a.getProp(o, 1.5)), show(a.getProp(o, null)), show(a.getProp(o, 7)));
console.log(show(a.getProp(o, { toString() { return 'x'; } })));
console.log(show(a.getProp(o, { toString() { throw new Error('bad key'); } })));
console.log(show(a.getProp(o, 'boom')));
const t = {};
console.log(show(a.setProp(t, 7, 'seven')), show(a.setProp(t, 'k', 'v')), show(a.setProp(t, true, 'yes')), JSON.stringify(t));
console.log(show(a.setProp(t, { toString() { throw new Error('bad key 2'); } }, 1)), JSON.stringify(t));
console.log(show(a.setProp(o, 'trap', 9)));
"""
    r = js(code)
    assert out(r) == golden("keyed_props")
    assert (r.returncode, r.stderr) == (0, b"")


def test_elements_and_array_creation(js, workdir, golden):
    """CATCHES: napi_set_element/napi_get_element that do not grow arrays, use the wrong index, skip
    index accessors, or napi_create_array_with_length producing an array of the wrong length."""
    addon(workdir, PROPS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
const arr = [1, 2];
console.log(show(a.setEl(arr, 4, 'e')), arr.length, JSON.stringify(arr));
console.log(show(a.setEl(arr, 0, 'first')), JSON.stringify(arr));
console.log(show(a.getEl(arr, 1)), show(a.getEl(arr, 3)), show(a.getEl(arr, 99)));
console.log(show(a.getEl('abc', 2)), show(a.getEl({ 5: 'five' }, 5)), show(a.getEl(new Uint8Array([9, 8]), 1)));
const bad = [];
Object.defineProperty(bad, '0', { get() { throw new Error('element getter'); }, set(v) { throw new Error('element setter ' + v); } });
console.log(show(a.getEl(bad, 0)), show(a.setEl(bad, 0, 3)));
const m = a.mkArrays();
console.log(Array.isArray(m.a), m.a.length, JSON.stringify(m.a));
console.log(Array.isArray(m.b), m.b.length, JSON.stringify(m.b), m.b[1]);
console.log(Array.isArray(m.c), m.c.length, JSON.stringify(m.c));
m.b.push('pushed'); console.log(m.b.length, m.b[3]);
"""
    r = js(code)
    assert out(r) == golden("elements")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------- functions and callbacks
FUNCS_C = r"""
static int tag_a = 1, tag_b = 2;
static napi_value describe(napi_env env, napi_callback_info info) {
  size_t argc = 3; napi_value argv[3] = {NULL, NULL, NULL}; napi_value self = NULL; void *data = (void *)&tag_b;
  napi_get_cb_info(env, info, &argc, argv, &self, &data);
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "argc", num(env, (double)argc));
  napi_value list; napi_create_array(env, &list);
  for (uint32_t i = 0; i < 3; i++) napi_set_element(env, list, i, argv[i]);
  napi_set_named_property(env, o, "argv", list);
  napi_set_named_property(env, o, "this", self);
  napi_set_named_property(env, o, "data", num(env, data == NULL ? 0 : *(int *)data));
  return o;
}
static napi_value count_only(napi_env env, napi_callback_info info) {
  size_t argc = 0;
  napi_get_cb_info(env, info, &argc, NULL, NULL, NULL);
  napi_value self; napi_get_cb_info(env, info, NULL, NULL, &self, NULL);
  bool same = false; napi_strict_equals(env, self, arg(env, info, 0), &same);
  return num(env, (double)argc + (same ? 0.5 : 0));
}
static napi_value call_it(napi_env env, napi_callback_info info) {
  size_t argc = 8; napi_value argv[8]; napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  napi_value r = NULL;
  napi_status s = napi_call_function(env, argv[1], argv[0], argc - 2, argv + 2, &r);
  if (s != 0) return str(env, "this return value is discarded");  /* the exception stays pending */
  return r;
}
static napi_value call_catch(napi_env env, napi_callback_info info) {
  size_t argc = 2; napi_value argv[2]; napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  napi_value r = NULL, undef; napi_get_undefined(env, &undef);
  bool before = true, after = false, cleared = true;
  napi_is_exception_pending(env, &before);
  napi_status s = napi_call_function(env, undef, argv[0], 1, &argv[1], &r);
  napi_is_exception_pending(env, &after);
  napi_value e; napi_get_and_clear_last_exception(env, &e);
  napi_is_exception_pending(env, &cleared);
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "status", num(env, s));
  napi_set_named_property(env, o, "pendingBefore", boolean(env, before));
  napi_set_named_property(env, o, "pendingAfter", boolean(env, after));
  napi_set_named_property(env, o, "pendingAfterClear", boolean(env, cleared));
  napi_set_named_property(env, o, "exception", e);
  if (s == 0) napi_set_named_property(env, o, "result", r);
  return o;
}
static napi_value call_noresult(napi_env env, napi_callback_info info) {
  napi_value fn = arg(env, info, 0), g; napi_get_global(env, &g);
  napi_status s = napi_call_function(env, g, fn, 0, NULL, NULL);
  return num(env, s);
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  napi_value fn;
  napi_create_function(env, "describeA", NAPI_AUTO_LENGTH, describe, &tag_a, &fn);
  napi_set_named_property(env, exports, "describeA", fn);
  napi_create_function(env, "describeBxyz", 9, describe, &tag_b, &fn);
  napi_set_named_property(env, exports, "describeB", fn);
  napi_create_function(env, NULL, 0, describe, NULL, &fn);
  napi_set_named_property(env, exports, "anon", fn);
  napi_create_function(env, "noCallback", NAPI_AUTO_LENGTH, NULL, NULL, &fn);
  napi_set_named_property(env, exports, "noCallback", fn);
  export_fn(env, exports, "countOnly", count_only);
  export_fn(env, exports, "callIt", call_it);
  export_fn(env, exports, "callCatch", call_catch);
  export_fn(env, exports, "callNoResult", call_noresult);
  return exports;
}
"""


def test_function_names_and_data_pointers(js, workdir, golden):
    """CATCHES: napi_create_function that ignores the explicit name length, mixes up per-function data
    pointers between functions sharing one C callback, or a NULL callback that crashes when called."""
    addon(workdir, FUNCS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
console.log(JSON.stringify([a.describeA.name, a.describeB.name, a.anon.name, a.noCallback.name]));
console.log(typeof a.describeA, a.describeA.length, a.describeA instanceof Function, a.describeA !== a.describeB);
console.log('A data', a.describeA().data, 'B data', a.describeB().data, 'anon data', a.anon().data);
console.log('noCallback', show(a.noCallback(1, 2)));
console.log(String(a.describeA.call.call(a.describeB, null).data));
"""
    r = js(code)
    assert out(r) == golden("function_names")
    assert (r.returncode, r.stderr) == (0, b"")


def test_get_cb_info_args_and_receiver(js, workdir, golden):
    """CATCHES: napi_get_cb_info that reports the buffer capacity instead of the real argument count,
    leaves unused argv slots unset rather than undefined, or passes the wrong `this` receiver."""
    addon(workdir, FUNCS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
const strip = (r) => ({ ...r, this: r.this === a ? '<exports>' : r.this });
console.log(show(strip(a.describeA(1, 'two'))));
console.log(show(strip(a.describeA(1, 2, 3, 4, 5))));
console.log(show(strip(a.describeA())));
console.log(show(strip(a.describeB.call({ me: 1 }, null))));
const holder = { m: a.describeA, tag: 'holder' };
console.log(show(strip(holder.m('x', undefined))));
console.log(show(strip(a.describeA.apply({ applied: true }, [[1], { k: 2 }, 'z', 'dropped']))));
console.log(show(strip(Reflect.apply(a.anon, { r: 1 }, [false]))));
const recv = { name: 'recv' };
console.log(a.countOnly.call(recv, recv), a.countOnly.call(recv, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10), a.countOnly());
"""
    r = js(code)
    assert out(r) == golden("cb_info")
    assert (r.returncode, r.stderr) == (0, b"")


def test_call_function_from_native(js, workdir, golden):
    """CATCHES: napi_call_function that drops the receiver or arguments, mis-orders them, cannot call
    builtins or other native functions, or breaks when re-entering native code from the JS callee."""
    addon(workdir, FUNCS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
function add(x, y) { return [this && this.k, x + y, arguments.length]; }
console.log(show(a.callIt(add, { k: 'recv' }, 2, 3)));
console.log(show(a.callIt(add, null, 'a', 'b', 'c')));
console.log(a.callIt(Math.max, null, 4, 9, 2), a.callIt(Math.max, null));
console.log(show(a.callIt(String.prototype.toUpperCase, 'shout')));
console.log(show(a.callIt(a.describeA, { via: 'native' }, 7).argv), a.callIt(a.describeA, { via: 'native' }, 7).this.via);
console.log(a.callIt(function () { return a.callIt((p) => p + '!', null, 'nested'); }, null));
console.log(a.callIt((...xs) => xs.reverse().join('<'), null, 1, 2, 3, 4, 5, 6));
console.log('no result slot:', a.callNoResult(function () { globalThis.sawGlobal = this === globalThis; return 1; }), globalThis.sawGlobal);
"""
    r = js(code)
    assert out(r) == golden("call_function")
    assert (r.returncode, r.stderr) == (0, b"")


def test_call_function_exceptions(js, workdir, golden):
    """CATCHES: exceptions from a JS callee that are not reported as napi_pending_exception, lose
    object identity on the way back through native code, or are not cleared by get_and_clear."""
    addon(workdir, FUNCS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
try { a.callIt(() => { throw new SyntaxError('inner'); }, null); console.log('no throw'); } catch (e) { console.log('propagated', e.name, e.message); }
const errObj = new Error('identity');
try { a.callIt(() => { throw errObj; }, null); } catch (e) { console.log('same object', e === errObj); }
try { a.callIt(() => { throw 'plain string'; }, null); } catch (e) { console.log('thrown value', typeof e, e); }
console.log(show(a.callCatch((v) => { throw new TypeError('bad ' + v); }, 'input')));
console.log(show(a.callCatch((v) => v * 2, 21)));
console.log(show(a.callCatch(42, 1)));
console.log(show(a.callCatch(undefined, 1)));
console.log('after all: still running');
"""
    r = js(code)
    assert out(r) == golden("call_exceptions")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------- errors / exceptions
ERRORS_C = r"""
static napi_value thrower(napi_env env, napi_callback_info info) {
  char kind[16]; size_t n; napi_get_value_string_utf8(env, arg(env, info, 0), kind, sizeof kind, &n);
  if (!strcmp(kind, "error")) napi_throw_error(env, "ERR_CODE", "plain failure");
  else if (!strcmp(kind, "type")) napi_throw_type_error(env, NULL, "wrong type");
  else if (!strcmp(kind, "range")) napi_throw_range_error(env, "E_RANGE", "out of range");
  else if (!strcmp(kind, "value")) napi_throw(env, arg(env, info, 1));
  else if (!strcmp(kind, "created")) {
    napi_value e; napi_create_error(env, NULL, arg(env, info, 1), &e);
    napi_throw(env, e);
  } else if (!strcmp(kind, "nullmsg")) napi_throw_error(env, NULL, NULL);
  else if (!strcmp(kind, "utf8")) napi_throw_error(env, NULL, "\xc3\xa9" "chec \xe2\x9c\x97");
  else if (!strcmp(kind, "cleared")) {
    napi_throw_error(env, NULL, "swallowed");
    napi_value e; napi_get_and_clear_last_exception(env, &e);
    return e;
  }
  return str(env, "returned normally");  /* discarded whenever an exception is pending */
}
static napi_value statuses(napi_env env, napi_callback_info info) {
  bool p0, p1, p2, p3;
  napi_is_exception_pending(env, &p0);
  napi_status s1 = napi_throw_error(env, NULL, "x");
  napi_is_exception_pending(env, &p1);
  napi_value e; napi_status s2 = napi_get_and_clear_last_exception(env, &e);
  napi_is_exception_pending(env, &p2);
  napi_value empty; napi_status s3 = napi_get_and_clear_last_exception(env, &empty);
  int t = -1; napi_typeof(env, empty, &t);
  napi_status s4 = napi_throw(env, e);
  napi_is_exception_pending(env, &p3);
  napi_value again; napi_get_and_clear_last_exception(env, &again);
  bool same = false; napi_strict_equals(env, e, again, &same);
  char buf[96];
  snprintf(buf, sizeof buf, "pending %d%d%d%d status %d%d%d%d empty-typeof %d rethrown-same %d",
           p0, p1, p2, p3, s1, s2, s3, s4, t, same);
  return str(env, buf);
}
static napi_value make_error(napi_env env, napi_callback_info info) {
  napi_value e = NULL; napi_status s = napi_create_error(env, arg(env, info, 0), arg(env, info, 1), &e);
  bool is = false; napi_is_error(env, e, &is);
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "status", num(env, s));
  napi_set_named_property(env, o, "isError", boolean(env, is));
  napi_set_named_property(env, o, "error", e);
  return o;
}
static napi_value is_error(napi_env env, napi_callback_info info) {
  bool is = false; napi_status s = napi_is_error(env, arg(env, info, 0), &is);
  return num(env, s * 10 + is);
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "thrower", thrower);
  export_fn(env, exports, "statuses", statuses);
  export_fn(env, exports, "makeError", make_error);
  export_fn(env, exports, "isError", is_error);
  return exports;
}
"""


def test_throw_family_creates_matching_error_types(js, workdir, golden):
    """CATCHES: napi_throw_error/type_error/range_error that throw the wrong constructor or prototype,
    garble UTF-8 messages, wrap napi_throw's non-Error values, or let the C return value win."""
    addon(workdir, ERRORS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
const describe = (e) => e instanceof Error
  ? `${e.constructor.name}(${JSON.stringify(e.message)}) proto-ok=${Object.getPrototypeOf(e) === globalThis[e.name].prototype} native-is-error=${a.isError(e)}`
  : `${typeof e} ${show(e)}`;
const cases = [['error'], ['type'], ['range'], ['nullmsg'], ['utf8'], ['value', 42], ['value', { custom: true }],
  ['value', 'str'], ['value', undefined], ['value', new URIError('prebuilt')], ['created', 'made by napi_create_error'],
  ['created', 99], ['cleared'], ['none']];
for (const [k, v] of cases) {
  try { console.log(k, 'returned', describe(a.thrower(k, v))); } catch (e) { console.log(k, 'threw', describe(e)); }
}
"""
    r = js(code)
    assert out(r) == golden("throw_family")
    assert (r.returncode, r.stderr) == (0, b"")


def test_exception_pending_state_machine(js, workdir):
    """CATCHES: napi_is_exception_pending not tracking throws, get_and_clear not clearing (or not
    returning undefined when nothing is pending), or napi_throw not re-raising the very same object."""
    addon(workdir, ERRORS_C)
    r = js("console.log(require('./addon.node').statuses());\n")
    assert out(r) == "pending 0101 status 0000 empty-typeof 0 rethrown-same 1\n"
    assert (r.returncode, r.stderr) == (0, b"")


def test_create_error_and_is_error(js, workdir, golden):
    """CATCHES: napi_create_error that throws instead of returning the error, ignores the message
    value, or napi_is_error that is fooled by error-shaped plain objects or misses Error subclasses."""
    addon(workdir, ERRORS_C)
    code = SHOW_JS + r"""
const a = require('./addon.node');
const m = a.makeError('ECODE', 'msg here');
console.log(m.status, m.isError, m.error instanceof Error, m.error.name, JSON.stringify(m.error.message), typeof m.error.stack);
const m2 = a.makeError(undefined, 'second');
console.log(m2.status, m2.isError, m2.error.message, m.error !== m2.error);
class MyErr extends TypeError {}
const vals = [new Error('e'), new MyErr('m'), new RangeError('r'), new AggregateError([]), Object.create(Error.prototype),
  { message: 'fake', name: 'Error', stack: '' }, 'Error', null, undefined, 0, Error];
console.log(vals.map(a.isError).join(','));
"""
    r = js(code)
    assert out(r) == golden("create_error")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("call,expected", [
    pytest.param("a.thrower('type')", "Uncaught TypeError: wrong type\n", id="type_error"),
    pytest.param("a.thrower('range')", "Uncaught RangeError: out of range\n", id="range_error"),
    pytest.param("a.thrower('value', 42)", "Uncaught 42\n", id="thrown_number"),
])
def test_uncaught_native_exception_terminates(js, workdir, call, expected):
    """CATCHES: a pending native exception that is ignored when nobody catches it (program continues,
    exit 0), or that is reported with the wrong error name/message instead of `Uncaught ...`."""
    addon(workdir, ERRORS_C)
    r = js(f"const a = require('./addon.node');\nconsole.log('before');\n{call};\nconsole.log('not reached');\n")
    assert out(r) == "before\n"
    assert (r.returncode, err(r)) == (1, expected)


# -------------------------------------------------------------------------------- misc env helpers
def test_handle_scopes_version_strict_equals_prototype(js, workdir, golden):
    """CATCHES: handle scopes that invalidate values or return NULL tokens, a wrong napi_get_version,
    napi_strict_equals using == or SameValue (NaN/-0), or napi_get_prototype not following [[Prototype]]."""
    addon(workdir, r"""
static napi_value version(napi_env env, napi_callback_info info) {
  uint32_t v = 0; napi_status s = napi_get_version(env, &v);
  return num(env, s * 100 + v);
}
static napi_value seq(napi_env env, napi_callback_info info) {
  bool r = false; napi_status s = napi_strict_equals(env, arg(env, info, 0), arg(env, info, 1), &r);
  return num(env, s * 10 + r);
}
static napi_value proto(napi_env env, napi_callback_info info) {
  napi_value p = NULL; napi_status s = napi_get_prototype(env, arg(env, info, 0), &p);
  return s ? num(env, -s) : p;
}
static napi_value scopes(napi_env env, napi_callback_info info) {
  napi_handle_scope outer = NULL, inner = NULL;
  napi_status a = napi_open_handle_scope(env, &outer);
  napi_status b = napi_open_handle_scope(env, &inner);
  napi_value made = str(env, "made inside nested scopes");
  napi_status c = napi_close_handle_scope(env, inner);
  napi_status d = napi_close_handle_scope(env, outer);
  napi_status e = napi_open_handle_scope(env, NULL);
  napi_value o; napi_create_object(env, &o);
  char buf[64]; snprintf(buf, sizeof buf, "%d %d %d %d %d tokens-non-null=%d", a, b, c, d, e, outer != NULL && inner != NULL);
  napi_set_named_property(env, o, "statuses", str(env, buf));
  napi_set_named_property(env, o, "value", made);
  return o;
}
static napi_value global_check(napi_env env, napi_callback_info info) {
  napi_value g, g2, v; napi_get_global(env, &g); napi_get_global(env, &g2);
  bool same = false; napi_strict_equals(env, g, g2, &same);
  napi_get_named_property(env, g, "fromJs", &v);
  napi_set_named_property(env, g, "fromC", str(env, "set on global by C"));
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "fromJs", v);
  napi_set_named_property(env, o, "same", boolean(env, same));
  return o;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "version", version);
  export_fn(env, exports, "seq", seq);
  export_fn(env, exports, "proto", proto);
  export_fn(env, exports, "scopes", scopes);
  export_fn(env, exports, "globalCheck", global_check);
  return exports;
}
""")
    code = r"""
const a = require('./addon.node');
console.log('version', a.version());
console.log('scopes', JSON.stringify(a.scopes()));
const o = {}, s = Symbol('s');
const pairs = [[1, 1], [1, '1'], [NaN, NaN], [0, -0], ['ab', 'a' + 'b'], [o, o], [o, {}], [null, undefined],
  [undefined, undefined], [null, null], [s, s], [s, Symbol('s')], [10n, 10n], [true, 1], [a.seq, a.seq]];
console.log('strict', pairs.map(([x, y]) => a.seq(x, y)).join(','));
class K {}
console.log('proto', a.proto([]) === Array.prototype, a.proto(Object.create(null)), a.proto(new K()) === K.prototype,
  a.proto(function () {}) === Function.prototype, a.proto(Object.create(o)) === o, a.proto(async () => {}).constructor.name);
globalThis.fromJs = 'js value';
console.log('global', JSON.stringify(a.globalCheck()), globalThis.fromC, typeof fromC);
"""
    r = js(code)
    assert out(r) == golden("misc_env")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------- references
def test_references_persist_values_and_count(js, workdir, golden):
    """CATCHES: references that do not keep their value across native calls, wrong ref/unref counts,
    napi_delete_reference leaving the value reachable (or crashing on a stale handle), or freed slots
    that are not reused for new references."""
    addon(workdir, r"""
static napi_ref saved[8];
static napi_ref listener;
static napi_value keep(napi_env env, napi_callback_info info) {
  uint32_t slot = arg_u32(env, info, 0);
  return num(env, napi_create_reference(env, arg(env, info, 1), arg_u32(env, info, 2), &saved[slot]));
}
static napi_value fetch(napi_env env, napi_callback_info info) {
  napi_value v = NULL; napi_status s = napi_get_reference_value(env, saved[arg_u32(env, info, 0)], &v);
  return s ? num(env, -s) : v;
}
static napi_value bump(napi_env env, napi_callback_info info) {
  uint32_t slot = arg_u32(env, info, 0), up = arg_u32(env, info, 1);
  uint32_t c = 777;
  napi_status s = up ? napi_reference_ref(env, saved[slot], &c) : napi_reference_unref(env, saved[slot], &c);
  return num(env, s * 1000 + c);
}
static napi_value bump_quiet(napi_env env, napi_callback_info info) {
  uint32_t slot = arg_u32(env, info, 0);
  napi_status a = napi_reference_ref(env, saved[slot], NULL);
  napi_status b = napi_reference_unref(env, saved[slot], NULL);
  return num(env, a * 10 + b);
}
static napi_value drop(napi_env env, napi_callback_info info) {
  return num(env, napi_delete_reference(env, saved[arg_u32(env, info, 0)]));
}
static napi_value on(napi_env env, napi_callback_info info) {
  if (listener) napi_delete_reference(env, listener);
  return num(env, napi_create_reference(env, arg(env, info, 0), 1, &listener));
}
static napi_value emit(napi_env env, napi_callback_info info) {
  napi_value cb, undef, payload = arg(env, info, 0), r;
  napi_get_reference_value(env, listener, &cb);
  napi_get_undefined(env, &undef);
  if (napi_call_function(env, undef, cb, 1, &payload, &r) != 0) return NULL;
  return r;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "keep", keep);
  export_fn(env, exports, "fetch", fetch);
  export_fn(env, exports, "bump", bump);
  export_fn(env, exports, "bumpQuiet", bump_quiet);
  export_fn(env, exports, "drop", drop);
  export_fn(env, exports, "on", on);
  export_fn(env, exports, "emit", emit);
  return exports;
}
""")
    code = r"""
const a = require('./addon.node');
const obj = { name: 'kept object' };
const arr = [1, 2, 3];
console.log('create', a.keep(0, obj, 1), a.keep(1, arr, 1), a.keep(2, () => 'fn result', 2));
console.log('fetch', a.fetch(0) === obj, a.fetch(1) === arr, a.fetch(2)(), a.fetch(0).name);
obj.name = 'mutated after keep';
console.log('live object', a.fetch(0).name);
console.log('ref/unref', a.bump(0, 1), a.bump(0, 1), a.bump(0, 0), a.bump(2, 0), a.bump(2, 1));
console.log('null result ptr', a.bumpQuiet(0), a.bump(0, 0));
console.log('delete', a.drop(1), typeof a.fetch(1), 'stale handle', a.drop(1), a.bump(1, 1), a.bump(1, 0), typeof a.fetch(1));
console.log('reuse', a.keep(3, { name: 'new after delete' }, 1), a.fetch(3).name, a.fetch(0) === obj, a.fetch(2)());
const seen = [];
console.log('listen', a.on((x) => { seen.push(x); return x * 2; }));
console.log('emit', a.emit(1), a.emit(20));
a.on((x) => 'second listener got ' + x);
console.log('emit', a.emit(3), seen.join(','));
"""
    r = js(code)
    assert out(r) == golden("references")
    assert (r.returncode, r.stderr) == (0, b"")


# ------------------------------------------------------------------------------------ object wrap
def test_wrap_unwrap_remove_wrap(js, workdir, golden):
    """CATCHES: napi_wrap keyed by something other than object identity (e.g. shape or prototype),
    napi_unwrap returning another object's pointer, remove_wrap not detaching, or non-objects accepted."""
    addon(workdir, r"""
typedef struct { int id; double total; } Counter;
static Counter counters[4] = {{1, 0}, {2, 0}, {3, 0}, {4, 0}};
static napi_ref wrapped_ref;
static napi_value wrap_it(napi_env env, napi_callback_info info) {
  bool want_ref = false; napi_get_value_bool(env, arg(env, info, 2), &want_ref);
  return num(env, napi_wrap(env, arg(env, info, 0), &counters[arg_u32(env, info, 1)], NULL, NULL,
                            want_ref ? &wrapped_ref : NULL));
}
static napi_value unwrap_it(napi_env env, napi_callback_info info) {
  void *p = (void *)&counters[3]; napi_status s = napi_unwrap(env, arg(env, info, 0), &p);
  if (s != 0) return num(env, -s);
  if (p == NULL) return str(env, "no native data");
  Counter *c = p; c->total += 1;
  char buf[48]; snprintf(buf, sizeof buf, "counter#%d total=%g", c->id, c->total); return str(env, buf);
}
static napi_value remove_it(napi_env env, napi_callback_info info) {
  void *p = (void *)&counters[3]; napi_status s = napi_remove_wrap(env, arg(env, info, 0), &p);
  if (s != 0) return num(env, -s);
  if (p == NULL) return str(env, "nothing removed");
  char buf[48]; snprintf(buf, sizeof buf, "removed counter#%d", ((Counter *)p)->id); return str(env, buf);
}
static napi_value remove_quiet(napi_env env, napi_callback_info info) {
  return num(env, napi_remove_wrap(env, arg(env, info, 0), NULL));
}
static napi_value wrapped(napi_env env, napi_callback_info info) {
  napi_value v; napi_get_reference_value(env, wrapped_ref, &v); return v;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "wrap", wrap_it);
  export_fn(env, exports, "unwrap", unwrap_it);
  export_fn(env, exports, "remove", remove_it);
  export_fn(env, exports, "removeQuiet", remove_quiet);
  export_fn(env, exports, "wrapped", wrapped);
  return exports;
}
""")
    code = r"""
const a = require('./addon.node');
const o1 = { same: 'shape' }, o1twin = { same: 'shape' }, o2 = [], o3 = function () {};
console.log('wrap', a.wrap(o1, 0, false), a.wrap(o2, 1, true), a.wrap(o3, 2, false));
console.log('wrap ref', a.wrapped() === o2);
console.log('unwrap', a.unwrap(o1), '|', a.unwrap(o1), '|', a.unwrap(o2), '|', a.unwrap(o3), '|', a.unwrap(o1twin));
console.log('non-objects', a.wrap(5, 0, false), a.wrap('s', 0, false), a.wrap(undefined, 0, false), a.wrap(null, 0, false),
  a.unwrap(5), a.unwrap(true), a.remove(null), a.removeQuiet(1));
console.log('remove', a.remove(o1), '|', a.unwrap(o1), '|', a.remove(o1));
console.log('rewrap', a.wrap(o1, 2, false), a.unwrap(o1), '|', a.unwrap(o3));
console.log('remove quietly', a.removeQuiet(o3), a.unwrap(o3), '|', a.unwrap(o1));
const derived = Object.create(o2);
console.log('derived', a.unwrap(derived), '|', a.unwrap(o2));
"""
    r = js(code)
    assert out(r) == golden("wrap")
    assert (r.returncode, r.stderr) == (0, b"")


# ----------------------------------------------------------------------------------------- classes
CLASS_C = r"""
typedef struct { double x, y; } Point;
static Point pool[256]; static int used = 0;
static int class_tag = 77;
static double origin_y = 1.25;
static napi_value point_ctor(napi_env env, napi_callback_info info) {
  size_t argc = 2; napi_value argv[2], self; void *data;
  napi_get_cb_info(env, info, &argc, argv, &self, &data);
  if (argc == 1) { napi_throw_type_error(env, NULL, "Point needs 0 or 2 coordinates"); return NULL; }
  if (used == 256) { napi_throw_range_error(env, NULL, "pool exhausted"); return NULL; }
  Point *p = &pool[used++];
  p->x = 0; p->y = 0;
  if (argc >= 2) { napi_get_value_double(env, argv[0], &p->x); napi_get_value_double(env, argv[1], &p->y); }
  napi_wrap(env, self, p, NULL, NULL, NULL);
  napi_set_named_property(env, self, "tag", num(env, *(int *)data));
  return NULL;
}
static Point *self_point(napi_env env, napi_callback_info info, napi_value *argv, size_t cap) {
  napi_value self; size_t argc = cap;
  napi_get_cb_info(env, info, &argc, argv, &self, NULL);
  void *p = NULL; napi_unwrap(env, self, &p);
  if (!p) napi_throw_type_error(env, NULL, "not a Point");
  return p;
}
static napi_value get_x(napi_env env, napi_callback_info info) { Point *p = self_point(env, info, NULL, 0); return p ? num(env, p->x) : NULL; }
static napi_value get_y(napi_env env, napi_callback_info info) { Point *p = self_point(env, info, NULL, 0); return p ? num(env, p->y) : NULL; }
static napi_value set_x(napi_env env, napi_callback_info info) {
  napi_value argv[1]; Point *p = self_point(env, info, argv, 1);
  if (p) napi_get_value_double(env, argv[0], &p->x);
  return NULL;
}
static napi_value set_both(napi_env env, napi_callback_info info) {
  napi_value argv[1]; Point *p = self_point(env, info, argv, 1);
  if (p) { double d = 0; napi_get_value_double(env, argv[0], &d); p->x = d; p->y = d; }
  return NULL;
}
static napi_value to_string(napi_env env, napi_callback_info info) {
  Point *p = self_point(env, info, NULL, 0); if (!p) return NULL;
  char buf[64]; snprintf(buf, sizeof buf, "(%g, %g)", p->x, p->y); return str(env, buf);
}
static napi_value translate(napi_env env, napi_callback_info info) {
  napi_value argv[2]; Point *p = self_point(env, info, argv, 2); if (!p) return NULL;
  double dx = 0, dy = 0; napi_get_value_double(env, argv[0], &dx); napi_get_value_double(env, argv[1], &dy);
  p->x += dx; p->y += dy;
  napi_value self; napi_get_cb_info(env, info, NULL, NULL, &self, NULL); return self;
}
static napi_value origin(napi_env env, napi_callback_info info) {
  napi_value ctor; size_t argc = 0; void *data;
  napi_get_cb_info(env, info, &argc, NULL, &ctor, &data);
  napi_value args[2] = {num(env, 0.5), num(env, *(double *)data)};
  napi_value inst = NULL;
  return napi_new_instance(env, ctor, 2, args, &inst) == 0 ? inst : NULL;
}
static napi_value make_instance(napi_env env, napi_callback_info info) {
  size_t argc = 3; napi_value argv[3]; napi_get_cb_info(env, info, &argc, argv, NULL, NULL);
  napi_value inst = NULL; napi_status s = napi_new_instance(env, argv[0], argc - 1, argv + 1, &inst);
  napi_value o = report(env, s);
  if (s == 0) napi_set_named_property(env, o, "instance", inst);
  return o;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  napi_property_descriptor props[] = {
    {"x", NULL, NULL, get_x, set_x, NULL, napi_enumerable, NULL},
    {"y", NULL, NULL, get_y, NULL, NULL, 0, NULL},
    {"both", NULL, NULL, NULL, set_both, NULL, 0, NULL},
    {"toString", NULL, to_string, NULL, NULL, NULL, 0, NULL},
    {"translate", NULL, translate, NULL, NULL, NULL, 0, NULL},
    {"origin", NULL, origin, NULL, NULL, NULL, napi_static, &origin_y},
    {"VERSION", NULL, NULL, NULL, NULL, num(env, 3), napi_static, NULL},
    {"kind", NULL, NULL, NULL, NULL, str(env, "point"), 0, NULL},
    {NULL, str(env, "namedByValue"), NULL, NULL, NULL, num(env, 11), 0, NULL},
    {"nothingAttached", NULL, NULL, NULL, NULL, NULL, 0, NULL},
  };
  napi_value cls;
  napi_define_class(env, "Point", NAPI_AUTO_LENGTH, point_ctor, &class_tag, sizeof props / sizeof props[0], props, &cls);
  napi_set_named_property(env, exports, "Point", cls);
  export_fn(env, exports, "newInstance", make_instance);
  napi_value plain;
  napi_define_class(env, "PlainXX", 5, NULL, NULL, 0, NULL, &plain);
  napi_set_named_property(env, exports, "Plain", plain);
  return exports;
}
"""


@pytest.mark.parametrize("tier", TIERS)
def test_define_class_instances_methods_and_accessors(js, workdir, golden, tier):
    """CATCHES: napi_define_class whose `new` does not create an instance of the prototype, whose
    methods/accessors land on the wrong object or lose their native `this`, under any execution tier."""
    addon(workdir, CLASS_C)
    code = r"""
const { Point } = require('./addon.node');
const p = new Point(1, 2);
console.log(typeof Point, Point.name, p instanceof Point, Object.getPrototypeOf(p) === Point.prototype, Point.prototype.constructor === Point);
console.log(String(p), p.x, p.y, p.tag, `${p}`);
p.x = 10; p.y = 99;
console.log('after set', String(p), p.y);
p.both = 4;
console.log('setter only', String(p), p.both);
console.log('chain', String(p.translate(1, -1)), p.translate(0, 0) === p);
const dx = Object.getOwnPropertyDescriptor(Point.prototype, 'x');
const dy = Object.getOwnPropertyDescriptor(Point.prototype, 'y');
const db = Object.getOwnPropertyDescriptor(Point.prototype, 'both');
console.log('x accessor', typeof dx.get, typeof dx.set, dx.enumerable, dx.configurable);
console.log('y accessor', typeof dy.get, typeof dy.set, dy.enumerable, 'both accessor', typeof db.get, typeof db.set);
console.log('own keys', JSON.stringify(Object.keys(p)), Object.hasOwn(p, 'x'), 'x' in p);
const q = new Point();
console.log('default', String(q), q.tag);
try { Point.prototype.toString.call({ x: 1 }); console.log('no throw'); } catch (e) { console.log(e.name, e.message); }
try { new Point(5); console.log('no throw'); } catch (e) { console.log(e.name, e.message); }
// Every wrapped instance is kept alive for the whole program, so no object can ever be unwrapped
// through a recycled address.
const alive = [];
let sum = 0;
for (let i = 0; i < 100; i++) { const r = new Point(i, -i); alive.push(r); r.translate(1, 1); sum += r.x + r.y * 2; }
console.log('loop sum', sum, alive.length, String(alive[99]));
"""
    r = js(code, *tier)
    assert out(r) == golden("class_instances")
    assert (r.returncode, r.stderr) == (0, b"")


def test_define_class_static_members_values_and_subclassing(js, workdir, golden):
    """CATCHES: napi_static members attached to the prototype instead of the constructor, value or
    napi_value-named descriptors dropped, a NULL-constructor class failing, or `extends` + super() breaking."""
    addon(workdir, CLASS_C)
    code = r"""
const { Point, Plain } = require('./addon.node');
console.log('static', Point.VERSION, typeof Point.origin, 'origin' in Point.prototype, 'VERSION' in Point.prototype);
const o = Point.origin();
console.log('origin()', String(o), o instanceof Point, o.tag);
const z = new Point(0, 0);
console.log('proto values', Point.prototype.kind, Point.prototype.namedByValue, z.kind, Object.hasOwn(z, 'kind'), 'nothingAttached' in Point.prototype);
console.log('ctor prop desc', JSON.stringify(Object.getOwnPropertyDescriptor(Point, 'prototype'), ['writable', 'enumerable', 'configurable']));
class Sub extends Point {
  constructor() { super(3, 4); this.extra = 'sub'; }
  norm() { return Math.hypot(this.x, this.y); }
  toString() { return 'Sub' + super.toString(); }
}
const s = new Sub();
console.log('subclass', s instanceof Sub, s instanceof Point, String(s), s.norm(), s.extra, s.tag, s.constructor.name);
const pl = new Plain();
console.log('plain', Plain.name, typeof pl, pl instanceof Plain, JSON.stringify(pl), Object.getPrototypeOf(pl) === Plain.prototype);
"""
    r = js(code)
    assert out(r) == golden("class_static")
    assert (r.returncode, r.stderr) == (0, b"")


def test_new_instance_from_native(js, workdir, golden):
    """CATCHES: napi_new_instance that calls instead of constructs, drops arguments, or swallows a
    constructor's exception / a non-constructor TypeError rather than returning status 10 with it."""
    addon(workdir, CLASS_C)
    code = SHOW_JS + r"""
const { Point, newInstance } = require('./addon.node');
const r = newInstance(Point, 7, 8);
console.log(r.status, r.pending, String(r.instance), r.instance instanceof Point);
console.log(show(newInstance(Point, 7)));
const r3 = newInstance(function JsCtor(a, b) { this.a = a; this.b = b; this.isNew = new.target === JsCtor; }, 'js', 2);
console.log(r3.status, JSON.stringify(r3.instance), r3.instance.constructor.name);
class Thrower { constructor() { throw new EvalError('ctor refused'); } }
console.log(show(newInstance(Thrower)));
const dt = newInstance(Date, 0);
console.log(dt.status, dt.instance instanceof Date, dt.instance.toISOString());
const viaMap = newInstance(Map, [[1, 'one']]);
console.log(viaMap.status, viaMap.instance.get(1));
const bad = newInstance(() => 1, 'x');
console.log(bad.status, bad.pending, bad.error.name);
const bad2 = newInstance({}, 'x');
console.log(bad2.status, bad2.pending, bad2.error.name);
"""
    r = js(code)
    assert out(r) == golden("new_instance")
    assert (r.returncode, r.stderr) == (0, b"")


def test_native_constructor_error_is_uncaught(js, workdir):
    """CATCHES: a class constructor whose pending exception is dropped so `new` returns a half-built
    instance, instead of the TypeError escaping as an uncaught error with exit status 1."""
    addon(workdir, CLASS_C)
    r = js("const { Point } = require('./addon.node');\nconsole.log(String(new Point(1, 1)));\nnew Point(1);\nconsole.log('not reached');\n")
    assert out(r) == "(1, 1)\n"
    assert (r.returncode, err(r)) == (1, "Uncaught TypeError: Point needs 0 or 2 coordinates\n")


# ---------------------------------------------------------------------------------------- promises
PROMISE_C = r"""
static napi_deferred slots[4];
static napi_value make(napi_env env, napi_callback_info info) {
  napi_value p; napi_status s = napi_create_promise(env, &slots[arg_u32(env, info, 0)], &p);
  return s ? num(env, s) : p;
}
static napi_value settle(napi_env env, napi_callback_info info) {
  uint32_t slot = arg_u32(env, info, 0);
  bool ok = false; napi_get_value_bool(env, arg(env, info, 1), &ok);
  napi_value v = arg(env, info, 2);
  napi_status s = ok ? napi_resolve_deferred(env, slots[slot], v) : napi_reject_deferred(env, slots[slot], v);
  return num(env, s);
}
static napi_value rejected_now(napi_env env, napi_callback_info info) {
  napi_deferred d; napi_value p;
  napi_create_promise(env, &d, &p);
  napi_value e; napi_create_error(env, NULL, str(env, "rejected natively"), &e);
  napi_reject_deferred(env, d, e);
  return p;
}
static napi_value null_deferred(napi_env env, napi_callback_info info) {
  napi_status a = napi_resolve_deferred(env, NULL, NULL), b = napi_reject_deferred(env, NULL, NULL);
  return num(env, a * 10 + b);
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "make", make);
  export_fn(env, exports, "settle", settle);
  export_fn(env, exports, "rejectedNow", rejected_now);
  export_fn(env, exports, "nullDeferred", null_deferred);
  return exports;
}
"""


def test_promise_deferreds_settle_once(js, workdir, golden):
    """CATCHES: napi_create_promise returning a non-Promise, deferreds that can be settled twice, NULL
    deferreds not rejected with napi_invalid_arg, or settlement running reactions synchronously."""
    addon(workdir, PROMISE_C)
    code = r"""
const a = require('./addon.node');
const log = [];
const p0 = a.make(0), p1 = a.make(1);
console.log(p0 instanceof Promise, typeof p0.then, Object.getPrototypeOf(p0) === Promise.prototype, p0 !== p1);
p0.then((v) => log.push('p0 resolved ' + JSON.stringify(v)), () => log.push('p0 wrongly rejected'));
p1.then(() => log.push('p1 wrongly resolved'), (e) => log.push('p1 rejected ' + e));
console.log('settle p0', a.settle(0, true, { answer: 42 }), 'again', a.settle(0, true, 'again'), a.settle(0, false, 'x'));
console.log('settle p1', a.settle(1, false, 'reason'), 'again', a.settle(1, true, 'late'));
console.log('null deferred', a.nullDeferred());
log.push('sync end');
queueMicrotask(() => log.push('microtask queued after settling'));
setTimeout(() => console.log(log.join('\n')), 0);
"""
    r = js(code)
    assert out(r) == golden("promise_settle")
    assert (r.returncode, r.stderr) == (0, b"")


def test_promise_await_adoption_and_late_settlement(js, workdir, golden):
    """CATCHES: native promises that cannot be awaited, a resolve with a thenable that does not adopt
    its state, a rejection not delivered to try/catch, or a deferred lost when settled from a timer."""
    addon(workdir, PROMISE_C)
    code = r"""
const a = require('./addon.node');
(async () => {
  const p2 = a.make(2);
  a.settle(2, true, Promise.resolve('adopted value'));
  console.log('adopted:', await p2);
  try { await a.rejectedNow(); } catch (e) { console.log('rejected:', e instanceof Error, e.message); }
  const p3 = a.make(3);
  setTimeout(() => console.log('timer settles', a.settle(3, true, 'from timer')), 5);
  console.log('late:', await p3);
  const p0 = a.make(0);
  a.settle(0, false, new TypeError('typed rejection'));
  const outcome = await p0.then(() => 'resolved?', (e) => `${e.name}: ${e.message}`);
  console.log('outcome:', outcome);
  const all = [a.make(0), a.make(1)];
  a.settle(1, true, 'second'); a.settle(0, true, 'first');
  console.log('all:', (await Promise.all(all)).join('+'));
})();
"""
    r = js(code)
    assert out(r) == golden("promise_await")
    assert (r.returncode, r.stderr) == (0, b"")


# ---------------------------------------------------------------------------- buffers / typed arrays
def test_buffer_copy_and_external_buffer(js, workdir, golden):
    """CATCHES: buffer creation that aliases the caller's memory (so later C writes leak in), returns a
    data pointer that is not the new buffer's storage, or mishandles zero-length / NULL-data buffers."""
    addon(workdir, r"""
static unsigned char source[6] = {1, 2, 3, 250, 255, 0};
static unsigned char ext[4] = {9, 8, 7, 6};
static napi_value copy(napi_env env, napi_callback_info info) {
  void *dp = NULL; napi_value b;
  napi_status s = napi_create_buffer_copy(env, 5, source, &dp, &b);
  if (dp) ((unsigned char *)dp)[0] = 100;  /* writes go to the new buffer, not to source */
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "status", num(env, s));
  napi_set_named_property(env, o, "buf", b);
  napi_set_named_property(env, o, "source0", num(env, source[0]));
  return o;
}
static napi_value empties(napi_env env, napi_callback_info info) {
  napi_value b1, b2, b3, b4, arr; napi_create_array(env, &arr);
  napi_status s1 = napi_create_buffer_copy(env, 0, source, NULL, &b1);
  napi_status s2 = napi_create_buffer_copy(env, 3, NULL, NULL, &b2);
  napi_status s3 = napi_create_external_buffer(env, 0, ext, NULL, NULL, &b3);
  napi_status s4 = napi_create_external_buffer(env, 2, NULL, NULL, NULL, &b4);
  napi_set_element(env, arr, 0, b1); napi_set_element(env, arr, 1, b2);
  napi_set_element(env, arr, 2, b3); napi_set_element(env, arr, 3, b4);
  napi_set_element(env, arr, 4, num(env, s1 + s2 + s3 + s4));
  return arr;
}
static napi_value external(napi_env env, napi_callback_info info) {
  napi_value b; napi_status s = napi_create_external_buffer(env, 4, ext, NULL, NULL, &b);
  ext[0] = 0;  /* changing the source afterwards must not show through */
  napi_value o; napi_create_object(env, &o);
  napi_set_named_property(env, o, "status", num(env, s));
  napi_set_named_property(env, o, "buf", b);
  ext[0] = 9;
  return o;
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "copy", copy);
  export_fn(env, exports, "empties", empties);
  export_fn(env, exports, "external", external);
  return exports;
}
""")
    code = r"""
const a = require('./addon.node');
const c = a.copy();
console.log('copy', c.status, c.buf instanceof Uint8Array, c.buf.length, c.buf.byteLength, Array.from(c.buf).join(','), 'source0=' + c.source0);
const c2 = a.copy();
console.log('independent', c2.buf !== c.buf, (c.buf[1] = 77, Array.from(c2.buf).join(',')), Array.from(c.buf).join(','));
const e = a.empties();
console.log('empties', e.slice(0, 4).map((b) => `${b instanceof Uint8Array}:${b.length}`).join(' '), 'statuses', e[4]);
const x = a.external();
console.log('external', x.status, x.buf instanceof Uint8Array, Array.from(x.buf).join(','));
console.log('decoded', Buffer.from(a.copy().buf).toString('hex'), new TextDecoder().decode(new Uint8Array(a.copy().buf.slice(1, 3))).length);
"""
    r = js(code)
    assert out(r) == golden("buffers")
    assert (r.returncode, r.stderr) == (0, b"")


def test_typedarray_info_types_lengths_and_data(js, workdir, golden):
    """CATCHES: napi_get_typedarray_info with a wrong napi_typedarray_type code, a byte count instead
    of an element count, a data pointer not at the view's first element, or non-views not rejected."""
    addon(workdir, r"""
static napi_value info_of(napi_env env, napi_callback_info info) {
  int type = -1; size_t len = 999, off = 999; void *data = NULL; napi_value ab = NULL;
  napi_status s = napi_get_typedarray_info(env, arg(env, info, 0), &type, &len, &data, &ab, &off);
  if (s != 0) return num(env, -s);
  size_t elem = (type <= 2) ? 1 : (type <= 4) ? 2 : (type <= 7) ? 4 : 8;
  unsigned long sum = 0;
  for (size_t i = 0; i < len * elem; i++) sum += ((unsigned char *)data)[i];
  if (len) ((unsigned char *)data)[0] += 1;  /* write through the pointer: visible to JS */
  char buf[96]; snprintf(buf, sizeof buf, "type=%d len=%zu bytesum=%lu", type, len, sum);
  return str(env, buf);
}
static napi_value offset_of(napi_env env, napi_callback_info info) {
  size_t off = 999;
  napi_status s = napi_get_typedarray_info(env, arg(env, info, 0), NULL, NULL, NULL, NULL, &off);
  return num(env, s * 1000 + off);
}
static napi_value info_nulls(napi_env env, napi_callback_info info) {
  return num(env, napi_get_typedarray_info(env, arg(env, info, 0), NULL, NULL, NULL, NULL, NULL));
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "info", info_of);
  export_fn(env, exports, "offset", offset_of);
  export_fn(env, exports, "infoNulls", info_nulls);
  return exports;
}
""")
    code = r"""
const a = require('./addon.node');
const arrs = [new Int8Array([-1, 2]), new Uint8Array([1, 2, 3]), new Uint8ClampedArray([200]), new Int16Array([256, -1]),
  new Uint16Array([513]), new Int32Array([1, 2]), new Uint32Array([7]), new Float32Array([1.5]), new Float64Array([0.5, 2]),
  new BigInt64Array([3n]), new BigUint64Array([4n]), Buffer.from('AB'), new Uint8Array(0)];
for (const t of arrs) {
  const r = a.info(t);
  console.log(t.constructor.name.padEnd(17), r, '->', Array.from(t, String).join(','));
}
const big = new Uint8Array([10, 20, 30, 40, 50, 60]);
console.log('subarray', a.info(big.subarray(2, 5)), '->', Array.from(big).join(','));
const i16 = new Int16Array(new ArrayBuffer(8), 2, 2); i16[0] = 3; i16[1] = 4;
console.log('offset view', a.info(i16), '->', Array.from(i16).join(','));
console.log('offset of whole array', a.offset(new Uint8Array(4)));
console.log('rejected', a.info([1, 2]), a.info(new ArrayBuffer(4)), a.info(new DataView(new ArrayBuffer(2))), a.info('str'), a.info({ length: 1 }));
console.log('all outputs NULL', a.infoNulls(new Uint8Array(2)), a.infoNulls({}));
"""
    r = js(code)
    assert out(r) == golden("typedarray_info")
    assert (r.returncode, r.stderr) == (0, b"")


# -------------------------------------------------------------------------------------- async work
ASYNC_C = r"""
typedef struct { double input, output; napi_ref cb; napi_deferred d; napi_async_work work; int executed; } Job;
static Job jobs[4];
static void execute(napi_env env, void *data) { Job *j = data; j->output = j->input * j->input; j->executed++; }
static void complete_cb(napi_env env, napi_status status, void *data) {
  Job *j = data;
  napi_value cb, undef, args[3];
  napi_get_reference_value(env, j->cb, &cb);
  napi_get_undefined(env, &undef);
  args[0] = num(env, status); args[1] = num(env, j->output); args[2] = num(env, j->executed);
  napi_call_function(env, undef, cb, 3, args, NULL);
  napi_delete_reference(env, j->cb);
  napi_delete_async_work(env, j->work);
}
static napi_value square_cb(napi_env env, napi_callback_info info) {
  Job *j = &jobs[arg_u32(env, info, 0)];
  j->executed = 0;
  napi_get_value_double(env, arg(env, info, 1), &j->input);
  napi_create_reference(env, arg(env, info, 2), 1, &j->cb);
  napi_status s1 = napi_create_async_work(env, NULL, str(env, "square"), execute, complete_cb, j, &j->work);
  napi_status s2 = napi_queue_async_work(env, j->work);
  return num(env, s1 * 10 + s2);
}
static void complete_promise(napi_env env, napi_status status, void *data) {
  Job *j = data;
  if (j->input < 0) {
    napi_value e; napi_create_error(env, NULL, str(env, "negative input"), &e);
    napi_reject_deferred(env, j->d, e);
  } else {
    napi_resolve_deferred(env, j->d, num(env, j->output));
  }
  napi_delete_async_work(env, j->work);
}
static napi_value square_promise(napi_env env, napi_callback_info info) {
  Job *j = &jobs[arg_u32(env, info, 0)];
  napi_get_value_double(env, arg(env, info, 1), &j->input);
  napi_value p; napi_create_promise(env, &j->d, &p);
  napi_create_async_work(env, NULL, str(env, "squarePromise"), execute, complete_promise, j, &j->work);
  napi_queue_async_work(env, j->work);
  return p;
}
static napi_value lifecycle(napi_env env, napi_callback_info info) {
  Job *j = &jobs[3]; j->input = 3; j->executed = 0;
  napi_async_work w, w2, w3;
  napi_status a = napi_create_async_work(env, NULL, str(env, "x"), execute, NULL, j, &w);
  napi_status b = napi_queue_async_work(env, w);
  napi_status c = napi_queue_async_work(env, w);  /* already consumed */
  napi_status d = napi_cancel_async_work(env, w);
  napi_status e = napi_delete_async_work(env, w);
  napi_create_async_work(env, NULL, str(env, "y"), execute, NULL, j, &w2);
  napi_status f = napi_delete_async_work(env, w2);
  napi_status g = napi_queue_async_work(env, w2);  /* deleted before it was queued */
  napi_status h = napi_queue_async_work(env, NULL);
  napi_status i = napi_delete_async_work(env, NULL);
  napi_create_async_work(env, NULL, str(env, "z"), NULL, NULL, j, &w3);
  napi_status k = napi_queue_async_work(env, w3);  /* no callbacks at all */
  char buf[256];
  snprintf(buf, sizeof buf, "create=%d queue=%d requeue=%d cancel=%d delete=%d delete-unqueued=%d queue-deleted=%d "
           "queue-null=%d delete-null=%d queue-empty=%d executed=%d output=%g",
           a, b, c, d, e, f, g, h, i, k, j->executed, j->output);
  return str(env, buf);
}
static napi_value tsfn(napi_env env, napi_callback_info info) {
  napi_threadsafe_function f = NULL;
  napi_status a = napi_create_threadsafe_function(env, arg(env, info, 0), NULL, str(env, "tsfn"), 0, 1, NULL, NULL, NULL, NULL, &f);
  napi_status b = napi_unref_threadsafe_function(env, f);
  napi_status c = napi_create_threadsafe_function(env, arg(env, info, 0), NULL, str(env, "tsfn"), 0, 1, NULL, NULL, NULL, NULL, NULL);
  char buf[64]; snprintf(buf, sizeof buf, "create=%d unref=%d create-no-result=%d handle=%s", a, b, c, f ? "set" : "null");
  return str(env, buf);
}
napi_value napi_register_module_v1(napi_env env, napi_value exports) {
  export_fn(env, exports, "squareCb", square_cb);
  export_fn(env, exports, "squarePromise", square_promise);
  export_fn(env, exports, "lifecycle", lifecycle);
  export_fn(env, exports, "tsfn", tsfn);
  return exports;
}
"""


def test_async_work_completes_with_callbacks_and_promises(js, workdir, golden):
    """CATCHES: async work whose execute result is not visible in complete, whose complete callback
    cannot call into JS or settle deferreds, or that never completes so awaiting it hangs."""
    addon(workdir, ASYNC_C)
    code = r"""
const a = require('./addon.node');
const results = [];
const done = new Promise((res) => {
  let n = 0;
  const cb = (tag) => (status, value, executed) => {
    results.push(`${tag}: status=${status} value=${value} executed=${executed}`);
    if (++n === 3) res();
  };
  console.log('queued', a.squareCb(0, 7, cb('seven')), a.squareCb(1, 1.5, cb('one-and-half')), a.squareCb(2, -3, cb('minus-three')));
});
(async () => {
  await done;
  console.log(results.sort().join('\n'));
  console.log('promise', await a.squarePromise(2, 12));
  console.log('both', (await Promise.all([a.squarePromise(0, 2), a.squarePromise(1, 3)])).join(','));
  await a.squarePromise(2, -2).then(() => console.log('unexpected'), (e) => console.log('rejected', e.message));
})();
"""
    r = js(code)
    assert out(r) == golden("async_work")
    assert (r.returncode, r.stderr) == (0, b"")


def test_async_work_lifecycle_statuses_and_threadsafe_stubs(js, workdir, golden):
    """CATCHES: async work that can be queued twice or after deletion, NULL work handles not rejected
    with napi_invalid_arg, work without callbacks crashing, or threadsafe-function stubs failing."""
    addon(workdir, ASYNC_C)
    code = "const a = require('./addon.node');\nconsole.log(a.lifecycle());\nconsole.log(a.tsfn(() => {}));\n"
    r = js(code)
    assert out(r) == golden("async_lifecycle")
    assert (r.returncode, r.stderr) == (0, b"")
