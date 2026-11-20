"""WebAssembly JS API (WebAssembly.Module/Instance/Memory/Table/Global, validate/compile/instantiate)
and the wasm interpreter behind it: numeric/conversion opcodes, control flow, memory, tables, globals,
imports, start functions, traps and decoder errors.

Every module is hand-assembled by the tiny assembler below and embedded into the JS program as a
literal Uint8Array, so the tests need no binary resources.
"""

import struct

import pytest

from conftest import golden, write_files

TIERS = [[], ["--tier=interp"], ["--tier=bytecode"]]
TIER_IDS = ["jit", "interp", "bytecode"]

# ---------------------------------------------------------------------------------------------
# A minimal wasm binary assembler
# ---------------------------------------------------------------------------------------------

I32, I64, F32, F64, FUNCREF = 0x7F, 0x7E, 0x7D, 0x7C, 0x70
BT_EMPTY = 0x40


def uleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def sleb(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if (n == 0 and not b & 0x40) or (n == -1 and b & 0x40):
            out.append(b)
            return bytes(out)
        out.append(b | 0x80)


def vec(items):
    return uleb(len(items)) + b"".join(items)


def wname(s):
    b = s.encode()
    return uleb(len(b)) + b


def section(sid, payload):
    return bytes([sid]) + uleb(len(payload)) + payload


def limits(mn, mx=None):
    return b"\x00" + uleb(mn) if mx is None else b"\x01" + uleb(mn) + uleb(mx)


def op(*codes):
    return bytes(codes)


def lget(i):
    return b"\x20" + uleb(i)


def lset(i):
    return b"\x21" + uleb(i)


def ltee(i):
    return b"\x22" + uleb(i)


def gget(i):
    return b"\x23" + uleb(i)


def gset(i):
    return b"\x24" + uleb(i)


def i32c(n):
    return b"\x41" + sleb(n)


def i64c(n):
    return b"\x42" + sleb(n)


def f32c(x):
    return b"\x43" + struct.pack("<f", x)


def f64c(x):
    return b"\x44" + struct.pack("<d", x)


def call(i):
    return b"\x10" + uleb(i)


def call_indirect(type_idx, table=0):
    return b"\x11" + uleb(type_idx) + uleb(table)


def br(d):
    return b"\x0c" + uleb(d)


def br_if(d):
    return b"\x0d" + uleb(d)


def br_table(targets, default):
    return b"\x0e" + vec([uleb(t) for t in targets]) + uleb(default)


def mem(opcode, offset=0, align=0):
    return bytes([opcode]) + uleb(align) + uleb(offset)


def block(bt, *body):
    return b"\x02" + bytes([bt]) + b"".join(body) + b"\x0b"


def loop(bt, *body):
    return b"\x03" + bytes([bt]) + b"".join(body) + b"\x0b"


def if_(bt, then, els=None):
    out = b"\x04" + bytes([bt]) + then
    if els is not None:
        out += b"\x05" + els
    return out + b"\x0b"


class Mod:
    """Collects module entities; build() emits the sections in canonical order."""

    def __init__(self):
        self.types, self.imports, self.funcs = [], [], []
        self.tables, self.mems, self.globals, self.exports = [], [], [], []
        self.elems, self.datas = [], []
        self.n_imp_funcs = self.n_imp_globals = 0
        self.start = None

    def type(self, params, results):
        t = b"\x60" + vec([bytes([p]) for p in params]) + vec([bytes([r]) for r in results])
        if t not in self.types:
            self.types.append(t)
        return self.types.index(t)

    def import_func(self, module, nm, params, results):
        ti = self.type(params, results)
        self.imports.append(wname(module) + wname(nm) + b"\x00" + uleb(ti))
        self.n_imp_funcs += 1
        return self.n_imp_funcs - 1

    def import_memory(self, module, nm, mn, mx=None):
        self.imports.append(wname(module) + wname(nm) + b"\x02" + limits(mn, mx))

    def import_table(self, module, nm, mn, mx=None):
        self.imports.append(wname(module) + wname(nm) + b"\x01" + bytes([FUNCREF]) + limits(mn, mx))

    def import_global(self, module, nm, vt, mutable=False):
        self.imports.append(wname(module) + wname(nm) + b"\x03" + bytes([vt, int(mutable)]))
        self.n_imp_globals += 1
        return self.n_imp_globals - 1

    def func(self, params, results, body, locals=(), export=None):
        self.funcs.append((self.type(params, results), list(locals), body))
        idx = self.n_imp_funcs + len(self.funcs) - 1
        if export:
            self.export(export, 0, idx)
        return idx

    def memory(self, mn, mx=None, export=None):
        self.mems.append(limits(mn, mx))
        if export:
            self.export(export, 2, len(self.mems) - 1)

    def table(self, mn, mx=None, export=None):
        self.tables.append(bytes([FUNCREF]) + limits(mn, mx))
        if export:
            self.export(export, 1, len(self.tables) - 1)

    def global_(self, vt, mutable, init, export=None):
        self.globals.append(bytes([vt, int(mutable)]) + init + b"\x0b")
        idx = self.n_imp_globals + len(self.globals) - 1
        if export:
            self.export(export, 3, idx)
        return idx

    def export(self, nm, kind, idx):
        self.exports.append(wname(nm) + bytes([kind]) + uleb(idx))

    def elem(self, offset, funcs, table=None):
        if table is None:
            self.elems.append(uleb(0) + offset + b"\x0b" + vec([uleb(f) for f in funcs]))
        else:
            self.elems.append(uleb(2) + uleb(table) + offset + b"\x0b" + b"\x00" + vec([uleb(f) for f in funcs]))

    def data(self, offset, data, flags=0):
        if flags == 0:
            self.datas.append(uleb(0) + offset + b"\x0b" + uleb(len(data)) + data)
        elif flags == 1:
            self.datas.append(uleb(1) + uleb(len(data)) + data)
        else:
            self.datas.append(uleb(2) + uleb(0) + offset + b"\x0b" + uleb(len(data)) + data)

    def build(self):
        out = b"\x00asm\x01\x00\x00\x00"
        if self.types:
            out += section(1, vec(self.types))
        if self.imports:
            out += section(2, vec(self.imports))
        if self.funcs:
            out += section(3, vec([uleb(t) for t, _, _ in self.funcs]))
        if self.tables:
            out += section(4, vec(self.tables))
        if self.mems:
            out += section(5, vec(self.mems))
        if self.globals:
            out += section(6, vec(self.globals))
        if self.exports:
            out += section(7, vec(self.exports))
        if self.start is not None:
            out += section(8, uleb(self.start))
        if self.elems:
            out += section(9, vec(self.elems))
        if self.funcs:
            bodies = []
            for _, locs, body in self.funcs:
                b = vec([uleb(1) + bytes([t]) for t in locs]) + body + b"\x0b"
                bodies.append(uleb(len(b)) + b)
            out += section(10, vec(bodies))
        if self.datas:
            out += section(11, vec(self.datas))
        return out


def js_bytes(b):
    return "new Uint8Array([" + ",".join(str(x) for x in b) + "])"


# Shared JS helpers: float formatting that distinguishes -0, and a "call and show trap" wrapper.
JS_PRELUDE = r"""
const fmt = (v) => (typeof v === "number" && Object.is(v, -0) ? "-0" : typeof v === "bigint" ? v + "n" : String(v));
const tryCall = (f, ...a) => { try { return fmt(f(...a)); } catch (e) { return `${e.name}(${e.message})`; } };
"""


def _run_prog(run, workdir, src, tier=()):
    write_files(workdir, {"t.mjs": JS_PRELUDE + src})
    return run([*tier, "t.mjs"])


def _check(r, name):
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, name)


