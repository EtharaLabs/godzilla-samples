"""Namespaces derived from file names (the README's table), as inspect lists them and as the naming rule spells and
matches them."""

from conftest import assert_golden, changes, gomod, snapshot, transcript, write_files

# Each file declares one function, so each is a namespace of its own.
NAMES = [
    "user_repository.go", "user_repository_test.go", "parser_linux.go", "parser_test_linux.go", "parser_linux.pb.go",
    "parser.x_linux.go", "user_id.go", "user_ids.go", "parse_json.go", "foo-bar.go", "Foo.go", "HTTPServer.go",
    "URLs.go", "IPv4.go", "OAuth.go", "2fa_auth.go", "用户.go", "_skipped.go", "range.go",
]


def test_namespaces_of_file_names(run, workdir):
    """CATCHES: a file name turned into the wrong namespace: build suffixes counted only before the first dot, a test
    sharing its subject's namespace, initialisms and their plurals spelled as Go spells them, separators and PascalCase
    lowered to lowerCamelCase, and a namespace that cannot be a prefix still a namespace (files starting with _ are not
    read by the go command at all)."""
    files = {"go.mod": gomod("example.com/n")}
    for i, name in enumerate(NAMES):
        files[name] = f"package n\n\nfunc f{i}() int {{ return {i} }}\n"
    write_files(workdir, files)
    assert_golden(transcript(run(["inspect", "-format=json", "."]), workdir), __file__, "file_names")


def test_qualify_messages_spell_initialisms(run, workdir):
    """CATCHES: a rename suggestion that spells an initialism namespace or name the way Go would not (userId, httpserver),
    or that does not keep an exported name exported under rules.naming.exported."""
    write_files(workdir, {
        "go.mod": gomod("example.com/n"),
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    exported: true\n",
        "user_id.go": "package n\n\nfunc id() int { return 1 }\n\nfunc Load() int { return id() }\n",
        "HTTPServer.go": "package n\n\nfunc serve() int { return 2 }\n\nfunc ids() int { return serve() }\n",
        "URLs.go": "package n\n\nfunc parse() int { return 3 }\n\nfunc loadURLs() int { return parse() }\n\nfunc urlsCache() int { return 0 }\n",
        "IPv4.go": "package n\n\nfunc mask() int { return 4 }\n",
        "OAuth.go": "package n\n\nfunc token() int { return 5 }\n",
    })
    before = snapshot(workdir)
    out = transcript(run(["./..."]), workdir)
    out += "\n=== -fix\n" + transcript(run(["-fix", "./..."]), workdir) + changes(before, workdir)
    assert_golden(out, __file__, "initialisms")


def test_vocabulary_words_and_inflections(run, workdir):
    """CATCHES: a vocabulary word matched without the left word boundary (pinwheel), not matched with a free right
    edge (wheelDelta), matched when the name is shorter than the word, or the generated inflections (storing,
    applies, applied) not accepted while a merely similar stem (story) is."""
    write_files(workdir, {
        "go.mod": gomod("example.com/n"),
        ".declscope.yaml": "rules:\n  naming:\n    qualify: always\n    vocabulary:\n      mouse: [wheel, accelerator]\n",
        "mouse.go": "package n\n\nfunc wheelDelta() {}\n\nfunc pinwheel() {}\n\nfunc accel() {}\n\nfunc mouseMove() {}\n",
        "store.go": "package n\n\nfunc storingItems() {}\n\nfunc story() {}\n",
        "apply.go": "package n\n\nfunc appliesTo() {}\n\nfunc appliedAt() {}\n\nfunc applying() {}\n",
        "tracing.go": "package n\n\nfunc traceValue() {}\n",
    })
    assert_golden(transcript(run(["./..."]), workdir), __file__, "vocabulary")
