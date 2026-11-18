package analyzer

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/parser"
	"go/token"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"declscope/internal/load"
)

// internalParent returns the path of the tree that may import an internal
// package: the parent of its last internal element.
func internalParent(path string) string {
	elems := strings.Split(path, "/")
	for i := len(elems) - 1; i >= 0; i-- {
		if elems[i] == "internal" {
			return strings.Join(elems[:i], "/")
		}
	}
	return path
}

func inTree(path, parent string) bool {
	return parent == "" || path == parent || strings.HasPrefix(path, parent+"/")
}

// buildModule is one module of a build list.
type buildModule struct {
	Path  string
	Main  bool
	Dir   string
	Error *struct{ Err string }
}

// readBuildList reads the build list of the module or workspace the go
// command finds from dir. A failure is described as it follows "reading the
// build list failed: ".
func readBuildList(dir string) ([]buildModule, string) {
	cmd := exec.Command("go", "list", "-m", "-e", "-json", "all")
	cmd.Dir = dir
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		if strings.Contains(errb.String(), "can't compute 'all' using the vendor directory") {
			return vendoredBuildList(dir)
		}
		return nil, strings.TrimSpace(errb.String())
	}
	var mods []buildModule
	for dec := json.NewDecoder(&out); dec.More(); {
		var m buildModule
		if err := dec.Decode(&m); err != nil {
			return mods, err.Error()
		}
		mods = append(mods, m)
	}
	for _, m := range mods {
		if m.Error != nil {
			return mods, m.Path + ": " + strings.TrimSpace(m.Error.Err)
		}
	}
	return mods, ""
}

// vendoredBuildList reads the build list of a module built in vendor mode
// from vendor/modules.txt: each module is read from its vendored copy.
func vendoredBuildList(dir string) ([]buildModule, string) {
	cmd := exec.Command("go", "list", "-m", "-json")
	cmd.Dir = dir
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		return nil, strings.TrimSpace(errb.String())
	}
	var mods []buildModule
	root := dir
	for dec := json.NewDecoder(&out); dec.More(); {
		var m buildModule
		if err := dec.Decode(&m); err != nil {
			return nil, err.Error()
		}
		mods = append(mods, m)
		if m.Dir != "" {
			root = m.Dir
		}
	}
	data, err := os.ReadFile(filepath.Join(root, "vendor", "modules.txt"))
	if err != nil {
		return nil, err.Error()
	}
	var vendored []buildModule
	for _, line := range strings.Split(string(data), "\n") {
		rest, ok := strings.CutPrefix(line, "# ")
		if !ok {
			continue
		}
		f := strings.Fields(rest)
		if len(f) == 0 {
			continue
		}
		vendored = append(vendored, buildModule{Path: f[0], Dir: filepath.Join(root, "vendor", filepath.FromSlash(f[0]))})
	}
	sort.SliceStable(vendored, func(i, j int) bool { return vendored[i].Path < vendored[j].Path })
	return append(mods, vendored...), ""
}

// modulePath returns the module path a go.mod file declares, tolerating
// unrelated problems in it, or "" if it declares none.
func modulePath(data []byte) string {
	for len(data) > 0 {
		line := data
		data = nil
		if i := bytes.IndexByte(line, '\n'); i >= 0 {
			line, data = line[:i], line[i+1:]
		}
		if i := bytes.Index(line, []byte("//")); i >= 0 {
			line = line[:i]
		}
		line = bytes.TrimSpace(line)
		rest, ok := bytes.CutPrefix(line, []byte("module"))
		if !ok {
			continue
		}
		n := len(rest)
		rest = bytes.TrimSpace(rest)
		if len(rest) == n || len(rest) == 0 {
			continue
		}
		if rest[0] == '"' || rest[0] == '`' {
			p, err := strconv.Unquote(string(rest))
			if err != nil {
				return ""
			}
			return p
		}
		return string(rest)
	}
	return ""
}

type nestedModule struct {
	path, dir string
}

// findNested lists the modules below a module root.
func findNested(root string) ([]nestedModule, error) {
	var out []nestedModule
	var failed error
	filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil || !d.IsDir() || path == root {
			return nil
		}
		if d.Name() == ".git" {
			return filepath.SkipDir
		}
		gomod := filepath.Join(path, "go.mod")
		data, err := os.ReadFile(gomod)
		if err != nil {
			return nil
		}
		mp := modulePath(data)
		if mp == "" {
			failed = fmt.Errorf("reading %s: no module path", gomod)
			return filepath.SkipAll
		}
		out = append(out, nestedModule{path: mp, dir: path})
		return nil
	})
	return out, failed
}

// moduleImports lists, sorted, the import paths the Go files of a module
// copy name, whatever their build constraints.
func moduleImports(root string) []string {
	seen := make(map[string]bool)
	var out []string
	filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if path == root {
				return nil
			}
			if d.Name() == "vendor" {
				return filepath.SkipDir
			}
			if _, err := os.Stat(filepath.Join(path, "go.mod")); err == nil {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(d.Name(), ".go") {
			return nil
		}
		f, _ := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
		if f == nil {
			return nil
		}
		for _, is := range f.Imports {
			if p, err := strconv.Unquote(is.Path.Value); err == nil && !seen[p] {
				seen[p] = true
				out = append(out, p)
			}
		}
		return nil
	})
	sort.Strings(out)
	return out
}