# ---------------------------------------------------------------------------------------------
# Numeric opcodes
# ---------------------------------------------------------------------------------------------

BIN_I32 = {
    "add": 0x6A, "sub": 0x6B, "mul": 0x6C, "div_s": 0x6D, "div_u": 0x6E, "rem_s": 0x6F, "rem_u": 0x70,
    "and": 0x71, "or": 0x72, "xor": 0x73, "shl": 0x74, "shr_s": 0x75, "shr_u": 0x76, "rotl": 0x77,
    "rotr": 0x78, "eq": 0x46, "ne": 0x47, "lt_s": 0x48, "lt_u": 0x49, "gt_s": 0x4A, "gt_u": 0x4B,
    "le_s": 0x4C, "le_u": 0x4D, "ge_s": 0x4E, "ge_u": 0x4F,
}
UN_I32 = {"clz": 0x67, "ctz": 0x68, "popcnt": 0x69, "eqz": 0x45, "extend8_s": 0xC0, "extend16_s": 0xC1}


def _i32_module():
    m = Mod()
    for n, o in BIN_I32.items():
        m.func([I32, I32], [I32], lget(0) + lget(1) + op(o), export=n)
    for n, o in UN_I32.items():
        m.func([I32], [I32], lget(0) + op(o), export=n)
    return m.build()


PROG_I32 = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_i32_module())});
const x = instance.exports;
const pairs = [[7, 3], [-7, 3], [7, -3], [-2147483648, -1], [-1, 31], [5, 33], [0x12345678, 4], [3, 0]];
for (const n of {list(BIN_I32)!r}) console.log(n.padEnd(7), pairs.map(([a, b]) => tryCall(x[n], a, b)).join(" "));
for (const n of {list(UN_I32)!r}) console.log(n.padEnd(10), [0, 1, -1, 0x80, 0x8000, 0x00f0f000, -2147483648].map((v) => x[n](v)).join(" "));
// JS -> i32 argument coercion: ToNumber then wrap.
console.log("coerce", x.add(2 ** 32 + 5, 0), x.add(-1.9, 0), x.add("12", true), x.add(NaN, undefined), x.add(2 ** 31, 0), x.add({{ valueOf() {{ return 40; }} }}, 2));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_wasm_i32_arithmetic_and_traps(run, workdir, tier):
    """CATCHES: wrong i32 arithmetic/bitwise/shift/rotate/compare semantics (signed vs unsigned, shift
    counts mod 32, sign extension), missing divide-by-zero/overflow traps, or wrong JS->i32 coercion."""
    _check(_run_prog(run, workdir, PROG_I32, tier), "i32_ops")


BIN_I64 = {
    "add": 0x7C, "sub": 0x7D, "mul": 0x7E, "div_s": 0x7F, "div_u": 0x80, "rem_s": 0x81, "rem_u": 0x82,
    "and": 0x83, "or": 0x84, "xor": 0x85, "shl": 0x86, "shr_s": 0x87, "shr_u": 0x88, "rotl": 0x89,
    "rotr": 0x8A,
}
CMP_I64 = {"eq": 0x51, "ne": 0x52, "lt_s": 0x53, "lt_u": 0x54, "gt_s": 0x55, "gt_u": 0x56, "le_s": 0x57,
           "le_u": 0x58, "ge_s": 0x59, "ge_u": 0x5A}
UN_I64 = {"clz": 0x79, "ctz": 0x7A, "popcnt": 0x7B, "extend8_s": 0xC2, "extend16_s": 0xC3, "extend32_s": 0xC4}


def _i64_module():
    m = Mod()
    for n, o in BIN_I64.items():
        m.func([I64, I64], [I64], lget(0) + lget(1) + op(o), export=n)
    for n, o in CMP_I64.items():
        m.func([I64, I64], [I32], lget(0) + lget(1) + op(o), export=n)
    for n, o in UN_I64.items():
        m.func([I64], [I64], lget(0) + op(o), export=n)
    m.func([I64], [I32], lget(0) + op(0x50), export="eqz")
    m.func([], [I64], i64c(-(2**63)), export="min")
    m.func([], [I64], i64c(2**63 - 1), export="max")
    return m.build()


PROG_I64 = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_i64_module())});
const x = instance.exports;
const pairs = [[7n, 3n], [-7n, 3n], [-9223372036854775808n, -1n], [-1n, 63n], [5n, 65n], [0x123456789abcdefn, 8n], [1n, 0n]];
for (const n of {list(BIN_I64) + list(CMP_I64)!r}) console.log(n.padEnd(6), pairs.map(([a, b]) => tryCall(x[n], a, b)).join(" "));
for (const n of {list(UN_I64)!r}) console.log(n.padEnd(10), [0n, 1n, -1n, 0x80n, 0x8000n, 0x80000000n, -9223372036854775808n].map((v) => fmt(x[n](v))).join(" "));
console.log("eqz", x.eqz(0n), x.eqz(5n), typeof x.eqz(0n));
console.log("limits", fmt(x.min()), fmt(x.max()), typeof x.max());
// BigInt arguments wrap to 64 bits; plain Numbers are accepted and truncated.
console.log("coerce", fmt(x.add(2n ** 64n + 3n, 0n)), fmt(x.add(-1n, 2n ** 63n)), fmt(x.add(42, 0n)), fmt(x.add(-3.7, 0n)));
"""


def test_wasm_i64_arithmetic_and_bigint_interop(run, workdir):
    """CATCHES: i64 ops computed in 32 bits or as doubles, results not returned as BigInt, wrong
    unsigned division/comparison, missing i64 overflow trap, or wrong BigInt wrapping of arguments."""
    _check(_run_prog(run, workdir, PROG_I64), "i64_ops")


BIN_F = {"add": (0x92, 0xA0), "sub": (0x93, 0xA1), "mul": (0x94, 0xA2), "div": (0x95, 0xA3),
         "min": (0x96, 0xA4), "max": (0x97, 0xA5), "copysign": (0x98, 0xA6)}
CMP_F = {"eq": (0x5B, 0x61), "ne": (0x5C, 0x62), "lt": (0x5D, 0x63), "gt": (0x5E, 0x64), "le": (0x5F, 0x65),
         "ge": (0x60, 0x66)}
UN_F = {"abs": (0x8B, 0x99), "neg": (0x8C, 0x9A), "ceil": (0x8D, 0x9B), "floor": (0x8E, 0x9C),
        "trunc": (0x8F, 0x9D), "nearest": (0x90, 0x9E), "sqrt": (0x91, 0x9F)}


def _float_module():
    m = Mod()
    for k, (t, idx) in {"f32": (F32, 0), "f64": (F64, 1)}.items():
        for n, ops in BIN_F.items():
            m.func([t, t], [t], lget(0) + lget(1) + op(ops[idx]), export=f"{k}_{n}")
        for n, ops in CMP_F.items():
            m.func([t, t], [I32], lget(0) + lget(1) + op(ops[idx]), export=f"{k}_{n}")
        for n, ops in UN_F.items():
            m.func([t], [t], lget(0) + op(ops[idx]), export=f"{k}_{n}")
    m.func([], [F32], f32c(0.1), export="f32_const")
    m.func([], [F64], f64c(-2.5e-300), export="f64_const")
    return m.build()


PROG_FLOAT = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_float_module())});
const x = instance.exports;
const pairs = [[1.5, 2.25], [0.1, 0.2], [-0, 0], [1, 0], [-1, Infinity], [3, -2], [1e39, 10]];
for (const k of ["f32", "f64"]) {{
  for (const n of {list(BIN_F) + list(CMP_F)!r}) console.log(`${{k}}.${{n}}`.padEnd(13), pairs.map(([a, b]) => fmt(x[`${{k}}_${{n}}`](a, b))).join(" "));
  for (const n of {list(UN_F)!r}) console.log(`${{k}}.${{n}}`.padEnd(13), [2.5, 3.5, -2.5, -0.4, 0.5, 1.7, -0, 16, -4, Infinity].map((v) => fmt(x[`${{k}}_${{n}}`](v))).join(" "));
}}
console.log("nan", x.f64_add(NaN, 1), x.f64_eq(NaN, NaN), x.f64_ne(NaN, NaN), x.f32_lt(NaN, 1), x.f64_sqrt(-1));
console.log("consts", x.f32_const(), x.f64_const(), x.f32_add(16777217, 0), x.f32_add("0.5", null));
"""


