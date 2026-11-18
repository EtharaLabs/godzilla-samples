package load

import (
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/scanner"
	"go/token"
	"go/types"
	"io"
	"os"
	"sort"
	"sync"
)

// Package is a loaded package.
type Package struct {
	ID              string
	Name            string
	PkgPath         string
	Dir             string
	Errors          []Error
	TypeErrors      []types.Error
	GoFiles         []string
	CompiledGoFiles []string
	OtherFiles      []string
	EmbedFiles      []string
	IgnoredFiles    []string
	ExportFile      string
	Imports         map[string]*Package
	Types           *types.Package
	Fset            *token.FileSet
	IllTyped        bool
	Syntax          []*ast.File
	TypesInfo       *types.Info
	TypesSizes      types.Sizes
	Module          *Module
	ForTest         string
	DepOnly         bool
	Initial         bool

	// Raw is the go list record.
	Raw *jsonPackage

	needsrc, needtypes bool
	importErrors       map[string]error
	color              int
	loaded             bool
}

// CgoFiles returns the package's cgo files as absolute paths.
func (p *Package) CgoFiles() []string {
	if p.Raw == nil {
		return nil
	}
	return absJoin(p.Dir, p.Raw.CgoFiles)
}

// IgnoredGoFiles returns the build-excluded Go files as absolute paths.
func (p *Package) IgnoredGoFiles() []string {
	if p.Raw == nil {
		return nil
	}
	return absJoin(p.Dir, p.Raw.IgnoredGoFiles)
}

// RawGoFiles returns the Go files as listed (without cgo files), absolute.
func (p *Package) RawGoFiles() []string {
	if p.Raw == nil {
		return nil
	}
	return absJoin(p.Dir, p.Raw.GoFiles)
}

// TestGoFiles returns the in-package test files, absolute.
func (p *Package) TestGoFiles() []string {
	if p.Raw == nil {
		return nil
	}
	return absJoin(p.Dir, p.Raw.TestGoFiles)
}

// XTestGoFiles returns the external test files, absolute.
func (p *Package) XTestGoFiles() []string {
	if p.Raw == nil {
		return nil
	}
	return absJoin(p.Dir, p.Raw.XTestGoFiles)
}

func (p *Package) String() string { return p.ID }

type parseValue struct {
	f     *ast.File
	err   error
	ready chan struct{}
}

type loader struct {
	cfg      *Config
	fset     *token.FileSet
	pkgs     map[string]*Package
	sizes    types.Sizes
	imp      types.ImporterFrom
	byPath   map[string]*Package // export-data packages by path
	parseMu  sync.Mutex
	cache    map[string]*parseValue
	exportMu sync.Mutex
}

// Load loads the packages named by patterns.
func Load(cfg *Config, patterns ...string) ([]*Package, error) {
	state := &golistState{cfg: cfg}
	response, err := state.driver(patterns)
	if err != nil {
		return nil, err
	}
	ld := &loader{
		cfg:   cfg,
		fset:  token.NewFileSet(),
		cache: make(map[string]*parseValue),
	}
	if !cfg.NoTypes {
		ld.sizes = types.SizesFor(response.Compiler, response.Arch)
		if ld.sizes == nil {
			return nil, fmt.Errorf("can't determine type sizes for compiler %q on GOARCH %q", response.Compiler, response.Arch)
		}
	}
	return ld.refine(response)
}

