package skill

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
)

// state is where a skill directory stands against the embedded skills.
type state int

const (
	stateMissing  state = iota // nothing there
	stateUpToDate              // installed by this tool, current, untouched
	stateOutdated              // installed by an older build of this tool, untouched
	stateModified              // installed by this tool, then edited
	stateForeign               // not installed by this tool
	stateOrphaned              // installed by this tool, which no longer carries it
)

func (s state) String() string {
	return [...]string{"missing", "up-to-date", "outdated", "modified", "foreign", "orphaned"}[s]
}

// inspect reports the state of the skill directory dir, given the digest of
// the embedded skill of that name ("" for none).
func inspect(dir, current string) (state, error) {
	fi, err := os.Stat(dir)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return stateMissing, nil
		}
		return 0, err
	}
	if !fi.IsDir() {
		return stateForeign, nil
	}
	data, err := os.ReadFile(filepath.Join(dir, skillFile))
	if err != nil {
		return stateForeign, nil
	}
	meta, ok := parseMeta(data)
	if !ok || meta[keyBy] != toolName || meta[keyDigest] == "" {
		return stateForeign, nil
	}
	actual, err := digestFS(os.DirFS(dir))
	if err != nil {
		return stateForeign, nil
	}
	switch recorded := meta[keyDigest]; {
	case actual != recorded:
		return stateModified, nil
	case recorded == current:
		return stateUpToDate, nil
	default:
		return stateOutdated, nil
	}
}
