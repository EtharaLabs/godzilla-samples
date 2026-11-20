"""`.jsx` entry points: the runtime lowers JSX to React.createElement calls before running the file as ESM."""

import pytest

from conftest import golden, write_files

# A minimal stand-in for React so the transformed calls render to readable markup.
FAKE_REACT = r"""
globalThis.React = {
  Fragment: Symbol.for('frag'),
  createElement(type, props, ...children) { return { type, props, children }; },
};
globalThis.render = function render(n) {
  if (n == null || n === false || n === true) return '';
  if (Array.isArray(n)) return n.map(render).join('');
  if (typeof n !== 'object') return String(n);
  if (typeof n.type === 'function') return render(n.type({ ...(n.props || {}), children: n.children }));
  if (n.type === React.Fragment) return '[' + render(n.children) + ']';
  const attrs = Object.entries(n.props || {}).map(([k, v]) => ` ${k}=${typeof v === 'function' ? 'fn' : JSON.stringify(v)}`).join('');
  return `<${String(n.type)}${attrs}>${render(n.children)}</${String(n.type)}>`;
};
"""


def _res(r):
    return r.returncode, r.stdout, r.stderr


def _run_jsx(run, workdir, body, name="app.jsx", extra=None):
    write_files(workdir, {"react-shim.mjs": FAKE_REACT, name: "import './react-shim.mjs';\n" + body, **(extra or {})})
    return run([name])


def test_jsx_attribute_forms(run, workdir):
    """CATCHES: JSX lowering that mishandles string/expression/boolean/spread/element-valued/hyphenated attributes."""
    body = r"""
const extra = { title: 'T', 'data-n': 3 };
const el = <input type="text" value={1 + 2} disabled {...extra} aria-label='single "quoted"' data-x="a\nb" icon=<b>i</b> on:click={() => 0} />;
console.log(render(el));
console.log(JSON.stringify(Object.keys(el.props)));
"""
    r = _run_jsx(run, workdir, body)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "attribute_forms")


def test_jsx_components_and_member_tags(run, workdir):
    """CATCHES: lowering that quotes capitalised/member-expression tags as strings or treats lowercase/hyphenated tags as identifiers."""
    body = r"""
function Greeting({ name, children }) { return <p class="g">Hello, {name}! {children}</p>; }
const UI = { Card: ({ children }) => <section>{children}</section> };
const Inner = { deep: () => <i>deep</i> };
const el = <UI.Card><Greeting name="Ada">extra</Greeting><my-elem/><Inner.deep/></UI.Card>;
console.log(render(el));
console.log(typeof el.type, el.children.map(c => typeof c.type).join(','));
"""
    r = _run_jsx(run, workdir, body)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "components")


def test_jsx_children_whitespace_and_containers(run, workdir):
    """CATCHES: wrong JSX text whitespace normalisation, or empty expression containers producing children."""
    body = r"""
const items = ['a', 'b'];
const el = (
  <ul>
    first line
       second   line
    {}
    {   }
    {items.map(i => <li key={i}>{i.toUpperCase()}</li>)}
    <>frag {1}{2}</>
    tail	text
  </ul>
);
console.log(JSON.stringify(el.children.map(c => typeof c === 'string' ? c : Array.isArray(c) ? 'array' : 'node')));
console.log(render(el));
"""
    r = _run_jsx(run, workdir, body)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "children_whitespace")


def test_jsx_coexists_with_js_syntax(run, workdir):
    """CATCHES: a JSX scanner that mistakes comparisons, regex literals, strings, comments or templates containing '<' for JSX."""
    body = r"""
const a = 3, b = 5;
const cmp = a < b && b > a;          // a < b is a comparison, not a tag
const re = /<div>[/]x/g;             // regex containing tags
const s = "<span>not jsx</span>" + '<i>' ;
/* <block comment> */
const t = `<tpl ${a < b ? <em>yes</em> : 'no'}>`;
const n = 10 < 20;
function pick(x) { if (x) return <b>{x}</b>; else return <i/>; }
const arr = [1, 2].map(x => x * 2 < 3);
console.log(cmp, re.source, s, t.slice(0, 5), typeof t, n, render(pick('k')), render(pick(0)), arr.join());
console.log(typeof (void <a/>), render([<x-a/>, (<y/>)]));
"""
    r = _run_jsx(run, workdir, body)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "js_syntax")


