"""Second-wave gap tests for the engine's less-travelled library corners: the regex compiler and
matcher (v-flag class-set grammar errors, lazy-quantifier continuation pruning, duplicate named
groups, lookbehind with modifiers/backreferences), ShadowRealm marshalling in both directions
(wrapped-function name/length copying, callbacks re-entering the host realm, importValue), the
`-e` uncaught-error describer for non-Error throw values, Temporal option/limit edge cases and
the Intl services' rarely used options (tag canonicalisation, DurationFormat fractional styles,
PluralRules option validation, Segmenter grapheme rules, NumberFormat significant-digit corners)."""

import pytest

from conftest import assert_result, check_script, resources_for, write_files

G = resources_for(__file__)

PRELUDE = r'''
const J = (x) => JSON.stringify(x);
const show = (label, f) => {
  let out;
  try {
    const v = f();
    out = (typeof v === 'object' && v !== null && !Array.isArray(v)) ? String(v) : J(v);
  } catch (e) {
    out = 'threw ' + e.name + ': ' + e.message;
  }
  console.log(label + ' => ' + out);
};
'''


def check_js(run, workdir, name, body, **kw):
    """Run PRELUDE + body as a script and compare stdout with the golden `name`."""
    return check_script(run, workdir, G, name, PRELUDE + body, **kw)


# ----- regex compiler / matcher -------------------------------------------------------------------

def test_regex_class_set_and_group_name_errors(run, workdir):
    """CATCHES: a v-flag class-set parser that accepts mixing `--` with a union or a range, reversed
    ranges, doubled reserved punctuators (`&&` at the start, `!!`), malformed `\\p` escapes (no brace,
    bad character, unterminated, unknown property), or that rejects legal forms ([], [^], [\\P{..}]);
    also duplicate group names in nested groups, astral/escaped group names and lone surrogates in
    names, and the exact SyntaxError messages for each."""
    check_js(run, workdir, "regex_class_set_and_group_name_errors", r'''
const tryRe = (src, flags) => { try { return 'ok ' + new RegExp(src, flags); } catch (e) { return e.name + ': ' + e.message; } };
for (const [s, f] of [
  ['[ab--c]', 'v'], ['[a-z--[aeiou]]', 'v'], ['[[a-z]--[aeiou]]', 'v'], ['[z-a]', 'v'], ['[a&&', 'v'], ['[&&a]', 'v'],
  ['[a!!b]', 'v'], ['[a##]', 'v'], ['[\\p]', 'v'], ['[\\p{L!}]', 'v'], ['[\\p{L', 'v'], ['[\\P{Lu}]', 'v'],
  ['[^\\P{Lu}]', 'v'], ['[\\p{Nope}]', 'v'], ['[\\P{Nope}]', 'v'], ['[]', 'v'], ['[^]', 'v'], ['[a', 'u'],
  ['[\\', ''], ['(?<a>(?<a>x)|y)', ''], ['(?<a>x)(?<a>y)', ''], ['(?:(?<a>x)|(?<a>y))\\k<a>', ''],
  ['(?<\\uD835\\uDC9C>.)', ''], ['(?<\\u{1D49C}>.)', 'u'], ['(?<\\uD835x>.)', ''], ['(?<\\uD835\\u0041>.)', ''],
  ['(?<a\uD800>.)', ''], ['(?<a\uD800>.)', 'u'], ['[a-', ''], ['[a-', 'u'],
]) console.log(J(s), f || '-', '->', tryRe(s, f).replace(/\uFFFD/g, '<U+FFFD>'));
''')


def test_regex_matching_rare_constructs(run, workdir):
    """CATCHES: wrong results for negated property classes inside v-mode classes, empty v-mode
    classes, duplicate named groups re-used by a backreference, astral group names, a lone lead
    surrogate escape in u-mode, \\v/\\f escapes in and out of classes, inline modifiers and lazy or
    bounded quantifiers inside lookbehind (matched right-to-left), backreferences inside a
    case-insensitive lookbehind, and \\D under the i flag."""
    check_js(run, workdir, "regex_matching_rare_constructs", r'''
const ex = (label, re, s) => { const m = re.exec(s); console.log(label, m ? J([...m]) + '@' + m.index + (m.groups ? ' ' + J(m.groups) : '') : 'null'); };
ex('P in v class', /[\P{Lu}]+/v, 'ABcdE');
ex('neg P in v class', /[^\P{Lu}]+/v, 'abCDe');
ex('empty v class', /a[]b|c/v, 'abc');
ex('neg empty v class', /a[^]b/v, 'a\nb');
ex('dup names backref', /(?:(?<n>a)|(?<n>b))x*?\k<n>/, 'bxxb axxa');
ex('dup names backref second', /(?:(?<n>a)|(?<n>b))x*?\k<n>/, 'bxxa axxa');
ex('dup names no match', /(?:(?<n>a)|(?<n>b))x*?\k<n>/, 'bxxa');
ex('astral group name', /(?<𝒜>.)/, 'q');
ex('astral group name u', /(?<\u{1D49C}>.)./u, 'qr');
ex('escaped pair group name', new RegExp('(?<\\uD835\\uDC9C>z)'), 'xyz');
ex('lone lead u', /\uD83DA/u, 'x\uD83DA');
ex('vt ff', /[\v\f]\v\f/, 'a\v\v\f');
ex('lookbehind modifier', /(?<=(?i:a))b/, 'Ab');
ex('lookbehind modifier no', /(?<=(?i:a))B/, 'Ab');
ex('lookbehind lazy', /(?<=(x*?))y/, 'xxy');
ex('lookbehind lazy bounded', /(?<=(x{1,3}?))y/, 'xxxxy');
ex('lookbehind greedy bounded', /(?<=(x{1,3}))y/, 'xxxxy');
ex('lookbehind backref ic', /(?<=\1(a))b/i, 'aab');
ex('lookbehind backref ic2', /(?<=\1(a))b/i, 'Aab');
ex('lookbehind backref no', /(?<=\1(a))b/i, 'xab');
ex('D class ic', /\D+/i, '12ab34');
ex('D class in class ic', /[\D]+/i, '12aB34');
ex('repeat containing lookbehind group', /(?:(?<=(a))b)+/, 'abab');
ex('backref inside lookahead', /(a)(?=\1)/, 'xaab');
ex('lookahead group then backref', /(?=(a))\1b/, 'ab');
ex('class astral u', /[😀]/u, 'x\u{1F600}');
ex('class lead then non-trail u', /[\uD83DA]+/u, 'AA\uD83D');
ex('class lead then braced escape u', /[\uD83D\u{41}]+/u, 'AA');
ex('lead then braced escape u', /\uD83D\u{41}/u, '\uD83DA');
ex('octal escape two digits', /\012/, 'a\nb');
ex('null escape then digit', /\08/, '\x008');
ex('dup names mismatch', /(?:(?<n>a)|(?<n>b))\k<n>/, 'abba');
ex('dup names mismatch ic', /(?:(?<n>a)|(?<n>b))\k<n>/i, 'aBBa');
ex('dup names in lookbehind', /(?<=(?:(?<n>a)|(?<n>b))\k<n>)c/, 'abbc');
ex('ic lone surrogate', /\uD800/i, 'x\uD800');
ex('ic lone surrogate class u', /[\uD800-\uDBFF]/iu, 'x\uD800');
ex('ic lone surrogate backref', /(\uD800)\1/i, '\uD800\uD800');
ex('sticky past end', Object.assign(/a/y, {lastIndex: 10}), 'aaa');
ex('global at end', Object.assign(/a?/g, {lastIndex: 3}), 'aaa');
''')


