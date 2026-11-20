"""Parser and lexer coverage for lumen-cli: exact SyntaxError messages for lexical errors, early errors
(strict mode, declarations, control flow, assignment targets, classes, modules, `using`, decorators),
plus rare-but-valid syntax that must parse and run, and the CLI's SyntaxError report formats.
Sources are fed through indirect eval, `$262.evalScript`, `Function`, module files or the CLI."""

import pytest

from conftest import err, out

TIERS = [
    pytest.param((), id="jit"),
    pytest.param(("--tier=bytecode",), id="bytecode"),
    pytest.param(("--tier=interp",), id="interp"),
]

# Each case prints `<source as JSON> => ok <value>` or `=> <ErrorName>: <message>`.
SE = r"""var out = [];
function show(v) { return v === undefined ? '' : ' ' + (typeof v === 'function' ? 'fn' : typeof v === 'string' ? JSON.stringify(v) : typeof v === 'bigint' ? v + 'n' : String(v)); }
function se(src) { try { return 'ok' + show((0, eval)(src)); } catch (e) { return e.name + ': ' + e.message; } }
function group(name, list, prefix) { out.push('# ' + name); list.forEach(function (src) { out.push(JSON.stringify(src) + ' => ' + se((prefix || '') + src)); }); }
"""
END = "\nconsole.log(out.join('\\n'));\n"