func (ld *loader) refine(response *driverResponse) ([]*Package, error) {
	roots := response.Roots
	rootMap := make(map[string]int, len(roots))
	for i, root := range roots {
		rootMap[root] = i
	}
	ld.pkgs = make(map[string]*Package)
	initial := make([]*Package, len(roots))
	wantTypes := !ld.cfg.NoTypes
	for _, pkg := range response.Packages {
		rootIndex := -1
		if i, found := rootMap[pkg.ID]; found {
			rootIndex = i
		}
		exportDataInvalid := pkg.ExportFile == "" && pkg.PkgPath != "unsafe"
		pkg.needtypes = wantTypes && (rootIndex >= 0 || ld.cfg.Deps)
		pkg.needsrc = (wantTypes && (rootIndex >= 0 || ld.cfg.Deps) || wantTypes && exportDataInvalid) && pkg.PkgPath != "unsafe"
		pkg.Fset = ld.fset
		ld.pkgs[pkg.ID] = pkg
		if rootIndex >= 0 {
			initial[rootIndex] = pkg
			pkg.Initial = true
		}
	}
	for i, root := range roots {
		if initial[i] == nil {
			return nil, fmt.Errorf("root package %v is missing", root)
		}
	}

	const (
		white = 0
		grey  = 1
		black = 2
	)
	var stack []*Package
	var visit func(lpkg *Package) bool
	visit = func(lpkg *Package) bool {
		if lpkg.color == grey {
			panic("internal error: grey node")
		}
		if lpkg.color == white {
			lpkg.color = grey
			stack = append(stack, lpkg)
			stubs := lpkg.Imports
			lpkg.Imports = make(map[string]*Package, len(stubs))
			paths := make([]string, 0, len(stubs))
			for p := range stubs {
				paths = append(paths, p)
			}
			sort.Strings(paths)
			for _, importPath := range paths {
				ipkg := stubs[importPath]
				var importErr error
				imp := ld.pkgs[ipkg.ID]
				if imp == nil {
					importErr = fmt.Errorf("missing package: %q", ipkg.ID)
				} else if imp.color == grey {
					importErr = fmt.Errorf("import cycle: %s", stack)
				}
				if importErr != nil {
					if lpkg.importErrors == nil {
						lpkg.importErrors = make(map[string]error)
					}
					lpkg.importErrors[importPath] = importErr
					continue
				}
				if visit(imp) {
					lpkg.needsrc = true
				}
				lpkg.Imports[importPath] = imp
			}
			if lpkg.needsrc && wantTypes {
				for _, ipkg := range lpkg.Imports {
					ipkg.needtypes = true
				}
			}
			if wantTypes {
				lpkg.TypesSizes = ld.sizes
			}
			stack = stack[:len(stack)-1]
			lpkg.color = black
		}
		return lpkg.needsrc
	}
	for _, lpkg := range initial {
		visit(lpkg)
	}

	if wantTypes {
		ld.byPath = make(map[string]*Package)
		for _, p := range ld.pkgs {
			if !p.needsrc && p.ExportFile != "" {
				ld.byPath[p.PkgPath] = p
			}
		}
		ld.imp = importer.ForCompiler(ld.fset, "gc", func(path string) (io.ReadCloser, error) {
			p := ld.byPath[path]
			if p == nil || p.ExportFile == "" {
				return nil, fmt.Errorf("no export data for %q", path)
			}
			return os.Open(p.ExportFile)
		}).(types.ImporterFrom)
		ld.loadAll(initial)
	}
	return initial, nil
}

// loadAll loads every package reachable from the initial ones, dependencies
// first. Source packages are type-checked in parallel once their imports are
// done.
func (ld *loader) loadAll(initial []*Package) {
	var order []*Package
	seen := make(map[*Package]bool)
	var post func(p *Package)
	post = func(p *Package) {
		if seen[p] {
			return
		}
		seen[p] = true
		paths := make([]string, 0, len(p.Imports))
		for path := range p.Imports {
			paths = append(paths, path)
		}
		sort.Strings(paths)
		for _, path := range paths {
			post(p.Imports[path])
		}
		order = append(order, p)
	}
	for _, p := range initial {
		post(p)
	}
	// Parse every source file up front. go/packages parses the files of a
	// package concurrently, and the goroutine started last usually wins
	// the race to register its file; mimic that order so that positions,
	// and thus the order of edits spanning files, come out the same.
	//
	// A package and its in-package test variant share most files and load
	// side by side: the last file of each usually comes first, then the
	// package's other files, then the variant's.
	testVariant := make(map[string]*Package)
	for _, p := range order {
		if p.ForTest != "" && p.PkgPath == p.ForTest {
			testVariant[p.PkgPath] = p
		}
	}
	unparsed := func(p *Package) []string {
		var todo []string
		for _, f := range p.CompiledGoFiles {
			if _, ok := ld.cache[f]; !ok {
				todo = append(todo, f)
			}
		}
		return todo
	}
	for _, p := range order {
		if !p.needsrc || p.PkgPath == "unsafe" {
			continue
		}
		todo := unparsed(p)
		var tv []string
		if t := testVariant[p.PkgPath]; p.ForTest == "" && t != nil && t.needsrc {
			mine := make(map[string]bool)
			for _, f := range todo {
				mine[f] = true
			}
			for _, f := range unparsed(t) {
				if !mine[f] {
					tv = append(tv, f)
				}
			}
		}
		var seq []string
		if n := len(todo); n > 0 {
			seq = append(seq, todo[n-1])
			todo = todo[:n-1]
		}
		if n := len(tv); n > 0 {
			seq = append(seq, tv[n-1])
			tv = tv[:n-1]
		}
		seq = append(append(seq, todo...), tv...)
		for _, f := range seq {
			ld.parseFile(f)
		}
	}
	var wg sync.WaitGroup

	// Type-check in dependency order, running independent packages in parallel.
	done := make(map[*Package]chan struct{}, len(order))
	for _, p := range order {
		done[p] = make(chan struct{})
	}
	for _, p := range order {
		wg.Add(1)
		go func(p *Package) {
			defer wg.Done()
			for _, imp := range p.Imports {
				<-done[imp]
			}
			ld.loadPackage(p)
			close(done[p])
		}(p)
	}
	wg.Wait()
}

