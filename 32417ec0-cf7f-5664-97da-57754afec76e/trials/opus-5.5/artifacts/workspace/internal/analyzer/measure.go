package analyzer

import (
	"sort"

	"declscope/internal/checker"
	"declscope/internal/load"
)

// RuleCount tallies one rule's findings in a package.
type RuleCount struct {
	Asked     bool `json:"asked"`
	Keyable   bool `json:"keyable"`
	Found     int  `json:"found"`
	Ignored   int  `json:"ignored"`
	Baselined int  `json:"baselined"`
	Reported  int  `json:"reported"`
}

// Edge is one declaration reached from one other namespace.
type Edge struct {
	From        string `json:"from"`
	To          string `json:"to"`
	Declaration string `json:"declaration"`
	Kind        string `json:"kind"`
	Uses        int    `json:"uses"`
	State       string `json:"state"`

	decl *decl
}

// Crossing folds the edges between two namespaces, open ones left out.
type Crossing struct {
	From         string `json:"from"`
	To           string `json:"to"`
	Mutual       bool   `json:"mutual"`
	Declared     int    `json:"declared"`
	Baselined    int    `json:"baselined"`
	Reported     int    `json:"reported"`
	Ignored      int    `json:"ignored"`
	Unchecked    int    `json:"unchecked"`
	Reached      int    `json:"reached"`
	Declarations int    `json:"declarations"`
	Uses         int    `json:"uses"`
	Clears       int    `json:"clears"`
}

// NamespaceInfo describes one namespace.
type NamespaceInfo struct {
	Namespace      string   `json:"namespace"`
	Files          []string `json:"files"`
	Core           bool     `json:"core"`
	Declarations   int      `json:"declarations"`
	QualifyTargets int      `json:"qualifyTargets"`

	failing, exempt, baselined, reported int
}

// NameInfo is one finding of the naming rule.
type NameInfo struct {
	Namespace   string `json:"namespace"`
	File        string `json:"file"`
	Declaration string `json:"declaration"`
	Kind        string `json:"kind"`
	Exported    bool   `json:"exported"`
	State       string `json:"state"`
	Fixable     bool   `json:"fixable"`
}

// Measure is everything survey and inspect report about one package.
type Measure struct {
	Path          string
	Pkg           *load.Package
	Rules         *Rules
	Baseline      string // path of the baseline consulted, if any
	Counts        map[string]*RuleCount
	Namespaces    []*NamespaceInfo
	Edges         []*Edge
	Crossings     []*Crossing
	Names         []*NameInfo
	NothingRead   bool
	CoreFiles     int
	AllCore       bool
	QualifyAsked  bool
	BoundaryAsked bool

	res *Result
}

var ruleOrder = []string{"boundary", "qualify", "surplus", "unused", "directive", "filter"}

// MeasurePackage analyzes a package and folds the results.
func MeasurePackage(pkg *load.Package, rules *Rules, base Baseline, basePath string) *Measure {
	pass := &checker.Pass{
		Pkg:       pkg,
		Fset:      pkg.Fset,
		Files:     pkg.Syntax,
		Types:     pkg.Types,
		TypesInfo: pkg.TypesInfo,
	}
	res := Analyze(pass, rules, base)
	m := res.Model
	me := &Measure{
		Path:     pkg.PkgPath,
		Pkg:      pkg,
		Rules:    rules,
		Baseline: basePath,
		Counts:   make(map[string]*RuleCount),
		res:      res,
	}
	me.NothingRead = len(m.files) == 0
	me.BoundaryAsked = rules.Boundary
	me.QualifyAsked = m.qualifyAsked()
	asked := map[string]bool{
		"boundary":  rules.Boundary,
		"qualify":   me.QualifyAsked,
		"surplus":   rules.Surplus != "off" && !me.NothingRead && !m.surplusStandsDown() && !(m.unseenTests && !m.testVariant),
		"unused":    rules.Unused != "off",
		"directive": true,
		"filter":    true,
	}
	for _, r := range ruleOrder {
		me.Counts[r] = &RuleCount{Asked: asked[r], Keyable: r == "boundary" || r == "qualify" || r == "surplus"}
	}
	for _, f := range res.Findings {
		c := me.Counts[f.rule]
		if c == nil {
			continue
		}
		c.Found++
		switch {
		case res.Ignored[f]:
			c.Ignored++
		case res.Baselined[f]:
			c.Baselined++
		default:
			c.Reported++
		}
	}

	// Namespaces.
	byNS := make(map[*namespace]*NamespaceInfo)
	for _, f := range m.files {
		info := byNS[f.ns]
		if info == nil {
			info = &NamespaceInfo{Namespace: f.ns.key(), Core: f.ns.core}
			byNS[f.ns] = info
			me.Namespaces = append(me.Namespaces, info)
		}
		info.Files = append(info.Files, f.base)
		if f.ns.core {
			me.CoreFiles++
		}
	}
	me.AllCore = len(m.files) > 0 && me.CoreFiles == len(m.files)
	sort.Slice(me.Namespaces, func(i, j int) bool { return me.Namespaces[i].Namespace < me.Namespaces[j].Namespace })

	boundaryOf := make(map[*decl]*finding)
	qualifyOf := make(map[*decl]*finding)
	for _, f := range res.Findings {
		if f.decl == nil {
			continue
		}
		switch f.rule {
		case "boundary":
			boundaryOf[f.decl] = f
		case "qualify":
			qualifyOf[f.decl] = f
		}
	}
	state := func(f *finding) string {
		switch {
		case res.Ignored[f]:
			return "ignored"
		case res.Baselined[f]:
			return "baselined"
		}
		return "reported"
	}
	for _, d := range m.decls {
		info := byNS[d.ns]
		info.Declarations++
		if me.QualifyAsked && m.qualifyTarget(d) {
			info.QualifyTargets++
			if f := qualifyOf[d]; f != nil {
				st := state(f)
				switch st {
				case "baselined":
					info.baselined++
					info.failing++
				case "reported":
					info.reported++
					info.failing++
				case "ignored":
					info.exempt++
					st = "exempt"
				}
				me.Names = append(me.Names, &NameInfo{
					Namespace:   d.ns.key(),
					File:        d.file.base,
					Declaration: d.display,
					Kind:        d.kind,
					Exported:    d.exported,
					State:       st,
					Fixable:     f.fix != nil,
				})
			}
		}
	}
	sort.SliceStable(me.Names, func(i, j int) bool {
		a, b := me.Names[i], me.Names[j]
		if a.Namespace != b.Namespace {
			return a.Namespace < b.Namespace
		}
		return a.Declaration < b.Declaration
	})

	// Edges: one per declaration and reaching namespace.
	for _, d := range m.decls {
		uses := make(map[*namespace]int)
		var order []*namespace
		for _, u := range d.crossing() {
			if uses[u.file.ns] == 0 {
				order = append(order, u.file.ns)
			}
			uses[u.file.ns]++
		}
		if len(order) == 0 {
			continue
		}
		st := m.edgeState(d, boundaryOf[d], state)
		for _, ns := range order {
			me.Edges = append(me.Edges, &Edge{
				From:        ns.key(),
				To:          d.ns.key(),
				Declaration: d.display,
				Kind:        d.kind,
				Uses:        uses[ns],
				State:       st,
				decl:        d,
			})
		}
	}
	sort.SliceStable(me.Edges, func(i, j int) bool {
		a, b := me.Edges[i], me.Edges[j]
		if a.From != b.From {
			return a.From < b.From
		}
		if a.To != b.To {
			return a.To < b.To
		}
		return a.Declaration < b.Declaration
	})
	me.fold(byNS)
	return me
}

