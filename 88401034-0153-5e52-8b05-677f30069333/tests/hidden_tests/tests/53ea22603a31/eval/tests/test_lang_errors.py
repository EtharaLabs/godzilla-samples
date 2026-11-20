"""Errors raised by the language itself: exact SyntaxError messages (from eval/new Function and for
whole programs with their line numbers), TypeError/ReferenceError/RangeError messages produced by the
evaluator for property access, calls, constructors, private names, coercions, iteration and
destructuring, and how uncaught language errors are reported. Messages are printed as
`e.name + ': ' + e.message` because the exact text is observable behaviour."""

import pytest

from conftest import assert_golden, assert_result, check_script, resources_for, write_files

G = resources_for(__file__)

TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
         pytest.param(["--tier=bytecode"], id="bytecode")]

SYNTAX_LOOP = r'''
for (const [g, list] of Object.entries(groups)) {
  console.log('## ' + g);
  for (const c of list) {
    try { new Function(c); console.log(JSON.stringify(c), 'ok'); }
    catch (e) { console.log(JSON.stringify(c), e.name + ': ' + e.message, e instanceof SyntaxError); }
  }
}
'''


def test_syntax_errors_general(run, workdir):
    """CATCHES: a parser that accepts invalid programs or reports different SyntaxError messages for
    redeclarations, missing initialisers, bad numeric/string/template/regex tokens, operator-mixing
    rules (?? with ||, unary base of **), invalid assignment/update targets, optional-chain misuse,
    decorators and module-only syntax inside a function body."""
    check_script(run, workdir, G, "syntax_errors_general", r'''
const groups = {
  declarations: ['let a; let a;', 'const x;', 'let let = 1', 'class await {}', 'let x, x', 'var x; let x', 'let x; { var x; }',
    'function f() {} let f', 'const a = 1, a = 2', '{ function g() {} let g; }', '{ function g() {} function g() {} }', 'let [a, a] = []',
    'try {} catch ([e, e]) {}', 'try {} catch (e) { let e; }', 'try {} catch (e) { var e; }', 'const {a} = 1, b;', 'let [a] ', 'var [a] = ',
    'var 1x', '\\u0076ar x = 1', 'x = { #a: 1 }', 'function f(a, a) { "use strict" }', '(a, a) => 1', 'function f(a, ...a) {}'],
  tokens: ['0b12', '0o9', '1__0', '1_', '08n', "'abc", '`abc', '/abc', '/* x', "'\\x4'", "'\\u{110000}'", '"\\u{FFFFFF}"', '`${`', '`${a`',
    '/(?<n>a)(?<n>b)/', '/a{2,1}/', '/\\p{Nope}/u', '/[b-a]/', '/a/gg', '1..', '1.a', '..1', '#!/x\n1', 'a b', 'a\u2028b', 'a\u2029b', 'x = @', '"\\u{1F600"'],
  expressions: ['a ?? b || c', 'a || b ?? c', 'a && b ?? c', '-2 ** 2', 'typeof 2 ** 2', '!a ** 2', '(-2) ** 2', 'await 1', '1 = 2', '++1',
    'a++ = 1', '(a, b) = 1', 'a + 1 = 2', 'this = 1', 'new.target = 1', 'import.meta = 1', 'a?.b = 1', 'a?.b++', 'delete a?.b', '[...a,] = b',
    '({a: 1} = b)', '({a} += 1)', 'x = {a b}', 'x = {a: 1 b: 2}', 'f(a b)', 'f(...)', 'f(,)', '[,,] = []', '({__proto__: 1, __proto__: 2})',
    '({__proto__: 1, ["__proto__"]: 2})', '({__proto__: 1, __proto__})', '({ get a() {}, get a() {} })', 'a => {} + 1', '(a) => {}()',
    'x = function () {} ()', 'new a?.b', 'new a?.b()', 'a?.`x`', 'super.x', 'super()', 'a ? b', 'a ? b :', 'x = 1 2', 'let = 1; let',
    'async () => await', 'function* g() { yield\n* 1 }', 'function* g() { yield = 1 }', 'async function f() { await => 1 }', '({a = 1})',
    'obj = {get a(){}, async *}', '1 +', 'foo(', '(1, 2', '[1, 2', '({a:1', '?', 'x = 1 ++ 2', 'import.foo', '@', 'var x = yield 1'],
  modules: ['import.meta', 'import("a", "b", "c")', 'export default 1', 'import x from "y"', 'export { x }', 'import("a")', 'import.source', 'import.defer("x")'],
};
''' + SYNTAX_LOOP)


