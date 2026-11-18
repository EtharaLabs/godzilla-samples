// Package skill implements "declscope skill": installing, removing and
// listing the agent skills embedded in the binary.
package skill

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"text/tabwriter"
)

const (
	toolName = "declscope"
	// toolVersion is recorded in installed skills; builds without a
	// release version report devel.
	toolVersion = "devel"
)

// Main runs "declscope skill" with the arguments that follow "skill".
func Main(args []string) int {
	c := &cli{stdout: os.Stdout, stderr: os.Stderr}
	return c.run(args)
}

type cli struct {
	stdout, stderr io.Writer
}

func (c *cli) run(args []string) int {
	if len(args) == 0 {
		c.usage(c.stdout, "")
		return 0
	}
	switch cmd := args[0]; cmd {
	case "-h", "--help", "help":
		c.usage(c.stdout, "")
		return 0
	case "install", "uninstall", "list":
		return c.subcommand(cmd, args[1:])
	default:
		c.usage(c.stderr, "")
		return c.fail(fmt.Errorf("unknown skill subcommand %q", cmd))
	}
}

func (c *cli) fail(err error) int {
	fmt.Fprintf(c.stderr, "%s: %v\n", toolName, err)
	return 1
}

var synopses = map[string]string{
	"":          "Manage the agent skills embedded in declscope.",
	"install":   "Install the agent skills embedded in declscope, and remove the ones it no longer carries.",
	"uninstall": "Remove the agent skills embedded in declscope.",
	"list":      "Show the agent skills embedded in declscope, and where each one stands.",
}

// flagsUsage describes the flags parseFlags defines, laid out as
// flag.PrintDefaults would.
const flagsUsage = "Flags:\n" +
	"  -agent value\n" +
	"    \tTarget agent: {github-copilot|claude-code|cursor|codex|gemini|antigravity}, or all, or detected (repeatable) (default \"detected\")\n" +
	"  -dir string\n" +
	"    \tInstall to a custom directory (overrides -agent and -scope)\n" +
	"  -dry-run\n" +
	"    \tReport what would happen without writing\n" +
	"  -f\tOverwrite existing skills (shorthand)\n" +
	"  -force\n" +
	"    \tOverwrite existing skills\n" +
	"  -scope value\n" +
	"    \tInstallation scope: {project|user} (default project)\n"

// usage prints the help of a subcommand, or of "skill" itself for "".
func (c *cli) usage(w io.Writer, cmd string) {
	fmt.Fprintf(w, "%s\n\nUsage:\n", synopses[cmd])
	if cmd == "" {
		fmt.Fprint(w, "  declscope skill install   [flags] [skill...]\n"+
			"  declscope skill uninstall [flags] [skill...]\n"+
			"  declscope skill list      [flags] [skill...]\n")
	} else {
		fmt.Fprintf(w, "  declscope skill %s [flags] [skill...]\n", cmd)
	}
	fmt.Fprintf(w, "\n%s\nEmbedded skills:\n", flagsUsage)
	tw := tabwriter.NewWriter(w, 0, 8, 2, ' ', 0)
	for _, s := range embedded {
		fmt.Fprintf(tw, "  %s\t%s\n", s.name, summary(s.description))
	}
	tw.Flush()
}

// options are the flags and arguments shared by the subcommands.
type options struct {
	agents []string // -agent values, each a comma-separated list
	scope  string
	dir    string
	dryRun bool
	force  bool
	skills []string
}

// agentsFlag collects repeated -agent values. The first one given replaces
// the default.
type agentsFlag struct {
	values []string
	set    bool
}

func (f *agentsFlag) String() string { return strings.Join(f.values, ",") }

func (f *agentsFlag) Set(v string) error {
	if !f.set {
		f.values, f.set = nil, true
	}
	f.values = append(f.values, v)
	return nil
}

type scopeFlag struct{ value string }

func (f *scopeFlag) String() string { return f.value }

func (f *scopeFlag) Set(v string) error {
	if v == "" {
		return errors.New("scope must not be empty")
	}
	f.value = v
	return nil
}

func parseFlags(args []string) (options, error) {
	var o options
	agentList := &agentsFlag{values: []string{"detected"}}
	scope := &scopeFlag{value: scopeProject}
	// Help and errors are printed by the caller; flagsUsage documents these.
	flags := flag.NewFlagSet("skill", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.Usage = func() {}
	flags.Var(agentList, "agent", "")
	flags.StringVar(&o.dir, "dir", "", "")
	flags.BoolVar(&o.dryRun, "dry-run", false, "")
	flags.BoolVar(&o.force, "f", false, "")
	flags.BoolVar(&o.force, "force", false, "")
	flags.Var(scope, "scope", "")
	if err := flags.Parse(args); err != nil {
		return o, err
	}
	o.agents, o.scope, o.skills = agentList.values, scope.value, flags.Args()
	return o, nil
}

func (c *cli) subcommand(cmd string, args []string) int {
	o, err := parseFlags(args)
	if errors.Is(err, flag.ErrHelp) {
		c.usage(c.stdout, cmd)
		return 0
	}
	if err != nil {
		c.usage(c.stderr, cmd)
		return c.fail(err)
	}
	p, err := makePlan(o)
	if err != nil {
		return c.fail(err)
	}
	switch cmd {
	case "install":
		return c.install(p, o)
	case "uninstall":
		return c.uninstall(p, o)
	default:
		return c.list(p)
	}
}

// header names the project root, when the targets were found from it.
func (c *cli) header(p *plan) {
	if p.root != "" {
		fmt.Fprintf(c.stdout, "Project root: %s\n\n", p.root)
	}
}

func (c *cli) list(p *plan) int {
	c.header(p)
	seen := make(map[string]bool)
	for _, s := range p.skills {
		if !seen[s.name] {
			seen[s.name] = true
			fmt.Fprintf(c.stdout, "%s\n  %s\n", s.name, summary(s.description))
		}
	}
	fmt.Fprintln(c.stdout)
	tw := tabwriter.NewWriter(c.stdout, 0, 8, 2, ' ', 0)
	fmt.Fprintln(tw, "SKILL\tSTATE\tPATH")
	for _, it := range p.items {
		fmt.Fprintf(tw, "%s\t%s\t%s\n", it.name, it.state, it.path)
	}
	tw.Flush()
	return 0
}

// result is one line of what install or uninstall did.
type result struct {
	verb, name, path, note string
}

// report prints the results, which stop short of the action that failed.
func (c *cli) report(p *plan, dryRun bool, results []result) {
	if len(results) == 0 {
		return
	}
	c.header(p)
	tw := tabwriter.NewWriter(c.stdout, 0, 8, 2, ' ', 0)
	for _, r := range results {
		verb := r.verb
		if dryRun {
			verb = "would be " + verb
		}
		line := verb + "\t" + r.name + "\t" + r.path
		if r.note != "" {
			line += " (" + r.note + ")"
		}
		fmt.Fprintln(tw, line)
	}
	tw.Flush()
}

const (
	noteEdited  = "edited after installing; use --force"
	noteForeign = "installed by something else; use --force"
)
