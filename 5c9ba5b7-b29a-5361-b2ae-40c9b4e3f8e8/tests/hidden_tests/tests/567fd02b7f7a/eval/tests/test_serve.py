"""`lini serve`: the single-file live preview and the directory playground,
exercised over HTTP on a free local port, plus its start-up failures."""

import http.client
import json
import os
import re
import socket
import time

import pytest

from conftest import free_port, wait_for

FLOW = (
    '{ |svc::box| { fill: --teal-wash; stroke: --teal-ink } }\n'
    '|svc#api| "API"\n|svc#db| "Postgres"\napi -> db "read"\n'
)
ERROR = '|box#a| { colr: red; }\n'


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type"), resp.read()
    finally:
        conn.close()


def accepting(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


@pytest.fixture
def serve(spawn):
    """serve(args...) -> (process, port) once the server accepts connections."""

    def _serve(*args, cwd=None):
        port = free_port()
        proc = spawn(["serve", "--port", str(port), *args], cwd=cwd)
        assert wait_for(lambda: accepting(port) or proc.poll() is not None)
        assert proc.poll() is None
        return proc, port

    return _serve


def stop(proc, port):
    """Kill the server; its (stdout, stderr) with the port normalised to PORT."""
    proc.kill()
    out, err = proc.communicate(timeout=10)
    return out.decode(), err.decode().replace(f"127.0.0.1:{port}", "127.0.0.1:PORT")


def test_file_mode_page_and_banner(serve, workdir, golden):
    """CATCHES: a preview page without the file's name in its title, a wrong
    content type, or a start-up banner that names the wrong file/URL or goes to
    stdout instead of stderr."""
    (workdir / "flow.lini").write_text(FLOW)
    proc, port = serve("flow.lini")
    status, ctype, body = request(port, "GET", "/")
    assert (status, ctype) == (200, "text/html; charset=utf-8")
    assert body.decode() == golden("file_page")
    assert stop(proc, port) == ("", "lini serve: flow.lini → http://127.0.0.1:PORT/  (Ctrl-C to stop)\n")


def test_file_mode_svg_matches_cli_compile(serve, run, workdir):
    """CATCHES: the served /svg differing from what `lini FILE` writes (the preview
    must show what the file compiles to), or a wrong content type."""
    (workdir / "flow.lini").write_text(FLOW)
    proc, port = serve("flow.lini")
    status, ctype, body = request(port, "GET", "/svg")
    assert (status, ctype) == (200, "image/svg+xml")
    assert body == run(["flow.lini"]).stdout
    assert body.startswith(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="')


def test_file_mode_svg_reports_compile_error(serve, workdir):
    """CATCHES: a compile error in the previewed file crashing the server or being
    served as SVG instead of the `file:line:col: error:` text."""
    (workdir / "bad.lini").write_text(ERROR)
    proc, port = serve("bad.lini")
    status, ctype, body = request(port, "GET", "/svg")
    assert (status, ctype) == (200, "text/plain; charset=utf-8")
    assert body == b"bad.lini:1:11: error: unknown property 'colr'; did you mean 'color'?"


def test_file_mode_svg_follows_edits_and_deletion(serve, run, workdir):
    """CATCHES: a preview that caches the first compile instead of re-reading the
    file on each request, or that crashes once the file disappears."""
    src = workdir / "live.lini"
    src.write_text('|box| "one"\n')
    proc, port = serve("live.lini")
    first = request(port, "GET", "/svg")[2]
    assert first == run(["live.lini"]).stdout
    src.write_text('|box| "two"\n')
    second = request(port, "GET", "/svg")[2]
    assert second == run(["live.lini"]).stdout
    assert second != first
    src.unlink()
    status, ctype, body = request(port, "GET", "/svg")
    assert (status, ctype, body) == (200, "text/plain; charset=utf-8",
                                     b"read error: No such file or directory (os error 2)")


def test_file_mode_misc_routes(serve, workdir):
    """CATCHES: unknown routes not answered with 404 `not found`, the favicon not
    answered with an empty 204, or non-GET methods being accepted."""
    (workdir / "flow.lini").write_text(FLOW)
    proc, port = serve("flow.lini")
    assert request(port, "GET", "/nope") == (404, "text/plain", b"not found\n")
    assert request(port, "GET", "/favicon.ico") == (204, "text/plain", b"")
    assert request(port, "POST", "/svg", body=b"x") == (404, "text/plain", b"not found\n")
    assert request(port, "GET", "/svg?x=1")[1] == "image/svg+xml"


def test_file_mode_events_push_reload(serve, workdir):
    """CATCHES: a live preview whose /events stream never announces a change to
    the file (no `event: reload`), or uses a different SSE framing."""
    src = workdir / "live.lini"
    src.write_text('|box| "one"\n')
    proc, port = serve("live.lini")
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(b"GET /events HTTP/1.1\r\nHost: x\r\n\r\n")
        head = b""
        while b"\r\n\r\n" not in head:
            head += sock.recv(4096)
        assert head == (b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                        b"Cache-Control: no-cache\r\nConnection: keep-alive\r\n\r\n")
        time.sleep(0.5)
        tmp = workdir.parent / "live.tmp"
        tmp.write_text('|box| "two, longer"\n')
        os.replace(tmp, src)
        data = b""
        deadline = time.monotonic() + 8
        while b"\n\n" not in data and time.monotonic() < deadline:
            data += sock.recv(4096)
        assert data == b"event: reload\ndata: 1\n\n"
    finally:
        sock.close()


def test_file_mode_static_and_theme(serve, run, workdir, golden):
    """CATCHES: `serve --static` / `serve --theme` not applying to the served
    compile, or the theme's palette not reaching the page as `:root` variables."""
    (workdir / "flow.lini").write_text(FLOW)
    proc, port = serve("--static", "--theme", "blueprint", "flow.lini")
    assert request(port, "GET", "/svg")[2] == run(["--static", "--theme", "blueprint", "flow.lini"]).stdout
    page = request(port, "GET", "/")[2].decode()
    assert page == golden("file_page_blueprint")


def test_file_mode_theme_file_reaches_page(serve, workdir):
    """CATCHES: a theme file's `--lini-*` declarations not copied onto the preview
    page, non-lini variables leaking, or a `<` in a value not being dropped."""
    (workdir / "flow.lini").write_text(FLOW)
    (workdir / "t.css").write_text(":root {\n  --lini-bg: #102030;\n  --x-other: 1;\n  --lini-evil: </style>;\n}\n")
    proc, port = serve("--theme", "t.css", "flow.lini")
    page = request(port, "GET", "/")[2].decode()
    styles = re.findall(r"<style>:root \{[^<]*\}</style>", page)
    assert styles == ["<style>:root { --lini-bg: #102030; }</style>"]


def test_file_mode_title_is_escaped(serve, workdir):
    """CATCHES: a file name spliced into the page title without HTML escaping."""
    (workdir / "a&b<c>.lini").write_text(FLOW)
    proc, port = serve("a&b<c>.lini")
    page = request(port, "GET", "/")[2].decode()
    assert re.findall(r"<title>.*</title>", page) == ["<title>lini — a&amp;b&lt;c&gt;.lini</title>"]


def playground(workdir):
    (workdir / "a.lini").write_text(FLOW)
    (workdir / "bad.lini").write_text(ERROR)
    (workdir / "sub" / "deeper").mkdir(parents=True)
    (workdir / "sub" / "z.lini").write_text('|box| "z"\n')
    (workdir / "sub" / "deeper" / "m.lini").write_text('|oval| "m"\n')
    (workdir / ".hidden").mkdir()
    (workdir / ".hidden" / "secret.lini").write_text('|box| "secret"\n')
    (workdir / "notes.txt").write_text("not lini\n")
    (workdir / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>\n')


def test_dir_mode_page_and_banner(serve, workdir, tmp_path, golden):
    """CATCHES: a directory target not opening the playground page, or a banner
    that does not announce the playground with its directory."""
    playground(workdir)
    proc, port = serve(".")
    status, ctype, body = request(port, "GET", "/")
    assert (status, ctype) == (200, "text/html; charset=utf-8")
    assert body.decode() == golden("dir_page")
    assert stop(proc, port) == ("", "lini playground: . → http://127.0.0.1:PORT/  (Ctrl-C to stop)\n")


def test_dir_mode_defaults_to_current_directory(serve, workdir):
    """CATCHES: `lini serve` with no path not defaulting to the current directory
    (the playground), e.g. erroring or serving nothing."""
    playground(workdir)
    proc, port = serve()
    assert request(port, "GET", "/api/files")[2] == b"a.lini\nbad.lini\nsub/deeper/m.lini\nsub/z.lini"
    banner = stop(proc, port)
    assert banner == ("", f"lini playground: {workdir.resolve()} → http://127.0.0.1:PORT/  (Ctrl-C to stop)\n")


def test_dir_mode_lists_lini_files(serve, workdir):
    """CATCHES: a file list that is unsorted, includes non-.lini files or hidden
    directories, misses nested files, or uses OS path separators."""
    playground(workdir)
    proc, port = serve(".")
    assert request(port, "GET", "/api/files") == (
        200, "text/plain; charset=utf-8", b"a.lini\nbad.lini\nsub/deeper/m.lini\nsub/z.lini")


def test_dir_mode_reads_files(serve, workdir):
    """CATCHES: /api/file serving the wrong bytes or content type, accepting
    traversal or absolute paths, or answering a missing parameter/file wrongly."""
    playground(workdir)
    proc, port = serve(".")
    assert request(port, "GET", "/api/file?path=sub%2Fz.lini") == (
        200, "text/plain; charset=utf-8", b'|box| "z"\n')
    assert request(port, "GET", "/api/file?path=logo.svg") == (
        200, "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>\n')
    assert request(port, "GET", "/api/file?path=notes.txt") == (200, "application/octet-stream", b"not lini\n")
    assert request(port, "GET", "/api/file") == (400, "text/plain", b"missing path\n")
    assert request(port, "GET", "/api/file?path=../x.lini") == (400, "text/plain", b"invalid path\n")
    assert request(port, "GET", "/api/file?path=%2Fetc%2Fhostname") == (400, "text/plain", b"invalid path\n")
    assert request(port, "GET", "/api/file?path=nope.lini") == (400, "text/plain", b"invalid path\n")
    assert request(port, "GET", "/api/file?path=sub") == (404, "text/plain", b"not found\n")


def test_dir_mode_compile_ok(serve, run, workdir, golden):
    """CATCHES: the playground compile endpoint returning a different JSON shape,
    an SVG that differs from the CLI's, or wrong formatted/desugared payloads."""
    playground(workdir)
    proc, port = serve(".")
    status, ctype, body = request(port, "POST", "/compile?path=a.lini", body=FLOW.encode())
    assert (status, ctype) == (200, "application/json; charset=utf-8")
    assert body.decode() == golden("compile_ok")


def test_dir_mode_compile_error_and_warnings(serve, workdir, golden):
    """CATCHES: compile errors not reported as `ok:false` with the message under
    the `playground.lini` name, or warnings missing from `diagnostics`."""
    playground(workdir)
    proc, port = serve(".")
    err = request(port, "POST", "/compile", body=ERROR.encode())[2].decode()
    assert err == golden("compile_error")
    warn_src = '{ .hot { fill: red; } }\n|box#a| "A"\n'
    warn = request(port, "POST", "/compile?path=sub%2Fz.lini", body=warn_src.encode())[2].decode()
    assert warn == golden("compile_warning")
    unparsable = request(port, "POST", "/compile", body=b'|box| "open\n')[2].decode()
    assert unparsable == golden("compile_unparsable")


def test_dir_mode_save(serve, workdir):
    """CATCHES: /save writing outside the root, creating non-.lini files, or not
    overwriting an existing .lini file with the posted body."""
    playground(workdir)
    proc, port = serve(".")
    json_ct = "application/json; charset=utf-8"
    assert request(port, "POST", "/save?path=sub%2Fz.lini", body=b'|box| "saved"\n') == (200, json_ct, b'{"ok":true}')
    assert (workdir / "sub" / "z.lini").read_text() == '|box| "saved"\n'
    assert request(port, "POST", "/save?path=notes.txt", body=b"x") == (400, json_ct, b'{"ok":false,"error":"invalid path"}')
    assert (workdir / "notes.txt").read_text() == "not lini\n"
    assert request(port, "POST", "/save", body=b"x") == (400, json_ct, b'{"ok":false,"error":"missing path"}')
    assert request(port, "POST", "/save?path=..%2Fout.lini", body=b"x") == (400, json_ct, b'{"ok":false,"error":"invalid path"}')
    assert not (workdir.parent / "out.lini").exists()
    assert request(port, "GET", "/save?path=a.lini") == (404, "text/plain", b"not found\n")


def test_port_already_in_use(run, workdir):
    """CATCHES: a server that silently picks another port, hangs, or exits with a
    code other than 2 when its port is taken."""
    (workdir / "flow.lini").write_text(FLOW)
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        r = run(["serve", "--port", str(port), "flow.lini"])
    assert r.returncode == 2
    assert r.stdout == b""
    assert r.stderr == b"error: Address already in use (os error 98)\n"


LOGO = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect id="r" width="4" height="4"/></svg>\n'
IMAGE_SRC = '|image| { src: "%s"; width: 20; height: 20; }\n'


def test_file_mode_assets_confined_to_file_directory(serve, run, workdir):
    """CATCHES: a served preview reading images outside the file's own directory
    (the served root), or not resolving an in-root image relative to the file."""
    (workdir / "site" / "img").mkdir(parents=True)
    (workdir / "site" / "img" / "logo.svg").write_text(LOGO)
    (workdir / "outside.svg").write_text(LOGO)
    (workdir / "site" / "inside.lini").write_text(IMAGE_SRC % "img/logo.svg")
    (workdir / "site" / "escape.lini").write_text(IMAGE_SRC % "../outside.svg")
    proc, port = serve("site/inside.lini")
    assert request(port, "GET", "/svg") == (200, "image/svg+xml", run(["site/inside.lini"]).stdout)
    proc2, port2 = serve("site/escape.lini")
    assert request(port2, "GET", "/svg") == (
        200, "text/plain; charset=utf-8",
        b"site/escape.lini:1:11: error: '../outside.svg' resolves outside the served root")
    # the plain CLI compile of the same file is unbounded
    assert run(["site/escape.lini"]).returncode == 0


def test_dir_mode_assets_resolve_per_file_and_stay_in_root(serve, run, workdir):
    """CATCHES: the playground compile resolving images against the wrong
    directory (it uses the edited file's), or letting a path escape the root."""
    (workdir / "root" / "sub").mkdir(parents=True)
    (workdir / "root" / "sub" / "logo.svg").write_text(LOGO)
    (workdir / "root" / "sub" / "page.lini").write_text(IMAGE_SRC % "logo.svg")
    (workdir / "secret.svg").write_text(LOGO)
    proc, port = serve("root")
    ok = request(port, "POST", "/compile?path=sub%2Fpage.lini", body=(IMAGE_SRC % "logo.svg").encode())[2]
    doc = json.loads(ok)
    assert sorted(doc) == ["desugared", "diagnostics", "formatted", "ok", "svg"]
    assert (doc["ok"], doc["diagnostics"]) == (True, [])
    assert doc["svg"] == run(["root/sub/page.lini"]).stdout.decode()
    missing = request(port, "POST", "/compile", body=(IMAGE_SRC % "logo.svg").encode())[2]
    assert missing.startswith(b'{"ok":false,"error":"playground.lini:1:11: error: cannot read image \'logo.svg\' '
                              b'\xe2\x80\x94 no such file","diagnostics":[],"formatted":')
    escape = request(port, "POST", "/compile?path=sub%2Fpage.lini", body=(IMAGE_SRC % "../../secret.svg").encode())[2]
    assert escape.startswith(b'{"ok":false,"error":"playground.lini:1:11: error: '
                             b'\'../../secret.svg\' resolves outside the served root","diagnostics":[]')


def test_dir_mode_raster_content_types(serve, workdir):
    """CATCHES: /api/file serving raster assets with a wrong Content-Type."""
    for name in ("a.png", "b.jpg", "c.jpeg", "d.gif", "e.webp"):
        (workdir / name).write_bytes(b"bytes of " + name.encode())
    proc, port = serve(".")
    got = [request(port, "GET", f"/api/file?path={n}")[:2] for n in ("a.png", "b.jpg", "c.jpeg", "d.gif", "e.webp")]
    assert got == [(200, "image/png"), (200, "image/jpeg"), (200, "image/jpeg"), (200, "image/gif"), (200, "image/webp")]
    assert request(port, "GET", "/api/file?path=d.gif")[2] == b"bytes of d.gif"


def test_serve_non_lini_file_is_file_mode(serve, workdir):
    """CATCHES: `lini serve FILE` refusing a file without the .lini extension or
    treating it as a playground directory."""
    (workdir / "diagram.txt").write_text('|box| "plain text extension"\n')
    proc, port = serve("diagram.txt")
    status, ctype, body = request(port, "GET", "/svg")
    assert (status, ctype) == (200, "image/svg+xml")
    assert b"plain text extension</text>" in body
    assert stop(proc, port) == ("", "lini serve: diagram.txt → http://127.0.0.1:PORT/  (Ctrl-C to stop)\n")