def test_regex_lazy_quantifier_continuations(run, workdir):
    """CATCHES: a lazy single-character repetition whose look-ahead pruning of retry positions is
    wrong when the continuation starts with a backreference (set, unset, duplicate-named), a
    multiline `^`, an empty alternative, a deep nest of capture groups (more than the pruning
    budget), or a capture group numbered above 128: each must still find the leftmost-shortest
    match exactly like plain backtracking."""
    check_js(run, workdir, "regex_lazy_quantifier_continuations", r'''
const ex = (label, re, s) => { const m = re.exec(s); console.log(label, m ? J([...m].slice(0, 4)) + ' len=' + m.length + ' @' + m.index : 'null'); };
ex('unset backref', /(a)?x*?\1y/, 'xxy');
ex('set backref', /(a)x*?\1/, 'axxxa');
ex('backref mismatch first', /(a)x*?\1b/, 'axxab');
ex('multiline start', /x*?^a/m, 'xx\na');
ex('multiline start newlines', /\n*?^a/m, '\n\na');
ex('not multiline', /x*?^a/, 'xx\na');
ex('empty alternative', /x*?(?:|a)b/, 'xxab');
ex('alternative', /x*?(?:a|b)c/, 'xxbc');
ex('deep groups', /x*?((((((((((((((((((a))))))))))))))))))/, 'xxa');
const many = new RegExp('()'.repeat(128) + 'x*?(a)');
const m = many.exec('xxa'); console.log('group 129', m.length, J(m[0]), J(m[129]), J(m[128]));
const many2 = new RegExp('x*?' + '(?:' + '(b)'.repeat(130) + ')?c');
const m2 = many2.exec('xxxc'); console.log('cleared 130', m2.length, J(m2[0]), m2[130]);
ex('lazy dot then class', /a.*?[0-9]/, 'abc123');
ex('lazy class then end', /[a-z]*?$/, 'abc');
ex('lazy u surrogates', /.*?\u{1F600}/u, 'a\u{1F600}b');
ex('lazy group star', /(?:ab)*?c/, 'ababc');
ex('lazy group star then optional', /^(?:ab)*?(ab)?$/, 'ababab');
ex('tainted empty group backref', /x*?()\1a/, 'xxa');
ex('dup names tainted', /x*?(?:(?<n>)|(?<n>b))\k<n>c/, 'xxc');
ex('dup names unset', /(?:(?<n>a)|(?<n>b))?x*?\k<n>y/, 'xxy');
ex('lazy bounded group', /(?:ab){1,3}?c/, 'abababc');
ex('lazy bounded group then rest', /^(?:ab){0,2}?((?:ab)*)$/, 'ababab');
ex('lazy bounded capture', /(ab){2,3}?/, 'abababab');
console.log('u-mode backref checks', (() => { try { return String(new RegExp('(a)(?=\\2)', 'u')); } catch (e) { return e.name + ': ' + e.message; } })(), (() => { try { return String(new RegExp('(?<=\\1(a))', 'u')); } catch (e) { return e.name + ': ' + e.message; } })(), J(/(a)(?=\1)/u.exec('aa')));
console.log('replace', 'aXbXXc'.replace(/X*?c/g, '_'), 'aaa'.replace(/a*?/g, '-'));
''')


def test_regexp_protocol_corners(run, workdir):
    """CATCHES: RegExp@@split not stopping when the limit is reached while pushing captures,
    `$<` substitutions without a closing `>` (kept literally) or naming a missing group (empty),
    @@search not restoring a lastIndex changed by a custom exec (and throwing when it cannot),
    RegExp(re) returning the same object only when called without new/flags and re.constructor is
    RegExp, RegExp.prototype's own getter defaults ("(?:)", "", undefined), empty-source rendering,
    and the generic flags getter over a plain object plus brand-check messages."""
    check_js(run, workdir, "regexp_protocol_corners", r"""
const t = (f) => { try { return J(f()); } catch (e) { return e.name + ': ' + e.message; } };
console.log('split limit in captures', t(() => 'a1b2c3'.split(/(\d)/, 2)), t(() => 'a1b2c3'.split(/(\d)(x)?/, 3)), t(() => 'a1b2c3'.split(/(\d)/, 0)), t(() => 'abc'.split(/(?:)/, 2)));
console.log('named $< substitutions', t(() => 'abc'.replace(/(?<x>b)/, '[$<x]')), t(() => 'abc'.replace(/(?<x>b)/, '[$<x>]')), t(() => 'abc'.replace(/(?<x>b)/, '[$<y>]')), t(() => 'abc'.replace(/(b)/, '[$<x>]')), t(() => 'abc'.replace(/(?<x>b)/g, '$<')));
console.log('search restores lastIndex', t(() => { const re = /a/; re.exec = function (s) { this.lastIndex = 5; return null; }; const r = 'abc'.search(re); return [r, re.lastIndex]; }), t(() => { const re = /b/g; re.lastIndex = 2; const r = 'abc'.search(re); return [r, re.lastIndex]; }));
console.log('search frozen lastIndex', t(() => { const re = /a/; re.exec = function () { return null; }; re.lastIndex = 3; Object.freeze(re); return 'abc'.search(re); }));
console.log('RegExp call identity', t(() => { const re = /a/g; return [RegExp(re) === re, RegExp(re, 'g') === re, new RegExp(re) === re]; }), t(() => { const re = /a/; re.constructor = 5; return RegExp(re) === re; }), t(() => { const o = {[Symbol.match]: true, constructor: RegExp, source: 'q', flags: 'i'}; return [RegExp(o) === o, String(new RegExp(o))]; }));
console.log('prototype getters', t(() => [RegExp.prototype.source, RegExp.prototype.flags, String(RegExp.prototype.global), String(RegExp.prototype.hasIndices), String(RegExp.prototype)]));
console.log('empty source', t(() => [new RegExp('').source, String(new RegExp('')), new RegExp('', 'g').source, RegExp('(?:)').source, /(?:)/.source]));
console.log('generic getters', t(() => Object.getOwnPropertyDescriptor(RegExp.prototype, 'flags').get.call({global: true, sticky: 1, unicodeSets: 'x'})), t(() => Object.getOwnPropertyDescriptor(RegExp.prototype, 'global').get.call({})), t(() => Object.getOwnPropertyDescriptor(RegExp.prototype, 'source').get.call({})));
""")


@pytest.mark.parametrize("cli", [pytest.param([], id="default"), pytest.param(["--tier=bytecode"], id="bytecode"),
                                 pytest.param(["--tier=interp"], id="interp")])
def test_regexp_dead_split_updates_legacy_statics(run, workdir, cli):
    """CATCHES: an optimised String#split whose result is unused (a hot statement `s.split(re);`)
    skipping the observable side effects: the legacy RegExp statics (lastMatch, left/rightContext,
    $1) must reflect the last successful match exactly as the full algorithm would (no attempt at
    the final position, empty matches advancing by code point only in u-mode, sticky/global
    separators, empty input), identically on every execution tier."""
    check_script(run, workdir, G, "regexp_dead_split_updates_legacy_statics", r"""
function deadSplit(s, re) { s.split(re); return JSON.stringify([RegExp.lastMatch, RegExp.leftContext, RegExp.rightContext, RegExp['$1']]); }
const seen = new Set();
const pats = [/x*/, /$/, /b/, /(a)|(b)/, /(?:)/, /\s*/u, /c/y, /a/g, /(?<n>[ab])+/];
const inputs = ['abc', '', 'xaxbx', 'aaa', 'a b  c', '\u{1F600}a\u{1F600}'];
for (let k = 0; k < 200; k++) for (const p of pats) for (const s of inputs) seen.add(`${p} ${JSON.stringify(s)} -> ${deadSplit(s, p)}`);
console.log([...seen].join('\n'));
""", cli=cli)


# ----- ShadowRealm ---------------------------------------------------------------------------------