def test_syntax_errors_strict_mode(run, workdir):
    """CATCHES: strict-mode early errors not enforced (eval/arguments bindings and assignments, legacy
    octal literals and escapes, delete of identifiers, `with`, duplicate params, strict reserved words,
    labelled/single-statement functions, 'use strict' with non-simple params) or enforced in sloppy code,
    and class bodies not being implicitly strict."""
    check_script(run, workdir, G, "syntax_errors_strict", r'''
const groups = {
  strict: ['"use strict"; var eval = 1', '"use strict"; arguments = 1', '"use strict"; function f(eval) {}', '"use strict"; 010', '"use strict"; "\\07"',
    '"use strict"; delete x', '"use strict"; with (o) {}', '"use strict"; function f(a, a) {}', '"use strict"; var let', '"use strict"; yield = 1',
    '"use strict"; if (1) function f() {}', '"use strict"; label: function f() {}', '"use strict"; ({ eval } = {})', '"use strict"; [arguments] = []',
    '"use strict"; try {} catch (eval) {}', '"use strict"; function eval() {}', '"use strict"; (eval) => 1', '"use strict"; ++arguments',
    'function f() { "use strict"; 08 }', 'function f(a = 1) { "use strict"; }', '"use strict"; var package', '"use strict"; protected: 1',
    '"use strict"; eval--', 'class C { m() { var interface; } }', 'class C { static { var arguments; } }', 'class C { x = arguments; }',
    'class C { m() { with (o) {} } }', 'class C { m() { return 010; } }', '"use strict"; var private', 'function f() { "use strict"; } with (o) {}',
    '"a"; "use strict"; delete x', '"use\\x20strict"; delete x', "'use strict'; static = 1", 'function f(eval) { "use strict"; }'],
  sloppyAllowed: ['var eval = 1', 'arguments = 1', '010', '"\\07"', 'delete x', 'with (o) {}', 'function f(a, a) {}', 'var let', 'yield = 1',
    'if (1) function f() {}', 'label: function f() {}', 'var static, implements, interface, package, private, protected, public'],
};
''' + SYNTAX_LOOP)


def test_syntax_errors_classes_and_private_names(run, workdir):
    """CATCHES: class early errors not raised (duplicate constructors/private names, static prototype,
    field named constructor, #constructor, special-method constructors, accessor arity, misplaced
    super()/super.#x, delete of private refs, undeclared private names, bare private names) or raised
    for valid getter+setter private pairs and optional private access."""
    check_script(run, workdir, G, "syntax_errors_classes", r'''
const groups = {
  classes: ['class A { constructor(){} constructor(){} }', 'class A { #x; #x }', 'class A { get #x() {} get #x() {} }', 'class A { get #x() {} set #x(v) {} }',
    'class A { static #x; #x }', 'class A { static get #x() {} set #x(v) {} }', 'this.#y', 'class A { m() { this.#z } }', 'class A { static prototype(){} }',
    'class A { static prototype = 1 }', 'class A { constructor = 1 }', 'class A { #constructor }', 'class A { get constructor() {} }', 'class A { *constructor() {} }',
    'class A { async constructor() {} }', 'class A { get x(a){} }', 'class A { set x(){} }', 'class A { set x(a, b){} }', 'class A { set x(...a){} }',
    'class A extends B { m() { super(); } }', 'class A { constructor() { super(); } }', 'class A { #x; m() { delete this.#x } }', 'class A { #x; m() { return #x } }',
    'class A { #x; m() { return #x in #x in this } }', 'class A { foo() {} static { super(); } }', 'class A { x = super(); }', 'class A extends B { x = super(); }',
    'class extends A {}', 'class A extends B, C {}', 'class A { static async *#gen() {} static m() { A.#gen = 1; } }', 'class A { #x; static m(o) { return o?.#x } }',
    'class A { #x; static m() { super.#x } }', 'class A { accessor #a; accessor #a; }', 'class A { m() { class B { [this.#q] = 1 } } }',
    'new class { #p; m() { obj.#p } }', 'class A { static { await 1 } }', 'class A { static { return; } }', 'class A { static { arguments; } }',
    'class A { constructor() {} "constructor"() {} }', 'class A { ["constructor"]() {} constructor() {} }', 'class A { static constructor() {} constructor() {} }',
    'class A { #a; m() { #a; } }', 'class A { #a; m(o) { return #a in o; } }', 'class A { m() { return (#a in this); } #a; }', 'class A { x = () => super(); }',
    'class A { #x = 1; static m() { class B { y = this.#x; } } }', 'class A { m() { let x = new.target; } }', 'class A { x = new.target; }',
    'class A { get [x]() {} set [x](v) {} }', 'class A { static async *[Symbol.iterator]() {} }', 'class A { "use strict"() {} }', 'class A { 1() {} 1() {} }'],
};
''' + SYNTAX_LOOP)


