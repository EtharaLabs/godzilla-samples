// Package load loads Go packages through "go list", parses them and
// type-checks them, following the conventions of golang.org/x/tools/go/packages
// in LoadSyntax mode: initial packages are type-checked from source, and their
// dependencies are read from export data.
package load

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"unicode"
)

// Config controls loading.
type Config struct {
	Dir        string   // working directory of the go command; "" means the current one
	Env        []string // environment of the go command; nil means os.Environ()
	Tests      bool     // include test variants
	BuildFlags []string
	// Deps requests source loading of every dependency (LoadAllSyntax).
	Deps bool
	// NoTypes requests only metadata: no parsing and no type checking.
	NoTypes bool
}

// ErrorKind classifies an Error.
type ErrorKind int

const (
	UnknownError ErrorKind = iota
	ListError
	ParseError
	TypeError
)

// Error is an error encountered while loading a package.
type Error struct {
	Pos  string // "file:line:col" or "file:line" or "" or "-"
	Msg  string
	Kind ErrorKind
}

func (err Error) Error() string {
	pos := err.Pos
	if pos == "" {
		pos = "-"
	}
	return pos + ": " + err.Msg
}

// Module describes a module as reported by go list.
type Module struct {
	Path      string
	Version   string
	Replace   *Module
	Main      bool
	Indirect  bool
	Dir       string
	GoMod     string
	GoVersion string
	Error     *ModuleError
}

// ModuleError is a module loading error.
type ModuleError struct {
	Err string
}

type jsonPackageError struct {
	ImportStack []string
	Pos         string
	Err         string
}

type jsonPackage struct {
	ImportPath        string
	Dir               string
	Name              string
	Target            string
	Export            string
	GoFiles           []string
	CompiledGoFiles   []string
	IgnoredGoFiles    []string
	IgnoredOtherFiles []string
	EmbedPatterns     []string
	EmbedFiles        []string
	CFiles            []string
	CgoFiles          []string
	CXXFiles          []string
	MFiles            []string
	HFiles            []string
	FFiles            []string
	SFiles            []string
	SwigFiles         []string
	SwigCXXFiles      []string
	SysoFiles         []string
	Imports           []string
	ImportMap         map[string]string
	Deps              []string
	Module            *Module
	TestGoFiles       []string
	TestImports       []string
	XTestGoFiles      []string
	XTestImports      []string
	ForTest           string
	DepOnly           bool
	Standard          bool
	Error             *jsonPackageError
	DepsErrors        []*jsonPackageError
}

type driverResponse struct {
	Compiler  string
	Arch      string
	Roots     []string
	Packages  []*Package
	GoVersion int
}

type golistState struct {
	cfg       *Config
	goVersion int
	haveGoVer bool
	goVerErr  error
}

func (state *golistState) env() []string {
	env := state.cfg.Env
	if env == nil {
		env = os.Environ()
	}
	return env
}

// invoke runs the go command and returns stdout, stderr and the errors in
// the forms gocommand reports them: the friendly one carries stderr.
func (state *golistState) invoke(verb string, args ...string) (stdout, stderr *bytes.Buffer, friendlyErr, rawErr error) {
	goArgs := []string{verb}
	if verb != "env" && verb != "version" {
		goArgs = append(goArgs, args...)
	} else {
		goArgs = append(goArgs, args...)
	}
	cmd := exec.CommandContext(context.Background(), "go", goArgs...)
	stdout, stderr = new(bytes.Buffer), new(bytes.Buffer)
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	env := append([]string(nil), state.env()...)
	dir := state.cfg.Dir
	if dir != "" {
		cmd.Dir = dir
		env = append(env, "PWD="+dir)
	}
	cmd.Env = env
	rawErr = cmd.Run()
	if rawErr != nil {
		friendlyErr = rawErr
		var ee *exec.Error
		if errors.As(rawErr, &ee) && ee.Err == exec.ErrNotFound {
			friendlyErr = fmt.Errorf("go command required, not found: %v", ee)
		}
		friendlyErr = fmt.Errorf("err: %v: stderr: %s", friendlyErr, stderr)
	}
	return
}

