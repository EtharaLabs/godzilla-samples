package analyzer

import (
	"fmt"
	"go/ast"
	"go/token"
	"go/types"
	"regexp"
	"slices"
	"sort"
	"strings"

	"declscope/internal/checker"
)

// finding is a report before ignores and the baseline are consulted.
type finding struct {
	rule    string
	pos     token.Pos
	message string
	related []checker.RelatedInformation
	fix     *checker.SuggestedFix
	decl    *decl      // the declaration reported on, if any
	dir     *directive // the directive reported on, if any
	// coveredBy is the report on a member's type whose fix narrows the
	// member too: while that report shows, this one does not.
	coveredBy *finding
	// unusedOf marks an unused report about dir.
	unusedOf bool
	// names is the directive a boundary report says the scope comes from.
	names *directive
}

// standsDown reports whether the surplus rule must stay quiet because a use
// may hide where declscope cannot see it.
func (m *model) surplusStandsDown() bool {
	return m.hasGen || m.hasAsm || m.hasCgo || m.unseenOwn
}

// srcPhrase describes where a private scope came from, for boundary.
func (m *model) privatePhrase(d *decl) string {
	switch d.source.kind {
	case srcOwn, srcBlock:
		return "is declared private by //declscope:private"
	case srcType:
		return "is declared private by //declscope:private on " + d.source.typ.name
	case srcFile:
		return "is declared private by the file's //declscope:private"
	}
	return "is private to " + d.ns.describe()
}

// reached returns the declarations that take their scope from dir.
func (m *model) reached(dir *directive) []*decl {
	if m.reachCache == nil {
		m.reachCache = make(map[*directive][]*decl)
		for _, d := range m.decls {
			if d.source.dir != nil {
				m.reachCache[d.source.dir] = append(m.reachCache[d.source.dir], d)
			}
		}
	}
	return m.reachCache[dir]
}

// widened reports whether d would be private if no directive reached it.
func (m *model) widened(d *decl) bool {
	return !d.exported && m.rules.Unexported == "private"
}

// boundaryFinding reports d if it is private and used from another namespace.
func (m *model) boundaryFinding(d *decl, fixes bool) *finding {
	if !m.rules.Boundary || d.scope != "private" {
		return nil
	}
	cross := d.crossing()
	if len(cross) == 0 {
		return nil
	}
	f := &finding{
		rule:    "boundary",
		pos:     d.ident.Pos(),
		message: fmt.Sprintf("%s %s %s, but is used from %s", d.kind, d.display, m.privatePhrase(d), cross[0].file.ns.describe()),
		decl:    d,
		names:   d.source.dir,
	}
	for _, u := range cross {
		f.related = append(f.related, checker.RelatedInformation{
			Pos:     u.pos,
			End:     u.end,
			Message: "used here, in " + u.file.ns.describe(),
		})
	}
	if fixes && d.source.kind == srcDefault {
		if d.member && d.typeDecl != nil && m.typeGetsFix(d.typeDecl) {
			return f
		}
		f.fix = m.shareFix(d)
	}
	return f
}

// typeGetsFix reports whether the boundary report of a type carries a fix.
func (m *model) typeGetsFix(t *decl) bool {
	return m.rules.Boundary && t.scope == "private" && t.source.kind == srcDefault && len(t.crossing()) > 0
}

// shareFix inserts //declscope:shared on d, and, for a type, narrows the
// members the new directive would widen for nothing.
func (m *model) shareFix(d *decl) *checker.SuggestedFix {
	fix := &checker.SuggestedFix{Message: "add //declscope:shared to " + d.display}
	fix.TextEdits = append(fix.TextEdits, m.insertDirective(d.target, "//declscope:shared"))
	if d.kind != "type" || m.rules.Surplus != "strict" || m.surplusStandsDown() {
		return fix
	}
	var names []string
	for _, ft := range d.target.children {
		if ft.kind != tField || len(ft.anchors) == 0 || m.ownScope(ft) != nil || m.ignoresRule(ft, "surplus") {
			continue
		}
		narrow := true
		for _, a := range ft.anchors {
			if a.exported || a.source.kind != srcDefault || m.surplusUsed(a) {
				narrow = false
				break
			}
		}
		if !narrow {
			continue
		}
		names = append(names, ft.anchors[0].display)
		fix.TextEdits = append(fix.TextEdits, m.insertDirective(ft, "//declscope:private"))
	}
	if len(names) > 0 {
		fix.Message += ", and //declscope:private to " + strings.Join(names, ", ")
	}
	return fix
}

// ignoresRule reports whether an ignore on a target, around it, or on its
// file silences a rule there.
func (m *model) ignoresRule(t *target, rule string) bool {
	for _, a := range ancestors(t) {
		for _, ig := range a.ignores {
			if ig.covers(rule) {
				return true
			}
		}
	}
	for _, ig := range t.file.ignores {
		if ig.covers(rule) {
			return true
		}
	}
	return false
}