def test_syntax_errors_control_flow(run, workdir):
    """CATCHES: missing early errors for break/continue outside loops or to unknown/non-loop labels,
    duplicate labels/defaults, try without catch/finally, newline after throw, bad for-in/of heads
    (initialisers, `async of`, multiple bindings), `for await` outside async code, and keyword misuse
    as bindings in generators/async functions."""
    check_script(run, workdir, G, "syntax_errors_control", r'''
const groups = {
  control: ['break', 'continue', 'x: x: 1', 'while(1) { continue nope }', 'for (const x of y) { break foo }', 'x: { continue x; }', 'x: if (1) { continue x; }',
    'switch (1) { default: default: }', 'switch (1) { case 1: continue; }', 'try {}', 'try {} catch {} catch {}', 'throw\n1', 'return', 'function f() { return } return 1',
    'for (let x of [], []) {}', 'for (let [a] = 1 of []) {}', 'for (var x = 1 of []) {}', 'for (var x = 1 in {}) {}', 'for (const x in {}) {} else {}',
    'do x while(1)', 'if (1) else {}', 'for (async of []) ;', 'for ((async) of []) ;', 'for (let let of []) ;', 'for (x => x in y;;) ;',
    'for await (const x of y) {}', 'async function f() { for await (const x in y) {} }', 'yield: { yield }', 'function* g() { yield: 1 }',
    'async function f() { await: 1 }', 'new.target', 'function f() { new.foo }', 'x: while (1) { (() => { break x; })(); }',
    'x: while (1) { function f() { continue x; } }', 'a: { b: { break a; } }', 'a: b: while (1) continue a;', 'if (1) let x = 1;',
    'while (1) const y = 2;', 'if (1) class C {}', 'label: let\nx', 'do function f() {} while (0)', 'with ({}) function f() {}',
    'for (;;) async function f() {}', 'if (1) async function f() {}', 'switch (1) { case 1: let a; case 2: let a; }', 'try {} finally {} catch {}'],
  generatorsAndAsync: ['function* g() { var yield; }', 'async function f() { var await; }', 'function* g() { function yield() {} }',
    'async function f() { function await() {} }', 'function* g(x = yield) {}', 'async function f(x = await 1) {}', 'async (x = await 1) => x',
    'async function f() { (await) => 1 }', 'function* g() { (yield) => 1 }', 'function* g() { yield\n1 }', 'async function f() { await\n1 }',
    'function* g() { yield yield 1 }', 'function* g() { const x = yield* ; }', 'async function* ag() { yield* await x; for await (const y of z) ; }',
    'async () => { for await (x of y) ; }', 'function f() { await x }', 'function f() { var await; }', 'async function f() { class await {} }'],
};
''' + SYNTAX_LOOP)