def test_shadow_realm_wrapped_name_length_and_callbacks(run, workdir):
    """CATCHES: ShadowRealm wrappers that copy name/length wrongly (Infinity kept, negative/-Infinity
    and non-number lengths clamped to 0, fractions truncated, non-string names become ""), that let a
    throwing length/name getter escape instead of a TypeError, and callbacks from the realm into the
    host that accept object arguments, return objects, leak host exceptions or mis-wrap callables in
    either direction (including nested realms). NOTE: a host callable returned to the realm is wrapped
    with name "" and length 0 by the reference (the spec copies them) — pinned as-is."""
    check_js(run, workdir, "shadow_realm_wrapped_name_length_and_callbacks", r'''
const r = new ShadowRealm();
show('empty sources', () => [r.evaluate(''), r.evaluate('var a1 = 1;'), r.evaluate('function decl() {}'), r.evaluate('if (true) {}')]);
show('length Infinity', () => { const f = r.evaluate('function f(a){}; Object.defineProperty(f, "length", {value: Infinity}); f'); return [f.length === Infinity, f.name]; });
show('length -Infinity', () => r.evaluate('var g0 = function(a){}; Object.defineProperty(g0, "length", {value: -Infinity}); g0').length);
show('length negative', () => r.evaluate('var g1 = function(a,b){}; Object.defineProperty(g1, "length", {value: -5}); g1').length);
show('length fraction', () => r.evaluate('var g2 = function(a,b){}; Object.defineProperty(g2, "length", {value: 2.9}); g2').length);
show('length string', () => r.evaluate('var g3 = function(a,b){}; Object.defineProperty(g3, "length", {value: "7"}); g3').length);
show('length deleted', () => { const f = r.evaluate('var g4 = function(a,b){}; delete g4.length; g4'); return [f.length, Object.getOwnPropertyNames(f).sort()]; });
show('name non-string', () => r.evaluate('var g5 = function(){}; Object.defineProperty(g5, "name", {value: 42}); g5').name);
show('name deleted', () => r.evaluate('var g6 = function(){}; delete g6.name; g6').name);
show('length getter throws', () => r.evaluate('var g7 = function(){}; Object.defineProperty(g7, "length", {get() { throw new Error("no"); }}); g7'));
show('name getter throws', () => r.evaluate('var g8 = function(){}; Object.defineProperty(g8, "name", {get() { throw new Error("no"); }}); g8'));
show('bound function', () => { const f = r.evaluate('(function foo(a, b, c) {}).bind(null, 1)'); return [f.name, f.length]; });
const probe = 'e => [e instanceof TypeError, e.message].join("|")';
show('callback given object', () => r.evaluate(`(cb) => { try { cb({}); return "no"; } catch (e) { return (${probe})(e); } }`)(() => 1));
show('callback given array', () => r.evaluate(`(cb) => { try { cb([1]); return "no"; } catch (e) { return (${probe})(e); } }`)(() => 1));
show('callback returns object', () => r.evaluate(`(cb) => { try { cb(); return "no"; } catch (e) { return (${probe})(e); } }`)(() => ({})));
show('callback throws', () => r.evaluate(`(cb) => { try { cb(); return "no"; } catch (e) { return (${probe})(e); } }`)(() => { throw new RangeError('outer'); }));
show('callback returns function', () => r.evaluate('(cb) => { const g = cb(); return [typeof g, g(4), g.name, g.length].join(":"); }')(() => function named(x, y) { return x * 100; }));
show('callback given function', () => r.evaluate('(cb) => cb((n) => n + 0.5)')((inner) => inner(2) * 2));
show('callback given fn returning object', () => r.evaluate('(cb) => cb(() => ({}))')((inner) => { try { inner(); return 'no'; } catch (e) { return [e.constructor === TypeError, e.message].join('|'); } }));
show('callback symbol argument', () => r.evaluate('(cb) => typeof cb(Symbol("s"))')((s) => s.description));
show('nested realm', () => r.evaluate('const inner = new ShadowRealm(); inner.evaluate("1 + 1") + inner.evaluate("typeof ShadowRealm").length'));
show('nested realm function', () => r.evaluate('const inner2 = new ShadowRealm(); inner2.evaluate("(x) => x * 3")')(7));
show('object argument', () => r.evaluate('(a) => a')({}));
show('round trip identity', () => { const f = r.evaluate('(cb) => cb'); const g = () => 'back'; const h = f(g); return [h === g, h(), typeof h]; });
show('strict this', () => r.evaluate('(function () { "use strict"; return typeof this; })').call({a: 1}));
show('construct wrapper', () => new (r.evaluate('() => 1'))());
show('callback argument with throwing length', () => r.evaluate(`(cb) => { const f = () => 1; Object.defineProperty(f, "length", {get() { throw 1; }}); try { cb(f); return "no"; } catch (e) { return (${probe})(e); } }`)(() => 0));
show('proxy getOwnPropertyDescriptor throws', () => r.evaluate('new Proxy(function(){}, {getOwnPropertyDescriptor() { throw new Error("trap"); }})'));
show('proxy hides length', () => { const f = r.evaluate('new Proxy(function named(a){}, {getOwnPropertyDescriptor(t, k) { return k === "length" ? undefined : Reflect.getOwnPropertyDescriptor(t, k); }})'); return [f.length, f.name]; });
show('proxy get trap', () => { const f = r.evaluate('new Proxy(function named(a){}, {get(t, k) { return k === "length" ? 42 : k === "name" ? "proxied" : t[k]; }})'); return [f.length, f.name, String(f(1))]; });
show('revoked proxy', () => r.evaluate('const pr = Proxy.revocable(function(){}, {}); pr.revoke(); pr.proxy'));
// Re-entrancy: while the host copies name/length of a realm function, the realm is checked out, so
// callbacks that reach back into it see it as unavailable (pinned reference behaviour).
const earlier = r.evaluate('(x) => x + 1');
const log = [];
const setup = r.evaluate(`(hostCb) => { const f = function inner(a, b) {}; Object.defineProperty(f, 'length', { get() { globalThis.cbResult = hostCb(() => 1); return 7; } }); return f; }`);
show('reentrant wrap', () => { const w = setup((g) => { log.push(typeof g, g.name, g.length); try { log.push(g()); } catch (e) { log.push(e.message); } return 'cb-done'; }); return [w.length, w.name, log, r.evaluate('globalThis.cbResult')]; });
const log2 = [];
const setup2 = r.evaluate(`(hostCb) => { const f = function inner2() {}; Object.defineProperty(f, 'name', { get() { globalThis.cb2 = hostCb(); return 'renamed'; } }); return f; }`);
show('realm checked out', () => { const w = setup2(() => { try { return earlier(1); } catch (e) { log2.push(e.constructor === TypeError, e.message); return 'caught'; } }); return [w.name, log2, r.evaluate('String(globalThis.cb2)'), earlier(1)]; });
''')


def test_shadow_realm_import_value(run, workdir):
    """CATCHES: ShadowRealm.prototype.importValue that does not load the module inside the realm
    (side effects must land on the realm's global, not the host's), returns objects instead of
    rejecting, resolves missing/undefined exports instead of rejecting with a TypeError, does not
    follow the module's own imports or top-level await, re-evaluates a cached module, or rejects
    with the wrong messages for missing files, throwing modules and non-ESM specifiers."""
    write_files(workdir, {
        "mod.mjs": "export const x = 42;\nexport function dbl(n) { return n * 2; }\nexport const obj = {a: 1};\n"
                   "export let undef;\nglobalThis.sideEffect = 'set in realm';\n",
        "bad.mjs": "throw new Error('module boom');\n",
        "counter.mjs": "globalThis.loads = (globalThis.loads || 0) + 1; export const n = globalThis.loads;\n",
        "tla.mjs": "export const v = await Promise.resolve('tla value');\n",
        "imp.mjs": "import { x } from './mod.mjs'; export const y = x + 1;\n",
        "c.cjs": "module.exports = 5;\n",
    })
    check_script(run, workdir, G, "shadow_realm_import_value", r'''
const r = new ShadowRealm();
const show = async (label, f) => {
  try { const v = await f(); console.log(label, typeof v, JSON.stringify(v)); }
  catch (e) { console.log(label, 'rejected', e.constructor.name, e.message); }
};
(async () => {
  await show('number export', () => r.importValue('./mod.mjs', 'x'));
  await show('function export', async () => { const f = await r.importValue('./mod.mjs', 'dbl'); return [f(21), f.name, f.length]; });
  await show('object export', () => r.importValue('./mod.mjs', 'obj'));
  await show('undefined export', () => r.importValue('./mod.mjs', 'undef'));
  await show('missing export', () => r.importValue('./mod.mjs', 'nope'));
  await show('throwing module', () => r.importValue('./bad.mjs', 'x'));
  await show('side effect in realm', async () => [r.evaluate('globalThis.sideEffect'), typeof globalThis.sideEffect]);
  await show('missing file', () => r.importValue('./nf.mjs', 'x'));
  await show('builtin module', () => r.importValue('node:path', 'sep'));
  await show('cjs file', () => r.importValue('./c.cjs', 'default'));
  await show('evaluated once', async () => { await r.importValue('./counter.mjs', 'n'); return [await r.importValue('./counter.mjs', 'n'), r.evaluate('globalThis.loads')]; });
  await show('returns promise', () => { const p = r.importValue('./mod.mjs', 'x'); return [p instanceof Promise, Object.getPrototypeOf(p) === Promise.prototype]; });
  await show('top-level await', () => r.importValue('./tla.mjs', 'v'));
  await show('nested import', () => r.importValue('./imp.mjs', 'y'));
  await show('separate realm reloads', async () => { const r2 = new ShadowRealm(); return [await r2.importValue('./counter.mjs', 'n'), r2.evaluate('globalThis.loads')]; });
})();
''', filename="main.cjs")


