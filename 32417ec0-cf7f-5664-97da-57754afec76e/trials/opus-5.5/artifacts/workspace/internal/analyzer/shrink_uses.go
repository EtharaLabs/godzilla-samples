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
	"strconv"
	"strings"

	"declscope/internal/checker"
	"declscope/internal/load"
)

const (
	reasonOwnExcl     = "a build-excluded file of its package names it"
	reasonOwnMayUse   = "a build-excluded file of its package may use it"
	reasonGenerated   = "a generated file names it"
	reasonXTest       = "external tests use it"
	reasonSetKept     = "another value of its const block keeps its name"
	reasonExcluded    = "a build-excluded file of another package may use it"
	reasonHanded      = "an exported declaration that keeps its name hands it out"
	reasonLdflags     = "a string variable may be set by -ldflags -X, which names it"
	reasonTaken       = "the unexported name is taken or would be captured"
	reasonTakenOnType = "the unexported name is taken on its type"
	reasonPredeclared = "the unexported name is predeclared"
	// Go spells names in mixedCaps: one with an underscore has no
	// unexported form to rename it to.
	reasonNoSpelling = "the name has no unexported spelling Go would use"
)

type shrinkState struct {
	res      *shrinkResult
	byObj    map[string]*shrinkCand // keyed by symbol, the same in every variant and load
	byPath   map[string]*shrinkUnit
	members  map[string][]*shrinkCand
	escaped  map[string]bool
	mayUse   map[string]bool
	owners   map[*types.Package]map[*types.Var]string
	ownNames map[*shrinkUnit]map[string]bool
	genNames map[*shrinkUnit]map[string]bool
}

func analyzeShrink(res *shrinkResult, us []*unit, configPath string, consultBaseline bool) {
	st := &shrinkState{
		res:      res,
		byObj:    make(map[string]*shrinkCand),
		byPath:   make(map[string]*shrinkUnit),
		members:  make(map[string][]*shrinkCand),
		escaped:  make(map[string]bool),
		mayUse:   make(map[string]bool),
		owners:   make(map[*types.Package]map[*types.Var]string),
		ownNames: make(map[*shrinkUnit]map[string]bool),
		genNames: make(map[*shrinkUnit]map[string]bool),
	}
	for _, su := range res.units {
		st.byPath[su.path] = su
		st.collect(su)
	}
	if len(st.byObj) == 0 && len(res.units) == 0 {
		return
	}
	for _, u := range us {
		st.scanUses(u)
	}
	for _, su := range res.units {
		st.tagged(su)
	}
	st.scanExcluded(us)
	// A declaration an ignore or the baseline keeps from being reported
	// keeps its name, as one in use does.
	for _, su := range res.units {
		if path := BaselinePath(su.pkg, su.rules); consultBaseline && path != "" {
			if b, err := LoadBaseline(path); err == nil {
				su.base = b
			}
		}
		for _, c := range su.cands {
			c.ignored = len(st.ignoresFor(c)) > 0 || su.base.Has(su.path, "overexported", c.ns, c.key)
		}
	}
	for _, su := range res.units {
		st.constSets(su)
	}
	st.reasons()
	st.findings(configPath)
}

