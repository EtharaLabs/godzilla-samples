// Package diff computes edits between texts, applies and merges them, and
// renders unified diffs.
package diff

import (
	"fmt"
	"slices"
	"sort"
	"strings"
	"unicode/utf8"
)

// An Edit replaces src[Start:End] by New.
type Edit struct {
	Start, End int
	New        string
}

// Strings computes the edits that turn before into after.
// The edits respect rune boundaries.
func Strings(before, after string) []Edit {
	if before == after {
		return nil
	}
	if isASCII(before) && isASCII(after) {
		a, b := []byte(before), []byte(after)
		diffs := lcsDiffs(bytesSeqs{a, b})
		res := make([]Edit, len(diffs))
		for i, d := range diffs {
			res[i] = Edit{d.Start, d.End, string(b[d.ReplStart:d.ReplEnd])}
		}
		return res
	}
	a, b := []rune(before), []rune(after)
	diffs := lcsDiffs(runesSeqs{a, b})
	res := make([]Edit, len(diffs))
	lastEnd := 0
	utf8Len := 0
	for i, d := range diffs {
		utf8Len += runesLen(a[lastEnd:d.Start])
		start := utf8Len
		utf8Len += runesLen(a[d.Start:d.End])
		res[i] = Edit{start, utf8Len, string(b[d.ReplStart:d.ReplEnd])}
		lastEnd = d.End
	}
	return res
}

// Lines computes the edits that turn before into after, a whole line at a
// time.
func Lines(before, after string) []Edit {
	if before == after {
		return nil
	}
	a, offsets := linesOf(before)
	b, _ := linesOf(after)
	diffs := lcsDiffs(linesSeqs{a, b})
	res := make([]Edit, len(diffs))
	for i, d := range diffs {
		res[i] = Edit{
			Start: offsets[d.Start],
			End:   offsets[d.End],
			New:   strings.Join(b[d.ReplStart:d.ReplEnd], ""),
		}
	}
	return res
}

// linesOf splits text into lines that keep their newlines, with the offset
// of the start of each line and of the end of the text.
func linesOf(text string) ([]string, []int) {
	var lines []string
	offsets := []int{0}
	for text != "" {
		i := strings.IndexByte(text, '\n') + 1
		if i == 0 {
			i = len(text)
		}
		lines = append(lines, text[:i])
		offsets = append(offsets, offsets[len(offsets)-1]+i)
		text = text[i:]
	}
	return lines, offsets
}

func runesLen(runes []rune) (n int) {
	for _, r := range runes {
		n += utf8.RuneLen(r)
	}
	return n
}

func isASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= utf8.RuneSelf {
			return false
		}
	}
	return true
}

type editsSort []Edit

func (a editsSort) Len() int { return len(a) }
func (a editsSort) Less(i, j int) bool {
	if a[i].Start != a[j].Start {
		return a[i].Start < a[j].Start
	}
	return a[i].End < a[j].End
}
func (a editsSort) Swap(i, j int) { a[i], a[j] = a[j], a[i] }

// SortEdits orders edits by (start, end), stably.
func SortEdits(edits []Edit) { sort.Stable(editsSort(edits)) }

func validate(src string, edits []Edit) ([]Edit, int, error) {
	if !sort.IsSorted(editsSort(edits)) {
		edits = slices.Clone(edits)
		SortEdits(edits)
	}
	size := len(src)
	lastEnd := 0
	for _, edit := range edits {
		if !(0 <= edit.Start && edit.Start <= edit.End && edit.End <= len(src)) {
			return nil, 0, fmt.Errorf("diff has out-of-bounds edits")
		}
		if edit.Start < lastEnd {
			return nil, 0, fmt.Errorf("diff has overlapping edits")
		}
		size += len(edit.New) + edit.Start - edit.End
		lastEnd = edit.End
	}
	return edits, size, nil
}