# ----- uncaught-error description in -e mode ------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("throw Object.create(null)", "Uncaught \n"),
    ("throw {constructor: {}}", "Uncaught \n"),
    ("throw {name: undefined, constructor: 5, message: 'ignored?'}", "Uncaught ignored?\n"),
    ("throw {constructor: {name: 'Custom'}, message: 'm1'}", "Uncaught Custom: m1\n"),
    ("throw {get name() { throw 1; }, message: 'm2'}", "Uncaught Object: m2\n"),
    ("throw {name: 'N', get message() { throw 2; }}", "Uncaught N: \n"),
    ("throw {name: '', message: 'empty name'}", "Uncaught empty name\n"),
    ("throw function namedFn() {}", "Uncaught namedFn: \n"),
    ("throw Symbol('s')", "Uncaught Symbol: \n"),
    ("throw {name: {toString() { return 'ObjName'; }}, message: 7}", "Uncaught ObjName: 7\n"),
])
def test_uncaught_non_error_values_in_eval_mode(run, workdir, code, expected):
    """CATCHES: the -e uncaught-exception reporter mis-describing non-Error throw values: a missing
    `name` must fall back to constructor.name (empty when the constructor is absent, not an object,
    or nameless), a throwing name/message getter must be swallowed (empty part), an empty name
    drops the `Name: ` prefix, and name/message are rendered with ToString; always exit 1."""
    r = run(["-e", "console.log('before'); " + code])
    assert r.stdout == b"before\n"
    assert r.stderr.decode() == expected
    assert r.returncode == 1


def test_shadow_realm_import_value_from_esm_entry(run, workdir):
    """CATCHES: importValue behaving differently from the reference when the entry point is an ES
    module: the reference resolves the specifier without the module's directory and rejects every
    relative/absolute specifier with "module not found" (pinned quirk), while argument validation
    (non-string export name, bad receiver) still throws synchronously."""
    write_files(workdir, {"dep.mjs": "export const x = 1;\n"})
    check_script(run, workdir, G, "shadow_realm_import_value_esm", r'''
const r = new ShadowRealm();
const out = async (label, p) => { try { console.log(label, await p); } catch (e) { console.log(label, e.constructor.name, e.message.replace(process.cwd(), '<cwd>')); } };
await out('relative', r.importValue('./dep.mjs', 'x'));
await out('file url', r.importValue(new URL('./dep.mjs', import.meta.url).href, 'x'));
try { r.importValue('./dep.mjs', Symbol('x')); } catch (e) { console.log('sync', e.constructor.name, e.message); }
try { ShadowRealm.prototype.importValue.call(r.evaluate('() => 1'), './dep.mjs', 'x'); } catch (e) { console.log('sync', e.constructor.name, e.message); }
''', filename="entry.mjs")


# ----- Temporal ----------------------------------------------------------------------------------

def test_temporal_calendar_unit_rounding_ties(run, workdir):
    """CATCHES: calendar-unit rounding (month/year smallestUnit with relativeTo or until/since) that
    mishandles exact ties: halfTrunc/halfFloor must round a tie down, halfCeil/halfExpand up, and
    halfEven to the even neighbour (both an odd and an even lower candidate are exercised), for
    Duration.round, Duration.total, PlainDate/PlainDateTime/PlainYearMonth/ZonedDateTime until/since."""
    check_js(run, workdir, "temporal_calendar_unit_rounding_ties", r'''
const T = Temporal;
for (const mode of ['halfTrunc', 'halfEven', 'halfCeil', 'halfFloor', 'halfExpand', 'trunc', 'expand'])
  show(mode, () => [
    T.Duration.from({months: 1, days: 15}).round({smallestUnit: 'month', roundingMode: mode, relativeTo: '2021-03-01'}).toString(),
    T.Duration.from({months: 2, days: 15}).round({smallestUnit: 'month', roundingMode: mode, relativeTo: '2021-02-01'}).toString(),
    T.Duration.from({months: -1, days: -15}).round({smallestUnit: 'month', roundingMode: mode, relativeTo: '2021-05-16'}).toString(),
    T.Duration.from({years: -2, months: -6}).round({smallestUnit: 'year', roundingMode: mode, relativeTo: '2021-01-01'}).toString(),
    T.PlainDate.from('2021-03-01').until('2021-04-16', {smallestUnit: 'month', roundingMode: mode}).toString(),
    T.PlainDateTime.from('2020-01-01T00:00').until('2020-07-02T00:00', {smallestUnit: 'year', roundingMode: mode}).toString(),
    T.PlainYearMonth.from('2020-01').since('2021-07', {smallestUnit: 'year', roundingMode: mode}).toString(),
  ].join(' '));
show('total tie', () => T.Duration.from({months: 1, days: 15}).total({unit: 'month', relativeTo: '2021-03-01'}));
show('zoned relativeTo tie', () => T.Duration.from({months: 1, days: 15}).round({smallestUnit: 'month', roundingMode: 'halfEven', relativeTo: T.ZonedDateTime.from('2021-03-01T00:00[America/New_York]')}).toString());
show('zoned until halfTrunc', () => T.ZonedDateTime.from('2021-03-01T00:00[Europe/London]').until(T.ZonedDateTime.from('2021-04-16T00:00[Europe/London]'), {smallestUnit: 'month', roundingMode: 'halfTrunc'}).toString());
show('week increment', () => T.Duration.from({days: 10}).round({smallestUnit: 'week', roundingIncrement: 3, relativeTo: '2020-01-01'}).toString());
show('day increment', () => T.Duration.from({days: 10}).round({smallestUnit: 'day', roundingIncrement: 7, relativeTo: '2020-01-01'}).toString());
show('month increment', () => T.Duration.from({months: 13}).round({smallestUnit: 'month', roundingIncrement: 5, relativeTo: '2020-01-01'}).toString());
show('increment zero', () => T.PlainTime.from('10:00').round({smallestUnit: 'minute', roundingIncrement: 0}));
show('increment negative', () => T.Instant.fromEpochMilliseconds(0).round({smallestUnit: 'second', roundingIncrement: -1}));
show('calendar increment zero', () => T.Duration.from({hours: 5}).round({smallestUnit: 'day', roundingIncrement: 0, relativeTo: '2020-01-01'}));
''')