// collect records the exported declarations of a judged package.
func (st *shrinkState) collect(su *shrinkUnit) {
	m := su.model
	info := su.pkg.TypesInfo
	add := func(id *ast.Ident, kind string, f *fileInfo, doc *ast.CommentGroup, t *target) *shrinkCand {
		if id == nil || !ast.IsExported(id.Name) {
			return nil
		}
		obj := info.Defs[id]
		if obj == nil {
			return nil
		}
		c := &shrinkCand{obj: obj, name: id.Name, kind: kind, ident: id, key: id.Name, file: f, doc: doc, target: t, unit: su, ns: f.ns.key(), isTest: f.isTest}
		su.cands = append(su.cands, c)
		st.byObj[st.symKey(obj)] = c
		return c
	}
	for _, f := range m.files {
		for _, t := range f.targets {
			switch t.kind {
			case tFunc:
				fd := t.node.(*ast.FuncDecl)
				if fd.Recv == nil {
					if f.isTest && isTestFunc(fd.Name.Name) {
						continue
					}
					add(fd.Name, "func", f, fd.Doc, t)
					continue
				}
				c := add(fd.Name, "method", f, fd.Doc, t)
				if c == nil {
					continue
				}
				c.method = true
				if fn, ok := c.obj.(*types.Func); ok && fn.Signature().Recv() != nil {
					if n := baseNamed(fn.Signature().Recv().Type()); n != nil {
						c.typeOf = n.Obj()
						c.key = n.Obj().Name() + "." + c.name
						st.members[st.symKey(c.typeOf)] = append(st.members[st.symKey(c.typeOf)], c)
					}
				}
			case tGen, tBlock:
				gd := t.node.(*ast.GenDecl)
				for i, s := range gd.Specs {
					stt := t
					if t.kind == tBlock {
						stt = t.children[i]
					}
					switch s := s.(type) {
					case *ast.ValueSpec:
						kind := "var"
						if gd.Tok == token.CONST {
							kind = "const"
						}
						doc := s.Doc
						if t.kind == tGen {
							doc = gd.Doc
						}
						for _, id := range s.Names {
							add(id, kind, f, doc, stt)
						}
					case *ast.TypeSpec:
						doc := s.Doc
						if t.kind == tGen {
							doc = gd.Doc
						}
						add(s.Name, "type", f, doc, stt)
						tn, _ := info.Defs[s.Name].(*types.TypeName)
						st.collectFields(su, f, s, stt, tn)
					}
				}
			}
		}
	}
}

func isTestFunc(name string) bool {
	for _, p := range []string{"Test", "Benchmark", "Fuzz", "Example"} {
		if strings.HasPrefix(name, p) {
			return true
		}
	}
	return false
}

func (st *shrinkState) collectFields(su *shrinkUnit, f *fileInfo, s *ast.TypeSpec, stt *target, tn *types.TypeName) {
	stype, ok := s.Type.(*ast.StructType)
	if !ok || tn == nil {
		return
	}
	info := su.pkg.TypesInfo
	i := 0
	for _, ft := range stt.children {
		if ft.kind != tField {
			continue
		}
		field := stype.Fields.List[i]
		i++
		for _, id := range field.Names {
			if !ast.IsExported(id.Name) {
				continue
			}
			obj := info.Defs[id]
			if obj == nil {
				continue
			}
			c := &shrinkCand{obj: obj, name: id.Name, kind: "field", ident: id, key: tn.Name() + "." + id.Name, file: f, doc: field.Doc, target: ft, unit: su, ns: f.ns.key(), member: true, typeOf: tn, isTest: f.isTest}
			su.cands = append(su.cands, c)
			st.byObj[st.symKey(obj)] = c
			st.members[st.symKey(tn)] = append(st.members[st.symKey(tn)], c)
		}
	}
}

// symKey names an object the same way in every load: package path, then
// the type for a method or a field, then the name.
func (st *shrinkState) symKey(obj types.Object) string {
	obj = origin(obj)
	pkg := obj.Pkg()
	if pkg == nil {
		return ""
	}
	switch o := obj.(type) {
	case *types.Func:
		if recv := o.Signature().Recv(); recv != nil {
			if n := baseNamed(recv.Type()); n != nil {
				return pkg.Path() + "." + n.Obj().Name() + "." + o.Name()
			}
			return ""
		}
	case *types.Var:
		if o.IsField() {
			owner := st.fieldOwner(o)
			if owner == "" {
				return ""
			}
			return pkg.Path() + "." + owner + "." + o.Name()
		}
	}
	if obj.Parent() != pkg.Scope() {
		return ""
	}
	return pkg.Path() + "." + obj.Name()
}

// fieldOwner names the package-level type whose struct declares a field.
func (st *shrinkState) fieldOwner(v *types.Var) string {
	m := st.owners[v.Pkg()]
	if m == nil {
		m = make(map[*types.Var]string)
		scope := v.Pkg().Scope()
		for _, name := range scope.Names() {
			tn, ok := scope.Lookup(name).(*types.TypeName)
			if !ok {
				continue
			}
			if s, ok := tn.Type().Underlying().(*types.Struct); ok {
				for i := 0; i < s.NumFields(); i++ {
					m[s.Field(i)] = name
				}
			}
		}
		st.owners[v.Pkg()] = m
	}
	return m[v]
}

