package skill

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// plan is what a subcommand works on: the skills directories it targets and
// the state of every skill in them, taken before anything is changed.
type plan struct {
	root   string // project root; "" when the targets were not found from one
	dirs   []string
	skills []*embeddedSkill // as named on the command line, repeats included
	items  []item
}

// item is one skill directory in a target.
type item struct {
	name  string
	dir   string // the skills directory holding it
	path  string
	state state
	skill *embeddedSkill // nil for an orphan
}

// makePlan checks the options and inspects the targets. The order of the
// steps decides which error is reported first: scope, project root, agent
// names, target directories, reading them, then skill names.
func makePlan(o options) (*plan, error) {
	if o.scope != scopeProject && o.scope != scopeUser {
		return nil, fmt.Errorf("skillembed: unknown scope %q (want project or user)", o.scope)
	}
	p := new(plan)
	if o.dir == "" && o.scope == scopeProject {
		root, err := findProjectRoot()
		if err != nil {
			return nil, err
		}
		p.root = root
	}
	names, err := parseAgents(o.agents)
	if err != nil {
		return nil, err
	}
	if o.dir != "" {
		dir, err := filepath.Abs(o.dir)
		if err != nil {
			return nil, err
		}
		p.dirs = []string{dir}
	} else {
		selected, err := selectAgents(names, o.scope, p.root)
		if err != nil {
			return nil, err
		}
		if p.dirs, err = targetDirs(selected, o.scope, p.root); err != nil {
			return nil, err
		}
	}

	entries := make([][]fs.DirEntry, len(p.dirs))
	for i, dir := range p.dirs {
		es, err := os.ReadDir(dir)
		if err != nil && !errors.Is(err, fs.ErrNotExist) {
			return nil, err
		}
		entries[i] = es
	}

	if p.skills, err = selectSkills(o.skills); err != nil {
		return nil, err
	}
	for i, dir := range p.dirs {
		for _, s := range p.skills {
			path := filepath.Join(dir, s.name)
			st, err := inspect(path, s.digest)
			if err != nil {
				return nil, err
			}
			p.items = append(p.items, item{name: s.name, dir: dir, path: path, state: st, skill: s})
		}
		if len(o.skills) > 0 {
			continue // orphans are only looked for when every skill is in play
		}
		for _, e := range entries[i] {
			name := e.Name()
			if !e.IsDir() || strings.HasPrefix(name, ".") || lookupSkill(name) != nil {
				continue
			}
			path := filepath.Join(dir, name)
			st, err := inspect(path, "")
			if err != nil {
				return nil, err
			}
			// Installed by this tool and untouched since: with no embedded
			// skill to compare against, that reads as outdated.
			if st == stateOutdated {
				p.items = append(p.items, item{name: name, dir: dir, path: path, state: stateOrphaned})
			}
		}
	}
	return p, nil
}

// selectSkills returns the embedded skills named, or all of them.
func selectSkills(names []string) ([]*embeddedSkill, error) {
	if len(names) == 0 {
		return embedded, nil
	}
	var skills []*embeddedSkill
	for _, name := range names {
		s := lookupSkill(name)
		if s == nil {
			known := make([]string, len(embedded))
			for i, s := range embedded {
				known[i] = s.name
			}
			return nil, fmt.Errorf("skillembed: unknown skill %q (embedded: %s)", name, strings.Join(known, ", "))
		}
		skills = append(skills, s)
	}
	return skills, nil
}

func (c *cli) install(p *plan, o options) int {
	installedAt := time.Now().UTC().Format(time.RFC3339)
	var (
		results []result
		refused []item
		err     error
	)
	for _, it := range p.items {
		r := result{name: it.name, path: it.path}
		switch {
		case it.state == stateOrphaned:
			r.verb, r.note = "removed", "no longer embedded in "+toolName
			if !o.dryRun {
				if rerr := os.RemoveAll(it.path); rerr != nil {
					err = fmt.Errorf("remove %s from %s: %w", it.name, it.dir, rerr)
				}
			}
		case it.state == stateUpToDate && !o.force:
			r.verb, r.note = "skipped", "already up to date"
		case it.state == stateModified && !o.force:
			r.verb, r.note = "skipped", noteEdited
			refused = append(refused, it)
		case it.state == stateForeign && !o.force:
			r.verb, r.note = "skipped", noteForeign
			refused = append(refused, it)
		default:
			r.verb = "updated"
			if it.state == stateMissing {
				r.verb = "installed"
			}
			if !o.dryRun {
				if ierr := installSkill(it, installedAt); ierr != nil {
					err = fmt.Errorf("install %s into %s: %w", it.name, it.dir, ierr)
				}
			}
		}
		if err != nil {
			break
		}
		results = append(results, r)
	}
	c.report(p, o.dryRun, results)
	if err != nil {
		return c.fail(err)
	}
	if len(refused) > 0 {
		var b strings.Builder
		b.WriteString("refusing to overwrite skills this tool did not install, or that were edited after installing:\n")
		for _, it := range refused {
			fmt.Fprintf(&b, "  %s (%s)\n", it.path, it.state)
		}
		b.WriteString("re-run with --force to overwrite")
		return c.fail(errors.New(b.String()))
	}
	return 0
}

func (c *cli) uninstall(p *plan, o options) int {
	var (
		results []result
		err     error
	)
	for _, it := range p.items {
		r := result{name: it.name, path: it.path}
		switch {
		case it.state == stateMissing:
			r.verb, r.note = "skipped", "not installed"
		case it.state == stateModified && !o.force:
			r.verb, r.note = "skipped", noteEdited
		case it.state == stateForeign && !o.force:
			r.verb, r.note = "skipped", noteForeign
		default:
			r.verb = "removed"
			if !o.dryRun {
				err = os.RemoveAll(it.path)
			}
		}
		if err != nil {
			break
		}
		results = append(results, r)
	}
	c.report(p, o.dryRun, results)
	if err != nil {
		return c.fail(err)
	}
	return 0
}

// installSkill writes the skill into a temporary directory beside its
// destination, then swaps it into place, so a reader never sees half of it.
func installSkill(it item, installedAt string) error {
	if err := os.MkdirAll(it.dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.MkdirTemp(it.dir, "."+it.name+".tmp-*")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp) // gone already once renamed into place

	meta := [][2]string{
		{keyBy, toolName},
		{keyVersion, toolVersion},
		{keyAt, strconv.Quote(installedAt)},
		{keyDigest, strconv.Quote(it.skill.digest)},
	}
	if err := writeFiles(it.skill.files, tmp, meta); err != nil {
		return err
	}

	// Reserve a name to move the previous install aside to.
	old, err := os.MkdirTemp(it.dir, "."+it.name+".old-*")
	if err != nil {
		return err
	}
	if err := os.Remove(old); err != nil {
		return err
	}
	if err := os.Rename(it.path, old); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	if err := os.Rename(tmp, it.path); err != nil {
		os.Rename(old, it.path) // put the previous install back
		return err
	}
	os.RemoveAll(old) // best effort: the new install is in place
	return nil
}

// writeFiles copies a skill into dir, adding the install metadata to its
// SKILL.md.
func writeFiles(files fs.FS, dir string, meta [][2]string) error {
	return fs.WalkDir(files, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		target := filepath.Join(dir, filepath.FromSlash(p))
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		data, err := fs.ReadFile(files, p)
		if err != nil {
			return err
		}
		if p == skillFile {
			data = render(data, meta)
		}
		return os.WriteFile(target, data, 0o644)
	})
}
