package analyzer

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode"

	"declscope/internal/checker"
	"declscope/internal/load"
	"declscope/internal/yaml"
)

const baselineUsage = `Usage: declscope baseline [flags] [packages]

Records every current violation so that adopting declscope does not require
fixing them all at once. New violations are still reported.

Each package's entries go to the baseline the analyzer will consult for that
package: the one named by its nearest config file, else the nearest existing
default-named baseline at or below the working directory, else
.declscope-baseline.yaml in the working directory. Every file written is
regenerated wholesale; baselines above the working directory are left alone.

Wholesale means a narrower pattern drops the entries of every package it does
not load from the files it writes. -merge keeps them: it reads each file first,
replaces the entries of the packages this run loaded and keeps the rest. A file
-merge cannot parse stops the run.

What declscope shrink reports is recorded too, into the same files, so that
shrink passes on what the baseline already holds. That loads the whole module
once more. -shrink=false skips it, for a module that does not run shrink.

`

const baselineHeader = `# declscope baseline
#
# Violations recorded here are suppressed; new ones are still reported.
# Regenerate with:
#
#     declscope baseline ./...
#
# Do not edit by hand. An entry disappears when its violation is fixed, so the
# diff of a regeneration is the record of what was cleaned up.
`

// BaselineMain runs "declscope baseline".
func BaselineMain(args []string) int {
	fs := flag.NewFlagSet("declscope baseline", flag.ExitOnError)
	config := fs.String("config", "", "path to a declscope YAML config file")
	merge := fs.Bool("merge", false, "keep the entries of packages these patterns do not load")
	out := fs.String("o", "", "write every entry to this one file instead")
	withShrink := fs.Bool("shrink", true, "also record what declscope shrink reports (-shrink=false skips it)")
	fs.Usage = func() {
		fmt.Fprint(fs.Output(), baselineUsage)
		fs.PrintDefaults()
	}
	fs.Parse(args)
	patterns := fs.Args()
	if len(patterns) == 0 {
		patterns = []string{"./..."}
	}
	fail := func(format string, a ...any) int {
		fmt.Fprintf(os.Stderr, "declscope baseline: "+format+"\n", a...)
		return 1
	}

	pkgs, err := load.Load(&load.Config{Tests: true}, patterns...)
	if err != nil {
		return fail("%v", err)
	}
	if n := load.PrintErrors(os.Stderr, pkgs); n > 0 {
		return fail("packages contain errors")
	}
	us := units(pkgs)
	if len(us) == 0 {
		return fail("%s matched no packages", strings.Join(patterns, " "))
	}
	if _, none, err := matchedPackages(patterns); err == nil {
		for _, p := range none {
			fmt.Fprintf(os.Stderr, "declscope baseline: warning: %q matched no packages\n", p)
		}
	}

	cwd, _ := os.Getwd()
	entries := Baseline{}
	targets := make(map[string]string) // package path to file
	var unreachable []*unit
	for _, u := range us {
		rules, err := RulesFor(u.pkg, *config)
		if err != nil {
			return fail("%v", err)
		}
		target := *out
		if target == "" {
			var ok bool
			target, ok = baselineTarget(u.pkg, rules, cwd)
			if !ok {
				unreachable = append(unreachable, u)
				continue
			}
		}
		targets[u.path] = target
		res := Analyze(passFor(u.pkg), rules, nil)
		for _, f := range append(append([]*finding(nil), res.Findings...), res.Covered...) {
			if res.Ignored[f] || f.coveredBy != nil && len(res.Model.covering(f)) > 0 {
				continue
			}
			ns, name, ok := res.Model.baselineKey(f)
			if !ok {
				continue
			}
			entries.add(u.path, f.rule, ns, name)
		}
	}
	if len(unreachable) > 0 {
		fmt.Fprintf(os.Stderr, "declscope baseline: %s in %s would not be found from these packages, because the lookup from them never reaches the working directory:\n", BaselineName, cwd)
		for _, u := range unreachable {
			fmt.Fprintf(os.Stderr, "  %s (%s)\n", u.path, u.pkg.Dir)
		}
		fmt.Fprintf(os.Stderr, "run from a directory their lookup passes through, name a baseline in a config file near them, or pass -o\n")
		return 1
	}

	skipped := make(map[string]bool)
	if *withShrink {
		res, err := runShrink(patterns, *config, "baseline", false)
		if err != nil {
			return fail("declscope shrink: %v (pass -shrink=false to record the analyzer's findings alone)", err)
		}
		skipped = res.skipped
		for _, f := range res.all {
			if f.ignored || f.cand == nil {
				continue
			}
			if _, ok := targets[f.unit.path]; !ok {
				continue
			}
			entries.add(f.unit.path, "overexported", f.ns, f.key)
		}
	}

	// Gather the entries of each file.
	files := make(map[string]Baseline)
	for _, t := range targets {
		if files[t] == nil {
			files[t] = Baseline{}
		}
	}
	for pkg, rules := range entries {
		files[targets[pkg]][pkg] = rules
	}
	var names []string
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	if *merge {
		for _, name := range names {
			old, err := readForMerge(name)
			if err != nil {
				return fail("%s cannot be parsed: %v; run without -merge to replace it", name, err)
			}
			for pkg, rules := range old {
				if _, loaded := targets[pkg]; !loaded {
					files[name][pkg] = rules
					continue
				}
				// A loaded package keeps shrink's entries when this run
				// recorded none for it.
				if oe := rules["overexported"]; oe != nil && (!*withShrink || skipped[pkg]) {
					if files[name][pkg] == nil {
						files[name][pkg] = map[string]map[string][]string{}
					}
					files[name][pkg]["overexported"] = oe
				}
			}
		}
	}
	for _, name := range names {
		b := files[name]
		if err := os.MkdirAll(filepath.Dir(name), 0o755); err != nil {
			return fail("%v", err)
		}
		if err := os.WriteFile(name, []byte(baselineHeader+encodeBaseline(b)), 0644); err != nil {
			return fail("%v", err)
		}
		fmt.Fprintf(os.Stderr, "declscope: recorded %d violation(s) in %s\n", b.Count(), name)
	}
	return 0
}

