package analyzer

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"go/types"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"declscope/internal/checker"
)

// fileInfo is one analyzed file.
type fileInfo struct {
	ast    *ast.File
	path   string
	base   string
	index  int
	isTest bool
	ns     *namespace

	directives []*directive
	fileDirs   []*directive
	scope      *directive
	ignores    []*directive
	targets    []*target // top-level targets in source order
	hasDecls   bool

	docOf     map[*ast.CommentGroup]*target
	misplaced map[*ast.CommentGroup]bool
}

// namespace is a unit of files.
type namespace struct {
	name  string
	core  bool
	files []*fileInfo
}

func (ns *namespace) key() string {
	if ns.core {
		return "(core)"
	}
	return ns.name
}

// describe names the namespace in messages.
func (ns *namespace) describe() string {
	if ns.core {
		return "the core namespace"
	}
	return fmt.Sprintf("namespace %q", ns.name)
}

// decl is a declaration the analysis checks: a package-level name, a
// method, or a member of a type.
type decl struct {
	obj      types.Object
	name     string
	display  string
	kind     string
	ident    *ast.Ident
	file     *fileInfo
	ns       *namespace
	target   *target
	member   bool
	typeDecl *decl // the type of a member, or the receiver type of a method
	exported bool

	scope  string
	source scopeSource
	uses   []use
}

type use struct {
	pos, end token.Pos
	ident    *ast.Ident // nil for an element of a positional literal
	file     *fileInfo
}

type srcKind int

const (
	srcOwn srcKind = iota
	srcBlock
	srcType
	srcFile
	srcExported
	srcDefault
)

type scopeSource struct {
	kind srcKind
	dir  *directive
	typ  *decl
}

// model is everything the rules read about one package.
type model struct {
	pass  *checker.Pass
	fset  *token.FileSet
	rules *Rules
	files []*fileInfo
	byAst map[*ast.File]*fileInfo

	namespaces    map[string]*namespace
	decls         []*decl
	byObj         map[types.Object]*decl
	problems      []*finding // directive rule findings
	domains       map[*directive][]*decl
	deleted       map[*directive]bool // treated as deleted while judging a deletion
	narrowed      *decl               // treated as private by its own directive
	reachCache    map[*directive][]*decl
	scopeDirs     []*directive
	unusedMemo    map[string]unusedReport
	findingsMemo  map[string][]*finding
	exportedMeths map[*types.Func]bool
	ifaceTys      []*types.Interface
	holders       map[*types.Func][]types.Type
	claims        map[string]bool // names renames have taken

	pkgName     string
	testVariant bool // the pass includes in-package test files
	unseenTests bool // in-package tests exist outside this pass
	unseenOwn   bool // a file of this package is outside this pass
	hasAsm      bool
	hasGen      bool
	hasCgo      bool
	unseen      []*ast.File // build-excluded and filtered files of this package, for names
	excluded    []*ast.File // the build-excluded ones alone
	genFiles    []*ast.File
	ifaceFuncs  []*types.Func
}

func newModel(pass *checker.Pass, rules *Rules) *model {
	m := &model{
		pass:       pass,
		fset:       pass.Fset,
		rules:      rules,
		byAst:      make(map[*ast.File]*fileInfo),
		namespaces: make(map[string]*namespace),
		byObj:      make(map[types.Object]*decl),
		pkgName:    pass.Types.Name(),
	}
	m.loadFiles()
	m.scanDir()
	for _, f := range m.files {
		m.buildTargets(f)
	}
	for _, f := range m.files {
		m.bindDirectives(f)
	}
	m.assignNamespaces()
	m.collectDecls()
	m.resolveScopes(nil)
	m.collectUses()
	return m
}