def test_wasm_float_arithmetic(run, workdir):
    """CATCHES: f32 ops performed at f64 precision (no rounding to single), wrong nearest (ties-to-even),
    copysign/abs/neg on -0, NaN comparison results, or float constants decoded with the wrong width."""
    _check(_run_prog(run, workdir, PROG_FLOAT), "float_ops")


CONV = [
    ("i32.wrap_i64", 0xA7, I64, I32), ("i32.trunc_f32_s", 0xA8, F32, I32), ("i32.trunc_f32_u", 0xA9, F32, I32),
    ("i32.trunc_f64_s", 0xAA, F64, I32), ("i32.trunc_f64_u", 0xAB, F64, I32),
    ("i64.extend_i32_s", 0xAC, I32, I64), ("i64.extend_i32_u", 0xAD, I32, I64),
    ("i64.trunc_f32_s", 0xAE, F32, I64), ("i64.trunc_f32_u", 0xAF, F32, I64), ("i64.trunc_f64_s", 0xB0, F64, I64),
    ("i64.trunc_f64_u", 0xB1, F64, I64),
    ("f32.convert_i32_s", 0xB2, I32, F32), ("f32.convert_i32_u", 0xB3, I32, F32),
    ("f32.convert_i64_s", 0xB4, I64, F32), ("f32.convert_i64_u", 0xB5, I64, F32), ("f32.demote_f64", 0xB6, F64, F32),
    ("f64.convert_i32_s", 0xB7, I32, F64), ("f64.convert_i32_u", 0xB8, I32, F64),
    ("f64.convert_i64_s", 0xB9, I64, F64), ("f64.convert_i64_u", 0xBA, I64, F64), ("f64.promote_f32", 0xBB, F32, F64),
    ("i32.reinterpret_f32", 0xBC, F32, I32), ("i64.reinterpret_f64", 0xBD, F64, I64),
    ("f32.reinterpret_i32", 0xBE, I32, F32), ("f64.reinterpret_i64", 0xBF, I64, F64),
]
SAT = [("i32.trunc_sat_f32_s", 0, F32, I32), ("i32.trunc_sat_f32_u", 1, F32, I32),
       ("i32.trunc_sat_f64_s", 2, F64, I32), ("i32.trunc_sat_f64_u", 3, F64, I32),
       ("i64.trunc_sat_f32_s", 4, F32, I64), ("i64.trunc_sat_f32_u", 5, F32, I64),
       ("i64.trunc_sat_f64_s", 6, F64, I64), ("i64.trunc_sat_f64_u", 7, F64, I64)]


def _conv_module():
    m = Mod()
    for n, o, p, r in CONV:
        m.func([p], [r], lget(0) + op(o), export=n)
    for n, sub, p, r in SAT:
        m.func([p], [r], lget(0) + b"\xfc" + uleb(sub), export=n)
    return m.build()


def _conv_inputs():
    by_type = {
        I32: "[0, 1, -1, 2147483647, -2147483648, 0x3f800000]",
        I64: "[0n, -1n, 4294967297n, 9007199254740993n, -9223372036854775808n, 0x3ff0000000000000n]",
        F32: "[0, -1.9, 2.9, 1e10, -1e10, NaN, 3.4e38, -3.4e38, 1.5]",
        F64: "[0, -1.9, 2.9, 1e10, -1e10, NaN, 1e300, -1e300, 4294967295.5]",
    }
    rows = []
    for n, _, p, _ in CONV + SAT:
        rows.append(f"[{n!r}, {by_type[p]}]")
    return "[" + ",\n".join(rows) + "]"