// mark records a use of an object from package from.
func (st *shrinkState) mark(obj types.Object, from string) {
	c := st.byObj[st.symKey(obj)]
	if c == nil || from == c.unit.path {
		return
	}
	if from == c.unit.path+"_test" {
		c.xtest = true
		return
	}
	c.external = true
}

// scanUses records the uses one package makes of judged declarations.
func (st *shrinkState) scanUses(u *unit) {
	info := u.pkg.TypesInfo
	if info == nil {
		return
	}
	from := u.path
	for _, f := range u.pkg.Syntax {
		ast.Inspect(f, func(n ast.Node) bool {
			switch n := n.(type) {
			case *ast.Ident:
				if obj := info.Uses[n]; obj != nil {
					st.mark(obj, from)
					// An embedded field is spelled with its type's name.
					if v, ok := obj.(*types.Var); ok && v.Embedded() {
						if nt := baseNamed(v.Type()); nt != nil {
							st.mark(nt.Obj(), from)
						}
					}
				}
			case *ast.CompositeLit:
				if len(n.Elts) == 0 {
					break
				}
				if _, keyed := n.Elts[0].(*ast.KeyValueExpr); keyed {
					break
				}
				if s := literalStruct(info.TypeOf(n)); s != nil {
					for i := range n.Elts {
						if i < s.NumFields() {
							st.mark(s.Field(i), from)
						}
					}
				}
			}
			return true
		})
		conversions(info, f, func(t, iface types.Type, live bool) {
			if live {
				st.escape(t, map[types.Type]bool{})
			}
			st.satisfies(t, iface)
		})
	}
	// The types of the expressions of another package reach the types they
	// mention. The external tests' expressions do not: they reach a type
	// only by naming it.
	for _, tv := range info.Types {
		if tv.Type == nil {
			continue
		}
		walkNamed(tv.Type, map[types.Type]bool{}, func(tn *types.TypeName) {
			if c := st.byObj[st.symKey(tn)]; c != nil && from == c.unit.path+"_test" {
				return
			}
			st.mark(tn, from)
		})
	}
}

// walkNamed calls visit for every named type a type mentions, without
// looking inside the named types themselves.
func walkNamed(t types.Type, seen map[types.Type]bool, visit func(*types.TypeName)) {
	if t == nil || seen[t] {
		return
	}
	seen[t] = true
	switch t := t.(type) {
	case *types.Named:
		visit(t.Origin().Obj())
		for i := 0; i < t.TypeArgs().Len(); i++ {
			walkNamed(t.TypeArgs().At(i), seen, visit)
		}
	case *types.Alias:
		visit(t.Obj())
		walkNamed(types.Unalias(t), seen, visit)
	case *types.Pointer:
		walkNamed(t.Elem(), seen, visit)
	case *types.Slice:
		walkNamed(t.Elem(), seen, visit)
	case *types.Array:
		walkNamed(t.Elem(), seen, visit)
	case *types.Map:
		walkNamed(t.Key(), seen, visit)
		walkNamed(t.Elem(), seen, visit)
	case *types.Chan:
		walkNamed(t.Elem(), seen, visit)
	case *types.Signature:
		walkNamed(t.Params(), seen, visit)
		walkNamed(t.Results(), seen, visit)
	case *types.Tuple:
		for i := 0; i < t.Len(); i++ {
			walkNamed(t.At(i).Type(), seen, visit)
		}
	case *types.Struct:
		for i := 0; i < t.NumFields(); i++ {
			walkNamed(t.Field(i).Type(), seen, visit)
		}
	}
}

