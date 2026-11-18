package skill

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
)

// skillFile is the file every skill directory has at its root.
const skillFile = "SKILL.md"

// junkFiles are written by file managers, not by people, so a skill
// directory holding them is still the one that was installed.
var junkFiles = map[string]bool{".DS_Store": true, "Thumbs.db": true, "desktop.ini": true}

// digestFS hashes the regular files of a skill directory in walk order. Each
// file contributes its slash-separated path, its length and its content,
// with SKILL.md taken without its install metadata. Anything other than a
// directory or a regular file makes the directory one the digest cannot
// describe.
func digestFS(fsys fs.FS) (string, error) {
	h := sha256.New()
	err := fs.WalkDir(fsys, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || junkFiles[d.Name()] {
			return nil
		}
		if !d.Type().IsRegular() {
			return fmt.Errorf("%s: not a regular file", p)
		}
		data, err := fs.ReadFile(fsys, p)
		if err != nil {
			return err
		}
		if p == skillFile {
			data = normalize(data)
		}
		fmt.Fprintf(h, "%s\x00%d\x00", p, len(data))
		h.Write(data)
		return nil
	})
	if err != nil {
		return "", err
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil)), nil
}