// Apply applies edits to src.
func Apply(src string, edits []Edit) (string, error) {
	edits, size, err := validate(src, edits)
	if err != nil {
		return "", err
	}
	out := make([]byte, 0, size)
	lastEnd := 0
	for _, edit := range edits {
		if lastEnd < edit.Start {
			out = append(out, src[lastEnd:edit.Start]...)
		}
		out = append(out, edit.New...)
		lastEnd = edit.End
	}
	out = append(out, src[lastEnd:]...)
	return string(out), nil
}

// ApplyBytes is Apply for byte slices.
func ApplyBytes(src []byte, edits []Edit) ([]byte, error) {
	res, err := Apply(string(src), edits)
	return []byte(res), err
}

// Merge merges two valid, ordered lists of edits. It reports false on a
// conflict. Identical edits are coalesced.
func Merge(x, y []Edit) ([]Edit, bool) {
	x = slices.Clone(x)
	y = slices.Clone(y)
	var merged []Edit
	add := func(edit Edit) { merged = append(merged, edit) }
	var xi, yi int
	for xi < len(x) && yi < len(y) {
		px := &x[xi]
		py := &y[yi]
		if *px == *py {
			add(*px)
			xi++
			yi++
		} else if px.End <= py.Start {
			add(*px)
			xi++
		} else if py.End <= px.Start {
			add(*py)
			yi++
		} else if px.Start < py.Start {
			add(Edit{px.Start, py.Start, ""})
			px.Start = py.Start
		} else if py.Start < px.Start {
			add(Edit{py.Start, px.Start, ""})
			py.Start = px.Start
		} else {
			return nil, false
		}
	}
	for ; xi < len(x); xi++ {
		add(x[xi])
	}
	for ; yi < len(y); yi++ {
		add(y[yi])
	}
	return merged, true
}

// lineEdits expands and merges edits so that each replaces whole lines.
func lineEdits(src string, edits []Edit) ([]Edit, error) {
	edits, _, err := validate(src, edits)
	if err != nil {
		return nil, err
	}
	for _, edit := range edits {
		if edit.Start >= len(src) ||
			edit.Start > 0 && src[edit.Start-1] != '\n' ||
			edit.End > 0 && src[edit.End-1] != '\n' ||
			edit.New != "" && edit.New[len(edit.New)-1] != '\n' {
			goto expand
		}
	}
	return edits, nil

expand:
	if len(edits) == 0 {
		return edits, nil
	}
	expanded := make([]Edit, 0, len(edits))
	prev := edits[0]
	for _, edit := range edits[1:] {
		between := src[prev.End:edit.Start]
		if !strings.Contains(between, "\n") {
			prev.New += between + edit.New
			prev.End = edit.End
		} else {
			expanded = append(expanded, expandEdit(prev, src))
			prev = edit
		}
	}
	return append(expanded, expandEdit(prev, src)), nil
}

func expandEdit(edit Edit, src string) Edit {
	start := edit.Start
	if delta := start - 1 - strings.LastIndex(src[:start], "\n"); delta > 0 {
		edit.Start -= delta
		edit.New = src[start-delta:start] + edit.New
	}
	end := edit.End
	if end > 0 && src[end-1] != '\n' ||
		edit.New != "" && edit.New[len(edit.New)-1] != '\n' {
		if nl := strings.IndexByte(src[end:], '\n'); nl < 0 {
			edit.End = len(src)
		} else {
			edit.End = end + nl + 1
		}
	}
	edit.New += src[end:edit.End]
	return edit
}

const defaultContextLines = 3

// Unified returns a unified diff of old and new, labelled with the two names.
func Unified(oldLabel, newLabel, old, new string) string {
	edits := Lines(old, new)
	u, err := toUnified(oldLabel, newLabel, old, edits, defaultContextLines)
	if err != nil {
		panic(fmt.Sprintf("internal error in diff.Unified: %v", err))
	}
	return u.String()
}

type opKind int

const (
	opDelete opKind = iota
	opInsert
	opEqual
)

type line struct {
	kind    opKind
	content string
}