PROG_CONV = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_conv_module())});
const x = instance.exports;
for (const [n, inputs] of {_conv_inputs()}) console.log(n.padEnd(20), inputs.map((v) => tryCall(x[n], v)).join(" "));
"""


def test_wasm_conversions_reinterpret_and_saturating_truncation(run, workdir):
    """CATCHES: wrong wrap/extend/convert/demote/promote/reinterpret results, signed vs unsigned mixups,
    saturating truncation that does not clamp (or maps NaN to non-zero), or traps where the reference returns values."""
    _check(_run_prog(run, workdir, PROG_CONV), "conversions")


# ---------------------------------------------------------------------------------------------
# Control flow, calls, recursion
# ---------------------------------------------------------------------------------------------


def _control_module():
    m = Mod()
    # fac(i64) recursive via if/else with a result.
    fac = m.func([I64], [I64], b"")
    m.funcs[-1] = (m.funcs[-1][0], [], lget(0) + op(0x50) + if_(I64, i64c(1), lget(0) + lget(0) + i64c(1) + op(0x7D) + call(fac) + op(0x7E)))
    m.export("fac", 0, fac)
    # fib iterative with loop/br_if: locals a, b, i
    m.func([I32], [I32],
           i32c(0) + lset(1) + i32c(1) + lset(2)
           + block(BT_EMPTY, loop(BT_EMPTY,
                                  lget(0) + op(0x45) + br_if(1)
                                  + lget(1) + lget(2) + op(0x6A) + lget(2) + lset(1) + lset(2)
                                  + lget(0) + i32c(1) + op(0x6B) + lset(0) + br(0)))
           + lget(1), locals=[I32, I32], export="fib")
    # br_table dispatch: returns 100 + case, default 999.
    m.func([I32], [I32],
           block(BT_EMPTY, block(BT_EMPTY, block(BT_EMPTY, block(BT_EMPTY, lget(0) + br_table([0, 1, 2], 3))
                                                      + i32c(100) + op(0x0F))
                                       + i32c(101) + op(0x0F))
                 + i32c(102) + op(0x0F))
           + i32c(999), export="sw")
    # block with result + br carrying a value past dropped operands
    m.func([I32], [I32], block(I32, i32c(99) + i32c(7) + lget(0) + br_if(0) + op(0x1A, 0x1A) + i32c(1)), export="brval")
    # select
    m.func([I32, I32, I32], [I32], lget(0) + lget(1) + lget(2) + op(0x1B), export="select")
    # early return from nested loop: first i in [0, n) with i*i > limit, else -1
    m.func([I32, I32], [I32],
           block(BT_EMPTY, loop(BT_EMPTY,
                                lget(2) + lget(0) + op(0x4E) + br_if(1)
                                + lget(2) + lget(2) + op(0x6C) + lget(1) + op(0x4A) + if_(BT_EMPTY, lget(2) + op(0x0F))
                                + lget(2) + i32c(1) + op(0x6A) + lset(2) + br(0)))
           + i32c(-1), locals=[I32], export="firstsq")
    # multi-value result: (i32, i32) -> (i32, i32) swap; and a block typed by a type index.
    m.func([I32, I32], [I32, I32], lget(1) + lget(0), export="swap")
    ti = m.type([I32], [I32, I32])
    m.func([I32], [I32], lget(0) + b"\x02" + sleb(ti) + i32c(10) + b"\x0b" + op(0x6A), export="typedblock")
    # three results incl. i64 / f64
    m.func([], [I32, I64, F64], i32c(1) + i64c(-2) + f64c(0.5), export="three")
    # unreachable, nop, infinite recursion, drop
    m.func([], [], op(0x01, 0x00), export="trap")
    rec = m.func([I32], [I32], b"")
    m.funcs[-1] = (m.funcs[-1][0], [], lget(0) + i32c(1) + op(0x6A) + call(rec))
    m.export("recurse", 0, rec)
    m.func([], [], i32c(1) + op(0x1A), export="void")
    # tee + nested if without else in a value context
    m.func([I32], [I32], lget(0) + i32c(3) + op(0x6C) + ltee(1) + i32c(10) + op(0x4A) + if_(BT_EMPTY, lget(1) + i32c(1000) + op(0x6A) + lset(1)) + lget(1), locals=[I32], export="tee")
    return m.build()


PROG_CONTROL = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_control_module())});
const x = instance.exports;
console.log("fac", [0n, 1n, 5n, 20n, 21n].map((n) => fmt(x.fac(n))).join(" "));
console.log("fib", [0, 1, 2, 10, 30, 47].map((n) => x.fib(n)).join(" "));
console.log("br_table", [0, 1, 2, 3, -1, 100].map((n) => x.sw(n)).join(" "));
console.log("brval", x.brval(1), x.brval(0));
console.log("select", x.select(5, 6, 1), x.select(5, 6, 0), x.select(5, 6, -7));
console.log("firstsq", x.firstsq(10, 20), x.firstsq(10, 1000), x.firstsq(0, 0));
const sw = x.swap(1, 2);
console.log("swap", Array.isArray(sw), sw.join(","), x.typedblock(5));
const three = x.three();
console.log("three", three.length, three.map(fmt).join(","));
console.log("void", x.void(), x.void.length, typeof x.fac);
console.log("tee", x.tee(2), x.tee(4));
console.log("trap", tryCall(x.trap));
console.log("stack", tryCall(x.recurse, 0));
try {{ x.trap(); }} catch (e) {{ console.log(e instanceof WebAssembly.RuntimeError, e instanceof Error, e.constructor === WebAssembly.RuntimeError); }}
console.log("after traps still callable", x.fib(5));
"""


@pytest.mark.parametrize("tier", TIERS, ids=TIER_IDS)
def test_wasm_control_flow_calls_and_multivalue(run, workdir, tier):
    """CATCHES: broken block/loop/br/br_if/br_table/select/return handling, wrong branch value arity,
    multi-value results not surfaced as JS arrays, recursion bugs, or missing unreachable/stack-exhaustion traps."""
    _check(_run_prog(run, workdir, PROG_CONTROL, tier), "control_flow")


def _if_else_loop_module():
    m = Mod()
    # sum over i in [0, n): odd i added, even i subtracted, with an if/else inside a loop. The
    # reference interpreter does not pop the `if` frame when the then-arm reaches `else`, so the
    # loop's `br 0` that follows lands at the if's end instead (skipping the next iteration).
    body = (block(BT_EMPTY, loop(BT_EMPTY,
                                 lget(1) + lget(0) + op(0x4E) + br_if(1)
                                 + lget(1) + i32c(1) + op(0x71)
                                 + if_(BT_EMPTY, lget(2) + lget(1) + op(0x6A) + lset(2), lget(2) + lget(1) + op(0x6B) + lset(2))
                                 + lget(1) + i32c(1) + op(0x6A) + lset(1) + br(0)))
            + lget(2))
    m.func([I32], [I32], body, locals=[I32, I32], export="alt")
    # if/else as the final value of a function (no branch afterwards) behaves normally.
    m.func([I32], [I32], lget(0) + if_(I32, i32c(11), i32c(22)), export="pick")
    return m.build()