// escape marks a type whose values may be read through an interface or by
// reflection: the type, its methods and its fields, and the types of its
// fields in turn.
func (st *shrinkState) escape(t types.Type, seen map[types.Type]bool) {
	if t == nil || seen[t] {
		return
	}
	seen[t] = true
	switch t := t.(type) {
	case *types.Named:
		tn := t.Origin().Obj()
		if k := st.symKey(tn); !st.escaped[k] {
			st.escaped[k] = true
			if c := st.byObj[k]; c != nil {
				c.external = true
			}
			for _, c := range st.members[k] {
				c.external = true
			}
		}
		st.escape(t.Underlying(), seen)
	case *types.Alias:
		st.escape(types.Unalias(t), seen)
	case *types.Pointer:
		st.escape(t.Elem(), seen)
	case *types.Slice:
		st.escape(t.Elem(), seen)
	case *types.Array:
		st.escape(t.Elem(), seen)
	case *types.Map:
		st.escape(t.Key(), seen)
		st.escape(t.Elem(), seen)
	case *types.Chan:
		st.escape(t.Elem(), seen)
	case *types.Struct:
		for i := 0; i < t.NumFields(); i++ {
			if c := st.byObj[st.symKey(t.Field(i))]; c != nil {
				c.external = true
			}
			st.escape(t.Field(i).Type(), seen)
		}
	}
}

// satisfies marks the methods of t that an interface asks for.
func (st *shrinkState) satisfies(t, iface types.Type) {
	it, ok := iface.Underlying().(*types.Interface)
	if !ok || it.NumMethods() == 0 {
		return
	}
	ms := types.NewMethodSet(t)
	if _, isPtr := t.(*types.Pointer); !isPtr {
		ms = types.NewMethodSet(types.NewPointer(t))
	}
	for i := 0; i < it.NumMethods(); i++ {
		if sel := ms.Lookup(it.Method(i).Pkg(), it.Method(i).Name()); sel != nil {
			if c := st.byObj[st.symKey(sel.Obj())]; c != nil {
				c.external = true
			}
		}
	}
}

// tagged treats a struct with a tagged field as read by a marshaller.
func (st *shrinkState) tagged(su *shrinkUnit) {
	for _, c := range su.cands {
		tn, ok := c.obj.(*types.TypeName)
		if !ok {
			continue
		}
		s, ok := tn.Type().Underlying().(*types.Struct)
		if !ok {
			continue
		}
		for i := 0; i < s.NumFields(); i++ {
			if s.Tag(i) != "" {
				st.escape(tn.Type(), map[types.Type]bool{})
				break
			}
		}
	}
}

// scanExcluded reads the Go files of the module that no package loaded,
// for the names they write, since they are not type-checked.
func (st *shrinkState) scanExcluded(us []*unit) {
	loaded := make(map[string]bool)
	var roots []string
	for _, u := range us {
		p := u.pkg
		for _, f := range p.GoFiles {
			loaded[f] = true
		}
		for _, f := range p.CompiledGoFiles {
			loaded[f] = true
		}
		if p.Raw != nil {
			for _, list := range [][]string{p.TestGoFiles(), p.XTestGoFiles()} {
				for _, f := range list {
					loaded[f] = true
				}
			}
		}
		if p.Module != nil && p.Module.Dir != "" {
			roots = append(roots, p.Module.Dir)
		}
	}
	sort.Strings(roots)
	byDir := make(map[string]*shrinkUnit)
	for _, su := range st.res.units {
		byDir[su.pkg.Dir] = su
	}
	seenRoot := make(map[string]bool)
	for _, root := range roots {
		if seenRoot[root] {
			continue
		}
		seenRoot[root] = true
		for _, path := range moduleGoFiles(root) {
			if loaded[path] {
				continue
			}
			st.readExcluded(path, byDir)
		}
	}
}

// moduleGoFiles lists the Go files under a module root the way ./... walks
// it: no testdata, vendor, hidden or underscore directories, and no nested
// modules.
func moduleGoFiles(root string) []string {
	var out []string
	filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		name := d.Name()
		if d.IsDir() {
			if path == root {
				return nil
			}
			if strings.HasPrefix(name, ".") || strings.HasPrefix(name, "_") || name == "testdata" || name == "vendor" {
				return filepath.SkipDir
			}
			if _, err := os.Stat(filepath.Join(path, "go.mod")); err == nil {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.HasSuffix(name, ".go") && !strings.HasPrefix(name, ".") && !strings.HasPrefix(name, "_") {
			out = append(out, path)
		}
		return nil
	})
	return out
}

