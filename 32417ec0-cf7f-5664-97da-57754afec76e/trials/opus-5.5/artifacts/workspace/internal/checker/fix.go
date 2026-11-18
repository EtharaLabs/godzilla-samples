package checker

import (
	"fmt"
	"go/format"
	"log"
	"maps"
	"os"
	"sort"

	"declscope/internal/diff"
)

// applyFixes applies the first fix of every diagnostic, skipping a fix that
// conflicts with one already accepted, then writes the files or, with
// printDiff, prints the combined patch.
func applyFixes(actions []*action, printDiff bool) error {
	type fixact struct {
		fix *SuggestedFix
		act *action
	}
	var fixes []*fixact
	for _, act := range actions {
		for _, diag := range act.diagnostics {
			for i := range diag.SuggestedFixes {
				fix := &diag.SuggestedFixes[i]
				if i == 0 {
					fixes = append(fixes, &fixact{fix, act})
				} else {
					log.Printf("%s: ignoring alternative fix %q", act.pkg.ID, fix.Message)
				}
			}
		}
	}

	baselineContent := make(map[string][]byte)
	getBaseline := func(filename string) ([]byte, error) {
		content, ok := baselineContent[filename]
		if !ok {
			var err error
			content, err = os.ReadFile(filename)
			if err != nil {
				return nil, err
			}
			baselineContent[filename] = content
		}
		return content, nil
	}

	accumulatedEdits := make(map[string][]diff.Edit)
	goodFixes := 0
fixloop:
	for _, fa := range fixes {
		fileEdits := make(map[string][]diff.Edit)
		fset := fa.act.pkg.Fset
		for _, edit := range fa.fix.TextEdits {
			file := fset.File(edit.Pos)
			baseline, err := getBaseline(file.Name())
			if err != nil {
				log.Printf("skipping fix to file %s: %v", file.Name(), err)
				continue fixloop
			}
			if file.Size() != len(baseline) {
				return fmt.Errorf("concurrent file modification detected in file %s (size changed from %d -> %d bytes); aborting fix",
					file.Name(), file.Size(), len(baseline))
			}
			end := edit.End
			if !end.IsValid() {
				end = edit.Pos
			}
			fileEdits[file.Name()] = append(fileEdits[file.Name()], diff.Edit{
				Start: file.Offset(edit.Pos),
				End:   file.Offset(end),
				New:   string(edit.NewText),
			})
		}
		after := make(map[string][]diff.Edit)
		for file, edits := range fileEdits {
			if prev := accumulatedEdits[file]; len(prev) > 0 {
				merged, ok := diff.Merge(prev, edits)
				if !ok {
					continue fixloop
				}
				edits = merged
			}
			after[file] = edits
		}
		goodFixes++
		maps.Copy(accumulatedEdits, after)
	}
	badFixes := len(fixes) - goodFixes

	var files []string
	for file := range accumulatedEdits {
		files = append(files, file)
	}
	sort.Strings(files)
	var filesUpdated, totalFiles int
	for _, file := range files {
		edits := accumulatedEdits[file]
		if len(edits) == 0 {
			continue
		}
		baseline := baselineContent[file]
		final, err := diff.ApplyBytes(baseline, edits)
		if err != nil {
			log.Fatalf("internal error in diff.ApplyBytes: %v", err)
		}
		if formatted, err := format.Source(final); err == nil {
			final = formatted
		}
		if printDiff {
			unified := diff.Unified(file+" (old)", file+" (new)", string(baseline), string(final))
			os.Stdout.WriteString(unified)
		} else {
			totalFiles++
			if err := os.WriteFile(file, final, 0644); err != nil {
				log.Println(err)
				continue
			}
			filesUpdated++
		}
	}

	if badFixes > 0 || filesUpdated < totalFiles {
		if printDiff {
			return fmt.Errorf("%d of %d fixes skipped (e.g. due to conflicts)", badFixes, len(fixes))
		}
		return fmt.Errorf("applied %d of %d fixes; %d files updated. (Re-run the command to apply more.)",
			goodFixes, len(fixes), filesUpdated)
	}
	return nil
}