// loadFiles selects the files the analysis reads.
func (m *model) loadFiles() {
	for _, f := range m.pass.Files {
		path := m.fset.File(f.Pos()).Name()
		if ast.IsGenerated(f) {
			m.hasGen = true
			m.genFiles = append(m.genFiles, f)
			continue
		}
		if !m.rules.admits(path) {
			// A file the filter removes is still part of the package: read
			// it for names only, like a file the build leaves out.
			m.unseenOwn = true
			m.unseen = append(m.unseen, f)
			continue
		}
		fi := &fileInfo{
			ast:       f,
			path:      path,
			base:      filepath.Base(path),
			index:     len(m.files),
			isTest:    strings.HasSuffix(path, "_test.go"),
			docOf:     make(map[*ast.CommentGroup]*target),
			misplaced: make(map[*ast.CommentGroup]bool),
		}
		if fi.isTest {
			m.testVariant = true
		}
		m.files = append(m.files, fi)
		m.byAst[f] = fi
	}
	if len(m.pass.Pkg.CgoFiles()) > 0 {
		m.hasCgo = true
	}
}

// scanDir looks at the package directory for files the build left out.
func (m *model) scanDir() {
	dir := m.pass.Pkg.Dir
	if dir == "" {
		return
	}
	seen := make(map[string]bool)
	for _, f := range m.pass.Pkg.GoFiles {
		seen[f] = true
	}
	for _, f := range m.pass.Pkg.CompiledGoFiles {
		seen[f] = true
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		path := filepath.Join(dir, name)
		switch filepath.Ext(name) {
		case ".s", ".S", ".sx":
			m.hasAsm = true
		case ".go":
			if seen[path] {
				continue
			}
			src, err := os.ReadFile(path)
			if err != nil {
				continue
			}
			f, _ := parser.ParseFile(token.NewFileSet(), path, src, parser.ParseComments|parser.SkipObjectResolution)
			if f == nil || f.Name == nil || f.Name.Name != m.pkgName {
				continue
			}
			m.unseenOwn = true
			if strings.HasSuffix(name, "_test.go") {
				m.unseenTests = true
			}
			m.unseen = append(m.unseen, f)
			m.excluded = append(m.excluded, f)
		}
	}
}

// buildTargets records the declaration nodes of a file.
func (m *model) buildTargets(f *fileInfo) {
	for _, d := range f.ast.Decls {
		switch d := d.(type) {
		case *ast.FuncDecl:
			f.hasDecls = true
			t := &target{kind: tFunc, node: d, file: f}
			f.targets = append(f.targets, t)
			if d.Doc != nil {
				f.docOf[d.Doc] = t
			}
		case *ast.GenDecl:
			f.hasDecls = true
			if d.Tok == token.IMPORT {
				if d.Doc != nil {
					f.misplaced[d.Doc] = true
				}
				for _, s := range d.Specs {
					is := s.(*ast.ImportSpec)
					if is.Doc != nil {
						f.misplaced[is.Doc] = true
					}
					if is.Comment != nil {
						f.misplaced[is.Comment] = true
					}
				}
				continue
			}
			t := &target{kind: tGen, node: d, file: f}
			if d.Lparen.IsValid() {
				t.kind = tBlock
			}
			f.targets = append(f.targets, t)
			if d.Doc != nil {
				f.docOf[d.Doc] = t
			}
			for _, s := range d.Specs {
				st := t
				if t.kind == tBlock {
					st = &target{kind: tSpec, node: s, file: f, parent: t}
					t.children = append(t.children, st)
				}
				// A spec binds its doc comment; a trailing comment binds by
				// line, to the first declaration on it.
				var doc *ast.CommentGroup
				switch s := s.(type) {
				case *ast.ValueSpec:
					doc = s.Doc
				case *ast.TypeSpec:
					doc = s.Doc
					m.buildMemberTargets(f, s, st)
				}
				if doc != nil {
					f.docOf[doc] = st
				}
			}
		}
	}
	// Every other doc or line comment of the file belongs to something no
	// directive may bind to.
	topSpecs := make(map[ast.Node]bool)
	for _, d := range f.ast.Decls {
		if gd, ok := d.(*ast.GenDecl); ok && gd.Tok != token.IMPORT {
			for _, s := range gd.Specs {
				topSpecs[s] = true
			}
		}
	}
	ast.Inspect(f.ast, func(n ast.Node) bool {
		var groups []*ast.CommentGroup
		switch n := n.(type) {
		case *ast.Field:
			groups = []*ast.CommentGroup{n.Doc, n.Comment}
		case *ast.GenDecl:
			groups = []*ast.CommentGroup{n.Doc}
		case *ast.ValueSpec:
			groups = []*ast.CommentGroup{n.Doc}
			if !topSpecs[n] {
				groups = append(groups, n.Comment)
			}
		case *ast.TypeSpec:
			groups = []*ast.CommentGroup{n.Doc}
			if !topSpecs[n] {
				groups = append(groups, n.Comment)
			}
		case *ast.ImportSpec:
			groups = []*ast.CommentGroup{n.Doc, n.Comment}
		}
		for _, g := range groups {
			if g != nil && f.docOf[g] == nil {
				f.misplaced[g] = true
			}
		}
		return true
	})
}

