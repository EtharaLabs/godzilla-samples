// Package checker is the command-line driver for the analyzer. It loads
// packages, runs the analyzer on each, and prints the diagnostics or applies
// their fixes, with the conventions of the go/analysis single checker.
package checker

import (
	"bytes"
	"cmp"
	"crypto/sha256"
	"encoding/json"
	"flag"
	"fmt"
	"go/ast"
	"go/token"
	"go/types"
	"io"
	"log"
	"os"
	"runtime"
	"runtime/pprof"
	"runtime/trace"
	"slices"
	"sort"
	"strings"
	"time"

	"declscope/internal/load"
)

// TextEdit replaces the text between Pos and End with NewText.
type TextEdit struct {
	Pos, End token.Pos
	NewText  []byte
}

// SuggestedFix is a set of edits applied as a whole.
type SuggestedFix struct {
	Message   string
	TextEdits []TextEdit
}

// RelatedInformation is a secondary position of a diagnostic.
type RelatedInformation struct {
	Pos, End token.Pos
	Message  string
}

// Diagnostic is one report of the analyzer.
type Diagnostic struct {
	Pos, End       token.Pos
	Category       string
	Message        string
	SuggestedFixes []SuggestedFix
	Related        []RelatedInformation
}

// Pass is the input of one analyzer run on one package.
type Pass struct {
	Pkg       *load.Package
	Fset      *token.FileSet
	Files     []*ast.File
	Types     *types.Package
	TypesInfo *types.Info
	Report    func(Diagnostic)
}

// Analyzer describes the analysis the driver runs.
type Analyzer struct {
	Name  string
	Doc   string
	Flags *flag.FlagSet
	Run   func(*Pass) error
}

type action struct {
	pkg         *load.Package
	diagnostics []Diagnostic
	err         error
	duration    time.Duration
	inspect     time.Duration // the prerequisite AST inspection
}

// Options holds the driver's flag values.
type Options struct {
	IncludeTests bool
	Fix          bool
	Diff         bool
	JSON         bool
	Context      int
	Debug        string
	CPUProfile   string
	MemProfile   string
	Trace        string
}

func (opts *Options) dbg(b byte) bool { return strings.IndexByte(opts.Debug, b) >= 0 }

// Main parses the command line and runs the analyzer, then exits.
func Main(a *Analyzer) {
	log.SetFlags(0)
	log.SetPrefix(a.Name + ": ")

	var opts Options
	fs := flag.CommandLine
	fs.StringVar(&opts.Debug, "debug", "", `debug flags, any subset of "fpstv"`)
	fs.StringVar(&opts.CPUProfile, "cpuprofile", "", "write CPU profile to this file")
	fs.StringVar(&opts.MemProfile, "memprofile", "", "write memory profile to this file")
	fs.StringVar(&opts.Trace, "trace", "", "write trace log to this file")
	fs.BoolVar(&opts.IncludeTests, "test", true, "indicates whether test files should be analyzed, too")
	fs.BoolVar(&opts.Fix, "fix", false, "apply all suggested fixes")
	fs.BoolVar(&opts.Diff, "diff", false, "with -fix, don't update the files, but print a unified diff")

	fs.Usage = func() {
		paras := strings.Split(a.Doc, "\n\n")
		fmt.Fprintf(os.Stderr, "%s: %s\n\n", a.Name, paras[0])
		fmt.Fprintf(os.Stderr, "Usage: %s [-flag] [package]\n\n", a.Name)
		if len(paras) > 1 {
			fmt.Fprintln(os.Stderr, strings.Join(paras[1:], "\n\n"))
		}
		fmt.Fprintln(os.Stderr, "\nFlags:")
		fs.PrintDefaults()
	}

	if a.Flags != nil {
		a.Flags.VisitAll(func(f *flag.Flag) {
			if fs.Lookup(f.Name) != nil {
				log.Printf("%s flag -%s would conflict with driver; skipping", a.Name, f.Name)
				return
			}
			fs.Var(f.Value, f.Name, f.Usage)
		})
	}
	printflags := fs.Bool("flags", false, "print analyzer flags in JSON")
	fs.Var(versionFlag{}, "V", "print version and exit")
	fs.BoolVar(&opts.JSON, "json", false, "emit JSON output")
	fs.IntVar(&opts.Context, "c", -1, "display offending line with this many lines of context")
	_ = fs.Bool("source", false, "no effect (deprecated)")
	verbose := fs.Bool("v", false, "no effect (deprecated)")
	_ = fs.Bool("all", false, "no effect (deprecated)")
	_ = fs.String("tags", "", "no effect (deprecated)")

	flag.Parse()
	// -v is an undocumented alias for -debug=v.
	if *verbose && !strings.Contains(opts.Debug, "v") {
		opts.Debug += "v"
	}

	if *printflags {
		printFlags()
		os.Exit(0)
	}

	args := flag.Args()
	if len(args) == 0 {
		fs.Usage()
		os.Exit(1)
	}
	os.Exit(Run(args, a, &opts))
}