def test_syntax_errors_eval_versus_function(run, workdir):
    """CATCHES: eval and new Function reporting different SyntaxError text than the reference for the
    same broken source (eval sees end-of-input, Function bodies see the synthetic closing brace),
    Function parameter strings that can smuggle code past the parameter list, and SyntaxErrors not
    being catchable, instanceof SyntaxError, or leaving earlier eval side effects."""
    check_script(run, workdir, G, "syntax_errors_eval_vs_function", r'''
const sources = ['1 +', 'foo(', 'var [a] = ', 'a ? b :', '{', '}', '(', 'if (', 'function', 'class', 'let', 'x =>', '"use strict"; 010',
  'return 1', 'break', 'new.target', 'super.x', 'yield 1', 'await 1', 'arguments', '/*', '//', '`', '"', "'", '\\', '@'];
for (const s of sources) {
  const viaEval = (() => { try { eval(s); return 'ok'; } catch (e) { return e.name + ': ' + e.message; } })();
  const viaFn = (() => { try { Function(s); return 'ok'; } catch (e) { return e.name + ': ' + e.message; } })();
  console.log(JSON.stringify(s).padEnd(22), '| eval:', viaEval, '| Function:', viaFn);
}
const params = [['a)', '{', 'return 1'], ['/*', '*/){'], ['a = 1', ''], ['a, a', ''], ['...a, b', ''], ['{a}, [b]', 'return a + b'], ['a\n', ''], ['//', 'return 1'],
  ['a /* c */', 'return a'], ['x = () => {', '}']];
for (const p of params) {
  try { const f = Function(...p); console.log(JSON.stringify(p), 'ok length=' + f.length); } catch (e) { console.log(JSON.stringify(p), e.name + ': ' + e.message); }
}
let sideEffect = 0;
try { eval('sideEffect = 1; let y = ;'); } catch (e) { console.log('no partial execution:', sideEffect, e instanceof SyntaxError, e.constructor === SyntaxError); }
try { eval('var ok = 1;\n\nvar bad = ;'); } catch (e) { console.log(e.name + ': ' + e.message, typeof ok); }
''')


@pytest.mark.parametrize("name,src", [
    pytest.param("redeclared_line3", "let a = 1;\nlet b = 2;\nlet a = 3;\n", id="redeclare"),
    pytest.param("after_template_and_comment", "const s = `multi\nline\ntemplate`;\n/* comment\n spanning */ var x = ;\n", id="multiline-tokens"),
    pytest.param("in_function_body", "// c1\n// c2\n\n\nfunction f() {\n  return 1 +;\n}\n", id="function-body"),
    pytest.param("strict_with", "\"use strict\";\nvar o = {\n  a: 1,\n};\nwith (o) {}\n", id="strict-with"),
    pytest.param("unterminated_string", "var s = \"unterminated\n;\n", id="unterminated-string"),
    pytest.param("crlf_lines", "x = 1;\r\ny = 2;\r\nz = ;\r\n", id="crlf"),
    pytest.param("duplicate_private", "class A {\n  m() {}\n  #x; #x;\n}\n", id="dup-private"),
    pytest.param("break_outside", "for (;;) {\n}\nbreak;\n", id="break-outside"),
    pytest.param("eof_after_blank_lines", "1 +\n\n\n", id="eof"),
    pytest.param("decorator_eof", "\n\n\n@", id="decorator"),
    pytest.param("unterminated_comment", "var a = 1;\n/* never\nclosed\n", id="comment"),
    pytest.param("regex_flags", "var ok = /x/g;\nvar bad = /x/q;\n", id="regex-flag"),
])
def test_syntax_error_reporting_with_line_numbers(run, name, src):
    """CATCHES: a lexer that miscounts lines (CRLF, multi-line templates/comments/strings), reports the
    error on a different line or with different text than the reference, runs any part of a program
    that fails to parse, or exits with a code other than 1 (stdin program form: `(line N)` suffix)."""
    r = run([], input=src)
    assert_golden(r.stderr, G / f"lineno_{name}.golden")
    assert r.stdout == b""
    assert r.returncode == 1


