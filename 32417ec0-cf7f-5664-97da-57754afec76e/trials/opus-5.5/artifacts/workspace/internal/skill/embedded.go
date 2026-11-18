package skill

import (
	"embed"
	"io/fs"
	"path"
)

// skillsFS holds one directory per skill, each with a SKILL.md at its root.
//
//go:embed skills
var skillsFS embed.FS

// embeddedSkill is a skill carried by the binary.
type embeddedSkill struct {
	name        string
	description string
	files       fs.FS  // rooted at the skill's directory
	digest      string // digest of files, as recorded by an install
}

// embedded lists the skills carried by the binary, sorted by name.
var embedded = loadEmbedded()

func loadEmbedded() []*embeddedSkill {
	entries, err := fs.ReadDir(skillsFS, "skills")
	if err != nil {
		panic(err)
	}
	var skills []*embeddedSkill
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		sub, err := fs.Sub(skillsFS, path.Join("skills", e.Name()))
		if err != nil {
			panic(err)
		}
		data, err := fs.ReadFile(sub, skillFile)
		if err != nil {
			panic(err)
		}
		digest, err := digestFS(sub)
		if err != nil {
			panic(err)
		}
		meta, _ := parseMeta(data)
		skills = append(skills, &embeddedSkill{
			name:        e.Name(),
			description: meta["description"],
			files:       sub,
			digest:      digest,
		})
	}
	return skills
}

// lookupSkill returns the embedded skill with the given name, or nil.
func lookupSkill(name string) *embeddedSkill {
	for _, s := range embedded {
		if s.name == name {
			return s
		}
	}
	return nil
}

// summary shortens a description to the width the listings show.
func summary(desc string) string {
	const width = 100
	r := []rune(desc)
	if len(r) <= width {
		return desc
	}
	return string(r[:width-3]) + "..."
}