// buildMemberTargets records the fields or interface methods of a type.
func (m *model) buildMemberTargets(f *fileInfo, s *ast.TypeSpec, st *target) {
	var list *ast.FieldList
	switch t := s.Type.(type) {
	case *ast.StructType:
		list = t.Fields
	case *ast.InterfaceType:
		list = t.Methods
	}
	if list == nil {
		return
	}
	for _, field := range list.List {
		ft := &target{kind: tField, node: field, file: f, parent: st}
		st.children = append(st.children, ft)
		if field.Doc != nil {
			f.docOf[field.Doc] = ft
		}
		if field.Comment != nil {
			f.docOf[field.Comment] = ft
		}
	}
}

// bindDirectives parses the directives of a file, binds them and validates
// them.
func (m *model) bindDirectives(f *fileInfo) {
	type site struct {
		fileLevel bool
		t         *target
	}
	var order []*directive
	for _, g := range f.ast.Comments {
		for _, c := range g.List {
			name, arg, ok, malformed := parseComment(c.Text)
			if !ok && !malformed {
				continue
			}
			d := &directive{comment: c, file: f, name: name, arg: arg}
			switch {
			case c.Pos() < f.ast.Package:
				d.fileLevel = true
			case f.docOf[g] != nil:
				d.target = f.docOf[g]
			case f.misplaced[g]:
			default:
				d.target = m.lineTarget(f, c)
			}
			if malformed {
				m.problem(d, "malformed declscope directive: write it as //declscope:name")
				continue
			}
			f.directives = append(f.directives, d)
			order = append(order, d)
		}
	}
	for _, d := range order {
		m.validate(f, d)
	}
	// Namespace directives: core takes precedence over an explicit name.
	var cores, names []*directive
	for _, d := range f.fileDirs {
		if !d.effective {
			continue
		}
		switch d.name {
		case "core":
			cores = append(cores, d)
		case "namespace":
			names = append(names, d)
		}
	}
	if len(cores) > 0 && len(names) > 0 {
		m.problem(cores[0], "conflicting namespace directives: a core file's namespace is the core")
	}
}

// lineTarget finds the declaration whose first or last line holds c.
func (m *model) lineTarget(f *fileInfo, c *ast.Comment) *target {
	line := m.fset.Position(c.Pos()).Line
	for _, t := range f.targets {
		start, end := t.lines(m.fset)
		if start == line || end == line {
			return t
		}
		if t.kind == tBlock {
			for _, st := range t.children {
				start, end := st.lines(m.fset)
				if start == line || end == line {
					return st
				}
			}
		}
	}
	return nil
}

func (m *model) problem(d *directive, msg string) {
	m.problems = append(m.problems, &finding{
		rule:    "directive",
		pos:     d.pos(),
		message: msg,
		dir:     d,
	})
}

