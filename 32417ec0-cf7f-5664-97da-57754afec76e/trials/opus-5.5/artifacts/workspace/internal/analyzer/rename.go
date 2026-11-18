package analyzer

import (
	"go/ast"
	"go/token"
	"go/types"
	"os"
	"sync"

	"declscope/internal/checker"
)

// sourceCache holds file contents read for fixes.
var sourceCache = &srcCache{m: make(map[string]string)}

type srcCache struct {
	mu sync.Mutex
	m  map[string]string
}

func (c *srcCache) get(name string) (string, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if s, ok := c.m[name]; ok {
		return s, true
	}
	b, err := os.ReadFile(name)
	if err != nil {
		return "", false
	}
	c.m[name] = string(b)
	return string(b), true
}

// mentions reports whether any identifier in the files is spelled name.
func mentions(files []*ast.File, names ...string) bool {
	found := false
	for _, f := range files {
		ast.Inspect(f, func(n ast.Node) bool {
			if found {
				return false
			}
			if id, ok := n.(*ast.Ident); ok {
				for _, name := range names {
					if id.Name == name {
						found = true
						return false
					}
				}
			}
			return true
		})
		if found {
			return true
		}
	}
	return false
}

// rename returns the edits that rename d to newName, or nil when the
// rename cannot be shown to change nothing but the spelling.
func (m *model) rename(d *decl, newName string) []checker.TextEdit {
	if m.hasAsm || m.unseenTests && !m.testVariant {
		return nil
	}
	if mentions(m.unseen, d.name, newName) || mentions(m.genFiles, d.name, newName) {
		return nil
	}
	pkg := m.pass.Types
	if pkg.Scope().Lookup(newName) != nil {
		return nil
	}
	info := m.pass.TypesInfo
	idents := []*ast.Ident{d.ident}
	for _, u := range d.uses {
		if u.ident != nil {
			idents = append(idents, u.ident)
		}
	}

	switch obj := d.obj.(type) {
	case *types.Func:
		if !m.methodRenamable(obj, newName) {
			return nil
		}
	case *types.TypeName:
		fields, ok := m.embeddings(obj, newName)
		if !ok {
			return nil
		}
		for _, fv := range fields {
			for _, f := range m.files {
				ast.Inspect(f.ast, func(n ast.Node) bool {
					if sel, ok := n.(*ast.SelectorExpr); ok {
						if info.Uses[sel.Sel] != nil && origin(info.Uses[sel.Sel]) == fv {
							idents = append(idents, sel.Sel)
						}
					}
					if kv, ok := n.(*ast.KeyValueExpr); ok {
						if id, ok := kv.Key.(*ast.Ident); ok && info.Uses[id] != nil && origin(info.Uses[id]) == fv {
							idents = append(idents, id)
						}
					}
					return true
				})
			}
		}
	}

	// No use may be captured by a declaration of the new name in an
	// enclosing scope, and no file may import a package under it.
	for _, f := range m.files {
		if s := info.Scopes[f.ast]; s != nil && s.Lookup(newName) != nil {
			return nil
		}
	}
	if d.kind != "method" {
		for _, id := range idents {
			if id == d.ident {
				continue
			}
			s := m.innermostScope(id)
			if s == nil {
				continue
			}
			if _, obj := s.LookupParent(newName, id.Pos()); obj != nil && obj.Parent() != pkg.Scope() && obj.Parent() != types.Universe {
				return nil
			}
		}
	}

	if !m.claimName(d.obj, newName) {
		return nil
	}

	seen := make(map[*ast.Ident]bool)
	var edits []checker.TextEdit
	for _, id := range idents {
		if seen[id] {
			continue
		}
		seen[id] = true
		edits = append(edits, checker.TextEdit{Pos: id.Pos(), End: id.End(), NewText: []byte(newName)})
	}
	return edits
}

// claimName reserves the name a rename gives: two renames in one package
// never take the same name, and the first written does.
func (m *model) claimName(obj types.Object, newName string) bool {
	if m.claims == nil {
		m.claims = make(map[string]bool)
	}
	if m.claims[newName] {
		return false
	}
	m.claims[newName] = true
	return true
}

// innermostScope finds the scope that encloses an identifier.
func (m *model) innermostScope(id *ast.Ident) *types.Scope {
	return m.pass.Types.Scope().Innermost(id.Pos())
}