// edgeState says what became of a declaration reached from elsewhere.
func (m *model) edgeState(d *decl, f *finding, state func(*finding) string) string {
	if f != nil {
		return state(f)
	}
	if d.scope == "shared" {
		switch d.source.kind {
		case srcOwn, srcBlock, srcType, srcFile:
			// Declared, if some config would leave it private without
			// the directive.
			if s, src := m.scopeOf(d, map[*directive]bool{d.source.dir: true}); s == "private" || src.kind == srcDefault {
				return "declared"
			}
		}
		return "open"
	}
	return "unchecked"
}

// fold groups the edges into crossings.
func (me *Measure) fold(byNS map[*namespace]*NamespaceInfo) {
	type pair struct{ from, to string }
	index := make(map[pair]*Crossing)
	declsIn := make(map[string]int)
	for _, info := range byNS {
		declsIn[info.Namespace] = info.Declarations
	}
	// Which namespaces reach each declaration through a finding.
	reachers := make(map[*decl]map[string]bool)
	for _, e := range me.Edges {
		if e.State == "open" {
			continue
		}
		if reachers[e.decl] == nil {
			reachers[e.decl] = make(map[string]bool)
		}
		reachers[e.decl][e.From] = true
		k := pair{e.From, e.To}
		c := index[k]
		if c == nil {
			c = &Crossing{From: e.From, To: e.To, Declarations: declsIn[e.To]}
			index[k] = c
			me.Crossings = append(me.Crossings, c)
		}
		c.Reached++
		c.Uses += e.Uses
		switch e.State {
		case "declared":
			c.Declared++
		case "baselined":
			c.Baselined++
		case "reported":
			c.Reported++
		case "ignored":
			c.Ignored++
		case "unchecked":
			c.Unchecked++
		}
	}
	for _, c := range me.Crossings {
		_, c.Mutual = index[pair{c.To, c.From}]
		pairNS := map[string]bool{c.From: true, c.To: true}
		seen := make(map[*decl]bool)
		for _, e := range me.Edges {
			if e.State != "reported" && e.State != "baselined" || seen[e.decl] {
				continue
			}
			if !pairNS[e.To] {
				continue
			}
			from := reachers[e.decl]
			ok := len(from) > 0
			for ns := range from {
				if !pairNS[ns] {
					ok = false
				}
			}
			if ok {
				seen[e.decl] = true
				c.Clears++
			}
		}
	}
	sort.SliceStable(me.Crossings, func(i, j int) bool {
		a, b := me.Crossings[i], me.Crossings[j]
		if a.Reached != b.Reached {
			return a.Reached > b.Reached
		}
		if a.Uses != b.Uses {
			return a.Uses > b.Uses
		}
		if a.From != b.From {
			return a.From < b.From
		}
		return a.To < b.To
	})
}