func (state *golistState) getGoVersion() (int, error) {
	if state.haveGoVer {
		return state.goVersion, state.goVerErr
	}
	state.haveGoVer = true
	stdout, stderr, friendly, raw := state.invoke("list", "-e", "-f", "{{context.ReleaseTags}}", "--", "unsafe")
	if raw != nil {
		state.goVerErr = friendly
		return 0, friendly
	}
	tags := strings.TrimSpace(stdout.String())
	if len(tags) < 2 || tags[0] != '[' || tags[len(tags)-1] != ']' {
		state.goVerErr = fmt.Errorf("could not parse go version: stdout: %q, stderr: %q", stdout, stderr)
		return 0, state.goVerErr
	}
	fields := strings.Fields(tags[1 : len(tags)-1])
	for i := len(fields) - 1; i >= 0; i-- {
		var v int
		if _, err := fmt.Sscanf(fields[i], "go1.%d", &v); err == nil {
			state.goVersion = v
			return v, nil
		}
	}
	state.goVerErr = fmt.Errorf("no parseable ReleaseTags in %v", fields)
	return 0, state.goVerErr
}

// getSizes reports the compiler and GOARCH, as go/packages does.
func (state *golistState) getSizes() (compiler, arch string, err error) {
	stdout, stderr, friendly, raw := state.invoke("list", "-f", "{{context.GOARCH}} {{context.Compiler}}", "--", "unsafe")
	if raw != nil {
		msg := raw.Error()
		if friendly != nil {
			msg = friendly.Error()
		}
		if strings.Contains(msg, "cannot find main module") || strings.Contains(msg, "go.mod file not found") {
			envout, _, envFriendly, envErr := state.invoke("env", "GOARCH")
			if envErr != nil {
				return "", "", envFriendly
			}
			return "gc", strings.TrimSpace(envout.String()), nil
		}
		return "", "", friendly
	}
	fields := strings.Fields(stdout.String())
	if len(fields) < 2 {
		return "", "", fmt.Errorf("could not parse GOARCH and Go compiler in format \"<GOARCH> <compiler>\":\nstdout: <<%s>>\nstderr: <<%s>>", stdout.String(), stderr.String())
	}
	return fields[1], fields[0], nil
}

func (state *golistState) usesExportData() bool {
	return !state.cfg.Deps && !state.cfg.NoTypes
}

func (state *golistState) listArgs(words []string, goVersion int) []string {
	cfg := state.cfg
	fields := []string{"Name", "ImportPath", "Error", "Dir", "GoFiles", "IgnoredGoFiles", "IgnoredOtherFiles",
		"CFiles", "CgoFiles", "CXXFiles", "MFiles", "HFiles", "FFiles", "SFiles", "SwigFiles", "SwigCXXFiles", "SysoFiles"}
	if cfg.Tests {
		fields = append(fields, "TestGoFiles", "XTestGoFiles")
	}
	fields = append(fields, "CompiledGoFiles", "Export", "DepOnly", "Imports", "ImportMap")
	if cfg.Tests {
		fields = append(fields, "TestImports", "XTestImports")
	}
	fields = append(fields, "ForTest", "DepsErrors", "Module", "EmbedFiles")
	compiled := !cfg.NoTypes
	args := []string{
		"-e", "-json=" + strings.Join(fields, ","),
		fmt.Sprintf("-compiled=%t", compiled),
		fmt.Sprintf("-test=%t", cfg.Tests),
		fmt.Sprintf("-export=%t", state.usesExportData()),
		"-deps=true",
		"-find=false",
	}
	if goVersion >= 21 {
		args = append(args, "-pgo=off")
	}
	args = append(args, cfg.BuildFlags...)
	args = append(args, "--")
	args = append(args, words...)
	return args
}