// methodRenamable checks that a method's new name is free on its receiver
// and asked for by no interface of the package, and that no interface asks
// for its old name either.
func (m *model) methodRenamable(fn *types.Func, newName string) bool {
	sig := fn.Signature()
	if sig.Recv() == nil {
		return true
	}
	pkg := m.pass.Types
	recv := sig.Recv().Type()
	if obj, _, _ := types.LookupFieldOrMethod(recv, true, pkg, newName); obj != nil {
		return false
	}
	scope := pkg.Scope()
	for _, name := range scope.Names() {
		tn, ok := scope.Lookup(name).(*types.TypeName)
		if !ok {
			continue
		}
		iface, ok := tn.Type().Underlying().(*types.Interface)
		if !ok {
			continue
		}
		for i := 0; i < iface.NumMethods(); i++ {
			mn := iface.Method(i).Name()
			if mn == fn.Name() || mn == newName {
				return false
			}
		}
	}
	// Types that embed the receiver hold the method too.
	named := baseNamed(recv)
	if named == nil {
		return true
	}
	for _, name := range scope.Names() {
		tn, ok := scope.Lookup(name).(*types.TypeName)
		if !ok || tn.Type() == named {
			continue
		}
		if embedsType(tn.Type(), named, map[types.Type]bool{}) {
			if obj, _, _ := types.LookupFieldOrMethod(tn.Type(), true, pkg, newName); obj != nil {
				return false
			}
		}
	}
	return true
}

func baseNamed(t types.Type) *types.Named {
	if p, ok := t.(*types.Pointer); ok {
		t = p.Elem()
	}
	n, _ := types.Unalias(t).(*types.Named)
	if n != nil {
		return n.Origin()
	}
	return nil
}

// embedsType reports whether t embeds target, directly or through other
// embedded structs.
func embedsType(t types.Type, target *types.Named, seen map[types.Type]bool) bool {
	if seen[t] {
		return false
	}
	seen[t] = true
	st, ok := t.Underlying().(*types.Struct)
	if !ok {
		return false
	}
	for i := 0; i < st.NumFields(); i++ {
		f := st.Field(i)
		if !f.Embedded() {
			continue
		}
		n := baseNamed(f.Type())
		if n == nil {
			continue
		}
		if n == target || embedsType(n, target, seen) {
			return true
		}
	}
	return false
}

// embeddings finds the fields that embed a type. It reports false when a
// struct embedding it already holds the new name.
func (m *model) embeddings(tn *types.TypeName, newName string) ([]*types.Var, bool) {
	pkg := m.pass.Types
	var out []*types.Var
	ok := true
	check := func(st *types.Struct, holder types.Type) {
		for i := 0; i < st.NumFields(); i++ {
			f := st.Field(i)
			if !f.Embedded() {
				continue
			}
			n := baseNamed(f.Type())
			if n == nil || n.Obj() != tn {
				continue
			}
			out = append(out, f)
			if obj, _, _ := types.LookupFieldOrMethod(holder, true, pkg, newName); obj != nil {
				ok = false
			}
		}
	}
	for _, f := range m.files {
		ast.Inspect(f.ast, func(n ast.Node) bool {
			if st, isStruct := n.(*ast.StructType); isStruct {
				if tv, has := m.pass.TypesInfo.Types[st]; has {
					if s, isS := tv.Type.(*types.Struct); isS {
						holder := types.Type(s)
						check(s, holder)
					}
				}
			}
			return true
		})
	}
	// Check the named holders too, so methods count.
	scope := pkg.Scope()
	for _, name := range scope.Names() {
		h, isTN := scope.Lookup(name).(*types.TypeName)
		if !isTN {
			continue
		}
		st, isS := h.Type().Underlying().(*types.Struct)
		if !isS {
			continue
		}
		for i := 0; i < st.NumFields(); i++ {
			f := st.Field(i)
			if f.Embedded() {
				if n := baseNamed(f.Type()); n != nil && n.Obj() == tn {
					if obj, _, _ := types.LookupFieldOrMethod(h.Type(), true, pkg, newName); obj != nil {
						ok = false
					}
				}
			}
		}
	}
	return out, ok
}

var _ = token.NoPos