// insertDirective writes a directive on its own line above a target.
func (m *model) insertDirective(t *target, text string) checker.TextEdit {
	pos := t.node.Pos()
	tf := m.fset.File(pos)
	src := m.source(tf.Name())
	off := tf.Offset(pos)
	lineStart := off
	for lineStart > 0 && src[lineStart-1] != '\n' {
		lineStart--
	}
	indent := src[lineStart:off]
	if strings.Trim(indent, " \t") != "" {
		return checker.TextEdit{Pos: pos, End: pos, NewText: []byte("\n" + text + "\n")}
	}
	if text == "//declscope:private" && endsInProse(docOf(t)) {
		// Keep the directive apart from the prose of the doc comment.
		text = "//\n" + indent + text
	}
	return checker.TextEdit{Pos: pos, End: pos, NewText: []byte(text + "\n" + indent)}
}

// docOf returns the doc comment of a target's node.
func docOf(t *target) *ast.CommentGroup {
	switch n := t.node.(type) {
	case *ast.FuncDecl:
		return n.Doc
	case *ast.GenDecl:
		return n.Doc
	case *ast.ValueSpec:
		return n.Doc
	case *ast.TypeSpec:
		return n.Doc
	case *ast.Field:
		return n.Doc
	}
	return nil
}

// endsInProse reports whether the last line of a comment is text rather
// than a directive or an empty comment line.
func endsInProse(g *ast.CommentGroup) bool {
	if g == nil || len(g.List) == 0 {
		return false
	}
	text := g.List[len(g.List)-1].Text
	if !strings.HasPrefix(text, "//") {
		return true
	}
	body := text[2:]
	if strings.TrimSpace(body) == "" {
		return false
	}
	return !isDirectiveText(body)
}

// isDirectiveText reports whether a line comment, without its slashes,
// is a directive such as "go:noinline" or "declscope:shared".
func isDirectiveText(c string) bool {
	if strings.HasPrefix(c, "line ") || strings.HasPrefix(c, "extern ") || strings.HasPrefix(c, "export ") {
		return true
	}
	colon := strings.Index(c, ":")
	if colon <= 0 || colon+1 >= len(c) {
		return false
	}
	for i := 0; i <= colon+1; i++ {
		if i == colon {
			continue
		}
		b := c[i]
		if !('a' <= b && b <= 'z' || '0' <= b && b <= '9') {
			return false
		}
	}
	return true
}

// source returns the content of a file.
func (m *model) source(name string) string {
	if s, ok := sourceCache.get(name); ok {
		return s
	}
	return ""
}

// qualifyAsked reports whether the naming rule applies to the package.
func (m *model) qualifyAsked() bool {
	switch m.rules.Qualify {
	case "always":
		return true
	case "ondemand":
		return m.countNamespaces() >= 2
	}
	return false
}

// countNamespaces counts the namespaces of non-test files that declare
// something.
func (m *model) countNamespaces() int {
	seen := make(map[*namespace]bool)
	for _, f := range m.files {
		if f.isTest || !f.hasDecls {
			continue
		}
		seen[f.ns] = true
	}
	return len(seen)
}

// qualifyTarget reports whether the naming rule examines d.
func (m *model) qualifyTarget(d *decl) bool {
	if d.member || d.ns.core {
		return false
	}
	// A method is named for its type's unit, unless filed away from it. A
	// type the analysis does not read gives it no unit to be away from.
	if d.kind == "method" && (d.typeDecl == nil || d.typeDecl.ns == d.ns) {
		return false
	}
	if d.kind == "func" && d.name == "main" && m.pkgName == "main" {
		return false
	}
	if d.kind == "func" && d.file.isTest {
		for _, p := range []string{"Test", "Benchmark", "Fuzz", "Example"} {
			if strings.HasPrefix(d.name, p) {
				return false
			}
		}
	}
	if !prefixable(d.ns.name) {
		return false
	}
	if d.exported && !m.rules.Exported {
		return false
	}
	return true
}

// carriesNamespace reports whether a name carries its namespace.
func (m *model) carriesNamespace(name, ns string) bool {
	for _, w := range forms(ns) {
		if carries(name, w) {
			return true
		}
	}
	for _, v := range m.rules.Vocabulary[ns] {
		for _, w := range forms(v) {
			if carries(name, w) {
				return true
			}
		}
	}
	return false
}

func (m *model) newName(d *decl) string {
	if d.exported {
		return upperWord(d.ns.name) + upperWord(d.name)
	}
	return d.ns.name + upperWord(d.name)
}

