package analyzer

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	"declscope/internal/load"
)

const inspectUsage = `Usage: declscope inspect [flags] <package>

Reports the shape of one package: its namespaces, every crossing between them,
what became of each crossing, and where the naming rule stands.

Takes one package. A namespace is implicitly qualified by its package, so
counts from two packages cannot be added up, and averaging them away silently
would answer a question nobody asked.

`

// InspectMain runs "declscope inspect".
func InspectMain(args []string) int {
	sc := newSubcommand("inspect", inspectUsage, false, "path to a declscope YAML config file")
	sc.fs.Parse(args)
	patterns := sc.fs.Args()
	if len(patterns) == 0 {
		sc.fs.Usage()
		return 2
	}
	if sc.format != "markdown" && sc.format != "json" {
		return sc.fail("unknown format %q: this flag takes markdown, json", sc.format)
	}
	pkgs, err := load.Load(&load.Config{Tests: sc.test}, patterns...)
	if err != nil {
		return sc.fail("%v", err)
	}
	var us []*unit
	for _, u := range units(pkgs) {
		if !isXTest(u.pkg) {
			us = append(us, u)
		}
	}
	var failed []string
	for _, u := range us {
		if u.illTyped() {
			failed = append(failed, u.path+": "+u.failure())
		}
	}
	sort.Strings(failed)
	if len(failed) > 0 {
		fmt.Fprintf(os.Stderr, "declscope inspect: these packages do not type-check, so nothing can be measured:\n")
		for _, f := range failed {
			fmt.Fprintf(os.Stderr, "  %s\n", f)
		}
		return 1
	}
	if len(us) == 0 {
		return sc.fail("%s matched no packages", strings.Join(patterns, " "))
	}
	if len(us) > 1 {
		fmt.Fprintf(os.Stderr, "declscope inspect: this pattern matches %d packages, and a namespace of one means nothing in another:\n", len(us))
		for _, u := range us {
			fmt.Fprintf(os.Stderr, "  %s\n", u.path)
		}
		fmt.Fprintf(os.Stderr, "name one of them\n")
		return 1
	}
	u := us[0]
	rules, err := RulesFor(u.pkg, sc.config)
	if err != nil {
		return sc.fail("%v", err)
	}
	var base Baseline
	basePath := BaselinePath(u.pkg, rules)
	if basePath != "" {
		if base, err = LoadBaseline(basePath); err != nil {
			return sc.fail("%v", err)
		}
	}
	me := MeasurePackage(u.pkg, rules, base, basePath)
	if sc.format == "json" {
		writeInspectJSON(os.Stdout, me)
	} else {
		writeInspectMarkdown(os.Stdout, me)
	}
	return 0
}

func writeInspectJSON(w io.Writer, me *Measure) {
	type out struct {
		Package    string                `json:"package"`
		Config     []string              `json:"config"`
		AllCore    bool                  `json:"allCore"`
		Findings   map[string]*RuleCount `json:"findings"`
		Namespaces []*NamespaceInfo      `json:"namespaces"`
		Crossings  []*Crossing           `json:"crossings"`
		Edges      []*Edge               `json:"edges"`
		Names      []*NameInfo           `json:"names"`
	}
	o := out{
		Package:    me.Path,
		Config:     append([]string{}, me.Rules.Chain...),
		AllCore:    me.AllCore,
		Findings:   me.Counts,
		Namespaces: append([]*NamespaceInfo{}, me.Namespaces...),
		Crossings:  append([]*Crossing{}, me.Crossings...),
		Edges:      append([]*Edge{}, me.Edges...),
		Names:      append([]*NameInfo{}, me.Names...),
	}
	data, _ := json.MarshalIndent(o, "", "  ")
	fmt.Fprintf(w, "%s\n", data)
}