def test_temporal_limits_and_argument_validation(run, workdir):
    """CATCHES: Temporal values crossing the representable limits (-271821-04-19 dates/times), bad
    withCalendar arguments (missing, plain object, number vs. a Temporal object's calendar),
    month-day string forms (`--MM-DD`, `--MMDD` valid; `-MM-DD` invalid), month 0 in ISO and
    lunisolar bags, out-of-range strings for non-ISO year-month/month-day, unknown/leap month codes
    per calendar, malformed UTC-offset strings in ZonedDateTime bags, equal-date differences in a
    lunisolar calendar, and ZonedDateTime.prototype.toLocaleString on bad receivers."""
    check_js(run, workdir, "temporal_limits_and_argument_validation", r'''
const T = Temporal;
show('withCalendar missing', () => T.PlainDateTime.from('2020-01-01T00:00').withCalendar());
show('withCalendar object', () => T.PlainDateTime.from('2020-01-01T00:00').withCalendar({}));
show('withCalendar number', () => T.PlainDateTime.from('2020-01-01T00:00').withCalendar(1));
show('withCalendar zoned', () => T.PlainDateTime.from('2020-01-01T00:00').withCalendar(T.ZonedDateTime.from('2020-01-01T00:00[UTC][u-ca=coptic]')));
show('withCalendar date', () => T.PlainDateTime.from('2020-01-01T00:00').withCalendar(T.PlainDate.from('2020-01-01[u-ca=hebrew]')));
show('limit with', () => T.PlainDateTime.from('-271821-04-20T00:00').with({day: 19}));
show('limit with ns', () => T.PlainDateTime.from('-271821-04-20T00:00').with({day: 19, nanosecond: 1}));
show('limit toPlainDateTime', () => T.PlainDate.from('-271821-04-19').toPlainDateTime('00:00'));
show('limit date string', () => T.PlainDate.from('-271821-04-18'));
show('limit date string ok', () => T.PlainDate.from('-271821-04-19'));
show('limit hebrew year-month', () => T.PlainYearMonth.from('-271821-04-18[u-ca=hebrew]'));
show('limit hebrew month-day', () => T.PlainMonthDay.from('-271821-04-18[u-ca=hebrew]'));
show('limit iso month-day', () => T.PlainMonthDay.from('-271821-04-18'));
for (const s of ['--12-25', '--1225', '1225', '-12-25', '--x2-25', '--13-01', '--02-30'])
  show('month-day ' + s, () => T.PlainMonthDay.from(s));
show('iso month 0', () => T.PlainDate.from({year: 2020, month: 0, day: 1}));
show('hebrew month 0', () => T.PlainDate.from({calendar: 'hebrew', year: 5780, month: 0, day: 1}));
show('chinese month 0', () => T.PlainDate.from({calendar: 'chinese', year: 2020, month: 0, day: 1}));
show('year-month month 0', () => T.PlainYearMonth.from({year: 2020, month: 0}));
show('hebrew equal until', () => T.PlainDate.from('2020-01-01[u-ca=hebrew]').until('2020-01-01[u-ca=hebrew]', {largestUnit: 'year'}));
show('hebrew equal since', () => T.PlainDate.from('2020-03-01[u-ca=hebrew]').since(T.PlainDate.from('2020-03-01[u-ca=hebrew]'), {largestUnit: 'month'}));
for (const [cal, code, day] of [['persian', 'M05L', 1], ['islamic-civil', 'M05L', 1], ['indian', 'M03L', 1], ['coptic', 'M14', 1], ['gregory', 'M02L', 1],
    ['ethiopic', 'M13', 1], ['coptic', 'M13', 7], ['hebrew', 'M05L', 30], ['hebrew', 'M06L', 1], ['chinese', 'M12L', 1], ['dangi', 'M04L', 31]])
  show(`month-day ${cal} ${code} ${day}`, () => [
    (() => { try { return T.PlainMonthDay.from({calendar: cal, monthCode: code, day}, {overflow: 'reject'}).toString(); } catch (e) { return e.name + ': ' + e.message; } })(),
    (() => { try { return T.PlainMonthDay.from({calendar: cal, monthCode: code, day}).toString(); } catch (e) { return e.name + ': ' + e.message; } })()].join(' / '));
for (const off of ['+00:00:00x', '+00:00x', '+0000x', '+00:00:00.', '+00:00:00.1234567891', '+00:00:00,5', '+00:00:60', '+0000:00', '+00:0000'])
  show('offset ' + off, () => T.ZonedDateTime.from({year: 2020, month: 1, day: 1, timeZone: 'UTC', offset: off}, {offset: 'use'}).toString());
show('zoned toLocaleString primitive', () => T.ZonedDateTime.prototype.toLocaleString.call(1));
show('zoned toLocaleString object', () => T.ZonedDateTime.prototype.toLocaleString.call({}));
show('time until day', () => T.PlainTime.from('10:00').until('12:30', {largestUnit: 'day'}));
show('instant until week', () => T.Instant.fromEpochMilliseconds(0).until(T.Instant.fromEpochMilliseconds(90000000), {largestUnit: 'week'}));
show('withPlainTime limit', () => [T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').withPlainTime(), T.PlainDateTime.from('-271821-04-19T00:00:00.000000001').withPlainTime('00:00')]);
for (const cal of ['gregory', 'japanese', 'coptic', 'persian', 'indian', 'ethiopic', 'islamic-civil'])
  show('month 0 ' + cal, () => T.PlainDate.from({calendar: cal, year: 2020, month: 0, day: 1}));
show('hebrew time-only differences', () => [T.Duration.from({hours: 1}).round({largestUnit: 'year', relativeTo: T.PlainDate.from('2020-01-01[u-ca=hebrew]')}).toString(),
  T.Duration.from({hours: 25}).round({largestUnit: 'month', smallestUnit: 'day', relativeTo: T.PlainDate.from('2020-01-01[u-ca=hebrew]')}).toString(),
  T.PlainDateTime.from('2020-01-01T00:00[u-ca=hebrew]').until(T.PlainDateTime.from('2020-01-01T05:00[u-ca=hebrew]'), {largestUnit: 'year'}).toString(),
  T.ZonedDateTime.from('2020-01-01T00:00[UTC][u-ca=hebrew]').until(T.ZonedDateTime.from('2020-01-01T05:00[UTC][u-ca=hebrew]'), {largestUnit: 'year'}).toString()]);
''')


def test_temporal_zoned_sub_minute_offsets_and_option_errors(run, workdir):
    """CATCHES: ZonedDateTime parsing that does not accept a minute-rounded string offset for a
    zone whose real offset has seconds (LMT +00:17:30 -> "+00:18", -00:44:30 -> "-00:45", rounding
    half away from zero) while property bags must match exactly; `offset: "use"` with a named zone;
    invalid disambiguation/offset/calendarName/timeZoneName option messages across from/with/
    toString; invalid smallestUnit messages; and time-only durations totalled or rounded to
    calendar units (sign and zero handling), including very large nanosecond totals."""
    check_js(run, workdir, "temporal_zoned_sub_minute_offsets_and_option_errors", r"""
const T = Temporal;
show('lmt actual offset', () => T.ZonedDateTime.from('1830-01-01T00:00[Europe/Amsterdam]').offset);
show('lmt rounded string', () => T.ZonedDateTime.from('1830-01-01T00:00+00:18[Europe/Amsterdam]').toString());
show('lmt exact string', () => T.ZonedDateTime.from('1830-01-01T00:00+00:17:30[Europe/Amsterdam]').toString());
show('lmt truncated string', () => T.ZonedDateTime.from('1830-01-01T00:00+00:17[Europe/Amsterdam]').toString());
show('lmt rounded bag', () => T.ZonedDateTime.from({year: 1830, month: 1, day: 1, timeZone: 'Europe/Amsterdam', offset: '+00:18'}).toString());
show('lmt exact bag', () => T.ZonedDateTime.from({year: 1830, month: 1, day: 1, timeZone: 'Europe/Amsterdam', offset: '+00:17:30'}).toString());
show('lmt with prefer', () => T.ZonedDateTime.from('1830-01-01T00:00[Europe/Amsterdam]').with({hour: 5}, {offset: 'prefer'}).toString());
show('lmt offset never', () => T.ZonedDateTime.from('1830-01-01T00:00[Europe/Amsterdam]').toString({offset: 'never'}));
show('negative lmt', () => [T.ZonedDateTime.from('1960-01-01T00:00[Africa/Monrovia]').offset, T.ZonedDateTime.from('1960-01-01T00:00-00:45[Africa/Monrovia]').toString()]);
show('lmt compare/equals', () => [T.ZonedDateTime.compare('1830-01-01T00:00+00:18[Europe/Amsterdam]', '1830-01-01T00:00+00:17:30[Europe/Amsterdam]'), T.ZonedDateTime.from('1830-01-01T00:00[Europe/Amsterdam]').equals('1830-01-01T00:00+00:18[Europe/Amsterdam]')]);
show('lmt relativeTo', () => T.Duration.from({days: 1}).total({unit: 'hour', relativeTo: '1830-01-01T00:00+00:18[Europe/Amsterdam]'}));
show('lmt transition', () => T.ZonedDateTime.from('1830-01-01T00:00[Europe/Amsterdam]').getTimeZoneTransition('next').toString());
show('offset use named zone', () => T.ZonedDateTime.from({year: 2020, month: 1, day: 1, timeZone: 'America/New_York', offset: '+05:00'}, {offset: 'use'}).toString());
show('offset prefer named zone', () => T.ZonedDateTime.from({year: 2020, month: 1, day: 1, timeZone: 'America/New_York', offset: '+05:00'}, {offset: 'prefer'}).toString());
show('bad disambiguation bag', () => T.ZonedDateTime.from({year: 2020, month: 1, day: 1, timeZone: 'UTC'}, {disambiguation: 'bad'}));
show('bad disambiguation string', () => T.ZonedDateTime.from('2020-01-01T00:00[UTC]', {disambiguation: 'bad'}));
show('bad offset option bag', () => T.ZonedDateTime.from({year: 2020, month: 1, day: 1, timeZone: 'UTC'}, {offset: 'bad'}));
const z = T.ZonedDateTime.from('2020-01-01T00:00[UTC]');
show('toString calendarName', () => z.toString({calendarName: 'bad'}));
show('toString timeZoneName', () => z.toString({timeZoneName: 'bad'}));
show('toString offset', () => z.toString({offset: 'bad'}));
show('with offset', () => z.with({hour: 1}, {offset: 'bad'}));
show('with disambiguation', () => z.with({hour: 1}, {disambiguation: 'bad'}));
show('withPlainTime gap', () => T.ZonedDateTime.from('2020-03-08T00:00[America/New_York]').withPlainTime('02:30').toString());
show('until smallestUnit', () => z.until('2020-02-01T00:00[UTC]', {smallestUnit: 'bad'}));
show('date until smallestUnit', () => T.PlainDate.from('2020-01-01').until('2020-02-01', {smallestUnit: 'bad'}));
show('year-month until smallestUnit', () => [T.PlainYearMonth.from('2020-01').until('2020-02', {smallestUnit: 'bad'}), T.PlainYearMonth.from('2020-01').until('2020-02', {smallestUnit: 'day'})]);
show('round smallestUnit', () => z.round({smallestUnit: 'bad'}));
show('time-only total month', () => [T.Duration.from({hours: -1000}).total({unit: 'month', relativeTo: '2020-01-01'}), T.Duration.from({hours: 1000}).total({unit: 'month', relativeTo: '2020-01-01'})]);
show('time-only round month', () => [T.Duration.from({hours: 1000}).round({smallestUnit: 'month', relativeTo: '2020-01-01'}).toString(), T.Duration.from({hours: -1000}).round({smallestUnit: 'month', relativeTo: '2020-01-01'}).toString()]);
show('zero duration', () => [new T.Duration().total({unit: 'year', relativeTo: '2020-01-01'}), new T.Duration().round({smallestUnit: 'year', relativeTo: '2020-01-01'}).toString(), new T.Duration().total({unit: 'nanosecond'})]);
const zr = T.ZonedDateTime.from('2020-01-01T00:00[America/New_York]');
show('zoned time-only total', () => [T.Duration.from({hours: -1000}).total({unit: 'month', relativeTo: zr}), T.Duration.from({hours: 1000}).total({unit: 'month', relativeTo: zr}), new T.Duration().total({unit: 'month', relativeTo: zr})]);
show('zoned time-only round', () => [T.Duration.from({hours: -1000}).round({smallestUnit: 'month', relativeTo: zr}).toString(), new T.Duration().round({smallestUnit: 'month', relativeTo: zr}).toString(), T.Duration.from({minutes: -1}).round({smallestUnit: 'day', relativeTo: zr}).toString()]);
show('offset use string', () => T.ZonedDateTime.from('2020-01-01T00:00+05:00[America/New_York]', {offset: 'use'}).toString());
show('with offset modes', () => ['use', 'ignore', 'prefer', 'reject'].map(m => { try { return zr.with({hour: 5, offset: '+01:00'}, {offset: m}).toString(); } catch (e) { return e.name + ': ' + e.message; } }));
show('huge totals', () => [T.Duration.from({days: 100000000}).total({unit: 'nanosecond'}), T.Duration.from({years: 200000}).total({unit: 'nanosecond', relativeTo: '-100000-01-01'}), T.Duration.from({seconds: 9007199254740991}).total({unit: 'millisecond'})]);
""")