func (m *model) qualifyFinding(d *decl, asked, fixes bool) *finding {
	if !asked || !m.qualifyTarget(d) || m.carriesNamespace(d.name, d.ns.name) {
		return nil
	}
	ns := d.ns.name
	newName := m.newName(d)
	msg := fmt.Sprintf("%s %s does not carry namespace %q anywhere in its name; rename it to %s, or to another name that carries %q", d.kind, d.name, ns, newName, ns)
	if looksInflected(ns) {
		msg += fmt.Sprintf("; if the name spells %q in another form, list that form under rules.naming.vocabulary.%s", ns, ns)
	}
	f := &finding{rule: "qualify", pos: d.ident.Pos(), message: msg, decl: d}
	if fixes && !d.exported {
		if edits := m.rename(d, newName); edits != nil {
			f.fix = &checker.SuggestedFix{
				Message:   fmt.Sprintf("rename %s to %s (prefix it with its namespace)", d.name, newName),
				TextEdits: edits,
			}
		}
	}
	return f
}

// surplusFindings evaluates d against the shared directive it takes its
// scope from. reported tracks directives already reported as a whole.
func (m *model) surplusFinding(d *decl, reported map[*directive]bool, byDecl map[*decl]*finding) *finding {
	if m.rules.Surplus == "off" || m.surplusStandsDown() || m.unseenTests && !m.testVariant {
		return nil
	}
	dir := d.source.dir
	if dir == nil || dir.name != "shared" {
		return nil
	}
	reach := m.reached(dir)
	inUse := false
	for _, r := range reach {
		if r.exported || m.surplusUsed(r) {
			inUse = true
		}
	}
	if !inUse {
		if reported[dir] {
			return nil
		}
		reported[dir] = true
		var msg string
		if dir.fileLevel {
			msg = "the file's //declscope:shared: no use from another namespace is visible to declscope"
		} else {
			var names []string
			for _, r := range reach {
				names = append(names, r.display)
			}
			msg = fmt.Sprintf("//declscope:shared on %s: no use from another namespace is visible to declscope", strings.Join(names, ", "))
		}
		f := &finding{rule: "surplus", pos: dir.pos(), message: msg, dir: dir}
		if len(reach) > 0 {
			f.decl = reach[0]
		}
		return f
	}
	if m.rules.Surplus != "strict" || !m.surplusNarrowable(d, dir) {
		return nil
	}
	var covered *finding
	if d.member && d.typeDecl != nil && d.typeDecl.source.dir == dir && m.surplusNarrowable(d.typeDecl, dir) {
		// The type is reported, and narrowing it narrows its members.
		covered = byDecl[d.typeDecl]
	}
	var from string
	switch d.source.kind {
	case srcType:
		from = "//declscope:shared on " + d.source.typ.name
	case srcBlock:
		from = "the //declscope:shared on its block"
	case srcFile:
		from = "the file's //declscope:shared"
	}
	f := &finding{
		rule:      "surplus",
		pos:       d.ident.Pos(),
		message:   fmt.Sprintf("%s %s takes shared scope from %s, but no use from another namespace is visible to declscope", d.kind, d.display, from),
		decl:      d,
		coveredBy: covered,
	}
	// A directive that changes a scope must still change one once what it
	// widens for nothing is narrowed, or it would be left with nothing to do.
	needed, stays := false, false
	without := map[*directive]bool{dir: true}
	for _, r := range reach {
		if s, _ := m.scopeOf(r, without); s != "shared" {
			needed = true
			if !m.surplusNarrowable(r, dir) {
				stays = true
			}
		}
	}
	if (!needed || stays) && !m.narrowingChangesUnused(d, dir) {
		f.fix = &checker.SuggestedFix{
			Message:   "add //declscope:private to " + d.display,
			TextEdits: []checker.TextEdit{m.insertDirective(d.target, "//declscope:private")},
		}
	}
	return f
}

// narrowingChangesUnused reports whether giving d a //declscope:private of
// its own would change what the unused rule says of dir, which it takes its
// scope from.
func (m *model) narrowingChangesUnused(d *decl, dir *directive) bool {
	if m.rules.Unused == "off" {
		return false
	}
	all := m.scopeDirectives()
	before := m.unusedOf(dir, nil, all)
	m.narrowed = d
	defer func() { m.narrowed = nil }()
	return m.unusedOf(dir, nil, all) != before
}

// surplusNarrowable reports whether a declaration that takes its scope from
// dir could be narrowed by itself: dir is not its own, dir widens it, and
// neither it nor a member that inherits from it is used elsewhere.
func (m *model) surplusNarrowable(d *decl, dir *directive) bool {
	if d.target == dir.target || !m.widened(d) || m.surplusUsed(d) {
		return false
	}
	if d.kind == "type" {
		for _, ft := range d.target.children {
			if ft.kind != tField || m.ownScope(ft) != nil {
				continue
			}
			for _, a := range ft.anchors {
				if a.exported || m.surplusUsed(a) {
					return false
				}
			}
		}
	}
	return true
}

