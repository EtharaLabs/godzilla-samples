package analyzer

import (
	"path/filepath"
	"strings"
	"unicode"
	"unicode/utf8"
)

// initialisms are the words Go spells in one case throughout.
var initialisms = map[string]bool{
	"ACL": true, "API": true, "ASCII": true, "CPU": true, "CSS": true, "DNS": true,
	"EOF": true, "GUID": true, "HTML": true, "HTTP": true, "HTTPS": true, "ID": true,
	"IP": true, "JSON": true, "LHS": true, "QPS": true, "RAM": true, "RHS": true,
	"RPC": true, "SLA": true, "SMTP": true, "SQL": true, "SSH": true, "TCP": true,
	"TLS": true, "TTL": true, "UDP": true, "UI": true, "UID": true, "UUID": true,
	"URI": true, "URL": true, "UTF8": true, "VM": true, "XML": true, "XMPP": true,
	"XSRF": true, "XSS": true,
}

func isInitialism(s string) bool { return initialisms[strings.ToUpper(s)] }

// upperWord spells the leading word of s as it starts a word inside a
// camelCase name: "id" becomes "ID", "ids" "IDs", "user" "User".
func upperWord(s string) string {
	if s == "" {
		return s
	}
	if isInitialism(s) {
		return strings.ToUpper(s)
	}
	if strings.HasSuffix(s, "s") && len(s) > 1 && isInitialism(s[:len(s)-1]) {
		return strings.ToUpper(s[:len(s)-1]) + "s"
	}
	// The leading run of lower-case letters is the first word.
	n := 0
	for n < len(s) {
		r, size := utf8.DecodeRuneInString(s[n:])
		if !unicode.IsLower(r) {
			break
		}
		n += size
	}
	if n == 0 {
		return s
	}
	run, rest := s[:n], s[n:]
	if isInitialism(run) {
		return strings.ToUpper(run) + rest
	}
	if strings.HasSuffix(run, "s") && len(run) > 1 && isInitialism(run[:len(run)-1]) {
		return strings.ToUpper(run[:len(run)-1]) + "s" + rest
	}
	r, size := utf8.DecodeRuneInString(run)
	return string(unicode.ToUpper(r)) + run[size:] + rest
}

// lowerWord lowers the leading word of s the way Go unexports a name:
// "HTTPServer" becomes "httpServer", "URLs" "urls", "IPv4" "ipv4".
func lowerWord(s string) string {
	if s == "" {
		return s
	}
	if isInitialism(s) {
		return strings.ToLower(s)
	}
	if strings.HasSuffix(s, "s") && len(s) > 1 && isInitialism(s[:len(s)-1]) {
		return strings.ToLower(s)
	}
	// The leading run of upper-case letters.
	var runes []rune
	n := 0
	for n < len(s) {
		r, size := utf8.DecodeRuneInString(s[n:])
		if !unicode.IsUpper(r) {
			break
		}
		runes = append(runes, r)
		n += size
	}
	if n == 0 {
		return s
	}
	if n == len(s) {
		return strings.ToLower(s)
	}
	next, _ := utf8.DecodeRuneInString(s[n:])
	if !unicode.IsLower(next) || len(runes) == 1 {
		return strings.ToLower(s[:n]) + s[n:]
	}
	run := string(runes)
	lastSize := utf8.RuneLen(runes[len(runes)-1])
	head := run[:len(run)-lastSize]
	if !isInitialism(head) && isInitialism(run) {
		return strings.ToLower(run) + s[n:]
	}
	return strings.ToLower(head) + s[n-lastSize:]
}

// fileNamespace derives a namespace from a Go file name.
func fileNamespace(filename string) string {
	stem := strings.TrimSuffix(filename, ".go")
	if strings.HasSuffix(filename, "_test.go") {
		stem = strings.TrimSuffix(stem, "_test")
	}
	head, tail, hasDot := strings.Cut(stem, ".")
	head = stripOSArch(head)
	if hasDot {
		stem = head + "." + tail
	} else {
		stem = head
	}
	var segs []string
	start := -1
	for i, r := range stem {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			if start < 0 {
				start = i
			}
			continue
		}
		if start >= 0 {
			segs = append(segs, stem[start:i])
			start = -1
		}
	}
	if start >= 0 {
		segs = append(segs, stem[start:])
	}
	var b strings.Builder
	for i, seg := range segs {
		if i == 0 {
			b.WriteString(lowerWord(seg))
		} else {
			b.WriteString(upperWord(seg))
		}
	}
	return b.String()
}