PROG_IF_ELSE = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_if_else_loop_module())});
const x = instance.exports;
console.log("alt", [0, 1, 2, 5, 10].map((n) => x.alt(n)).join(" "));
console.log("pick", x.pick(1), x.pick(0));
"""


def test_wasm_if_else_inside_loop_reference_quirk(run, workdir):
    """CATCHES: rewrites that diverge from the reference's if/else control-stack handling: when the then-arm
    of an if/else is followed by a loop branch, the reference skips the next iteration (alt(10) = 25)."""
    _check(_run_prog(run, workdir, PROG_IF_ELSE), "if_else_quirk")


# ---------------------------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------------------------


def _memory_module(export_mem):
    m = Mod()
    m.memory(1, 3, export="mem" if export_mem else None)
    loads = {"i32.load": (0x28, I32), "i64.load": (0x29, I64), "f32.load": (0x2A, F32), "f64.load": (0x2B, F64),
             "i32.load8_s": (0x2C, I32), "i32.load8_u": (0x2D, I32), "i32.load16_s": (0x2E, I32),
             "i32.load16_u": (0x2F, I32), "i64.load8_s": (0x30, I64), "i64.load8_u": (0x31, I64),
             "i64.load16_s": (0x32, I64), "i64.load16_u": (0x33, I64), "i64.load32_s": (0x34, I64),
             "i64.load32_u": (0x35, I64)}
    for n, (o, t) in loads.items():
        m.func([I32], [t], lget(0) + mem(o), export=n)
    m.func([I32], [I32], lget(0) + mem(0x28, offset=4), export="load_off4")
    m.func([I32], [I32], lget(0) + mem(0x2D, offset=300), export="load_off300")
    stores = {"i32.store": (0x36, I32), "i64.store": (0x37, I64), "f32.store": (0x38, F32), "f64.store": (0x39, F64),
              "i32.store8": (0x3A, I32), "i32.store16": (0x3B, I32), "i64.store8": (0x3C, I64),
              "i64.store16": (0x3D, I64), "i64.store32": (0x3E, I64)}
    for n, (o, t) in stores.items():
        m.func([I32, t], [], lget(0) + lget(1) + mem(o), export=n)
    m.func([], [I32], op(0x3F, 0x00), export="size")
    m.func([I32], [I32], lget(0) + op(0x40, 0x00), export="grow")
    m.func([I32, I32, I32], [], lget(0) + lget(1) + lget(2) + b"\xfc\x0b\x00", export="fill")
    m.func([I32, I32, I32], [], lget(0) + lget(1) + lget(2) + b"\xfc\x0a\x00\x00", export="copy")
    m.data(i32c(16), b"Hello, wasm!")
    m.data(i32c(0), b"never copied", flags=1)  # passive segment: not applied at instantiation
    m.data(i32c(40), bytes([0xFF, 0xFE, 0x80, 0x7F, 1, 2, 3, 4]), flags=2)
    return m.build()


# Calls into a module that exports (or imports) its memory copy the whole buffer in and out, which
# is slow in the reference; the bulk of the opcode checks therefore use a module whose memory is
# private and only a few calls go through the exported-memory module.
PROG_MEMORY = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_memory_module(False))});
const x = instance.exports;
const peek = (a, n) => Array.from({{ length: n }}, (_, i) => x["i32.load8_u"](a + i));
console.log("private memory", "mem" in x, x.size());
console.log("data", String.fromCharCode(...peek(16, 12)), x["i32.load8_u"](0), peek(40, 8).join(","));
for (const n of ["i32.load", "i64.load", "f32.load", "f64.load", "i32.load8_s", "i32.load8_u", "i32.load16_s", "i32.load16_u",
                 "i64.load8_s", "i64.load8_u", "i64.load16_s", "i64.load16_u", "i64.load32_s", "i64.load32_u"]) {{
  console.log(n.padEnd(13), tryCall(x[n], 40), tryCall(x[n], 16));
}}
console.log("offset", x.load_off4(36) === x["i32.load"](40), tryCall(x.load_off4, 65532), tryCall(x["i32.load"], 65533), tryCall(x["i32.load8_u"], 65535), tryCall(x["i32.load"], -1));
x["i32.store"](100, -2); x["i64.store"](104, -3n); x["f32.store"](112, 1.1); x["f64.store"](116, -0.5);
x["i32.store8"](124, 0x1ff); x["i32.store16"](126, 0x12345); x["i64.store8"](128, 0x1ffn); x["i64.store16"](130, -1n); x["i64.store32"](132, 0x123456789n);
console.log("stored", peek(100, 36).join(","));
console.log("store oob", tryCall(x["i64.store"], 65530, 1n), tryCall(x["i32.store8"], 65536, 1));
x.fill(300, 0x5a, 4); x.copy(302, 16, 5);
console.log("fill/copy", String.fromCharCode(...peek(300, 7)), x.load_off300(2), tryCall(x.load_off300, 65236));
x.copy(17, 16, 4); console.log("overlapping copy", String.fromCharCode(...peek(16, 6)));
console.log("bulk oob", tryCall(x.fill, 65530, 1, 10), tryCall(x.copy, 0, 65530, 10), tryCall(x.copy, 65530, 0, 10));
console.log("grow", x.grow(1), x.size(), x.grow(1), x.size(), x.grow(1), x.grow(0), x.grow(-1));
console.log("last byte reachable", x["i32.load8_u"](3 * 65536 - 1), tryCall(x["i32.load8_u"], 3 * 65536));
// Exported memory: JS writes are visible to wasm on the next call; wasm writes refresh the JS view.
const a = (await WebAssembly.instantiate({js_bytes(_memory_module(True))})).instance.exports;
const mem = a.mem;
console.log("memory", mem instanceof WebAssembly.Memory, mem.buffer instanceof ArrayBuffer, mem.buffer.byteLength);
const bytes = new Uint8Array(mem.buffer);
console.log("exported data", new TextDecoder().decode(bytes.subarray(16, 28)), bytes[0], Array.from(bytes.subarray(40, 48)).join(","));
bytes[200] = 0xab;
console.log("js->wasm", a["i32.load8_u"](200));
a["i32.store"](204, 0x01020304);
console.log("wasm->js", Array.from(new Uint8Array(mem.buffer, 204, 4)).join(","), mem.buffer === bytes.buffer);
const before = mem.buffer;
console.log("grow", a.grow(1), mem.buffer.byteLength, before === mem.buffer, before.byteLength);
console.log("grow js", mem.grow(1), mem.buffer.byteLength);
try {{ mem.grow(1); }} catch (e) {{ console.log(e.name, e.message); }}
"""


def test_wasm_memory_loads_stores_segments_and_growth(run, workdir):
    """CATCHES: wrong load/store widths or sign extension, little-endian errors, memarg offsets ignored,
    missing out-of-bounds traps, data segments applied wrongly (passive copied), memory.fill/copy bugs,
    stale JS views after wasm writes, or memory.grow ignoring the declared maximum."""
    _check(_run_prog(run, workdir, PROG_MEMORY), "memory")


def _imported_memory_module():
    m = Mod()
    m.import_memory("env", "mem", 1)
    m.func([I32], [I32], lget(0) + mem(0x28), export="peek")
    m.func([I32, I32], [], lget(0) + lget(1) + mem(0x36), export="poke")
    m.func([], [I32], op(0x3F, 0x00), export="pages")
    m.data(i32c(8), b"\x2a\x00\x00\x00")
    return m.build()


PROG_MEMORY_IMPORT = f"""
const memory = new WebAssembly.Memory({{ initial: 1, maximum: 2 }});
console.log("standalone", memory.buffer.byteLength, new Uint8Array(memory.buffer)[0]);
new DataView(memory.buffer).setInt32(0, 1234, true);
const bytes = {js_bytes(_imported_memory_module())};
const mod = new WebAssembly.Module(bytes);
const a = new WebAssembly.Instance(mod, {{ env: {{ mem: memory }} }});
const b = new WebAssembly.Instance(mod, {{ env: {{ mem: memory }} }});
console.log("exports", Object.keys(a.exports).join(","), a.exports.mem);
console.log("shared", a.exports.peek(0), a.exports.peek(8), b.exports.peek(8));
a.exports.poke(16, 77);
console.log("cross-instance", b.exports.peek(16), new DataView(memory.buffer).getInt32(16, true));
console.log("grow", memory.grow(1), a.exports.pages(), b.exports.pages(), memory.buffer.byteLength);
try {{ memory.grow(1); }} catch (e) {{ console.log(e.name, e.message); }}
const empty = new WebAssembly.Memory({{ initial: 0 }});
console.log("empty", empty.buffer.byteLength, empty.grow(2), empty.buffer.byteLength);
"""


