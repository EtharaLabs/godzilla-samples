// Package analyzer implements the declscope analysis.
package analyzer

import (
	"flag"
	"fmt"
	"go/ast"
	"strings"

	"declscope/internal/checker"
)

const doc = `enforces private and shared pseudo scopes for package-level declarations, methods and struct fields

Subcommands:

   declscope baseline [flags] [packages]
   declscope inspect  [flags] <package>
   declscope survey   [flags] [packages]
   declscope shrink   [flags] [packages]

   declscope skill install   [flags] [skill...]
   declscope skill uninstall [flags] [skill...]
   declscope skill list      [flags] [skill...]

Run a subcommand with -h for its flags.`

// configFlag is the -config flag of the analyzer.
var configFlag string

// New returns the analyzer with its flags.
func New() *checker.Analyzer {
	fs := flag.NewFlagSet("declscope", flag.ExitOnError)
	fs.StringVar(&configFlag, "config", "", "path to a declscope YAML config file (default: nearest .declscope.yaml)")
	return &checker.Analyzer{
		Name:  "declscope",
		Doc:   doc,
		Flags: fs,
		Run:   run,
	}
}

func run(pass *checker.Pass) error {
	rules, err := rulesForPass(pass.Pkg, configFlag)
	if err != nil {
		return err
	}
	var base Baseline
	if path := baselineFrom(pass.Pkg, searchDir(pass.Pkg), rules); path != "" {
		if base, err = LoadBaseline(path); err != nil {
			return err
		}
	}
	res := Analyze(pass, rules, base)
	for _, f := range res.Reported {
		pass.Report(f.diagnostic())
	}
	return nil
}

func (f *finding) diagnostic() checker.Diagnostic {
	d := checker.Diagnostic{
		Pos:      f.pos,
		End:      f.pos,
		Category: f.rule,
		Message:  f.message,
		Related:  f.related,
	}
	if f.fix != nil {
		d.SuggestedFixes = []checker.SuggestedFix{*f.fix}
	}
	return d
}

// Result is the outcome of analyzing one package.
type Result struct {
	Model     *model
	Findings  []*finding // every finding, silenced or not
	Reported  []*finding
	Ignored   map[*finding]bool
	Baselined map[*finding]bool
	// Covered holds the member reports a shown report on their type hides.
	Covered []*finding
}

// Analyze runs every rule on a package.
func Analyze(pass *checker.Pass, rules *Rules, base Baseline) *Result {
	m := newModel(pass, rules)
	res := &Result{Model: m, Ignored: make(map[*finding]bool), Baselined: make(map[*finding]bool)}
	if len(m.files) == 0 {
		if f := m.filterFinding(); f != nil {
			res.Findings = append(res.Findings, f)
			res.Reported = append(res.Reported, f)
		}
		return res
	}

	phase1 := m.declFindings(true)
	phase2 := append([]*finding(nil), m.problems...)
	phase2 = append(phase2, m.unusedScopeFindings(true, phase1)...)
	m.sortByPos(phase2)

	shown := make(map[*finding]bool)
	emit := func(f *finding) {
		if f.coveredBy != nil && shown[f.coveredBy] {
			res.Covered = append(res.Covered, f)
			return
		}
		igs := m.covering(f)
		for _, ig := range igs {
			ig.used = true
		}
		if len(igs) > 0 && (f.rule == "directive" || f.rule == "unused") && !allFileLevel(igs) {
			// Silenced on its declaration, the report never counts.
			return
		}
		res.Findings = append(res.Findings, f)
		if len(igs) > 0 {
			res.Ignored[f] = true
			// A silenced report on a type still covers its members.
			shown[f] = true
			return
		}
		if ns, name, ok := m.baselineKey(f); ok && base.Has(pass.Pkg.PkgPath, f.rule, ns, name) {
			res.Baselined[f] = true
			return
		}
		shown[f] = true
		res.Reported = append(res.Reported, f)
	}
	for _, f := range phase1 {
		emit(f)
	}
	for _, f := range phase2 {
		emit(f)
	}
	reported, silenced := m.unusedIgnoreFindings()
	for _, f := range silenced {
		res.Findings = append(res.Findings, f)
		res.Ignored[f] = true
	}
	for _, f := range reported {
		res.Findings = append(res.Findings, f)
		res.Reported = append(res.Reported, f)
	}
	return res
}

// ancestors lists a target and the targets that contain it.
func ancestors(t *target) []*target {
	var out []*target
	for ; t != nil; t = t.parent {
		out = append(out, t)
	}
	return out
}

// covering lists the ignores that silence a finding.
func (m *model) covering(f *finding) []*directive {
	var out []*directive
	if f.unusedOf {
		dir := f.dir
		file := dir.file
		if !dir.fileLevel && dir.target != nil {
			for _, ig := range dir.target.ignores {
				if ig == dir {
					continue
				}
				if ig.bare && dir.isScope() || !ig.bare && ig.covers("unused") {
					out = append(out, ig)
				}
			}
		}
		for _, ig := range file.ignores {
			if ig != dir && ig.covers("unused") {
				out = append(out, ig)
			}
		}
		return out
	}
	var t *target
	var file *fileInfo
	switch {
	case f.decl != nil:
		t, file = f.decl.target, f.decl.file
	case f.dir != nil:
		file = f.dir.file
		if !f.dir.fileLevel {
			t = f.dir.target
		}
	}
	scope := ancestors(t)
	if f.rule == "directive" && len(scope) > 0 {
		// A problem with a directive is silenced on its own declaration
		// only, never from the type or block around it.
		scope = scope[:1]
	}
	for _, a := range scope {
		for _, ig := range a.ignores {
			if ig.covers(f.rule) {
				out = append(out, ig)
			}
		}
	}
	if file != nil {
		for _, ig := range file.ignores {
			if ig.covers(f.rule) {
				out = append(out, ig)
			}
		}
	}
	return out
}

