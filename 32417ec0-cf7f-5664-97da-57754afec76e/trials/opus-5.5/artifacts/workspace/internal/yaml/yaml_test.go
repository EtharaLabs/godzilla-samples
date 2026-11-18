package yaml

import (
	"fmt"
	"strings"
	"testing"
	"unicode/utf16"
)

// The expectations in this file were checked against the reference: the
// original declscope binary, which parses its configuration with
// gopkg.in/yaml.v3. Error messages are compared exactly; values, tags and
// lines are those the reference reported for the same input.

func TestSyntaxErrors(t *testing.T) {
	tests := []struct{ in, want string }{
		{"rules:\n\tfoo: 1\n", "yaml: line 2: found character that cannot start any token"},
		{": bad\n", "yaml: did not find expected key"},
		{"key: value: other\n", "yaml: mapping values are not allowed in this context"},
		{"rules:\n  naming:\n      qualify: always\n    exported: true\n", "yaml: line 1: did not find expected key"},
		{"filter:\n  only: [a.go\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"filter:\n  only: \"a.go\n", "yaml: line 2: found unexpected end of stream"},
		{"...\n", "yaml: did not find expected node content"},
		{"\t", "yaml: found character that cannot start any token"},
		{"\t\n", "yaml: found character that cannot start any token"},
		{"...", "yaml: did not find expected node content"},
		{"... # c\n", "yaml: did not find expected node content"},
		{"%YAML 1.1\n", "yaml: line 1: did not find expected <document start>"},
		{"rules:\n  boundary: \"\\/\"\n", "yaml: line 2: found unknown escape character"},
		{"rules:\n  boundary: a\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: a\n\n  b\n", "yaml: line 4: could not find expected ':'"},
		{"rules:\n  boundary: a: b\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"rules:\n  boundary: [a\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"rules:\n  boundary: {a\n", "yaml: line 1: did not find expected ',' or '}'"},
		{"rules:\n  boundary: %a\n", "yaml: line 2: found character that cannot start any token"},
		{"rules:\n  boundary: @a\n", "yaml: line 2: found character that cannot start any token"},
		{"rules:\n  boundary: `a\n", "yaml: line 2: found character that cannot start any token"},
		{"rules:\n  boundary: |\n  a\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |-\n  a\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |+\n  a\n  b\n\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |\n  a\n\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |\n\n  a\n", "yaml: line 4: could not find expected ':'"},
		{"rules:\n  boundary: |\n  a\n   b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |2\n   a\n", "yaml: line 1: did not find expected key"},
		{"rules:\n  boundary: |+2\n   a\n\n", "yaml: line 1: did not find expected key"},
		{"rules:\n  boundary: |2-\n   a\n", "yaml: line 1: did not find expected key"},
		{"rules:\n  boundary: |-2\n   a\n", "yaml: line 1: did not find expected key"},
		{"rules:\n  boundary: >\n  a\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >\n  a\n\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >\n  a\n   b\n  c\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >-\n  a\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >+\n  a\n\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >\n\n  a\n", "yaml: line 4: could not find expected ':'"},
		{"rules:\n  boundary: >\n  a\n  \n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >\n   a\n  b\n", "yaml: line 4: could not find expected ':'"},
		{"rules:\n  boundary: | # c\n  a\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |#c\n  a\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |\n  a\n# c\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |\n  a\n  # c\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |\n  a\n\n\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |+\n  a\n\n\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |-\n  a\n\n\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >\n  a\n  b\n\n  c\n   d\n  e\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: a\r\n  b\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: |\r\n  a\r\n  b\r\n", "yaml: line 3: could not find expected ':'"},
		{"rules:\n  boundary: >\r\n  a\r\n  b\r\n", "yaml: line 3: could not find expected ':'"},
		{"a: 1\n\t\nb: 2\n", "yaml: line 2: found a tab character that violates indentation"},
		{"a: 1\n b: 2\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a: 1\n  b: 2\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a:\n  b: 1\n c: 2\n", "yaml: line 2: did not find expected key"},
		{"a:\n  b: 1\n   c: 2\n", "yaml: line 3: mapping values are not allowed in this context"},
		{"a:\n  b:\n    c: 1\n   d: 2\n", "yaml: line 1: did not find expected key"},
		{"a:\n  b: 1\n    c: 2\n", "yaml: line 3: mapping values are not allowed in this context"},
		{"a:\n  - b\n - c\n", "yaml: line 2: did not find expected key"},
		{"a: 1\nb\n", "yaml: line 2: could not find expected ':'"},
		{"a: 1\nb\nc: 2\n", "yaml: line 2: could not find expected ':'"},
		{"- a\nb\n", "yaml: line 2: could not find expected ':'"},
		{"- a\nb: 1\n", "yaml: line 1: did not find expected '-' indicator"},
		{"a: 1\n- b\n", "yaml: line 1: did not find expected key"},
		{"a:\n  b: 1\n- c\n", "yaml: line 2: did not find expected key"},
		{"a: b\n  c: d\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a: b\nc\n", "yaml: line 2: could not find expected ':'"},
		{"a\nb: c\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a\n b: c\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a:\n    b: 1\n  c: 2\n", "yaml: line 2: did not find expected key"},
		{"x:\n  a: 1\n  b: 2\n c: 3\n", "yaml: line 3: did not find expected key"},
		{"x:\n  y:\n    a: 1\n  b: 2\n   c: 3\n", "yaml: line 5: mapping values are not allowed in this context"},
		{"- - a\n  - b\n - c\n", "yaml: line 2: did not find expected '-' indicator"},
		{"\ta: b\n", "yaml: found character that cannot start any token"},
		{"a:\n\tb: c\n", "yaml: line 2: found character that cannot start any token"},
		{"a:\n \tb: c\n", "yaml: line 2: found character that cannot start any token"},
		{"a:\n\t- b\n", "yaml: line 2: found character that cannot start any token"},
		{"- \tb\n", "yaml: found character that cannot start any token"},
		{"-\tb\n", "yaml: found character that cannot start any token"},
		{"? \tb\n", "yaml: found character that cannot start any token"},
		{"a: b\n\t\n", "yaml: line 2: found a tab character that violates indentation"},
		{"a: b\n\t# c\n", "yaml: line 2: found a tab character that violates indentation"},
		{"a: |\n\tb\n", "yaml: line 2: found a tab character where an indentation space is expected"},
		{"a: |\n  b\n\tc\n", "yaml: line 3: found a tab character where an indentation space is expected"},
		{"a: |\n \tb\n", "yaml: line 2: found a tab character where an indentation space is expected"},
		{"a: >\n  b\n \t c\n", "yaml: line 3: found a tab character where an indentation space is expected"},
		{"a:\n  b\n\tc\n", "yaml: line 2: found a tab character that violates indentation"},
		{"a: b\n\tc\n", "yaml: line 2: found a tab character that violates indentation"},
		{"\t- a\n", "yaml: found character that cannot start any token"},
		{"- a\n\t- b\n", "yaml: line 2: found a tab character that violates indentation"},
		{"? a\n:\tb\n", "yaml: line 2: found character that cannot start any token"},
		{"?\ta\n", "yaml: found character that cannot start any token"},
		{"-\t# c\n", "yaml: found character that cannot start any token"},
		{"-\t\n", "yaml: found character that cannot start any token"},
		{"key:\n\t\tvalue\n", "yaml: line 2: found character that cannot start any token"},
		{"[a\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"[a", "yaml: line 1: did not find expected ',' or ']'"},
		{"[a,\n", "yaml: line 1: did not find expected node content"},
		{"[a, b\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"{a\n", "yaml: line 1: did not find expected ',' or '}'"},
		{"{a: 1\n", "yaml: line 1: did not find expected ',' or '}'"},
		{"{a: 1,\n", "yaml: line 1: did not find expected node content"},
		{"]\n", "yaml: did not find expected node content"},
		{"}\n", "yaml: did not find expected node content"},
		{"[\n", "yaml: line 1: did not find expected node content"},
		{"{\n", "yaml: line 1: did not find expected node content"},
		{"a: [b\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"a: [b,\nc: d\n", "yaml: line 2: did not find expected ',' or ']'"},
		{"a:\n  b: [c\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"a:\n  b: {c\n", "yaml: line 1: did not find expected ',' or '}'"},
		{"[a, - b]\n", "yaml: did not find expected node content"},
		{"[- a]\n", "yaml: did not find expected node content"},
		{"{- a}\n", "yaml: did not find expected node content"},
		{"[,]\n", "yaml: did not find expected node content"},
		{"[a,,b]\n", "yaml: did not find expected node content"},
		{"{a: 1,,b: 2}\n", "yaml: did not find expected node content"},
		{"{,}\n", "yaml: did not find expected node content"},
		{"{a\n: b}\n", "yaml: line 1: did not find expected ',' or '}'"},
		{"{\"a\"\n: b}\n", "yaml: line 1: did not find expected ',' or '}'"},
		{"[:a]\n", "yaml: did not find expected node content"},
		{"{:a}\n", "yaml: did not find expected node content"},
		{"{: a}\n", "yaml: did not find expected node content"},
		{"[a?b]\n", "yaml: did not find expected ',' or ']'"},
		{"[a?]\n", "yaml: did not find expected ',' or ']'"},
		{"[?]\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"[a\n---\n]\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"[a\n...\n]\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"'a\n---\n'\n", "yaml: line 2: found unexpected document indicator"},
		{"\"a\n...\n\"\n", "yaml: line 2: found unexpected document indicator"},
		{"a: 'b\n---\nc'\n", "yaml: line 2: found unexpected document indicator"},
		{"\"a\n", "yaml: line 2: found unexpected end of stream"},
		{"'a\n", "yaml: line 2: found unexpected end of stream"},
		{"\"a", "yaml: found unexpected end of stream"},
		{"'a", "yaml: found unexpected end of stream"},
		{"a: \"b\n", "yaml: line 2: found unexpected end of stream"},
		{"a: 'b\n", "yaml: line 2: found unexpected end of stream"},
		{"a:\n  b: \"c\n", "yaml: line 2: found unexpected end of stream"},
		{"a:\n  b: 'c\n\n\n", "yaml: line 2: found unexpected end of stream"},
		{"\"a\": b: c\n", "yaml: mapping values are not allowed in this context"},
		{"\"\\q\"\n", "yaml: found unknown escape character"},
		{"\"\\x\"\n", "yaml: did not find expected hexdecimal number"},
		{"\"\\x4\"\n", "yaml: did not find expected hexdecimal number"},
		{"\"\\x4g\"\n", "yaml: did not find expected hexdecimal number"},
		{"\"\\u12\"\n", "yaml: did not find expected hexdecimal number"},
		{"\"\\ud800\"\n", "yaml: found invalid Unicode character escape code"},
		{"\"\\U00110000\"\n", "yaml: found invalid Unicode character escape code"},
		{"a: \"\\q\"\n", "yaml: found unknown escape character"},
		{"a:\n  b: \"\\q\"\n", "yaml: line 2: found unknown escape character"},
		{"a:\n  b: \"x\n\n  \\q\"\n", "yaml: line 2: found unknown escape character"},
		{"\"x\n\n\\q\"\n", "yaml: line 3: found unknown escape character"},
		{"\"\\", "yaml: found unknown escape character"},
		{"\"\\\n", "yaml: line 2: found unexpected end of stream"},
		{"'''\n", "yaml: line 2: found unexpected end of stream"},
		{"a: -\n", "yaml: block sequence entries are not allowed in this context"},
		{"a: - b\n", "yaml: block sequence entries are not allowed in this context"},
		{":\n", "yaml: did not find expected key"},
		{": \n", "yaml: did not find expected key"},
		{"a: :\n", "yaml: mapping values are not allowed in this context"},
		{"a: : b\n", "yaml: mapping values are not allowed in this context"},
		{": a\n: b\n", "yaml: did not find expected key"},
		{"a:\n  : b\n", "yaml: line 1: did not find expected key"},
		{"- : a\n", "yaml: did not find expected key"},
		{"@a\n", "yaml: found character that cannot start any token"},
		{"`a\n", "yaml: found character that cannot start any token"},
		{"%a\n", "yaml: found unknown directive name"},
		{"a: @b\n", "yaml: found character that cannot start any token"},
		{"a: `b\n", "yaml: found character that cannot start any token"},
		{"a: %b\n", "yaml: found character that cannot start any token"},
		{"|a\n", "yaml: did not find expected comment or line break"},
		{">a\n", "yaml: did not find expected comment or line break"},
		{"a: |a\n", "yaml: did not find expected comment or line break"},
		{"a: >-a\n", "yaml: did not find expected comment or line break"},
		{"a: |++\n", "yaml: did not find expected comment or line break"},
		{"a: |12\n", "yaml: did not find expected comment or line break"},
		{"a: |0\n", "yaml: found an indentation indicator equal to 0"},
		{"a: |-0\n", "yaml: found an indentation indicator equal to 0"},
		{"a: | x\n", "yaml: did not find expected comment or line break"},
		{"a: |9\n  b\n", "yaml: line 1: did not find expected key"},
		{"a: b: c\n", "yaml: mapping values are not allowed in this context"},
		{"a: b:\n", "yaml: mapping values are not allowed in this context"},
		{"- a: b: c\n", "yaml: mapping values are not allowed in this context"},
		{"a:\n  b: c: d\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a: 'b': c\n", "yaml: mapping values are not allowed in this context"},
		{"a: [b]: c\n", "yaml: mapping values are not allowed in this context"},
		{"- a\n- b: c: d\n", "yaml: line 2: mapping values are not allowed in this context"},
		{"a: *x\n", "yaml: unknown anchor 'x' referenced"},
		{"*x\n", "yaml: unknown anchor 'x' referenced"},
		{"& x\n", "yaml: did not find expected alphabetic or numeric character"},
		{"&\n", "yaml: did not find expected alphabetic or numeric character"},
		{"a: &\n", "yaml: did not find expected alphabetic or numeric character"},
		{"a: *\n", "yaml: did not find expected alphabetic or numeric character"},
		{"a: &x.y 1\n", "yaml: did not find expected alphabetic or numeric character"},
		{"a: *x.y\n", "yaml: did not find expected alphabetic or numeric character"},
		{"a: &a &b c\n", "yaml: did not find expected key"},
		{"a: !!str !!int c\n", "yaml: did not find expected key"},
		{"a: !e!x b\n", "yaml: found undefined tag handle"},
		{"a: !<> b\n", "yaml: did not find expected tag URI"},
		{"a: !<x b\n", "yaml: did not find the expected '>'"},
		{"a: !! b\n", "yaml: did not find expected tag URI"},
		{"a: !a! b\n", "yaml: did not find expected tag URI"},
		{"a: !a!b c\n", "yaml: found undefined tag handle"},
		{"a: !x! b\n", "yaml: did not find expected tag URI"},
		{"a: !%4 b\n", "yaml: did not find URI escaped octet"},
		{"a: !%zz b\n", "yaml: did not find URI escaped octet"},
		{"a: !%e9 b\n", "yaml: did not find URI escaped octet"},
		{"a: !%c3%41 b\n", "yaml: found an incorrect trailing UTF-8 octet"},
		{"[!x,a]\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"a: !x#y b\n", "yaml: did not find expected whitespace or line break"},
		{"%TAG !e! tag:x,2000:\n%TAG !e! tag:y,2000:\n---\na: 1\n", "yaml: line 1: found duplicate %TAG directive"},
		{"%TAG e! x\n---\na\n", "yaml: did not find expected '!'"},
		{"%TAG !e x\n---\na\n", "yaml: did not find expected '!'"},
		{"%TAG !e!\n---\na\n", "yaml: did not find expected whitespace"},
		{"%TAG !e!x\n---\na\n", "yaml: did not find expected whitespace"},
		{"%YAML 1.1\n%YAML 1.1\n---\na\n", "yaml: line 1: found duplicate %YAML directive"},
		{"%YAML 1.2\n---\na\n", "yaml: found incompatible YAML document"},
		{"%YAML 2.0\n---\na\n", "yaml: found incompatible YAML document"},
		{"%YAML 1\n---\na\n", "yaml: did not find expected digit or '.' character"},
		{"%YAML 1.\n---\na\n", "yaml: did not find expected version number"},
		{"%YAML 123.1\n---\na\n", "yaml: found extremely long version number"},
		{"%YAML 1.1 x\n---\na\n", "yaml: did not find expected comment or line break"},
		{"%YAMLx 1.1\n---\na\n", "yaml: found unknown directive name"},
		{"%FOO bar\n---\na\n", "yaml: found unknown directive name"},
		{"%\n---\na\n", "yaml: could not find expected directive name"},
		{"% YAML\n---\na\n", "yaml: could not find expected directive name"},
		{" %YAML 1.1\n", "yaml: found character that cannot start any token"},
		{"a: 1\n---\n@\n", "yaml: line 3: found character that cannot start any token"},
		{"a: 1\n...\n@\n", "yaml: line 3: found character that cannot start any token"},
		{"--- a: b\n", "yaml: mapping values are not allowed in this context"},
		{"--- [a,\n---\nb]\n", "yaml: line 1: did not find expected node content"},
		{"...\n---\na\n", "yaml: did not find expected node content"},
		{"a: 1\n---\n\"x\n", "yaml: line 3: found unexpected end of stream"},
		{"a: [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[\n", "yaml: line 1: did not find expected node content"},
		{"\xff\xfea\x00:\x00 \x00[\x00b\x00\n\x00", "yaml: line 1: did not find expected ',' or ']'"},
		{"\xff\xfea\x00:\x00\n\x00\t\x00b\x00\n\x00", "yaml: line 2: found character that cannot start any token"},
		{"\xfe\xff\x00a\x00:\x00 \x00[\x00b\x00\n", "yaml: line 1: did not find expected ',' or ']'"},
		{"\xfe\xff\x00a\x00:\x00\n\x00\t\x00b\x00\n", "yaml: line 2: found character that cannot start any token"},
		{"\xff\xfea\x00:", "yaml: incomplete UTF-16 character"},
		{"\xff\xfe\x00\xdc", "yaml: unexpected low surrogate area"},
		{"\xff\xfe\x00\xd8a\x00", "yaml: expected low surrogate area"},
		{"\xff\xfe\x00\xd8", "yaml: incomplete UTF-16 surrogate pair"},
		{"\xfe\xff\x00a\x00:\x00 \x00\x01", "yaml: control characters are not allowed"},
		{"# c\u0085# d\u0085\t# e\na: 1\n", "yaml: line 3: found character that cannot start any token"},
		{"a:\u0085\tb\n", "yaml: line 2: found character that cannot start any token"},
		{"# c\u2028# d\u2028\t# e\na: 1\n", "yaml: line 3: found character that cannot start any token"},
		{"a:\u2028\tb\n", "yaml: line 2: found character that cannot start any token"},
		{"# c\u2029# d\u2029\t# e\na: 1\n", "yaml: line 3: found character that cannot start any token"},
		{"a:\u2029\tb\n", "yaml: line 2: found character that cannot start any token"},
		{"a: *x\nb: @\n", "yaml: unknown anchor 'x' referenced"},
		{"a: *x\n@\n", "yaml: line 2: found character that cannot start any token"},
		{"a: *x @\n", "yaml: found character that cannot start any token"},
		{"- *x\n- @\n", "yaml: line 2: found character that cannot start any token"},
		{"[*x, @]\n", "yaml: found character that cannot start any token"},
		{"{a: *x, b: @}\n", "yaml: found character that cannot start any token"},
		{"a: *x\nb: c: d\n", "yaml: unknown anchor 'x' referenced"},
		{"a: *x\n  b: c\n", "yaml: unknown anchor 'x' referenced"},
		{"a: *x\n- b\n", "yaml: unknown anchor 'x' referenced"},
		{"*x: a\n", "yaml: unknown anchor 'x' referenced"},
		{"? *x\n: y\n", "yaml: unknown anchor 'x' referenced"},
		{"a: *x\nb: \"\\q\"\n", "yaml: unknown anchor 'x' referenced"},
		{"a: *x\n\"b\n", "yaml: line 2: found unexpected end of stream"},
		{"a: *x, b\n", "yaml: unknown anchor 'x' referenced"},
		{"[*x\n", "yaml: unknown anchor 'x' referenced"},
		{"- *x\n-\t*y\n", "yaml: line 2: found character that cannot start any token"},
		{"a: &a 1\nb: *a\nc: *b\n", "yaml: unknown anchor 'b' referenced"},
		{"a: !t *x\n", "yaml: did not find expected key"},
		{"a: &y *x\n", "yaml: did not find expected key"},
		{"*x\n---\n@\n", "yaml: line 3: found character that cannot start any token"},
		{"        # c\n    - } [ *", "yaml: line 1: did not find expected node content"},
		{"      # c\n  - ] [ !<x\n", "yaml: line 1: did not find expected node content"},
		{"    # c\n    - ,{*a!<\n", "yaml: line 2: did not find expected tag URI"},
		{"    # c\n    - ]{*\n", "yaml: line 1: did not find expected node content"},
		{"  # c\n    # d\n  - ]'q' &a{'a\n---\n'\nb: 2\n", "yaml: line 2: did not find expected node content"},
		{"  # c\n- &a, |'a\n---\n'\nb: 2\n", "yaml: line 2: found unexpected document indicator"},
		{"# c\n# e\n- ,, *a'q' @\n- k\n", "yaml: line 2: did not find expected node content"},
		{"# e\n- , 'q'!<x\n", "yaml: line 1: did not find expected node content"},
		{"#c\n- }{\"\\q\"", "yaml: line 1: did not find expected node content"},
		{"%YAML 1.1\n---\n        # c\n    - } [ &\n- k\n", "yaml: line 3: did not find expected node content"},
		{"%YAML 1.1\n---\n    # c\n\n    # e\n    - ,{!<", "yaml: line 5: did not find expected node content"},
		{"%YAML 1.1\n---\n    # c\n\n    # e\n    - { : !t`\n- k\n", "yaml: line 6: found character that cannot start any token"},
	}
	for _, tt := range tests {
		checkError(t, tt.in, tt.want)
	}
}

func checkError(t *testing.T, in, want string) {
	t.Helper()
	doc, err := Parse([]byte(in))
	if err == nil {
		t.Errorf("Parse(%q) succeeded, want error %q", in, want)
		return
	}
	if got := err.Error(); got != want {
		t.Errorf("Parse(%q)\n got error %q\nwant error %q", in, got, want)
	}
	if doc != nil {
		t.Errorf("Parse(%q) returned a document with its error", in)
	}
}

func TestValidDocuments(t *testing.T) {
	tests := []string{
		"",
		"  # c\n",
		"--- # c\n",
		" \n",
		"---\n---\n",
		"1\n",
		"+1",
		"08\n",
		"0X1F",
		"017\n",
		"-0b101",
		"1_000\n",
		"1__0",
		".5\n",
		"+.5",
		"1E3\n",
		"1.e3",
		".inf\n",
		".INF",
		".nan\n",
		".NAN",
		"nan\n",
		"true",
		"tRue\n",
		"yes",
		"off\n",
		"n",
		"Null\n",
		"nULL",
		"2001-12-14 21:59:43.10\n",
		"2001-1-1",
		"<<\n",
		"9223372036854775807",
		"-9223372036854775809\n",
		"0b11111111111111111111111111111111111111111111111111111111111111111",
		"-0x1F\n",
		"0.1.2",
		"a b\n",
		"a\n b",
		"a \n b\n",
		"a #c",
		"\"a\"\n",
		"\"true\"",
		"!!str 1\n",
		"!!float 1",
		"!foo bar\n",
		"! a",
		"&a 1\n",
		"\"\\x41\"",
		"\"a\\\n  b\"\n",
		"abcdefghij",
		"- \"x\"\n",
		"{a: 1}",
		"rules:\n  boundary: a\n",
		"rules:\n  boundary: 'a''b'\n",
		"rules:\n  boundary: \"\\0\"\n",
		"rules:\n  boundary: \"\\'\"\n",
		"rules:\n  boundary: \"a\\\n\n  b\"\n",
		"rules:\n  boundary: a   b\n",
		"rules:\n  boundary: a]\n",
		"rules:\n  boundary: a?\n",
		"rules:\n  boundary: ''\n",
		"rules:\n  boundary: |\n",
		"rules:\n  boundary: '\\t'\n",
		"rules:\n  boundary: é\n",
		"rules:\n  boundary: !!str a\n",
		"rules:\n  boundary: \"a\"  # c\n",
		"\n\na: 1\n\n\nb: 2\n",
		"    a: 1\n    b: 2\n",
		"a:\nb:\n",
		"%YAML 1.1\n---\na: 1\n",
		"a: 'x\n  y'\nb: 1\n",
		"\ufeffa: 1\nb: 2\n",
		"a:   1   \nb:\t2\n",
		"- a\n- b\n - c\n",
		"a:\tb\n",
		"a: 'b\n\tc'\n",
		"a:\t\n",
		"[a]]\n",
		"{a: b c}\n",
		"[a, b,]\n",
		"{[a]: b}\n",
		"[a #c\n]\n",
		"{a: 1} b\n",
		"[a: b]\n",
		"- [a,\nb]\n",
		"'a' b\n",
		"''''\n",
		"- \n",
		"::\n",
		"??\n",
		"? - a\n",
		"&a [*a]\n",
		"!!str a: b\n",
		"a: !%41 b\n",
		"a: !<a,b> c\n",
		"%TAG ! tag:x,2000:\n---\na: !foo b\n",
		"---\na: 1\n---\nb: 2\n",
		"---a: b\n",
		"- a\n---\n",
	}
	for _, in := range tests {
		if _, err := Parse([]byte(in)); err != nil {
			t.Errorf("Parse(%q) error: %v", in, err)
		}
	}
}

// lookup follows mapping keys from the root of doc.
func lookup(doc *Node, keys ...string) *Node {
	if doc == nil || len(doc.Content) == 0 {
		return nil
	}
	n := doc.Content[0]
	for _, k := range keys {
		var next *Node
		if n.Kind == MappingNode {
			for i := 0; i+1 < len(n.Content); i += 2 {
				if n.Content[i].Value == k {
					next = n.Content[i+1]
					break
				}
			}
		}
		if next == nil {
			return nil
		}
		n = next
	}
	return n
}

// TestScalarValues checks the decoded value of the scalar at rules.boundary.
func TestScalarValues(t *testing.T) {
	tests := []struct{ in, want string }{
		{"rules:\n  boundary: a\n", "a"},
		{"rules:\n  boundary: 1\n", "1"},
		{"rules:\n  boundary: 1.5\n", "1.5"},
		{"rules:\n  boundary: true\n", "true"},
		{"rules:\n  boundary: \"a\\tb\"\n", "a\tb"},
		{"rules:\n  boundary: 'a''b'\n", "a'b"},
		{"rules:\n  boundary: \"a\\\\b\"\n", "a\\b"},
		{"rules:\n  boundary: \"\\u00e9\"\n", "é"},
		{"rules:\n  boundary: \"\\U0001F600\"\n", "😀"},
		{"rules:\n  boundary: \"\\x41\\x42\"\n", "AB"},
		{"rules:\n  boundary: \"\\0\"\n", "\x00"},
		{"rules:\n  boundary: \"\\a\\b\\e\\f\\n\\r\\t\\v\"\n", "\a\b\x1b\f\n\r\t\v"},
		{"rules:\n  boundary: \"\\N\\_\\L\\P\"\n", "\u0085\u00a0\u2028\u2029"},
		{"rules:\n  boundary: \"\\ \"\n", " "},
		{"rules:\n  boundary: \"\\\"\"\n", "\""},
		{"rules:\n  boundary: \"\\'\"\n", "'"},
		{"rules:\n  boundary: \"a\n  b\"\n", "a b"},
		{"rules:\n  boundary: \"a\n\n  b\"\n", "a\nb"},
		{"rules:\n  boundary: \"a  \n  b\"\n", "a b"},
		{"rules:\n  boundary: \"a\\\n  b\"\n", "ab"},
		{"rules:\n  boundary: \"a\\\n\n  b\"\n", "a\nb"},
		{"rules:\n  boundary: 'a\n  b'\n", "a b"},
		{"rules:\n  boundary: 'a\n\n  b'\n", "a\nb"},
		{"rules:\n  boundary: 'a  \n   b'\n", "a b"},
		{"rules:\n  boundary: a\n    b\n    c\n", "a b c"},
		{"rules:\n  boundary: a   b\n", "a   b"},
		{"rules:\n  boundary: a \t b\n", "a \t b"},
		{"rules:\n  boundary: a b # c\n", "a b"},
		{"rules:\n  boundary: a:b\n", "a:b"},
		{"rules:\n  boundary: a,b\n", "a,b"},
		{"rules:\n  boundary: a]\n", "a]"},
		{"rules:\n  boundary: a}\n", "a}"},
		{"rules:\n  boundary: -a\n", "-a"},
		{"rules:\n  boundary: ?a\n", "?a"},
		{"rules:\n  boundary: :a\n", ":a"},
		{"rules:\n  boundary: a?\n", "a?"},
		{"rules:\n  boundary: a-\n", "a-"},
		{"rules:\n  boundary: a#\n", "a#"},
		{"rules:\n  boundary: a #\n", "a"},
		{"rules:\n  boundary: \" a \"\n", " a "},
		{"rules:\n  boundary: ' a '\n", " a "},
		{"rules:\n  boundary: |1\n   a\n", "a\n"},
		{"rules:\n  boundary: \"a\\tb\\u0041\"\n", "a\tbA"},
		{"rules:\n  boundary: '\\t'\n", "\\t"},
		{"rules:\n  boundary: a\\tb\n", "a\\tb"},
		{"rules:\n  boundary: \"\\x7f\"\n", "\x7f"},
		{"rules:\n  boundary: \"\\u2028\"\n", "\u2028"},
		{"rules:\n  boundary: 'é'\n", "é"},
		{"rules:\n  boundary: é\n", "é"},
		{"rules:\n  boundary: \"€\"\n", "€"},
		{"rules:\n  boundary: \"a\r\n  b\"\n", "a b"},
		{"rules:\n  boundary: 'a\r\n\r\n  b'\n", "a\nb"},
		{"rules:\n  boundary: &x a\n", "a"},
		{"rules:\n  boundary: !!str a\n", "a"},
		{"rules:\n  boundary: !!str 1\n", "1"},
		{"rules:\n  boundary: &x !!str a\n", "a"},
		{"rules:\n  boundary: !!str &x a\n", "a"},
		{"rules:\n  boundary: \"a\"  # c\n", "a"},
		{"rules:\n  boundary: 'a' #c\n", "a"},
		{"rules:\n  boundary: a \t\n", "a"},
		{"rules:\n  boundary: \"a\" \t\n", "a"},
		{"rules:\n  boundary: >\r\n    a", "a"},
		{"rules:\n  boundary: |+\r\n    a\r\n      \r\n    b\r\n", "a\n  \nb\n"},
		{"rules:\n  boundary: >+\r\n    a\r\n     b\r\n    c\r\n", "a\n b\nc\n"},
		{"rules:\n  boundary: |1\r\n    a", " a"},
		{"rules:\n  boundary: >1\n     a\n    b\n", "  a\n b\n"},
		{"rules:\n  boundary: >2\n    a", "a"},
		{"rules:\n  boundary: |2+\n\n    a\n\n\n", "\na\n\n\n"},
		{"rules:\n  boundary: >-1\n    a\n    \tb\n", " a\n \tb"},
		{"rules:\n  boundary: | #c\n    a\n\n    b\n", "a\n\nb\n"},
		{"rules:\n  boundary: 'aaa'\n", "aaa"},
		{"rules:\n  boundary: 'a\nx\n'\n", "a x "},
		{"rules:\n  boundary: 'a\tx\n'\n", "a\tx "},
		{"rules:\n  boundary: ' a\n  '\n", " a "},
		{"rules:\n  boundary: ' \n\n\n\n'\n", "\n\n\n"},
		{"rules:\n  boundary: ' x\n '\n", " x "},
		{"rules:\n  boundary: '  ax\n'\n", "  ax "},
		{"rules:\n  boundary: '  \n\ta'\n", " a"},
		{"rules:\n  boundary: '  x \t'\n", "  x \t"},
		{"rules:\n  boundary: '\n  \n\n'\n", "\n\n"},
		{"rules:\n  boundary: '\n\n\t\n'\n", "\n\n"},
		{"rules:\n  boundary: '\nx b'\n", " x b"},
		{"rules:\n  boundary: '\n\n\n  a'\n", "\n\na"},
		{"rules:\n  boundary: '\n\nx \t'\n", "\nx \t"},
		{"rules:\n  boundary: '\n    \n  '\n", "\n"},
		{"rules:\n  boundary: '\n  \n\t\t'\n", "\n"},
		{"rules:\n  boundary: '\n  b\n'\n", " b "},
		{"rules:\n  boundary: '\n\t\n '\n", "\n"},
		{"rules:\n  boundary: '\n\t\t\n'\n", "\n"},
		{"rules:\n  boundary: '\n\tbb'\n", " bb"},
		{"rules:\n  boundary: '\t\n\t'\n", " "},
		{"rules:\n  boundary: '\t\t\n\t'\n", " "},
		{"rules:\n  boundary: 'x\na  '\n", "x a  "},
		{"rules:\n  boundary: 'x\n\nb'\n", "x\nb"},
		{"rules:\n  boundary: 'x\n\tx '\n", "x x "},
		{"rules:\n  boundary: 'x a\n  '\n", "x a "},
		{"rules:\n  boundary: 'x \n\n\n\n'\n", "x\n\n\n"},
		{"rules:\n  boundary: 'x x\n '\n", "x x "},
		{"rules:\n  boundary: 'bax\n'\n", "bax "},
		{"rules:\n  boundary: 'b\n\nx\n'\n", "b\nx "},
		{"rules:\n  boundary: 'bx\n\n\n'\n", "bx\n\n"},
		{"rules:\n  boundary: \"a a\"\n", "a a"},
		{"rules:\n  boundary: \"a\n  a\"\n", "a a"},
		{"rules:\n  boundary: \"a\\\n\\\n\"\n", "a"},
		{"rules:\n  boundary: \"  \n  \"\n", " "},
		{"rules:\n  boundary: \" \n  \n  \"\n", "\n"},
		{"rules:\n  boundary: \" \\  \"\n", "   "},
		{"rules:\n  boundary: \"    \\ \"\n", "     "},
		{"rules:\n  boundary: \"  \ta\"\n", "  \ta"},
		{"rules:\n  boundary: \"  b\t\"\n", "  b\t"},
		{"rules:\n  boundary: \"\n\n\n\n\"\n", "\n\n\n"},
		{"rules:\n  boundary: \"\n\t\n\"\n", "\n"},
		{"rules:\n  boundary: \"\nbb\"\n", " bb"},
		{"rules:\n  boundary: \"\n\n\n\ta\"\n", "\n\na"},
		{"rules:\n  boundary: \"\n\nb\t\"\n", "\nb\t"},
		{"rules:\n  boundary: \"\n  \n\\\n\"\n", "\n"},
		{"rules:\n  boundary: \"\n  \t\t\"\n", " "},
		{"rules:\n  boundary: \"\n\ta\n\"\n", " a "},
		{"rules:\n  boundary: \"\n\t\n\n\n\t\"\n", "\n\n\n"},
		{"rules:\n  boundary: \"\n\t\\\n\n\"\n", " \n"},
		{"rules:\n  boundary: \"\tab\"\n", "\tab"},
		{"rules:\n  boundary: \"\t\n\nb\"\n", "\nb"},
		{"rules:\n  boundary: \"\t\\\n\n\t\"\n", "\t\n"},
		{"rules:\n  boundary: \"\\\n \n\n\"\n", "\n\n"},
		{"rules:\n  boundary: \"\\\n\n  \\ \"\n", "\n "},
		{"rules:\n  boundary: \"\\\nb  \"\n", "b  "},
		{"rules:\n  boundary: \"\\   b\"\n", "   b"},
		{"rules:\n  boundary: \"\\ \n\t\\ \"\n", "   "},
		{"rules:\n  boundary: \"\\ b\n  \"\n", " b "},
		{"rules:\n  boundary: \"b\n  \"\n", "b "},
		{"rules:\n  boundary: \"b\t \"\n", "b\t "},
		{"rules:\n  boundary: \"bb\\\n\"\n", "bb"},
		{"rules:\n  boundary: xa\n    \t\n", "xa"},
		{"rules:\n  boundary: xa- \n", "xa-"},
		{"rules:\n  boundary: x \n\n\n", "x"},
		{"rules:\n  boundary: x  #ca\n", "x"},
		{"rules:\n  boundary: x\n  #c\n", "x"},
		{"rules:\n  boundary: x\n #c:\n", "x"},
		{"rules:\n  boundary: x\n\n #c\t\n", "x"},
		{"rules:\n  boundary: x\n    \n    \n\n\n", "x"},
		{"rules:\n  boundary: x\n    :-\n", "x :-"},
		{"rules:\n  boundary: x\n   \n \n", "x"},
		{"rules:\n  boundary: x\n   \tb\n", "x b"},
		{"rules:\n  boundary: x\ta\n    \n", "x\ta"},
		{"rules:\n  boundary: x\t\n   \n\n\n", "x"},
		{"rules:\n  boundary: x\t--\n", "x\t--"},
		{"rules:\n  boundary: x #c\n\n   \n", "x"},
		{"rules:\n  boundary: x #c #c: \n", "x"},
		{"rules:\n  boundary: x #cb \n", "x"},
		{"rules:\n  boundary: x:b\t\n", "x:b"},
		{"rules:\n  boundary: x-\n    \n   \n", "x-"},
		{"rules:\n  boundary: x--a\n", "x--a"},
		{"rules:\n  boundary: xb\n \n", "xb"},
		{"rules:\n  boundary: xb\tb\n", "xb\tb"},
	}
	for _, tt := range tests {
		doc, err := Parse([]byte(tt.in))
		if err != nil {
			t.Errorf("Parse(%q) error: %v", tt.in, err)
			continue
		}
		n := lookup(doc, "rules", "boundary")
		if n == nil || n.Kind != ScalarNode {
			t.Errorf("Parse(%q): rules.boundary is not a scalar", tt.in)
			continue
		}
		if n.Value != tt.want {
			t.Errorf("Parse(%q): rules.boundary = %q, want %q", tt.in, n.Value, tt.want)
		}
	}
}

// TestResolvedTags checks the tag, line and value of a top-level scalar.
func TestResolvedTags(t *testing.T) {
	tests := []struct {
		in, tag string
		line    int
		value   string
	}{
		{"--- |\n", "!!str", 1, ""},
		{"%YAML 1.1\n--- a\n", "!!str", 2, "a"},
		{"a\n", "!!str", 1, "a"},
		{"1\n", "!!int", 1, "1"},
		{"-1\n", "!!int", 1, "-1"},
		{"+1\n", "!!int", 1, "+1"},
		{"0\n", "!!int", 1, "0"},
		{"00\n", "!!int", 1, "00"},
		{"08\n", "!!float", 1, "08"},
		{"0x1F\n", "!!int", 1, "0x1F"},
		{"0X1F\n", "!!int", 1, "0X1F"},
		{"0o17\n", "!!int", 1, "0o17"},
		{"0O17\n", "!!int", 1, "0O17"},
		{"017\n", "!!int", 1, "017"},
		{"0b101\n", "!!int", 1, "0b101"},
		{"-0b101\n", "!!int", 1, "-0b101"},
		{"0b\n", "!!str", 1, "0b"},
		{"0x\n", "!!str", 1, "0x"},
		{"1_000\n", "!!int", 1, "1_000"},
		{"_1\n", "!!str", 1, "_1"},
		{"1__0\n", "!!int", 1, "1__0"},
		{"1.5\n", "!!float", 1, "1.5"},
		{"-1.5\n", "!!float", 1, "-1.5"},
		{".5\n", "!!float", 1, ".5"},
		{"-.5\n", "!!float", 1, "-.5"},
		{"+.5\n", "!!float", 1, "+.5"},
		{"1.\n", "!!float", 1, "1."},
		{"1e3\n", "!!float", 1, "1e3"},
		{"1E3\n", "!!float", 1, "1E3"},
		{"1e+3\n", "!!float", 1, "1e+3"},
		{"1.e3\n", "!!float", 1, "1.e3"},
		{".e3\n", "!!str", 1, ".e3"},
		{"1_0.5\n", "!!float", 1, "1_0.5"},
		{".inf\n", "!!float", 1, ".inf"},
		{".Inf\n", "!!float", 1, ".Inf"},
		{".INF\n", "!!float", 1, ".INF"},
		{"-.inf\n", "!!float", 1, "-.inf"},
		{"+.inf\n", "!!float", 1, "+.inf"},
		{".nan\n", "!!float", 1, ".nan"},
		{".NaN\n", "!!float", 1, ".NaN"},
		{".NAN\n", "!!float", 1, ".NAN"},
		{".nAn\n", "!!str", 1, ".nAn"},
		{"inf\n", "!!str", 1, "inf"},
		{"nan\n", "!!str", 1, "nan"},
		{"Infinity\n", "!!str", 1, "Infinity"},
		{"true\n", "!!bool", 1, "true"},
		{"True\n", "!!bool", 1, "True"},
		{"TRUE\n", "!!bool", 1, "TRUE"},
		{"tRue\n", "!!str", 1, "tRue"},
		{"false\n", "!!bool", 1, "false"},
		{"yes\n", "!!str", 1, "yes"},
		{"no\n", "!!str", 1, "no"},
		{"on\n", "!!str", 1, "on"},
		{"off\n", "!!str", 1, "off"},
		{"y\n", "!!str", 1, "y"},
		{"n\n", "!!str", 1, "n"},
		{"nULL\n", "!!str", 1, "nULL"},
		{"2001-12-14\n", "!!timestamp", 1, "2001-12-14"},
		{"2001-1-1\n", "!!timestamp", 1, "2001-1-1"},
		{"2001-13-14\n", "!!str", 1, "2001-13-14"},
		{"<<\n", "!!merge", 1, "<<"},
		{"0x_1F\n", "!!int", 1, "0x_1F"},
		{"1e400\n", "!!str", 1, "1e400"},
		{"-0o17\n", "!!int", 1, "-0o17"},
		{"-0x1F\n", "!!int", 1, "-0x1F"},
		{"+0x1F\n", "!!int", 1, "+0x1F"},
		{"0.1.2\n", "!!str", 1, "0.1.2"},
		{"1:2\n", "!!str", 1, "1:2"},
		{"12:30:45\n", "!!str", 1, "12:30:45"},
		{"a b\n", "!!str", 1, "a b"},
		{"a  b\n", "!!str", 1, "a  b"},
		{"a\n b\n", "!!str", 1, "a b"},
		{"a \n b\n", "!!str", 1, "a b"},
		{"a\t\n b\n", "!!str", 1, "a b"},
		{"a #c\n", "!!str", 1, "a"},
		{"a#c\n", "!!str", 1, "a#c"},
		{"'a'\n", "!!str", 1, "a"},
		{"\"a\"\n", "!!str", 1, "a"},
		{"'1'\n", "!!str", 1, "1"},
		{"\"true\"\n", "!!str", 1, "true"},
		{"!!str 1\n", "!!str", 1, "1"},
		{"!!int 1\n", "!!int", 1, "1"},
		{"!!float 1\n", "!!float", 1, "1"},
		{"!!bool true\n", "!!bool", 1, "true"},
		{"!foo bar\n", "!foo", 1, "bar"},
		{"! 1\n", "!!int", 1, "1"},
		{"! a\n", "!!str", 1, "a"},
		{"!<tag:yaml.org,2002:int> 1\n", "!!int", 1, "1"},
		{"!!binary aGVsbG8=\n", "!!binary", 1, "aGVsbG8="},
		{"&a 1\n", "!!int", 1, "1"},
		{"&a b\n", "!!str", 1, "b"},
		{"\"\\x41\"\n", "!!str", 1, "A"},
		{"'it''s'\n", "!!str", 1, "it's"},
		{"'a\n  b'\n", "!!str", 1, "a b"},
		{"\"a\\\n  b\"\n", "!!str", 1, "ab"},
		{"abcdefghij\n", "!!str", 1, "abcdefghij"},
		{"\"\"\n", "!!str", 1, ""},
		{"''\n", "!!str", 1, ""},
		{"\"a\" b\n", "!!str", 1, "a"},
		{"'a' b\n", "!!str", 1, "a"},
		{"\"a\"b\n", "!!str", 1, "a"},
		{"'a'b\n", "!!str", 1, "a"},
		{"\"a\":b\n", "!!str", 1, "a"},
		{"\"\\U0010FFFF\"\n", "!!str", 1, "\U0010ffff"},
		{"''''\n", "!!str", 1, "'"},
		{"\"\\\"\"\n", "!!str", 1, "\""},
		{"--\n", "!!str", 1, "--"},
		{"---a\n", "!!str", 1, "---a"},
		{":a\n", "!!str", 1, ":a"},
		{"a::b\n", "!!str", 1, "a::b"},
		{"??\n", "!!str", 1, "??"},
		{"?a\n", "!!str", 1, "?a"},
		{"!x\n", "!x", 1, ""},
		{"%YAML 1.1 # c\n---\na\n", "!!str", 3, "a"},
		{"%YAML\t1.1\n---\na\n", "!!str", 3, "a"},
		{"--- a\n--- b\n", "!!str", 1, "a"},
	}
	for _, tt := range tests {
		doc, err := Parse([]byte(tt.in))
		if err != nil {
			t.Errorf("Parse(%q) error: %v", tt.in, err)
			continue
		}
		n := doc.Content[0]
		if n.Kind == AliasNode {
			n = n.Alias
		}
		if n.Tag != tt.tag || n.ShortTag() != tt.tag || n.Line != tt.line || n.Value != tt.value {
			t.Errorf("Parse(%q) = tag %q (short %q), line %d, value %q; want %q, %d, %q",
				tt.in, n.Tag, n.ShortTag(), n.Line, n.Value, tt.tag, tt.line, tt.value)
		}
	}
}

type keyLine struct {
	key  string
	line int
}

func (k keyLine) String() string { return fmt.Sprintf("%q@%d", k.key, k.line) }

// TestKeyLines checks the keys of a top-level mapping and their lines.
func TestKeyLines(t *testing.T) {
	tests := []struct {
		in   string
		keys []keyLine
	}{
		{"{a: 1}\n", []keyLine{{"a", 1}}},
		{"a: 1\nb: 2\n", []keyLine{{"a", 1}, {"b", 2}}},
		{"# c\na: 1\n# d\nb: 2\n", []keyLine{{"a", 2}, {"b", 4}}},
		{"a:\n  x: 1\nb:\n  - 1\nc: 3\n", []keyLine{{"a", 1}, {"b", 3}, {"c", 5}}},
		{"    a: 1\n    b: 2\n", []keyLine{{"a", 1}, {"b", 2}}},
		{"a: 1\rb: 2\r", []keyLine{{"a", 1}, {"b", 2}}},
		{"? a\n? b\n", []keyLine{{"a", 1}, {"b", 2}}},
		{"\"a\": 1\n'b': 2\n", []keyLine{{"a", 1}, {"b", 2}}},
		{"--- \na: 1\n", []keyLine{{"a", 2}}},
		{"%YAML 1.1\n---\na: 1\n", []keyLine{{"a", 3}}},
		{"a: 1\n...\nb: 2\n", []keyLine{{"a", 1}}},
		{"a: >\n  x\n\nb: 1\n", []keyLine{{"a", 1}, {"b", 4}}},
		{"a: x\n  y\nb: 1\n", []keyLine{{"a", 1}, {"b", 3}}},
		{"a: [1,\n  2]\nb: 1\n", []keyLine{{"a", 1}, {"b", 3}}},
		{"\ufeffa: 1\nb: 2\n", []keyLine{{"a", 1}, {"b", 2}}},
		{"a:\n- 1\n- 2\nb: 1\n", []keyLine{{"a", 1}, {"b", 4}}},
		{"a: 1\nb: 2\nc: 3\nd: 4\n", []keyLine{{"a", 1}, {"b", 2}, {"c", 3}, {"d", 4}}},
		{"a: 1\t\nb: 2 \n", []keyLine{{"a", 1}, {"b", 2}}},
		{"a:\n  - b\n   - c\n", []keyLine{{"a", 1}}},
		{"  a: 1\n b: 2\n", []keyLine{{"a", 1}}},
		{"a:\t b\n", []keyLine{{"a", 1}}},
		{"a: b\n# c\n\t# d\n", []keyLine{{"a", 1}}},
		{"a: 'b\n\tc'\n", []keyLine{{"a", 1}}},
		{"{a: 1,\n\tb: 2}\n", []keyLine{{"a", 1}, {"b", 2}}},
		{"a:\t\n", []keyLine{{"a", 1}}},
		{"a: b\t# c\n", []keyLine{{"a", 1}}},
		{"{a: b c}\n", []keyLine{{"a", 1}}},
		{"{? a}\n", []keyLine{{"a", 1}}},
		{"{a: 1}#c\n", []keyLine{{"a", 1}}},
		{"{\"a\":b}\n", []keyLine{{"a", 1}}},
		{"a: [b,\nc]\n", []keyLine{{"a", 1}}},
		{"a: \"b\" # c\n", []keyLine{{"a", 1}}},
		{"a: -b\n", []keyLine{{"a", 1}}},
		{"? a\n", []keyLine{{"a", 1}}},
		{"a: >1\n  b\n", []keyLine{{"a", 1}}},
		{"a: &a b\nc: &a d\ne: *a\n", []keyLine{{"a", 1}, {"c", 2}, {"e", 3}}},
		{"a: &a !!str c\n", []keyLine{{"a", 1}}},
		{"!!str a: b\n", []keyLine{{"a", 1}}},
		{"a: !!seq []\n", []keyLine{{"a", 1}}},
		{"a: !<x> b\n", []keyLine{{"a", 1}}},
		{"a: !%c3%a9 b\n", []keyLine{{"a", 1}}},
		{"a: !x[ b\n", []keyLine{{"a", 1}}},
		{"a: !<a[b]> c\n", []keyLine{{"a", 1}}},
		{"%TAG !e! tag:x,2000:\n---\na: !e!foo b\n", []keyLine{{"a", 3}}},
		{"%TAG !! tag:x,2000:\n---\na: !!foo b\n", []keyLine{{"a", 3}}},
		{"---\na: 1\n---\nb: 2\n", []keyLine{{"a", 2}}},
		{"a: 1\n---\nx\n---\n@\n", []keyLine{{"a", 1}}},
		{"---a: b\n", []keyLine{{"---a", 1}}},
		{"a: |\n  b\n---\n", []keyLine{{"a", 1}}},
		{"a: b\n...\n...\n", []keyLine{{"a", 1}}},
		{"a: 1\n---\n- a\n -\n", []keyLine{{"a", 1}}},
	}
	for _, tt := range tests {
		doc, err := Parse([]byte(tt.in))
		if err != nil {
			t.Errorf("Parse(%q) error: %v", tt.in, err)
			continue
		}
		var got []keyLine
		m := doc.Content[0]
		for i := 0; i+1 < len(m.Content); i += 2 {
			got = append(got, keyLine{m.Content[i].Value, m.Content[i].Line})
		}
		if fmt.Sprint(got) != fmt.Sprint(tt.keys) {
			t.Errorf("Parse(%q) keys = %v, want %v", tt.in, got, tt.keys)
		}
	}
}

func TestNodeTree(t *testing.T) {
	const in = `# head

defaults: &d
  unexported: private
rules:
  naming: {qualify: "always", exported: true}
  vocabulary:
  - [a, b]
  - *d
filter:
  only: |
    a.go
  omit: >-
    b
    c
? !!str complex
: 0x1F
`
	doc, err := Parse([]byte(in))
	if err != nil {
		t.Fatal(err)
	}
	var b strings.Builder
	var dump func(n *Node, depth int)
	dump = func(n *Node, depth int) {
		fmt.Fprintf(&b, "%s%d %d:%d %s %d %q %q\n", strings.Repeat("  ", depth),
			n.Kind, n.Line, n.Column, n.ShortTag(), n.Style, n.Value, n.Anchor)
		for _, c := range n.Content {
			dump(c, depth+1)
		}
	}
	dump(doc, 0)
	const want = `1 3:1  0 "" ""
  4 3:1 !!map 0 "" ""
    8 3:1 !!str 0 "defaults" ""
    4 3:11 !!map 0 "" "d"
      8 4:3 !!str 0 "unexported" ""
      8 4:15 !!str 0 "private" ""
    8 5:1 !!str 0 "rules" ""
    4 6:3 !!map 0 "" ""
      8 6:3 !!str 0 "naming" ""
      4 6:11 !!map 32 "" ""
        8 6:12 !!str 0 "qualify" ""
        8 6:21 !!str 2 "always" ""
        8 6:31 !!str 0 "exported" ""
        8 6:41 !!bool 0 "true" ""
      8 7:3 !!str 0 "vocabulary" ""
      2 8:3 !!seq 0 "" ""
        2 8:5 !!seq 32 "" ""
          8 8:6 !!str 0 "a" ""
          8 8:9 !!str 0 "b" ""
        16 9:5 !!map 0 "d" ""
    8 10:1 !!str 0 "filter" ""
    4 11:3 !!map 0 "" ""
      8 11:3 !!str 0 "only" ""
      8 11:9 !!str 8 "a.go\n" ""
      8 13:3 !!str 0 "omit" ""
      8 13:9 !!str 16 "b c" ""
    8 16:3 !!str 1 "complex" ""
    8 17:3 !!int 0 "0x1F" ""
`
	if got := b.String(); got != want {
		t.Errorf("tree:\n%s\nwant:\n%s", got, want)
	}
	alias := doc.Content[0].Content[3].Content[3].Content[1]
	if alias.Alias != doc.Content[0].Content[1] {
		t.Errorf("alias *d does not refer to the node anchored &d")
	}
}

func TestNoDocument(t *testing.T) {
	for _, in := range []string{"", "\n", "# c", "  # c\n\n# d\n", "\ufeff"} {
		doc, err := Parse([]byte(in))
		if doc != nil || err != nil {
			t.Errorf("Parse(%q) = %v, %v; want nil, nil", in, doc, err)
		}
	}
	doc, err := Parse([]byte("---\n"))
	if err != nil {
		t.Fatal(err)
	}
	if n := doc.Content[0]; n.Kind != ScalarNode || n.ShortTag() != "!!null" || n.Line != 2 || n.Column != 1 {
		t.Errorf("Parse(\"---\\n\") content = %+v, want an empty null scalar at 2:1", n)
	}
}

// Only the first document is parsed, but the scanner reads two tokens ahead
// of the parser, so an error there is still reported.
func TestFirstDocumentOnly(t *testing.T) {
	doc, err := Parse([]byte("a: 1\n---\nb: @\n"))
	if err != nil {
		t.Fatal(err)
	}
	if n := doc.Content[0]; len(n.Content) != 2 || n.Content[0].Value != "a" {
		t.Errorf("got %d nodes in the first document, want just a: 1", len(n.Content))
	}
	checkError(t, "a: 1\n---\n@\n", "yaml: line 3: found character that cannot start any token")
	checkError(t, "]\n@\n", "yaml: line 2: found character that cannot start any token")
}

// The input is decoded in 512-byte chunks, so whether an invalid byte or a
// scanner error is reported depends on where they fall.
func TestReaderChunks(t *testing.T) {
	var lines []string
	var starts []int
	off := 0
	for i := 0; i < 120; i++ {
		l := fmt.Sprintf("k%03d: value number %d\n", i, i)
		lines = append(lines, l)
		starts = append(starts, off)
		off += len(l)
	}
	base := strings.Join(lines, "")
	insert := func(s string, pos int, what string) string { return s[:pos] + what + s[pos:] }

	checkError(t, insert(base, 100, "\xff"), "yaml: invalid leading UTF-8 octet")
	checkError(t, insert(base, 2000, "\x01"), "yaml: control characters are not allowed")
	checkError(t, insert(insert(base, 1600, "\xff"), starts[10], "@"),
		"yaml: line 11: found character that cannot start any token")
	checkError(t, insert(insert(base, 1100, "\xff"), starts[46], "@"),
		"yaml: line 47: found character that cannot start any token")

	// The scanner looks four characters ahead when it fetches a token.
	tipping := func(at int) string {
		s := "a: " + strings.Repeat("x", at-4) + "\n@: 1\n" + strings.Repeat("y: 2\n", 30)
		return insert(s, 1100, "\xff")
	}
	checkError(t, tipping(1020), "yaml: line 2: found character that cannot start any token")
	checkError(t, tipping(1021), "yaml: invalid leading UTF-8 octet")
}

func TestDepthLimits(t *testing.T) {
	deep := func(n int, s string) string { return strings.Repeat(s, n) }
	if _, err := Parse([]byte(deep(10000, "[") + deep(10000, "]"))); err != nil {
		t.Errorf("10000 nested flow sequences: %v", err)
	}
	checkError(t, deep(10001, "[")+deep(10001, "]"), "yaml: exceeded max depth of 10000")
	if _, err := Parse([]byte(deep(10000, "- ") + "a\n")); err != nil {
		t.Errorf("10000 nested block sequences: %v", err)
	}
	checkError(t, deep(10001, "- ")+"a\n", "yaml: exceeded max depth of 10000")
	checkError(t, "a:\n  "+deep(10001, "- ")+"x\n", "yaml: line 2: exceeded max depth of 10000")
	checkError(t, "a: 1\n"+deep(1025, "k")+": v\n", "yaml: line 2: could not find expected ':'")
	checkError(t, deep(1025, "k")+": v\n", "yaml: mapping values are not allowed in this context")
}

// yaml.v3 skips a byte order mark at the start of the input. It checks for
// another one at the start of each line by looking at the start of its
// buffer, so after two leading marks it drops the first character of lines.
func TestByteOrderMarks(t *testing.T) {
	tests := []struct {
		in   string
		keys []keyLine
	}{
		{"\ufeffa: 1\nbc: 2\n", []keyLine{{"a", 1}, {"bc", 2}}},
		{"a: 1\n\ufeffb: 2\n", []keyLine{{"a", 1}, {"\ufeffb", 2}}},
		{"\ufeff\ufeffa: 1\nbc: 2\nde: 3\n", []keyLine{{"a", 1}, {"c", 2}, {"e", 3}}},
		{"\ufeff\ufeff\n\nbc: 2\n", []keyLine{{"bc", 2}}},
		{"\ufeff\ufeff\ufeffa: 1\n", []keyLine{{"\ufeffa", 1}}},
	}
	for _, tt := range tests {
		doc, err := Parse([]byte(tt.in))
		if err != nil {
			t.Errorf("Parse(%q) error: %v", tt.in, err)
			continue
		}
		var got []keyLine
		m := doc.Content[0]
		for i := 0; i+1 < len(m.Content); i += 2 {
			got = append(got, keyLine{m.Content[i].Value, m.Content[i].Line})
		}
		if fmt.Sprint(got) != fmt.Sprint(tt.keys) {
			t.Errorf("Parse(%q) keys = %v, want %v", tt.in, got, tt.keys)
		}
	}
}

func TestUTF16(t *testing.T) {
	encode := func(s string, bigEndian bool) []byte {
		out := []byte{0xFF, 0xFE}
		if bigEndian {
			out = []byte{0xFE, 0xFF}
		}
		for _, u := range utf16.Encode([]rune(s)) {
			if bigEndian {
				out = append(out, byte(u>>8), byte(u))
			} else {
				out = append(out, byte(u), byte(u>>8))
			}
		}
		return out
	}
	for _, be := range []bool{false, true} {
		doc, err := Parse(encode("rules:\n  boundary: \u00e9\U0001F600\n", be))
		if err != nil {
			t.Fatal(err)
		}
		if n := lookup(doc, "rules", "boundary"); n == nil || n.Value != "\u00e9\U0001F600" {
			t.Errorf("UTF-16 (big endian %v): rules.boundary = %+v", be, n)
		}
		_, err = Parse(encode("a: [b\n", be))
		if err == nil || err.Error() != "yaml: line 1: did not find expected ',' or ']'" {
			t.Errorf("UTF-16 (big endian %v): error %v", be, err)
		}
	}
}

func TestShortTag(t *testing.T) {
	tests := []struct {
		n    *Node
		want string
	}{
		{&Node{}, "!!null"},
		{&Node{Kind: ScalarNode, Value: "12"}, "!!int"},
		{&Node{Kind: ScalarNode, Value: "12", Style: DoubleQuotedStyle}, "!!str"},
		{&Node{Kind: ScalarNode, Value: "yes"}, "!!str"},
		{&Node{Kind: ScalarNode, Value: "1e3"}, "!!float"},
		{&Node{Kind: ScalarNode, Value: "~"}, "!!null"},
		{&Node{Kind: ScalarNode, Tag: "tag:yaml.org,2002:str", Value: "1"}, "!!str"},
		{&Node{Kind: ScalarNode, Tag: "!", Value: "1"}, "!!int"},
		{&Node{Kind: MappingNode}, "!!map"},
		{&Node{Kind: SequenceNode, Tag: "!foo"}, "!foo"},
		{&Node{Kind: AliasNode, Alias: &Node{Kind: SequenceNode}}, "!!seq"},
		{&Node{Kind: DocumentNode}, ""},
	}
	for _, tt := range tests {
		if got := tt.n.ShortTag(); got != tt.want {
			t.Errorf("(%+v).ShortTag() = %q, want %q", tt.n, got, tt.want)
		}
	}
}