func printFlags() {
	type jsonFlag struct {
		Name  string
		Bool  bool
		Usage string
	}
	var flags []jsonFlag
	flag.VisitAll(func(f *flag.Flag) {
		switch f.Name {
		case "debug", "cpuprofile", "memprofile", "trace", "fix":
			return
		}
		b, ok := f.Value.(interface{ IsBoolFlag() bool })
		isBool := ok && b.IsBoolFlag()
		flags = append(flags, jsonFlag{f.Name, isBool, f.Usage})
	})
	data, err := json.MarshalIndent(flags, "", "\t")
	if err != nil {
		log.Fatal(err)
	}
	os.Stdout.Write(data)
}

type versionFlag struct{}

func (versionFlag) IsBoolFlag() bool { return true }
func (versionFlag) Get() any         { return nil }
func (versionFlag) String() string   { return "" }
func (versionFlag) Set(s string) error {
	if s != "full" {
		return fmt.Errorf("unsupported flag value: -V=%s (use -V=full)", s)
	}
	progname, err := os.Executable()
	if err != nil {
		return err
	}
	f, err := os.Open(progname)
	if err != nil {
		log.Fatal(err)
	}
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		log.Fatal(err)
	}
	f.Close()
	fmt.Printf("%s version devel comments-go-here buildID=%02x\n", progname, string(h.Sum(nil)))
	os.Exit(0)
	return nil
}

