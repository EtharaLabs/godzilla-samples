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

const surveyUsage = `Usage: declscope survey [flags] [packages]

Reports what was checked and what it found, one row per package, so that the
package to open first is the one at the top.

It decides nothing and gates nothing: the exit status is zero whatever the
counts say. Use declscope itself for that, and a baseline to adopt it.

`

type surveyConfig struct {
	Chain    []string        `json:"chain"`
	Packages int             `json:"packages"`
	Rules    surveyRulesJSON `json:"rules"`
}

type surveyRulesJSON struct {
	Boundary bool   `json:"boundary"`
	Qualify  string `json:"qualify"`
	Exported bool   `json:"exported"`
	Surplus  string `json:"surplus"`
	Unused   string `json:"unused"`
}

type surveyBaseline struct {
	Path    string `json:"path"`
	Entries int    `json:"entries"`
}

type surveyWorst struct {
	Namespace string `json:"namespace"`
	Failing   int    `json:"failing"`
	Targets   int    `json:"targets"`
}

type surveyLargest struct {
	From    string `json:"from"`
	To      string `json:"to"`
	Reached int    `json:"reached"`
	Uses    int    `json:"uses"`
}

type surveyPackage struct {
	Package    string `json:"package"`
	Namespaces int    `json:"namespaces"`
	CoreFiles  int    `json:"coreFiles"`
	AllCore    bool   `json:"allCore"`
	Boundary   struct {
		Asked     bool `json:"asked"`
		Reported  int  `json:"reported"`
		Baselined int  `json:"baselined"`
		Declared  int  `json:"declared"`
	} `json:"boundary"`
	Qualify struct {
		Asked     bool         `json:"asked"`
		Reported  int          `json:"reported"`
		Baselined int          `json:"baselined"`
		Exempt    int          `json:"exempt"`
		Worst     *surveyWorst `json:"worst,omitempty"`
	} `json:"qualify"`
	Largest *surveyLargest `json:"largest,omitempty"`

	nothingRead bool
}

