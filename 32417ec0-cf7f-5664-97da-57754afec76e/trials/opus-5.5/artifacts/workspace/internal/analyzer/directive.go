package analyzer

import (
	"go/ast"
	"go/token"
	"sort"
	"strings"
)

// ruleNames lists the rules an ignore may name, in the order messages list them.
var ruleNames = []string{"boundary", "qualify", "surplus", "unused", "directive", "filter", "overexported"}

func knownRule(name string) bool {
	for _, r := range ruleNames {
		if r == name {
			return true
		}
	}
	return false
}

// directive is one //declscope: comment.
type directive struct {
	comment *ast.Comment
	file    *fileInfo
	name    string // directive name, e.g. "shared"
	arg     string // argument, trimmed
	rules   []string
	bare    bool // an ignore naming no rule

	fileLevel bool
	target    *target // the declaration it binds to, if any

	// effective is false when the directive is reported by the directive
	// rule and has no effect.
	effective bool
	// silent marks a directive that has no effect without being reported
	// itself (a duplicate silenced elsewhere is still reported).
	used bool // for ignores: silenced at least one report
}

func (d *directive) pos() token.Pos { return d.comment.Slash }

func (d *directive) isScope() bool { return d.name == "shared" || d.name == "private" }

// ruleText renders the rules of an ignore as they appear in messages.
func (d *directive) ruleText() string { return strings.Join(d.rules, ",") }

// covers reports whether an effective ignore silences the named rule.
func (d *directive) covers(rule string) bool {
	if d.bare {
		return rule != "overexported"
	}
	for _, r := range d.rules {
		if r == rule {
			return true
		}
	}
	return false
}

// sameIgnore reports whether two ignores name the same rules in any order.
func sameIgnore(a, b *directive) bool {
	if a.bare != b.bare {
		return false
	}
	x := append([]string(nil), a.rules...)
	y := append([]string(nil), b.rules...)
	sort.Strings(x)
	sort.Strings(y)
	x = dedup(x)
	y = dedup(y)
	if len(x) != len(y) {
		return false
	}
	for i := range x {
		if x[i] != y[i] {
			return false
		}
	}
	return true
}

func dedup(s []string) []string {
	var out []string
	for i, v := range s {
		if i == 0 || v != s[i-1] {
			out = append(out, v)
		}
	}
	return out
}

// parseComment classifies a comment. It returns the directive name and its
// argument; malformed reports a comment that starts with "declscope:" but
// is not written as //declscope:name.
func parseComment(text string) (name, arg string, ok, malformed bool) {
	const prefix = "//declscope:"
	if strings.HasPrefix(text, prefix) {
		body := text[len(prefix):]
		if body == "" || !isNameStart(body[0]) {
			return "", "", false, true
		}
		if i := strings.Index(body, "//"); i >= 0 {
			body = body[:i]
		}
		name = body
		if i := strings.IndexAny(body, " \t"); i >= 0 {
			name, arg = body[:i], body[i+1:]
		}
		return name, strings.TrimSpace(arg), true, false
	}
	var content string
	switch {
	case strings.HasPrefix(text, "//"):
		content = text[2:]
	case strings.HasPrefix(text, "/*"):
		content = strings.TrimSuffix(text[2:], "*/")
	default:
		return "", "", false, false
	}
	content = strings.TrimLeft(content, " \t\r\n")
	if strings.HasPrefix(content, "declscope:") {
		return "", "", false, true
	}
	return "", "", false, false
}

func isNameStart(b byte) bool {
	return 'a' <= b && b <= 'z' || '0' <= b && b <= '9'
}

// targetKind classifies the declaration nodes a directive binds to.
type targetKind int

const (
	tFunc  targetKind = iota // a FuncDecl
	tGen                     // a GenDecl without parentheses
	tBlock                   // a GenDecl with parentheses
	tSpec                    // a spec inside a block
	tField                   // a field or interface method of a type
)

// target is a declaration node: what a directive binds to.
type target struct {
	kind targetKind
	node ast.Node
	file *fileInfo
	// anchors are the declarations this node declares itself.
	anchors []*decl
	// parent is the block of a spec, or the type of a field.
	parent *target
	// typeDecl is the type a field belongs to.
	typeDecl *decl
	// children are the specs of a block or the fields of a type.
	children []*target

	directives []*directive
	scope      *directive   // the effective scope directive
	ignores    []*directive // the effective ignores
}

// start and end lines of a target's node.
func (t *target) lines(fset *token.FileSet) (int, int) {
	return fset.Position(t.node.Pos()).Line, fset.Position(t.node.End()).Line
}
