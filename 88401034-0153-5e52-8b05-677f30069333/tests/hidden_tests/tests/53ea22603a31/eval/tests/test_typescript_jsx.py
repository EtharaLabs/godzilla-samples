"""TypeScript and JSX entry files: lumen-cli erases erasable TypeScript syntax from .ts/.cts files run as
CommonJS (via node:module's stripTypeScriptTypes), rejects syntax that needs transformation, does not
strip ES-module TypeScript (.mts / .ts under "type": "module"), and lowers .jsx through its own JSX
transform to React.createElement calls (classic runtime, using whatever `React` is in scope)."""

from conftest import check_script, resources_for, write_files

G = resources_for(__file__)

# A tiny React shim: createElement returns plain objects and render() serialises them.
REACT_SHIM = r'''
const React = {
  Fragment: Symbol.for('fragment'),
  createElement(type, props, ...children) { return { type, props, children }; },
};
function render(n) {
  if (n === null || n === undefined || n === false || n === true) return '';
  if (Array.isArray(n)) return n.map(render).join('');
  if (typeof n !== 'object') return String(n);
  if (typeof n.type === 'function') return render(n.type({ ...(n.props || {}), children: n.children }));
  const tag = n.type === React.Fragment ? '#fragment' : n.type;
  const attrs = n.props ? Object.entries(n.props).map(([k, v]) => ' ' + k + '=' + (typeof v === 'object' ? '{' + render(v) + '}' : JSON.stringify(v))).join('') : '';
  return '<' + tag + attrs + '>' + n.children.map(render).join('') + '</' + tag + '>';
}
'''


def test_ts_entry_erasable_syntax(run, workdir):
    """CATCHES: a .ts entry that is not stripped before parsing, a stripper that eats colons/`as` inside
    strings, templates or comments, mishandles multi-line interfaces/type aliases, optional markers,
    tuple/object/generic annotations, return types, `as const`/`satisfies`, `import type` or
    `export interface`; also that a .ts file without a "type" package runs as CommonJS."""
    check_script(run, workdir, G, "ts_erasable", r'''
import type { Foo } from './nowhere';
export interface Shape {
  area(): number;
  name?: string;
}
type Pair<T> = [T, T];
type Obj = {
  a: string;
  b: number;
};
interface Empty {}
const url: string = "http://host:8080/path"; // a comment: with colons as text
let maybe?: number;
const tpl: string = `a:${1 + 1}:b as c`;
const pair: Pair<string> = ['l', 'r'];
const table: { [key: string]: number } = { z: 26 };
const list: Array<{ k: string }> = [{ k: 'v' }];
function add(a: number, b: number = 10): number { return a + b; }
function opt(a?: string, rest?: Record<string, number>): string { return String(a) + ':' + (rest ? Object.keys(rest).length : 'none'); }
const arrow = (x: number, ...more: number[]): string => x + '/' + more.length;
const fexpr = function (s: string): string { return s.toUpperCase(); };
async function later(v: number): Promise<number> { return v * 2; }
class Point {
  x = 1;
  move(dx: number, dy: number): string { return (this.x + dx) + ',' + dy; }
}
const asserted = ({ n: 5 } as any).n;
const fixed = ['a', 'b'] as const;
const checked = (7 as number) satisfies number;
for (let i: number = 0; i < 2; i++) console.log('loop', i);
console.log(url, maybe, tpl, pair.join('&'), table.z, list[0].k);
console.log(add(1), add(1, 2), opt(), opt('s', { q: 1 }), arrow(1, 2, 3), fexpr('up'));
console.log(new Point().move(2, 3), asserted, fixed.length, checked);
console.log(typeof module, typeof require, typeof exports, __filename.endsWith('ts_erasable.ts'));
later(21).then((v: number) => console.log('async', v));
''', filename="ts_erasable.ts")


def test_cts_entry_and_ts_dependencies(run, workdir):
    """CATCHES: .cts entries not treated as CommonJS + TypeScript, require() of extensionless
    TypeScript siblings (.ts/.cts) not being found or stripped (from a TypeScript or a plain .js
    entry), or TypeScript modules not getting the ordinary CommonJS wrapper (module.exports/require)."""
    write_files(workdir, {
        "lib/shapes.ts": "interface Sq { side: number }\nfunction area(s: Sq): number { return s.side * s.side; }\n"
                         "module.exports = { area, label: 'shapes.ts' as string };\n",
        "lib/plain.js": "exports.js = 'plain js dependency';\n",
    })
    check_script(run, workdir, G, "ts_cts_entry", r'''
type Mode = 'fast' | 'slow';
const mode: Mode = 'fast';
const shapes = require('./lib/shapes');
const { js } = require('./lib/plain');
console.log(mode, shapes.area({ side: 4 }), shapes.label, js, require.main === module);
console.log(require('path').basename(__filename), typeof module.exports);
''', filename="entry.cts")
    write_files(workdir, {
        "math.ts": "export interface Unused { x: number }\n"
                   "function add(a: number, b: number): number { return a + b; }\n"
                   "module.exports = { add, kind: 'ts module' as string };\n",
        "conf.cts": "type Mode = 'a' | 'b';\nconst mode: Mode = 'b';\nexports.mode = mode;\n"
                    "exports.helper = require('./math').kind;\n",
    })
    check_script(run, workdir, G, "ts_required_from_js", r'''
const m = require('./math');
console.log(m.add(2, 3), m.kind);
const c = require('./conf.cts');
console.log(c.mode, c.helper);
console.log(require('./conf') === c);
''')


