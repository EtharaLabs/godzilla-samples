package skill

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// agent is a coding agent whose skills directory the tool can write to.
type agent struct {
	name    string
	project string // skills directory, relative to the project root
	user    string // skills directory, relative to the home directory
}

// agents in the order the tool reports them.
var agents = []agent{
	{"github-copilot", ".agents/skills", ".copilot/skills"},
	{"claude-code", ".claude/skills", ".claude/skills"},
	{"cursor", ".agents/skills", ".cursor/skills"},
	{"codex", ".agents/skills", ".codex/skills"},
	{"gemini", ".agents/skills", ".gemini/skills"},
	{"antigravity", ".agents/skills", ".gemini/antigravity/skills"},
}

const (
	scopeProject = "project"
	scopeUser    = "user"
)

func lookupAgent(name string) (agent, bool) {
	for _, a := range agents {
		if a.name == name {
			return a, true
		}
	}
	return agent{}, false
}

// skillsDir returns where the agent keeps its skills in the given scope.
func (a agent) skillsDir(scope, root string) (string, error) {
	if scope == scopeProject {
		return filepath.Join(root, a.project), nil
	}
	if a.name == "claude-code" {
		if dir := strings.TrimSpace(os.Getenv("CLAUDE_CONFIG_DIR")); dir != "" {
			abs, err := filepath.Abs(dir)
			if err != nil {
				return "", err
			}
			return filepath.Join(abs, "skills"), nil
		}
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	home, err = filepath.Abs(home)
	if err != nil {
		return "", err
	}
	return filepath.Join(home, a.user), nil
}

// parseAgents splits the -agent values into names, checking each one.
func parseAgents(values []string) ([]string, error) {
	var names []string
	for _, v := range values {
		for _, name := range strings.Split(v, ",") {
			name = strings.TrimSpace(name)
			if name == "" {
				continue
			}
			if _, ok := lookupAgent(name); !ok && name != "all" && name != "detected" {
				known := make([]string, len(agents))
				for i, a := range agents {
					known[i] = a.name
				}
				sort.Strings(known)
				return nil, fmt.Errorf("skillembed: unknown agent %q (want one of %s, or all, or detected)",
					name, strings.Join(known, ", "))
			}
			names = append(names, name)
		}
	}
	return names, nil
}

// selectAgents expands all and detected. An agent is detected when the
// directory holding its skills directory exists; when detection is all that
// was asked for and it finds nothing, every agent is selected.
func selectAgents(names []string, scope, root string) ([]agent, error) {
	if len(names) == 0 {
		return nil, errors.New("skillembed: no agent selected")
	}
	var selected []agent
	seen := make(map[string]bool)
	add := func(a agent) {
		if !seen[a.name] {
			seen[a.name] = true
			selected = append(selected, a)
		}
	}
	for _, name := range names {
		switch name {
		case "all":
			for _, a := range agents {
				add(a)
			}
		case "detected":
			for _, a := range agents {
				dir, err := a.skillsDir(scope, root)
				if err != nil {
					return nil, err
				}
				if isDir(filepath.Dir(dir)) {
					add(a)
				}
			}
		default:
			a, _ := lookupAgent(name)
			add(a)
		}
	}
	if len(selected) == 0 {
		selected = append(selected, agents...)
	}
	return selected, nil
}

// targetDirs returns the distinct skills directories of the agents. In the
// project scope each must stay inside the project root once symbolic links
// are followed.
func targetDirs(selected []agent, scope, root string) ([]string, error) {
	var dirs []string
	seen := make(map[string]bool)
	for _, a := range selected {
		dir, err := a.skillsDir(scope, root)
		if err != nil {
			return nil, err
		}
		if !seen[dir] {
			seen[dir] = true
			dirs = append(dirs, dir)
		}
	}
	if scope == scopeProject {
		for _, dir := range dirs {
			if err := checkInside(root, dir); err != nil {
				return nil, err
			}
		}
	}
	return dirs, nil
}

// findProjectRoot walks up from the working directory to the nearest
// directory holding .git. Below that, the nearest directory already holding
// an agent's skills parent wins. Without a repository the working directory
// is the root. The home directory is refused, since the user scope is meant
// for it.
func findProjectRoot() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	root, marked := cwd, ""
	for dir := cwd; ; dir = filepath.Dir(dir) {
		if marked == "" && (isDir(filepath.Join(dir, ".agents")) || isDir(filepath.Join(dir, ".claude"))) {
			marked = dir
		}
		if exists(filepath.Join(dir, ".git")) {
			root = dir
			if marked != "" {
				root = marked
			}
			break
		}
		if filepath.Dir(dir) == dir {
			break
		}
	}
	if home, err := os.UserHomeDir(); err == nil && sameDir(root, home) {
		return "", fmt.Errorf("skillembed: the search landed on the home directory (%s), "+
			"so pass --scope user to write there on purpose or --dir to name another directory", root)
	}
	return root, nil
}

func sameDir(a, b string) bool {
	ra, err := filepath.EvalSymlinks(a)
	if err != nil {
		return false
	}
	rb, err := filepath.EvalSymlinks(b)
	if err != nil {
		return false
	}
	return ra == rb
}

// checkInside fails when dir, with its symbolic links followed, lies outside
// root.
func checkInside(root, dir string) error {
	realRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		return err
	}
	realDir, err := resolve(dir)
	if err != nil {
		return err
	}
	if rel, err := filepath.Rel(realRoot, realDir); err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
		return fmt.Errorf("skillembed: the destination is outside the project root (%s is really %s), "+
			"so pass --dir to write there on purpose", dir, realDir)
	}
	return nil
}

// resolve follows the symbolic links of an absolute path, including dangling
// ones, keeping whatever part of it does not exist yet.
func resolve(p string) (string, error) {
	return resolveLinks(p, 0)
}

func resolveLinks(p string, hops int) (string, error) {
	resolved, err := filepath.EvalSymlinks(p)
	if err == nil {
		return resolved, nil
	}
	if !errors.Is(err, fs.ErrNotExist) {
		return "", err
	}
	if fi, lerr := os.Lstat(p); lerr == nil && fi.Mode()&fs.ModeSymlink != 0 {
		if hops++; hops > 255 {
			return "", errors.New("EvalSymlinks: too many links")
		}
		link, err := os.Readlink(p)
		if err != nil {
			return "", err
		}
		if !filepath.IsAbs(link) {
			link = filepath.Join(filepath.Dir(p), link)
		}
		return resolveLinks(link, hops)
	}
	parent := filepath.Dir(p)
	if parent == p {
		return p, nil
	}
	resolvedParent, err := resolveLinks(parent, hops)
	if err != nil {
		return "", err
	}
	return filepath.Join(resolvedParent, filepath.Base(p)), nil
}

func isDir(p string) bool {
	fi, err := os.Stat(p)
	return err == nil && fi.IsDir()
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