# ----- Intl ---------------------------------------------------------------------------------------

def test_intl_locale_tag_aliases_and_options(run, workdir):
    """CATCHES: language-tag canonicalisation that ignores compound aliases (cnr -> sr-ME adding a
    region only when absent, sh -> sr-Latn keeping an explicit script, sgn-DE consuming the region),
    grandfathered `lang-variant` aliases followed by more variants (art-lojban-fonipa), variant
    aliases (polytoni, heploc, hepburn+heploc), variant sorting, transform/unicode extension
    validation, extlang rejection, plus Intl.Locale receivers without the brand, object tags,
    variants/numeric/firstDayOfWeek options and maximize/minimize of unknown languages."""
    check_js(run, workdir, "intl_locale_tag_aliases_and_options", r'''
const t = (f) => { try { return J(f()); } catch (e) { return e.name + ': ' + e.message; } };
for (const tag of ['cnr', 'cnr-Latn', 'cnr-RS', 'sh', 'sh-Cyrl', 'sh-RS', 'swc', 'swc-TZ', 'prs-IR', 'sgn-DE', 'sgn-de-fonipa',
    'art-lojban-fonipa', 'zh-guoyu-fonipa', 'hy-arevela-fonipa', 'zh-hakka-Latn', 'en-polytoni', 'el-polytoni-fonipa', 'ja-Latn-heploc',
    'ja-Latn-hepburn-heploc', 'zh-yue', 'en-u-abcdefghi', 'en-u-c1-x', 'en-t-en-ab', 'en-t-1abc', 'en-t-k0-abc-zz', 'en-t-k0-ab', 'en-t-k0', 'en-t-k0-abc',
    'en-u-abc-ca-buddhist', 'de-1996-1901', 'sl-rozaj-biske-1994', 'x-private', 'en-a-bbb-x-a-ccc'])
  console.log(tag.padEnd(24), t(() => Intl.getCanonicalLocales(tag)), '|', t(() => new Intl.Locale(tag).baseName));
const P = Intl.Locale.prototype;
const g = (name) => Object.getOwnPropertyDescriptor(P, name).get;
console.log('unbranded getters', t(() => g('numeric').call({})), t(() => g('numeric').call(1)), t(() => g('caseFirst').call({})), t(() => g('firstDayOfWeek').call(Object.create(P))), t(() => g('baseName').call({})), t(() => P.toString.call({})), t(() => P.maximize.call({})));
console.log('object tags', t(() => new Intl.Locale({toString() { return 'de-AT'; }}).toString()), t(() => new Intl.Locale(new Intl.Locale('fr-CA'), {region: 'FR'}).toString()), t(() => new Intl.Locale(5)), t(() => new Intl.Locale(null)));
console.log('variants option', t(() => new Intl.Locale('de', {variants: '1996'}).toString()), t(() => new Intl.Locale('de', {variants: '1996-fonipa'}).toString()), t(() => new Intl.Locale('de', {variants: '199'})), t(() => new Intl.Locale('de', {variants: 'a996'})), t(() => new Intl.Locale('de', {variants: 'fonipa-fonipa'})), t(() => new Intl.Locale('de', {variants: ''})));
console.log('numeric option', t(() => new Intl.Locale('en', {numeric: false}).toString()), t(() => new Intl.Locale('en', {numeric: false}).numeric), t(() => new Intl.Locale('en-u-kn-false').numeric), t(() => new Intl.Locale('en', {numeric: 0}).toString()));
console.log('firstDayOfWeek option', t(() => new Intl.Locale('en', {firstDayOfWeek: 'true'}).toString()), t(() => new Intl.Locale('en', {firstDayOfWeek: 'true'}).firstDayOfWeek), t(() => new Intl.Locale('en', {firstDayOfWeek: 'abcdefgh'}).toString()), t(() => new Intl.Locale('en', {firstDayOfWeek: 0}).toString()), t(() => new Intl.Locale('en-u-fw-xyz').getWeekInfo()), t(() => new Intl.Locale('en', {firstDayOfWeek: 'true'}).getWeekInfo()));
console.log('likely subtags', t(() => new Intl.Locale('xyz').maximize().toString()), t(() => new Intl.Locale('xyz').minimize().toString()), t(() => new Intl.Locale('xyz-Abcd-QQ').minimize().toString()), t(() => new Intl.Locale('und-QQ').maximize().toString()), t(() => new Intl.Locale('und').minimize().toString()));
''')