// exportedMethods lists the methods in the method set of an exported type
// of the package, its own or promoted through embedding.
func (m *model) exportedMethods() map[*types.Func]bool {
	if m.exportedMeths != nil {
		return m.exportedMeths
	}
	m.exportedMeths = make(map[*types.Func]bool)
	scope := m.pass.Types.Scope()
	for _, name := range scope.Names() {
		tn, ok := scope.Lookup(name).(*types.TypeName)
		if !ok || !tn.Exported() {
			continue
		}
		t := tn.Type()
		if !types.IsInterface(t) {
			t = types.NewPointer(t)
		}
		ms := types.NewMethodSet(t)
		for i := 0; i < ms.Len(); i++ {
			if fn, ok := ms.At(i).Obj().(*types.Func); ok {
				m.exportedMeths[fn.Origin()] = true
			}
		}
	}
	return m.exportedMeths
}

// surplusUsed reports whether surplus counts d as needed: used from another
// namespace, or, for an interface method, possibly called through another
// interface that declares the same method.
func (m *model) surplusUsed(d *decl) bool {
	if len(d.crossing()) > 0 {
		return true
	}
	if d.kind != "method" {
		return false
	}
	if d.typeDecl != nil && d.typeDecl.exported {
		// A method of an exported type may serve an interface declscope
		// cannot see.
		return true
	}
	if fn, ok := d.obj.(*types.Func); ok && m.exportedMethods()[fn] {
		// So may one an exported type gets by embedding.
		return true
	}
	fn, ok := d.obj.(*types.Func)
	if !ok {
		return false
	}
	// A method may be called through another interface of the package that
	// declares it too and that a type holding it satisfies, wherever that
	// is.
	holders := m.methodHolders()[fn.Origin()]
	for _, it := range m.ifaceTypes() {
		declared := false
		for i := 0; i < it.NumExplicitMethods(); i++ {
			if it.ExplicitMethod(i) == fn {
				declared = true
			}
		}
		if declared {
			continue
		}
		match := false
		for i := 0; i < it.NumMethods(); i++ {
			if other := it.Method(i); other != fn && other.Name() == fn.Name() && types.Identical(other.Type(), fn.Type()) {
				match = true
				break
			}
		}
		if !match {
			continue
		}
		for _, h := range holders {
			if types.Implements(h, it) {
				return true
			}
		}
	}
	return false
}

// methodHolders maps every method to the types of the package whose method
// sets hold it, its own or by embedding: a pointer for a concrete type.
func (m *model) methodHolders() map[*types.Func][]types.Type {
	if m.holders != nil {
		return m.holders
	}
	m.holders = make(map[*types.Func][]types.Type)
	scope := m.pass.Types.Scope()
	for _, name := range scope.Names() {
		tn, ok := scope.Lookup(name).(*types.TypeName)
		if !ok || tn.IsAlias() {
			continue
		}
		t := tn.Type()
		if !types.IsInterface(t) {
			t = types.NewPointer(t)
		}
		ms := types.NewMethodSet(t)
		for i := 0; i < ms.Len(); i++ {
			if fn, ok := ms.At(i).Obj().(*types.Func); ok {
				m.holders[fn.Origin()] = append(m.holders[fn.Origin()], t)
			}
		}
	}
	return m.holders
}

// ifaceTypes lists the interface types the analyzed files spell.
func (m *model) ifaceTypes() []*types.Interface {
	if m.ifaceTys != nil {
		return m.ifaceTys
	}
	m.ifaceTys = []*types.Interface{}
	for _, f := range m.files {
		ast.Inspect(f.ast, func(n ast.Node) bool {
			if it, ok := n.(*ast.InterfaceType); ok {
				if t, ok := m.pass.TypesInfo.Types[it].Type.(*types.Interface); ok {
					m.ifaceTys = append(m.ifaceTys, t)
				}
			}
			return true
		})
	}
	return m.ifaceTys
}

// ifaceMethods lists the methods every interface type of the package
// declares itself.
func (m *model) ifaceMethods() []*types.Func {
	if m.ifaceFuncs != nil {
		return m.ifaceFuncs
	}
	m.ifaceFuncs = []*types.Func{}
	for _, f := range m.files {
		ast.Inspect(f.ast, func(n ast.Node) bool {
			it, ok := n.(*ast.InterfaceType)
			if !ok || it.Methods == nil {
				return true
			}
			for _, field := range it.Methods.List {
				for _, id := range field.Names {
					if fn, ok := m.pass.TypesInfo.Defs[id].(*types.Func); ok {
						m.ifaceFuncs = append(m.ifaceFuncs, fn)
					}
				}
			}
			return true
		})
	}
	return m.ifaceFuncs
}