// Run loads the packages named by args, analyzes them, and reports.
// It returns the exit code.
func Run(args []string, a *Analyzer, opts *Options) (exitcode int) {
	exitAtLeast := func(code int) { exitcode = max(code, exitcode) }

	if opts.CPUProfile != "" {
		f, err := os.Create(opts.CPUProfile)
		if err != nil {
			log.Fatal(err)
		}
		if err := pprof.StartCPUProfile(f); err != nil {
			log.Fatal(err)
		}
		defer pprof.StopCPUProfile()
	}
	if opts.Trace != "" {
		f, err := os.Create(opts.Trace)
		if err != nil {
			log.Fatal(err)
		}
		if err := trace.Start(f); err != nil {
			log.Fatal(err)
		}
		defer func() {
			trace.Stop()
			log.Printf("To view the trace, run:\n$ go tool trace view %s", opts.Trace)
		}()
	}
	if opts.MemProfile != "" {
		f, err := os.Create(opts.MemProfile)
		if err != nil {
			log.Fatal(err)
		}
		defer func() {
			runtime.GC()
			if err := pprof.WriteHeapProfile(f); err != nil {
				log.Fatalf("Writing memory profile: %v", err)
			}
			f.Close()
		}()
	}

	if opts.dbg('v') {
		log.SetPrefix("")
		log.SetFlags(log.Lmicroseconds)
		log.Printf("load %s", args)
	}
	initial, err := load.Load(&load.Config{Tests: opts.IncludeTests}, args...)
	if err == nil && len(initial) == 0 {
		err = fmt.Errorf("%s matched no packages", strings.Join(args, " "))
	}
	if err != nil {
		log.Print(err)
		return 1
	}
	if n := load.PrintErrors(os.Stderr, initial); n > 0 {
		exitAtLeast(1)
	}

	if opts.dbg('v') {
		log.Printf("building graph of analysis passes")
	}
	actions := make([]*action, len(initial))
	for i, pkg := range initial {
		act := &action{pkg: pkg}
		actions[i] = act
		start := time.Now()
		for _, f := range pkg.Syntax {
			ast.Inspect(f, func(ast.Node) bool { return true })
		}
		act.inspect = time.Since(start)
		start = time.Now()
		if pkg.IllTyped {
			act.err = fmt.Errorf("analysis skipped due to errors in package")
			act.duration = time.Since(start)
			continue
		}
		pass := &Pass{
			Pkg:       pkg,
			Fset:      pkg.Fset,
			Files:     pkg.Syntax,
			Types:     pkg.Types,
			TypesInfo: pkg.TypesInfo,
		}
		pass.Report = func(d Diagnostic) {
			for i := range d.SuggestedFixes {
				sortEdits(d.SuggestedFixes[i].TextEdits)
			}
			act.diagnostics = append(act.diagnostics, d)
		}
		act.err = a.Run(pass)
		act.duration = time.Since(start)
	}

	if opts.Fix {
		if err := applyFixes(actions, opts.Diff); err != nil {
			log.Print(err)
			exitAtLeast(1)
		}
		return
	}

	if opts.dbg('t') {
		defer printTiming(a.Name, actions, opts)
	}
	if opts.JSON {
		if err := printJSON(os.Stdout, a.Name, actions); err != nil {
			exitAtLeast(1)
		}
		return
	}
	printText(os.Stderr, a.Name, actions, opts.Context)
	var numErrors, rootDiags int
	for _, act := range actions {
		if act.err != nil {
			numErrors++
		} else {
			rootDiags += len(act.diagnostics)
		}
	}
	if numErrors > 0 {
		exitAtLeast(1)
	} else if rootDiags > 0 {
		exitAtLeast(3)
	}
	return
}

// printTiming prints the slowest actions, accounting for 90% of the total.
func printTiming(name string, actions []*action, opts *Options) {
	if !opts.dbg('p') {
		log.Println("Warning: times are mostly GC/scheduler noise; use -debug=tp to disable parallelism")
	}
	type timing struct {
		d    time.Duration
		name string
	}
	var list []timing
	var total time.Duration
	for _, act := range actions {
		list = append(list,
			timing{act.inspect, "inspect@" + act.pkg.ID},
			timing{act.duration, name + "@" + act.pkg.ID})
		total += act.inspect + act.duration
	}
	sort.Slice(list, func(i, j int) bool { return list[i].d > list[j].d })
	var sum time.Duration
	for _, t := range list {
		fmt.Fprintf(os.Stderr, "%s\t%s\n", t.d, t.name)
		sum += t.d
		if sum >= total*9/10 {
			break
		}
	}
	if total > sum {
		fmt.Fprintf(os.Stderr, "%s\tall others\n", total-sum)
	}
}

func sortEdits(edits []TextEdit) {
	slices.SortStableFunc(edits, func(x, y TextEdit) int {
		if sign := cmp.Compare(x.Pos, y.Pos); sign != 0 {
			return sign
		}
		return cmp.Compare(x.End, y.End)
	})
}

func printText(w io.Writer, name string, actions []*action, contextLines int) {
	type key struct {
		pos, end token.Position
		message  string
	}
	seen := make(map[key]bool)
	buf := new(bytes.Buffer)
	for _, act := range actions {
		if act.err != nil {
			fmt.Fprintf(w, "%s: %v\n", name, act.err)
			continue
		}
		fset := act.pkg.Fset
		for _, diag := range act.diagnostics {
			k := key{fset.Position(diag.Pos), fset.Position(diag.End), diag.Message}
			if seen[k] {
				continue
			}
			seen[k] = true
			printPlain(buf, fset, contextLines, diag)
		}
	}
	w.Write(buf.Bytes())
}