func (st *shrinkState) readExcluded(path string, byDir map[string]*shrinkUnit) {
	f, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.SkipObjectResolution)
	if f == nil || f.Name == nil {
		_ = err
		return
	}
	if su := byDir[filepath.Dir(path)]; su != nil && (f.Name.Name == su.pkg.Name) {
		names := st.ownNames[su]
		if names == nil {
			names = make(map[string]bool)
			st.ownNames[su] = names
		}
		ast.Inspect(f, func(n ast.Node) bool {
			if id, ok := n.(*ast.Ident); ok {
				names[id.Name] = true
			}
			return true
		})
		return
	}
	imports := make(map[string]*shrinkUnit)
	for _, is := range f.Imports {
		p, err := strconv.Unquote(is.Path.Value)
		if err != nil {
			continue
		}
		su := st.byPath[p]
		if su == nil {
			continue
		}
		name := su.pkg.Name
		if is.Name != nil {
			name = is.Name.Name
		}
		imports[name] = su
	}
	if len(imports) == 0 {
		return
	}
	ast.Inspect(f, func(n ast.Node) bool {
		sel, ok := n.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		x, ok := sel.X.(*ast.Ident)
		if !ok {
			return true
		}
		su := imports[x.Name]
		if su == nil {
			return true
		}
		obj := su.pkg.Types.Scope().Lookup(sel.Sel.Name)
		if obj == nil {
			return true
		}
		if c := st.byObj[st.symKey(obj)]; c != nil {
			c.external = true
		}
		walkNamed(obj.Type(), map[types.Type]bool{}, func(tn *types.TypeName) {
			st.mayUse[st.symKey(tn)] = true
		})
		if tn, ok := obj.(*types.TypeName); ok {
			st.mayUse[st.symKey(tn)] = true
		}
		return true
	})
}

// constSets treats a block of two or more constants of one type as a set.
func (st *shrinkState) constSets(su *shrinkUnit) {
	for _, f := range su.model.files {
		for _, t := range f.targets {
			if t.kind != tBlock {
				continue
			}
			gd := t.node.(*ast.GenDecl)
			if gd.Tok != token.CONST {
				continue
			}
			var consts []*shrinkCand
			var typ types.Type
			same := true
			for _, s := range gd.Specs {
				vs := s.(*ast.ValueSpec)
				for _, id := range vs.Names {
					obj := su.pkg.TypesInfo.Defs[id]
					if obj == nil {
						continue
					}
					if typ == nil {
						typ = obj.Type()
					} else if !types.Identical(typ, obj.Type()) {
						same = false
					}
					if c := st.byObj[st.symKey(obj)]; c != nil {
						consts = append(consts, c)
					}
				}
			}
			named, _ := types.Unalias(typ).(*types.Named)
			if !same || named == nil || len(consts) < 2 {
				continue
			}
			used, tested := false, false
			// A type the ignore keeps exported keeps its values too.
			if c := st.byObj[st.symKey(named.Obj())]; c != nil && (c.external || c.ignored) {
				used = true
			}
			if named.Obj().Pkg() != nil && named.Obj().Pkg().Path() != su.path {
				used = true
			}
			for _, c := range consts {
				if c.external {
					used = true
				}
				if c.xtest || c.ignored {
					tested = true
				}
			}
			for _, c := range consts {
				switch {
				case used:
					c.external = true
				case tested && !c.xtest && !c.ignored:
					// A value the external tests or an ignore keep keeps
					// the set.
					c.setKept = true
				}
			}
		}
	}
}

// keeps reports whether a declaration keeps its exported name after a fix
// run: it is used, or reported without a fix.
func (c *shrinkCand) keeps() bool {
	return c.external || c.xtest || c.ignored || c.reason != ""
}

// embedders lists the named types of a package that embed tn, directly or
// through other embedded types.
func (st *shrinkState) embedders(su *shrinkUnit, tn *types.TypeName) []*types.TypeName {
	scope := su.pkg.Types.Scope()
	embeds := func(holder, target *types.TypeName) bool {
		s, ok := holder.Type().Underlying().(*types.Struct)
		if !ok {
			return false
		}
		for i := 0; i < s.NumFields(); i++ {
			if f := s.Field(i); f.Embedded() {
				if n := baseNamed(f.Type()); n != nil && n.Obj() == target {
					return true
				}
			}
		}
		return false
	}
	var out []*types.TypeName
	seen := map[*types.TypeName]bool{tn: true}
	queue := []*types.TypeName{tn}
	for len(queue) > 0 {
		t := queue[0]
		queue = queue[1:]
		for _, name := range scope.Names() {
			h, ok := scope.Lookup(name).(*types.TypeName)
			if !ok || seen[h] || !embeds(h, t) {
				continue
			}
			seen[h] = true
			out = append(out, h)
			queue = append(queue, h)
		}
	}
	return out
}

