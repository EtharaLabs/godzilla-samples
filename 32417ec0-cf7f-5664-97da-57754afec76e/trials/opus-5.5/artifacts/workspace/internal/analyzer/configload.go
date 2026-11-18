package analyzer

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"

	"declscope/internal/load"
	"declscope/internal/yaml"
)

// sections describes the config file layout: the Go type name the decoder
// reports for each section, its dotted path, and the keys it takes.
var sections = map[string]struct {
	path string
	keys []string
}{
	"config.File":            {"", []string{"defaults", "rules", "filter", "baseline"}},
	"config.defaultsSection": {"defaults", []string{"unexported"}},
	"config.rulesSection":    {"rules", []string{"naming", "boundary", "surplus", "unused"}},
	"config.namingSection":   {"rules.naming", []string{"qualify", "exported", "vocabulary"}},
	"config.filterSection":   {"filter", []string{"only", "omit"}},
}

// decoder decodes config nodes with the conventions of yaml.v3.
type decoder struct {
	terrors []string
}

// failure aborts decoding with a plain error.
type failure struct{ err error }

func (d *decoder) terror(n *yaml.Node, tag, into string) {
	if n.Tag != "" {
		tag = n.Tag
	}
	short := shortTagOf(tag)
	value := n.Value
	if short != "!!seq" && short != "!!map" {
		if len(value) > 10 {
			value = " `" + value[:7] + "...`"
		} else {
			value = " `" + value + "`"
		}
	} else {
		value = ""
	}
	d.terrors = append(d.terrors, fmt.Sprintf("line %d: cannot unmarshal %s%s into %s", n.Line, short, value, into))
}

func shortTagOf(tag string) string {
	const long = "tag:yaml.org,2002:"
	if strings.HasPrefix(tag, long) {
		return "!!" + tag[len(long):]
	}
	return tag
}

// resolve follows aliases and documents to the node holding the value.
func resolveNode(n *yaml.Node) *yaml.Node {
	for n != nil {
		switch n.Kind {
		case yaml.DocumentNode:
			if len(n.Content) == 0 {
				return nil
			}
			n = n.Content[0]
		case yaml.AliasNode:
			n = n.Alias
		default:
			return n
		}
	}
	return nil
}

func isNull(n *yaml.Node) bool {
	return n == nil || n.Kind == yaml.ScalarNode && n.ShortTag() == "!!null"
}

// checkExplicit fails like yaml.v3 when an explicit tag does not match the
// value it tags.
func checkExplicit(n *yaml.Node) {
	if n.Kind != yaml.ScalarNode || n.Style&yaml.TaggedStyle == 0 {
		return
	}
	tag := n.ShortTag()
	switch tag {
	case "!!str", "!!null", "!!binary", "!!merge", "!!seq", "!!map":
		return
	}
	plain := &yaml.Node{Kind: yaml.ScalarNode, Value: n.Value}
	got := plain.ShortTag()
	if got == tag {
		return
	}
	if tag == "!!float" && got == "!!int" {
		return
	}
	if tag == "!!timestamp" && got == "!!str" {
		return
	}
	switch tag {
	case "!!int", "!!float", "!!bool", "!!timestamp":
		panic(failure{fmt.Errorf("yaml: cannot decode %s `%s` as a %s", got, n.Value, tag)})
	}
}

// str decodes a scalar into a string.
func (d *decoder) str(n *yaml.Node) (string, bool) {
	n = resolveNode(n)
	if isNull(n) {
		return "", false
	}
	switch n.Kind {
	case yaml.ScalarNode:
		checkExplicit(n)
		return n.Value, true
	case yaml.SequenceNode:
		d.terror(n, "!!seq", "string")
	case yaml.MappingNode:
		if d.dupKeys(n) {
			return "", false
		}
		d.terror(n, "!!map", "string")
	}
	return "", false
}

// boolean decodes a scalar into a bool with yaml.v3's YAML 1.1 leniency.
func (d *decoder) boolean(n *yaml.Node) (bool, bool) {
	n = resolveNode(n)
	if isNull(n) {
		return false, false
	}
	if n.Kind == yaml.ScalarNode {
		checkExplicit(n)
		quoted := n.Style&(yaml.SingleQuotedStyle|yaml.DoubleQuotedStyle|yaml.LiteralStyle|yaml.FoldedStyle) != 0 || n.ShortTag() == "!!str"
		if !quoted {
			switch n.Value {
			case "true", "True", "TRUE":
				return true, true
			case "false", "False", "FALSE":
				return false, true
			}
		}
		switch n.Value {
		case "y", "Y", "yes", "Yes", "YES", "on", "On", "ON":
			return true, true
		case "n", "N", "no", "No", "NO", "off", "Off", "OFF":
			return false, true
		}
	}
	panic(failure{errors.New("want true or false")})
}