type hunk struct {
	fromLine int
	toLine   int
	lines    []line
}

type unified struct {
	from, to string
	hunks    []*hunk
}

func splitLines(text string) []string {
	lines := strings.SplitAfter(text, "\n")
	if lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	return lines
}

func addEqualLines(h *hunk, lines []string, start, end int) int {
	delta := 0
	for i := start; i < end; i++ {
		if i < 0 {
			continue
		}
		if i >= len(lines) {
			return delta
		}
		h.lines = append(h.lines, line{kind: opEqual, content: lines[i]})
		delta++
	}
	return delta
}

func toUnified(fromName, toName string, content string, edits []Edit, contextLines int) (unified, error) {
	gap := contextLines * 2
	u := unified{from: fromName, to: toName}
	if len(edits) == 0 {
		return u, nil
	}
	var err error
	edits, err = lineEdits(content, edits)
	if err != nil {
		return u, err
	}
	lines := splitLines(content)
	var h *hunk
	last := 0
	toLine := 0
	for _, edit := range edits {
		start := strings.Count(content[:edit.Start], "\n")
		end := strings.Count(content[:edit.End], "\n")
		if edit.End == len(content) && len(content) > 0 && content[len(content)-1] != '\n' {
			end++
		}
		switch {
		case h != nil && start == last:
		case h != nil && start <= last+gap:
			addEqualLines(h, lines, last, start)
		default:
			if h != nil {
				addEqualLines(h, lines, last, last+contextLines)
				u.hunks = append(u.hunks, h)
			}
			toLine += start - last
			h = &hunk{fromLine: start + 1, toLine: toLine + 1}
			delta := addEqualLines(h, lines, start-contextLines, start)
			h.fromLine -= delta
			h.toLine -= delta
		}
		last = start
		for i := start; i < end; i++ {
			h.lines = append(h.lines, line{kind: opDelete, content: lines[i]})
			last++
		}
		if edit.New != "" {
			for _, content := range splitLines(edit.New) {
				h.lines = append(h.lines, line{kind: opInsert, content: content})
				toLine++
			}
		}
	}
	if h != nil {
		addEqualLines(h, lines, last, last+contextLines)
		u.hunks = append(u.hunks, h)
	}
	return u, nil
}

func (u unified) String() string {
	if len(u.hunks) == 0 {
		return ""
	}
	b := new(strings.Builder)
	fmt.Fprintf(b, "--- %s\n", u.from)
	fmt.Fprintf(b, "+++ %s\n", u.to)
	for _, h := range u.hunks {
		fromCount, toCount := 0, 0
		for _, l := range h.lines {
			switch l.kind {
			case opDelete:
				fromCount++
			case opInsert:
				toCount++
			default:
				fromCount++
				toCount++
			}
		}
		fmt.Fprint(b, "@@")
		if fromCount > 1 {
			fmt.Fprintf(b, " -%d,%d", h.fromLine, fromCount)
		} else if h.fromLine == 1 && fromCount == 0 {
			fmt.Fprintf(b, " -0,0")
		} else {
			fmt.Fprintf(b, " -%d", h.fromLine)
		}
		if toCount > 1 {
			fmt.Fprintf(b, " +%d,%d", h.toLine, toCount)
		} else if h.toLine == 1 && toCount == 0 {
			fmt.Fprintf(b, " +0,0")
		} else {
			fmt.Fprintf(b, " +%d", h.toLine)
		}
		fmt.Fprint(b, " @@\n")
		for _, l := range h.lines {
			switch l.kind {
			case opDelete:
				fmt.Fprintf(b, "-%s", l.content)
			case opInsert:
				fmt.Fprintf(b, "+%s", l.content)
			default:
				fmt.Fprintf(b, " %s", l.content)
			}
			if !strings.HasSuffix(l.content, "\n") {
				fmt.Fprintf(b, "\n\\ No newline at end of file\n")
			}
		}
	}
	return b.String()
}