// validate checks one directive and, if it is valid, records it at its
// binding site.
func (m *model) validate(f *fileInfo, d *directive) {
	switch d.name {
	case "shared", "private", "ignore", "core", "namespace":
	default:
		if d.fileLevel {
			m.problem(d, fmt.Sprintf("declscope:%s is not a file-level directive", d.name))
		} else {
			m.problem(d, fmt.Sprintf("unknown directive declscope:%s", d.name))
		}
		return
	}
	if (d.name == "core" || d.name == "namespace") && !d.fileLevel {
		m.problem(d, fmt.Sprintf("declscope:%s must appear before the package clause", d.name))
		return
	}
	switch d.name {
	case "shared", "private", "core":
		if d.arg != "" {
			m.problem(d, fmt.Sprintf("//declscope:%s takes no argument", d.name))
			return
		}
	case "namespace":
		if d.arg == "" {
			m.problem(d, "declscope:namespace requires a name")
			return
		}
		if !validNamespace(d.arg) {
			m.problem(d, fmt.Sprintf("namespace %q is not a valid lowerCamelCase identifier", d.arg))
			return
		}
	case "ignore":
		if d.arg == "" {
			d.bare = true
		} else {
			for _, r := range strings.Split(d.arg, ",") {
				r = strings.TrimSpace(r)
				if r == "" {
					m.problem(d, "empty rule name in declscope:ignore")
					return
				}
				if !knownRule(r) {
					m.problem(d, fmt.Sprintf("unknown rule %q in declscope:ignore (want one of %s)", r, strings.Join(ruleNames, ", ")))
					return
				}
				d.rules = append(d.rules, r)
			}
		}
	}
	switch d.name {
	case "shared", "private", "ignore":
		if !d.fileLevel && d.target == nil {
			m.problem(d, fmt.Sprintf("misplaced declscope:%s: no declaration here for it to bind to; write it in a declaration's doc comment or trailing its first or last line", d.name))
			return
		}
	}
	var site []*directive
	if d.fileLevel {
		site = f.fileDirs
	} else {
		site = d.target.directives
	}
	for _, prev := range site {
		if !prev.effective {
			continue
		}
		if prev.name == d.name && (d.name != "ignore" || sameIgnore(prev, d)) {
			m.problem(d, fmt.Sprintf("duplicate declscope:%s directive", d.name))
			return
		}
		if d.name == "namespace" && prev.name == "namespace" {
			m.problem(d, "duplicate declscope:namespace directive")
			return
		}
		if d.isScope() && prev.isScope() {
			msg := fmt.Sprintf("conflicting scope directives: //declscope:%s and //declscope:%s", prev.name, d.name)
			if d.fileLevel {
				msg += " on one file"
			}
			m.problem(d, msg)
			return
		}
	}
	d.effective = true
	if d.fileLevel {
		f.fileDirs = append(f.fileDirs, d)
		switch {
		case d.isScope():
			f.scope = d
		case d.name == "ignore":
			f.ignores = append(f.ignores, d)
		}
		return
	}
	d.target.directives = append(d.target.directives, d)
	switch {
	case d.isScope():
		d.target.scope = d
	case d.name == "ignore":
		d.target.ignores = append(d.target.ignores, d)
	}
}

// assignNamespaces gives every file its namespace.
func (m *model) assignNamespaces() {
	coreStems := make(map[string]bool)
	explicit := make(map[*fileInfo]string)
	core := make(map[*fileInfo]bool)
	for _, f := range m.files {
		for _, d := range f.fileDirs {
			switch d.name {
			case "core":
				core[f] = true
			case "namespace":
				if _, ok := explicit[f]; !ok {
					explicit[f] = d.arg
				}
			}
		}
		if core[f] && !f.isTest {
			coreStems[strings.TrimSuffix(f.base, ".go")] = true
		}
	}
	for _, f := range m.files {
		var ns *namespace
		switch {
		case core[f]:
			ns = m.ns("", true)
		case explicit[f] != "":
			ns = m.ns(explicit[f], false)
		case f.isTest && coreStems[strings.TrimSuffix(f.base, "_test.go")]:
			ns = m.ns("", true)
		default:
			ns = m.ns(fileNamespace(f.base), false)
		}
		f.ns = ns
		ns.files = append(ns.files, f)
	}
}

func (m *model) ns(name string, core bool) *namespace {
	key := name
	if core {
		key = "(core)"
	}
	if ns, ok := m.namespaces[key]; ok {
		return ns
	}
	ns := &namespace{name: name, core: core}
	m.namespaces[key] = ns
	return ns
}

