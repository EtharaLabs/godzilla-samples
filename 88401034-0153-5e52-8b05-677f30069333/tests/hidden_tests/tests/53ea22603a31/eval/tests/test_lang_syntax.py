"""JavaScript source-level syntax: the lexer (numeric/string/template/regex literals, comments,
unicode escapes, hashbang, HTML-like comments) and the parser (ASI, contextual keywords, object
literals, arrows, destructuring patterns, precedence, decorators, Function.prototype.toString source
text). Values are printed with JSON.stringify/join because console.log uses plain ToString."""

import pytest

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)

TIERS = [pytest.param([], id="default"), pytest.param(["--tier=interp"], id="interp"),
         pytest.param(["--tier=bytecode"], id="bytecode")]


def test_numeric_literal_forms(run, workdir):
    """CATCHES: a lexer that mis-reads hex/octal/binary prefixes (upper or lower case), legacy octal
    (017) vs non-octal decimal (019, 08), numeric separators, exponent forms, leading/trailing dots,
    BigInt literals in every radix, number-to-string of huge/tiny values, or `1..toString()`."""
    check_script(run, workdir, G, "numeric_literals", r'''
const vals = [0x1F, 0XfF, 0o17, 0O7, 0b1011, 0B1, 017, 019, 08, 0.5e3, .25, 5., 1e-7, 1E21,
  123456789012345678901234567890, 1_000_000, 0xdead_beef, 0b1010_0101, 0o7_7, 1_0.0_1e1_0, 2**53+1,
  0.1+0.2, 5e-324, 1.7976931348623157e308, 1e400, 0.000001, 1e-6 * 10, 1e21 / 10, 0x7fffffff + 1];
console.log(vals.join(' '));
const big = [0n, 123n, 0x1Fn, 0o17n, 0b101n, 1_000n, 9007199254740993n, -(2n**64n), 0xFFFF_FFFFn];
console.log(big.map(String).join(' '), typeof 1n);
console.log(1..toString(), 1.5.toFixed(2), 0x10.toString(2), 5 .toString(), (255).toString(16), 1e3.toString(36));
console.log(Object.keys({0x10: 'a', 1e3: 'b', .5: 'c', 1_0: 'd', 0b11n: 'e', 1.0: 'f'}).join());
console.log(-0 === 0, Object.is(-0, 0), 1/-0, 077 === 63, 0o77 === 63, 0.1 * 3, 9007199254740993, 2**-1074);
const bad = ['0x', '0b2', '0o8', '1__0', '1_', '_1', '0_1', '08n', '1.5n', '1e3n', '0b', '1e', '1e+', '07_7',
  '3in x', '0xg', '1n_', '.e1', '09.5', '2.e3'];
for (const src of bad) {
  try { const v = eval(src); console.log(JSON.stringify(src), 'ok', String(v)); }
  catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_string_literal_escapes(run, workdir):
    """CATCHES: wrong decoding of \\x, \\u, \\u{...} (with leading zeros / astral), legacy octal and
    \\8 \\9 escapes, line continuations, identity escapes, or bad-escape errors; UTF-16 lengths of
    astral characters."""
    check_script(run, workdir, G, "string_escapes", r'''
const s = ['\x41B\u{43}\u{1F600}', '\0', 'a\
b', '\101\7', '\8\9', "\'\"\\\b\f\n\r\t\v", '\q\
', '\u{0000000041}', '😀', 'é́', '\1234', "it's", 'say "hi"', '\u2028  '];
for (const x of s) console.log(JSON.stringify(x), x.length);
console.log('😀' === '\u{1F600}', '😀'.length, [...'😀a'].length, '\uD83D'.length, JSON.stringify('\uD83D'));
for (const src of ["'\\x4'", "'\\xZZ'", "'\\u12'", "'\\u{}'", "'\\u{110000}'", "'\\u{1F600'", "'abc", "'line\nbreak'",
                   "'use strict'; '\\07'", "'use strict'; '\\8'", "'use strict'; '\\0'"]) {
  try { console.log(JSON.stringify(src), 'ok', JSON.stringify(eval(src))); }
  catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_template_literals_and_tagged_templates(run, workdir):
    """CATCHES: template literals with nested templates/braces mis-lexed, raw vs cooked strings wrong,
    invalid escapes in tagged templates not producing an undefined cooked value (or wrongly throwing),
    CRLF not normalised to LF in both cooked and raw, template objects not cached per site/frozen,
    or member-expression tags losing their `this`."""
    check_script(run, workdir, G, "template_literals", r'''
const tag = (strs, ...vals) => JSON.stringify({cooked: strs, raw: strs.raw, vals});
console.log(tag`a${1}b${2}c`);
console.log(tag`\unicode and \u{`);
console.log(tag`\x0g${'v'}\01`);
console.log(tag``, tag`${0}`);
console.log(String.raw`\n${1+1}\tA`, String.raw`a\
b`.length, String.raw({ raw: ['x', 'y', 'z'] }, 1, 2, 3));
console.log(`line1
line2`.split('\n').length, `a${`b${`c`}`}d`, `${1}${2}`, `\``, `$`, `$\{x}`, `${'}'}`, `{${'{'}}`, `${{a: 1}.a}`);
function id(s) { return s; }
const objs = []; for (let i = 0; i < 2; i++) objs.push(id`same`);
console.log(objs[0] === objs[1], id`same` === id`same`, Object.isFrozen(objs[0]), Object.isFrozen(objs[0].raw), Array.isArray(objs[0]));
console.log(new Function("return `x\r\ny`")().length, eval("String.raw`p\r\nq`").charCodeAt(1), eval("`a\rb`").charCodeAt(1));
const o = { m() { return this.v; }, v: 7 };
console.log(`${o.m()}` + o.m`x`, (function(){ return typeof this; })`t`, (s => s.length)`a${1}b${2}c`);
const chain = (s) => (t) => s[0] + t[0];
console.log(chain`first``second`, `${[1, 2]}`, `${null} ${undefined} ${true}`, `${{ toString() { return 'TS'; } }}`);
try { eval('`\\unicode`'); } catch (e) { console.log(e.name + ': ' + e.message); }
try { `${Symbol('s')}`; } catch (e) { console.log(e.name + ': ' + e.message); }
for (const src of ['`abc', '`${1', '`${`', 'a?.b`t`']) {
  try { eval(src); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_regex_literal_vs_division(run, workdir):
    """CATCHES: a lexer that cannot tell `/` division from a regex literal after identifiers, `)`, `]`,
    keywords or across a newline, mis-terminates a regex containing `/` inside a class, or drops flags
    (d, g, i, m, s, u, v, y)."""
    check_script(run, workdir, G, "regex_vs_division", r'''
const a = 10, b = 2, g = 5;
console.log(a / b / g, a /b/ g, a/b/g);
const r1 = /[/\]]+/g; console.log(r1.source, r1.flags, '/]/]x'.match(r1).join('|'));
const r2 = /a\/b/i; console.log(r2.source, r2.test('A/B'), String(/\//), RegExp('/').source, new RegExp('').source);
console.log(/(?<year>\d{4})-(?<m>\d\d)/u.exec('on 2024-05!').groups.year, /x/dgimsuy.flags, /x/v.flags);
let x = 1
/2/1; console.log(x);
const t = typeof /re/; console.log(t, [/a/][0].source, {k: /b/}.k.source);
if (/x/.test('x')) console.log('regex after paren');
const arr = [1]; console.log(arr[0] /1/ 1);
console.log(`${/t/.source}`, ((/q/)).source, !/z/.test('a'), void /a/, typeof /=/, /=/.source, /[*]/.test('*'));
let y = 4; y /= 2; console.log(y);
function f() { return /ret/.source; } console.log(f(), 1 + /a/.source.length);
const re3 = /a/g; console.log(re3 === /a/g, re3.lastIndex, re3.test('aa'), re3.lastIndex);
for (const src of ['/abc', '/a/gg', '/a/x', '/(/', '/[/', '/\\', 'x = /a\n/']) {
  try { eval(src); console.log(JSON.stringify(src), 'ok'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_automatic_semicolon_insertion(run, workdir):
    """CATCHES: ASI applied where it must not be (a line starting with `(`, `[` or a template continues
    the previous expression) or not applied where required (after `return`, before `++`/`--` on the next
    line, after `do-while`, `let` followed by a newline), and restricted productions like `throw`."""
    check_script(run, workdir, G, "asi_rules", r'''
function r1() { return
  42 }
console.log(r1());
let a = 1, b = 2
a
++b
console.log(a, b)
const f = () => 'f'
const c = f
(function(){ return 'called' })
console.log(c)
let d = [1,2]
;[d[0], d[1]] = [d[1], d[0]]
console.log(d.join())
var i = 0
do i++; while (i < 3) console.log('do', i)
const tagFn = (s) => 'tagged:' + s[0]
const h = tagFn
`t`
console.log(h)
let x = 5
x
--
x
console.log(x)
let
y = 3
console.log(y)
var async = 'v'; async
function q() {}
console.log(async)
label1:
for (;;) { break
label1 }
console.log('after')
var n = 1, m = 2, k = 3
n = m
+k
console.log(n)
var obj = { v: 1 }
var w = obj
.v
console.log(w)
const fnExpr = function () { return 'E' }
console.log(fnExpr())
for (const src of ['throw\nnew Error("x")', 'a\n++\nb\n++', 'for (;;\n) {}', 'let x = 1 let y = 2', 'if (1) \n else 2', 'x\n=>1']) {
  try { new Function(src); console.log(JSON.stringify(src), 'parses'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_hashbang_and_html_like_comments(run, workdir):
    """CATCHES: rejecting a hashbang line, not treating `<!--` and a line-leading `-->` as single-line
    comments in sloppy scripts, treating `x --> 0` (decrement-then-compare) as a comment, or wrongly
    accepting HTML-like comments in ES modules."""
    check_script(run, workdir, G, "html_comments",
                 '#!/usr/bin/env lumen-cli\n'
                 'var x = 1; <!-- html open comment console.log("hidden")\n'
                 'console.log("a", x);\n'
                 '--> html close comment at line start\n'
                 '  /* c */ --> also after block comment\n'
                 'console.log(x --> 0, x);\n'
                 '/* multi\nline */ --> after multiline comment\n'
                 'var y = 3; y<!--y\n'
                 'console.log("end", y, eval("1 <!-- 2\\n--> 3\\n+ 4"));\n')
    mod = run(["-e", "console.log(1); /* x */ #!/bin/no\n"])
    workdir.joinpath("m.mjs").write_text("var x = 1; <!-- no\nconsole.log(x)\n")
    esm = run(["m.mjs"])
    assert (mod.stdout, mod.stderr, mod.returncode) == (b"", b"SyntaxError: expected ';' (line 1)\n", 1)
    assert (esm.stdout, esm.stderr, esm.returncode) == (b"", b'Uncaught SyntaxError: unexpected token Punct("<")\n', 1)


def test_unicode_identifiers_and_escapes(run, workdir):
    """CATCHES: identifiers with \\u/\\u{} escapes, non-ASCII letters, astral letters, ZWNJ/ZWJ not
    accepted, escaped identifiers not equal to their plain spelling, or escaped keywords/invalid escape
    characters accepted instead of throwing SyntaxError."""
    check_script(run, workdir, G, "unicode_identifiers", r'''
var abc = 1; console.log(abc, \u{61}bc, abc);
const café = 'x'; console.log(café);
const ünïcödé = 2, $ = 3, _ = 4, ℮ = 5, 𝑥 = 6; console.log(ünïcödé + $ + _ + ℮ + 𝑥);
const o = { if: 1, class: 2, 'a b': 3, class2: 4 }; console.log(o.if, o["class"], o['a b'], o.class2, o.if);
console.log(Object.keys({ \u{1d465}: 1 })[0] === '𝑥');
var ab‌c = 7, x‍ = 8; console.log(ab‌c, x‍, 'ab‌c'.length);
class K { #priv = 9; #q = 10; get p() { return this.#priv + this.#q; } } console.log(new K().p);
const 日本 = 'jp'; console.log(日本, '日本'.length);
console.log(eval('var \\u{62}c = 1; bc'));
for (const bad of ['var a\\u0020b', 'var \\u0031x', 'var a\\u{zz}', 'var \\u0066or = 1', 'var x\\u', 'var \\u{110000}',
                   '\\u0069f (1) {}', 'var a = n\\u0065w Object()', 'var x = { g\\u0065t y() {} }', 'var 1a', 'var a€', 'var ⸯ']) {
  try { eval(bad); console.log('ok', bad); } catch (e) { console.log(bad, '->', e.name + ': ' + e.message); }
}
''')


def test_contextual_keywords_as_identifiers(run):
    """CATCHES: a parser that reserves contextual words (let, yield, await, async, of, get, set, static,
    using, accessor, ...) outside the contexts where they are keywords, rejects keywords as property
    names or class member names, or mis-handles `async` followed by a newline."""
    src = r'''
var let_ok = (function () { var let = 1; let += 1; return let; })(); console.log(let_ok);
var yield = 'yield ident', await = 'await ident', of = 'of ident', get = 'g', set = 's', static = 'st', implements = 'impl', package = 'pkg', target = 't', meta = 'm', from = 'f', as = 'a', accessor = 'acc';
console.log(yield, await, of, get, set, static, implements, package, target, meta, from, as, accessor);
for (var of of [1]) console.log('of of', of);
const using = 'using ident'; console.log(using);
let async = 1; async
++async; console.log(async);
function* g() { const o = { yield: 1 }; yield o.yield; } console.log([...g()].join());
async function af() { const o = { await: 2 }; return o.await; } af().then(v => console.log('await prop', v));
class Kw { get() { return 'get m'; } set() { return 'set m'; } static() { return 'static m'; } static static() { return 'static static'; } async() { return 'async m'; } get get() { return 'getter get'; } }
const kw = new Kw(); console.log(Kw.prototype.set(), kw.static(), Kw.static(), kw.async(), kw.get);
class Fields { static = 1; get = 2; set; async = 3; accessor = 4; 'quoted' = 5; 42 = 6; [`c`] = 7; } console.log(JSON.stringify(new Fields()), 'set' in new Fields());
const o = { if: 1, else: 2, for: 3, while: 4, function: 5, class: 6, return: 7, typeof: 8, delete: 9, in: 10, instanceof: 11, null: 12, true: 13, this: 14, super: 15, import: 16, export: 17, enum: 18 };
console.log(Object.values(o).join(), o.if + o.null + o.true + o.enum);
label: { break label; } yield: for (;;) break yield; console.log('labels named like keywords ok');
console.log((function () { var arguments = 'shadowed'; return arguments; })(), (function eval() { return typeof eval; })());
var as = 'escaped as ident'; console.log(as);
for (const src of ['function* g() { var yield; }', 'async function f() { var await; }', '"use strict"; var let = 1', '"use strict"; var static',
                   '"use strict"; var implements', 'let [let] = []', 'class C { m() { var yield; } }', 'async function f() { function await() {} }',
                   'function* g() { function yield() {} }', 'var enum', 'let\nlet = 1', 'for (let of of []) ;', 'for (let in {}) ;']) {
  try { new Function(src); console.log(JSON.stringify(src), 'parses'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
'''
    assert_result(run([], input=src), G / "contextual_keywords.golden")


def test_object_literal_forms(run, workdir):
    """CATCHES: wrong own-key ordering (integer keys first, then strings, then symbols), computed and
    numeric keys not canonicalised, `__proto__: x` vs shorthand/computed `__proto__` confusion,
    spread copying non-enumerable or inherited props or invoking setters, function name inference,
    and methods being constructible."""
    check_script(run, workdir, G, "object_literals", r'''
const k = 'dyn', sym = Symbol('s');
let getterCalls = 0;
const base = { inherited: 1 };
const o = {
  plain: 1, 'quoted key': 2, 3: 'three', 1.5: 'float', [k + 'amic']: 4, [sym]: 'symval',
  k, method() { return 'm:' + this.plain; }, get acc() { getterCalls++; return 'got'; }, set acc(v) { this._acc = v; },
  async am() {}, *gm() { yield 1; }, async *agm() {}, [`t${1}`]: 'templ', __proto__: base, 'get'() { return 'named get'; },
  get() { return 'method named get'; }, set: 'prop named set', async: 'prop named async', static: true, new: 'kw', 0b11: 'bin', 0x10: 'hex',
};
console.log(Object.keys(o).join('|'));
console.log(o.dynamic, o[sym], o.k, o.method(), o.acc, getterCalls, o.t1, o.inherited, Object.getPrototypeOf(o) === base, o.get(), o[3], o['1.5'], o[16], o.new);
o.acc = 'v'; console.log(o._acc, typeof Object.getOwnPropertyDescriptor(o, 'acc').get, o.gm().next().value, Object.prototype.toString.call(o.agm()));
const spreadSrc = { a: 1, get b() { return 'getter run'; } };
Object.defineProperty(spreadSrc, 'hidden', { value: 'x', enumerable: false });
const target = { set a(v) { console.log('setter must not run'); } };
const s = { ...target, ...spreadSrc, a: 2, ...null, ...undefined, ...'hi', ...[9], ...{ [sym]: 'sym copied' } };
console.log(JSON.stringify(s), s[sym], Object.getOwnPropertyDescriptor(s, 'b').value, 'hidden' in s);
const dup = { x: 1, x: 2, ['x']: 3 }; console.log(dup.x, Object.keys(dup).length);
const accDup = { get p() { return 'getter'; }, p: 'data' }; console.log(accDup.p, typeof Object.getOwnPropertyDescriptor(accDup, 'p').get);
const protoKeys = { ['__proto__']: 'computed', }; console.log(Object.getPrototypeOf(protoKeys) === Object.prototype, Object.keys(protoKeys).join());
const __proto__ = 'shorthand'; const sh = { __proto__ }; console.log(Object.keys(sh).join(), sh.__proto__ === 'shorthand');
const nullProto = { __proto__: null, a: 1 }; console.log(Object.getPrototypeOf(nullProto), 'toString' in nullProto);
const notObjProto = { __proto__: 5 }; console.log(Object.getPrototypeOf(notObjProto) === Object.prototype);
const order = { b: 1, 2: 'two', a: 2, 1: 'one', [Symbol.iterator]: 0, '-1': 'neg', '01': 'lead', 4294967295: 'big', 4294967294: 'maxidx' };
console.log(Reflect.ownKeys(order).map(String).join());
const fnNames = { a: function () {}, b: () => {}, c: class {}, ['d' + 1]: function () {}, [sym]: function () {}, e: function named() {}, get g() {}, 7: () => {} };
console.log(Object.values(fnNames).map(f => JSON.stringify(f && f.name)).join(), fnNames[sym].name, Object.getOwnPropertyDescriptor(fnNames, 'g').get.name);
const trailing = { a: 1, }, arrT = [1, 2, ,], arrHoles = [, , 1]; console.log(Object.keys(trailing).length, arrT.length, arrHoles.length, 0 in arrHoles, JSON.stringify(arrHoles));
const methodsNotConstructable = { m() {} }; try { new methodsNotConstructable.m(); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log('prototype' in methodsNotConstructable.m, 'prototype' in function () {}, 'prototype' in (() => {}), 'prototype' in o.gm);
''')


def test_arrow_function_forms(run, workdir):
    """CATCHES: arrows whose `{` body is mistaken for an object literal (or vice versa), lexical
    this/arguments not captured, parameter defaults that cannot see earlier params, async arrows vs a
    function named `async`, and the line-terminator restrictions around `=>` and `async`."""
    check_script(run, workdir, G, "arrow_functions", r'''
const f1 = () => ({ obj: true }); const f2 = () => { obj: true }; const f3 = x => y => x + y;
const f4 = ({ a, b: [c] = [9] } = {}, ...rest) => [a, c, rest.length];
const f5 = async (x) => await x * 2; const f6 = async x => x; const f7 = async () => {};
console.log(JSON.stringify(f1()), f2(), f3(1)(2), JSON.stringify(f4()), JSON.stringify(f4({ a: 1, b: [2] }, 3, 4)));
var async = (x) => 'async ident called with ' + x; console.log(async(5), typeof f6, f7.constructor.name);
const thisCap = { v: 'outer', m() { return [1].map(() => this.v)[0]; }, n() { 'use strict'; return (function () { return this; })(); } }; console.log(thisCap.m(), thisCap.n());
const argsCap = function () { return (() => arguments[0])(); }; console.log(argsCap('captured arg'));
const nested = (a = 1, b = a + 1, c = (() => a + b)()) => a + b + c; console.log(nested(), nested(10), nested(1, 1));
const comma = (a, b) => (a, b); console.log(comma(1, 2), ((a, b,) => a + b)(1, 2), (() => {})(), ((...[x, y]) => x * y)(3, 4));
const condArrow = true ? () => 'yes' : () => 'no'; console.log(condArrow());
const arr = [1, 2, 3].map((x, i) => x * i).filter(x => x).reduce((a, b) => a + b); console.log(arr);
console.log(typeof (() => {}).prototype, (() => {}).hasOwnProperty('prototype'), ((a, b) => {}).length);
f5(4).then(v => console.log('async arrow', v));
const iife = (() => 'iife')(); const iife2 = (function () { return 'iife2'; })(); const iife3 = (function () { return 'iife3'; }()); console.log(iife, iife2, iife3);
try { new (() => {})(); } catch (e) { console.log(e.name + ': ' + e.message); }
for (const src of ['(a, b) \n => a', 'async x \n => x', 'async \n x => x', '() => {} ()', '(a = yield) => a', 'x => { "use strict"; with (x) {} }',
                   '((a)) => 1', '(...a, b) => 1', '(a, ...b,) => 1', 'async (a, a) => 1', 'async await => 1', '({a}) = 1', '(a, b) => { let a; }',
                   '(a = 1, {b} = {}) => { "use strict" }', 'async (x = await 1) => x', '() => { super.x }', '(x) => { new.target }']) {
  try { new Function(src); console.log(JSON.stringify(src), 'parses'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_operator_precedence_and_coercion(run, workdir):
    """CATCHES: wrong precedence/associativity (** right-assoc, ?: nesting, comma, `in` in a for-init),
    compound assignment evaluating the target twice, `new` with/without arguments on member chains,
    and wrong ToNumber/ToPrimitive results for strings, arrays, objects and BigInt mixtures."""
    check_script(run, workdir, G, "operator_precedence", r'''
console.log(2 ** 3 ** 2, (2 ** 3) ** 2, (-2) ** 2, 2 ** -1, -(2 ** 2));
console.log(1 + 2 * 3 - 4 / 2 % 3, 7 % -3, -7 % 3, 2 + '3' * '4', '3' - - '2', +'', +' 12 ', +'0x1f', +'1e3', -'abc', +'0b11', +'-0x1', +'1_0');
console.log(1 < 2 < 3, 3 > 2 > 1, 1 == '1', null == undefined, null == 0, NaN != NaN, '' == 0, '0' == false, [] == false, [0] == false, [1,2] == '1,2');
console.log(5 & 3 | 4 ^ 1, ~5, 1 << 31, -1 >>> 0, -16 >> 2, 2 ** 32 | 0, 1.9 | 0, -1.9 | 0, ~~'7.8', 1 << 33, 2 ** 31 >> 0);
console.log(true && 'a' || 'b', null || undefined && 'x', 0 ?? 'n', null ?? (0 || 'z'), (null ?? 1) || 2, a = 1, typeof typeof 1);
var a; let c = (1, 2, 3); console.log(c, void 'x', void (c = 9), c, !!'', !'0', -'-0' === 0, Object.is(-'0', -0));
console.log(typeof null, typeof undefined, typeof function(){}, typeof class{}, typeof Symbol(), typeof 1n, typeof [], typeof undeclared_name);
let i = 0; const arr = [10, 20, 30]; arr[i++] += i; console.log(arr.join(), i);
let j = 1; j += j *= 2; console.log(j); let k = 2; k **= 3; k >>>= 1; k <<= 2; k ^= 1; k |= 16; k &= 0xff; k %= 7; console.log(k);
const obj = { n: 1, get f() { return () => this; } }; console.log((obj.f)() === obj, (0, obj.f)() === obj);
function Ctor() { this.v = 'ctor'; } Ctor.inner = function () { this.v = 'inner'; };
console.log(new Ctor().v, new Ctor.inner().v, new (function () { return Ctor; }())().v, new Ctor instanceof Ctor);
const ns = { a: { b: { C: class { constructor(x) { this.x = x; } } } } }; console.log(new ns.a.b.C(5).x, new ns.a.b.C().x);
console.log('in' in { in: 1 }, 'length' in [], 0 in [1], 1 in [1], !('x' in {}));
for (var q = ('a' in { a: 1 }) ? 1 : 0, w = 0; w < 1; w++) console.log('for-init with in', q);
console.log(1 ? 2 ? 'a' : 'b' : 'c', 0 ? 'x' : 0 ? 'y' : 'z', true ? (1, 2) : 3);
let x1 = 5; x1 = x1++ + ++x1; console.log(x1); let x2 = '5'; x2++; console.log(x2, typeof x2); let x3 = 1n; x3++; console.log(String(x3), typeof x3);
console.log(1 + - + + + - + 1, - -1, 1 - -1, typeof - '1', +[], +{}, +[5], +[1,2], [] + {}, [] + [], {} + 1);
console.log(2n ** 64n, 7n / 2n, -7n / 2n, -7n % 2n, 5n << 2n, -9n >> 1n, 1n == 1, 1n === 1, 2n > 1, 'abc' < 'abd', 'B' < 'a', [2] > 1, null >= 0, undefined >= 0);
console.log(1n < 1.5, 2n == '2', 10n > '9', 0n == '', -0n, typeof -0n, 1n + 2n * 3n, ~5n, -(-3n), 5n & 3n, 5n | 8n, 6n ^ 3n);
const prim = { valueOf() { return 10; }, toString() { return 'str'; } };
const toPrim = { [Symbol.toPrimitive](hint) { return hint === 'number' ? 42 : hint === 'string' ? 'S' : 'D'; } };
console.log(prim + 1, `${prim}`, prim * 2, String(prim), prim > 9, toPrim + '', `${toPrim}`, +toPrim, toPrim == 'D', [toPrim] + '');
''')


def test_destructuring_pattern_syntax(run, workdir):
    """CATCHES: destructuring that evaluates getters/computed keys/defaults out of order or eagerly,
    loses holes or rest elements, mishandles member-expression targets in assignment patterns, string
    and Set sources, or catch-clause/parameter/for-of patterns."""
    check_script(run, workdir, G, "destructuring_patterns", r'''
const log = [];
const src = { get a() { log.push('get a'); return undefined; }, get b() { log.push('get b'); return 'B'; }, c: { d: [1, [2, 3]] }, 'e-f': 'ef', 5: 'five', extra: 'E' };
const key = () => { log.push('key computed'); return 'b'; };
const { a = (log.push('default a'), 'A'), [key()]: bee = (log.push('default b'), 'X'), c: { d: [one, [, three]] }, 'e-f': ef, 5: five, missing: { deep } = { deep: 'dflt deep' }, ...rest } = src;
console.log(a, bee, one, three, ef, five, deep, JSON.stringify(rest), log.join(','));
const [x = 1, [y] = [2], { z } = { z: 3 }, ...[r1, r2]] = [undefined, undefined, undefined, 'r1', 'r2', 'r3'];
console.log(x, y, z, r1, r2);
const [s1, s2, ...sr] = 'héllo\u{1F600}'; console.log(s1, s2, sr.join(''), sr.length);
let p, q, t = {}, u = [];
[p, q] = [q, p] = [1, 2]; console.log(p, q);
({ a: t.x, b: t['y'], c: u[0] = 'u default', ...t.rest } = { a: 'tx', b: 'ty', d: 'd', e: 'e' }); console.log(JSON.stringify(t), u[0]);
[t.arr1, ...t.arr2] = new Set([1, 2, 3]); console.log(t.arr1, t.arr2.join());
function params({ a, b: { c = 'c default' } = {} }, [d, , e] = [4, 5, 6], ...{ length }) { return [a, c, d, e, length].join('|'); }
console.log(params({ a: 1 }), params({ a: 1, b: { c: 2 } }, [7, 8, 9], 'x', 'y'), params.length);
for (const [k, v] of Object.entries({ m: 1, n: 2 })) log.push(k + '=' + v);
for (const { id, tags: [first = 'none'] = [] } of [{ id: 1, tags: ['t'] }, { id: 2 }]) log.push(id + ':' + first);
let fa, fb; for ([fa, fb] of [[1, 2]]) log.push('assign-for ' + fa + fb); for ({ fa = 'dflt' } of [{}]) log.push('obj-for ' + fa);
console.log(log.slice(-6).join(' '));
try { throw { code: 42, info: { msg: 'thrown obj' } }; } catch ({ code, info: { msg } }) { console.log(code, msg); }
const { length: strLen, 0: firstCh } = 'abc'; console.log(strLen, firstCh);
const { toFixed } = 1; console.log(typeof toFixed);
let count = 0; const { [count++]: c0, [count++]: c1 } = ['zero', 'one']; console.log(c0, c1, count);
const { __proto__: pr } = {}; console.log(pr === Object.prototype);
const [h1, , , h4] = [1, 2, 3, 4, 5]; const [, , ...h5] = [1, 2, 3, 4]; console.log(h1, h4, h5.join());
let swapA = 1, swapB = 2; [swapA, swapB] = [swapB, swapA]; console.log(swapA, swapB);
const { l1: { l2: { l3: deepVal } } } = { l1: { l2: { l3: 'deep value' } } }; console.log(deepVal);
const fnDefault = ({ f = function () {}, g = () => {}, h = class {} } = {}) => [f.name, g.name, h.name].join(); console.log(fnDefault());
const res = ([a1, b1] = [1, 2]); console.log(Array.isArray(res), res.length);
for (const src of ['[...a, b] = c', '({...a,} = c)', '({a: 1} = c)', '[a + 1] = c', '({ ...{a} } = c)', '[...[a]] = c', '({ a = 1 })', 'let {a: {b}} = c, [d] = e;']) {
  try { new Function(src); console.log(JSON.stringify(src), 'parses'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_function_to_string_source_text(run, workdir):
    """CATCHES: Function.prototype.toString not returning the exact original source slice (spacing,
    comments, method/getter/static/computed forms, class bodies, arrows), the synthesized text of
    `new Function`/AsyncFunction/GeneratorFunction bodies, native-function text, and inferred names."""
    check_script(run, workdir, G, "function_to_string", r'''
function  decl ( a,b ) { return a /* c */ + b }
const arrow = (x) =>  x * 2;
const arrow2 = async y=>{ await y };
const obj = { method(a) { return 1 }, get g() { return 2 }, set s(v) {}, *gen() {}, async am() {}, async *ag() {}, ['comp' + 1]() {}, 123() {} };
class  Cls  extends Object { constructor() { super() } static st() {} #p() {} m() { return this.#p } }
const fexpr = function named() {};
const gen = function* () { yield 1 };
const nf = new Function('a', 'b', 'return a + b');
const nf2 = new Function('return 1');
const nf3 = Function('...args', 'return args');
const af = new (async function(){}).constructor('x', 'await x');
const gf = new (function*(){}).constructor('yield 1');
const agf = new (async function*(){}).constructor('a', 'yield a');
const items = [decl, arrow, arrow2, obj.method, Object.getOwnPropertyDescriptor(obj, 'g').get,
  Object.getOwnPropertyDescriptor(obj, 's').set, obj.gen, obj.am, obj.ag, obj.comp1, obj[123], Cls, Cls.st, new Cls().m,
  fexpr, gen, nf, nf2, nf3, af, gf, agf, Math.max, function(){}.bind(null), class {}, Symbol, Function.prototype,
  Object.getOwnPropertyDescriptor(Map.prototype, 'size').get, class { static x = 1; }];
for (const f of items) console.log(JSON.stringify(f.toString()));
console.log(decl.name, arrow.name, obj.comp1.name, obj[123].name, Object.getOwnPropertyDescriptor(obj, 'g').get.name, fexpr.name, nf.name, decl.bind(1).name, JSON.stringify((() => {}).name), Cls.name, agf.name);
console.log(decl.length, ((a, b = 1, c) => 0).length, ((...r) => 0).length, (({a}, [b]) => 0).length, nf3.length, nf.length);
try { Function.prototype.toString.call({}); } catch (e) { console.log(e.name + ': ' + e.message); }
console.log(String(decl) === decl.toString(), `${arrow}`, decl + '' === Function.prototype.toString.call(decl));
''')


def test_decorators(run, workdir):
    """CATCHES: missing or mis-ordered decorator evaluation (members in order, inner-to-outer per
    element, class decorators last, initializers after), wrong context objects (kind/name/static/private),
    replacement methods/field initializers/auto-accessors not taking effect, or addInitializer not running."""
    check_script(run, workdir, G, "decorators", r'''
const log = [];
function logged(value, ctx) {
  const extra = ctx.kind === 'class' ? '' : ` static=${ctx.static} private=${ctx.private}`;
  log.push(`${ctx.kind}:${String(ctx.name)}${extra} hasAccess=${'access' in ctx}`);
  if (ctx.kind === 'method') return function (...a) { log.push('call ' + ctx.name); return value.apply(this, a); };
  if (ctx.kind === 'field') return (init) => init * 10;
  if (ctx.kind === 'class') { ctx.addInitializer(function () { log.push('class init ' + this.name); }); }
  if (ctx.kind === 'accessor') return { get() { return value.get.call(this) + 1; }, set(v) { value.set.call(this, v); }, init(v) { return v + 100; } };
}
const tagged = (tag) => { log.push('evaluate tag ' + tag); return (value, ctx) => { log.push('apply tag ' + tag + ' on ' + ctx.name); }; };
@logged
class C {
  @logged @tagged('x') @tagged('y') m(a) { return a * 2; }
  @logged f = 4;
  @logged static sm() { return 's'; }
  @logged accessor acc = 1;
  @logged #pm() { return 'p'; }
  callPm() { return this.#pm(); }
  @logged get g() { return 'g'; }
}
const c = new C();
console.log(c.m(3), c.f, C.sm(), c.acc, c.callPm(), c.g);
c.acc = 5; console.log(c.acc);
console.log(log.join('\n'));
const ns = { deco: (v, ctx) => { log.length = 0; return class extends v { extra = 'added by ' + ctx.name; }; } };
@ns.deco class D {} console.log(new D().extra, D.name);
const withArgs = (n) => (v) => function () { return v.call(this) * n; };
class E { @withArgs(3) val() { return 7; } @(withArgs(2)) val2() { return 5; } } console.log(new E().val(), new E().val2());
for (const src of ['@dec function f() {}', 'class X { @dec }', 'class X { @ m() {} }', '@dec export class Y {}']) {
  try { new Function(src); console.log(JSON.stringify(src), 'parses'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


@pytest.mark.parametrize("cli", TIERS)
def test_using_declarations(run, workdir, cli):
    """CATCHES: `using`/`await using` declarations that dispose in the wrong (non-reverse) order, skip
    null/undefined, do not dispose per for-of iteration, build SuppressedError chains wrongly, accept
    non-disposable values, or allow `using` at script top level; all tiers must agree."""
    check_script(run, workdir, G, "using_declarations", r'''
const log = [];
const res = (name, fail) => ({ name, [Symbol.dispose]() { log.push('dispose ' + name); if (fail) throw new Error('fail ' + name); } });
function scope1() {
  using a = res('a'), b = res('b');
  using n = null;
  using u = undefined;
  log.push('body');
  return 'ret';
}
log.push(scope1());
try { (() => { using a = res('a', true); using b = res('b', true); throw new Error('body'); })(); }
catch (e) { log.push(e.name + ': ' + JSON.stringify(e.message) + ' | error=' + e.error.message + ' | suppressed=' + e.suppressed.name + ' / ' + e.suppressed.error.message + ' / ' + e.suppressed.suppressed.message); }
try { (() => { using bad = { }; })(); } catch (e) { log.push(e.name + ': ' + e.message); }
try { (() => { using bad = 5; })(); } catch (e) { log.push(e.name + ': ' + e.message); }
for (using r of [res('loop1'), res('loop2')]) log.push('iter ' + r.name);
{ using early = res('block'); log.push('in block'); } log.push('after block');
lbl: { using lb = res('labelled'); break lbl; }
switch (1) { case 1: { using sw = res('switch'); log.push('case'); } }
(() => { let i = 0; for (using r = res('for-head'); i < 2; i++) log.push('c-for iter ' + i + ' ' + r.name); log.push('after c-for'); })();
{ const stack = new DisposableStack(); stack.use(res('s1')); stack.defer(() => log.push('deferred')); stack.adopt('val', v => log.push('adopt ' + v)); log.push('stack disposed? ' + stack.disposed); stack.dispose(); log.push('stack disposed? ' + stack.disposed); }
for (const src of ['using x = 1', 'if (1) using x = res()', '{ using [a] = b }', '{ using x }', 'switch (1) { case 1: using x = y }', 'for (using x in {}) ;', '{ await using x = y }']) {
  try { new Function(src); log.push(JSON.stringify(src) + ' parses'); } catch (e) { log.push(JSON.stringify(src) + ' ' + e.name + ': ' + e.message); }
}
(async () => {
  {
    await using x = { async [Symbol.asyncDispose]() { await null; log.push('async dispose x'); } };
    await using y = res('sync-in-await-using');
    await using z = null;
    log.push('async body');
  }
  log.push('after async block');
  try { await (async () => { await using bad = {}; })(); } catch (e) { log.push(e.name + ': ' + e.message); }
  let i = 0; for (await using r = { async [Symbol.asyncDispose]() { log.push('async dispose c-for head'); } }; i < 1; i++) log.push('async c-for iter');
  for await (await using q of [{ [Symbol.asyncDispose]() { log.push('for-await-using element disposed'); } }]) log.push('for-await-using body');
  console.log(log.join('\n'));
})();
''', cli=cli)


def test_template_substitution_lexing(run, workdir):
    """CATCHES: a template lexer that ends a `${...}` hole at a `}` inside a comment, string, regex,
    nested template or object literal, mis-validates escapes in tagged templates (braced code points
    out of range, \\0 followed by a digit, short \\x/\\u), combines surrogate escapes wrongly, treats
    `?.5` as optional chaining, or rejects a hashbang at the start of eval code."""
    check_script(run, workdir, G, "template_substitutions", r'''
const x = 5;
console.log(`a${ /* } */ 1 }b`, `c${ // } comment
  2 }d`, `e${ '}' + "{" + '\'' }f`, `g${ `inner ${ `deep${x}` } ${'s'}` }h`, `i${ /}/.source }j`, `k${ {a: 1}.a }l`, `m${ (() => { return '}'; })() }n`);
console.log(`${x / 1 / 1}`, `${ x }${ x }`, `${ [1, 2].map(v => `<${v}>`).join('') }`, `${ "`" }`, `${ '${' }`, `${ x > 1 ? `yes${'!'}` : 'no' }`, `${ `\`` }`);
console.log(`${ { b: { c: 3 } }.b.c }`, `${ /[}]/.test('}') }`, `${ 1 /* a */ + /* b */ 2 }`, `${ `${ `${ 'three deep' }` }` }`);
const raw = (s) => JSON.stringify([s, s.raw]);
console.log(raw`\u{110000}|\u{}|\u{FFFFFFFFF}|\u{10FFFF}`);
console.log(raw`\00|\0|\x|\xG|\u00|\u00zz|😀|\9|\a`);
console.log(raw`a${1}\u{41}${2}\x41`, raw`\u{0041}A\x41\101`);
console.log(JSON.stringify(['😀', '\uD83D\u{DE00}', '\u{D83D}\uDE00', '\uDE00\uD83D', '\uD83D', '\uD83Dx'].map(s => [s.length, s.codePointAt(0).toString(16)])));
console.log(eval("'line\\\r\ncontinued'"), eval("'a\\ b'"), eval("'cr\\\rx'").length);
console.log(true?.5:1, false?.5:.25, null?.x, (0?.1:2));
console.log(eval('#! hashbang in eval\n40 + 2'));
for (const src of ['`${"}`', '`${/abc`', '`${ /* }`', '`${ `abc }`', '`${ 1 ', '`a\\', '`${ \'x }`', '`${ "\\\n}`']) {
  try { eval(src); console.log(JSON.stringify(src), 'ok'); } catch (e) { console.log(JSON.stringify(src), e.name + ': ' + e.message); }
}
''')


def test_es_module_syntax(run, workdir):
    """CATCHES: a module parser missing import/export forms (default + named + namespace imports,
    string export names, `export * as`, re-exports, exported destructuring, default function/class/
    expression exports and their names, JSON import attributes), live bindings, top-level await,
    `this`/strictness of module code, or wrong namespace key order."""
    write_files(workdir, {
        "lib.mjs": "export const a = 1;\nexport let counter = 0;\nexport function inc() { counter++; }\n"
                   "export default class Def { static tag = 'default class'; }\n"
                   "export { a as aliasA, inc as 'string name' };\nexport * from './more.mjs';\n"
                   "export * as moreNs from './more.mjs';\nexport var v1 = 'v1', v2 = 'v2';\n"
                   "export async function af() { return 'af'; }\nexport function* gf() { yield 'gf'; }\n"
                   "export class Named {}\nconst hidden = 'h'; export { hidden as default2 };\n"
                   "export let [d1, { d2 }] = [10, { d2: 20 }];\n",
        "more.mjs": "export const fromMore = 'more';\nexport default 'more default (not re-exported by star)';\n",
        "fnexp.mjs": "export default function () { return 'anon default fn'; }\n",
        "classexp.mjs": "export default class {}\n",
        "exprexp.mjs": "export default (1 + 2);\n",
        "data.json": '{"k": "json value", "n": [1, 2]}\n',
    })
    check_script(run, workdir, G, "es_module_syntax", r'''
import Def, { a, counter, inc, aliasA, 'string name' as strName, fromMore, moreNs, v1, v2, af, gf, Named, default2, d1, d2 } from './lib.mjs';
import * as ns from './lib.mjs';
import anonFn from './fnexp.mjs';
import AnonClass from './classexp.mjs';
import three from './exprexp.mjs';
import moreDefault, * as moreAll from './more.mjs';
import {} from './more.mjs';
import './more.mjs';
import json from './data.json' with { type: 'json' };
export const selfExport = 'self';
console.log(Def.tag, Def.name, a, aliasA, counter, fromMore, moreNs.fromMore, moreNs.default, v1, v2, Named.name, default2, d1, d2);
inc(); strName(); console.log('live binding', counter, ns.counter);
console.log(Object.keys(ns).join(), ns[Symbol.toStringTag], Object.getPrototypeOf(ns), 'default' in ns, Object.keys(moreAll).join());
console.log(anonFn(), anonFn.name, AnonClass.name, three, [...gf()].join(), await af(), moreDefault, json.k, json.n.length);
try { counter = 5; } catch (e) { console.log(e.name + ': ' + e.message); }
console.log(this, typeof import.meta, typeof import.meta.url, import.meta.url.endsWith('/es_module_syntax.mjs'));
const dyn = await import('./lib.mjs'); console.log(dyn === ns, dyn.a);
const t = await Promise.resolve('top-level await'); console.log(t);
console.log((function () { return this; })(), (() => { try { undeclaredInModule = 1; } catch (e) { return e.name; } })());
''', filename="es_module_syntax.mjs")


def test_parser_edge_cases(run):
    """CATCHES: parser edge cases handled differently from the reference: destructuring and
    parenthesised for-in/of heads (Annex B call heads that fail only at runtime), `yield`/`await`
    identifiers followed by `/`, nested assignment-pattern defaults and their strict-mode eval/arguments
    checks, CoverInitializedName (`{a = 1}`) outside patterns, method/accessor parameter rules,
    lexer errors inside template substitutions, escapes, numeric forms and regex/division after `}`."""
    src = r'''
const progs = [
  'var r = []; for ([a, b = 2] of [[1]]) r.push(a + b); r.join()',
  'var o = {}; for ({ x: o.p = "d" } of [{}]) ; o.p',
  'var x; for ((x) of [7]) ; x',
  'var x; for ((x) in { k: 1 }) ; x',
  'for (f() of []) ; "call head ok when empty"',
  'function f() {} for (f() in { k: 1 }) ;',
  'for ([a + 1] of []) ;',
  'for ({ a: 1 } of []) ;',
  'for (let [x = 1, ...y] of [[undefined, 2, 3]]) var res = x + y.length; res',
  '"use strict"; for (f() of []) ;',
  '"use strict"; for ([eval] of [[1]]) ;',
  '"use strict"; for ({ arguments } of [{}]) ;',
  'var yield = 10; yield /2/1',
  'var await = 12; await /3/ 2',
  'var a, b, c; [a = 1, [b] = [2], { c } = { c: 3 }] = []; [a, b, c].join()',
  'var a, b; ({ a: [b] = [5] } = {}); b',
  'var t = {}; [t.x = 1, ...t.rest] = [undefined, 2, 3]; JSON.stringify(t)',
  '"use strict"; [eval = 1] = []',
  '"use strict"; ({ a: arguments } = {})',
  '"use strict"; [...[eval]] = []',
  '"use strict"; ({ ...arguments } = {})',
  '"use strict"; ({ __proto__: eval } = {})',
  '"use strict"; ({ a: { b: eval } } = {})',
  'x = [{ a = 1 }]',
  'var a; [{ a = 1 }] = [{}]; a',
  'f({ a = 1 })',
  '(({ a = 1 }) => a)({})',
  '({ a = 1 }).a',
  '[{ a = 1 }.a] = []',
  'var q; ({ q = 1, __proto__: q } = {}); q === Object.prototype',
  '({ m(a, a) {} })',
  '({ get x(a) {} })',
  '({ set x(...a) {} })',
  '({ set x(a = 1) {} }); "default param in setter ok"',
  'function f(static) { "use strict" }',
  '(interface) => { "use strict" }',
  '({ m(implements) { "use strict" } }); "method param not re-checked"',
  '`${ 0b2 }`',
  '`${ "\\x" }`',
  '`${ /a\\/b/.source }`',
  'if (true) {} /foo/.test("foo")',
  '({} / 2)',
  "'abc\\",
  "'\\uD83D\\u{DE00x}'",
  "'\\uD83D\\uDEzz'",
  "['\\uD83D\\uDE00'.length, '\\uD83D\\u{DE00}'.codePointAt(0)].join()",
  '08.5', '019.5e1', '07.5', '09e1', '0.0e-0',
  '/a\\\n/',
  '/[\\]/]/.source',
  'x = 1\n/2/g',
  'let\nawait = 1; await',
  'async\nfunction f() {} typeof f',
  'a\n?.5:1',
  'var { if: iff } = { if: "kw key" }; iff',
  'var o = { "": "empty", " ": "space" }; o[""] + o[" "]',
  '({ 0x10: "hex", 1e2: "exp", .5: "half" })[16]',
  'new new Function("this.v = 1")().v',
  'new (class { constructor() { this.k = 1 } })().k',
  'typeof new.target',
  'void (() => {})?.()',
];
for (const src of progs) {
  let out;
  try { const v = eval(src); out = 'value ' + (typeof v === 'string' ? JSON.stringify(v) : String(v)); } catch (e) { out = e.name + ': ' + e.message; }
  console.log(JSON.stringify(src).padEnd(50), out);
}
'''
    assert_result(run([], input=src), G / "parser_edge_cases.golden")
