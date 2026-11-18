package analyzer

import (
	"go/ast"
	"go/token"
	"go/types"
)

// conversions calls found for every value a file converts to an interface
// type: the concrete type of the value and the interface. Go converts
// implicitly on assignment, on passing an argument or returning a result,
// inside composite literals, on sends, on comparisons with an interface,
// and explicitly with a conversion. live is false for a conversion whose
// result is discarded at once, as on assignment to the blank identifier,
// or that sits in a function literal nothing calls or keeps.
func conversions(info *types.Info, file *ast.File, found func(src, iface types.Type, live bool)) {
	live := true
	deadLits := deadFuncLits(info, file)
	blank := false
	check := func(src ast.Expr, dst types.Type) {
		if src == nil || dst == nil {
			return
		}
		if !types.IsInterface(dst) {
			return
		}
		tv, ok := info.Types[src]
		if !ok || tv.Type == nil || tv.IsNil() {
			return
		}
		if types.IsInterface(tv.Type) {
			return
		}
		if _, ok := tv.Type.(*types.TypeParam); ok {
			return
		}
		found(tv.Type, dst, live && !blank)
	}
	typeOf := func(e ast.Expr) types.Type {
		if tv, ok := info.Types[e]; ok {
			return tv.Type
		}
		if id, ok := e.(*ast.Ident); ok {
			if obj := info.Defs[id]; obj != nil {
				return obj.Type()
			}
			if obj := info.Uses[id]; obj != nil {
				return obj.Type()
			}
		}
		return nil
	}
	var funcs []*types.Signature
	var visit func(n ast.Node) bool
	visit = func(n ast.Node) bool {
		switch n := n.(type) {
		case *ast.FuncDecl:
			if obj, ok := info.Defs[n.Name].(*types.Func); ok {
				funcs = append(funcs, obj.Type().(*types.Signature))
				if n.Body != nil {
					ast.Inspect(n.Body, visit)
				}
				funcs = funcs[:len(funcs)-1]
			}
			return false
		case *ast.FuncLit:
			if sig, ok := typeOf(n).(*types.Signature); ok {
				funcs = append(funcs, sig)
				saved := live
				if deadLits[n] {
					live = false
				}
				ast.Inspect(n.Body, visit)
				live = saved
				funcs = funcs[:len(funcs)-1]
			}
			return false
		case *ast.AssignStmt:
			if n.Tok == token.ASSIGN && len(n.Lhs) == len(n.Rhs) {
				for i := range n.Lhs {
					blank = isBlank(n.Lhs[i])
					check(n.Rhs[i], typeOf(n.Lhs[i]))
					blank = false
				}
			}
		case *ast.ValueSpec:
			if n.Type != nil && len(n.Values) == len(n.Names) {
				t := typeOf(n.Type)
				for i, v := range n.Values {
					blank = n.Names[i].Name == "_"
					check(v, t)
					blank = false
				}
			}
		case *ast.ReturnStmt:
			if len(funcs) == 0 {
				break
			}
			res := funcs[len(funcs)-1].Results()
			if res != nil && res.Len() == len(n.Results) {
				for i, r := range n.Results {
					check(r, res.At(i).Type())
				}
			}
		case *ast.CallExpr:
			callConversions(info, n, check, typeOf)
		case *ast.CompositeLit:
			t := typeOf(n)
			if t == nil {
				break
			}
			u := t.Underlying()
			if p, ok := u.(*types.Pointer); ok {
				u = p.Elem().Underlying()
			}
			switch u := u.(type) {
			case *types.Struct:
				for i, e := range n.Elts {
					if kv, ok := e.(*ast.KeyValueExpr); ok {
						if id, ok := kv.Key.(*ast.Ident); ok {
							if f, ok := info.Uses[id].(*types.Var); ok {
								check(kv.Value, f.Type())
							}
						}
					} else if i < u.NumFields() {
						check(e, u.Field(i).Type())
					}
				}
			case *types.Slice:
				elemConv(n.Elts, u.Elem(), check)
			case *types.Array:
				elemConv(n.Elts, u.Elem(), check)
			case *types.Map:
				for _, e := range n.Elts {
					if kv, ok := e.(*ast.KeyValueExpr); ok {
						check(kv.Key, u.Key())
						check(kv.Value, u.Elem())
					}
				}
			}
		case *ast.SendStmt:
			if ch, ok := typeOf(n.Chan).Underlying().(*types.Chan); ok {
				check(n.Value, ch.Elem())
			}
		case *ast.BinaryExpr:
			if n.Op == token.EQL || n.Op == token.NEQ {
				check(n.X, typeOf(n.Y))
				check(n.Y, typeOf(n.X))
			}
		case *ast.IndexExpr:
			if t := typeOf(n.X); t != nil {
				if m, ok := t.Underlying().(*types.Map); ok {
					check(n.Index, m.Key())
				}
			}
		case *ast.SwitchStmt:
			if n.Tag != nil {
				tag := typeOf(n.Tag)
				for _, s := range n.Body.List {
					if cc, ok := s.(*ast.CaseClause); ok {
						for _, e := range cc.List {
							check(e, tag)
						}
					}
				}
			}
		}
		return true
	}
	ast.Inspect(file, visit)
}