// invokeList runs go list with the go/packages error conventions.
func (state *golistState) invokeList(args []string) (*bytes.Buffer, error) {
	stdout, stderr, friendlyErr, err := state.invoke("list", args...)
	if err == nil {
		return stdout, nil
	}
	var ee *exec.Error
	if errors.As(err, &ee) && ee.Err == exec.ErrNotFound {
		return nil, fmt.Errorf("'go list' driver requires 'go', but %s", exec.ErrNotFound)
	}
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		return nil, fmt.Errorf("couldn't run 'go': %w", err)
	}
	errStr := stderr.String()
	if strings.Contains(errStr, "flag provided but not defined") {
		return nil, fmt.Errorf("unsupported version of go: %s: %s", exitErr, stderr)
	}
	if len(errStr) > 0 && strings.Contains(errStr, "unexpected directory layout") {
		return nil, friendlyErr
	}
	if len(errStr) > 0 && strings.Contains(errStr, "go: no such tool") {
		return nil, friendlyErr
	}
	isPkgPathRune := func(r rune) bool {
		return unicode.IsOneOf([]*unicode.RangeTable{unicode.L, unicode.M, unicode.N, unicode.P, unicode.S}, r) &&
			!strings.ContainsRune("!\"#$%&'()*,:;<=>?[\\]^`{|}�", r)
	}
	msg := errStr
	for strings.HasPrefix(msg, "go: downloading") {
		msg = msg[strings.IndexRune(msg, '\n')+1:]
	}
	if len(errStr) > 0 && strings.HasPrefix(errStr, "# ") {
		msg := msg[len("# "):]
		if strings.HasPrefix(strings.TrimLeftFunc(msg, isPkgPathRune), "\n") {
			return stdout, nil
		}
		if strings.HasPrefix(msg, "pkg-config") {
			return stdout, nil
		}
	}
	synth := func(importPath, errText string) *bytes.Buffer {
		return bytes.NewBufferString(fmt.Sprintf(`{"ImportPath": %q,"Incomplete": true,"Error": {"Err": %q}}`, importPath, errText))
	}
	if len(errStr) > 0 && strings.Contains(errStr, "named files must be .go files") {
		return synth("command-line-arguments", strings.Trim(errStr, "\n")), nil
	}
	if len(errStr) > 0 && strings.Contains(errStr, "named files must all be in one directory") {
		return synth("command-line-arguments", strings.Trim(errStr, "\n")), nil
	}
	const noSuchDirectory = "no such directory"
	if len(errStr) > 0 && strings.Contains(errStr, noSuchDirectory) {
		abspath := strings.TrimSpace(errStr[strings.Index(errStr, noSuchDirectory)+len(noSuchDirectory):])
		return synth(abspath, strings.Trim(errStr, "\n")), nil
	}
	if len(errStr) > 0 && strings.Contains(errStr, "no such file or directory") {
		return synth("command-line-arguments", strings.Trim(errStr, "\n")), nil
	}
	if len(errStr) > 0 && strings.Contains(errStr, "outside available modules") {
		return synth("command-line-arguments", strings.Trim(errStr, "\n")), nil
	}
	if len(errStr) > 0 && strings.Contains(errStr, "outside module root") {
		return synth("command-line-arguments", strings.Trim(errStr, "\n")), nil
	}
	if len(errStr) > 0 && strings.Contains(errStr, "no Go files in") {
		if len(stdout.String()) > 0 {
			return stdout, nil
		}
		var importPath string
		colon := strings.Index(errStr, ":")
		if colon > 0 && strings.HasPrefix(errStr, "go build ") {
			importPath = errStr[len("go build "):colon]
		}
		return synth(importPath, strings.Trim(errStr, "\n")), nil
	}
	if !state.usesExportData() && !containsGoFile(args) {
		return nil, friendlyErr
	}
	return stdout, nil
}

func containsGoFile(s []string) bool {
	for _, f := range s {
		if strings.HasSuffix(f, ".go") {
			return true
		}
	}
	return false
}

func absJoin(dir string, fileses ...[]string) (res []string) {
	for _, files := range fileses {
		for _, file := range files {
			if !filepath.IsAbs(file) {
				file = filepath.Join(dir, file)
			}
			res = append(res, file)
		}
	}
	return res
}

