package analyzer

import (
	"path/filepath"
	"strings"
)

// Rules is the effective configuration for one package: every key resolved
// down the chain of config files.
type Rules struct {
	Unexported string // "shared" or "private"
	// UnexportedSet records whether a config file stated defaults.unexported.
	UnexportedSet bool
	Qualify       string // "always", "never" or "ondemand"
	Exported      bool
	Vocabulary    map[string][]string
	Boundary      bool
	Surplus       string // "off", "loose" or "strict"
	Unused        string // "off", "loose" or "strict"

	// Only holds one pattern list per stating file; a file must match every
	// list. Omit holds every omit pattern of the chain.
	Only []PatternList
	Omit []Pattern

	// Baseline is the path of the baseline to consult, or "".
	Baseline string
	// BaselineSet records whether a config file named the baseline.
	BaselineSet bool

	// Chain lists the config files read, outermost first.
	Chain []string
}

// PatternList is the filter.only list of one config file.
type PatternList struct {
	Dir      string
	Patterns []Pattern
}

// Pattern is a filter glob anchored at the directory of its config file.
type Pattern struct {
	Dir  string
	Text string
}

// DefaultRules returns the built-in defaults.
func DefaultRules() *Rules {
	return &Rules{
		Unexported: "private",
		Qualify:    "never",
		Boundary:   true,
		Surplus:    "strict",
		Unused:     "strict",
		Vocabulary: map[string][]string{},
	}
}

// FileSection is one parsed config file.
type FileSection struct {
	Path  string
	Shown string // the path as it was named
	Dir   string

	Unexported *string
	Qualify    *string
	Exported   *bool
	Vocabulary map[string][]string
	VocabOrder []string
	Boundary   *string
	Surplus    *string
	Unused     *string
	Only       []string
	OnlySet    bool
	Omit       []string
	Baseline   *string
}

// compose resolves a chain of config files, outermost first.
func compose(chain []*FileSection) *Rules {
	r := DefaultRules()
	for _, f := range chain {
		r.Chain = append(r.Chain, f.Shown)
		if f.Unexported != nil {
			r.Unexported = *f.Unexported
			r.UnexportedSet = true
		}
		if f.Qualify != nil {
			r.Qualify = *f.Qualify
		}
		if f.Exported != nil {
			r.Exported = *f.Exported
		}
		for ns, words := range f.Vocabulary {
			r.Vocabulary[ns] = words
		}
		if f.Boundary != nil {
			r.Boundary = *f.Boundary == "on"
		}
		if f.Surplus != nil {
			r.Surplus = *f.Surplus
		}
		if f.Unused != nil {
			r.Unused = *f.Unused
		}
		if len(f.Only) > 0 {
			list := PatternList{Dir: f.Dir}
			for _, p := range f.Only {
				list.Patterns = append(list.Patterns, Pattern{Dir: f.Dir, Text: p})
			}
			r.Only = append(r.Only, list)
		}
		for _, p := range f.Omit {
			r.Omit = append(r.Omit, Pattern{Dir: f.Dir, Text: p})
		}
		if f.Baseline != nil {
			r.Baseline = filepath.Join(f.Dir, *f.Baseline)
			r.BaselineSet = true
		}
	}
	return r
}

// match reports whether the file at path matches the pattern, which is read
// against the pattern's directory with .gitignore anchoring.
func (p Pattern) match(path string) bool {
	rel, err := filepath.Rel(p.Dir, path)
	if err != nil || rel == ".." || strings.HasPrefix(rel, "../") {
		return false
	}
	rel = filepath.ToSlash(rel)
	pat := p.Text
	dirOnly := strings.HasSuffix(pat, "/")
	pat = strings.TrimSuffix(pat, "/")
	anchored := false
	switch {
	case strings.HasPrefix(pat, "./"):
		pat = strings.TrimPrefix(pat, "./")
		anchored = true
	case strings.HasPrefix(pat, "/"):
		pat = strings.TrimPrefix(pat, "/")
		anchored = true
	case strings.Contains(pat, "/"):
		anchored = true
	}
	if dirOnly {
		pat += "/**"
	}
	if !anchored {
		pat = "**/" + pat
	}
	return globMatch(strings.Split(pat, "/"), strings.Split(rel, "/"))
}

// globMatch matches path segments against pattern segments. "**" matches
// any number of segments, though a trailing one needs at least one: a
// directory pattern names what is inside it.
func globMatch(pat, segs []string) bool {
	if len(pat) == 0 {
		return len(segs) == 0
	}
	if pat[0] == "**" {
		min := 0
		if len(pat) == 1 {
			min = 1
		}
		for i := min; i <= len(segs); i++ {
			if globMatch(pat[1:], segs[i:]) {
				return true
			}
		}
		return false
	}
	if len(segs) == 0 || !segMatch(pat[0], segs[0]) {
		return false
	}
	return globMatch(pat[1:], segs[1:])
}

// segMatch matches one path segment, where '*' matches any run of
// characters and '?' any one character.
func segMatch(pat, s string) bool {
	p, n := []rune(pat), []rune(s)
	var match func(i, j int) bool
	match = func(i, j int) bool {
		for i < len(p) {
			switch p[i] {
			case '*':
				for k := j; k <= len(n); k++ {
					if match(i+1, k) {
						return true
					}
				}
				return false
			case '?':
				if j >= len(n) {
					return false
				}
			default:
				if j >= len(n) || p[i] != n[j] {
					return false
				}
			}
			i++
			j++
		}
		return j == len(n)
	}
	return match(0, 0)
}

// admits reports whether the filter lets a file be read.
func (r *Rules) admits(path string) bool {
	for _, list := range r.Only {
		matched := false
		for _, p := range list.Patterns {
			if p.match(path) {
				matched = true
				break
			}
		}
		if !matched {
			return false
		}
	}
	for _, p := range r.Omit {
		if p.match(path) {
			return false
		}
	}
	return true
}
