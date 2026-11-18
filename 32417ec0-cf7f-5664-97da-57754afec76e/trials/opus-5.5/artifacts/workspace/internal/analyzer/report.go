package analyzer

import (
	"flag"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"unicode/utf8"

	"declscope/internal/load"
)

// column describes one column of a markdown table.
type column struct {
	header  string
	numeric bool
}

// writeTable renders a markdown table with padded cells. A numeric column
// is right-aligned unless it holds nothing but dashes.
func writeTable(w io.Writer, cols []column, rows [][]string) {
	widths := make([]int, len(cols))
	right := make([]bool, len(cols))
	for i, c := range cols {
		widths[i] = utf8.RuneCountInString(c.header)
		for _, r := range rows {
			if n := utf8.RuneCountInString(r[i]); n > widths[i] {
				widths[i] = n
			}
			if c.numeric && r[i] != "-" {
				right[i] = true
			}
		}
	}
	pad := func(s string, i int) string {
		n := widths[i] - utf8.RuneCountInString(s)
		if right[i] {
			return strings.Repeat(" ", n) + s
		}
		return s + strings.Repeat(" ", n)
	}
	line := func(cells []string) {
		var b strings.Builder
		b.WriteString("|")
		for i, c := range cells {
			b.WriteString(" " + pad(c, i) + " |")
		}
		fmt.Fprintln(w, b.String())
	}
	headers := make([]string, len(cols))
	seps := make([]string, len(cols))
	for i, c := range cols {
		headers[i] = c.header
		if right[i] {
			seps[i] = strings.Repeat("-", widths[i]-1) + ":"
		} else {
			seps[i] = strings.Repeat("-", widths[i])
		}
	}
	line(headers)
	var b strings.Builder
	b.WriteString("|")
	for _, s := range seps {
		b.WriteString(" " + s + " |")
	}
	fmt.Fprintln(w, b.String())
	for _, r := range rows {
		line(r)
	}
}

// subcommand holds the flags shared by survey and inspect.
type subcommand struct {
	name        string
	fs          *flag.FlagSet
	config      string
	format      string
	test        bool
	allowErrors bool
}

func newSubcommand(name, usage string, allowErrors bool, configUsage string) *subcommand {
	sc := &subcommand{name: name}
	fs := flag.NewFlagSet("declscope "+name, flag.ExitOnError)
	if allowErrors {
		fs.BoolVar(&sc.allowErrors, "allow-errors", false, "measure anyway when some packages do not type-check")
	}
	fs.StringVar(&sc.config, "config", "", configUsage)
	fs.StringVar(&sc.format, "format", "markdown", "output format: markdown or json")
	fs.BoolVar(&sc.test, "test", true, "measure *_test.go files as well")
	fs.Usage = func() {
		fmt.Fprint(fs.Output(), usage)
		fs.PrintDefaults()
	}
	sc.fs = fs
	return sc
}

func (sc *subcommand) fail(format string, args ...any) int {
	fmt.Fprintf(os.Stderr, "declscope %s: %s\n", sc.name, fmt.Sprintf(format, args...))
	return 1
}

// unit is one measured package: a package merged with its in-package test
// variant, or an external test package.
type unit struct {
	path     string
	pkg      *load.Package   // the variant measured: the test variant if any
	variants []*load.Package // every variant, the plain package first
}

// illTyped reports whether some variant of the unit does not type-check.
func (u *unit) illTyped() bool {
	for _, v := range u.variants {
		if v.IllTyped {
			return true
		}
	}
	return false
}

// failure describes the first variant that does not type-check.
func (u *unit) failure() string {
	for _, v := range u.variants {
		if v.IllTyped {
			return failureOf(v)
		}
	}
	return ""
}

// isXTest reports whether p is an external test package.
func isXTest(p *load.Package) bool {
	return p.ForTest != "" && p.PkgPath != p.ForTest
}

// units selects the packages to measure from what the loader returned.
func units(pkgs []*load.Package) []*unit {
	byPath := make(map[string]*unit)
	var out []*unit
	for _, p := range pkgs {
		if isTestMain(p) {
			continue
		}
		u := byPath[p.PkgPath]
		if u == nil {
			u = &unit{path: p.PkgPath, pkg: p, variants: []*load.Package{p}}
			byPath[p.PkgPath] = u
			out = append(out, u)
			continue
		}
		if p.ForTest != "" {
			u.pkg = p
			u.variants = append(u.variants, p)
		} else {
			u.variants = append([]*load.Package{p}, u.variants...)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].path < out[j].path })
	return out
}

// isTestMain reports whether p is the generated main package of a test.
func isTestMain(p *load.Package) bool {
	return p.Name == "main" && strings.HasSuffix(p.ID, ".test") && p.ForTest == "" && !strings.Contains(p.ID, " ")
}

// failure describes why a package does not type-check.
func failureOf(p *load.Package) string {
	if len(p.Errors) > 0 {
		return describeError(firstError(p))
	}
	var dep *load.Package
	seen := make(map[*load.Package]bool)
	var find func(p *load.Package) bool
	find = func(p *load.Package) bool {
		paths := make([]string, 0, len(p.Imports))
		for path := range p.Imports {
			paths = append(paths, path)
		}
		sort.Strings(paths)
		for _, path := range paths {
			imp := p.Imports[path]
			if seen[imp] {
				continue
			}
			seen[imp] = true
			if !imp.IllTyped {
				continue
			}
			if len(imp.Errors) > 0 {
				dep = imp
				return true
			}
			if find(imp) {
				return true
			}
		}
		return false
	}
	if find(p) && dep != nil {
		return "imports " + dep.PkgPath + ": " + describeError(firstError(dep))
	}
	return "does not type-check"
}

func firstError(p *load.Package) load.Error {
	for _, e := range p.Errors {
		if e.Kind != load.ListError {
			return e
		}
	}
	// A dependency is checked without its function bodies; check it again
	// whole to find what it would report on its own.
	for _, e := range p.Errors {
		if e.Kind == load.ParseError {
			return e
		}
	}
	if errs := load.Recheck(p); len(errs) > 0 {
		return errs[0]
	}
	return p.Errors[0]
}

func describeError(e load.Error) string {
	msg := e.Msg
	if e.Pos != "" && e.Pos != "-" {
		msg = e.Pos + ": " + msg
	}
	return strings.ReplaceAll(msg, "\n", " ")
}

func plural(n int, one, many string) string {
	if n == 1 {
		return fmt.Sprintf("%d %s", n, one)
	}
	return fmt.Sprintf("%d %s", n, many)
}

func num(asked bool, n int) string {
	if !asked {
		return "-"
	}
	return fmt.Sprint(n)
}

// rulesText describes the rules in force.
func rulesText(r *Rules) string {
	parts := []string{}
	if r.Boundary {
		parts = append(parts, "boundary on")
	} else {
		parts = append(parts, "boundary off")
	}
	parts = append(parts, "qualify "+r.Qualify)
	if r.Exported {
		parts = append(parts, "exported")
	}
	parts = append(parts, "surplus "+r.Surplus, "unused "+r.Unused)
	return strings.Join(parts, ", ")
}

func chainText(chain []string) string {
	if len(chain) == 0 {
		return "built-in defaults"
	}
	var parts []string
	for _, c := range chain {
		parts = append(parts, "`"+c+"`")
	}
	return strings.Join(parts, " + ")
}