def test_wasm_imported_memory_shared_between_instances(run, workdir):
    """CATCHES: imported WebAssembly.Memory not shared by reference (instances or JS seeing stale copies),
    data segments not written into the imported memory, or Memory.grow ignoring maximum/initial."""
    _check(_run_prog(run, workdir, PROG_MEMORY_IMPORT), "memory_import")


# ---------------------------------------------------------------------------------------------
# Globals, tables, imports
# ---------------------------------------------------------------------------------------------


def _globals_module():
    m = Mod()
    g_imp = m.import_global("env", "base", I32)
    g_imp64 = m.import_global("env", "big", I64)
    m.global_(I32, True, i32c(10), export="counter")
    m.global_(I64, False, i64c(-(2**40)), export="k64")
    m.global_(F32, True, f32c(0.1), export="f")
    m.global_(F64, False, f64c(2.5), export="d")
    m.global_(I32, False, gget(g_imp), export="copy_of_base")
    m.export("base", 3, g_imp)
    m.func([], [I32], gget(2) + i32c(1) + op(0x6A) + gset(2) + gget(2), export="bump")
    m.func([], [I32], gget(g_imp) + gget(2) + op(0x6A), export="sum")
    m.func([], [I64], gget(g_imp64) + gget(3) + op(0x7C), export="sum64")
    m.func([F32], [], lget(0) + gset(4), export="setf")
    m.global_(FUNCREF, False, b"\xd0\x70", export="nullref")
    m.global_(FUNCREF, False, b"\xd2\x00", export="funcref")
    return m.build()


PROG_GLOBALS = f"""
const big = new WebAssembly.Global({{ value: "i64", mutable: true }}, 5n);
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_globals_module())}, {{ env: {{ base: 100, big }} }});
const x = instance.exports;
console.log("kinds", x.counter instanceof WebAssembly.Global, x.k64 instanceof WebAssembly.Global);
console.log("values", x.counter.value, fmt(x.k64.value), x.f.value, x.d.value, x.copy_of_base.value, x.base.value);
console.log("bump", x.bump(), x.bump(), x.counter.value, x.counter.valueOf() + 1, x.sum());
console.log("sum64", fmt(x.sum64()));
big.value = -1n;
console.log("imported global updated", fmt(big.value), fmt(x.sum64()));
x.setf(1 / 3);
console.log("f32 global", x.f.value);
try {{ x.counter.value = 5; }} catch (e) {{ console.log(e.name, e.message); }}
const g = new WebAssembly.Global({{ value: "f64", mutable: true }}, 1.25);
g.value = 2.75;
console.log("standalone", g.value, new WebAssembly.Global({{ value: "i32" }}, 3.9).value, new WebAssembly.Global({{ value: "f32" }}, 0.1).value, new WebAssembly.Global({{}}).value, fmt(new WebAssembly.Global({{ value: "i64" }}).value));
const imm = new WebAssembly.Global({{ value: "i32" }}, 1);
try {{ imm.value = 2; }} catch (e) {{ console.log(e.name, e.message); }}
console.log("ref globals", x.nullref.value, x.funcref.value);
const gf = new WebAssembly.Global({{ value: "f32", mutable: true }}, 1);
gf.value = 1 / 3;
const g64 = new WebAssembly.Global({{ value: "i64", mutable: true }}, 7);
g64.value = 2n ** 64n + 1n;
console.log("f32/i64 set", gf.value, fmt(g64.value), fmt(new WebAssembly.Global({{ value: "i64" }}, 12).value));
const wrapped = new WebAssembly.Global({{ value: "i32", mutable: true }}, 0);
wrapped.value = 2 ** 32 + 9;
console.log("wrap", wrapped.value, +wrapped);
"""


def test_wasm_globals_import_export_and_mutability(run, workdir):
    """CATCHES: globals copied instead of shared, wrong value types (i64 not BigInt, f32 not rounded),
    const-expr global.get of an import broken, or immutable globals that accept writes."""
    _check(_run_prog(run, workdir, PROG_GLOBALS), "globals")


def _table_module():
    m = Mod()
    t_ii = m.type([I32], [I32])
    m.table(4, None, export="tbl")
    f_double = m.func([I32], [I32], lget(0) + i32c(2) + op(0x6C), export="double")
    f_square = m.func([I32], [I32], lget(0) + lget(0) + op(0x6C), export="square")
    f_noarg = m.func([], [I32], i32c(-5), export="noarg")
    m.func([I32, I32], [I32], lget(1) + lget(0) + call_indirect(t_ii), export="dispatch")
    m.elem(i32c(0), [f_double, f_square])
    m.elem(i32c(3), [f_noarg])
    return m.build()


def _table_user_module():
    m = Mod()
    m.import_table("env", "tbl", 2)
    t_ii = m.type([I32], [I32])
    neg = m.func([I32], [I32], i32c(0) + lget(0) + op(0x6B), export="neg")
    m.func([I32, I32], [I32], lget(1) + lget(0) + call_indirect(t_ii), export="run")
    m.elem(i32c(1), [neg], table=0)
    return m.build()


PROG_TABLES = f"""
const {{ instance }} = await WebAssembly.instantiate({js_bytes(_table_module())});
const x = instance.exports;
const t = x.tbl;
console.log("table", t instanceof WebAssembly.Table, t.length, typeof t.get(0), t.get(2), t.get(0)(21), t.get(1)(9));
console.log("dispatch", x.dispatch(0, 7), x.dispatch(1, 7));
console.log("errors", tryCall(x.dispatch, 2, 1), tryCall(x.dispatch, 3, 1), tryCall(x.dispatch, 4, 1), tryCall(x.dispatch, -1, 1));
t.set(2, x.square);
console.log("after set", x.dispatch(2, 12));
t.set(0, null);
console.log("cleared", t.get(0), tryCall(x.dispatch, 0, 1));
for (const bad of [() => t.set(1, () => 1), () => t.set(1, 5), () => t.get(10), () => t.set(9, x.double)]) {{
  try {{ bad(); console.log("no error"); }} catch (e) {{ console.log(e.name, e.message); }}
}}
// A standalone table imported by another module: its element segment writes into the shared table.
const shared = new WebAssembly.Table({{ initial: 3, element: "anyfunc" }});
shared.set(0, x.double);
const user = new WebAssembly.Instance(new WebAssembly.Module({js_bytes(_table_user_module())}), {{ env: {{ tbl: shared }} }});
console.log("shared", shared.length, user.exports.run(0, 4), user.exports.run(1, 4), shared.get(1)(8), tryCall(user.exports.run, 2, 4));
"""