func (ld *loader) parseFile(filename string) (*ast.File, error) {
	ld.parseMu.Lock()
	v, ok := ld.cache[filename]
	if ok {
		ld.parseMu.Unlock()
		<-v.ready
		return v.f, v.err
	}
	v = &parseValue{ready: make(chan struct{})}
	ld.cache[filename] = v
	ld.parseMu.Unlock()
	src, err := os.ReadFile(filename)
	if err != nil {
		v.err = err
	} else {
		v.f, v.err = parser.ParseFile(ld.fset, filename, src, parser.AllErrors|parser.ParseComments)
	}
	close(v.ready)
	return v.f, v.err
}

func (ld *loader) parseFiles(filenames []string) ([]*ast.File, []error) {
	var parsed []*ast.File
	var errs []error
	for _, filename := range filenames {
		f, err := ld.parseFile(filename)
		if f != nil {
			parsed = append(parsed, f)
		}
		if err != nil {
			errs = append(errs, err)
		}
	}
	return parsed, errs
}

func (ld *loader) loadFromExportData(lpkg *Package) error {
	ld.exportMu.Lock()
	defer ld.exportMu.Unlock()
	if lpkg.Types != nil && lpkg.Types.Complete() {
		return nil
	}
	lpkg.IllTyped = true
	if lpkg.ExportFile == "" {
		return fmt.Errorf("no export data file")
	}
	tpkg, err := ld.imp.ImportFrom(lpkg.PkgPath, "", 0)
	if err != nil {
		return fmt.Errorf("reading %s: %v", lpkg.ExportFile, err)
	}
	lpkg.Types = tpkg
	lpkg.IllTyped = false
	return nil
}

func (ld *loader) loadPackage(lpkg *Package) {
	if lpkg.loaded {
		return
	}
	lpkg.loaded = true
	if lpkg.PkgPath == "unsafe" {
		lpkg.Types = types.Unsafe
		lpkg.Syntax = []*ast.File{}
		lpkg.TypesInfo = new(types.Info)
		lpkg.TypesSizes = ld.sizes
		return
	}
	if !lpkg.needtypes && !lpkg.needsrc {
		lpkg.Types = types.NewPackage(lpkg.PkgPath, lpkg.Name)
		return
	}
	if !lpkg.needsrc {
		if err := ld.loadFromExportData(lpkg); err != nil {
			lpkg.Errors = append(lpkg.Errors, Error{Pos: "-", Msg: err.Error(), Kind: UnknownError})
		}
		return
	}
	lpkg.Types = types.NewPackage(lpkg.PkgPath, lpkg.Name)

	appendError := func(err error) {
		var errs []Error
		switch err := err.(type) {
		case Error:
			errs = append(errs, err)
		case *os.PathError:
			errs = append(errs, Error{Pos: err.Path + ":1", Msg: err.Err.Error(), Kind: ParseError})
		case scanner.ErrorList:
			for _, err := range err {
				errs = append(errs, Error{Pos: err.Pos.String(), Msg: err.Msg, Kind: ParseError})
			}
		case scanner.Error:
			errs = append(errs, Error{Pos: err.Pos.String(), Msg: err.Msg, Kind: ParseError})
		case types.Error:
			lpkg.TypeErrors = append(lpkg.TypeErrors, err)
			errs = append(errs, Error{Pos: err.Fset.Position(err.Pos).String(), Msg: err.Msg, Kind: TypeError})
		default:
			errs = append(errs, Error{Pos: "-", Msg: err.Error(), Kind: UnknownError})
		}
		lpkg.Errors = append(lpkg.Errors, errs...)
	}

	if len(lpkg.CompiledGoFiles) == 0 && lpkg.ExportFile != "" {
		appendError(Error{"-", fmt.Sprintf("sources missing for package %s", lpkg.ID), ParseError})
		_ = ld.loadFromExportData(lpkg)
		return
	}

	files, errs := ld.parseFiles(lpkg.CompiledGoFiles)
	for _, err := range errs {
		appendError(err)
	}
	lpkg.Syntax = files
	lpkg.TypesInfo = &types.Info{
		Types:        make(map[ast.Expr]types.TypeAndValue),
		Defs:         make(map[*ast.Ident]types.Object),
		Uses:         make(map[*ast.Ident]types.Object),
		Implicits:    make(map[ast.Node]types.Object),
		Instances:    make(map[*ast.Ident]types.Instance),
		Scopes:       make(map[ast.Node]*types.Scope),
		Selections:   make(map[*ast.SelectorExpr]*types.Selection),
		FileVersions: make(map[*ast.File]string),
	}
	lpkg.TypesSizes = ld.sizes

	imp := importerFunc(func(path string) (*types.Package, error) {
		if path == "unsafe" {
			return types.Unsafe, nil
		}
		ipkg := lpkg.Imports[path]
		if ipkg == nil {
			if err := lpkg.importErrors[path]; err != nil {
				return nil, err
			}
			return nil, fmt.Errorf("no metadata for %s", path)
		}
		if ipkg.Types != nil && ipkg.Types.Complete() {
			return ipkg.Types, nil
		}
		return nil, fmt.Errorf("internal error: package %q without types was imported from %q", path, lpkg)
	})

	tc := &types.Config{
		Importer:         imp,
		IgnoreFuncBodies: !ld.cfg.Deps && !lpkg.Initial,
		Error:            appendError,
		Sizes:            ld.sizes,
	}
	if lpkg.Module != nil && lpkg.Module.GoVersion != "" {
		tc.GoVersion = "go" + lpkg.Module.GoVersion
	}
	err := types.NewChecker(tc, ld.fset, lpkg.Types, lpkg.TypesInfo).Files(lpkg.Syntax)
	lpkg.importErrors = nil
	if err != nil && len(lpkg.Errors) == 0 {
		appendError(err)
	}
	illTyped := len(lpkg.Errors) > 0
	if !illTyped {
		for _, imp := range lpkg.Imports {
			if imp.IllTyped {
				illTyped = true
				break
			}
		}
	}
	lpkg.IllTyped = illTyped
}