func readForMerge(path string) (Baseline, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Baseline{}, nil
		}
		return nil, err
	}
	return ParseBaseline(data)
}

func (b Baseline) add(pkg, rule, ns, name string) {
	if b[pkg] == nil {
		b[pkg] = map[string]map[string][]string{}
	}
	if b[pkg][rule] == nil {
		b[pkg][rule] = map[string][]string{}
	}
	for _, n := range b[pkg][rule][ns] {
		if n == name {
			return
		}
	}
	b[pkg][rule][ns] = append(b[pkg][rule][ns], name)
}

// baselineTarget finds the file a package's entries go to.
func baselineTarget(pkg *load.Package, rules *Rules, cwd string) (string, bool) {
	if rules.BaselineSet {
		return rules.Baseline, true
	}
	for d := pkg.Dir; ; d = filepath.Dir(d) {
		rel, err := filepath.Rel(cwd, d)
		if err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
			break
		}
		p := filepath.Join(d, BaselineName)
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p, true
		}
		if d == cwd || d == filepath.Dir(d) {
			return filepath.Join(cwd, BaselineName), true
		}
	}
	return "", false
}

func passFor(p *load.Package) *checker.Pass {
	return &checker.Pass{Pkg: p, Fset: p.Fset, Files: p.Syntax, Types: p.Types, TypesInfo: p.TypesInfo}
}