// strings decodes a sequence of scalars.
func (d *decoder) stringList(n *yaml.Node) ([]string, bool) {
	n = resolveNode(n)
	if isNull(n) {
		return nil, false
	}
	switch n.Kind {
	case yaml.SequenceNode:
		out := []string{}
		for _, item := range n.Content {
			if s, ok := d.str(item); ok {
				out = append(out, s)
			} else if isNull(resolveNode(item)) {
				out = append(out, "")
			}
		}
		return out, true
	case yaml.MappingNode:
		if d.dupKeys(n) {
			return nil, false
		}
		d.terror(n, "!!map", "[]string")
	default:
		checkExplicit(n)
		d.terror(n, n.ShortTag(), "[]string")
	}
	return nil, false
}

// dupKeys reports duplicate keys of a mapping like yaml.v3 does.
func (d *decoder) dupKeys(n *yaml.Node) bool {
	before := len(d.terrors)
	l := len(n.Content)
	for i := 0; i < l; i += 2 {
		ni := n.Content[i]
		for j := i + 2; j < l; j += 2 {
			nj := n.Content[j]
			if ni.Kind == nj.Kind && ni.Value == nj.Value {
				d.terrors = append(d.terrors, fmt.Sprintf("line %d: mapping key %s already defined at line %d", nj.Line, strconv.Quote(nj.Value), ni.Line))
			}
		}
	}
	return len(d.terrors) > before
}

// mapping walks the key/value pairs of a mapping decoded into a struct type,
// including merged ones, calling field for every key.
func (d *decoder) structFields(n *yaml.Node, typeName string, field func(key string, keyNode, value *yaml.Node) bool) bool {
	n = resolveNode(n)
	if isNull(n) {
		return false
	}
	switch n.Kind {
	case yaml.MappingNode:
	case yaml.SequenceNode:
		d.terror(n, "!!seq", typeName)
		return false
	default:
		checkExplicit(n)
		d.terror(n, n.ShortTag(), typeName)
		return false
	}
	if d.dupKeys(n) {
		return false
	}
	for i := 0; i+1 < len(n.Content); i += 2 {
		k, v := n.Content[i], n.Content[i+1]
		if k.Kind == yaml.ScalarNode && k.ShortTag() == "!!merge" {
			d.merge(v, typeName, field)
			continue
		}
		key, ok := d.str(k)
		if !ok && !isNull(resolveNode(k)) {
			continue
		}
		if !field(key, k, v) {
			d.terrors = append(d.terrors, fmt.Sprintf("line %d: field %s not found in type %s", k.Line, key, typeName))
		}
	}
	return true
}

func (d *decoder) merge(v *yaml.Node, typeName string, field func(string, *yaml.Node, *yaml.Node) bool) {
	v = resolveNode(v)
	switch {
	case v != nil && v.Kind == yaml.MappingNode:
		d.structFields(v, typeName, field)
	case v != nil && v.Kind == yaml.SequenceNode:
		for i := len(v.Content) - 1; i >= 0; i-- {
			item := resolveNode(v.Content[i])
			if item == nil || item.Kind != yaml.MappingNode {
				panic(failure{errors.New("yaml: map merge requires map or sequence of maps as the value")})
			}
			d.structFields(item, typeName, field)
		}
	default:
		panic(failure{errors.New("yaml: map merge requires map or sequence of maps as the value")})
	}
}

var unknownField = regexp.MustCompile(`^line (\d+): field (\S+) not found in type (config\.\w+)$`)

