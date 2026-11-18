package skill

import (
	"io/fs"
	"testing"
	"testing/fstest"
)

func TestEmbeddedDigests(t *testing.T) {
	want := map[string]string{
		"declscope-adoption":  "sha256:95b89ae2e7904a1bd4e000c3cb254645ae22dc91c52f1bf12a04d518dc97ea8e",
		"declscope-authoring": "sha256:c55e34c6118d518c9fc7807b58108d9eab6f0510ac604f2b48de075dc8f5bd11",
	}
	if len(embedded) != len(want) {
		t.Fatalf("got %d embedded skills, want %d", len(embedded), len(want))
	}
	for _, s := range embedded {
		if s.digest != want[s.name] {
			t.Errorf("%s: digest %s, want %s", s.name, s.digest, want[s.name])
		}
	}
}

func TestNormalize(t *testing.T) {
	tests := []struct{ in, want string }{
		{"---\nname: x\nx-embedded-by: declscope\nx-embedded-at: \"t\"\n---\nbody\n", "---\nname: x\n---\nbody\n"},
		{"---\r\nname: x\r\nx-embedded-by : declscope\r\n---\r\nbody\r\n", "---\r\nname: x\r\n---\r\nbody\r\n"},
		{"---\nx-embedded-by: declscope\nx-embedded-digest: d\n---\n\nbody\n", "\nbody\n"},
		{"\xef\xbb\xbf---\nx-embedded-by: declscope\n---\nbody\n", "\xef\xbb\xbfbody\n"},
		{"---\nname: x\n x-embedded-at: 1\nx-embedded-foo: 1\n---\n", "---\nname: x\n x-embedded-at: 1\nx-embedded-foo: 1\n---\n"},
		{"---\nname: x\nx-embedded-by: declscope\n", "---\nname: x\nx-embedded-by: declscope\n"},
	}
	for _, tt := range tests {
		if got := string(normalize([]byte(tt.in))); got != tt.want {
			t.Errorf("normalize(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}

func TestDigestSkipsJunkAndRendersRoundTrip(t *testing.T) {
	s := embedded[0]
	data, err := fs.ReadFile(s.files, skillFile)
	if err != nil {
		t.Fatal(err)
	}
	installed := render(data, [][2]string{{keyBy, toolName}, {keyDigest, `"` + s.digest + `"`}})
	fsys := fstest.MapFS{
		skillFile:       {Data: installed},
		".DS_Store":     {Data: []byte("junk")},
		"sub/Thumbs.db": {Data: []byte("junk")},
	}
	got, err := digestFS(fsys)
	if err != nil {
		t.Fatal(err)
	}
	if got != s.digest {
		t.Errorf("digest of installed copy = %s, want %s", got, s.digest)
	}
	meta, ok := parseMeta(installed)
	if !ok || meta[keyBy] != toolName || meta[keyDigest] != s.digest {
		t.Errorf("parseMeta(installed) = %v, %v", meta, ok)
	}
}