func writeInspectMarkdown(w io.Writer, me *Measure) {
	fmt.Fprintf(w, "# %s\n\n", me.Path)
	if len(me.Rules.Chain) > 0 {
		fmt.Fprintf(w, "Config: %s\n\n", chainText(me.Rules.Chain))
	}
	if me.NothingRead {
		fmt.Fprintf(w, "> No file of this package was read — every one is generated, or the filter removed them — so nothing here was checked.\n\n")
	}
	if me.AllCore {
		fmt.Fprintf(w, "> Every file is in the core namespace, so nothing crosses and no name is asked to carry one.\n\n")
	}

	fmt.Fprintf(w, "## Namespaces\n\n")
	var rows [][]string
	for _, n := range me.Namespaces {
		var files []string
		for _, f := range n.Files {
			files = append(files, "`"+f+"`")
		}
		rows = append(rows, []string{n.Namespace, strings.Join(files, ", "), fmt.Sprint(n.Declarations), num(me.QualifyAsked && !n.Core, n.QualifyTargets)})
	}
	writeTable(w, []column{{"namespace", false}, {"files", false}, {"declarations", true}, {"qualify targets", true}}, rows)
	fmt.Fprintln(w)

	fmt.Fprintf(w, "## Crossings\n\n")
	open := make(map[string]bool)
	for _, e := range me.Edges {
		if e.State == "open" {
			open[e.To+"\x00"+e.Declaration] = true
		}
	}
	if len(me.Crossings) == 0 && len(open) > 0 {
		fmt.Fprintf(w, "Open crossings only: %s shared by default rather than by decision, so there is nothing to put in the table or diagram.\n\n",
			plural(len(open), "declaration is", "declarations are"))
	} else if len(me.Crossings) == 0 {
		fmt.Fprintf(w, "Nothing crosses a namespace in this package.\n\n")
	} else {
		writeMermaid(w, me.Crossings)
		fmt.Fprintf(w, "<details>\n<summary>Table: %s</summary>\n\n", plural(len(me.Crossings), "crossing", "crossings"))
		b := me.BoundaryAsked
		rows = nil
		for _, c := range me.Crossings {
			mutual := ""
			if c.Mutual {
				mutual = "yes"
			}
			rows = append(rows, []string{
				c.From + " → " + c.To, mutual,
				num(b, c.Declared), num(b, c.Baselined), num(b, c.Reported), num(b, c.Clears),
				fmt.Sprintf("%d of %d", c.Reached, c.Declarations), fmt.Sprint(c.Uses),
			})
		}
		writeTable(w, []column{{"crossing", false}, {"mutual", false}, {"declared", true}, {"baselined", true}, {"reported", true}, {"clears", true}, {"reached", true}, {"uses", true}}, rows)
		fmt.Fprintf(w, "\n</details>\n\n")
	}
	if n := len(open); n > 0 && len(me.Crossings) > 0 {
		if n == 1 {
			fmt.Fprintf(w, "1 declaration is further: open, shared by default rather than by decision, so left out of the table and of the diagram.\n\n")
		} else {
			fmt.Fprintf(w, "%d declarations are further: open, shared by default rather than by decision, so left out of the table and of the diagram.\n\n", n)
		}
	}
	if len(me.Crossings) > 0 && me.BoundaryAsked {
		states := make(map[string]map[string]bool)
		for _, e := range me.Edges {
			if states[e.State] == nil {
				states[e.State] = make(map[string]bool)
			}
			states[e.State][e.To+"\x00"+e.Declaration] = true
		}
		fmt.Fprintf(w, "Declarations crossed: %d reported, %d baselined, %d declared. The columns above count within a pair, so they sum to more: a declaration reached from two namespaces is two rows and one finding.\n\n",
			len(states["reported"]), len(states["baselined"]), len(states["declared"]))
	}
	if len(me.Crossings) > 0 {
		writeMostReached(w, me)
	}

	fmt.Fprintf(w, "## Qualify\n\n")
	if !me.QualifyAsked {
		fmt.Fprintf(w, "Not asked: `rules.naming.qualify` does not apply to this package.\n\n")
		return
	}
	rows = nil
	for _, n := range me.Namespaces {
		if n.Core || n.QualifyTargets == 0 {
			rows = append(rows, []string{n.Namespace, "-", "-", "-", "-"})
			continue
		}
		rows = append(rows, []string{n.Namespace, fmt.Sprint(n.exempt), fmt.Sprint(n.baselined), fmt.Sprint(n.reported), fmt.Sprintf("%d of %d", n.failing, n.QualifyTargets)})
	}
	writeTable(w, []column{{"namespace", false}, {"exempt", true}, {"baselined", true}, {"reported", true}, {"saturation", true}}, rows)
	fmt.Fprintln(w)
}

// writeMermaid draws the crossings as a graph.
func writeMermaid(w io.Writer, cs []*Crossing) {
	fmt.Fprintf(w, "```mermaid\ngraph LR\n")
	ids := make(map[string]int)
	var nodes []string
	node := func(name string) {
		if _, ok := ids[name]; !ok {
			ids[name] = len(nodes)
			nodes = append(nodes, name)
		}
	}
	for _, c := range cs {
		node(c.From)
		node(c.To)
	}
	for i, n := range nodes {
		fmt.Fprintf(w, "  n%d[%q]\n", i, n)
	}
	for _, c := range cs {
		arrow := "-.->"
		switch {
		case c.Reported > 0:
			arrow = "==>"
		case c.Baselined > 0:
			arrow = "-->"
		}
		fmt.Fprintf(w, "  n%d %s|%d| n%d\n", ids[c.From], arrow, c.Reached, ids[c.To])
	}
	fmt.Fprintf(w, "```\n\n")
}

// writeMostReached ranks the declarations reached from other namespaces.
func writeMostReached(w io.Writer, me *Measure) {
	type row struct {
		decl, ns, state string
		from, uses      int
	}
	byDecl := make(map[string]*row)
	var rows []*row
	coreDecls := make(map[string]bool)
	for _, e := range me.Edges {
		if e.State == "open" {
			continue
		}
		key := e.To + "\x00" + e.Declaration
		if e.To == "(core)" {
			coreDecls[key] = true
			continue
		}
		r := byDecl[key]
		if r == nil {
			r = &row{decl: e.Declaration, ns: e.To, state: e.State}
			byDecl[key] = r
			rows = append(rows, r)
		}
		r.from++
		r.uses += e.Uses
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if a.from != b.from {
			return a.from > b.from
		}
		if a.uses != b.uses {
			return a.uses > b.uses
		}
		if a.ns != b.ns {
			return a.ns < b.ns
		}
		return a.decl < b.decl
	})
	fmt.Fprintf(w, "## Most-reached declarations except `(core)`\n\n")
	if len(rows) > 10 {
		rows = rows[:10]
	}
	var cells [][]string
	for _, r := range rows {
		cells = append(cells, []string{"`" + r.decl + "`", r.ns, plural(r.from, "namespace", "namespaces"), r.state})
	}
	if len(cells) > 0 {
		writeTable(w, []column{{"declaration", false}, {"namespace", false}, {"reached from", false}, {"state", false}}, cells)
		fmt.Fprintln(w)
	}
	if n := len(coreDecls); n > 0 {
		if n == 1 {
			fmt.Fprintf(w, "1 declaration is further: the core's, which is the shared model and reached from everywhere by design.\n\n")
		} else {
			fmt.Fprintf(w, "%d declarations are further: the core's, which is the shared model and reached from everywhere by design.\n\n", n)
		}
	}
}