// decodeConfig decodes a parsed config document into a FileSection.
func decodeConfig(doc *yaml.Node, fs *FileSection) (err error) {
	d := &decoder{}
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
	d.structFields(root, "config.File", func(key string, _, v *yaml.Node) bool {
		switch key {
		case "defaults":
			d.structFields(v, "config.defaultsSection", func(key string, _, v *yaml.Node) bool {
				if key != "unexported" {
					return false
				}
				if s, ok := d.str(v); ok {
					fs.Unexported = &s
				}
				return true
			})
		case "rules":
			d.structFields(v, "config.rulesSection", func(key string, _, v *yaml.Node) bool {
				switch key {
				case "naming":
					d.structFields(v, "config.namingSection", func(key string, _, v *yaml.Node) bool {
						switch key {
						case "qualify":
							if s, ok := d.str(v); ok {
								fs.Qualify = &s
							}
						case "exported":
							if b, ok := d.boolean(v); ok {
								fs.Exported = &b
							}
						case "vocabulary":
							d.vocabulary(v, fs)
						default:
							return false
						}
						return true
					})
				case "boundary":
					if s, ok := d.str(v); ok {
						fs.Boundary = &s
					}
				case "surplus":
					if s, ok := d.str(v); ok {
						fs.Surplus = &s
					}
				case "unused":
					if s, ok := d.str(v); ok {
						fs.Unused = &s
					}
				default:
					return false
				}
				return true
			})
		case "filter":
			d.structFields(v, "config.filterSection", func(key string, _, v *yaml.Node) bool {
				switch key {
				case "only":
					if l, ok := d.stringList(v); ok {
						fs.Only = l
						fs.OnlySet = true
					}
				case "omit":
					if l, ok := d.stringList(v); ok {
						fs.Omit = l
					}
				default:
					return false
				}
				return true
			})
		case "baseline":
			if s, ok := d.str(v); ok {
				fs.Baseline = &s
			}
		default:
			return false
		}
		return true
	})
	if len(d.terrors) == 0 {
		return nil
	}
	msgs := make([]string, len(d.terrors))
	for i, e := range d.terrors {
		msgs[i] = e
		if m := unknownField.FindStringSubmatch(e); m != nil {
			sec := sections[m[3]]
			key := m[2]
			if sec.path != "" {
				key = sec.path + "." + key
			}
			msgs[i] = fmt.Sprintf("line %s: unknown key %q (this section takes %s)", m[1], key, strings.Join(sec.keys, ", "))
		}
	}
	return errors.New(strings.Join(msgs, "\n"))
}

func (d *decoder) vocabulary(v *yaml.Node, fs *FileSection) {
	v = resolveNode(v)
	if isNull(v) {
		return
	}
	switch v.Kind {
	case yaml.SequenceNode:
		d.terror(v, "!!seq", "map[string][]string")
		return
	case yaml.ScalarNode:
		checkExplicit(v)
		d.terror(v, v.ShortTag(), "map[string][]string")
		return
	}
	if d.dupKeys(v) {
		return
	}
	if fs.Vocabulary == nil {
		fs.Vocabulary = make(map[string][]string)
	}
	for i := 0; i+1 < len(v.Content); i += 2 {
		k, val := v.Content[i], v.Content[i+1]
		key, ok := d.str(k)
		if !ok && !isNull(resolveNode(k)) {
			continue
		}
		words, ok := d.stringList(val)
		if ok || isNull(resolveNode(val)) {
			if _, seen := fs.Vocabulary[key]; !seen {
				fs.VocabOrder = append(fs.VocabOrder, key)
			}
			fs.Vocabulary[key] = words
		}
	}
}

// validate checks the values of a decoded config file.
func (fs *FileSection) validate() error {
	if fs.Unexported != nil {
		switch *fs.Unexported {
		case "":
			fs.Unexported = nil
		case "shared", "private":
		default:
			return fmt.Errorf("defaults.unexported: unknown scope %q (want shared or private)", *fs.Unexported)
		}
	}
	check := func(p **string, key string, want string, modes ...string) error {
		if *p == nil {
			return nil
		}
		v := **p
		if v == "" {
			*p = nil
			return nil
		}
		for _, m := range modes {
			if v == m {
				return nil
			}
		}
		return fmt.Errorf("%s: unknown mode %q (want %s)", key, v, want)
	}
	if err := check(&fs.Qualify, "rules.naming.qualify", "always, never or ondemand", "always", "never", "ondemand"); err != nil {
		return err
	}
	if err := check(&fs.Boundary, "rules.boundary", "off or on", "off", "on"); err != nil {
		return err
	}
	if err := check(&fs.Surplus, "rules.surplus", "off, loose or strict", "off", "loose", "strict"); err != nil {
		return err
	}
	if err := check(&fs.Unused, "rules.unused", "off, loose or strict", "off", "loose", "strict"); err != nil {
		return err
	}
	return nil
}

