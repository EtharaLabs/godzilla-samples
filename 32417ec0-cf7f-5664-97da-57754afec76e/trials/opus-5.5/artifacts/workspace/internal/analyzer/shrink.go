package analyzer

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"go/types"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"unicode"

	"declscope/internal/checker"
	"declscope/internal/load"
)

const shrinkUsage = `Usage: declscope shrink [flags] [packages]

Reports the exported declarations of internal packages that nothing outside
their package uses, and with -fix unexports them.

Every package of the module is loaded, whatever the patterns name: an importer
outside them still counts. In a workspace, every module of it is loaded. The
patterns only choose which packages to report on, and default to ./... They
mean what they mean to the go command: a pattern it rejects stops the run, and
one that matches no package is warned about. Build tags come from GOFLAGS, as
for the analyzer.

A fix is offered only where no use can exist outside the package. Where a use
is possible but cannot be proved, such as a type that escapes into an
interface, the report stays and says why no fix is offered.

`

// isInternal reports whether an import path has an internal element.
func isInternal(path string) bool {
	for _, e := range strings.Split(path, "/") {
		if e == "internal" {
			return true
		}
	}
	return false
}

// shrinkCand is an exported declaration of a judged package.
type shrinkCand struct {
	obj    types.Object
	name   string
	kind   string
	ident  *ast.Ident
	key    string // baseline name: Type.member for members and methods
	ns     string
	file   *fileInfo
	doc    *ast.CommentGroup
	target *target
	typeOf *types.TypeName // the type of a field or method
	setOf  *types.TypeName // the type of a const set
	unit   *shrinkUnit
	member bool
	method bool
	isTest bool

	external bool // used outside the package
	xtest    bool // used by the external tests
	setKept  bool // another value of its const set keeps its name
	ignored  bool // an ignore of overexported, or the baseline, keeps its name
	reason   string
	fixable  bool
}

type shrinkUnit struct {
	path  string
	pkg   *load.Package
	model *model
	cands []*shrinkCand
	rules *Rules
	noFix string // why no declaration of the package can be fixed
	base  Baseline
}

// ShrinkMain runs "declscope shrink".
func ShrinkMain(args []string) int {
	fs := flag.NewFlagSet("declscope shrink", flag.ExitOnError)
	config := fs.String("config", "", "path to a declscope YAML config file, for the baseline it names")
	fix := fs.Bool("fix", false, "unexport every declaration a fix is offered for")
	fs.Usage = func() {
		fmt.Fprint(fs.Output(), shrinkUsage)
		fs.PrintDefaults()
	}
	fs.Parse(args)
	patterns := fs.Args()
	if len(patterns) == 0 {
		patterns = []string{"./..."}
	}
	res, err := runShrink(patterns, *config, "shrink", true)
	if err != nil {
		fmt.Fprintf(os.Stderr, "declscope shrink: %v\n", err)
		return 1
	}
	var lines []*shrinkFinding
	for _, f := range res.findings {
		lines = append(lines, f)
	}
	if *fix {
		var unfixed []*shrinkFinding
		var fixed []*shrinkFinding
		for _, f := range lines {
			if f.fix != nil {
				fixed = append(fixed, f)
			} else {
				unfixed = append(unfixed, f)
			}
		}
		if err := applyShrinkFixes(res.fset, fixed); err != nil {
			fmt.Fprintf(os.Stderr, "declscope shrink: %v\n", err)
			return 1
		}
		lines = unfixed
	}
	for _, f := range lines {
		fmt.Fprintf(os.Stdout, "%s: %s\n", res.fset.Position(f.pos), f.message)
	}
	if len(lines) > 0 {
		return 3
	}
	return 0
}

type shrinkFinding struct {
	pos     token.Pos
	message string
	fix     []checker.TextEdit
	cand    *shrinkCand
	unit    *shrinkUnit
	ns      string
	key     string
	ignored bool
}

type shrinkResult struct {
	fset     *token.FileSet
	findings []*shrinkFinding
	units    []*shrinkUnit
	all      []*shrinkFinding // every finding before ignores and baselines
	skipped  map[string]bool
}

// goModules lists the main modules of the go command run here.
func goModules() ([]load.Module, error) {
	cmd := exec.Command("go", "list", "-m", "-json")
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("%s", strings.TrimSpace(errb.String()))
	}
	var mods []load.Module
	for dec := json.NewDecoder(&out); dec.More(); {
		var m load.Module
		if err := dec.Decode(&m); err != nil {
			return nil, err
		}
		mods = append(mods, m)
	}
	return mods, nil
}

// matched lists the packages the patterns select, and the patterns that
// select none.
func matchedPackages(patterns []string) (map[string]bool, []string, error) {
	args := append([]string{"list", "-e", "-json=ImportPath,Match,Error,DepOnly,Dir", "--"}, patterns...)
	cmd := exec.Command("go", args...)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		return nil, nil, fmt.Errorf("err: %v: stderr: %s", err, errb.String())
	}
	sel := make(map[string]bool)
	used := make(map[string]bool)
	var rejected []string
	for dec := json.NewDecoder(&out); dec.More(); {
		var p struct {
			ImportPath string
			Dir        string
			Match      []string
			DepOnly    bool
			Error      *struct{ Err string }
		}
		if err := dec.Decode(&p); err != nil {
			return nil, nil, err
		}
		if p.DepOnly {
			continue
		}
		if p.Error != nil {
			// The go command rejects the pattern, or cannot read the
			// package it names.
			rejected = append(rejected, strings.TrimRight(p.Error.Err, "\n"))
			continue
		}
		sel[p.ImportPath] = true
		for _, m := range p.Match {
			used[m] = true
		}
	}
	if len(rejected) > 0 {
		sort.Strings(rejected)
		return nil, nil, fmt.Errorf("%s", strings.Join(rejected, "\n"))
	}
	var none []string
	for _, p := range patterns {
		if !used[p] {
			none = append(none, p)
		}
	}
	return sel, none, nil
}