// SurveyMain runs "declscope survey".
func SurveyMain(args []string) int {
	sc := newSubcommand("survey", surveyUsage, true, "path to a declscope YAML config file")
	sc.fs.Parse(args)
	patterns := sc.fs.Args()
	if len(patterns) == 0 {
		patterns = []string{"./..."}
	}
	if sc.format != "markdown" && sc.format != "json" {
		return sc.fail("unknown format %q: this flag takes markdown, json", sc.format)
	}
	pkgs, err := load.Load(&load.Config{Tests: sc.test}, patterns...)
	if err != nil {
		return sc.fail("%v", err)
	}
	us := units(pkgs)
	var failed []string
	var ok []*unit
	for _, u := range us {
		if u.illTyped() {
			failed = append(failed, u.path+": "+u.failure())
		} else {
			ok = append(ok, u)
		}
	}
	sort.Strings(failed)
	if len(failed) > 0 && !sc.allowErrors {
		fmt.Fprintf(os.Stderr, "declscope survey: these packages do not type-check, so their counts would be zero for a reason that is not the code:\n")
		for _, f := range failed {
			fmt.Fprintf(os.Stderr, "  %s\n", f)
		}
		fmt.Fprintf(os.Stderr, "pass -allow-errors to measure the rest anyway\n")
		return 1
	}
	if len(us) == 0 {
		return sc.fail("%s matched no packages", strings.Join(patterns, " "))
	}

	var configs []*surveyConfig
	configIndex := make(map[string]*surveyConfig)
	var baselines []*surveyBaseline
	baselineIndex := make(map[string]bool)
	totals := make(map[string]*RuleCount)
	for _, r := range ruleOrder {
		totals[r] = &RuleCount{Keyable: r == "boundary" || r == "qualify" || r == "surplus"}
	}
	var rows []*surveyPackage
	for _, u := range ok {
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
			if _, statErr := os.Stat(basePath); statErr == nil && !baselineIndex[basePath] {
				baselineIndex[basePath] = true
				baselines = append(baselines, &surveyBaseline{Path: basePath, Entries: base.Count()})
			}
		}
		key := strings.Join(rules.Chain, "\x00")
		c := configIndex[key]
		if c == nil {
			c = &surveyConfig{Chain: append([]string{}, rules.Chain...), Rules: surveyRulesJSON{
				Boundary: rules.Boundary, Qualify: rules.Qualify, Exported: rules.Exported, Surplus: rules.Surplus, Unused: rules.Unused,
			}}
			configIndex[key] = c
			configs = append(configs, c)
		}
		c.Packages++

		me := MeasurePackage(u.pkg, rules, base, basePath)
		for _, r := range ruleOrder {
			t, c := totals[r], me.Counts[r]
			if c.Asked {
				t.Asked = true
			}
			t.Found += c.Found
			t.Ignored += c.Ignored
			t.Baselined += c.Baselined
			t.Reported += c.Reported
		}
		rows = append(rows, surveyRow(me))
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a := rows[i].outstanding()
		b := rows[j].outstanding()
		if a != b {
			return a > b
		}
		return rows[i].Package < rows[j].Package
	})
	if sc.format == "json" {
		type checks struct {
			TypeCheck struct {
				Packages int      `json:"packages"`
				Failed   []string `json:"failed"`
			} `json:"typeCheck"`
			Configs   []*surveyConfig   `json:"configs"`
			Baselines []*surveyBaseline `json:"baselines"`
		}
		var o struct {
			Checks   checks                `json:"checks"`
			Totals   map[string]*RuleCount `json:"totals"`
			Packages []*surveyPackage      `json:"packages"`
		}
		o.Checks.TypeCheck.Packages = len(us)
		o.Checks.TypeCheck.Failed = append([]string{}, failed...)
		o.Checks.Configs = append([]*surveyConfig{}, configs...)
		o.Checks.Baselines = append([]*surveyBaseline{}, baselines...)
		o.Totals = totals
		o.Packages = append([]*surveyPackage{}, rows...)
		data, _ := json.MarshalIndent(o, "", "  ")
		fmt.Fprintf(os.Stdout, "%s\n", data)
		return 0
	}
	writeSurveyMarkdown(os.Stdout, configs, baselines, len(us)-len(failed), failed, totals, rows)
	return 0
}

func surveyRow(me *Measure) *surveyPackage {
	p := &surveyPackage{
		Package:     me.Path,
		Namespaces:  len(me.Namespaces),
		CoreFiles:   me.CoreFiles,
		AllCore:     me.AllCore,
		nothingRead: me.NothingRead,
	}
	b := me.Counts["boundary"]
	p.Boundary.Asked = b.Asked
	p.Boundary.Reported = b.Reported
	p.Boundary.Baselined = b.Baselined
	declared := make(map[string]bool)
	for _, e := range me.Edges {
		if e.State == "declared" {
			declared[e.To+"\x00"+e.Declaration] = true
		}
	}
	p.Boundary.Declared = len(declared)
	q := me.Counts["qualify"]
	p.Qualify.Asked = q.Asked
	p.Qualify.Reported = q.Reported
	p.Qualify.Baselined = q.Baselined
	for _, n := range me.Namespaces {
		p.Qualify.Exempt += n.exempt
		if n.failing == 0 {
			continue
		}
		w := p.Qualify.Worst
		if w == nil || n.failing > w.Failing ||
			n.failing == w.Failing && n.failing*w.Targets > w.Failing*n.QualifyTargets {
			p.Qualify.Worst = &surveyWorst{Namespace: n.Namespace, Failing: n.failing, Targets: n.QualifyTargets}
		}
	}
	if len(me.Crossings) > 0 {
		c := me.Crossings[0]
		p.Largest = &surveyLargest{From: c.From, To: c.To, Reached: c.Reached, Uses: c.Uses}
	}
	return p
}