def test_ts_unsupported_syntax_is_rejected(run, workdir):
    """CATCHES: enums/namespaces being silently accepted (or half-stripped) instead of rejected before any
    code runs with the exact 'TypeScript ... declarations require transformation' SyntaxError; also pins
    the reference's limits of type stripping: generic type parameters on functions, parameter
    properties, class field annotations, `declare`, non-null `!`, function-typed parameters and ES
    `import` in a CommonJS .ts file all reach the JS parser and fail with these exact SyntaxErrors."""
    write_files(workdir, {
        "en.ts": "console.log('must not run');\nenum Color { Red, Green }\n",
        "ns.ts": "console.log('must not run');\nnamespace NS { export const x = 1; }\n",
        "both.cts": "const s: string = 'enum inside a string is fine';\nconsole.log(s);\n",
    })
    en, ns, ok = run(["en.ts"]), run(["ns.ts"]), run(["both.cts"])
    assert (en.stdout, en.stderr, en.returncode) == (
        b"", b"Uncaught SyntaxError: TypeScript enum declarations require transformation\n", 1)
    assert (ns.stdout, ns.stderr, ns.returncode) == (
        b"", b"Uncaught SyntaxError: TypeScript namespace declarations require transformation\n", 1)
    assert (ok.stdout, ok.stderr, ok.returncode) == (b"enum inside a string is fine\n", b"", 0)
    cases = {
        "generic.ts": ("function id<T>(x: T): T { return x; }\n", "expected '('"),
        "paramprop.ts": ("class C { constructor(public n: string) {} }\n",
                         "'public' cannot be used as a binding in strict mode"),
        "classfield.ts": ("class P { x: number = 1; }\n", "expected ';'"),
        "declare.ts": ("declare const ext: string;\n", "expected ';'"),
        "nonnull.ts": ("const v = [1][0]!;\nconsole.log(v);\n", "expected ';'"),
        "fntype.ts": ("function g(cb: (e: Error) => void): void { cb(null); }\n", "expected ')'"),
        "esimport.ts": ("import { readFileSync } from 'fs';\nconsole.log(typeof readFileSync);\n", "expected '('"),
    }
    write_files(workdir, {name: src for name, (src, _) in cases.items()})
    got = {}
    for name in cases:
        r = run([name])
        got[name] = (r.stdout, r.stderr.decode(), r.returncode)
    assert got == {name: (b"", f"Uncaught SyntaxError: {msg}\n", 1) for name, (_, msg) in cases.items()}


def test_strip_typescript_types_api(run, workdir):
    """CATCHES: stripTypeScriptTypes that does not preserve positions (types must become spaces of equal
    length and newlines must survive), wrong handling of options (mode/sourceMap/sourceUrl), or
    different error names/codes/messages for unsupported or malformed input."""
    check_script(run, workdir, G, "ts_strip_api", r'''
const { stripTypeScriptTypes } = require('node:module');
const show = (s) => console.log(JSON.stringify(s));
show(stripTypeScriptTypes('const a: number = 1;'));
show(stripTypeScriptTypes('interface A {\n  x: number;\n}\nlet b = a as string;'));
show(stripTypeScriptTypes('function f(a?: string, b: number[] = []): void {}'));
show(stripTypeScriptTypes('type T = { a: 1 };\nimport type { X } from "y";\nconst s = "a: b";'));
show(stripTypeScriptTypes('let q = 1;', { sourceUrl: 'file.ts' }));
show(stripTypeScriptTypes('let q = 1;', { mode: 'strip' }));
const bad = ['enum E { A, B }', 'namespace N { export const x = 1 }', 'let x: = 1', 'interface X', 'function f(a: (number) {}'];
for (const src of bad) {
  try { show(stripTypeScriptTypes(src)); } catch (e) { console.log(e.name, e.code, e.message); }
}
for (const args of [[1], ['x', null], ['x', { mode: 'transform' }], ['x', { sourceMap: true }]]) {
  try { show(stripTypeScriptTypes(...args)); } catch (e) { console.log(e.name, e.code, e.message); }
}
''')