func otherFiles(p *jsonPackage) [][]string {
	return [][]string{p.CFiles, p.CXXFiles, p.MFiles, p.HFiles, p.FFiles, p.SFiles, p.SwigFiles, p.SwigCXXFiles, p.SysoFiles}
}

func (state *golistState) createDriverResponse(words ...string) (*driverResponse, error) {
	goVersion, err := state.getGoVersion()
	if err != nil {
		return nil, err
	}
	buf, err := state.invokeList(state.listArgs(words, goVersion))
	if err != nil {
		return nil, err
	}

	seen := make(map[string]*jsonPackage)
	pkgs := make(map[string]*Package)
	additionalErrors := make(map[string][]Error)
	response := &driverResponse{GoVersion: goVersion}
	for dec := json.NewDecoder(buf); dec.More(); {
		p := new(jsonPackage)
		if err := dec.Decode(p); err != nil {
			return nil, fmt.Errorf("JSON decoding failed: %v", err)
		}
		if p.ImportPath == "" {
			if p.Error != nil {
				return nil, Error{Pos: p.Error.Pos, Msg: p.Error.Err}
			}
			return nil, fmt.Errorf("package missing import path: %+v", p)
		}
		if filepath.IsAbs(p.ImportPath) && p.Error != nil {
			if pkgPath, ok := state.getPkgPath(p.ImportPath); ok {
				p.ImportPath = pkgPath
			}
		}
		if old, found := seen[p.ImportPath]; found {
			if old.Error == nil && p.Error == nil {
				continue
			}
			if old.Error != nil {
				var errkind string
				if strings.Contains(old.Error.Err, "not an importable package") {
					errkind = "not an importable package"
				} else if strings.Contains(old.Error.Err, "use of internal package") && strings.Contains(old.Error.Err, "not allowed") {
					errkind = "use of internal package not allowed"
				}
				if errkind != "" {
					if len(old.Error.ImportStack) < 1 {
						return nil, fmt.Errorf(`internal error: go list gave a %q error with empty import stack`, errkind)
					}
					importingPkg := old.Error.ImportStack[len(old.Error.ImportStack)-1]
					if importingPkg == old.ImportPath {
						if len(old.Error.ImportStack) < 2 {
							return nil, fmt.Errorf(`internal error: go list gave a %q error with an import stack without importing package`, errkind)
						}
						importingPkg = old.Error.ImportStack[len(old.Error.ImportStack)-2]
					}
					additionalErrors[importingPkg] = append(additionalErrors[importingPkg], Error{
						Pos:  old.Error.Pos,
						Msg:  old.Error.Err,
						Kind: ListError,
					})
				}
			}
			if old.Error == nil {
				continue
			}
		}
		seen[p.ImportPath] = p

		pkg := &Package{
			Name:            p.Name,
			ID:              p.ImportPath,
			Dir:             p.Dir,
			GoFiles:         absJoin(p.Dir, p.GoFiles, p.CgoFiles),
			CompiledGoFiles: absJoin(p.Dir, p.CompiledGoFiles),
			OtherFiles:      absJoin(p.Dir, otherFiles(p)...),
			EmbedFiles:      absJoin(p.Dir, p.EmbedFiles),
			IgnoredFiles:    absJoin(p.Dir, p.IgnoredGoFiles, p.IgnoredOtherFiles),
			ForTest:         p.ForTest,
			Module:          p.Module,
			DepOnly:         p.DepOnly,
			Raw:             p,
		}
		if len(pkg.CompiledGoFiles) > 0 {
			out := pkg.CompiledGoFiles[:0]
			for _, f := range pkg.CompiledGoFiles {
				if ext := filepath.Ext(f); ext != ".go" && ext != "" {
					continue
				}
				out = append(out, f)
			}
			pkg.CompiledGoFiles = out
		}
		if i := strings.IndexByte(pkg.ID, ' '); i >= 0 {
			pkg.PkgPath = pkg.ID[:i]
		} else {
			pkg.PkgPath = pkg.ID
		}
		if pkg.PkgPath == "unsafe" {
			pkg.CompiledGoFiles = nil
		} else if len(pkg.CompiledGoFiles) == 0 {
			pkg.CompiledGoFiles = pkg.GoFiles
		}
		if p.Export != "" && !filepath.IsAbs(p.Export) {
			pkg.ExportFile = filepath.Join(p.Dir, p.Export)
		} else {
			pkg.ExportFile = p.Export
		}

		ids := make(map[string]bool)
		for _, id := range p.Imports {
			ids[id] = true
		}
		pkg.Imports = make(map[string]*Package)
		for path, id := range p.ImportMap {
			pkg.Imports[path] = &Package{ID: id}
			delete(ids, id)
		}
		for id := range ids {
			if id == "C" {
				continue
			}
			pkg.Imports[id] = &Package{ID: id}
		}
		if !p.DepOnly {
			response.Roots = append(response.Roots, pkg.ID)
		}

		if err := p.Error; err != nil && state.shouldAddFilenameFromError(p) {
			addFilenameFromPos := func(pos string) bool {
				split := strings.Split(pos, ":")
				if len(split) < 1 {
					return false
				}
				filename := strings.TrimSpace(split[0])
				if filename == "" {
					return false
				}
				if !filepath.IsAbs(filename) {
					filename = filepath.Join(state.dir(), filename)
				}
				info, _ := os.Stat(filename)
				if info == nil {
					return false
				}
				pkg.CompiledGoFiles = append(pkg.CompiledGoFiles, filename)
				pkg.GoFiles = append(pkg.GoFiles, filename)
				return true
			}
			found := addFilenameFromPos(err.Pos)
			if !found {
				addFilenameFromPos(err.Err)
			}
		}

		if p.Error != nil {
			msg := strings.TrimSpace(p.Error.Err)
			if msg == "import cycle not allowed" && len(p.Error.ImportStack) != 0 {
				msg += fmt.Sprintf(": import stack: %v", p.Error.ImportStack)
			}
			pkg.Errors = append(pkg.Errors, Error{
				Pos:  p.Error.Pos,
				Msg:  msg,
				Kind: ListError,
			})
		}
		pkgs[pkg.ID] = pkg
	}

	for id, errs := range additionalErrors {
		if p, ok := pkgs[id]; ok {
			p.Errors = append(p.Errors, errs...)
		}
	}
	for _, pkg := range pkgs {
		response.Packages = append(response.Packages, pkg)
	}
	sort.Slice(response.Packages, func(i, j int) bool { return response.Packages[i].ID < response.Packages[j].ID })
	return response, nil
}