// generatedNames lists the identifiers the generated files of a package
// spell.
func (st *shrinkState) generatedNames(su *shrinkUnit) map[string]bool {
	if names, ok := st.genNames[su]; ok {
		return names
	}
	names := make(map[string]bool)
	for _, f := range su.model.genFiles {
		ast.Inspect(f, func(n ast.Node) bool {
			if id, ok := n.(*ast.Ident); ok {
				names[id.Name] = true
			}
			return true
		})
	}
	st.genNames[su] = names
	return names
}

// reasons decides, for every unused declaration, whether a fix can be
// offered.
func (st *shrinkState) reasons() {
	var all []*shrinkCand
	for _, su := range st.res.units {
		all = append(all, su.cands...)
	}
	// Two declarations that unexport to one name cannot both take it: the
	// first written does.
	type spot struct {
		scope any
		name  string
	}
	claimed := make(map[spot]bool)
	claim := func(c *shrinkCand) bool {
		name := lowerWord(c.name)
		if !(c.method || c.member) || c.typeOf == nil {
			k := spot{c.unit, name}
			if claimed[k] {
				return false
			}
			claimed[k] = true
			return true
		}
		// A member's new name is promoted to every type that embeds its
		// own: it takes the name there too.
		if claimed[spot{c.typeOf, name}] {
			return false
		}
		claimed[spot{c.typeOf, name}] = true
		for _, h := range st.embedders(c.unit, c.typeOf) {
			claimed[spot{h, name}] = true
		}
		return true
	}
	for _, c := range all {
		if c.external {
			continue
		}
		switch {
		case c.xtest:
			c.reason = reasonXTest
		case c.setKept:
			c.reason = reasonSetKept
		case c.unit.noFix != "":
			c.reason = c.unit.noFix
		case st.ownNames[c.unit][c.name]:
			c.reason = reasonOwnExcl
		case (c.method || c.member) && st.ownNames[c.unit] != nil:
			// A build-excluded file of the package is not type-checked:
			// any value it holds may reach a field or a method.
			c.reason = reasonOwnMayUse
		case st.generatedNames(c.unit)[c.name]:
			c.reason = reasonGenerated
		case (c.method || c.member) && c.typeOf != nil && st.mayUse[st.symKey(c.typeOf)]:
			c.reason = reasonExcluded
		case c.kind == "var" && isString(c.obj.Type()):
			c.reason = reasonLdflags
		case strings.Contains(c.name, "_"):
			c.reason = reasonNoSpelling
		case types.Universe.Lookup(lowerWord(c.name)) != nil:
			c.reason = reasonPredeclared
		case !st.renamable(c) || !claim(c):
			c.reason = reasonTaken
			if c.method || c.member {
				c.reason = reasonTakenOnType
			}
		}
	}
	// A type an exported declaration keeps handing out cannot be unexported.
	for changed := true; changed; {
		changed = false
		for _, c := range all {
			if c.external || c.reason != "" || c.kind != "type" {
				continue
			}
			tn := c.obj.(*types.TypeName)
			for _, d := range c.unit.cands {
				if d == c || !d.keeps() {
					continue
				}
				if typeMentions(d, tn) {
					c.reason = reasonHanded
					changed = true
					break
				}
			}
		}
	}
	for _, c := range all {
		c.fixable = !c.external && c.reason == ""
	}
}

func isString(t types.Type) bool {
	b, ok := t.(*types.Basic)
	return ok && b.Kind() == types.String
}

// typeMentions reports whether the type of a declaration names tn.
func typeMentions(d *shrinkCand, tn *types.TypeName) bool {
	var t types.Type
	switch obj := d.obj.(type) {
	case *types.TypeName:
		if obj.IsAlias() {
			t = types.Unalias(obj.Type())
		} else if _, isStruct := obj.Type().Underlying().(*types.Struct); !isStruct {
			t = obj.Type().Underlying()
		}
	default:
		t = obj.Type()
	}
	found := false
	walkNamed(t, map[types.Type]bool{}, func(x *types.TypeName) {
		if x.Pkg() == tn.Pkg() && x.Name() == tn.Name() || x.Pos() == tn.Pos() {
			found = true
		}
	})
	return found
}

