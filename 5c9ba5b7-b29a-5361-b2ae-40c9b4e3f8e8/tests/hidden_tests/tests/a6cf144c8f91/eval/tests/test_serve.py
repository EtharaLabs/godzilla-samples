"""`lini serve`: the file preview (/, /svg, /events) and the directory
playground (/api/files, /api/file, /compile, /save) over loopback HTTP.

The server runs under the `run` fixture until its timeout stops it; requests
go over raw sockets so status line, headers and body are compared exactly."""

import re
import socket
import subprocess
import threading
import time

from conftest import Goldens, outcome, write_files

G = Goldens(__file__)

HELLO = '|box#a| "Hello"\n|box#b| "World"\na -> b\n'


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """`lini serve ARGS --port N` in a background thread for `seconds`."""

    def __init__(self, run, args, seconds=4.0):
        self.port = free_port()
        self.stderr = b""
        self.thread = threading.Thread(target=self._run, args=(run, [*args, "--port", str(self.port)], seconds))
        self.thread.start()
        deadline = time.monotonic() + seconds - 0.5
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)

    def _run(self, run, args, seconds):
        try:
            run(["serve", *args], timeout=seconds)
        except subprocess.TimeoutExpired as stopped:
            self.stderr = stopped.stderr or b""

    def request(self, method, path, body=b""):
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as s:
            s.sendall(f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
            data = b""
            while chunk := s.recv(65536):
                data += chunk
        return data.decode("utf-8")

    def banner(self):
        self.thread.join()
        return re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:PORT", self.stderr.decode())


def test_serve_missing_path(run):
    """CATCHES: serve on a nonexistent path not failing fast with exit 2 and its message."""
    r = run(["serve", "nope.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: nope.lini: no such file or directory\n"


def test_serve_bad_theme(run, workdir):
    """CATCHES: serve accepting an unknown --theme instead of failing like a compile (exit 2, same message)."""
    write_files(workdir, {"h.lini": HELLO})
    r = run(["serve", "--theme", "nosuch", "h.lini"])
    assert outcome(r) == "exit: 2\n--- stdout ---\n--- stderr ---\nerror: theme 'nosuch': not a built-in (try: default, light, dark, high-contrast, blueprint), and reading it as a file failed: No such file or directory (os error 2)\n"


def test_serve_file_routes(run, workdir):
    """CATCHES: a file preview serving a different page, a /svg that differs from the CLI compile, wrong 204/404 routes, or a different banner."""
    write_files(workdir, {"h.lini": HELLO})
    srv = Server(run, ["h.lini"])
    page = srv.request("GET", "/")
    svg = srv.request("GET", "/svg")
    fav = srv.request("GET", "/favicon.ico")
    missing = srv.request("GET", "/nope")
    assert page == G("file_page")
    assert svg == G("file_svg")
    assert fav == "HTTP/1.1 204 No Content\r\nContent-Type: text/plain\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    assert missing == "HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\nContent-Length: 10\r\nConnection: close\r\n\r\nnot found\n"
    assert srv.banner() == "lini serve: h.lini → http://127.0.0.1:PORT/  (Ctrl-C to stop)\n"
    cli = run(["h.lini"]).stdout.decode()
    assert svg.split("\r\n\r\n", 1)[1] == cli


def test_serve_file_compile_error_and_static_theme(run, workdir):
    """CATCHES: /svg not returning the located error as plain text, or serve ignoring --static/--theme for its compiles and page."""
    write_files(workdir, {"bad.lini": '|box| { colr: red; }\n', "ok.lini": HELLO})
    srv = Server(run, ["--static", "--theme", "blueprint", "bad.lini"])
    err = srv.request("GET", "/svg")
    page = srv.request("GET", "/")
    srv.banner()
    assert err == G("file_error")
    assert page == G("file_page_themed")


def test_serve_file_live_reload_event(run, workdir):
    """CATCHES: a preview whose /events stream does not push 'event: reload' after the watched file changes."""
    write_files(workdir, {"h.lini": HELLO})
    srv = Server(run, ["h.lini"], seconds=5.0)
    with socket.create_connection(("127.0.0.1", srv.port), timeout=3) as s:
        s.sendall(b"GET /events HTTP/1.1\r\nHost: localhost\r\n\r\n")
        data = b""
        while b"\r\n\r\n" not in data and (chunk := s.recv(4096)):
            data += chunk
        time.sleep(0.5)
        (workdir / "h.lini").write_text(HELLO + 'b -> c "added"\n')
        while b"event: reload" not in data and (chunk := s.recv(4096)):
            data += chunk
    srv.banner()
    assert data.decode() == "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-cache\r\nConnection: keep-alive\r\n\r\nevent: reload\ndata: 1\n\n"


def test_serve_playground_routes(run, workdir):
    """CATCHES: a playground that lists files unsorted or includes hidden dirs/non-.lini files, reads outside its root, or serves the wrong page."""
    write_files(workdir, {"site/b.lini": HELLO, "site/a.lini": '|oval| "o"\n', "site/sub/c.lini": "|box|\n",
                          "site/.git/x.lini": "|box|\n", "site/notes.txt": "x\n", "secret.lini": "|box|\n"})
    srv = Server(run, ["site"])
    listing = srv.request("GET", "/api/files")
    one = srv.request("GET", "/api/file?path=sub%2Fc.lini")
    txt = srv.request("GET", "/api/file?path=notes.txt")
    escape = srv.request("GET", "/api/file?path=../secret.lini")
    absolute = srv.request("GET", "/api/file?path=/etc/hostname")
    nopath = srv.request("GET", "/api/file")
    page = srv.request("GET", "/")
    assert srv.banner() == "lini playground: site → http://127.0.0.1:PORT/  (Ctrl-C to stop)\n"
    assert listing == "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: 24\r\nConnection: close\r\n\r\na.lini\nb.lini\nsub/c.lini"
    assert one == "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: 6\r\nConnection: close\r\n\r\n|box|\n"
    assert txt == "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: 2\r\nConnection: close\r\n\r\nx\n"
    assert escape == "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nContent-Length: 13\r\nConnection: close\r\n\r\ninvalid path\n"
    assert absolute == escape
    assert nopath == "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\nContent-Length: 13\r\nConnection: close\r\n\r\nmissing path\n"
    assert page == G("playground_page")


def test_serve_playground_compile(run, workdir):
    """CATCHES: POST /compile returning a different JSON (svg, diagnostics, formatted and desugared panes), or a different error document."""
    write_files(workdir, {"site/a.lini": HELLO})
    srv = Server(run, ["site"])
    ok = srv.request("POST", "/compile?path=a.lini", b'{ .hot { fill: red; } }\n|box#x|{fill:--teal}\n')
    bad = srv.request("POST", "/compile", b'|box| "x" { colr: red; }\n')
    unparsable = srv.request("POST", "/compile", b'|box| "open\n')
    srv.banner()
    assert ok == G("compile_ok")
    assert bad == G("compile_error")
    assert unparsable == G("compile_unparsable")


def test_serve_playground_save(run, workdir):
    """CATCHES: POST /save that creates new files, writes non-.lini files, escapes the root, or fails to overwrite a listed file."""
    write_files(workdir, {"site/a.lini": HELLO, "site/n.txt": "keep\n"})
    srv = Server(run, ["site"])
    saved = srv.request("POST", "/save?path=a.lini", b'|oval| "saved"\n')
    created = srv.request("POST", "/save?path=new.lini", b"|box|\n")
    wrong_ext = srv.request("POST", "/save?path=n.txt", b"overwrite\n")
    nopath = srv.request("POST", "/save", b"|box|\n")
    srv.banner()
    assert saved == 'HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}'
    assert created == 'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: 35\r\nConnection: close\r\n\r\n{"ok":false,"error":"invalid path"}'
    assert wrong_ext == created
    assert nopath == 'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: 35\r\nConnection: close\r\n\r\n{"ok":false,"error":"missing path"}'
    assert (workdir / "site/a.lini").read_text() == '|oval| "saved"\n'
    assert (workdir / "site/n.txt").read_text() == "keep\n"
    assert sorted(p.name for p in (workdir / "site").iterdir()) == ["a.lini", "n.txt"]