// silence reports whether an ignore silences f, marking every ignore that
// covers it as used.
func (m *model) silence(f *finding) bool {
	igs := m.covering(f)
	for _, ig := range igs {
		ig.used = true
	}
	return len(igs) > 0
}

// unusedIgnoreFindings reports the ignores that silenced nothing, and
// separately the reports another ignore silenced.
func (m *model) unusedIgnoreFindings() (out, quiet []*finding) {
	if m.rules.Unused == "off" || m.unseenTests && !m.testVariant {
		return nil, nil
	}
	var cands []*directive
	for _, f := range m.files {
		for _, d := range f.directives {
			if !d.effective || d.name != "ignore" || d.used {
				continue
			}
			if !d.bare && containsRule(d.rules, "overexported") {
				continue
			}
			if m.excludedNames(d) {
				continue
			}
			cands = append(cands, d)
		}
	}
	var pending []*finding
	for _, d := range cands {
		var msg string
		text := "//declscope:ignore"
		if !d.bare {
			text += " " + d.ruleText()
		}
		switch names := m.targetNames(d.target); {
		case d.fileLevel:
			msg = "unused file-level " + text
		case len(names) == 0:
			msg = "unused " + text + ": no checked declaration carries it"
		default:
			msg = "unused " + text + " on " + strings.Join(names, ", ")
		}
		f := &finding{rule: "unused", pos: d.pos(), message: msg, dir: d, unusedOf: true}
		pending = append(pending, f)
	}
	silenced := make(map[*finding]bool)
	dropped := make(map[*finding]bool)
	for _, f := range pending {
		igs := m.covering(f)
		for _, ig := range igs {
			ig.used = true
		}
		if len(igs) > 0 {
			silenced[f] = true
			if !allFileLevel(igs) {
				dropped[f] = true
			}
		}
	}
	for _, f := range pending {
		if f.dir.used || dropped[f] {
			continue
		}
		if silenced[f] {
			quiet = append(quiet, f)
			continue
		}
		out = append(out, f)
	}
	m.sortByPos(out)
	return out, quiet
}

func allFileLevel(igs []*directive) bool {
	for _, ig := range igs {
		if !ig.fileLevel {
			return false
		}
	}
	return true
}

func containsRule(rules []string, r string) bool {
	for _, x := range rules {
		if x == r {
			return true
		}
	}
	return false
}

// targetNames names the declarations a target declares.
func (m *model) targetNames(t *target) []string {
	var names []string
	if t == nil {
		return nil
	}
	if t.kind == tBlock {
		for _, c := range t.children {
			for _, a := range c.anchors {
				names = append(names, a.display)
			}
		}
		return names
	}
	for _, a := range t.anchors {
		names = append(names, a.display)
	}
	return names
}

// excludedNames reports whether an ignore of boundary reaches a declaration
// that a build-excluded file names, so that the ignore may be in use there.
func (m *model) excludedNames(ig *directive) bool {
	if !ig.covers("boundary") || len(m.excluded) == 0 {
		return false
	}
	var names []string
	var collect func(t *target)
	collect = func(t *target) {
		for _, a := range t.anchors {
			names = append(names, a.name)
			if a.member && a.typeDecl != nil {
				names = append(names, a.typeDecl.name)
			}
		}
		for _, c := range t.children {
			collect(c)
		}
	}
	if ig.fileLevel {
		for _, t := range ig.file.targets {
			collect(t)
		}
	} else {
		collect(ig.target)
	}
	return mentions(m.excluded, names...)
}

// filterFinding reports a package read as empty because an only above the
// nearest one removes every file the nearest one matches.
func (m *model) filterFinding() *finding {
	only := m.rules.Only
	if len(only) == 0 {
		return nil
	}
	var paths []string
	var first *ast.File
	for _, f := range m.pass.Files {
		if ast.IsGenerated(f) {
			continue
		}
		if first == nil {
			first = f
		}
		paths = append(paths, m.fset.File(f.Pos()).Name())
	}
	// The nearest only matched files, and the rest of the filter took
	// every one of them back out.
	nearest := only[len(only)-1]
	matched := 0
	for _, p := range paths {
		if m.rules.admits(p) {
			return nil
		}
		if matchesList(nearest, p) {
			matched++
		}
	}
	if matched == 0 {
		return nil
	}
	return &finding{
		rule:    "filter",
		pos:     first.Package,
		message: fmt.Sprintf("filter.only stated in %s matches %d file(s) here, but an only above it removes them all, so this package is read as empty", nearest.Dir, matched),
	}
}

func matchesList(list PatternList, path string) bool {
	for _, p := range list.Patterns {
		if p.match(path) {
			return true
		}
	}
	return false
}