// renamable reports whether lowering the name changes nothing else.
func (st *shrinkState) renamable(c *shrinkCand) bool {
	newName := lowerWord(c.name)
	pkg := c.unit.pkg.Types
	info := c.unit.pkg.TypesInfo
	if newName == c.name {
		return false
	}
	switch {
	case c.method || c.member:
		if c.typeOf != nil {
			if obj, _, _ := types.LookupFieldOrMethod(c.typeOf.Type(), true, pkg, newName); obj != nil {
				return false
			}
		}
		// An interface of the package that asks for the new name would
		// change its answer to a type assertion.
		{
			for _, fn := range c.unit.model.ifaceMethods() {
				if fn.Name() == newName {
					return false
				}
			}
		}
		// Every type that embeds its own must have the name free too.
		if c.typeOf != nil {
			for _, holder := range st.embedders(c.unit, c.typeOf) {
				if other, _, _ := types.LookupFieldOrMethod(holder.Type(), true, pkg, newName); other != nil {
					return false
				}
			}
		}
		return true
	}
	if pkg.Scope().Lookup(newName) != nil || types.Universe.Lookup(newName) != nil {
		return false
	}
	// A type a struct embeds names a field of it too: the new name must be
	// free on every struct that holds it.
	if tn, ok := c.obj.(*types.TypeName); ok {
		for _, name := range pkg.Scope().Names() {
			holder, ok := pkg.Scope().Lookup(name).(*types.TypeName)
			if !ok {
				continue
			}
			st, ok := holder.Type().Underlying().(*types.Struct)
			if !ok {
				continue
			}
			for i := 0; i < st.NumFields(); i++ {
				f := st.Field(i)
				if n := baseNamed(f.Type()); f.Embedded() && n != nil && n.Obj() == tn {
					if obj, _, _ := types.LookupFieldOrMethod(holder.Type(), true, pkg, newName); obj != nil {
						return false
					}
				}
			}
		}
	}
	for _, f := range c.unit.pkg.Syntax {
		if s := info.Scopes[f]; s != nil && s.Lookup(newName) != nil {
			return false
		}
	}
	for _, id := range st.refs(c) {
		if id == c.ident {
			continue
		}
		s := pkg.Scope().Innermost(id.Pos())
		if s == nil {
			continue
		}
		if _, obj := s.LookupParent(newName, id.Pos()); obj != nil && obj.Parent() != pkg.Scope() && obj.Parent() != types.Universe {
			return false
		}
	}
	return true
}

// refs returns every identifier of the package that names a declaration.
func (st *shrinkState) refs(c *shrinkCand) []*ast.Ident {
	info := c.unit.pkg.TypesInfo
	var out []*ast.Ident
	for _, f := range c.unit.pkg.Syntax {
		ast.Inspect(f, func(n ast.Node) bool {
			id, ok := n.(*ast.Ident)
			if !ok {
				return true
			}
			if obj := info.Defs[id]; obj != nil && origin(obj).Pos() == c.obj.Pos() {
				out = append(out, id)
			} else if obj := info.Uses[id]; obj != nil && (origin(obj).Pos() == c.obj.Pos() || embedsCand(obj, c)) {
				out = append(out, id)
			}
			return true
		})
	}
	return out
}