func writeSurveyMarkdown(w io.Writer, configs []*surveyConfig, baselines []*surveyBaseline, okCount int, failed []string, totals map[string]*RuleCount, rows []*surveyPackage) {
	fmt.Fprintf(w, "## Checks in force\n\n")
	var cells [][]string
	for _, c := range configs {
		r := &Rules{Boundary: c.Rules.Boundary, Qualify: c.Rules.Qualify, Exported: c.Rules.Exported, Surplus: c.Rules.Surplus, Unused: c.Rules.Unused}
		cells = append(cells, []string{"config", chainText(c.Chain), fmt.Sprint(c.Packages)})
		cells = append(cells, []string{"rules", rulesText(r), fmt.Sprint(c.Packages)})
	}
	for _, b := range baselines {
		cells = append(cells, []string{"baseline", fmt.Sprintf("`%s`, %s", b.Path, plural(b.Entries, "entry", "entries")), ""})
	}
	cells = append(cells, []string{"type check", fmt.Sprintf("%s ok, %d failed", plural(okCount, "package", "packages"), len(failed)), ""})
	writeTable(w, []column{{"check", false}, {"value", false}, {"packages", true}}, cells)
	fmt.Fprintln(w)
	if len(failed) > 0 {
		fmt.Fprintf(w, "Did not type-check, so given no row:\n\n")
		for _, f := range failed {
			fmt.Fprintf(w, "- `%s`\n", f)
		}
		fmt.Fprintln(w)
	}

	fmt.Fprintf(w, "## Findings\n\n")
	cells = nil
	for _, r := range ruleOrder {
		t := totals[r]
		cells = append(cells, []string{"`" + r + "`", num(t.Asked, t.Found), num(t.Asked, t.Ignored), num(t.Asked && t.Keyable, t.Baselined), num(t.Asked, t.Reported)})
	}
	writeTable(w, []column{{"rule", false}, {"found", true}, {"ignored", true}, {"baselined", true}, {"reported", true}}, cells)
	fmt.Fprintln(w)

	fmt.Fprintf(w, "## Packages — boundary\n\n")
	cells = nil
	for _, p := range rows {
		largest := "-"
		if p.Largest != nil {
			largest = fmt.Sprintf("%s → %s (%s)", p.Largest.From, p.Largest.To, plural(p.Largest.Reached, "declaration", "declarations"))
		}
		a := p.Boundary.Asked
		cells = append(cells, []string{packageCell(p), num(a, p.Boundary.Reported), num(a, p.Boundary.Baselined), num(a, p.Boundary.Declared), largest})
	}
	writeTable(w, []column{{"package", false}, {"reported", true}, {"baselined", true}, {"declared", true}, {"largest crossing", false}}, cells)
	fmt.Fprintln(w)

	fmt.Fprintf(w, "## Packages — qualify\n\n")
	cells = nil
	for _, p := range rows {
		worst := "-"
		if p.Qualify.Worst != nil {
			worst = fmt.Sprintf("%s %d of %d", p.Qualify.Worst.Namespace, p.Qualify.Worst.Failing, p.Qualify.Worst.Targets)
		}
		a := p.Qualify.Asked
		cells = append(cells, []string{"`" + p.Package + "`", num(a, p.Qualify.Reported), num(a, p.Qualify.Baselined), num(a, p.Qualify.Exempt), worst})
	}
	writeTable(w, []column{{"package", false}, {"reported", true}, {"baselined", true}, {"exempt", true}, {"worst namespace", false}}, cells)
	fmt.Fprintln(w)
}

// outstanding counts what is undecided in a package: its reported and
// baselined findings.
func (p *surveyPackage) outstanding() int {
	return p.Boundary.Reported + p.Boundary.Baselined + p.Qualify.Reported + p.Qualify.Baselined
}

func packageCell(p *surveyPackage) string {
	s := "`" + p.Package + "`"
	if p.nothingRead {
		s += " [nothing read]"
	}
	if p.AllCore {
		s += " [all core]"
	}
	return s
}