def test_jsx_imported_from_esm_entry(run, workdir):
    """CATCHES: .jsx modules imported from an .mjs entry not being transformed by the ESM loader."""
    write_files(workdir, {
        "react-shim.mjs": FAKE_REACT,
        "button.jsx": "export const Button = ({ label }) => <button type=\"button\">{label}</button>;\nexport default 'btn';\n",
        "main.mjs": "import './react-shim.mjs';\nimport def, { Button } from './button.jsx';\nimport { Button as B2 } from './button';\n"
                    "console.log(def, render(React.createElement(Button, { label: 'Go' })), Button === B2);\n"})
    r = run(["main.mjs"])
    assert _res(r) == (0, b'btn <button type="button">Go</button> true\n', b"")


@pytest.mark.parametrize("src, message", [
    ("const a = <div>\n", b"unterminated JSX element"),
    ("const a = <div a=\"1\"\n", b"unterminated JSX opening tag"),
    ("const a = <div x=5/>;\n", b"expected a JSX attribute value"),
    ("const a = <div =1/>;\n", b"expected a JSX attribute name"),
    ("const a = <div>{1</div>;\n", b"unterminated `{ \xe2\x80\xa6 }` in JSX"),
    ("const a = <div {...}>;\n", b"unterminated JSX element"),
])
def test_jsx_transform_errors(run, workdir, src, message):
    """CATCHES: malformed JSX in an entry file not reported as 'JSX transform failed for <path>: <reason>' with exit 1."""
    write_files(workdir, {"bad/e.jsx": src})
    r = run(["bad/e.jsx"])
    assert _res(r) == (1, b"", b"Uncaught JSX transform failed for bad/e.jsx: " + message + b"\n")


def test_jsx_entry_runtime_error_after_transform(run, workdir):
    """CATCHES: errors thrown by transformed JSX code not reported like other ES module entry errors (twice, exit 1)."""
    body = "const Broken = () => { throw new TypeError('render failed') };\nrender(<Broken/>);\n"
    r = _run_jsx(run, workdir, body)
    assert _res(r) == (1, b"", b"Uncaught (in promise) TypeError: render failed\nUncaught TypeError: render failed\n")


def test_jsx_scanner_skips_escapes_in_strings_templates_and_regexes(run, workdir):
    """CATCHES: a JSX scanner that ends strings/templates/regex literals at an escaped delimiter and then mistakes '<' inside them for JSX."""
    body = r"""
const s1 = 'it\'s <b>not jsx</b>';
const s2 = "q\"<i>also not</i>";
const t = `tick \` <em>still template</em> ${'x'}`;
const re = /a\/<b>[<]/;
const el = <p data-s={s1}>{s2}</p>;
console.log(s1, s2, t, re.source, re.test('a/<b><'));
console.log(render(el));
"""
    r = _run_jsx(run, workdir, body)
    assert (r.returncode, r.stderr) == (0, b"")
    assert r.stdout == golden(__file__, "escapes")


def test_jsx_comments_and_newlines_inside_tags(run, workdir):
    """CATCHES: comments inside opening tags not skipped, or multi-line attribute strings not escaped into valid JS literals."""
    body = 'const el = <div // a line comment\n  id="x" /* block\n comment */ title="line1\nline2\r\nline3"\n  >hi</div>;\n' \
           'console.log(JSON.stringify(el.props), render(el.children));\n'
    r = _run_jsx(run, workdir, body)
    assert _res(r) == (0, b'{"id":"x","title":"line1\\nline2\\r\\nline3"} hi\n', b"")


def test_jsx_closing_tag_without_opening(run, workdir):
    """CATCHES: a stray closing tag in expression position not reported as a missing element name."""
    write_files(workdir, {"stray.jsx": "const x = </div>;\n"})
    assert _res(run(["stray.jsx"])) == (1, b"", b"Uncaught JSX transform failed for stray.jsx: expected a JSX element name after `<`\n")