func printPlain(out io.Writer, fset *token.FileSet, contextLines int, diag Diagnostic) {
	print := func(pos, end token.Pos, message string) {
		posn := fset.Position(pos)
		fmt.Fprintf(out, "%s: %s\n", posn, message)
		if contextLines >= 0 {
			end := fset.Position(end)
			if !end.IsValid() {
				end = posn
			}
			data, _ := os.ReadFile(posn.Filename)
			lines := strings.Split(string(data), "\n")
			for i := posn.Line - contextLines; i <= end.Line+contextLines; i++ {
				if 1 <= i && i <= len(lines) {
					fmt.Fprintf(out, "%d\t%s\n", i, lines[i-1])
				}
			}
		}
	}
	print(diag.Pos, diag.End, diag.Message)
	for _, rel := range diag.Related {
		print(rel.Pos, rel.End, "\t"+rel.Message)
	}
}

type jsonTextEdit struct {
	Filename string `json:"filename"`
	Start    int    `json:"start"`
	End      int    `json:"end"`
	New      string `json:"new"`
}

type jsonSuggestedFix struct {
	Message string         `json:"message"`
	Edits   []jsonTextEdit `json:"edits"`
}

type jsonRelated struct {
	Posn    string `json:"posn"`
	End     string `json:"end"`
	Message string `json:"message"`
}

type jsonDiagnostic struct {
	Category       string             `json:"category,omitempty"`
	Posn           string             `json:"posn"`
	End            string             `json:"end"`
	Message        string             `json:"message"`
	SuggestedFixes []jsonSuggestedFix `json:"suggested_fixes,omitempty"`
	Related        []jsonRelated      `json:"related,omitempty"`
}

func printJSON(w io.Writer, name string, actions []*action) error {
	tree := make(map[string]map[string]any)
	for _, act := range actions {
		var v any
		fset := act.pkg.Fset
		if act.err != nil {
			type jsonError struct {
				Err string `json:"error"`
			}
			v = jsonError{act.err.Error()}
		} else if len(act.diagnostics) > 0 {
			diags := make([]jsonDiagnostic, 0, len(act.diagnostics))
			for _, d := range act.diagnostics {
				var fixes []jsonSuggestedFix
				for _, fix := range d.SuggestedFixes {
					var edits []jsonTextEdit
					for _, edit := range fix.TextEdits {
						file := fset.File(edit.Pos)
						end := edit.End
						if !end.IsValid() {
							end = edit.Pos
						}
						edits = append(edits, jsonTextEdit{
							Filename: file.Name(),
							Start:    file.Offset(edit.Pos),
							End:      file.Offset(end),
							New:      string(edit.NewText),
						})
					}
					fixes = append(fixes, jsonSuggestedFix{Message: fix.Message, Edits: edits})
				}
				var related []jsonRelated
				for _, r := range d.Related {
					related = append(related, jsonRelated{
						Posn:    fset.Position(r.Pos).String(),
						End:     fset.Position(r.End).String(),
						Message: r.Message,
					})
				}
				diags = append(diags, jsonDiagnostic{
					Category:       d.Category,
					Posn:           fset.Position(d.Pos).String(),
					End:            fset.Position(d.End).String(),
					Message:        d.Message,
					SuggestedFixes: fixes,
					Related:        related,
				})
			}
			v = diags
		}
		if v != nil {
			m, ok := tree[act.pkg.ID]
			if !ok {
				m = make(map[string]any)
				tree[act.pkg.ID] = m
			}
			m[name] = v
		}
	}
	data, err := json.MarshalIndent(tree, "", "\t")
	if err != nil {
		log.Panicf("internal error: JSON marshaling failed: %v", err)
	}
	_, err = fmt.Fprintf(w, "%s\n", data)
	return err
}