// findings builds the reports, consulting ignores and the baseline.
func (st *shrinkState) findings(configPath string) {
	for _, su := range st.res.units {
		base := su.base
		var fs []*shrinkFinding
		for _, c := range su.cands {
			if c.external {
				continue
			}
			var msg string
			if c.xtest {
				msg = fmt.Sprintf("%s %s is exported, but only the external tests of %s use it", c.kind, c.name, su.path)
			} else {
				msg = fmt.Sprintf("%s %s is exported, but nothing outside %s uses it", c.kind, c.name, su.path)
			}
			if c.reason != "" {
				msg += " (no fix: " + c.reason + ")"
			}
			f := &shrinkFinding{pos: c.ident.Pos(), message: msg, cand: c, unit: su, ns: c.ns, key: c.key}
			if c.fixable {
				f.fix = st.renameEdits(c)
			}
			st.res.all = append(st.res.all, f)
			if igs := st.ignoresFor(c); len(igs) > 0 {
				for _, ig := range igs {
					ig.used = true
				}
				f.ignored = true
				continue
			}
			if base.Has(su.path, "overexported", c.ns, c.key) {
				continue
			}
			fs = append(fs, f)
		}
		fs = append(fs, st.unusedIgnores(su)...)
		sort.SliceStable(fs, func(i, j int) bool {
			pi, pj := st.res.fset.Position(fs[i].pos), st.res.fset.Position(fs[j].pos)
			if pi.Filename != pj.Filename {
				return pi.Filename < pj.Filename
			}
			return pi.Offset < pj.Offset
		})
		st.res.findings = append(st.res.findings, fs...)
	}
}

// ignoresFor lists the ignores of overexported that cover a declaration.
func (st *shrinkState) ignoresFor(c *shrinkCand) []*directive {
	var out []*directive
	add := func(igs []*directive) {
		for _, ig := range igs {
			if !ig.bare && ig.covers("overexported") {
				out = append(out, ig)
			}
		}
	}
	for t := c.target; t != nil; t = t.parent {
		add(t.ignores)
	}
	add(c.file.ignores)
	return out
}

// unusedIgnores reports ignores of overexported that silenced nothing.
func (st *shrinkState) unusedIgnores(su *shrinkUnit) []*shrinkFinding {
	var out []*shrinkFinding
	for _, f := range su.model.files {
		for _, d := range f.directives {
			// An ignore naming other rules too is the analyzer's to judge.
			if !d.effective || d.name != "ignore" || d.bare || d.used || len(d.rules) != 1 || d.rules[0] != "overexported" {
				continue
			}
			// "ignore unused" next to it, or above the package clause,
			// answers the report.
			silenced := false
			var site []*directive
			if !d.fileLevel && d.target != nil {
				site = d.target.ignores
			}
			for _, ig := range append(site, f.ignores...) {
				if ig != d && !ig.bare && ig.covers("unused") {
					silenced = true
				}
				if ig != d && ig.bare && ig.fileLevel {
					silenced = true
				}
			}
			if silenced {
				continue
			}
			out = append(out, &shrinkFinding{pos: d.pos(), message: "unused //declscope:ignore " + d.ruleText() + ": nothing it covers is reported", unit: su})
		}
	}
	return out
}

// renameEdits unexports a declaration everywhere its package names it,
// and in the first line of its doc comment.
func (st *shrinkState) renameEdits(c *shrinkCand) []checker.TextEdit {
	newName := lowerWord(c.name)
	var edits []checker.TextEdit
	seen := make(map[token.Pos]bool)
	for _, id := range st.refs(c) {
		if seen[id.Pos()] {
			continue
		}
		seen[id.Pos()] = true
		edits = append(edits, checker.TextEdit{Pos: id.Pos(), End: id.End(), NewText: []byte(newName)})
	}
	if c.doc != nil && len(c.doc.List) > 0 {
		first := c.doc.List[0]
		text := first.Text
		prefix := "// " + c.name
		if strings.HasPrefix(text, prefix) {
			rest := text[len(prefix):]
			if rest == "" || !isIdentRune(rest) {
				start := first.Slash + token.Pos(3)
				edits = append(edits, checker.TextEdit{Pos: start, End: start + token.Pos(len(c.name)), NewText: []byte(newName)})
			}
		}
	}
	return edits
}

// embedsCand reports whether obj is a field that embeds the type c, and so
// is spelled with its name.
func embedsCand(obj types.Object, c *shrinkCand) bool {
	v, ok := obj.(*types.Var)
	if !ok || !v.Embedded() || c.kind != "type" {
		return false
	}
	n := baseNamed(v.Type())
	return n != nil && n.Obj().Pos() == c.obj.Pos()
}

func isIdentRune(s string) bool {
	r := []rune(s)[0]
	return r == '_' || 'a' <= r && r <= 'z' || 'A' <= r && r <= 'Z' || '0' <= r && r <= '9' || r > 127
}

var _ = os.Stderr
var _ load.Error