def test_intl_number_format_rare_rounding_and_parts(run, workdir):
    """CATCHES: NumberFormat corner cases: useGrouping given the strings "true"/"false" (fall back to
    the default), zero with minimumSignificantDigits, values whose every digit is discarded by
    maximumFractionDigits under directed rounding modes (number and exact-decimal string inputs),
    roundingPriority with compact notation, unit/currency/accounting formatToParts with compact
    suffixes, BigInt/significant digits, and the reference's scientific/engineering carry output
    (a mantissa rounded up to 10 is printed as "10E0", not renormalised to "1E1" — pinned quirk)."""
    check_js(run, workdir, "intl_number_format_rare_rounding_and_parts", r'''
const t = (f) => { try { return f(); } catch (e) { return e.name + ': ' + e.message; } };
const nf = (o, v, l = 'en') => t(() => new Intl.NumberFormat(l, o).format(v));
const parts = (o, v, l = 'en') => t(() => new Intl.NumberFormat(l, o).formatToParts(v).map(p => p.type + ':' + p.value).join('|'));
console.log('useGrouping strings', J([new Intl.NumberFormat('en', {useGrouping: 'false'}).resolvedOptions().useGrouping, new Intl.NumberFormat('en', {useGrouping: 'true'}).resolvedOptions().useGrouping, nf({useGrouping: 'false'}, 12345), nf({useGrouping: 'true', notation: 'compact'}, 12345), nf({useGrouping: false}, 12345), nf({useGrouping: 'min2'}, 1234)]));
console.log('min significant zero', J([nf({minimumSignificantDigits: 3}, 0), nf({minimumSignificantDigits: 3}, -0), nf({minimumSignificantDigits: 1}, 0), nf({minimumSignificantDigits: 5, maximumSignificantDigits: 5}, 0), parts({minimumSignificantDigits: 3}, 0), nf({minimumSignificantDigits: 4}, 0n)]));
console.log('all digits discarded', J([nf({maximumFractionDigits: 2, roundingMode: 'ceil'}, 0.0004), nf({maximumFractionDigits: 2, roundingMode: 'expand'}, -0.0004), nf({maximumFractionDigits: 2, roundingMode: 'floor'}, -0.0004), nf({maximumFractionDigits: 2}, 0.0004), nf({maximumFractionDigits: 0, roundingMode: 'ceil'}, 0.0000001), nf({maximumFractionDigits: 0, roundingIncrement: 5, roundingMode: 'ceil'}, 0.1)]));
console.log('discarded decimal strings', J([nf({maximumFractionDigits: 2, roundingMode: 'ceil'}, '0.0004'), nf({maximumFractionDigits: 2, roundingMode: 'expand'}, '-0.000000000000000000000004'), nf({maximumFractionDigits: 2, roundingMode: 'halfExpand'}, '0.005'), nf({maximumFractionDigits: 2, roundingMode: 'halfEven'}, '0.005'), nf({maximumFractionDigits: 2, roundingMode: 'halfEven'}, '0.015'), nf({maximumFractionDigits: 2, roundingMode: 'halfTrunc'}, '0.005')]));
console.log('scientific carry', J([nf({notation: 'scientific', maximumFractionDigits: 2}, 9.9999), nf({notation: 'engineering', maximumFractionDigits: 1}, 999.99), nf({notation: 'scientific', maximumSignificantDigits: 2}, 99999), nf({notation: 'scientific'}, 0.00099999), nf({notation: 'engineering', maximumSignificantDigits: 1}, 9999), nf({notation: 'scientific', maximumFractionDigits: 0}, 96), nf({notation: 'engineering'}, 999999)]));
console.log('rounding priority compact', J([nf({notation: 'compact', roundingPriority: 'morePrecision'}, 1234), nf({notation: 'compact', roundingPriority: 'morePrecision'}, 1.5), nf({notation: 'compact', roundingPriority: 'morePrecision'}, 15), nf({notation: 'compact', roundingPriority: 'lessPrecision'}, 1.55), nf({notation: 'compact', roundingPriority: 'morePrecision'}, 0.123), nf({notation: 'compact'}, 1234)]));
console.log('unit parts', parts({style: 'unit', unit: 'kilometer-per-hour'}, 50), '/', parts({style: 'unit', unit: 'liter', unitDisplay: 'long'}, 1), '/', parts({style: 'unit', unit: 'percent', notation: 'compact'}, 12345));
console.log('currency parts', parts({style: 'currency', currency: 'USD', currencySign: 'accounting', notation: 'compact'}, -12345), '/', parts({style: 'currency', currency: 'EUR', currencySign: 'accounting'}, -5, 'de'), '/', parts({style: 'currency', currency: 'USD', currencyDisplay: 'name', notation: 'compact'}, -1234567));
console.log('currency compact', parts({style: 'currency', currency: 'JPY', notation: 'compact', compactDisplay: 'long'}, 1234567, 'ja'), '/', parts({style: 'currency', currency: 'USD', currencySign: 'accounting', signDisplay: 'always'}, 0));
console.log('significant strings', J([nf({maximumSignificantDigits: 2}, 123456789012345678901234567890n), nf({maximumSignificantDigits: 2, roundingMode: 'ceil'}, 99n), nf({maximumSignificantDigits: 3}, '0.000123456'), nf({roundingIncrement: 5, maximumFractionDigits: 1}, '1.23'), nf({maximumSignificantDigits: 2, roundingPriority: 'lessPrecision'}, '123.456')]));
console.log('unit display default', new Intl.NumberFormat('en', {style: 'unit', unit: 'meter'}).resolvedOptions().unitDisplay, nf({style: 'unit', unit: 'meter'}, 3));
''')


def test_intl_segmenter_plural_relative_duration_corners(run, workdir):
    """CATCHES: grapheme segmentation that splits Hangul LV/LVT syllables from trailing jamo,
    separates spacing marks, merges controls or CRLF wrongly; word segmentation of MidLetter/MidNum
    punctuation; containing() on edges/NaN/strings; PluralRules option validation messages,
    compact resolvedOptions and infinite selectRange; RelativeTimeFormat numberingSystem validation and
    Polish unit words; DurationFormat numberingSystem validation and sub-second folding (micro/
    nanosecond fractional values, a hidden-seconds minute separator in mixed numeric styles)."""
    check_js(run, workdir, "intl_segmenter_plural_relative_duration_corners", r'''
const t = (f) => { try { return J(f()); } catch (e) { return e.name + ': ' + e.message; } };
const seg = (s, g = 'grapheme', l = 'en') => [...new Intl.Segmenter(l, {granularity: g}).segment(s)].map(x => x.segment);
console.log('hangul', t(() => seg('가각ᆨ각한')), t(() => seg('ᄀ가가ᅡ')));
console.log('spacing mark', t(() => seg('का किः')), t(() => seg('กำ')));
console.log('controls', t(() => seg('a b\r\nc\u0007d\u200Be\u2028f')));
console.log('empty', t(() => seg('')), t(() => seg('', 'word')), t(() => seg('', 'sentence')));
console.log('word mid punctuation', t(() => seg('a:b c·d e.f 3.4 5,6 7;8 g;h', 'word')));
console.log('containing', t(() => { const s = new Intl.Segmenter('en', {granularity: 'word'}).segment('hi there'); return [s.containing(0).segment, s.containing(2).segment, s.containing(7).segment, s.containing(8), s.containing(-1), s.containing(NaN).segment, s.containing('3').segment]; }));
for (const o of [{notation: 'bad'}, {compactDisplay: 'bad'}, {maximumFractionDigits: 101}, {minimumIntegerDigits: 0}, {maximumSignificantDigits: 22}, {minimumSignificantDigits: 0}, {roundingMode: 'bad'}, {roundingPriority: 'bad'}, {trailingZeroDisplay: 'bad'}, {roundingIncrement: 3}])
  console.log('plural options', J(o), t(() => Object.keys(new Intl.PluralRules('en', o).resolvedOptions()).length));
console.log('plural compact', t(() => new Intl.PluralRules('en', {notation: 'compact'}).resolvedOptions()), t(() => new Intl.PluralRules('en', {notation: 'compact', compactDisplay: 'long'}).select(1000000)));
console.log('plural infinite range', t(() => new Intl.PluralRules('en').selectRange(1, Infinity)), t(() => new Intl.PluralRules('fr').selectRange(0, Infinity)), t(() => new Intl.PluralRules('en').selectRange(-Infinity, 1)));
console.log('rtf numberingSystem', t(() => new Intl.RelativeTimeFormat('en', {numberingSystem: 'ab'})), t(() => new Intl.RelativeTimeFormat('en', {numberingSystem: 'abc-de'})), t(() => new Intl.RelativeTimeFormat('en', {numberingSystem: 'arab'}).format(3, 'day')));
console.log('rtf polish', t(() => ['long', 'short', 'narrow'].map(s => new Intl.RelativeTimeFormat('pl', {style: s}).format(-5, 'quarter') + ' / ' + new Intl.RelativeTimeFormat('pl', {style: s}).format(2, 'week'))));
console.log('df numberingSystem', t(() => new Intl.DurationFormat('en', {numberingSystem: 'ab'})), t(() => new Intl.DurationFormat('en', {numberingSystem: 'thai'}).format({hours: 12, minutes: 3})));
const df = (o, d) => t(() => new Intl.DurationFormat('en', o).format(d));
console.log('df fractional', df({milliseconds: 'long', microseconds: 'numeric'}, {milliseconds: 1, microseconds: 2, nanoseconds: 3}), df({milliseconds: 'long', microseconds: 'numeric'}, {microseconds: 2}), df({milliseconds: 'numeric'}, {milliseconds: 5}), df({milliseconds: 'numeric'}, {seconds: 3, milliseconds: 5}), df({microseconds: 'numeric'}, {microseconds: 7}));
console.log('df hidden seconds', df({hours: 'numeric', secondsDisplay: 'auto'}, {hours: 1, milliseconds: 5}), df({hours: 'numeric', secondsDisplay: 'auto'}, {hours: 1, microseconds: 5}), df({hours: 'numeric', secondsDisplay: 'auto'}, {hours: 1, nanoseconds: 5}), df({hours: 'numeric', secondsDisplay: 'auto'}, {hours: 1}), df({hours: 'numeric', secondsDisplay: 'auto'}, {hours: 1, seconds: 2}));
console.log('df microsecond fold', df({microseconds: 'long', nanoseconds: 'numeric'}, {microseconds: 7, nanoseconds: 5}), df({microseconds: 'long', nanoseconds: 'numeric'}, {microseconds: 7}), df({milliseconds: 'long', microseconds: 'numeric'}, {milliseconds: 5}), df({milliseconds: 'long', microseconds: 'numeric'}, {milliseconds: 5, nanoseconds: 9}));
console.log('df misc', df({milliseconds: 'numeric', millisecondsDisplay: 'always'}, {seconds: 1}), df({style: 'digital', fractionalDigits: 2}, {seconds: 1, milliseconds: 456}));
''')