// checkPatterns rejects a filter pattern that leaves its directory.
func (fs *FileSection) checkPatterns() error {
	for _, list := range [][]string{fs.Only, fs.Omit} {
		for _, p := range list {
			for _, seg := range strings.Split(p, "/") {
				if seg == ".." {
					return fmt.Errorf("filter %q: a pattern cannot leave the directory of the config file that states it", p)
				}
			}
		}
	}
	return nil
}

// configCache caches parsed config files by path.
var configCache = struct {
	sync.Mutex
	m map[string]*cachedConfig
}{m: make(map[string]*cachedConfig)}

type cachedConfig struct {
	fs  *FileSection
	err error
}

// readConfig reads and validates one config file. name is the path as the
// user gave it, abs its absolute form.
func readConfig(name, abs string) (*FileSection, error) {
	configCache.Lock()
	defer configCache.Unlock()
	if c, ok := configCache.m[abs]; ok {
		return c.fs, c.err
	}
	fs, err := readConfigUncached(name, abs)
	configCache.m[abs] = &cachedConfig{fs, err}
	return fs, err
}

func readConfigUncached(name, abs string) (*FileSection, error) {
	data, err := os.ReadFile(name)
	if err != nil {
		return nil, err
	}
	fs := &FileSection{Path: abs, Shown: name, Dir: filepath.Dir(abs)}
	doc, err := yaml.Parse(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %v", abs, err)
	}
	if err := decodeConfig(doc, fs); err != nil {
		return nil, fmt.Errorf("%s: %v", abs, err)
	}
	if err := fs.validate(); err != nil {
		return nil, fmt.Errorf("%s: %v", abs, err)
	}
	if err := fs.checkPatterns(); err != nil {
		return nil, err
	}
	return fs, nil
}

// configNames are the config file names, in order of preference.
var configNames = []string{".declscope.yaml", ".declscope.yml"}

// FindChain returns the config files that govern a directory, outermost
// first: one per directory between the module root and dir.
func FindChain(dir, root string) []string {
	var dirs []string
	for d := dir; ; d = filepath.Dir(d) {
		dirs = append(dirs, d)
		if root == "" || d == root || d == filepath.Dir(d) {
			break
		}
		if rel, err := filepath.Rel(root, d); err != nil || strings.HasPrefix(rel, "..") {
			break
		}
	}
	var chain []string
	for i := len(dirs) - 1; i >= 0; i-- {
		for _, name := range configNames {
			p := filepath.Join(dirs[i], name)
			if st, err := os.Stat(p); err == nil && !st.IsDir() {
				chain = append(chain, p)
				break
			}
		}
	}
	return chain
}

// searchDir is where the search for a package's config files starts: the
// directory of its first file, which for a test main or a cgo-only package
// is the build cache.
func searchDir(pkg *load.Package) string {
	if len(pkg.CompiledGoFiles) > 0 {
		return filepath.Dir(pkg.CompiledGoFiles[0])
	}
	return pkg.Dir
}

// RulesFor resolves the configuration of a package.
func RulesFor(pkg *load.Package, configPath string) (*Rules, error) {
	return rulesFrom(pkg, pkg.Dir, configPath)
}

// rulesForPass resolves the configuration the analyzer applies to a pass:
// the search starts at the pass's first file.
func rulesForPass(pkg *load.Package, configPath string) (*Rules, error) {
	return rulesFrom(pkg, searchDir(pkg), configPath)
}

func rulesFrom(pkg *load.Package, dir, configPath string) (*Rules, error) {
	var sections []*FileSection
	if configPath != "" {
		abs, err := filepath.Abs(configPath)
		if err != nil {
			return nil, err
		}
		fs, err := readConfig(configPath, abs)
		if err != nil {
			return nil, err
		}
		sections = append(sections, fs)
	} else {
		root := ""
		if pkg.Module != nil {
			root = pkg.Module.Dir
		}
		for _, p := range FindChain(dir, root) {
			fs, err := readConfig(p, p)
			if err != nil {
				return nil, err
			}
			sections = append(sections, fs)
		}
	}
	return compose(sections), nil
}