def test_wasm_tables_call_indirect_and_table_api(run, workdir):
    """CATCHES: call_indirect without signature checks or bounds/null checks, element segments at the
    wrong offset, WebAssembly.Table get/set/length bugs, or imported tables not shared across modules."""
    _check(_run_prog(run, workdir, PROG_TABLES), "tables")


def _imports_module():
    m = Mod()
    log = m.import_func("env", "log", [I32, I64, F32, F64], [])
    twice = m.import_func("env", "twice", [I32], [I32])
    pair = m.import_func("env", "pair", [], [I32, F64])
    m.import_func("env", "boom", [], [])
    big = m.import_func("env", "big", [], [I64])
    m.func([I32], [I32], lget(0) + call(twice) + call(twice), export="quad")
    m.func([], [], i32c(-1) + i64c(2**40) + f32c(0.1) + f64c(0.1) + call(log), export="callLog")
    m.func([], [F64], call(pair) + lset(0) + op(0xB7) + lget(0) + op(0xA0), locals=[F64], export="sumPair")
    m.func([], [], call(3), export="callBoom")
    m.func([], [I64], call(big) + i64c(1) + op(0x7C), export="bigPlusOne")
    start = m.func([], [], i32c(7) + call(twice) + op(0x1A))
    m.start = start
    return m.build()


PROG_IMPORTS = f"""
const calls = [];
const env = {{
  log: (...args) => calls.push("log(" + args.map((a) => typeof a + ":" + fmt(a)).join(",") + ")"),
  twice: (n) => {{ calls.push("twice(" + n + ")"); return n * 2; }},
  pair: () => [3, 0.5],
  boom: () => {{ throw new RangeError("from host"); }},
  big: () => 2n ** 63n - 1n,
}};
const bytes = {js_bytes(_imports_module())};
const mod = await WebAssembly.compile(bytes);
console.log("imports", JSON.stringify(WebAssembly.Module.imports(mod)));
console.log("exports", JSON.stringify(WebAssembly.Module.exports(mod)));
console.log("custom", JSON.stringify(WebAssembly.Module.customSections(mod, "name")));
const inst = await WebAssembly.instantiate(mod, {{ env }});
console.log("start ran", calls.join(" "), inst instanceof WebAssembly.Instance);
calls.length = 0;
console.log("quad", inst.exports.quad(5), calls.join(" "));
calls.length = 0;
inst.exports.callLog();
console.log(calls.join(" "));
console.log("pair", inst.exports.sumPair());
try {{ inst.exports.callBoom(); }} catch (e) {{ console.log("host error", e.name, e.message, e instanceof RangeError); }}
console.log("i64 wraps", fmt(inst.exports.bigPlusOne()));
env.twice = (n) => "21";
console.log("string result coerced", new WebAssembly.Instance(mod, {{ env }}).exports.quad(0));
for (const bad of [{{ env: {{ ...env, twice: 5 }} }}, {{}}, undefined]) {{
  try {{ new WebAssembly.Instance(mod, bad); console.log("no error"); }} catch (e) {{ console.log(e.name, e.message, e instanceof WebAssembly.LinkError); }}
}}
"""


def test_wasm_host_imports_start_function_and_descriptors(run, workdir):
    """CATCHES: wrong JS<->wasm value conversion at import boundaries (i64 as BigInt, f32 rounding),
    start function not run at instantiation, host exceptions swallowed or rewrapped, missing LinkError
    for non-callable imports, or wrong Module.imports/exports descriptors."""
    _check(_run_prog(run, workdir, PROG_IMPORTS), "imports")


# ---------------------------------------------------------------------------------------------
# Decoder / validation errors and API surface
# ---------------------------------------------------------------------------------------------


def _bad_modules():
    hdr = b"\x00asm\x01\x00\x00\x00"
    good = Mod()
    good.func([], [I32], i32c(1), export="one")
    ok = good.build()
    cases = {
        "empty module": hdr,
        "valid": ok,
        "not wasm": b"not wasm at all",
        "too short": b"\x00as",
        "bad version": b"\x00asm\x02\x00\x00\x00",
        "unknown section": hdr + section(13, b""),
        "out of order": hdr + section(3, vec([])) + section(1, vec([])),
        "overrun": hdr + b"\x01\x10\x00",
        "size mismatch": hdr + section(1, vec([]) + b"\x00"),
        "bad functype": hdr + section(1, vec([b"\x61\x00\x00"])),
        "bad valtype": hdr + section(1, vec([b"\x60\x01\x55\x00"])),
        "type idx range": hdr + section(1, vec([b"\x60\x00\x00"])) + section(3, vec([uleb(5)])),
        "code count": hdr + section(1, vec([b"\x60\x00\x00"])) + section(3, vec([uleb(0)])) + section(10, vec([])),
        "body no end": hdr + section(1, vec([b"\x60\x00\x00"])) + section(3, vec([uleb(0)])) + section(10, vec([b"\x02\x00\x01"])),
        "import kind": hdr + section(2, vec([wname("m") + wname("n") + b"\x07"])),
        "export kind": hdr + section(7, vec([wname("e") + b"\x09\x00"])),
        "export range": hdr + section(7, vec([wname("e") + b"\x00\x03"])),
        "global range": hdr + section(7, vec([wname("g") + b"\x03\x00"])),
        "elem kind": hdr + section(9, vec([uleb(5)])),
        "data kind": hdr + section(11, vec([uleb(3)])),
        "const expr": hdr + section(6, vec([bytes([I32, 0]) + b"\x6a\x0b"])),
        "leb overflow": hdr + b"\x01\xff\xff\xff\xff\xff\x7f",
        "custom only": hdr + section(0, wname("meta") + b"xyz"),
        "datacount": hdr + section(12, uleb(0)),
        "bad code body": hdr + section(1, vec([b"\x60\x00\x00"])) + section(3, vec([uleb(0)])) + section(10, uleb(1) + uleb(100) + b"\x00"),
        "mem export range": hdr + section(7, vec([wname("m") + b"\x02\x00"])),
        "table export range": hdr + section(7, vec([wname("t") + b"\x01\x00"])),
        "uleb overflow": hdr + b"\x01" + b"\xff" * 10 + b"\x01",
        "sleb overflow": hdr + section(6, vec([bytes([I32, 0]) + b"\x41" + b"\xff" * 10 + b"\x00\x0b"])),
        "unknown global type": hdr + section(6, vec([bytes([0x55, 0]) + b"\x41\x00\x0b"])),
    }
    return cases


def _bad_cases_js():
    rows = [f"[{k!r}, {js_bytes(v)}]" for k, v in _bad_modules().items()]
    return "[" + ",\n".join(rows) + "]"