@pytest.mark.parametrize("tier", TIERS)
def test_lexer_strings_templates_and_comments(js, golden, tier):
    """CATCHES: a lexer that accepts unterminated strings/templates/comments, malformed hex and unicode escapes or out-of-range code points, mis-normalizes CR/CRLF in template cooked and raw values, mis-tracks nested template substitutions containing strings, regexes and comments, or rejects legal line continuations and U+2028/2029 in strings fails this."""
    code = SE + r"""group('strings, templates, comments', ['"abc', "'abc\ndef'", '`abc', '/* never closed', '"\\x4"', '"\\xZZ"', '"\\u12"', '"\\u{}"', '"\\u{110000}"', '"\\u{12"', '"\\u{zz}"', '"\\', '`${`', '`${1`', '`${ "}`" }`', '`${ /}`/ }`', '`${ /*}*/ 1 }`', '`${ `in${"n"}er` }`', '`${ //c\n 2 }`', '`${ \'x}\' }`', '`${ {a: 1}.a }`', '"\\08"', '"\u2028"', '"\u2029".length', "'line\\\ncontinuation'", "'crlf\\\r\ncontinuation'", "'cr\\\rcontinuation'", '"a\rb"', '`a\rb` === "a\\nb"', '`a\r\nb`.length', '`\\u{1F600}`.length', '"\\uD83D\\uDE00".length', '"\\uD83D".length', '"\\u{D83D}\\u{DE00}".length', '"\\x41\\u0041\\u{41}\\101"', '"\\v\\b\\f\\t\\r\\n".length', "'\\''", '"\\"\\\\"', '"\\q\\w\\e"', '`${ `${ `deep` }` }`', '`a${1}b${2}c`', '`\\unicode`', '`\\01`', '`\\1`', '`\\u{`', '`\\x0`', '`${1}${2}${3}`.length', '`$`', '`$ {1}`', '`\\${1}`', '`${"a"}${`b${"c"}`}`', '`line1\\\nline2`', '/* a */ /* b */ 1', '/*\n*/ 2', '// only comment', '/**/3', '/*/ 4 */ 5']);
out.push('# tagged templates (compiled with Function)');
['String.raw`a\r\nb`.length', '(function (s) { return s.raw[0].length + ":" + s[0].length; })`x\r\ny\rz`', '(function (s) { return s[0] + "|" + s.raw[0]; })`\\unicode`', '(function (s) { return String(s[0]) + "|" + s.raw[0]; })`\\x0`', '(function (s) { return String(s[0]) + "|" + s.raw[0]; })`\\u{110000}`', '(function (s) { return s.length + "|" + s.raw.join(","); })`a${1}b${2}`', '(function (s) { return Object.isFrozen(s) + "|" + Object.isFrozen(s.raw) + "|" + Array.isArray(s); })`x`'].forEach(function (src) { try { out.push(JSON.stringify(src) + ' => ok ' + JSON.stringify(Function('return ' + src)())); } catch (e) { out.push(JSON.stringify(src) + ' => ' + e.name + ': ' + e.message); } });""" + END
    r = js(code, *tier)
    assert out(r) == golden("lexer_strings_templates_and_comments")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_lexer_identifiers_escapes_and_unexpected_characters(js, golden, tier):
    """CATCHES: a lexer that accepts invalid escaped identifier characters, lets escaped keywords act as keywords, rejects legal Unicode ID_Start/ID_Continue identifiers (astral, ZWJ, Other_ID_Start), normalizes identifiers, or reports unexpected characters and line separators wrongly fails this."""
    code = SE + r"""group('identifiers', ['var \\u0030x', 'var a\\u002Fb', 'var \\u{zz}', 'var \\u12', 'var \\x41', '\\u0061\\u{62}c = 1', 'v\\u0061r x = 1', '#', '@', '\u0000', 'a ~ b', 'a\u2028b', '1\u2029+2']);
group('escaped keywords and unicode identifiers', ['v\\u0061r x = 1', '\\u0076ar x', 'n\\u0065w Object()', 'n\\u0065w.target', 'function f() { n\\u0065w.target; }', 'function f() { new.t\\u0061rget; }', '\\u0061sync function f() {} 1', 'async function f() { aw\\u0061it 1; }', 'async function f() { var aw\\u0061it; }', 'var yi\\u0065ld = 2; yield', 'l\\u0065t x = 1', 'var l\\u0065t = 3; let', 'for (x \\u006ff []) ;', 'for (var x \\u006ff []) ;', 'class C { st\\u0061tic m() {} }', 'class C { \\u0067et x() {} }', '({ \\u0067et x() {} })', '({ \\u0061sync m() {} })', 'class C { \\u0061ccessor x = 1 } 1', 'o = { v\\u0061r: 1 }; o.var', 'o = {}; o.v\\u0061r = 2; o["var"]', 'o = { if: 1 }; o.i\\u0066', 'th\\u0069s', 'tru\\u0065', 'nul\\u006c', '\\u{74}ypeof 1', 'a\\u{200D}b = 4; a\\u200db', 'x\\u0041 = 5; xA', '\\u{1d4b6} = 6; \\u{1d4b6}', '\\u{1d4b6}x = 7; 𝒶x', 'ñandú = 8', 'ゆ = 9', 'x\u200dy = 10', '℘ = 11', '\\u2118 = 12; ℘', 'a\\u0030 = 13', '\\u0030a = 14', '\\u{2F800} = 15; 丽', 'i\\u{66} (1) 16', 'import.m\\u0065ta', 'impor\\u0074("x")', 'defaul\\u0074: 1', 'try {} c\\u0061tch {}', 'O\\u0062ject.keys', 'label\\u0031: 1']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("lexer_identifiers_escapes_and_unexpected_characters")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_numeric_literals_separators_and_bigints(js, golden, tier):
    """CATCHES: numeric literal scanning that accepts misplaced numeric separators, separators or BigInt suffixes on legacy octal-like literals, empty radix literals, identifiers glued to numbers or fractional BigInts, or that mis-evaluates exponent, radix, legacy-octal and member-access-on-number forms fails this."""
    code = SE + r"""group('numbers', ['1__0', '1_', '0x_1', '0_1', '08_1', '01n', '1.5n', '1e', '1e+', '0b2', '0o8', '0x', '0b', '0o', '3in []', '1n_', '0b1_', '1._5', '1_.5', '1e_5', '.5_', '0xG', '"use strict"; "\\08"', '"use strict"; "\\8"', '"use strict"; 08', '"use strict"; 07', '0.0000001', '1e-7 === 0.0000001', '.5e1', '5.e1', '0x1F_FF', '0B1010', '0O777', '1_000_000.000_1', '0.000_001', '1e1_0', '9007199254740993n', '0xFFn', '0o7n', '0b11n', '0n', '-0n', '00', '007', '09', '0.1.toFixed', '1..toString()', '1 .toString()', '5..constructor.name']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("numeric_literals_separators_and_bigints")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_regexp_literal_syntax_and_flags(js, golden, tier):
    """CATCHES: regular expression literal scanning or early validation that mis-handles unterminated bodies and classes, duplicate/conflicting/unknown flags, the v flag set syntax, named-group and back-reference rules, quantifier and class-range order, Annex B leniency outside u-mode or inline modifiers fails this."""
    code = SE + r"""group('regexp literals', ['/abc', '/abc\n/', '/a[/', '/a\\', '/[/]/.test("/")', '/\\//.source', '/a/gimsuyd.flags', '/a/v.unicodeSets', '/[\\p{L}--[a-z]]/v.test("A")', '/[[a-z]&&[aeiou]]/v.test("e")', '/a/gg', '/a/uv', '/a/z', '/(?<n>a)\\k<n>/.test("aa")', '/\\k<n>/.test("k<n>")', '/\\k<n>/u', '/(?<a>x)(?<a>y)/', '/(?<a>x)|(?<a>y)/.test("y")', '/a{2,1}/', '/(?<=a)b/.test("ab")', '/[z-a]/', '/\\p{Nope}/u', '/\\u{110000}/u', '/(/', '/)/', '/a**/', '/\\c/u', '/[\\d-a]/u', '/\\1(a)/u.test("a")', '/(?i:a)b/.test("Ab")', '/(?i-i:a)/', '/x/dg.hasIndices']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("regexp_literal_syntax_and_flags")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_strict_mode_only_errors(js, golden, tier):
    """CATCHES: a parser that does not apply strict-mode early errors (with, delete identifier, duplicate params, eval/arguments as targets or bindings, future reserved words, legacy octals) to 'use strict' scripts, functions and class bodies, or applies them retroactively wrong to directive prologues and non-simple parameter lists, fails this."""
    code = SE + r"""group('strict', ['with ({}) {}', 'delete x', 'delete (x)', 'delete ((x))', 'function f(a, a) {}', 'eval = 1', 'arguments = 1', 'eval++', '--arguments', '[eval] = []', '({a: arguments} = {})', 'var eval', 'let arguments', 'function eval() {}', 'function f(eval) {}', '(function arguments() {})', 'try {} catch (eval) {}', 'var implements', 'var package', 'var let', 'var static', 'var yield', 'interface: 1', 'class let {}', 'function f() { "use strict"; var private; }', '(eval) => 1', 'for (eval in {}) {}', 'implements', 'x = { implements }', 'function protected() {}', 'class C { m(private) {} }', '({ static }) => 1', 'for (let let of []) {}'], '"use strict"; ');
group('sloppy', ['with ({}) {}', 'delete x', 'function f(a, a) { return a; } f(1, 2)', 'eval = eval', 'var let = 1; let', 'var static, yield, implements', 'let\nx = 1', 'yield: 1', 'await: 2', 'var await = 3; await', 'function f(a, a = 1) {}', '(a, a) => 1', 'function f([a, a]) {}', 'function f(a, ...a) {}', 'function f(a) { "use strict"; } f()', 'function f(a = 1) { "use strict"; }', 'function f({a}) { "use strict"; }', 'function f(...a) { "use strict"; }', '(a = 1) => { "use strict"; }', 'function f() { "\\07"; "use strict"; }', 'function f() { "use strict"; 010; }', 'function eval() { "use strict"; }', 'function f(eval) { "use strict"; }', '(function (eval) { "use strict"; })', '({ set s(arguments) { "use strict"; } })', 'class C { m() { var implements; } }', 'class C { static m() { with ({}) {} } }', 'class C extends (function () { with ({}) {} return Object; })() {}']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("strict_mode_only_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_declaration_early_errors(js, golden, tier):
    """CATCHES: a parser that misses redeclaration errors between let/const/class/var/function/catch/parameter bindings, accepts `let` as a lexical name, uninitialized const or using bindings, lexical declarations in single-statement positions, bad labelled declarations, or mis-handles module syntax and new.target/import.meta in scripts fails this."""
    code = SE + r"""group('declarations', ['let a; let a;', 'let a; var a;', 'var a; let a;', 'const a;', 'const a = 1; a = 2', 'let let = 1', 'let [let] = []', 'for (let let = 0;;) {}', 'for (const x;;) {}', 'for (let [a];;) {}', 'for (const x in {}) {} ok = 1', 'if (1) let x = 1', 'if (1) const x = 1', 'while (0) class C {}', 'if (1) function* g() {}', 'if (1) async function f() {}', 'L: let x = 1', 'L: function* g() {}', 'L: async function f() {}', 'L: class C {}', 'while (0) L: function f() {}', 'if (0) L: function f() {}', 'try {} catch ([a, a]) {}', 'try {} catch (e) { let e; }', 'try {} catch (e) { var e; }', 'try {} catch ([e]) { var e; }', 'function f(a) { let a; }', 'function f(a) { var a; } 1', '(a) => { let a; }', '({ m(a) { let a; } })', 'function f() { let x; { var x; } }', '{ function f() {} function f() {} } 1', '"use strict"; { function f() {} function f() {} }', '{ function f() {} let f; }', '{ async function f() {} function f() {} }', 'switch (0) { case 1: let a; case 2: let a; }', 'switch (0) { case 1: function f() {} case 2: function f() {} } 1', 'let x; { var x; }', 'class A {} class A {}', 'let undefined', 'var undefined; 1', 'const [a, a] = [];', 'let {a, b: a} = {};', 'for (let [x, x] of []) {}', 'label: label: ;', 'a: { a: ; }', 'a: { b: ; } a: ;', 'export var x = 1', 'import x from "y"', 'import.meta', 'new.target', 'function f() { return new.target; } 1', 'new.tar', 'import.foo', '(function () { return import("x", ); }); 1', 'import()', 'import("a", "b", "c")']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("declaration_early_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_control_flow_early_errors(js, golden, tier):
    """CATCHES: a parser that accepts break/continue outside loops or to undefined/non-iteration labels, return at top level, a newline after throw, try without catch/finally, duplicate default clauses, bad do-while, misplaced for-await or bad for-in/of initializers fails this."""
    code = SE + r"""group('control flow', ['break', 'continue', 'break L', 'L: { break L; } 1', 'L: { continue L; }', 'L: if (1) { continue L; }', 'L: while (0) { continue M; }', 'L: while (0) { (function () { break L; }); }', 'while (0) { function f() { break; } }', 'return', 'return 1', 'throw\n1', 'try {}', 'try {} catch {} 1', 'switch (1) { default: default: }', 'switch (1) { case 1: case 1: } 1', 'switch (1) { foo }', 'switch (1) {} case 1:', 'do x = 1; while (0) 1', 'do {} 1', 'do ; while (0) 2', 'for (;;) break; 3', 'for await (var x of []) {}', 'async function f() { for await (var x in {}) {} }', 'async function f() { for await (var i = 0; i < 1; i++) {} }', 'async function f() { for await (x of []) {} } 1', 'function f() { for await (x of []) {} }', 'for (var i, j of []) {}', 'for (var i = 0 of []) {}', 'for (let i = 0 in {}) {}', 'for (x = 0 in {}) {}', 'for (var [a] = 0 in {}) {}', 'if (1) else 2', 'else 1', 'debugger; 4', 'with (1) 5', 'yield 1', 'await 1']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("control_flow_early_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_assignment_and_for_in_of_target_errors(js, golden, tier):
    """CATCHES: assignment-target validation that accepts literals, optional chains, nested-rest or defaulted-rest patterns and shorthand cover initializers outside patterns, rejects legal parenthesized and member targets, or mis-converts for-in/of destructuring heads (defaults, rest, __proto__, nested patterns, async-of ambiguity) fails this."""
    code = SE + r"""group('assignment targets', ['1 = 2', 'a + 1 = 2', 'f() = 1', 'f()++', '++f()', '(a, b) = 1', '[a, ...b,] = []', '[...a, b] = []', '[...a = 1] = []', '({...{a}} = {})', '({...[a]} = {})', '({a: 1} = {})', '({a = 1})', '({a = 1}) => 1', '({a = 1} = {}); 1', '[{a = 1}] = [{}]; 2', '({ a: { b = 1 } }); 3', '(a = 1) = 2', '[a] = [1]; a', '({a: b.c} = {a: 1}); b.c', 'var b = {}; [b["x"], b.y] = [1, 2]; b.x + b.y', 'for ([a, b = 1, ...c] of [[1]]) ; a + "" + b + c.length', 'for ({x, y: z = 2, __proto__: p, ...rest} of [{x: 1, w: 9}]) ; x + z + rest.w', 'for ([a.b] of [[1]]) ;', 'for ([x, ...[y, z]] of [[1, 2, 3]]) ; y + z', 'for ({a = 1} in {}) ;', 'for ([a, ...b, c] of []) ;', 'for ({...{a}} of []) ;', 'for (f() of []) ;', 'for (f() in {}) ;', 'for (a + 1 of []) ;', 'for (async of []) ;', 'for (async of => 1;;) break', 'for ((async) of []) ; 1', 'for (let of of []) ;', 'for (let in {}) ;', '++1', 'x++ = 1', 'new.target = 1', 'this = 1', 'import.meta = 1', '[a, b] += 1', '({}) => {}; ({} = 1)', '({} = {}); 5', '[,] = []; 6', '[a.b = 1] = []; 7', 'a?.b = 1', 'a?.b++', '[a?.b] = []', 'delete a?.b; 8', '(a?.b) = 1', '`${a}` = 1', 'async () => {}++']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("assignment_and_for_in_of_target_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_class_body_early_errors_and_rare_members(js, golden, tier):
    """CATCHES: class parsing that allows multiple or special constructors, static prototype members, fields named constructor, #constructor, duplicate or undeclared private names, private deletes or super.#x, wrong accessor arities, arguments/await/return misuse in fields and static blocks, or mis-parses rare valid members (accessor, ASI before names, numeric and computed keys) fails this."""
    code = SE + r"""group('classes', ['class A { constructor() {} constructor() {} }', 'class A { *constructor() {} }', 'class A { async constructor() {} }', 'class A { get constructor() {} }', 'class A { set constructor(v) {} }', 'class A { static prototype() {} }', 'class A { static get prototype() {} }', 'class A { static prototype = 1 }', 'class A { constructor = 1 }', 'class A { "constructor" = 1 }', 'class A { static constructor() {} } 1', 'class A { static "prototype" = 1 }', 'class A { #constructor }', 'class A { #a; #a; }', 'class A { get #a() {} set #a(v) {} } 2', 'class A { get #a() {} get #a() {} }', 'class A { static get #a() {} set #a(v) {} }', 'class A { #a; m() { #a; } }', 'class A { m() { this.#b; } }', 'class A { m() { return #b in this; } }', 'this.#x', 'class A { #a; m() { delete this.#a; } }', 'class A { #a; m() { delete this?.#a; } }', 'class A { #a; m() { super.#a; } }', 'class A { #a; static m(o) { return #a in #a in o; } }', 'class A { #a; m() { return 1 + #a; } }', 'class A { #a; m(o) { return #a in o; } } 3', 'class A { #a; m() { class B { n() { return this.#a; } } } } 4', 'class A { m() { class B { #z; } return this.#z; } }', '({ #a: 1 })', 'class A { get g(x) {} }', 'class A { set s() {} }', 'class A { set s(a, b) {} }', 'class A { set s(...a) {} }', '({ get g(x) {} })', '({ set s() {} })', 'class let {}', 'class yield {}', 'class await {} 5', 'class static {}', 'async function f() { class await {} }', 'function* g() { class yield {} }', 'class A { x = arguments; }', 'class A { static { arguments; } }', 'class A { static { await 1; } }', 'class A { static { var await; } }', 'class A { static { return; } }', 'class A { static { super(); } }', 'class A { static { super.x; } } 6', 'class A { x = super(); }', 'class A { m() { super(); } }', 'class A extends Object { constructor() { super(); } } 7', 'class A { constructor() { super(); } }', '({ m() { super(); } })', '({ m() { return super.x; } }).m()', 'function f() { super.x; }', 'class A extends B, C {}', 'class A extends {}', 'class A extends 1 {} ', 'class A { static async *m() {} static #p = 1; static { this.q = A.#p; } } A.q', 'class A { accessor x = 1; static accessor #y = 2; } new A().x', 'class A { accessor\nx = 1 } new A().accessor', 'class A { get\nx() { return 1; } } new A().x', 'class A { static\nm() { return 2; } } A.m()', 'class A { async\nm() {} }', 'class A { "a b"() { return 1; } 42() { return 2; } [Symbol.iterator]() {} get [1 + 1]() { return 3; } static 0x10 = 4 } new A()["a b"]() + new A()[42]() + new A()[2] + A[16]', 'class A { x; y = 1; z } Object.keys(new A()).join()', 'class A { static x = this; } A.x === A', 'class A { #m() { return 1; } static has(o) { return #m in o; } } A.has(new A()) + "" + A.has({})', 'class A { get #g() { return "g"; } t() { return this.#g; } } new A().t()', 'class A { static #s() { return "s"; } static t() { return A.#s(); } } A.t()', 'class A { ; ; m() {} ; } 8', 'new class { constructor(x) { this.x = x; } }(9).x', '(class Named { static n = Named.name }).n']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("class_body_early_errors_and_rare_members")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_operator_and_function_context_errors(js, golden, tier):
    """CATCHES: a parser that allows ?? mixed with &&/|| without parentheses, unary or await bases for **, new on import()/optional chains, tagged templates in optional chains, yield/await in parameters or as identifiers in generators/async functions, duplicate arrow parameters, bad async method line breaks, illegal shorthand properties, or duplicate __proto__ fails this."""
    code = SE + r"""group('functions and operators', ['a ?? b || c', 'a || b ?? c', 'a ?? b && c', 'a && b ?? c', '(a || b) ?? c; 1', 'a ?? (b || c); 2', '-x ** 2', '!x ** 2', 'typeof x ** 2', 'delete x.y ** 2', 'async function f() { await x ** 2; }', 'async function f() { (await x) ** 2; } 3', '(-2) ** 2', '2 ** -2', 'new import("x")', '(function () { return new (import("x")); }); 2', 'new a?.b()', 'new a?.()', 'new C?.()', 'new o?.C()', 'a?.b`tpl`', 'a?.`tpl`', 'new.target', 'function f() { new.target; } 4', '() => new.target', 'function f() { return () => new.target; } 5', 'super.x', 'super()', 'function* g(x = yield) {}', 'function* g() { function* h(x = yield) {} }', 'async function f(x = await 1) {}', 'async (x = await 1) => 1', 'function* g() { var yield; }', 'function* g() { yield: 1; }', 'async function f() { var await; }', 'async function f() { await: 1; }', 'function* g() { yield\n* 2; }', 'function* g() { yield * 2; } 6', 'function* g() { (yield) => 1; }', 'async function f() { (await 1) => 1; }', 'async (a, a) => 1', '(a, b, a) => 1', '({ a, a }) => 1', '([a, a]) => 1', '(...a, b) => 1', '(a, ...b,) => 1', '((a)) => 1', '(a,) => 1; 7', '(a\n) => 1; 8', '(a)\n=> 1', 'async a\n=> 1', 'async\na => 1', '({ async\nm() {} })', '({ async *m() {}, *g() {}, async a() {} }); 9', '({ async m })', '({ *m })', '({ get })', '({ get: 1, set: 2, async: 3, static: 4, await: 5 }).await', '({ get get() { return "gg"; } }).get', '({ set set(v) {} }); 10', '({ if: 1, class: 2, new: 3, typeof: 4 }).typeof', '({ a: 1, b })', 'x = { a, b, c }', 'x = { "a": 1, 1: 2, 1n: 3, [1 + 1]: 4, 0x10: 5 }; Object.keys(x).join()', 'x = { if }', 'x = { true }', 'x = { this }', 'function f() { "use strict"; return { yield }; }', 'function* g() { return { yield }; }', 'async function f() { return { await }; }', 'function f() { return { arguments }; } 11', 'x = { __proto__: 1, __proto__: 2 }', 'x = { __proto__: 1, "__proto__": 2 }', 'x = { __proto__: 1, ["__proto__"]: 2 }; 12', 'x = { __proto__: 1, __proto__ }; 13', 'x = { __proto__: 1, __proto__() {} }; 14', '({ __proto__: a, __proto__: b } = {}); 15', '[{ __proto__: a, __proto__: b }] = [{}]; 16', '({ __proto__: a, __proto__: b }) => 1; 17', 'a = 1, b = 2; a, b', 'void 0, typeof undefinedVar', 'x = a => b => c => 42; x()()()', '(function () {}) ()', 'function f() {}()', 'x = function* () { yield* [1, 2]; }; [...x()].join()', 'x = async function* () {}; typeof x', '(async () => 1); 18', 'async () => await 1; 19', 'async function f() { return await import.meta; }', 'function f() { "use strict"; return this; } f()', 'function f() { return typeof this; } f()', '0 ? 1 : 2 ? 3 : 4', 'a = 1; a ? b : c => d', '1 in {}', 'for (var i = (1 in {}) ? 0 : 1; i < 1; i++); i', 'for (var x = "a" in {}; false;); x', 'for (let x = ("a" in {}); false;); 20', 'typeof typeof 1', '!!!0', '- - 1', '+ + 1', '1 - -1', '1 + +1', 'x = 1; x+++x', 'x = 1; x---x', 'x = 1; x+ ++x', '1/2/3', 'x = 6; x /2/ 3', 'a = 4; g = 2; a /g/ 1', '"use strict"; ({ get arguments() { return 1; } }).arguments']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("operator_and_function_context_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_using_declaration_syntax(js, golden, tier):
    """CATCHES: a parser that permits `using` at the top level of scripts, directly in case clauses, in for-in heads, with patterns or without initializers, mis-parses `using` and `await using` as identifiers versus declarations across line breaks, or rejects for-of using heads fails this."""
    code = SE + r"""group('using', ['using x = null', '{ using x = null; } 1', '{ using x = { [Symbol.dispose]() {} }, y = null; } 2', '{ using [a] = [] }', '{ using {a} = {} }', '{ using x; }', 'switch (1) { case 1: using x = null; }', 'switch (1) { case 1: { using x = null; } } 3', 'for (using x in {}) ;', 'for (using x of []) ; 4', 'for (using of []) ; 6', 'for (using x = null;;) break; 7', 'for (using\nx of []) ; 8', '{ await using x = null; }', 'async function f() { await using x = null; } 9', 'async function f() { for (await using x of []) ; } 10', 'async function f() { await using [a] = []; }', 'var using = 11; using', 'using = 12', 'var using = [13]; using[0]', 'function f() { using x = null; } 14', 'using\nx = null', '{ using let = null; }', '{ using await = null; } 15', 'label: using x = null']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("using_declaration_syntax")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_decorator_syntax(js, golden, tier):
    """CATCHES: decorator parsing that rejects member-chain, call and parenthesized decorators on classes and elements, accepts decorators on functions or object literals, mis-handles a line break after the decorator, or evaluates decorators without validating their return values fails this."""
    code = SE + r"""group('decorators', ['@dec class A {}', 'var dec = function () {}; @dec class A {} 1', 'var d = { e: { f: function () { return function () {}; } } }; @d.e.f() class A {} 2', '@(function () {}) class A {} 3', 'class A { @(x => x) m() {} } 4', '@1 class A {}', '@dec\nclass A {}', 'class A { @dec static #m() {} }', 'class A { @dec constructor() {} }', 'export @dec class A {}', '@dec function f() {}', 'x = @dec class {}', 'x = class { @dec accessor a = 1 }; 5', 'var dec = (v, c) => c.kind; class A { @dec @dec m() {} } 6', 'x = { @dec m() {} }', 'class A { @new X m() {} }', 'class A { @(a, b) m() {} } 7', 'class A { @a?.b m() {} }', 'class A { @a[0] m() {} }', 'class A { @a() () m() {} }']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("decorator_syntax")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_asi_and_rare_valid_syntax(js, golden, tier):
    """CATCHES: a parser with wrong automatic semicolon insertion (return/postfix/++/template/call continuations), contextual keywords that cannot be identifiers, accessor names that are strings/numbers/BigInts/keywords, optional-chaining edge cases, parenthesized assignment targets, or HTML-like comments and hashbangs handled in the wrong positions fails this."""
    code = SE + r"""group('asi and rare valid', ['var a = 1\nvar b = 2\na + b', 'var c = 1\n++c\nc', 'var d = 1\nd\n++\nd', 'function r() { return\n1 } r()', 'x = 5\n(function () {})', 'y = [1]\n[0]', 'z = "s"\n`t`', 'let\n[q] = [9]; q', 'var l2 = 1; l2\n/2/g', 'if (0) ; else ; 1', ';;; 2', 'L1: L2: L3: for (;;) { break L2; } 3', 'outer: for (var i = 0; i < 3; i++) { inner: for (;;) { continue outer; } } i', 'L: { L2: { break L; } } 4', 'a = { get: 1, set: 2 }; a.get + a.set', 'o = { get "x y"() { return "sp"; }, set 5(v) {}, get [`t${1}`]() { return "tpl"; } }; o["x y"] + o.t1', 'o = { get 1e3() { return "num"; } }; o[1000]', 'o = { get 0x10() { return "hex"; } }; o[16]', 'o = { get 1n() { return "big"; } }; o[1]', 'o = { get new() { return "kw"; } }; o.new', 'class K { static get static() { return "s"; } get get() { return "g"; } set set(v) {} static async async() {} } K.static + new K().get', 'async = 1; async', 'of = 2; of', 'get = 3; set = 4; get + set', 'static = 5', 'yield = 6; yield', 'await = 7; await', 'let = 8; let', 'eval("var let = 9"); let', 'a?.b', 'a = { b: { c: 1 } }; a?.b?.c', 'a?.["b"]?.c', 'f = null; f?.()', 'f = function () { return 1; }; f?.()', 'a?.b.c.d', 'null?.x.y.z', 'a = { m() { return this === a; } }; a?.m()', '(a?.m)()', 'x = 1.5; x?.toFixed(1)', 'true ? .5 : 1', 'a = { "5": 1 }; a?.[5]', 'x?.5:1', '1..x', 'a = []; a?.length', 'new.target?.x', '((x)) = 3; x', '[((x))] = [4]; x', '({ a: (x) } = { a: 5 }); x', '({ a: (x.y) } = { a: 6 })', '[(x)] = [7]; x', '((x, y)) = 1', '({ a: ([x]) } = { a: [1] })', '(x) += 1; x', '<!-- html open comment\n10', '11\n--> html close comment', '/* multi\nline */ --> after comment\n12', 'a = 1 <!--x\n; a', 'a = 13; a-->0', '#!/not/hashbang\n1', 'function f() {\n#!x\n}', '"\\u2028 and \\u2029 in strings".length', 'eval("\\u2028 1")', 'x = 1;\u000b\u000c\u00a0\ufeff x', '/*\u2028*/ 14']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("asi_and_rare_valid_syntax")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_global_script_declaration_instantiation_and_function_bodies(js, golden, tier):
    """CATCHES: script evaluation ($262.evalScript) that lets later scripts redeclare earlier let/const/class bindings with var/let/function, skips CanDeclareGlobalFunction/Var checks for non-configurable or non-extensible globals, accepts top-level using/await/return/super, misplaces hashbangs, or a Function constructor whose body errors leak through the synthesized wrapper fails this."""
    code = "var out = [];\n" + r"""function es(src) { try { var v = $262.evalScript(src); return 'ok' + (v === undefined ? '' : ' ' + String(v)); } catch (e) { return e.name + ': ' + e.message; } }
function t(src) { out.push(JSON.stringify(src) + ' => ' + es(src)); }
['let gl = 1; gl', 'let gl = 2', 'var gl = 3', 'function gl() {}', 'gl', 'const gc = 1; gc', 'gc = 2', 'class GC {}', 'var GC', 'var gv = 1; gv', 'let gv', 'function gf() { return "gf"; } gf()', 'let gf', 'using u = null', 'await using u = null', 'await 1', 'yield 1', 'var x = 1; var x = 2; x', 'let y = 1; var y', 'let z; { var z; }', '"use strict"; var undefined', 'var NaN; typeof NaN', 'function NaN() {}', 'let Infinity = 1', 'var globalThis2 = globalThis === this; globalThis2', 'this === globalThis', 'new.target', 'return 1', 'break', 'L: { break L; } "labelled"', 'super.x', 'import.meta', 'export default 1', 'import("./none.mjs").catch(function () {}); 1', 'arguments', 'typeof arguments', '#!hashbang\n"after hashbang"', ' #!not-at-start', 'eval("1+1")', '(0, eval)("let ev = 1; ev")', 'ev', 'let tdz = tdz;', 'tdz', 'let late; late = "assigned"; late', 'Object.defineProperty(globalThis, "nonConfig", { value: 1, configurable: false }); 1', 'let nonConfig = 2', 'var nonConfig = 3; nonConfig', 'function nonConfig() {}', 'Object.preventExtensions(globalThis); 1', 'var brandNew', 'function brandNewFn() {}', 'let brandNewLet = "lexical ok"; brandNewLet'].forEach(t);
out.push('# Function constructor bodies');
function fc(params, body) { try { var f = Function.apply(null, params.concat([body])); return 'ok ' + String(f()); } catch (e) { return e.name + ': ' + e.message; } }
[[[], 'return 1 +'], [[], 'let a; let a;'], [['a'], 'let a;'], [['a', 'a'], 'return a'], [['a', 'a'], '"use strict"'], [['a = 1'], 'return a'], [['...a'], 'return a.length'], [['{ x }'], 'return x'], [[], 'return new.target'], [[], 'super.x'], [[], 'yield 1'], [[], 'return arguments.length'], [['a,b'], 'return a + b'], [[], '"use strict"; return this'], [[], '<!-- html\nreturn "html ok"'], [[], 'break'], [[], 'return\n1'], [['/* c */'], 'return "comment params"']].forEach(function (p) { out.push(JSON.stringify(p) + ' => ' + fc(p[0], p[1])); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("global_script_declaration_instantiation_and_function_bodies")
    assert (r.returncode, r.stderr) == (0, b"")


MODULE_CASES = {
 "dup_export": "export var a = 1; export { a };",
 "dup_export_default": "export default 1; export default 2;",
 "export_undeclared": "export { nothere };",
 "dup_lexical": "let a; const a = 1;",
 "var_lexical_clash": "var a; let a;",
 "fn_lexical_clash": "function f() {} let f;",
 "dup_fn_module": "function f() {} function f() {}",
 "attr_dup": "import x from \"./data.json\" with { type: \"json\", type: \"json\" };",
 "attr_nonstring": "import x from \"./data.json\" with { type: 1 };",
 "attr_ok": "import x from \"./data.json\" with { type: \"json\" }; export default x.v;",
 "attr_string_key": "import x from \"./data.json\" with { \"type\": \"json\" }; export default x.v;",
 "export_string_local": "export { \"str\" };",
 "export_string_from": "export { \"a b\" as \"c d\" } from \"./lib.mjs\"; export default \"re-exported\";",
 "import_string_no_as": "import { \"a b\" } from \"./lib.mjs\";",
 "import_string_as": "import { \"a b\" as ab } from \"./lib.mjs\"; export default ab;",
 "import_reserved_binding": "import { x as eval } from \"./lib.mjs\";",
 "import_reserved_binding2": "import { arguments } from \"./lib.mjs\";",
 "lone_surrogate_name": "export { x as \"\\ud800\" } from \"./lib.mjs\";",
 "await_ident": "var await = 1;",
 "await_label": "await: 1;",
 "await_class": "class await {}",
 "await_top": "export default await Promise.resolve(\"tla\");",
 "html_comment": "var x = 1; <!-- not a comment in modules\n",
 "html_close": "var x = 1;\n--> nope\n",
 "new_target_top": "new.target;",
 "import_meta_ok": "export default typeof import.meta;",
 "escaped_default": "export d\\u0065fault 1;",
 "escaped_as": "var x; export { x \\u0061s y };",
 "escaped_from": "export * fr\\u006fm \"./lib.mjs\";",
 "escaped_import_meta": "import.m\\u0065ta;",
 "escaped_import": "i\\u006dport x from \"./lib.mjs\";",
 "nested_export": "{ export var x; }",
 "nested_import": "if (1) import x from \"./lib.mjs\";",
 "export_default_async_fn": "export default async function named() { return 5; }",
 "export_default_class": "export default class { static v = 6 }",
 "export_default_fn_anon": "export default function () { return 7; }",
 "strict_in_module": "with ({}) {}",
 "delete_ident_module": "var q; delete q;",
 "octal_module": "var o = 010;",
 "yield_ident": "var yield = 1;",
 "let_ident": "var let = 1;",
 "export_star_as": "export * as ns from \"./lib.mjs\"; export default \"star as\";",
 "export_star_as_string": "export * as \"a b\" from \"./lib.mjs\"; export default \"star as string\";",
 "import_defer": "import defer * as ns from \"./lib.mjs\"; export default typeof ns;",
 "import_source": "import source s from \"./lib.mjs\";",
 "missing_specifier": "import x from y;",
 "export_let_dup_import": "import { x } from \"./lib.mjs\"; let x;",
 "import_dup_binding": "import { x, x } from \"./lib.mjs\";",
 "using_top_module": "using u = null; export default \"using ok\";",
 "await_using_top_module": "await using u = null; export default \"await using ok\";",
 "super_top": "super.x;",
 "return_top": "return;",
 "private_top": "this.#x;",
 "hashbang_module": "#!/usr/bin/env lumen-cli\nexport default \"hashbang module\";",
 "arguments_top": "export default typeof arguments;",
 "this_top": "export default String(this);",
 "export_default_expr_then_decl": "export default (1, 2); export const k = 3;",
 "export_async_arrow": "export const f = async () => 8; export default await f();"
}


@pytest.mark.parametrize("tier", TIERS)
def test_module_only_syntax_errors(js, golden, workdir, tier):
    """CATCHES: a module parser that misses duplicate or undeclared exports, lexical clashes, bad import attributes, string export names that are not well-formed, escaped contextual keywords, nested import/export, await/yield/let bindings in module (strict, async) code, or HTML-like comments in modules, or that rejects valid top-level await, using and default-export forms fails this."""
    (workdir / "lib.mjs").write_text('export var x = 1; var ab = "AB"; export { ab as "a b" };\n', encoding="utf-8")
    (workdir / "data.json").write_text('{"v": "json value"}', encoding="utf-8")
    for name, src in MODULE_CASES.items():
        (workdir / f"{name}.mjs").write_text(src + "\n", encoding="utf-8")
    code = "var names = " + repr(list(MODULE_CASES)).replace("'", '"') + r""";
(async function () {
  for (var n of names) {
    try { var m = await import('./' + n + '.mjs'); console.log(n + ': ok ' + String(m.default)); }
    catch (e) { console.log(n + ': ' + e.name + ': ' + e.message); }
  }
})();
"""
    r = js(code, *tier)
    assert out(r) == golden("module_only_syntax_errors")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_deep_nesting_and_large_sources(js, golden, tier):
    """CATCHES: a parser or evaluator that overflows, truncates or slows down on moderately deep nesting (parentheses, arrays, objects, blocks, functions, arrows, ternaries, templates, if/else, labels) or on large sources (long chains, big array/object literals, thousands of statements/functions/cases/lines, long strings, identifiers and regexps, many parameters) fails this."""
    code = "var out = [];\n" + r"""var N = 200;
function t(label, f) { try { out.push(label + ': ' + f()); } catch (e) { out.push(label + ': ' + e.name + ': ' + e.message); } }
t('nested parens', function () { return eval('('.repeat(N) + '7' + ')'.repeat(N)); });
t('nested arrays', function () { var v = eval('['.repeat(N) + '1' + ']'.repeat(N)); var d = 0; while (Array.isArray(v)) { v = v[0]; d++; } return d + ' ' + v; });
t('nested objects', function () { var src = ''; for (var i = 0; i < N; i++) src += '{a:'; src += '1' + '}'.repeat(N); var v = eval('(' + src + ')'); var d = 0; while (typeof v === 'object') { v = v.a; d++; } return d; });
t('nested blocks', function () { return eval('{'.repeat(N) + '"block"' + '}'.repeat(N)); });
t('nested functions', function () { var src = 'function () { return '.repeat(100) + '"deep"' + '; }'.repeat(100); var f = eval('(' + src + ')'); for (var k = 0; k < 99; k++) f = f(); return f(); });
t('nested arrows', function () { var src = ''; for (var i = 0; i < 150; i++) src += '() => '; src += '"arrow"'; var f = eval(src); for (var k = 0; k < 150; k++) f = f(); return f; });
t('nested ternaries', function () { var src = ''; for (var i = 0; i < N; i++) src += 'false ? ' + i + ' : '; src += '"last"'; return eval(src); });
t('long binary chain', function () { var parts = []; for (var i = 0; i < 300; i++) parts.push(i); return eval(parts.join('+')); });
t('long string concat chain', function () { var parts = []; for (var i = 0; i < 300; i++) parts.push('"' + (i % 10) + '"'); return eval(parts.join(' + ')).length; });
t('nested template literals', function () { var src = '"core"'; for (var i = 0; i < 60; i++) src = '`[${' + src + '}]`'; return eval(src).length; });
t('nested if-else', function () { var src = ''; for (var i = 0; i < N; i++) src += 'if (false) ' + i + '; else '; src += '"else end"'; return eval(src); });
t('nested loops with labels', function () { var src = ''; for (var i = 0; i < 50; i++) src += 'L' + i + ': for (var i' + i + ' = 0; i' + i + ' < 1; i' + i + '++) '; src += 'break L0;'; eval(src); return 'ok'; });
t('large array literal', function () { var parts = []; for (var i = 0; i < 3000; i++) parts.push(i % 7); var a = eval('[' + parts.join(',') + ']'); return a.length + ' ' + a.reduce(function (x, y) { return x + y; }); });
t('large object literal', function () { var parts = []; for (var i = 0; i < 2000; i++) parts.push('k' + i + ': ' + i); var o = eval('({' + parts.join(',') + '})'); return Object.keys(o).length + ' ' + o.k1999; });
t('many statements', function () { var parts = []; for (var i = 0; i < 2000; i++) parts.push('s += ' + (i % 3) + ';'); return eval('var s = 0; ' + parts.join('\n') + ' s'); });
t('many functions', function () { var parts = []; for (var i = 0; i < 600; i++) parts.push('function fn' + i + '() { return ' + i + '; }'); parts.push('fn599() + fn0() + fn300()'); return eval(parts.join('\n')); });
t('long string literal', function () { var s = 'x'.repeat(100000); return eval('"' + s + '"').length; });
t('long identifier', function () { var id = 'v' + 'a'.repeat(5000); return eval('var ' + id + ' = "long id"; ' + id); });
t('long regexp', function () { var body = 'a'.repeat(3000); return eval('/' + body + '/').test(body); });
t('many lines', function () { var src = '\n'.repeat(20000) + '"after many lines"'; return eval(src); });
t('syntax error after many lines', function () { try { eval('\n'.repeat(3000) + 'var = 1'); } catch (e) { return e.name + ': ' + e.message; } });
t('large switch', function () { var parts = []; for (var i = 0; i < 500; i++) parts.push('case ' + i + ': r = ' + (i * 2) + '; break;'); return eval('var r; switch (499) { ' + parts.join(' ') + ' } r'); });
t('JSON deep', function () { var src = '['.repeat(N) + ']'.repeat(N); return JSON.stringify(JSON.parse(src)).length; });
t('Function with many params', function () { var ps = []; for (var i = 0; i < 1000; i++) ps.push('p' + i); var f = Function(ps.join(','), 'return p999 + arguments.length'); return f.length + ' ' + f.apply(null, ps.map(function (x, i) { return i; })); });
""" + END
    r = js(code, *tier)
    assert out(r) == golden("deep_nesting_and_large_sources")
    assert (r.returncode, r.stderr) == (0, b"")


def test_cli_eval_syntax_error_report_format(run):
    """CATCHES: a CLI whose `-e` mode does not report parse failures as `SyntaxError: <message> (line N)` on stderr with exit status 1 and no stdout, counts lines wrongly across LF/CRLF/comments/templates, or executes any statement of a script that fails to parse fails this."""
    cases = [
        ("console.log('must not run'); let x = ;", 'SyntaxError: unexpected token Punct(";") (line 1)'),
        ("a = 1\nb = 2\nc = ;", 'SyntaxError: unexpected token Punct(";") (line 3)'),
        ("// c1\n/* c2\n c3 */\nvar = 1", "SyntaxError: expected binding identifier (line 4)"),
        ("var s = `line1\nline2`;\n)", 'SyntaxError: unexpected token Punct(")") (line 3)'),
        ("1\r\n2\r\n3 +", "SyntaxError: unexpected token Eof (line 3)"),
        ('"unterminated', "SyntaxError: unterminated string literal (line 1)"),
        ("var a;\nlet a;", "SyntaxError: Identifier 'a' has already been declared (line 2)"),
        ('"use strict";\nwith (a) {}', "SyntaxError: 'with' statements are not allowed in strict mode (line 2)"),
        ("class A {\n constructor() {}\n constructor() {}\n}", "SyntaxError: a class may only have one constructor (line 4)"),
        ("\n\n\nbreak;", "SyntaxError: illegal 'break' statement (line 4)"),
        ("`${", "SyntaxError: unterminated template substitution (line 1)"),
        ("/re", "SyntaxError: unterminated regular expression (line 1)"),
        ("for (;;) {\n", "SyntaxError: expected '}' (line 2)"),
        ("using x = null", "SyntaxError: 'using' declaration is not allowed at the top level of a script (line 1)"),
        ("import x from 'y'", "SyntaxError: expected '(' (line 1)"),
        ("x = { __proto__: 1,\n __proto__: 2 }", "SyntaxError: duplicate __proto__ property in object literal (line 2)"),
    ]
    got = []
    for src, _ in cases:
        r = run(["-e", src])
        got.append((src, out(r), err(r), r.returncode))
    assert got == [(src, "", expected + "\n", 1) for src, expected in cases]


def test_file_stdin_and_require_syntax_error_formats(run, workdir):
    """CATCHES: a CLI that reports file-level parse failures differently from `Uncaught SyntaxError: <message>` (exit 1, nothing executed), mis-reports stdin parse errors, fails to surface a required module's SyntaxError as catchable, or mishandles hashbang/BOM/HTML-comment prologues in CommonJS and ESM files fails this."""
    files = {
        "bad.js": 'console.log("first");\nvar x = ;\n',
        "bad.mjs": 'console.log("first");\nexport default ;\n',
        "hb.js": '#!/usr/bin/env lumen-cli\nconsole.log("hashbang ok", typeof require);\n',
        "hb.mjs": '#!/x\nexport default 1; console.log("module hashbang");\n',
        "hb_late.js": ' #!/x\nconsole.log(1)\n',
        "bom.js": '\ufeffconsole.log("bom ok");\n',
        "html.js": '<!-- html in file\nconsole.log("html ok")\n--> closing\n',
        "html.mjs": '<!-- html in module\nconsole.log("never")\n',
        "req.js": 'console.log("main"); require("./bad.js");\n',
        "req2.js": 'console.log("main"); try { require("./bad.js"); } catch (e) { console.log("caught", e.name, e.message); }\n',
        "dyn.mjs": 'import("./bad.mjs").catch(e => console.log("dyn", e.name, e.message));\n',
        "lines.js": 'var ok = 1;\n\n\n\nfunction f() {\n  return 1 +;\n}\n',
    }
    for name, src in files.items():
        (workdir / name).write_text(src, encoding="utf-8")
    expected = {
        "bad.js": ("", 'Uncaught SyntaxError: unexpected token Punct(";")\n', 1),
        "bad.mjs": ("", 'Uncaught SyntaxError: unexpected token Punct(";")\n', 1),
        "hb.js": ("hashbang ok function\n", "", 0),
        "hb.mjs": ("module hashbang\n", "", 0),
        "hb_late.js": ("", "Uncaught SyntaxError: unterminated regular expression\n", 1),
        "bom.js": ("bom ok\n", "", 0),
        "html.js": ("html ok\n", "", 0),
        "html.mjs": ("", 'Uncaught SyntaxError: unexpected token Punct("<")\n', 1),
        "req.js": ("main\n", 'Uncaught SyntaxError: unexpected token Punct(";")\n', 1),
        "req2.js": ('main\ncaught SyntaxError unexpected token Punct(";")\n', "", 0),
        "dyn.mjs": ('dyn SyntaxError unexpected token Punct(";")\n', "", 0),
        "lines.js": ("", 'Uncaught SyntaxError: unexpected token Punct(";")\n', 1),
    }
    got = {}
    for name in files:
        r = run([name])
        got[name] = (out(r), err(r), r.returncode)
    assert got == expected
    r = run([], input="console.log('never');\n\n\nvar x = ;")
    assert (out(r), err(r), r.returncode) == ("", 'SyntaxError: unexpected token Punct(";") (line 4)\n', 1)
    r = run([], input="#!/stdin/hashbang\nconsole.log('stdin hashbang ok')")
    assert (out(r), err(r), r.returncode) == ("stdin hashbang ok\n", "", 0)


@pytest.mark.parametrize("tier", TIERS)
def test_directive_prologues_and_strictness(js, golden, tier):
    """CATCHES: directive-prologue handling that treats non-leading, parenthesized, escaped or concatenated 'use strict' strings as directives, misses retroactive octal errors around the directive, or fails to propagate strictness into nested functions, class bodies, eval code and this/arguments semantics fails this."""
    code = SE + r"""group('directive prologues', ['"use strict"; (function () { return this; })()', '"other"; "use strict"; (function () { return this; })()', '1; "use strict"; (function () { return typeof this; })()', '("use strict"); (function () { return typeof this; })()', '"use\\x20strict"; (function () { return typeof this; })()', "'use strict'; (function () { return this; })()", '"use strict" + 1; (function () { return typeof this; })()', '"use strict"\n010', '"use strict"\n;010', '"\\07"; "use strict"', '"use strict"; "\\07"', 'function f() { "use strict"; return this; } f()', 'function f() { "use strict"; return function () { return this; }(); } f()', 'function f() { return function () { "use strict"; return typeof this; }(); } f()', '(() => { "use strict"; return this === globalThis; })()', 'class C { m() { return function () { return this; }(); } } new C().m()', 'class C { m() { return eval("var leaked = 1; typeof leaked"); } } new C().m() + " " + typeof leaked', '({ get g() { "use strict"; return typeof this; } }).g', 'function f() { "use strict"; return eval("this"); } f()', 'function f() { "use strict"; eval("var e1 = 1"); return typeof e1; } f()', 'function f() { eval("\'use strict\'; var e2 = 1"); return typeof e2; } f()', '"use strict"; function g() { return typeof this; } g.call(5)', 'function g() { return typeof this; } g.call(5)', '"use strict"; Object.defineProperty({}, "x", { value: 1 }).x = 2', 'Object.defineProperty({}, "x", { value: 1 }).x = 2; "silent"', 'function f(a, b) { "use strict"; a = 9; return arguments[0]; } f(1, 2)', 'function f(a, b) { a = 9; return arguments[0]; } f(1, 2)', '"use strict"; (function () { return arguments.callee; })()', 'function f() { "use strict"; } f.caller', '"use strict"; typeof Function("return this")()', '"use strict"; var o = { a: 1 }; Object.freeze(o); o.a = 2', '"use strict"; undefinedName = 1', '"use strict"; ({}).x.y']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("directive_prologues_and_strictness")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_parameter_list_syntax_and_scoping(js, golden, tier):
    """CATCHES: parameter handling with wrong default-value scoping (TDZ for later params, closures over the parameter scope vs body vars), bad rest-parameter rules, wrong function length for defaults/rest, or misplaced super/yield/await/new.target in parameter initializers fails this."""
    code = SE + r"""group('parameters', ['function f(a, b = a + 1, c = b * 2) { return [a, b, c].join(); } f(1)', 'function f(a = b, b = 1) { return a; } f()', 'function f(a = arguments.length) { return a; } f(undefined, 2, 3)', 'function f(a, b = () => a) { var a = "body"; return b(); } f("param")', 'function f(a, b = () => a) { a = "reassigned"; return b(); } f("param")', 'function f({ x = 1, y } = {}, [z = 2] = []) { return [x, y, z].join(); } f()', 'function f(...[a, b]) { return a + b; } f(1, 2)', 'function f(...{ length }) { return length; } f(1, 2, 3)', 'function f(a, ...rest,) {}', 'function f(...a = []) {}', 'function f(a,) { return f.length; } f()', '(function (a, b = 1, c) {}).length', '((a, ...b) => {}).length', 'function f(x = this) { return typeof x; } f.call("s")', 'function f(x = new.target) { return x === undefined; } f()', 'function* g(x = 1) { yield x; } g().next().value', 'async function af(x = 1) { return x; } typeof af()', 'function f(eval) { return eval; } f(3)', 'function f(arguments) { return arguments; } f(4)', 'function f(a, a) { "use strict"; }', 'function f(x = super.y) {}', 'var o = { m(x = super.toString) { return typeof x; } }; o.m()', 'function f(x = yield) { return x; } f()', 'function f(x = await) { return x; } f()', '(a = 1, { b }, [c]) => a', '({ a } = {}) => a', '([a] = [1]) => a', '(a, b) => a + b', '() => {}', '(...a) => a.length', 'async (...a) => a.length', 'async x => x', 'async (x) => await x', 'x => { return x; }', 'x => ({ x })']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("parameter_list_syntax_and_scoping")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_label_syntax_and_semantics(js, golden, tier):
    """CATCHES: a parser or evaluator that rejects labels named by contextual keywords in sloppy code, allows duplicate nested labels or continue to non-iteration/outer-function labels, or mis-targets labelled break/continue across blocks, try/finally, do-while and function boundaries fails this."""
    code = SE + r"""group('labels', ['L: for (var i = 0; i < 3; i++) { for (;;) { continue L; } } i', 'L: { break L; } "after block"', 'L: if (true) break L; "after if"', 'L: try { break L; } finally { 1; } "after try"', 'L: L2: { break L; } "nested"', 'L: { L: ; }', 'L: { M: { break L; } } "inner label"', 'L: function f() {} typeof f', 'yield: { break yield; } "yield label"', 'await: { break await; } "await label"', 'let: 1', 'static: 1', 'async: 1', 'of: 2', 'L: while (false) {} L: while (false) {} "reused label"', 'L: for (;;) { (function () { L: for (;;) { break L; } })(); break L; } "function boundary"', 'L: do { continue L; } while (false); "do continue"', 'x: { var y = 1; } y', 'L: { continue L; }', 'L: while (0) { function f() { continue L; } }', 'L:\nfor (;;) break L; "label newline"']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("label_syntax_and_semantics")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_await_and_yield_context_rules(js, golden, tier):
    """CATCHES: a parser that applies await/yield keyword rules to the wrong nesting levels (nested plain functions, arrows, class field initializers, computed keys, static blocks, parameter lists, function names) or mis-tokenizes a regexp/newline after yield and await fails this."""
    code = SE + r"""group('await and yield contexts', ['async function f() { function inner() { var await = 1; return await; } return inner(); } 1', 'async function f() { return () => await 1; } 2', 'async function f() { return async () => await 1; } 3', 'async function f() { (function () { await 1; }); }', 'function* g() { function inner() { var yield = 1; return yield; } return inner(); } g().next().value', 'function* g() { return () => yield; }', 'function* g() { yield yield 1; } var it = g(); it.next(); it.next(5).value', 'function* g() { yield* yield; } 4', 'function* g() { var x = yield; return x; } var it = g(); it.next(); it.next(7).value', 'function* g() { yield\n1; } [...g()].length', 'async (await) => 1', 'async (x = await 1) => x', 'async ({ await }) => 1', 'async function await() {} 5', 'async function f(await) {}', 'function* yield() {}', 'function* g(yield) {}', '(function* yield() {})', '(async function await() {})', 'var async = function (x) { return "called " + x; }; async(1)', 'var async = 2; async\n(3)', 'class C { async *[Symbol.asyncIterator]() { yield await 1; } } 6', 'class C { static async m() { for await (const x of []) ; } } 7', 'class C { x = await; }', 'async function f() { class C { x = await 1; } }', 'async function f() { class C { [await 1]() {} } } 8', 'function* g() { class C { [yield 1]() {} } } 9', 'function* g() { class C { x = yield; } }', 'class C { static { function f() { var await = 1; return await; } } } 10', 'class C { static { (() => await) } }', 'async () => { for await (x of y) ; }; 11', 'async function f() { await using x = null; using y = null; } 12', 'function* g() { yield /x/g; } 13', 'function* g() { yield\n/x/g; } 14', 'async function f() { await /x/; } 15', 'yield\n/1/g', 'async function f() { await\n1; } 16', 'function f() { return typeof yield; } f()', 'function* g() { return typeof yield; } g().next().value', 'async function* ag() { yield* [1]; await 1; for await (var x of [2]) yield x; } typeof ag().next']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("await_and_yield_context_rules")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_comments_and_line_terminators_drive_asi(js, golden, tier):
    """CATCHES: a lexer/parser that does not treat multi-line block comments and CR/CRLF/LS/PS as line terminators for automatic semicolon insertion (return, throw, ++), inserts semicolons where no line break exists, or mis-handles nested-looking block comments fails this."""
    code = SE + r"""group('comments and line terminators', ['var a = 1, b = 2; a /* comment\n */ ++b; [a, b].join()', 'var r = (function () { return /*\n*/ 1; })(); String(r)', 'var r2 = (function () { return /* same line */ 2; })(); r2', 'var c = 1 c', 'var d = 1 d + 1', 'var e = 3 // comment e', '/* line sep */ var f2 = 4; f2', 'var g2 = 5;\r\ng2', 'var h = 6;\rh', 'var i2 = 7\n// trailing comment', 'x = 1 /*\n*/ -->html comment after newline in block comment\n; x', '/**/ --> not at line start? ok\n1', 'var j = 8 /*a*//*b*/; j', 'var k = 9 /* /* nested? */ k', 'var s = "a\\ b"; s.length', 'var t = ` `; t.length', 'throw /*\n*/ 1', 'var m = 1; m\n++\nm', 'a = b\n(1)', 'var q = [1,\n2,\n3\n]; q.length']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("comments_and_line_terminators_drive_asi")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_object_and_array_literal_forms(js, golden, tier):
    """CATCHES: literal evaluation with wrong numeric-key canonicalization, hole/trailing-comma handling, spread of null/primitives, computed-key evaluation order, duplicate data/accessor property merging, special __proto__ forms, or function name inference for literal members fails this."""
    code = SE + r"""group('literal forms', ['({ 1.0: "a", 1e3: "b", .5: "c", 0x10: "d", 1n: "e", "01": "f" }) && Object.keys({ 1.0: "a", 1e3: "b", .5: "c", 0x10: "d", 1n: "e", "01": "f" }).join()', '[1, , 3,].length', '[, , ,].length', '[...[1, 2], ...[], ...[3]].join()', '({ ...null, ...undefined, ...123, ..."ab", ...[9] })[1]', 'var log = []; ({ [log.push(1)]: log.push(2), [log.push(3)]: log.push(4) }); log.join()', '({ a: 1, a: 2 }).a', '({ get a() { return 1; }, a: 2 }).a', '({ a: 2, get a() { return 1; } }).a', '({ set a(v) {}, get a() { return "both"; } }).a', '({ async *gen() { yield 1; } }).gen.constructor.name', '({ "constructor"() { return 1; } }).constructor()', '({ __proto__() { return "method"; } }).__proto__()', '({ get __proto__() { return "getter"; } }).__proto__', 'Object.getPrototypeOf({ ["__proto__"]: null }) === Object.prototype', '`a${1}${2}b`', '"\\u{10FFFF}".codePointAt(0).toString(16)', '[0b11, 0o17, 0x1f, 1e2, 1E-2, .1, 1., 1_0].join()', 'typeof /regex/', '(() => ({}))().constructor === Object', '[function () {}][0].name', '({ f: function () {} }).f.name', '({ ["computed" + "Name"]: () => {} }).computedName.name', '({ [Symbol.iterator]: function () {} })[Symbol.iterator].name', '({ 123: function () {} })[123].name', 'new Function("a", "b", "return a + b")(1, 2)']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("object_and_array_literal_forms")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_dynamic_import_options_and_phases(js, golden, workdir, tier):
    """CATCHES: dynamic import() that does not validate its options argument and `with` attributes (non-objects, non-string values, proxies, non-enumerable and symbol keys, throwing getters) before loading, mis-coerces specifiers, mishandles import.source/import.defer, or returns different namespaces for one module fails this."""
    (workdir / "m.mjs").write_text('export default "mod";\n', encoding="utf-8")
    (workdir / "d.json").write_text('{"j": 1}', encoding="utf-8")
    code = r"""var log = [];
async function t(label, f) { try { var r = await f(); log.push(label + ': ok ' + (r && typeof r === 'object' ? Object.keys(r).sort().join('/') + (r.default !== undefined ? '=' + JSON.stringify(r.default) : '') : String(r))); } catch (e) { log.push(label + ': ' + e.name + ': ' + e.message.replace(/ \(imported from .*\)/, '')); } }
await t('plain', () => import('./m.mjs'));
await t('options undefined', () => import('./m.mjs', undefined));
await t('options not object', () => import('./m.mjs', 5));
await t('with undefined', () => import('./m.mjs', {}));
await t('with not object', () => import('./m.mjs', { with: 'json' }));
await t('json with type', () => import('./d.json', { with: { type: 'json' } }));
await t('attribute non-string', () => import('./d.json', { with: { type: 1 } }));
await t('proxy attributes', () => import('./d.json', { with: new Proxy({ type: 'json' }, {}) }));
await t('proxy attributes non-string', () => import('./d.json', { with: new Proxy({ type: 2 }, {}) }));
await t('proxy attributes non-enumerable', () => import('./m.mjs', { with: new Proxy({}, { ownKeys: () => ['type', 'skip'], getOwnPropertyDescriptor: (t, k) => k === 'skip' ? undefined : { value: 'x', enumerable: false, configurable: true } }) }));
await t('symbol keyed attribute ignored', () => import('./m.mjs', { with: { [Symbol('s')]: 1 } }));
await t('non-enumerable attribute ignored', () => import('./m.mjs', { with: Object.defineProperty({}, 'type', { value: 5, enumerable: false }) }));
await t('with getter throws', () => import('./m.mjs', { get with() { throw new EvalError('with getter'); } }));
await t('specifier toString throws', () => import({ toString() { throw new RangeError('specifier'); } }));
await t('specifier object', () => import({ toString() { return './m.mjs'; } }));
await t('missing module', () => import('./nope.mjs'));
await t('import.source', () => import.source('./m.mjs'));
await t('import.defer', () => import.defer('./m.mjs'));
await t('same namespace twice', async () => (await import('./m.mjs')) === (await import('./m.mjs')));
await t('namespace tag', async () => Object.prototype.toString.call(await import('./m.mjs')));
await t('import from script-like eval', () => (0, eval)('import("./m.mjs")'));
console.log(log.join('\n'));
"""
    r = js(code, *tier, name="main.mjs")
    assert out(r) == golden("dynamic_import_options_and_phases")
    assert (r.returncode, r.stderr) == (0, b"")


@pytest.mark.parametrize("tier", TIERS)
def test_parser_rare_error_paths_and_statement_positions(js, golden, tier):
    """CATCHES: a parser that accepts private names as bindings/labels/function names, `let` in for-of lexical patterns, using with patterns, misplaced shorthand cover initializers, escaped `new`/`import` in expressions, `new await`, duplicate method parameters, reserved catch/arrow parameters in generators or strict bodies, super() outside derived constructors, arguments in field initializers, bad object-literal method modifiers, or Annex B function declarations in loop/with bodies fails this."""
    code = SE + r"""group('rare parser paths', ['{ using x = null, [y] = []; }', '{ using x = null, { y } = {}; }', 'class A { #a; m() { var #a; } }', 'class A { #a; m(#a) {} }', 'class A { m() { function #f() {} } }', 'for (let [let] of []) ;', 'for (const { let } of []) ;', 'class A { #x; m() { #x: 1; } }', 'var a; (a) = function () {}; a.name', 'var b; (b) = class {}; b.name', 'var c2; c2 = function () {}; c2.name', '[{ a = 1 }.b] = [];', '({ a = 1 }).x', 'async function f() { class C { static { await 1; } } }', 'delete undefined', 'class A { #p; m() { super.#p(); } }', 'function f() { return 1; } f()`x`', 'var tagf = function () { return function (s) { return s[0]; }; }; tagf()`inner`', 'x = n\\u0065w Object()', 'async function f() { new await x; }', 'new a?.b.c', 'x = typ\\u0065of 1', 'x = super', 'x = i\\u006dport("a")', '({ a b })', 'function* g() { function yield() {} }', 'function* g() { try {} catch (yield) {} }', 'function* g() { (yield) => 1; }', 'class A { m(a, a) {} }', 'class A { static s(a, a) {} }', '({ m(a, a) {} })', '(interface) => { "use strict"; }', '(a, implements) => { "use strict"; }', 'class A extends Object { m() { super(); } }', 'class A extends Object { get g() { super(); } }', 'function f() { class A { [arguments] = 1 } }', 'class A { x = () => arguments; }', 'class A { static { var x = () => arguments; } }', 'class A { static { class B { [arguments] = 1 } } }', 'L: L: ;', 'yield: yield: 1', 'function f() { "use strict"; L: { implements: 1; } }', 'x = { get a() {}, get a() {} }; 1', 'x = { a, }; 2', 'x = { ...a, }; 3', 'x = { async, get, set, static }', 'x = { async *[Symbol.iterator]() {} }; 4', '({ async get x() {} })', '({ get *x() {} })', '({ *get x() {} })', '({ async *get() {} }); 5', 'class A { static async *#m() {} } 6', 'class A { get #a() {} static set #a(v) {} }', 'class A { #a; static #a; }', 'class A { constructor() {} ["constructor"]() {} } 7', 'class A { static ["prototype"]() {} }', 'class A { "prototype"() {} } 8', 'new.target', 'function f() { return new.target === undefined; } f()', 'x = { m() { return new.target; } }; x.m()', 'x = () => { "use strict"; return this; }; typeof x()', 'a\n++\nb', 'if (a) function f() {} else function g() {}', '"use strict"; if (a) function f() {}', 'while (false) function f() {}', 'for (;false;) function f() {}', 'do function f() {} while (false)', 'with ({}) function f() {}', 'L: L2: function f() {} 9']);""" + END
    r = js(code, *tier)
    assert out(r) == golden("parser_rare_error_paths_and_statement_positions")
    assert (r.returncode, r.stderr) == (0, b"")


MODULE_FORMS = {
 "star_missing_as": "import * x from \"./lib.mjs\";",
 "export_star_missing_from": "export * as ns \"./lib.mjs\";",
 "import_assign": "import { x } from \"./lib.mjs\"; x = 2;",
 "import_assign_ns": "import * as ns from \"./lib.mjs\"; ns.x = 2;",
 "import_live_binding": "import { counter, bump } from \"./live.mjs\"; bump(); bump(); export default counter;",
 "assert_newline": "import x from \"./lib.mjs\"\nassert({ type: \"json\" });",
 "import_from_from": "import from from \"./from.mjs\"; export default from;",
 "escaped_as_import": "import { x \\u0061s y } from \"./lib.mjs\";",
 "escaped_as_export_from": "export { x \\u0061s y } from \"./lib.mjs\";",
 "escaped_as_star": "import * \\u0061s ns from \"./lib.mjs\";",
 "default_escaped_import": "import { d\\u0065fault as d } from \"./lib.mjs\"; export default d;",
 "export_default_let": "export default let;",
 "export_let_list": "export let p = 1, q = 2; export default p + q;",
 "export_destructured": "export const { r = 3, s } = { s: 4 }; export default r + s;",
 "export_class_and_fn": "export class K {} export function fn() {} export default typeof K + typeof fn;",
 "export_reserved_local": "var v = 1; export { v as default, v as \"string name\" }; ",
 "export_keyword_name": "var v = 1; export { v as if, v as class };",
 "import_keyword_name": "import { if as iff } from \"./kw.mjs\"; export default iff;",
 "tla_in_function": "function f() { await 1; }",
 "tla_for_await": "var acc = []; for await (const v of [Promise.resolve(1), 2]) acc.push(v); export default acc.join();",
 "module_this_arrow": "export default (() => typeof this)();",
 "module_eval_var": "eval(\"var fromEval = 1\"); export default typeof fromEval;"
}


@pytest.mark.parametrize("tier", TIERS)
def test_module_import_export_forms_and_bindings(js, golden, workdir, tier):
    """CATCHES: module parsing/linking that misses `as`/`from` in star forms, allows assignment to imported bindings or namespace properties, breaks live bindings, treats a next-line `assert(...)` as import attributes, mishandles `from` as a binding name, escaped `as`, IdentifierName/keyword export names, destructured and list exports, or top-level await and for-await in modules fails this."""
    files = {
        "lib.mjs": 'export var x = 1; export default "lib default";\n',
        "live.mjs": 'export var counter = 0; export function bump() { counter++; }\n',
        "from.mjs": 'export default "from module";\n',
        "kw.mjs": 'var k = "keyword export"; export { k as if };\n',
    }
    for name, src in {**files, **{k + ".mjs": v + "\n" for k, v in MODULE_FORMS.items()}}.items():
        (workdir / name).write_text(src, encoding="utf-8")
    code = "var names = " + repr(list(MODULE_FORMS)).replace("'", '"') + r""";
(async function () { for (var n of names) { try { var m = await import('./' + n + '.mjs'); console.log(n + ': ok ' + String(m.default)); } catch (e) { console.log(n + ': ' + e.name + ': ' + e.message); } } })();
"""
    r = js(code, *tier)
    assert out(r) == golden("module_import_export_forms_and_bindings")
    assert (r.returncode, r.stderr) == (0, b"")