// stripOSArch removes a GOOS or GOARCH suffix that go/build reads as a
// build constraint.
func stripOSArch(name string) string {
	i := strings.Index(name, "_")
	if i < 0 {
		return name
	}
	l := strings.Split(name[i:], "_")
	if n := len(l); n > 0 && l[n-1] == "test" {
		// A "_test" suffix here is part of the name, not a test marker,
		// but go/build skips it when looking for constraints.
		l = l[:n-1]
		n := len(l)
		if n >= 2 && knownOS[l[n-2]] && knownArch[l[n-1]] {
			return name
		}
		if n >= 1 && (knownOS[l[n-1]] || knownArch[l[n-1]]) {
			return name
		}
		return name
	}
	n := len(l)
	if n >= 2 && knownOS[l[n-2]] && knownArch[l[n-1]] {
		suffix := "_" + l[n-2] + "_" + l[n-1]
		return strings.TrimSuffix(name, suffix)
	}
	if n >= 1 && (knownOS[l[n-1]] || knownArch[l[n-1]]) {
		return strings.TrimSuffix(name, "_"+l[n-1])
	}
	return name
}

var knownOS = map[string]bool{
	"aix": true, "android": true, "darwin": true, "dragonfly": true, "freebsd": true,
	"hurd": true, "illumos": true, "ios": true, "js": true, "linux": true, "nacl": true,
	"netbsd": true, "openbsd": true, "plan9": true, "solaris": true, "wasip1": true,
	"windows": true, "zos": true,
}

var knownArch = map[string]bool{
	"386": true, "amd64": true, "amd64p32": true, "arm": true, "armbe": true, "arm64": true,
	"arm64be": true, "loong64": true, "mips": true, "mipsle": true, "mips64": true,
	"mips64le": true, "mips64p32": true, "mips64p32le": true, "ppc": true, "ppc64": true,
	"ppc64le": true, "riscv": true, "riscv64": true, "s390": true, "s390x": true,
	"sparc": true, "sparc64": true, "wasm": true,
}

// validNamespace reports whether s may name a namespace: an identifier that
// does not start with an upper-case letter or a digit.
func validNamespace(s string) bool {
	if s == "" {
		return false
	}
	for i, r := range s {
		if i == 0 {
			if !(unicode.IsLetter(r) || r == '_') || unicode.IsUpper(r) {
				return false
			}
			continue
		}
		if !(unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_') {
			return false
		}
	}
	return true
}

// prefixable reports whether a namespace can start an identifier whose
// exportedness is preserved: its first character needs a capital form.
func prefixable(ns string) bool {
	r, _ := utf8.DecodeRuneInString(ns)
	if !unicode.IsLetter(r) {
		return false
	}
	return unicode.ToUpper(r) != unicode.ToLower(r)
}

// wordStart reports whether a word starts at byte offset i of name.
func wordStart(name string, i int) bool {
	if i == 0 {
		return true
	}
	r, _ := utf8.DecodeRuneInString(name[i:])
	prev, _ := utf8.DecodeLastRuneInString(name[:i])
	if unicode.IsUpper(r) {
		if !unicode.IsUpper(prev) {
			return true
		}
		_, size := utf8.DecodeRuneInString(name[i:])
		if i+size < len(name) {
			next, _ := utf8.DecodeRuneInString(name[i+size:])
			if unicode.IsLower(next) {
				return true
			}
		}
		return false
	}
	if unicode.IsLetter(r) && unicode.IsDigit(prev) {
		return true
	}
	return false
}

// carries reports whether name contains word, ignoring case, starting at a
// word boundary.
func carries(name, word string) bool {
	if word == "" {
		return false
	}
	lw := []rune(strings.ToLower(word))
	runes := []rune(name)
	offsets := make([]int, len(runes)+1)
	off := 0
	for i, r := range runes {
		offsets[i] = off
		off += utf8.RuneLen(r)
	}
	offsets[len(runes)] = off
	for i := 0; i+len(lw) <= len(runes); i++ {
		if !wordStart(name, offsets[i]) {
			continue
		}
		match := true
		for j, r := range lw {
			if unicode.ToLower(runes[i+j]) != r {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}

func isVowel(b byte) bool {
	switch b {
	case 'a', 'e', 'i', 'o', 'u':
		return true
	}
	return false
}

// forms lists the spellings that carry word: the word itself and the
// inflections that change its spelling.
func forms(word string) []string {
	w := strings.ToLower(word)
	out := []string{w}
	n := len(w)
	if n >= 2 && w[n-1] == 'e' && !isVowel(w[n-2]) {
		out = append(out, w[:n-1]+"ing")
	}
	if n >= 2 && w[n-1] == 'y' && !isVowel(w[n-2]) {
		out = append(out, w[:n-1]+"ies", w[:n-1]+"ied")
	}
	return out
}

// looksInflected reports whether a namespace reads as an inflected form, so
// that a name may spell its base instead.
func looksInflected(ns string) bool {
	for _, suffix := range []string{"ing", "ies", "ied"} {
		if !strings.HasSuffix(ns, suffix) {
			continue
		}
		stem := ns[:len(ns)-len(suffix)]
		if stem == "" || isVowel(stem[len(stem)-1]) {
			return false
		}
		for i := 0; i < len(stem); i++ {
			if isVowel(stem[i]) {
				return true
			}
		}
		return false
	}
	return false
}

// baseName returns the file name of a path.
func baseName(path string) string { return filepath.Base(path) }