PROG_DECODE = f"""
for (const [label, bytes] of {_bad_cases_js()}) {{
  let compiled;
  try {{ new WebAssembly.Module(bytes); compiled = "ok"; }} catch (e) {{ compiled = `${{e.name}}(${{e.message}}) ${{e instanceof WebAssembly.CompileError}}`; }}
  console.log(label.padEnd(16), WebAssembly.validate(bytes), compiled);
}}
"""


def test_wasm_decoder_errors_and_validate(run, workdir):
    """CATCHES: decoders that accept malformed binaries (bad magic/version, misordered or oversized
    sections, bad type/kind bytes, index out of range) or report different CompileError messages, and
    validate() disagreeing with the reference on structurally invalid exports."""
    _check(_run_prog(run, workdir, PROG_DECODE), "decode_errors")


def _unsupported_module():
    m = Mod()
    m.memory(1)
    m.func([], [], b"\xfd\x0c" + b"\x00" * 16 + op(0x1A), export="simd")
    m.func([], [], i32c(0) + i32c(0) + i32c(0) + b"\xfc\x08\x00\x00", export="meminit")
    m.func([], [], b"\xfc\x0c\x00\x00", export="tableinit")
    m.func([], [], op(0x06), export="try")
    m.func([], [I32], i32c(9), export="fine")
    m.func([], [], b"\xd0\x70" + op(0x1A), export="refnull")
    m.func([], [], b"\xfc\x09\x00", export="datadrop")
    m.func([], [], br(5), export="baddepth")
    m.func([], [I32], i32c(1) + b"\x0b" + i32c(2), export="earlyend")
    m.func([], [I32], f64c(1.5) + op(0x45), export="confused_eqz")
    m.func([], [F64], i32c(5) + op(0x9A), export="confused_neg")
    m.func([], [I64], f32c(2.0) + op(0x50) + op(0xAC), export="confused_i64")
    m.func([0x6F], [0x6F], lget(0), export="externref")
    m.func([], [F64], lget(0) + op(0x1A) + lget(2) + op(0x1A) + lget(3) + op(0x1A) + lget(1), locals=[F32, F64, 0x6F, I64], export="typedlocals")
    m.func([], [F32], i32c(1) + op(0x8C), export="confused_f32")
    m.func([], [I32], i32c(3) + b"\x05", export="stray_else")
    return m.build()


def _unbounded_memory_module():
    m = Mod()
    m.memory(0)
    m.func([I32], [I32], lget(0) + op(0x40, 0x00), export="grow")
    m.func([], [I32], op(0x3F, 0x00), export="size")
    return m.build()


def _start_trap_module():
    m = Mod()
    m.func([], [], op(0x00))
    m.start = 0
    return m.build()


def _elem_oob_module():
    m = Mod()
    f = m.func([], [], b"")
    m.table(1)
    m.elem(i32c(1), [f])
    return m.build()


def _data_oob_module():
    m = Mod()
    m.memory(1)
    m.data(i32c(65534), b"abc")
    return m.build()


def _truncated_body_module(body):
    m = Mod()
    m.func([], [], body)
    return m.build()


def _elem_no_table_module():
    m = Mod()
    f = m.func([], [], b"")
    m.elem(i32c(0), [f])
    return m.build()


def _elem_bad_func_module():
    m = Mod()
    m.table(2)
    m.elem(i32c(0), [7])
    return m.build()


def _data_no_memory_module():
    m = Mod()
    m.data(i32c(0), b"x")
    return m.build()


def _global_offset_data_module():
    m = Mod()
    g = m.import_global("env", "off", I32)
    m.memory(1)
    m.data(gget(g), b"at-global")
    m.func([I32], [I32], lget(0) + mem(0x2D), export="byte")
    return m.build()


PROG_API = f"""
const W = WebAssembly;
console.log("namespace", Object.keys(W).sort().join(","));
console.log("classes", [W.CompileError, W.LinkError, W.RuntimeError].map((C) => new C("m").name + ":" + (new C("m") instanceof Error)).join(" "));
const bytes = {js_bytes(_unsupported_module())};
const r = await W.instantiate(bytes.buffer);
console.log("result", Object.keys(r).join(","), r.module instanceof W.Module, r.instance instanceof W.Instance);
const x = r.instance.exports;
for (const n of ["simd", "meminit", "tableinit", "try", "fine", "refnull", "datadrop", "baddepth", "earlyend", "confused_eqz", "confused_neg", "confused_i64", "confused_f32", "typedlocals", "stray_else"]) console.log(n, tryCall(x[n]));
console.log("externref", x.externref({{ any: "object" }}), x.externref(5));
const ub = new W.Instance(new W.Module({js_bytes(_unbounded_memory_module())})).exports;
console.log("unbounded grow", ub.size(), ub.grow(65537), ub.grow(2), ub.size());
const again = await W.instantiate(r.module);
console.log("from module", again instanceof W.Instance, again.exports.fine());
console.log("subarray source", W.validate(new Uint8Array([0, ...bytes, 0]).subarray(1, bytes.length + 1)), W.validate(new DataView(bytes.buffer)));
for (const bad of [() => W.validate("str"), () => new W.Module([0, 97, 115, 109]), () => new W.Instance({{}}), () => W.validate(null)]) {{
  try {{ console.log("returned", bad()); }} catch (e) {{ console.log(e.name, e.message); }}
}}
try {{ await W.compile(new Uint8Array([1, 2, 3, 4])); }} catch (e) {{ console.log("compile rejects", e.name, e.message); }}
try {{ await W.instantiate(new Uint8Array(8)); }} catch (e) {{ console.log("instantiate rejects", e.name, e.message); }}
for (const [label, b] of [["start trap", {js_bytes(_start_trap_module())}], ["elem oob", {js_bytes(_elem_oob_module())}], ["data oob", {js_bytes(_data_oob_module())}],
                          ["elem no table", {js_bytes(_elem_no_table_module())}], ["elem bad func", {js_bytes(_elem_bad_func_module())}], ["data no memory", {js_bytes(_data_no_memory_module())}],
                          ["truncated LEB", {js_bytes(_truncated_body_module(b"\x20"))}], ["truncated blocktype", {js_bytes(_truncated_body_module(b"\x02"))}], ["truncated SLEB", {js_bytes(_truncated_body_module(b"\x41\x80"))}]]) {{
  try {{ new W.Instance(new W.Module(b)); console.log(label, "ok"); }} catch (e) {{ console.log(label, e.name, e.message); }}
}}
const go = new W.Instance(new W.Module({js_bytes(_global_offset_data_module())}), {{ env: {{ off: 100 }} }}).exports;
console.log("data at global offset", String.fromCharCode(...[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => go.byte(100 + i))), go.byte(99));
"""


def test_wasm_api_surface_unsupported_ops_and_link_traps(run, workdir):
    """CATCHES: missing WebAssembly namespace members or error classes, instantiate() not returning
    {module, instance} for bytes, unsupported opcodes (SIMD, memory.init, exceptions) not trapping with the
    reference messages, or start/element/data failures at instantiation reported with the wrong error type."""
    _check(_run_prog(run, workdir, PROG_API), "api_surface")