// runShrink judges the internal packages the patterns select. A failure
// that stops the run is returned; what it judges, warns about and leaves out
// is printed under the name of the command.
func runShrink(patterns []string, configPath, cmdName string, warn bool) (*shrinkResult, error) {
	selected, none, err := matchedPackages(patterns)
	if err != nil {
		return nil, err
	}
	if len(selected) == 0 {
		return nil, fmt.Errorf("%s matched no packages", strings.Join(patterns, " "))
	}
	if warn {
		for _, p := range none {
			fmt.Fprintf(os.Stderr, "declscope %s: warning: %q matched no packages\n", cmdName, p)
		}
	}
	mods, err := goModules()
	if err != nil {
		return nil, err
	}
	var all []string
	for _, m := range mods {
		all = append(all, m.Dir+string(filepath.Separator)+"...")
	}
	pkgs, err := load.Load(&load.Config{Tests: true}, all...)
	if err != nil {
		return nil, err
	}
	us := units(pkgs)
	// Every variant with errors of its own is named, by its own first error.
	seenFail := make(map[string]bool)
	var failed []string
	for _, p := range pkgs {
		if isTestMain(p) || len(p.Errors) == 0 {
			continue
		}
		line := p.PkgPath + ": " + failureOf(p)
		if !seenFail[line] {
			seenFail[line] = true
			failed = append(failed, line)
		}
	}
	if len(failed) > 0 {
		sort.Strings(failed)
		return nil, fmt.Errorf("these packages do not type-check, so no absence of a use means anything:\n  %s", strings.Join(failed, "\n  "))
	}
	loaded := make(map[string]bool)
	for _, u := range us {
		loaded[u.path] = true
	}

	res := &shrinkResult{skipped: make(map[string]bool)}
	if len(pkgs) > 0 {
		res.fset = pkgs[0].Fset
	}
	// Choose the packages to judge.
	var notJudged []string
	var paths []string
	for p := range selected {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	byPath := make(map[string]*unit)
	for _, u := range us {
		if !isXTest(u.pkg) {
			byPath[u.path] = u
		}
	}
	for _, path := range paths {
		if !isInternal(path) {
			continue
		}
		u := byPath[path]
		if u == nil {
			notJudged = append(notJudged, path+": ./... leaves it out, so this run does not load it")
			res.skipped[path] = true
			continue
		}
		if reason := skipReason(u.pkg); reason != "" {
			notJudged = append(notJudged, path+": "+reason)
			res.skipped[path] = true
			continue
		}
		rules, err := RulesFor(u.pkg, configPath)
		if err != nil {
			return nil, err
		}
		pass := &checker.Pass{Pkg: u.pkg, Fset: u.pkg.Fset, Files: u.pkg.Syntax, Types: u.pkg.Types, TypesInfo: u.pkg.TypesInfo}
		res.units = append(res.units, &shrinkUnit{path: path, pkg: u.pkg, model: newModel(pass, rules), rules: rules})
	}
	extra, more, err := moduleRanges(mods, res)
	if err != nil {
		return nil, err
	}
	notJudged = append(notJudged, more...)
	sort.Strings(notJudged)
	for _, s := range notJudged {
		fmt.Fprintf(os.Stderr, "declscope %s: not judged: %s\n", cmdName, s)
	}
	if res.fset == nil {
		return res, nil
	}
	// The baseline command regenerates the baseline, and never reads it.
	analyzeShrink(res, append(us, extra...), configPath, warn)
	return res, nil
}

// skipReason says why a package cannot be judged.
func skipReason(p *load.Package) string {
	if p.Name == "main" {
		return "package main"
	}
	if len(p.CgoFiles()) > 0 {
		return "the package uses cgo"
	}
	entries, err := os.ReadDir(p.Dir)
	if err == nil {
		for _, e := range entries {
			if e.IsDir() {
				continue
			}
			switch filepath.Ext(e.Name()) {
			case ".s", ".S", ".sx", ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".m", ".f", ".F", ".for", ".f90", ".swig", ".swigcxx", ".syso":
				return "the package holds non-Go files"
			}
		}
	}
	return ""
}

// applyShrinkFixes writes the renames of the fixable findings.
func applyShrinkFixes(fset *token.FileSet, fs []*shrinkFinding) error {
	type edit struct {
		start, end int
		text       string
	}
	byFile := make(map[string][]edit)
	for _, f := range fs {
		for _, e := range f.fix {
			tf := fset.File(e.Pos)
			byFile[tf.Name()] = append(byFile[tf.Name()], edit{tf.Offset(e.Pos), tf.Offset(e.End), string(e.NewText)})
		}
	}
	var files []string
	for name := range byFile {
		files = append(files, name)
	}
	sort.Strings(files)
	for _, name := range files {
		src, err := os.ReadFile(name)
		if err != nil {
			return err
		}
		edits := byFile[name]
		sort.SliceStable(edits, func(i, j int) bool { return edits[i].start < edits[j].start })
		var out bytes.Buffer
		last := 0
		for _, e := range edits {
			if e.start < last {
				continue
			}
			out.Write(src[last:e.start])
			out.WriteString(e.text)
			last = e.end
		}
		out.Write(src[last:])
		if err := os.WriteFile(name, out.Bytes(), 0644); err != nil {
			return err
		}
	}
	return nil
}

var (
	_ = ast.IsExported
	_ = parser.ParseFile
	_ = unicode.IsUpper
	_ = types.Universe
)