// moduleRanges judges what the modules around the main ones mean for the
// judged packages. Nested modules that may import a package and read it from
// other source, or fail to load, take it out of judgement; so does a module
// of the build list that may hold an importer. A module that a nested module
// builds from outside the tree and that imports an internal package withholds
// the fixes of its range. It returns the packages of the nested modules,
// whose uses count, and the packages it takes out of judgement, with the
// reason.
func moduleRanges(mods []load.Module, res *shrinkResult) ([]*unit, []string, error) {
	loaded := make(map[string]bool)
	for _, m := range mods {
		loaded[filepath.Clean(m.Dir)] = true
	}
	var nested []nestedModule
	for _, root := range mods {
		ns, err := findNested(root.Dir)
		if err != nil {
			return nil, nil, err
		}
		nested = append(nested, ns...)
	}
	for _, nm := range nested {
		loaded[filepath.Clean(nm.dir)] = true
	}

	var extra []*unit
	var notJudged []string
	drop := func(su *shrinkUnit, reason string) {
		notJudged = append(notJudged, su.path+": "+reason)
		res.skipped[su.path] = true
	}
	judged := func() []*shrinkUnit {
		var out []*shrinkUnit
		for _, su := range res.units {
			if !res.skipped[su.path] {
				out = append(out, su)
			}
		}
		return out
	}

	imports := make(map[string][]string)
	for _, nm := range nested {
		var inRange []*shrinkUnit
		for _, su := range judged() {
			if inTree(nm.path, internalParent(su.path)) {
				inRange = append(inRange, su)
			}
		}
		if len(inRange) > 0 {
			pkgs, err := load.Load(&load.Config{Dir: nm.dir, Tests: true}, "./...")
			for _, su := range inRange {
				if reason := nestedFailure(pkgs, err, su); reason != "" {
					drop(su, fmt.Sprintf("the nested module %s may import it, and %s", nm.path, reason))
				}
			}
			if err == nil {
				extra = append(extra, units(pkgs)...)
			}
		}

		list, failure := readBuildList(nm.dir)
		for _, su := range judged() {
			if su.noFix != "" {
				continue
			}
			parent := internalParent(su.path)
			if failure != "" && inTree(nm.path, parent) {
				su.noFix = fmt.Sprintf("the build list of the nested module %s cannot be read, and a module it names may use it: reading the build list failed: %s", nm.path, failure)
				continue
			}
			for _, m := range list {
				if m.Main || m.Dir == "" || loaded[filepath.Clean(m.Dir)] {
					continue
				}
				imps, ok := imports[m.Dir]
				if !ok {
					imps = moduleImports(m.Dir)
					imports[m.Dir] = imps
				}
				if q := internalImport(imps, parent); q != "" {
					su.noFix = fmt.Sprintf("the build of the nested module %s uses %s from %s, which imports %s", nm.path, m.Path, m.Dir, q)
					break
				}
			}
		}
	}

	if units := judged(); len(units) > 0 {
		list, failure := readBuildList(".")
		for _, su := range units {
			if failure != "" {
				drop(su, "reading the build list failed: "+failure)
				continue
			}
			parent := internalParent(su.path)
			for _, m := range list {
				if m.Main || loaded[filepath.Clean(m.Dir)] {
					continue
				}
				if holds(m, parent) {
					drop(su, fmt.Sprintf("the build uses %s from %s", m.Path, m.Dir))
					break
				}
			}
		}
	}
	res.units = judged()
	return extra, notJudged, nil
}

// nestedFailure says why the load of a nested module leaves a package
// unjudged, or returns "".
func nestedFailure(pkgs []*load.Package, err error, su *shrinkUnit) string {
	if err != nil {
		return "loading it failed: " + err.Error()
	}
	var listed []string
	reads := false
	var from string
	load.Visit(pkgs, nil, func(p *load.Package) {
		for _, e := range p.Errors {
			// A compile error the go command met building export data is
			// a type error, not a failure to load.
			if e.Kind == load.ListError && !strings.HasPrefix(e.Msg, "# ") {
				listed = append(listed, p.PkgPath+": "+describeError(e))
				break
			}
		}
		if p.PkgPath == su.path && !reads {
			reads = true
			if p.Dir != su.pkg.Dir {
				from = p.Dir
				if p.Module != nil && p.Module.Dir != "" {
					from = p.Module.Dir
				}
			}
		}
	})
	if len(listed) > 0 {
		sort.Strings(listed)
		return "loading it failed: " + listed[0]
	}
	if !reads {
		return ""
	}
	var broken []string
	for _, p := range pkgs {
		if isTestMain(p) || len(p.Errors) == 0 {
			continue
		}
		broken = append(broken, fmt.Sprintf("its package %s does not type-check: %s", p.PkgPath, describeError(firstError(p))))
	}
	if len(broken) > 0 {
		sort.Strings(broken)
		return broken[0]
	}
	if from != "" {
		return fmt.Sprintf("it reads %s from %s", su.path, from)
	}
	return ""
}

// internalImport returns the first of the sorted import paths that names an
// internal package in the tree of parent, or "".
func internalImport(imps []string, parent string) string {
	for _, imp := range imps {
		if isInternal(imp) && inTree(imp, parent) {
			return imp
		}
	}
	return ""
}

// holds reports whether a module of the build list may hold a package in the
// tree of parent: its path lies in the tree, or above it with the tree's
// directory inside.
func holds(m buildModule, parent string) bool {
	if inTree(m.Path, parent) {
		return true
	}
	rel, ok := strings.CutPrefix(parent, m.Path+"/")
	if !ok || m.Dir == "" {
		return false
	}
	fi, err := os.Stat(filepath.Join(m.Dir, filepath.FromSlash(rel)))
	return err == nil && fi.IsDir()
}