def test_esm_typescript_is_not_stripped(run, workdir):
    """CATCHES: pins that ES-module TypeScript is run as plain JavaScript by the reference: a .mts entry
    (or a .ts entry under "type": "module") with no annotations runs as ESM, while any annotation makes
    the parser fail."""
    write_files(workdir, {
        "plain.mts": "export const v = 1;\nconsole.log('mts as ESM', typeof require, import.meta.url.endsWith('plain.mts'));\n",
        "typed.mts": "const x: number = 1;\nconsole.log(x);\n",
        "pkg/package.json": '{"type": "module"}',
        "pkg/typed.ts": "let n: number = 2;\nconsole.log(n);\n",
        "pkg/plain.ts": "import { join } from 'node:path';\nconsole.log('ts as ESM', join('a', 'b'));\n",
    })
    outs = [run([p]) for p in ["plain.mts", "typed.mts", "pkg/typed.ts", "pkg/plain.ts"]]
    assert [(o.stdout, o.stderr, o.returncode) for o in outs] == [
        (b"mts as ESM function true\n", b"", 0),
        (b"", b"Uncaught SyntaxError: missing initializer in const declaration\n", 1),
        (b"", b"Uncaught SyntaxError: expected ';'\n", 1),
        (b"ts as ESM a/b\n", b"", 0),
    ]


def test_jsx_elements_props_children(run, workdir):
    """CATCHES: a JSX transform that mis-lowers element names (lowercase -> string, Capitalised/member
    expressions -> references, dashed names -> strings), props (spread order, boolean shorthand,
    quoted attribute strings without escape processing, expression values, element-valued props),
    children (expressions, nested map() results) or fragments."""
    check_script(run, workdir, G, "jsx_elements", REACT_SHIM + r'''
function Item({ label, children }) { return <li class="item">{label}{children}</li>; }
const ui = { Deep: { Comp: function DeepComp() { return <em>deep</em>; } } };
const items = ['a', 'b'];
const base = { id: 'x', 'data-n': 2 };
const tree = (
  <div {...base} hidden title='single "q" \n' data-x="1" aria-label={"lbl"} id="override">
    {items.map((i) => <Item label={i}>!</Item>)}
    <>
      <br/>
      <rect width={5} icon={<i/>} />
    </>
    {1 < 2 ? <b>yes</b> : null}
    <ui.Deep.Comp />
    <x-custom data-a="1" />
    {false}{null}{undefined}{0}
  </div>
);
console.log(render(tree));
console.log(JSON.stringify(Object.keys(tree.props)), tree.children.length);
const self = <input disabled value={3} />;
console.log(JSON.stringify(self), JSON.stringify(<p></p>), JSON.stringify(<p>{}</p>));
''', filename="jsx_elements.jsx")


def test_jsx_text_whitespace(run, workdir):
    """CATCHES: wrong JSX text normalisation: multi-line text must be trimmed per line and joined with
    single spaces, whitespace-only lines dropped, inner runs of spaces kept, HTML entities left
    undecoded (the reference does not decode them), and whitespace between two expressions dropped."""
    check_script(run, workdir, G, "jsx_text", r'''
const React = { createElement: (t, p, ...c) => ({ t, c }), Fragment: 'F' };
const name = 'World';
const show = (el) => console.log(JSON.stringify(el.c));
show(<p>  Hello,   {name}!  </p>);
show(<p>
    first line
      second   line

    third &amp; &lt;fourth&gt; &copy;
  </p>);
show(<p>{name} {name}</p>);
show(<p>   </p>);
show(<p>
  {name}
</p>);
show(<p>a{' '}b</p>);
show(<p>quote " and ' and \n stay</p>);
''', filename="jsx_text.jsx")


def test_jsx_lexing_does_not_misfire(run, workdir):
    """CATCHES: a JSX scanner that treats `<` in comparisons, strings, templates, regex literals or
    comments as the start of an element, or that breaks `/` division after values."""
    check_script(run, workdir, G, "jsx_lexing", r'''
const React = { createElement: (t, p, ...c) => '<' + t + (p ? JSON.stringify(p) : '') + '>' + c.join('') + '</' + t + '>', Fragment: 'frag' };
const a = 1, b = 2;
console.log(a < b, a<b ? 'lt' : 'ge', 'string with <tag> inside', `template <b>${a}</b>`);
console.log(/<div>/.test('<div>'), 10 / 2 / 5, [3, 1, 2].filter((x) => x <a + 2).length);
// a comment with <div> inside
/* block <span> */
function f(x) { return x <a ? 'small' : 'big'; }
console.log(f(0), f(5));
console.log(<p>{a < b && <b>and</b>}</p>);
console.log(<ul>{[1, 2].map((n) => <li key={n}>{n * 10}</li>)}</ul>);
console.log(typeof <i/>, [<a/>, <b/>].join(','));
function r() { return <x-el data-a="1" />; }
console.log(r());
''', filename="jsx_lexing.jsx")