def test_type_errors_for_calls_and_constructors(run, workdir):
    """CATCHES: different TypeError messages than the reference for calling non-functions (identifier,
    member, computed and call-result callees), `new` on non-constructors (arrows, methods, async and
    generator functions, Symbol/BigInt/Math), classes called without new, bad iterators/tags, and
    Symbol/BigInt coercions, private member misuse and prototype cycles."""
    check_script(run, workdir, G, "type_errors_calls", r'''
const o = { a: { b: 1 }, n: null, s: 'str', arr: [] };
const cases = {
  ident: () => { const notFn = 5; notFn(); },
  undefIdent: () => { let u; u(); },
  member: () => o.a.b(),
  computed: () => o['a']['b'](),
  computedVar: () => { const k = 'zz'; o[k](); },
  callResult: () => (() => 1)()(),
  optionalMember: () => o.a?.b(),
  newIdent: () => { const notCtor = 1; new notCtor(); },
  newMember: () => new o.a.b(),
  newArrow: () => new (() => 1)(),
  newMethod: () => new ({ m() {} }).m(),
  newAsync: () => new (async function () {})(),
  newGen: () => new (function* () {})(),
  newSymbol: () => new Symbol(),
  newBigInt: () => new BigInt(1),
  newMath: () => new Math(),
  newUndefined: () => new undefined(),
  callClass: () => { class K {} K(); },
  callNull: () => o.n(),
  callString: () => o.s(),
  callArrayMethod: () => o.arr.nope(),
  taggedNotFn: () => { const t = 1; t`x`; },
  superNotCtor: () => { class X extends Object {} Object.setPrototypeOf(X, null); new X(); },
  extendsNonCtor: () => { class X extends (() => {}) {} },
  extendsBadProto: () => { function F() {} F.prototype = 3; class X extends F {} },
  iterNextNotFn: () => { const it = { [Symbol.iterator]() { return { next: 1 }; } }; for (const x of it) {} },
  iterNotFn: () => { const it = { [Symbol.iterator]: 1 }; [...it]; },
  iterReturnsPrim: () => { const it = { [Symbol.iterator]() { return 1; } }; [...it]; },
  applyNonArray: () => Math.max.apply(null, 1),
  hasInstanceNotFn: () => ({}) instanceof { [Symbol.hasInstance]: 1 },
  instanceofPrimitive: () => ({}) instanceof 5,
  inPrimitive: () => 'x' in 'string',
  toPrimitiveNotFn: () => +{ [Symbol.toPrimitive]: 1 },
  toPrimitiveReturnsObj: () => +{ [Symbol.toPrimitive]() { return {}; } },
  ordinaryToPrimitive: () => ({ toString() { return {}; }, valueOf() { return {}; } }) + 1,
  symbolToNumber: () => +Symbol(),
  symbolToString: () => Symbol('d') + '',
  symbolInTemplate: () => `${Symbol('t')}`,
  bigintToNumber: () => +1n,
  bigintMix: () => 1n + 1,
  bigintMixedCompare: () => 1n < 2 ? 'cmp ok' : '',
  bigintUnsignedShift: () => 1n >>> 0n,
  bigintDivZero: () => 1n / 0n,
  privateOnPrimitive: () => { class P { #x = 1; static r(o) { return o.#x; } } P.r(1); },
  privateOnOther: () => { class P { #x = 1; static r(o) { return o.#x; } } P.r({}); },
  privateWriteOther: () => { class P { #x = 1; static w(o) { o.#x = 2; } } P.w({}); },
  privateMethodWrite: () => { class P { #m() {} static w(o) { o.#m = 1; } } P.w(new P()); },
  privateGetterOnlyWrite: () => { class P { get #g() { return 1; } static w(o) { o.#g = 1; } } P.w(new P()); },
  privateSetterOnlyRead: () => { class P { set #s(v) {} static r(o) { return o.#s; } } P.r(new P()); },
  privateInPrimitive: () => { class P { #x; static h(o) { return #x in o; } } P.h('str'); },
  superPropNullProto: () => { const obj = { m() { return super.x; } }; Object.setPrototypeOf(obj, null); obj.m(); },
  constAssign: () => { const c = 1; c = 2; },
  constInLoop: () => { for (const i = 0; i < 2; i++) {} },
  constCompound: () => { const c = 1; c += 1; },
  constDestructure: () => { const c = 1; [c] = [2]; },
  setPrototypeCycle: () => { const a = {}; const b = Object.create(a); Object.setPrototypeOf(a, b); },
  protoAssignCycle: () => { const a = {}; const b = Object.create(a); a.__proto__ = b; },
  readUndefined: () => undefined.foo,
  readNull: () => null.foo,
  readNested: () => ({}).x.y.z,
  writeUndefined: () => { let u; u.x = 1; },
  writeNullComputed: () => { const n = null; n['k'] = 1; },
  readSymbolKeyOfNull: () => null[Symbol.iterator],
  destructureNullParam: () => (({ a }) => a)(null),
  destructureNullVar: () => { const { a } = null; },
};
for (const [k, f] of Object.entries(cases)) {
  try { const r = f(); console.log(k.padEnd(24), 'returned', String(r)); }
  catch (e) { console.log(k.padEnd(24), e.constructor.name, e.name + ': ' + e.message); }
}
''')