// declFindings computes the per-declaration findings in report order.
func (m *model) declFindings(fixes bool) []*finding {
	m.claims = nil
	var out []*finding
	asked := m.qualifyAsked()
	reported := make(map[*directive]bool)
	surplusOf := make(map[*decl]*finding)
	for _, d := range m.decls {
		if f := m.boundaryFinding(d, fixes); f != nil {
			out = append(out, f)
		}
		if f := m.qualifyFinding(d, asked, fixes); f != nil {
			out = append(out, f)
		}
		if f := m.surplusFinding(d, reported, surplusOf); f != nil {
			out = append(out, f)
			surplusOf[d] = f
		}
	}
	return out
}

// scopeDirectives lists every effective scope directive.
func (m *model) scopeDirectives() []*directive {
	if m.scopeDirs != nil {
		return m.scopeDirs
	}
	out := []*directive{}
	for _, f := range m.files {
		for _, d := range f.directives {
			if d.effective && d.isScope() {
				out = append(out, d)
			}
		}
	}
	m.scopeDirs = out
	return out
}

// domain lists the declarations a directive is written over, whether or
// not they take their scope from it.
func (m *model) domain(dir *directive) []*decl {
	if out, ok := m.domains[dir]; ok {
		return out
	}
	var out []*decl
	for _, d := range m.decls {
		if dir.fileLevel {
			if d.file == dir.file {
				out = append(out, d)
			}
			continue
		}
		for t := d.target; t != nil; t = t.parent {
			if t == dir.target {
				out = append(out, d)
				break
			}
		}
	}
	if m.domains == nil {
		m.domains = make(map[*directive][]*decl)
	}
	m.domains[dir] = out
	return out
}

// nearer lists the scope directives written inside what dir is written
// over: they take precedence over it where both reach.
func (m *model) nearer(dir *directive, all []*directive) []*directive {
	var out []*directive
	for _, y := range all {
		if y == dir || y.file != dir.file || y.fileLevel {
			continue
		}
		if dir.fileLevel {
			out = append(out, y)
			continue
		}
		for t := y.target.parent; t != nil; t = t.parent {
			if t == dir.target {
				out = append(out, y)
				break
			}
		}
	}
	return out
}

func withDeleted(skip map[*directive]bool, dir *directive) map[*directive]bool {
	out := map[*directive]bool{dir: true}
	for k := range skip {
		out[k] = true
	}
	return out
}

// unusedReport is what the unused rule says of a scope directive.
type unusedReport struct {
	message string // empty when the directive is in use
	strict  bool   // the strict reason, which -fix acts on
}

// unusedOf judges a scope directive with the directives in skip deleted.
func (m *model) unusedOf(dir *directive, skip map[*directive]bool, all []*directive) unusedReport {
	key := m.unusedKey(dir, skip)
	if r, ok := m.unusedMemo[key]; ok {
		return r
	}
	r := m.judgeUnused(dir, skip, all)
	if m.unusedMemo == nil {
		m.unusedMemo = make(map[string]unusedReport)
	}
	m.unusedMemo[key] = r
	return r
}

// unusedKey identifies a judgement of dir: the directives deleted, and the
// state of the model it is made in.
func (m *model) unusedKey(dir *directive, skip map[*directive]bool) string {
	var ids []string
	for k, v := range skip {
		if v {
			ids = append(ids, fmt.Sprintf("%p", k))
		}
	}
	for k, v := range m.deleted {
		if v {
			ids = append(ids, fmt.Sprintf("d%p", k))
		}
	}
	sort.Strings(ids)
	return fmt.Sprintf("%p|%p|%s", dir, m.narrowed, strings.Join(ids, ","))
}