def test_jsx_module_graph(run, workdir):
    """CATCHES: .jsx dependencies not being transformed when imported from a .jsx entry, extensionless
    imports not probing .jsx, or the factory not being looked up as the importing module's `React`."""
    write_files(workdir, {
        "react-shim.mjs": "export default { createElement: (t, p, ...c) => ({ t: typeof t === 'function' ? t.name : t, p, c }), Fragment: 'Frag' };\n",
        "components/Button.jsx": "import React from '../react-shim.mjs';\n"
                                 "export function Button({ label }) { return <button type=\"button\">{label}</button>; }\n"
                                 "export default function Card(props) { return <section>{props.title}</section>; }\n",
    })
    check_script(run, workdir, G, "jsx_graph", r'''
import React from './react-shim.mjs';
import Card, { Button } from './components/Button';
const el = <main><Button label="go" /><Card title="t" /></main>;
console.log(JSON.stringify(el));
console.log(JSON.stringify(Button({ label: 'x' })), JSON.stringify(<>frag</>));
''', filename="main.jsx")


def test_jsx_transform_errors(run, workdir):
    """CATCHES: malformed JSX being accepted or reported with different text: the reference fails before
    running anything with 'Uncaught JSX transform failed for <path>: <reason>' for each kind of error,
    and a missing React factory only fails at runtime with a ReferenceError."""
    cases = {
        "unclosed.jsx": ("const x = <div>\n  <span>unclosed\n</div>;\n", "unterminated JSX element"),
        "attrval.jsx": ("const x = <div a=1 />;\n", "expected a JSX attribute value"),
        "brace.jsx": ("const x = <div a={1 />;\n", "unterminated `{ … }` in JSX"),
        "opentag.jsx": ('const x = <div a="1"', "unterminated JSX opening tag"),
    }
    write_files(workdir, {name: "console.log('must not run');\n" + src for name, (src, _) in cases.items()})
    got = {}
    for name in cases:
        r = run([name])
        got[name] = (r.stdout, r.stderr.decode(), r.returncode)
    assert got == {name: (b"", f"Uncaught JSX transform failed for {name}: {msg}\n", 1)
                   for name, (_, msg) in cases.items()}
    (workdir / "noreact.jsx").write_text("console.log('runs first');\nconst el = <div/>;\n")
    r = run(["noreact.jsx"])
    assert r.stdout == b"runs first\n"
    assert r.stderr == (b"Uncaught (in promise) ReferenceError: React is not defined\n"
                        b"Uncaught ReferenceError: React is not defined\n")
    assert r.returncode == 1


def test_jsx_transform_output_text(run, workdir):
    """CATCHES: differences in the exact JavaScript the JSX transform emits (factory call shape, `null`
    props, prop ordering/quoting, shorthand `true`, child text splitting, fragments) as observed
    through Bun.Transpiler's jsx/tsx/ts loaders; also pins reference quirks: a comment-only `{}`
    child is emitted verbatim (leaving an empty argument), namespaced tags are emitted unquoted,
    entities are not decoded, and transform errors surface as SyntaxErrors."""
    check_script(run, workdir, G, "jsx_transform_text", r'''
const t = new Bun.Transpiler({ loader: 'jsx' });
const show = (s) => console.log(JSON.stringify(s));
show(t.transformSync('<div/>'));
show(t.transformSync('<Foo.Bar x="1" {...p} y={2} flag />'));
show(t.transformSync('<>\n  <a>hi {name}!</a>\n  {/* c */}\n</>'));
show(t.transformSync('const x = a < b ? <i>{a}</i> : null;'));
show(t.transformSync('<svg:rect data-x="1" aria-hidden={true}>text &amp; more</svg:rect>'));
show(t.transformSync('<p>{ }</p>'));
show(t.transformSync('function C() { return <ul>{xs.map((x) => <li key={x}>{x}</li>)}</ul>; }'));
show(new Bun.Transpiler({ loader: 'tsx' }).transformSync('const el: JSX = <b>{n as number}</b>;'));
show(new Bun.Transpiler({ loader: 'ts' }).transformSync('let n: number = 1;'));
for (const bad of ['<div', '<div a=1/>', '<div>{1</div>', '<div><b></div>']) {
  try { show(t.transformSync(bad)); } catch (e) { console.log(e.name + ': ' + e.message); }
}
t.transform('<x/>').then((s) => show(s));
''')