// encodeBaseline renders entries the way yaml.v3 marshals the map.
func encodeBaseline(b Baseline) string {
	if len(b) == 0 {
		return "packages: {}\n"
	}
	var sb strings.Builder
	sb.WriteString("packages:\n")
	for _, pkg := range yamlKeys(b) {
		sb.WriteString("  " + yamlScalar(pkg) + ":\n")
		rules := b[pkg]
		for _, rule := range yamlKeys(rules) {
			sb.WriteString("    " + yamlScalar(rule) + ":\n")
			nss := rules[rule]
			for _, ns := range yamlKeys(nss) {
				names := append([]string(nil), nss[ns]...)
				sort.Strings(names)
				if len(names) == 0 {
					sb.WriteString("      " + yamlScalar(ns) + ": []\n")
					continue
				}
				sb.WriteString("      " + yamlScalar(ns) + ":\n")
				for _, n := range names {
					sb.WriteString("        - " + yamlScalar(n) + "\n")
				}
			}
		}
	}
	return sb.String()
}

// yamlKeys sorts map keys the way yaml.v3 does: digit runs compare as
// numbers, letters before other characters only after digits.
func yamlKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return yamlKeyLess(keys[i], keys[j]) })
	return keys
}

func yamlKeyLess(a, b string) bool {
	ar, br := []rune(a), []rune(b)
	digits := false
	for i := 0; i < len(ar) && i < len(br); i++ {
		if ar[i] == br[i] {
			digits = unicode.IsDigit(ar[i])
			continue
		}
		al := unicode.IsLetter(ar[i])
		bl := unicode.IsLetter(br[i])
		if al && bl {
			return ar[i] < br[i]
		}
		if al || bl {
			if digits {
				return al
			}
			return bl
		}
		var ai, bi int
		var an, bn int64
		if ar[i] == '0' || br[i] == '0' {
			for j := i - 1; j >= 0 && unicode.IsDigit(ar[j]); j-- {
				if ar[j] != '0' {
					an = 1
					bn = 1
					break
				}
			}
		}
		for ai = i; ai < len(ar) && unicode.IsDigit(ar[ai]); ai++ {
			an = an*10 + int64(ar[ai]-'0')
		}
		for bi = i; bi < len(br) && unicode.IsDigit(br[bi]); bi++ {
			bn = bn*10 + int64(br[bi]-'0')
		}
		if an != bn {
			return an < bn
		}
		if ai != bi {
			return ai < bi
		}
		return ar[i] < br[i]
	}
	return len(ar) < len(br)
}

var base60 = regexp.MustCompile(`^[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+(?:\.[0-9_]*)?$`)

// yamlScalar renders a string as yaml.v3 does: plain when it reads back as
// the same string, double-quoted when it would resolve to another type,
// single-quoted when plain style is not allowed.
func yamlScalar(s string) string {
	switch s {
	case "y", "Y", "yes", "Yes", "YES", "on", "On", "ON",
		"n", "N", "no", "No", "NO", "off", "Off", "OFF":
		return fmt.Sprintf("%q", s)
	}
	if (&yaml.Node{Kind: yaml.ScalarNode, Value: s}).ShortTag() != "!!str" || base60.MatchString(s) {
		return fmt.Sprintf("%q", s)
	}
	if !plainAllowed(s) {
		return "'" + strings.ReplaceAll(s, "'", "''") + "'"
	}
	return s
}

// plainAllowed reports whether a block-context plain scalar may hold s.
func plainAllowed(s string) bool {
	if s == "" || strings.HasPrefix(s, "---") || strings.HasPrefix(s, "...") {
		return false
	}
	if s[0] == ' ' || s[len(s)-1] == ' ' {
		return false
	}
	for i, r := range s {
		follows := i+1 >= len(s) || s[i+1] == ' '
		if i == 0 {
			switch r {
			case '#', ',', '[', ']', '{', '}', '&', '*', '!', '|', '>', '\'', '"', '%', '@', '`':
				return false
			case '?', ':', '-':
				if follows {
					return false
				}
			}
			continue
		}
		switch r {
		case ':':
			if follows {
				return false
			}
		case '#':
			if s[i-1] == ' ' {
				return false
			}
		}
		if !unicode.IsPrint(r) {
			return false
		}
	}
	return true
}