func (m *model) judgeUnused(dir *directive, skip map[*directive]bool, all []*directive) unusedReport {
	strict := m.rules.Unused == "strict"
	prefix := "unused //declscope:" + dir.name
	if dir.fileLevel {
		prefix = "unused file-level //declscope:" + dir.name
	}
	domain := m.domain(dir)
	if len(domain) == 0 {
		if dir.fileLevel {
			return unusedReport{message: prefix}
		}
		return unusedReport{message: prefix + ": no checked declaration carries it"}
	}
	var reach []*decl
	for _, d := range domain {
		if _, src := m.scopeOf(d, skip); src.dir == dir {
			reach = append(reach, d)
		}
	}
	without := withDeleted(skip, dir)
	configFree := true
	for _, d := range reach {
		s, src := m.scopeOf(d, without)
		if s != dir.name {
			return unusedReport{}
		}
		if src.kind == srcDefault {
			configFree = false
		}
	}
	var looseMsg string
	switch {
	case dir.fileLevel:
		looseMsg = prefix
	case len(reach) == 0:
		looseMsg = prefix + ": every declaration it reaches states its own scope"
	default:
		looseMsg = fmt.Sprintf("%s on %s: nothing it reaches takes a scope", prefix, strings.Join(m.dirNames(dir, reach), ", "))
	}
	if !strict || m.keeps(dir, skip, all) {
		// Deleting it would change what a nearer directive is reported
		// as; only a directive no configuration could need is reported.
		if configFree {
			return unusedReport{message: looseMsg}
		}
		return unusedReport{}
	}
	if len(reach) > 0 && !dir.fileLevel {
		names := m.dirNames(dir, reach)
		each := "it already has"
		if len(names) > 1 {
			each = "each already has"
		}
		return unusedReport{message: fmt.Sprintf("%s on %s: %s %s scope", prefix, strings.Join(names, ", "), each, dir.name), strict: true}
	}
	nearer, already := false, false
	for _, d := range domain {
		if s, src := m.scopeOf(d, skip); src.dir != dir && s != dir.name {
			nearer = true
		} else {
			already = true
		}
	}
	own := "takes a nearer directive's scope"
	if !dir.fileLevel {
		own = "states its own scope"
	}
	var msg string
	switch {
	case nearer && already:
		msg = fmt.Sprintf("%s: every declaration it reaches %s or already has %s scope", prefix, own, dir.name)
	case nearer:
		msg = fmt.Sprintf("%s: every declaration it reaches %s", prefix, own)
	default:
		msg = fmt.Sprintf("%s: every declaration it reaches already has %s scope", prefix, dir.name)
	}
	return unusedReport{message: msg, strict: true}
}

// keeps reports whether deleting dir would change what the unused rule
// says of a nearer directive.
func (m *model) keeps(dir *directive, skip map[*directive]bool, all []*directive) bool {
	without := withDeleted(skip, dir)
	for _, y := range m.nearer(dir, all) {
		if skip[y] {
			continue
		}
		if m.unusedOf(y, skip, all) != m.unusedOf(y, without, all) || m.effect(y, skip) != m.effect(y, without) {
			return true
		}
	}
	return false
}

// effect lists, as a key, the declarations whose scope a directive changes,
// with the directives in skip deleted.
func (m *model) effect(dir *directive, skip map[*directive]bool) string {
	without := withDeleted(skip, dir)
	var b strings.Builder
	for _, d := range m.domain(dir) {
		if _, src := m.scopeOf(d, skip); src.dir != dir {
			continue
		}
		if s, _ := m.scopeOf(d, without); s != dir.name {
			fmt.Fprintf(&b, "%p,", d)
		}
	}
	return b.String()
}

// unusedScopeFindings reports scope directives that change nothing.
func (m *model) unusedScopeFindings(fixes bool, base []*finding) []*finding {
	if m.rules.Unused == "off" {
		return nil
	}
	var out []*finding
	all := m.scopeDirectives()
	reports := make(map[*directive]unusedReport)
	for _, dir := range all {
		if r := m.unusedOf(dir, nil, all); r.message != "" {
			reports[dir] = r
		}
	}
	// Outer directives are judged first: a declaration that falls back to
	// one whose report keeps it keeps its own directive too.
	depth := func(dir *directive) int {
		n := 0
		if !dir.fileLevel {
			for t := dir.target; t != nil; t = t.parent {
				n++
			}
		}
		return n
	}
	order := append([]*directive(nil), all...)
	sort.SliceStable(order, func(i, j int) bool { return depth(order[i]) < depth(order[j]) })
	fixable := make(map[*directive]bool)
	for _, dir := range order {
		r, ok := reports[dir]
		if !ok {
			continue
		}
		fixable[dir] = r.strict && fixes && !(m.unseenTests && !m.testVariant) && !m.fallsBackToKept(dir, reports, fixable) && !m.reliesOnShared(dir) && !m.guardsMember(dir, base) && !m.reachesSurplusIgnore(dir) && !m.changesFindings(dir, base) && !m.changesUnused(dir, all, fixable)
	}
	for _, dir := range all {
		r, ok := reports[dir]
		if !ok {
			continue
		}
		f := &finding{rule: "unused", pos: dir.pos(), message: r.message, dir: dir, unusedOf: true}
		if fixable[dir] {
			f.fix = &checker.SuggestedFix{
				Message:   "remove //declscope:" + dir.name,
				TextEdits: []checker.TextEdit{m.deleteDirective(dir)},
			}
		}
		out = append(out, f)
	}
	return out
}