// collectDecls records the declarations the rules check.
func (m *model) collectDecls() {
	info := m.pass.TypesInfo
	add := func(id *ast.Ident, kind string, f *fileInfo, t *target) *decl {
		if id == nil || id.Name == "_" {
			return nil
		}
		obj := info.Defs[id]
		if obj == nil {
			return nil
		}
		d := &decl{
			obj:      obj,
			name:     id.Name,
			display:  id.Name,
			kind:     kind,
			ident:    id,
			file:     f,
			ns:       f.ns,
			target:   t,
			exported: ast.IsExported(id.Name),
		}
		m.decls = append(m.decls, d)
		m.byObj[obj] = d
		t.anchors = append(t.anchors, d)
		return d
	}
	var methods []*decl
	for _, f := range m.files {
		for _, t := range f.targets {
			switch t.kind {
			case tFunc:
				fd := t.node.(*ast.FuncDecl)
				if fd.Recv == nil {
					if fd.Name.Name == "init" {
						continue
					}
					add(fd.Name, "func", f, t)
					continue
				}
				if d := add(fd.Name, "method", f, t); d != nil {
					methods = append(methods, d)
				}
			case tGen, tBlock:
				gd := t.node.(*ast.GenDecl)
				for i, s := range gd.Specs {
					st := t
					if t.kind == tBlock {
						st = t.children[i]
					}
					switch s := s.(type) {
					case *ast.ValueSpec:
						kind := "var"
						if gd.Tok == token.CONST {
							kind = "const"
						}
						for _, id := range s.Names {
							add(id, kind, f, st)
						}
					case *ast.TypeSpec:
						td := add(s.Name, "type", f, st)
						m.collectMembers(f, s, st, td)
					}
				}
			}
		}
	}
	for _, d := range methods {
		fn := d.obj.(*types.Func)
		recv := fn.Signature().Recv()
		if recv == nil {
			continue
		}
		rt := recv.Type()
		if p, ok := rt.(*types.Pointer); ok {
			rt = p.Elem()
		}
		if n, ok := types.Unalias(rt).(*types.Named); ok {
			tn := n.Origin().Obj()
			d.display = tn.Name() + "." + d.name
			d.typeDecl = m.byObj[tn]
		}
	}
	sort.SliceStable(m.decls, func(i, j int) bool {
		pi, pj := m.fset.Position(m.decls[i].ident.Pos()), m.fset.Position(m.decls[j].ident.Pos())
		if pi.Filename != pj.Filename {
			return pi.Filename < pj.Filename
		}
		return pi.Offset < pj.Offset
	})
}

// collectMembers records the fields or interface method names of a type.
func (m *model) collectMembers(f *fileInfo, s *ast.TypeSpec, st *target, td *decl) {
	var list *ast.FieldList
	kind := "field"
	switch t := s.Type.(type) {
	case *ast.StructType:
		list = t.Fields
	case *ast.InterfaceType:
		list = t.Methods
		kind = "method"
	}
	if list == nil {
		return
	}
	typeName := s.Name.Name
	i := 0
	for _, ft := range st.children {
		if ft.kind != tField {
			continue
		}
		field := list.List[i]
		i++
		ft.typeDecl = td
		for _, id := range field.Names {
			if id.Name == "_" {
				continue
			}
			obj := m.pass.TypesInfo.Defs[id]
			if obj == nil {
				continue
			}
			ns := f.ns
			d := &decl{
				obj:      obj,
				name:     id.Name,
				display:  typeName + "." + id.Name,
				kind:     kind,
				ident:    id,
				file:     f,
				ns:       ns,
				target:   ft,
				member:   true,
				typeDecl: td,
				exported: ast.IsExported(id.Name),
			}
			m.decls = append(m.decls, d)
			m.byObj[obj] = d
			ft.anchors = append(ft.anchors, d)
		}
	}
}