type importerFunc func(path string) (*types.Package, error)

func (f importerFunc) Import(path string) (*types.Package, error) { return f(path) }

// Visit visits all the packages in the import graph rooted at pkgs, calling
// post for each in postorder (dependencies first, imports sorted by path).
func Visit(pkgs []*Package, pre func(*Package) bool, post func(*Package)) {
	seen := make(map[*Package]bool)
	var visit func(*Package)
	visit = func(pkg *Package) {
		if !seen[pkg] {
			seen[pkg] = true
			if pre == nil || pre(pkg) {
				paths := make([]string, 0, len(pkg.Imports))
				for path := range pkg.Imports {
					paths = append(paths, path)
				}
				sort.Strings(paths)
				for _, path := range paths {
					visit(pkg.Imports[path])
				}
			}
			if post != nil {
				post(pkg)
			}
		}
	}
	for _, pkg := range pkgs {
		visit(pkg)
	}
}

// PrintErrors prints the errors of every package in the import graph rooted
// at pkgs, dependencies first, and returns how many it printed.
func PrintErrors(w io.Writer, pkgs []*Package) int {
	var n int
	errModules := make(map[*Module]bool)
	Visit(pkgs, nil, func(pkg *Package) {
		for _, err := range pkg.Errors {
			fmt.Fprintln(w, err)
			n++
		}
		mod := pkg.Module
		if mod != nil && mod.Error != nil && !errModules[mod] {
			errModules[mod] = true
			fmt.Fprintln(w, mod.Error.Err)
			n++
		}
	})
	return n
}

// Recheck type-checks a source package again with every function body, and
// returns the errors it finds. It reports what a package that was only
// checked as a dependency would report had it been named itself.
func Recheck(p *Package) []Error {
	if len(p.Syntax) == 0 {
		return nil
	}
	var errs []Error
	imp := importerFunc(func(path string) (*types.Package, error) {
		if path == "unsafe" {
			return types.Unsafe, nil
		}
		ipkg := p.Imports[path]
		if ipkg == nil || ipkg.Types == nil || !ipkg.Types.Complete() {
			return nil, fmt.Errorf("no metadata for %s", path)
		}
		return ipkg.Types, nil
	})
	tc := &types.Config{
		Importer: imp,
		Sizes:    p.TypesSizes,
		Error: func(err error) {
			if te, ok := err.(types.Error); ok {
				errs = append(errs, Error{Pos: te.Fset.Position(te.Pos).String(), Msg: te.Msg, Kind: TypeError})
			}
		},
	}
	if p.Module != nil && p.Module.GoVersion != "" {
		tc.GoVersion = "go" + p.Module.GoVersion
	}
	pkg := types.NewPackage(p.PkgPath, p.Name)
	_ = types.NewChecker(tc, p.Fset, pkg, &types.Info{}).Files(p.Syntax)
	return errs
}
