package skill

import (
	"bytes"
	"strings"
)

// Frontmatter keys an install adds to SKILL.md. They describe the install
// itself, so they are left out of the digest.
const (
	keyBy      = "x-embedded-by"
	keyVersion = "x-embedded-version"
	keyAt      = "x-embedded-at"
	keyDigest  = "x-embedded-digest"
)

var metaKeys = map[string]bool{keyBy: true, keyVersion: true, keyAt: true, keyDigest: true}

var bom = []byte("\xef\xbb\xbf")

// frontmatter locates the YAML frontmatter of a SKILL.md.
type frontmatter struct {
	prefix []byte   // a byte order mark, if the file starts with one
	lines  [][]byte // the lines after prefix, each with its line ending
	end    int      // index of the closing delimiter; lines[0] opens
}

// findFrontmatter reports the frontmatter of data, which must open on the
// first line and be closed by a later delimiter line.
func findFrontmatter(data []byte) (frontmatter, bool) {
	var prefix []byte
	if bytes.HasPrefix(data, bom) {
		prefix, data = data[:len(bom)], data[len(bom):]
	}
	lines := splitLines(data)
	if len(lines) == 0 || !isDelimiter(lines[0]) {
		return frontmatter{}, false
	}
	for i := 1; i < len(lines); i++ {
		if isDelimiter(lines[i]) {
			return frontmatter{prefix: prefix, lines: lines, end: i}, true
		}
	}
	return frontmatter{}, false
}

func splitLines(b []byte) [][]byte {
	var lines [][]byte
	for len(b) > 0 {
		i := bytes.IndexByte(b, '\n')
		if i < 0 {
			lines = append(lines, b)
			break
		}
		lines = append(lines, b[:i+1])
		b = b[i+1:]
	}
	return lines
}

func isDelimiter(line []byte) bool {
	return string(bytes.TrimRight(line, " \t\r\n")) == "---"
}

// field splits a frontmatter line into its key and value. An indented line
// continues the value above it and has no key of its own.
func field(line []byte) (key, value string, ok bool) {
	if len(line) == 0 || line[0] == ' ' || line[0] == '\t' {
		return "", "", false
	}
	k, v, found := strings.Cut(string(line), ":")
	if !found {
		return "", "", false
	}
	return strings.TrimSpace(k), unquote(strings.TrimSpace(v)), true
}

func unquote(s string) string {
	if len(s) >= 2 && (s[0] == '"' || s[0] == '\'') && s[len(s)-1] == s[0] {
		return s[1 : len(s)-1]
	}
	return s
}

// parseMeta returns the top-level keys of the frontmatter of data. A key
// given twice takes its last value.
func parseMeta(data []byte) (map[string]string, bool) {
	fm, ok := findFrontmatter(data)
	if !ok {
		return nil, false
	}
	meta := make(map[string]string)
	for _, line := range fm.lines[1:fm.end] {
		if k, v, ok := field(line); ok {
			meta[k] = v
		}
	}
	return meta, true
}

// normalize removes the install metadata from a SKILL.md, giving back the
// file as it was embedded. A frontmatter left with nothing in it is dropped.
func normalize(data []byte) []byte {
	fm, ok := findFrontmatter(data)
	if !ok {
		return data
	}
	var kept [][]byte
	empty := true
	for _, line := range fm.lines[1:fm.end] {
		if k, _, ok := field(line); ok && metaKeys[k] {
			continue
		}
		kept = append(kept, line)
		if len(bytes.TrimSpace(line)) > 0 {
			empty = false
		}
	}
	var b bytes.Buffer
	b.Write(fm.prefix)
	if !empty {
		b.Write(fm.lines[0])
		for _, line := range kept {
			b.Write(line)
		}
		b.Write(fm.lines[fm.end])
	}
	for _, line := range fm.lines[fm.end+1:] {
		b.Write(line)
	}
	return b.Bytes()
}

// render adds the install metadata to the end of the frontmatter of data,
// creating a frontmatter if there is none.
func render(data []byte, meta [][2]string) []byte {
	var m bytes.Buffer
	for _, kv := range meta {
		m.WriteString(kv[0] + ": " + kv[1] + "\n")
	}
	fm, ok := findFrontmatter(data)
	if !ok {
		var b bytes.Buffer
		b.WriteString("---\n")
		b.Write(m.Bytes())
		b.WriteString("---\n")
		b.Write(data)
		return b.Bytes()
	}
	var b bytes.Buffer
	b.Write(fm.prefix)
	for i, line := range fm.lines {
		if i == fm.end {
			b.Write(m.Bytes())
		}
		b.Write(line)
	}
	return b.Bytes()
}