// fallback resolves the scope of d, ignoring the directives in skip.
func (m *model) scopeOf(d *decl, skip map[*directive]bool) (string, scopeSource) {
	if d == m.narrowed {
		return "private", scopeSource{kind: srcOwn}
	}
	live := func(x *directive) bool { return x != nil && !skip[x] && !m.deleted[x] }
	t := d.target
	if live(t.scope) {
		return t.scope.name, scopeSource{kind: srcOwn, dir: t.scope}
	}
	switch t.kind {
	case tSpec:
		if live(t.parent.scope) {
			return t.parent.scope.name, scopeSource{kind: srcBlock, dir: t.parent.scope}
		}
	case tField:
		tt := t.parent
		if live(tt.scope) {
			return tt.scope.name, scopeSource{kind: srcType, dir: tt.scope, typ: t.typeDecl}
		}
		if tt.kind == tSpec && live(tt.parent.scope) {
			return tt.parent.scope.name, scopeSource{kind: srcType, dir: tt.parent.scope, typ: t.typeDecl}
		}
	}
	if live(d.file.scope) {
		return d.file.scope.name, scopeSource{kind: srcFile, dir: d.file.scope}
	}
	if d.exported {
		return "shared", scopeSource{kind: srcExported}
	}
	return m.rules.Unexported, scopeSource{kind: srcDefault}
}

// ownScope returns the scope directive written on t itself, if any.
func (m *model) ownScope(t *target) *directive {
	if t.scope == nil || m.deleted[t.scope] {
		return nil
	}
	return t.scope
}

func (m *model) resolveScopes(skip map[*directive]bool) {
	m.deleted = skip
	m.reachCache = nil
	for _, d := range m.decls {
		d.scope, d.source = m.scopeOf(d, skip)
	}
}

// collectUses records, for every checked declaration, the places that name
// it in the analyzed files, in file order. An element of a struct literal
// written by position uses the field it fills.
func (m *model) collectUses() {
	info := m.pass.TypesInfo
	for _, f := range m.files {
		ast.Inspect(f.ast, func(n ast.Node) bool {
			switch n := n.(type) {
			case *ast.Ident:
				obj := info.Uses[n]
				if obj == nil {
					return true
				}
				if d := m.byObj[origin(obj)]; d != nil {
					d.uses = append(d.uses, use{pos: n.Pos(), end: n.End(), ident: n, file: f})
				}
			case *ast.CompositeLit:
				if len(n.Elts) == 0 {
					return true
				}
				if _, keyed := n.Elts[0].(*ast.KeyValueExpr); keyed {
					return true
				}
				st := literalStruct(info.TypeOf(n))
				if st == nil {
					return true
				}
				for i, e := range n.Elts {
					if i >= st.NumFields() {
						break
					}
					if d := m.byObj[origin(st.Field(i))]; d != nil {
						d.uses = append(d.uses, use{pos: e.Pos(), end: e.End(), file: f})
					}
				}
			}
			return true
		})
	}
}

// literalStruct returns the struct type a composite literal fills, when the
// literal names it: a struct type, or a type parameter whose constraint
// names exactly one struct.
func literalStruct(t types.Type) *types.Struct {
	if t == nil {
		return nil
	}
	if tp, ok := t.(*types.TypeParam); ok {
		iface, _ := tp.Constraint().Underlying().(*types.Interface)
		if iface == nil || iface.NumEmbeddeds() != 1 {
			return nil
		}
		et := iface.EmbeddedType(0)
		if u, ok := et.(*types.Union); ok {
			if u.Len() != 1 {
				return nil
			}
			et = u.Term(0).Type()
		}
		if p, ok := et.(*types.Pointer); ok {
			et = p.Elem()
		}
		if _, named := types.Unalias(et).(*types.Named); !named {
			return nil
		}
		st, _ := et.Underlying().(*types.Struct)
		return st
	}
	if p, ok := t.Underlying().(*types.Pointer); ok {
		t = p.Elem()
	}
	st, _ := t.Underlying().(*types.Struct)
	return st
}

func origin(obj types.Object) types.Object {
	switch o := obj.(type) {
	case *types.Var:
		return o.Origin()
	case *types.Func:
		return o.Origin()
	}
	return obj
}

// crossing returns the uses of d from outside its namespace.
func (d *decl) crossing() []use {
	var out []use
	for _, u := range d.uses {
		if u.file.ns != d.ns {
			out = append(out, u)
		}
	}
	return out
}