def test_intl_datetime_temporal_hour_cycles_and_ranges(run, workdir):
    """CATCHES: DateTimeFormat over Temporal values with an unresolved hour cycle (locale default
    12h/24h, hour12 option, -u-hc- extension), Temporal type checks in formatRange (mixed types,
    ZonedDateTime rejection, calendar mismatch for PlainYearMonth/PlainMonthDay), Hebrew month
    names in common and leap years, era-less negative-year ranges, Chinese relatedYear ranges and
    offset time zones. Pins reference quirks: a Temporal.Duration is formatted as the epoch date
    (1/1/1970) instead of throwing, and the second Adar of a leap year is named "Adar"."""
    check_js(run, workdir, "intl_datetime_temporal_hour_cycles_and_ranges", r'''
const t = (f) => { try { return J(f()); } catch (e) { return e.name + ': ' + e.message; } };
const T = Temporal;
const pt = T.PlainTime.from('00:05:09'), pt2 = T.PlainTime.from('13:05:09');
for (const [l, o] of [['en', {}], ['de', {}], ['en', {hour12: false}], ['de', {hour12: true}], ['ja', {}], ['en', {hourCycle: 'h23'}], ['en-u-hc-h11', {}], ['en', {timeStyle: 'short'}]])
  console.log('plain time', l, J(o), t(() => { const f = new Intl.DateTimeFormat(l, o); return [f.format(pt), f.format(pt2), f.resolvedOptions().hourCycle]; }));
const d = new Intl.DateTimeFormat('en', {timeZone: 'UTC'});
const dur = T.Duration.from({hours: 1});
console.log('duration', t(() => d.format(dur)), t(() => d.formatRange(dur, dur)), t(() => d.formatToParts(dur).map(p => p.value).join('')));
const z = T.ZonedDateTime.from('2020-01-01T10:00[UTC]');
console.log('zoned', t(() => d.formatRange(z, z)), t(() => d.formatRange(z, T.Instant.fromEpochMilliseconds(0))));
console.log('mixed', t(() => d.formatRange(T.PlainDate.from('2020-01-01'), T.PlainDateTime.from('2020-01-02T00:00'))), t(() => d.formatRange(0, T.Instant.fromEpochMilliseconds(0))));
console.log('same type', t(() => d.formatRange(T.Instant.fromEpochMilliseconds(0), T.Instant.fromEpochMilliseconds(86400000))), t(() => d.formatRange(T.PlainTime.from('10:00'), T.PlainTime.from('11:30'))));
console.log('calendar mismatch', t(() => d.formatRange(T.PlainYearMonth.from('2020-01'), T.PlainYearMonth.from('2020-03'))), t(() => d.formatRange(T.PlainMonthDay.from('01-05'), T.PlainMonthDay.from('03-07'))));
console.log('no overlap', t(() => new Intl.DateTimeFormat('en', {timeZone: 'UTC', day: 'numeric'}).format(T.PlainYearMonth.from('2020-03'))), t(() => new Intl.DateTimeFormat('en', {timeZone: 'UTC', year: 'numeric'}).format(T.PlainMonthDay.from('03-04'))));
const heb = new Intl.DateTimeFormat('en-u-ca-hebrew', {timeZone: 'UTC', year: 'numeric', month: 'long', day: 'numeric'});
console.log('hebrew 5783', [0, 2, 4, 6, 8, 10].map(m => heb.format(Date.UTC(2023, m, 15))).join(' | '));
console.log('hebrew 5784', [0, 1, 2, 3].map(m => heb.format(Date.UTC(2024, m, 15))).join(' | '));
console.log('hebrew defaults', new Intl.DateTimeFormat('en-u-ca-hebrew', {timeZone: 'UTC'}).format(Date.UTC(2023, 5, 15)), new Intl.DateTimeFormat('en-u-ca-hebrew', {timeZone: 'UTC', month: 'short'}).format(Date.UTC(2023, 5, 15)));
const u = {timeZone: 'UTC'};
console.log('era ranges', t(() => new Intl.DateTimeFormat('en', {...u, year: 'numeric'}).formatRange(Date.UTC(-5, 0, 1), Date.UTC(2020, 0, 1))), t(() => new Intl.DateTimeFormat('en', {...u, year: 'numeric', month: 'short', era: 'short'}).formatRange(Date.UTC(-5, 0, 1), Date.UTC(-5, 5, 1))));
console.log('period ranges', t(() => new Intl.DateTimeFormat('en', {...u, hour: 'numeric', dayPeriod: 'short'}).formatRange(Date.UTC(2020, 0, 1, 9), Date.UTC(2020, 0, 1, 15))), t(() => new Intl.DateTimeFormat('en', {...u, second: 'numeric', fractionalSecondDigits: 2}).formatRange(Date.UTC(2020, 0, 1, 9, 0, 1, 100), Date.UTC(2020, 0, 1, 9, 0, 1, 900))));
console.log('offset zones', t(() => new Intl.DateTimeFormat('en', {timeZone: '+05:30', hour: 'numeric', minute: 'numeric', timeZoneName: 'longOffset'}).format(0)), t(() => new Intl.DateTimeFormat('en', {timeZone: '-0230', hour: 'numeric', minute: 'numeric'}).format(0)));
console.log('chinese range', t(() => new Intl.DateTimeFormat('en-u-ca-chinese', {...u, year: 'numeric', month: 'long'}).formatRange(Date.UTC(2020, 0, 1), Date.UTC(2021, 5, 1))));
''')


def test_intl_new_target_prototype_and_unwrap(run, workdir):
    """CATCHES: Intl constructors invoked through Reflect.construct with a newTarget whose
    `prototype` is not an object (must fall back to the newTarget realm's intrinsic prototype, also
    for bound functions and functions with a reshaped/null [[Prototype]]), not propagating a throwing
    `prototype` getter, not detecting a proxy newTarget revoked by its own getter, and brand checks /
    legacy fallback-symbol unwrapping of objects that merely inherit from a service prototype."""
    check_js(run, workdir, "intl_new_target_prototype_and_unwrap", r'''
const t = (f) => { try { return f(); } catch (e) { return e.name + ': ' + e.message; } };
const services = ['NumberFormat', 'DateTimeFormat', 'Collator', 'PluralRules', 'RelativeTimeFormat', 'ListFormat', 'DisplayNames', 'Segmenter', 'Locale', 'DurationFormat'];
const args = {DisplayNames: ['en', {type: 'region'}], Locale: ['en']};
function F() {} F.prototype = null;
const bound = function () {}.bind(null);
function G() {} G.prototype = 0; Object.setPrototypeOf(G, Object.create(Function.prototype));
function H() {} H.prototype = 'x'; Object.setPrototypeOf(H, null);
const throwing = new Proxy(function () {}, {get(target, k) { if (k === 'prototype') throw new EvalError('proto get'); return target[k]; }});
for (const s of services) {
  const C = Intl[s], a = args[s] || ['en'];
  const proto = (nt) => t(() => Object.getPrototypeOf(Reflect.construct(C, a, nt)) === C.prototype ? 'intrinsic' : 'other');
  const rv = Proxy.revocable(function () {}, {get(target, k) { if (k === 'prototype') { rv.revoke(); return undefined; } return target[k]; }});
  console.log(s.padEnd(18), [proto(F), proto(bound), proto(G), proto(H), proto(throwing), proto(rv.proxy)].join(' | '));
}
class Sub extends Intl.NumberFormat {}
console.log('subclass', Object.getPrototypeOf(new Sub('en')) === Sub.prototype, new Sub('en').format(1234.5));
const fake = Object.create(Intl.NumberFormat.prototype);
console.log('unbranded', t(() => Intl.NumberFormat.prototype.resolvedOptions.call(fake)), t(() => Intl.NumberFormat.prototype.formatToParts.call(fake, 1)), t(() => Intl.DateTimeFormat.prototype.resolvedOptions.call(Object.create(Intl.DateTimeFormat.prototype))));
const chained = Intl.NumberFormat.call(Object.create(Intl.NumberFormat.prototype), 'de');
const sym = Object.getOwnPropertySymbols(chained);
console.log('fallback symbol', sym.length, String(sym[0]), Intl.NumberFormat.prototype.resolvedOptions.call(chained).locale);
const wrong = Object.create(Intl.NumberFormat.prototype); wrong[sym[0]] = {};
console.log('fallback wrong value', t(() => Intl.NumberFormat.prototype.resolvedOptions.call(wrong)));
const real = Object.create(Intl.NumberFormat.prototype); real[sym[0]] = new Intl.NumberFormat('de');
const fmtGetter = Object.getOwnPropertyDescriptor(Intl.NumberFormat.prototype, 'format').get;
console.log('fallback real value', t(() => Intl.NumberFormat.prototype.resolvedOptions.call(real).locale), t(() => fmtGetter.call(real)(1234.5)), t(() => fmtGetter.call(fake)));
''')