func isBlank(e ast.Expr) bool {
	id, ok := ast.Unparen(e).(*ast.Ident)
	return ok && id.Name == "_"
}

// deadFuncLits finds the function literals whose value is thrown away: assigned
// to the blank identifier, or to a local variable nothing reads but the
// blank identifier. Nothing can call them.
func deadFuncLits(info *types.Info, file *ast.File) map[*ast.FuncLit]bool {
	dead := make(map[*ast.FuncLit]bool)
	// Count, for every local variable, the reads that do not just discard it.
	reads := make(map[types.Object]int)
	discards := make(map[*ast.Ident]bool)
	ast.Inspect(file, func(n ast.Node) bool {
		if as, ok := n.(*ast.AssignStmt); ok && len(as.Lhs) == len(as.Rhs) {
			for i := range as.Lhs {
				if isBlank(as.Lhs[i]) {
					if id, ok := ast.Unparen(as.Rhs[i]).(*ast.Ident); ok {
						discards[id] = true
					}
				}
			}
		}
		if id, ok := n.(*ast.Ident); ok && !discards[id] {
			if obj := info.Uses[id]; obj != nil {
				reads[obj]++
			}
		}
		return true
	})
	consider := func(lhs []ast.Expr, rhs []ast.Expr, define bool) {
		if len(lhs) != len(rhs) {
			return
		}
		for i, r := range rhs {
			lit, ok := ast.Unparen(r).(*ast.FuncLit)
			if !ok {
				continue
			}
			if isBlank(lhs[i]) {
				dead[lit] = true
				continue
			}
			id, ok := lhs[i].(*ast.Ident)
			if !ok {
				continue
			}
			obj := info.Defs[id]
			if obj == nil {
				obj = info.Uses[id]
			}
			if v, ok := obj.(*types.Var); ok && v.Parent() != nil && v.Parent() != v.Pkg().Scope() && reads[obj] == 0 {
				dead[lit] = true
			}
		}
	}
	ast.Inspect(file, func(n ast.Node) bool {
		switch n := n.(type) {
		case *ast.AssignStmt:
			consider(n.Lhs, n.Rhs, n.Tok == token.DEFINE)
		case *ast.ValueSpec:
			var lhs []ast.Expr
			for _, id := range n.Names {
				lhs = append(lhs, id)
			}
			consider(lhs, n.Values, true)
		}
		return true
	})
	return dead
}

func elemConv(elts []ast.Expr, elem types.Type, check func(ast.Expr, types.Type)) {
	for _, e := range elts {
		if kv, ok := e.(*ast.KeyValueExpr); ok {
			e = kv.Value
		}
		check(e, elem)
	}
}

// callConversions handles the arguments of a call or a conversion.
func callConversions(info *types.Info, call *ast.CallExpr, check func(ast.Expr, types.Type), typeOf func(ast.Expr) types.Type) {
	fun := ast.Unparen(call.Fun)
	if tv, ok := info.Types[fun]; ok && tv.IsType() {
		if len(call.Args) == 1 {
			check(call.Args[0], tv.Type)
		}
		return
	}
	if tv, ok := info.Types[fun]; ok && tv.IsBuiltin() {
		id, _ := fun.(*ast.Ident)
		if id == nil {
			if sel, ok := fun.(*ast.SelectorExpr); ok {
				id = sel.Sel
			}
		}
		if id == nil {
			return
		}
		switch id.Name {
		case "append":
			if len(call.Args) > 1 && !call.Ellipsis.IsValid() {
				if s, ok := typeOf(call.Args[0]).Underlying().(*types.Slice); ok {
					elemConv(call.Args[1:], s.Elem(), check)
				}
			}
		case "panic":
			if len(call.Args) == 1 {
				check(call.Args[0], types.NewInterfaceType(nil, nil))
			}
		}
		return
	}
	t := typeOf(fun)
	if t == nil {
		return
	}
	sig, ok := t.Underlying().(*types.Signature)
	if !ok {
		return
	}
	params := sig.Params()
	n := params.Len()
	for i, a := range call.Args {
		var pt types.Type
		switch {
		case sig.Variadic() && i >= n-1:
			if call.Ellipsis.IsValid() {
				pt = params.At(n - 1).Type()
			} else if s, ok := params.At(n - 1).Type().(*types.Slice); ok {
				pt = s.Elem()
			}
		case i < n:
			pt = params.At(i).Type()
		}
		check(a, pt)
	}
}