@pytest.mark.parametrize("cli", TIERS)
def test_runtime_error_messages_agree_across_tiers(run, workdir, cli):
    """CATCHES: an execution tier whose hot-path (looped, JIT/bytecode-compiled) code throws different
    error types/messages than the tree-walker for not-a-function calls, null property reads/writes,
    TDZ reads, const writes and BigInt mixing, or that leaves a loop in a different state after the
    throw."""
    check_script(run, workdir, G, "errors_across_tiers", r'''
const good = { f() { return 1; }, v: { w: 1 } }, bad = { f: 7, v: null };
function hot(kind, i) {
  const o = i < 150 ? good : bad;
  switch (kind) {
    case 'call': return o.f();
    case 'read': return o.v.w;
    case 'write': o.v.w = i; return i;
    case 'tdz': { if (i >= 150) return later; let later = i; return later; }
    case 'const': { const c = 0; if (i >= 150) c = i; return c; }
    case 'bigint': return (i >= 150 ? 1n : 1) + 1;
    case 'ident': return i >= 150 ? missingGlobal : i;
    case 'new': return new (i >= 150 ? o.f : Object)();
    case 'symbol': return (i >= 150 ? Symbol('s') : 's') + '';
    case 'iter': { const [a] = i >= 150 ? 5 : [i]; return a; }
  }
}
for (const kind of ['call', 'read', 'write', 'tdz', 'const', 'bigint', 'ident', 'new', 'symbol', 'iter']) {
  let completed = 0;
  try { for (let i = 0; i < 200; i++) { hot(kind, i); completed++; } console.log(kind, 'no error'); }
  catch (e) { console.log(kind.padEnd(7), completed, e.constructor.name, e.name + ': ' + e.message); }
}
function sumTo(n) { let s = 0; for (let i = 0; i < n; i++) s += i; return s; }
console.log('loop still fine', sumTo(1000));
''', cli=cli)