// fallsBackToKept reports whether, without dir, a declaration it reaches
// would take its scope from a directive reported unused with no fix: that
// one stays, and so must this one.
func (m *model) fallsBackToKept(dir *directive, reports map[*directive]unusedReport, fixable map[*directive]bool) bool {
	without := map[*directive]bool{dir: true}
	for _, d := range m.domain(dir) {
		if _, src := m.scopeOf(d, nil); src.dir != dir {
			continue
		}
		if _, src := m.scopeOf(d, without); src.dir != nil {
			if _, reported := reports[src.dir]; reported && !fixable[src.dir] {
				return true
			}
		}
	}
	return false
}

// reachesSurplusIgnore reports whether a //declscope:shared reaches a
// declaration that ignores surplus, which deleting it would not respect.
func (m *model) reachesSurplusIgnore(dir *directive) bool {
	if dir.name != "shared" || m.rules.Surplus == "off" {
		return false
	}
	for _, d := range m.domain(dir) {
		if d.source.dir == dir && m.ignoresRule(d.target, "surplus") {
			return true
		}
	}
	return false
}

// guardsMember reports whether dir is written on a member whose type is
// private by default and has a boundary report: its fix, sharing the type,
// would widen the member without dir.
func (m *model) guardsMember(dir *directive, base []*finding) bool {
	if dir.target == nil || dir.target.kind != tField {
		return false
	}
	for _, d := range m.domain(dir) {
		t := d.typeDecl
		if t == nil || t.source.kind != srcDefault {
			continue
		}
		for _, f := range base {
			if f.rule == "boundary" && f.decl == t && len(m.covering(f)) == 0 {
				return true
			}
		}
	}
	return false
}

// reliesOnShared reports whether, without dir, a declaration it reaches
// would take its scope from a //declscope:shared, whose surplus judgement
// would then cover it.
func (m *model) reliesOnShared(dir *directive) bool {
	if m.rules.Surplus == "off" {
		return false
	}
	without := map[*directive]bool{dir: true}
	for _, d := range m.domain(dir) {
		if _, src := m.scopeOf(d, nil); src.dir != dir {
			continue
		}
		if _, src := m.scopeOf(d, without); src.dir != nil && src.dir.name == "shared" {
			return true
		}
	}
	return false
}

// changesUnused reports whether deleting dir would change what the unused
// rule says of another directive.
func (m *model) changesUnused(dir *directive, all []*directive, fixable map[*directive]bool) bool {
	mine := make(map[*decl]bool)
	for _, d := range m.domain(dir) {
		mine[d] = true
	}
	without := map[*directive]bool{dir: true}
	for _, y := range all {
		if y == dir {
			continue
		}
		overlaps := false
		for _, d := range m.domain(y) {
			if mine[d] {
				overlaps = true
				break
			}
		}
		if !overlaps {
			continue
		}
		after := m.unusedOf(y, without, all)
		if m.unusedOf(y, nil, all).kind() != after.kind() {
			return true
		}
		// An outer directive, judged already, must keep its fix.
		if fixable[y] && slices.Contains(m.nearer(y, all), dir) {
			if !after.strict || after.message == "" || m.findingsDiffer(m.declFindingsWith(without, y.file), m.declFindingsWith(withDeleted(without, y), y.file), y) {
				return true
			}
		}
	}
	return false
}

var namesInReport = regexp.MustCompile(` on [^:]*: (it|each) already has`)

// kind is the report with the names it lists left out: a declaration that
// joins them does not change what is said of the directive.
func (r unusedReport) kind() unusedReport {
	r.message = namesInReport.ReplaceAllString(r.message, " on _: _ already has")
	return r
}

// dirNames lists what a directive is written on, for messages.
func (m *model) dirNames(dir *directive, reach []*decl) []string {
	var names []string
	for _, d := range reach {
		if dir.target != nil && dir.target.kind != tField && d.member {
			continue
		}
		names = append(names, d.display)
	}
	return names
}

// changesFindings reports whether deleting dir would change any finding
// other than the unused ones.
func (m *model) changesFindings(dir *directive, base []*finding) bool {
	return m.findingsDiffer(m.inFile(base, dir.file), m.declFindingsWith(map[*directive]bool{dir: true}, dir.file), dir)
}

// inFile keeps the boundary and surplus findings about a file, the ones a
// directive of the file can change.
func (m *model) inFile(fs []*finding, file *fileInfo) []*finding {
	var out []*finding
	for _, f := range fs {
		if f.rule != "boundary" && f.rule != "surplus" {
			continue
		}
		if f.decl != nil && f.decl.file == file || f.decl == nil && f.dir != nil && f.dir.file == file {
			out = append(out, f)
		}
	}
	return out
}

