package analyzer

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"declscope/internal/load"
	"declscope/internal/yaml"
)

// BaselineName is the default name of a baseline file.
const BaselineName = ".declscope-baseline.yaml"

// Baseline maps package path, rule and namespace to the declarations
// recorded there.
type Baseline map[string]map[string]map[string][]string

// Has reports whether an entry is recorded.
func (b Baseline) Has(pkg, rule, ns, name string) bool {
	for _, n := range b[pkg][rule][ns] {
		if n == name {
			return true
		}
	}
	return false
}

// Count returns the number of entries.
func (b Baseline) Count() int {
	n := 0
	for _, rules := range b {
		for _, nss := range rules {
			for _, names := range nss {
				n += len(names)
			}
		}
	}
	return n
}

var baselineCache = struct {
	sync.Mutex
	m map[string]*cachedBaseline
}{m: make(map[string]*cachedBaseline)}

type cachedBaseline struct {
	b   Baseline
	err error
}

// BaselinePath returns the baseline the analyzer consults for a package,
// or "" when there is none.
func BaselinePath(pkg *load.Package, rules *Rules) string {
	return baselineFrom(pkg, pkg.Dir, rules)
}

func baselineFrom(pkg *load.Package, dir string, rules *Rules) string {
	if rules.BaselineSet {
		return rules.Baseline
	}
	root := ""
	if pkg.Module != nil {
		root = pkg.Module.Dir
	}
	for d := dir; d != ""; d = filepath.Dir(d) {
		p := filepath.Join(d, BaselineName)
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p
		}
		if root == "" || d == root || d == filepath.Dir(d) {
			break
		}
		if rel, err := filepath.Rel(root, d); err != nil || strings.HasPrefix(rel, "..") {
			break
		}
	}
	return ""
}

// LoadBaseline reads a baseline file. A missing file is an empty baseline.
func LoadBaseline(path string) (Baseline, error) {
	baselineCache.Lock()
	defer baselineCache.Unlock()
	if c, ok := baselineCache.m[path]; ok {
		return c.b, c.err
	}
	b, err := ParseBaselineFile(path)
	if err != nil {
		err = fmt.Errorf("%s: %v (regenerate it with `declscope baseline ./...`)", path, err)
	}
	baselineCache.m[path] = &cachedBaseline{b, err}
	return b, err
}

// ParseBaselineFile reads a baseline file without caching.
func ParseBaselineFile(path string) (Baseline, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return Baseline{}, nil
		}
		return nil, err
	}
	return ParseBaseline(data)
}

// ParseBaseline decodes baseline content like yaml.v3 with known fields.
func ParseBaseline(data []byte) (Baseline, error) {
	doc, err := yaml.Parse(data)
	if err != nil {
		return nil, err
	}
	d := &decoder{}
	b := Baseline{}
	err = func() (err error) {
		defer func() {
			if r := recover(); r != nil {
				f, ok := r.(failure)
				if !ok {
					panic(r)
				}
				err = f.err
			}
		}()
		root := resolveNode(doc)
		if root == nil {
			return nil
		}
		d.structFields(root, "baseline.file", func(key string, _, v *yaml.Node) bool {
			if key != "packages" {
				return false
			}
			d.nestedMap(v, 3, func(keys []string, names []string) {
				pkg, rule, ns := keys[0], keys[1], keys[2]
				if b[pkg] == nil {
					b[pkg] = map[string]map[string][]string{}
				}
				if b[pkg][rule] == nil {
					b[pkg][rule] = map[string][]string{}
				}
				b[pkg][rule][ns] = names
			})
			return true
		})
		return nil
	}()
	if err != nil {
		return nil, err
	}
	if len(d.terrors) > 0 {
		return nil, errors.New("yaml: unmarshal errors:\n  " + strings.Join(d.terrors, "\n  "))
	}
	return b, nil
}

// nestedMap decodes depth levels of string-keyed maps ending in []string,
// calling leaf for every list.
func (d *decoder) nestedMap(n *yaml.Node, depth int, leaf func(keys, names []string)) {
	d.nestedMapKeys(n, depth, nil, leaf)
}

func mapTypeName(depth int) string {
	return strings.Repeat("map[string]", depth) + "[]string"
}

func (d *decoder) nestedMapKeys(n *yaml.Node, depth int, keys []string, leaf func(keys, names []string)) {
	n = resolveNode(n)
	if isNull(n) {
		return
	}
	switch n.Kind {
	case yaml.SequenceNode:
		d.terror(n, "!!seq", mapTypeName(depth))
		return
	case yaml.ScalarNode:
		checkExplicit(n)
		d.terror(n, n.ShortTag(), mapTypeName(depth))
		return
	}
	if d.dupKeys(n) {
		return
	}
	for i := 0; i+1 < len(n.Content); i += 2 {
		k, v := n.Content[i], n.Content[i+1]
		key, ok := d.str(k)
		if !ok && !isNull(resolveNode(k)) {
			continue
		}
		next := append(append([]string(nil), keys...), key)
		if depth == 1 {
			if names, ok := d.stringList(v); ok {
				leaf(next, names)
			}
			continue
		}
		d.nestedMapKeys(v, depth-1, next, leaf)
	}
}

// baselineKey returns the namespace and name under which a finding is
// recorded, if its rule is recorded at all.
func (m *model) baselineKey(f *finding) (string, string, bool) {
	switch f.rule {
	case "boundary", "qualify", "surplus":
	default:
		return "", "", false
	}
	d := f.decl
	if d == nil && f.dir != nil {
		if reach := m.reached(f.dir); len(reach) > 0 {
			d = reach[0]
		}
	}
	if d == nil {
		return "", "", false
	}
	return d.ns.key(), d.display, true
}

var _ = strconv.Itoa