func (state *golistState) dir() string {
	if state.cfg.Dir != "" {
		return state.cfg.Dir
	}
	wd, _ := os.Getwd()
	return wd
}

func (state *golistState) shouldAddFilenameFromError(p *jsonPackage) bool {
	if len(p.GoFiles) > 0 || len(p.CompiledGoFiles) > 0 {
		return false
	}
	return len(p.Error.ImportStack) == 0 || p.Error.ImportStack[len(p.Error.ImportStack)-1] == p.ImportPath
}

// getPkgPath finds the package path of a directory if it's relative to a
// root directory (the main module's).
func (state *golistState) getPkgPath(dir string) (string, bool) {
	stdout, _, _, err := state.invoke("list", "-m", "-json")
	if err != nil {
		return "", false
	}
	for dec := json.NewDecoder(stdout); dec.More(); {
		var m Module
		if dec.Decode(&m) != nil {
			return "", false
		}
		if m.Dir == "" {
			continue
		}
		rel, err := filepath.Rel(m.Dir, dir)
		if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			continue
		}
		if rel == "." {
			return m.Path, true
		}
		return m.Path + "/" + filepath.ToSlash(rel), true
	}
	return "", false
}

// runContainsQueries resolves file= patterns.
func (state *golistState) runContainsQueries(response *driverResponse, seenIDs map[string]bool, queries []string) error {
	for _, query := range queries {
		fdir := filepath.Dir(query)
		pattern, err := filepath.Abs(fdir)
		if err != nil {
			return fmt.Errorf("could not determine absolute path of file= query path %q: %v", query, err)
		}
		dirResponse, err := state.createDriverResponse(pattern)
		if err != nil || len(dirResponse.Packages) == 0 || len(dirResponse.Packages) == 1 && len(dirResponse.Packages[0].GoFiles) == 0 &&
			len(dirResponse.Packages[0].Errors) == 1 {
			var queryErr error
			if dirResponse, queryErr = state.adhocPackage(pattern, query); queryErr != nil {
				return err
			}
		}
		isRoot := make(map[string]bool, len(dirResponse.Roots))
		for _, root := range dirResponse.Roots {
			isRoot[root] = true
		}
		for _, pkg := range dirResponse.Packages {
			if !seenIDs[pkg.ID] {
				seenIDs[pkg.ID] = true
				response.Packages = append(response.Packages, pkg)
			}
			if !isRoot[pkg.ID] {
				continue
			}
			for _, pkgFile := range pkg.GoFiles {
				if filepath.Base(query) == filepath.Base(pkgFile) {
					if !containsString(response.Roots, pkg.ID) {
						response.Roots = append(response.Roots, pkg.ID)
					}
					break
				}
			}
		}
	}
	return nil
}