def test_reference_errors(run):
    """CATCHES: wrong ReferenceError behaviour: undeclared reads/calls/strict writes, TDZ for let/const/
    class in all positions (typeof, closures, default params, class heritage, own initialiser), sloppy
    writes creating globals instead of throwing, `delete` of unresolvable names, and the messages."""
    src = r'''
const cases = {
  undeclaredRead: () => undeclaredThing,
  undeclaredCall: () => undeclaredFn(1),
  undeclaredMember: () => undeclaredObj.prop,
  undeclaredStrictWrite: () => { 'use strict'; neverDeclared = 1; },
  undeclaredCompound: () => { undeclaredCounter += 1; },
  undeclaredUpdate: () => { undeclaredCounter2++; },
  sloppyWriteCreatesGlobal: () => { createdGlobal = 'yes'; return globalThis.createdGlobal; },
  typeofUndeclared: () => typeof alsoUndeclared,
  deleteUndeclared: () => delete notThere,
  tdzLet: () => { x; let x = 1; },
  tdzConst: () => { const f = () => y; f(); const y = 1; },
  tdzClass: () => { new C(); class C {} },
  tdzTypeof: () => { typeof z; let z; },
  tdzDefaultParam: () => ((a = b, b) => a)(),
  tdzHeritage: () => { class D extends D {} },
  tdzOwnInit: () => { let w = w; },
  tdzDestructure: () => { let { [k]: v } = {}, k = 'a'; },
  tdzForOfHead: () => { for (let q of [q]) ; },
  tdzSwitch: () => { switch (1) { case 0: let s = 1; break; case 1: s = 2; } },
  tdzAssign: () => { t = 1; let t; },
  tdzInGlobalLexical: () => laterGlobalLet,
  withUnscopableMiss: () => { with ({ [Symbol.unscopables]: { hidden: true }, hidden: 1 }) { return hidden; } },
  evalUndeclared: () => eval('nowhere'),
  functionUndeclared: () => Function('return nowhereFn()')(),
};
for (const [k, f] of Object.entries(cases)) {
  try { const r = f(); console.log(k, '->', 'returned', String(r)); }
  catch (e) { console.log(k, '->', e.constructor.name, e.name + ': ' + e.message); }
}
let laterGlobalLet = 'initialised';
console.log(cases.tdzInGlobalLexical());
'''
    assert_result(run([], input=src), G / "reference_errors.golden")


def test_iteration_and_destructuring_errors(run, workdir):
    """CATCHES: different TypeError messages than the reference for spreading/destructuring/for-of over
    non-iterables, null and undefined (including the reference's internal Symbol.iterator key text),
    non-object iterator results, bad Map/Set entries, async iteration of non-iterables and
    object-destructuring of null/undefined."""
    check_script(run, workdir, G, "iteration_errors", r'''
const attempts = {
  spreadNull: () => [...null],
  spreadUndefinedArg: () => Math.max(...undefined),
  spreadNumber: () => [...123],
  spreadObject: () => [...{}],
  forOfNumber: () => { for (const x of 5) ; },
  forOfObject: () => { for (const x of { a: 1 }) ; },
  arrayPatternNull: () => { const [a] = null; },
  arrayPatternObject: () => { const [a] = {}; },
  arrayPatternArrayLike: () => { const [a] = { 0: 'x', length: 1 }; },
  objectPatternNull: () => { const { a } = null; },
  objectPatternUndefined: () => { const { a } = undefined; },
  nestedPatternMissing: () => { const { a: { b } } = {}; },
  paramPatternMissing: () => (({ a: [b] }) => b)({}),
  mapBadEntry: () => new Map([1]),
  mapNonIterable: () => new Map(5),
  setNonIterable: () => new Set(5),
  arrayFromNonCallableIterator: () => Array.from({ [Symbol.iterator]: 'x' }),
  nextReturnsPrimitive: () => { for (const x of { [Symbol.iterator]() { return { next() { return 3; } }; } }) ; },
  yieldStarNonIterable: () => (function* () { yield* 5; })().next(),
  promiseAllNonIterable: () => Promise.all(5).catch(e => console.log('promise rejected:', e.name + ': ' + e.message)),
  stringFromCodePointBad: () => String.fromCodePoint(-1),
};
for (const [k, f] of Object.entries(attempts)) {
  try { const r = f(); console.log(k.padEnd(28), 'no error', r instanceof Promise ? 'promise' : String(r)); }
  catch (e) { console.log(k.padEnd(28), e.name + ': ' + e.message); }
}
(async () => {
  for (const [label, src] of [['forAwaitNumber', 5], ['forAwaitNull', null], ['forAwaitBadAsyncIter', { [Symbol.asyncIterator]() { return 1; } }]]) {
    try { for await (const x of src) ; console.log(label, 'no error'); } catch (e) { console.log(label.padEnd(28), e.name + ': ' + e.message); }
  }
})();
''')