// declFindingsWith computes the boundary and surplus findings of a file with
// the directives in skip deleted. A directive reaches only its own file, so
// no other file's findings can change.
func (m *model) declFindingsWith(skip map[*directive]bool, file *fileInfo) []*finding {
	key := m.unusedKey(nil, skip) + fmt.Sprintf("|%p", file)
	if fs, ok := m.findingsMemo[key]; ok {
		return fs
	}
	old := m.deleted
	m.resolveScopes(skip)
	defer m.resolveScopes(old)
	var out []*finding
	reported := make(map[*directive]bool)
	surplusOf := make(map[*decl]*finding)
	for _, d := range m.decls {
		if d.file != file {
			continue
		}
		if f := m.boundaryFinding(d, true); f != nil {
			out = append(out, f)
		}
		if f := m.surplusFinding(d, reported, surplusOf); f != nil {
			out = append(out, f)
			surplusOf[d] = f
		}
	}
	if m.findingsMemo == nil {
		m.findingsMemo = make(map[string][]*finding)
	}
	m.findingsMemo[key] = out
	return out
}

// findingsDiffer compares two sets of declaration findings, leaving out
// those about dir.
func (m *model) findingsDiffer(before, after []*finding, dir *directive) bool {
	others := func(fs []*finding) []*finding {
		var out []*finding
		for _, f := range fs {
			if f.dir != dir {
				out = append(out, f)
			}
		}
		return out
	}
	after, before = others(after), others(before)
	if len(after) != len(before) {
		return true
	}
	// The fix of a silenced finding is never offered.
	fixOf := func(f *finding) string {
		if f.fix == nil || len(m.covering(f)) > 0 {
			return ""
		}
		return f.fix.Message
	}
	for i := range after {
		a, b := after[i], before[i]
		if a.rule != b.rule || a.pos != b.pos || a.message != b.message || a.names != b.names || fixOf(a) != fixOf(b) {
			return true
		}
	}
	return false
}

// deleteDirective removes the line of a directive.
func (m *model) deleteDirective(dir *directive) checker.TextEdit {
	c := dir.comment
	tf := m.fset.File(c.Pos())
	src := m.source(tf.Name())
	start := tf.Offset(c.Pos())
	end := tf.Offset(c.End())
	// newline returns the offset past the line ending at i, or i.
	newline := func(i int) int {
		switch {
		case i < len(src) && src[i] == '\n':
			return i + 1
		case i+1 < len(src) && src[i] == '\r' && src[i+1] == '\n':
			return i + 2
		}
		return i
	}
	// blankBefore reports whether the line ending just before i is empty.
	blankBefore := func(i int) bool {
		if i < 2 {
			return true
		}
		if src[i-2] == '\n' {
			return true
		}
		return i >= 3 && src[i-2] == '\r' && src[i-3] == '\n'
	}
	lineStart := start
	for lineStart > 0 && src[lineStart-1] != '\n' && (src[lineStart-1] == ' ' || src[lineStart-1] == '\t') {
		lineStart--
	}
	if lineStart == 0 || src[lineStart-1] == '\n' {
		// The directive is alone on its line: delete the whole line.
		end = newline(end)
		// A bare "//" separating it from what is above goes with it, when
		// it ends its comment group.
		if prev := m.separatorAbove(dir); prev != nil {
			ps := tf.Offset(prev.Pos())
			ls := ps
			for ls > 0 && (src[ls-1] == ' ' || src[ls-1] == '\t') {
				ls--
			}
			pe := tf.Offset(prev.End())
			if (ls == 0 || src[ls-1] == '\n') && newline(pe) == lineStart && newline(pe) != pe {
				lineStart = ls
			}
		}
		if dir.fileLevel && newline(end) != end && (lineStart == 0 || src[lineStart-1] == '\n') {
			// Above the package clause a deleted group leaves no blank line.
			if lineStart == 0 || blankBefore(lineStart) {
				end = newline(end)
			}
		}
		return checker.TextEdit{Pos: tf.Pos(lineStart), End: tf.Pos(end), NewText: nil}
	}
	// A trailing directive: delete it with the space before it.
	return checker.TextEdit{Pos: tf.Pos(lineStart), End: tf.Pos(end), NewText: nil}
}

// separatorAbove returns the bare "//" line directly above a directive that
// ends its comment group, if there is one.
func (m *model) separatorAbove(dir *directive) *ast.Comment {
	for _, g := range dir.file.ast.Comments {
		n := len(g.List)
		if n < 2 || g.List[n-1] != dir.comment {
			continue
		}
		if prev := g.List[n-2]; prev.Text == "//" {
			return prev
		}
		return nil
	}
	return nil
}

// sortByPos orders findings by file name, then offset.
func (m *model) sortByPos(fs []*finding) {
	sort.SliceStable(fs, func(i, j int) bool {
		pi, pj := m.fset.Position(fs[i].pos), m.fset.Position(fs[j].pos)
		if pi.Filename != pj.Filename {
			return pi.Filename < pj.Filename
		}
		return pi.Offset < pj.Offset
	})
}