func (state *golistState) adhocPackage(pattern, query string) (*driverResponse, error) {
	response, err := state.createDriverResponse(query)
	if err != nil {
		return nil, err
	}
	if len(response.Packages) == 0 {
		response.Packages = append(response.Packages, &Package{
			ID:              "command-line-arguments",
			PkgPath:         query,
			GoFiles:         []string{query},
			CompiledGoFiles: []string{query},
			Imports:         make(map[string]*Package),
		})
		response.Roots = append(response.Roots, "command-line-arguments")
	}
	if len(response.Packages) == 1 {
		if response.Packages[0].Errors == nil {
			response.Packages[0].Errors = []Error{}
		}
	}
	return response, nil
}

func containsString(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// driver resolves patterns into a driver response.
func (state *golistState) driver(patterns []string) (*driverResponse, error) {
	var containFiles []string
	restPatterns := make([]string, 0, len(patterns))
extractQueries:
	for _, pattern := range patterns {
		eqidx := strings.Index(pattern, "=")
		if eqidx < 0 {
			restPatterns = append(restPatterns, pattern)
		} else {
			query, value := pattern[:eqidx], pattern[eqidx+len("="):]
			switch query {
			case "file":
				containFiles = append(containFiles, value)
			case "pattern":
				restPatterns = append(restPatterns, value)
			case "":
				restPatterns = append(restPatterns, pattern)
			default:
				for _, r := range query {
					if r < 'a' || r > 'z' {
						restPatterns = append(restPatterns, pattern)
						continue extractQueries
					}
				}
				return nil, fmt.Errorf("invalid query type %q in query pattern %q", query, pattern)
			}
		}
	}

	var compiler, arch string
	var sizesErr error
	if !state.cfg.NoTypes {
		compiler, arch, sizesErr = state.getSizes()
	}

	response := &driverResponse{}
	seenIDs := make(map[string]bool)
	if len(restPatterns) > 0 || len(patterns) == 0 {
		dr, err := state.createDriverResponse(restPatterns...)
		if err != nil {
			if sizesErr != nil {
				return nil, sizesErr
			}
			return nil, err
		}
		response.GoVersion = dr.GoVersion
		for _, pkg := range dr.Packages {
			seenIDs[pkg.ID] = true
			response.Packages = append(response.Packages, pkg)
		}
		response.Roots = append(response.Roots, dr.Roots...)
	}
	if len(containFiles) != 0 {
		if err := state.runContainsQueries(response, seenIDs, containFiles); err != nil {
			if sizesErr != nil {
				return nil, sizesErr
			}
			return nil, err
		}
		if v, err := state.getGoVersion(); err == nil {
			response.GoVersion = v
		}
	}
	if sizesErr != nil {
		return nil, sizesErr
	}
	response.Compiler, response.Arch = compiler, arch
	return response, nil
}