def test_stack_overflow_is_a_catchable_range_error(run):
    """CATCHES: unbounded recursion that crashes the process (native stack overflow/abort) instead of
    throwing a catchable RangeError with the reference message, or a runtime that cannot continue
    executing normally after unwinding."""
    src = ("function f() { return f(); }\n"
           "try { f(); } catch (e) { console.log(e instanceof RangeError, e.name + ': ' + e.message); }\n"
           "function depth(n) { return n === 0 ? 0 : 1 + depth(n - 1); }\n"
           "console.log('after overflow', depth(200));\n")
    r = run(["-e", src])
    assert r.stdout == b"true RangeError: Maximum call stack size exceeded\nafter overflow 200\n"
    assert r.stderr == b""
    assert r.returncode == 0


@pytest.mark.parametrize("name,src", [
    pytest.param("uncaught_from_generator", "function* g() { yield 1; throw new RangeError('from generator body'); }\n"
                 "const it = g(); console.log(it.next().value);\nit.next();\nconsole.log('unreachable');\n", id="generator"),
    pytest.param("uncaught_from_getter", "const o = { get bad() { throw new TypeError('getter failed'); } };\n"
                 "console.log('before');\nconst { bad } = o;\n", id="getter"),
    pytest.param("uncaught_from_constructor", "class Base { constructor() { console.log('base ctor'); } }\n"
                 "class D extends Base { constructor() { console.log('derived ctor'); } }\nnew D();\n", id="constructor"),
    pytest.param("uncaught_from_finally", "try { throw new Error('original'); } finally { console.log('finally runs'); }\n", id="finally"),
    pytest.param("uncaught_runtime_syntax_error", "console.log('start');\neval('let = = 1');\n", id="eval-syntax"),
    pytest.param("uncaught_tdz", "console.log('start');\nfoo;\nlet foo = 1;\n", id="tdz"),
])
def test_uncaught_language_errors(run, name, src):
    """CATCHES: language errors escaping to the top level of a stdin program being reported with a
    different `Uncaught <Name>: <message>` line, printing output that follows the throw point, losing
    output printed before it, or exiting with a status other than 1."""
    r = run([], input=src)
    assert_result(r, G / f"{name}.golden", rc=1, stderr=G / f"{name}.stderr.golden")


MODULE_ERROR_SOURCES = [
    'export const a = 1; export { a };',
    'export { nope };',
    'export default 1; export default 2;',
    'import { a } from "./dep.mjs"; import { a } from "./dep.mjs";',
    'export { a as "\\uD800" } from "./dep.mjs";',
    'import { "str" } from "./dep.mjs";',
    'import j from "./dep.json" with { type: "json", type: "json" };',
    'import j from "./dep.json" with { type: 1 };',
    'with ({}) {}',
    'var await = 1;',
    'var x = 1; <!-- html comment',
    'import * from "./dep.mjs";',
    'if (1) { export const z = 1; }',
    'export function () {}',
]


def test_module_early_errors(run, workdir):
    """CATCHES: ES module early errors not raised before any code runs (duplicate/undeclared exports,
    duplicate import bindings and attribute keys, non-identifier import bindings, ill-formed string
    export names, implicit strictness, `await` as an identifier, HTML comments, nested exports), or
    reported with a different `Uncaught SyntaxError: <message>` text or exit status."""
    write_files(workdir, {"dep.mjs": "export const a = 1;\n", "dep.json": '{"k": 1}\n'})
    lines = []
    for i, src in enumerate(MODULE_ERROR_SOURCES):  # 14 short runs
        name = f"bad{i}.mjs"
        (workdir / name).write_text(src + "\n")
        r = run([name])
        lines.append(f"{src}\n  rc={r.returncode} stdout={r.stdout.decode()!r} stderr={r.stderr.decode()!r}\n")
    assert_golden("".join(lines).encode(), G / "module_early_errors.golden")
