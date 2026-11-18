package diff

import (
	"fmt"
	"sort"
)

// This file computes a longest common subsequence of two sequences with a
// two-sided Myers search that gives up after a fixed number of differences.
// Its choices among equally long subsequences determine the shape of every
// printed diff, so the search order below is deliberate.

// lcsDiff is a replacement of a[Start:End] by b[ReplStart:ReplEnd].
type lcsDiff struct {
	Start, End         int
	ReplStart, ReplEnd int
}

// A diag is a run where a[X+i] == b[Y+i] for 0 <= i < Len.
type diag struct {
	X, Y int
	Len  int
}

type lcs []diag

func (l lcs) sort() lcs {
	sort.Slice(l, func(i, j int) bool {
		if l[i].X != l[j].X {
			return l[i].X < l[j].X
		}
		return l[i].Len > l[j].Len
	})
	return l
}

// fix repairs an lcs whose parts may overlap, which happens when the
// two-sided search stops early.
func (l lcs) fix() lcs {
	if len(l) == 0 {
		return nil
	}
	sort.Slice(l, func(i, j int) bool { return l[i].Len > l[j].Len })
	tmp := make(lcs, 0, len(l))
	tmp = append(tmp, l[0])
	for i := 1; i < len(l); i++ {
		var dir direction
		nxt := l[i]
		for _, in := range tmp {
			if dir, nxt = overlap(in, nxt); dir == empty || dir == bad {
				break
			}
		}
		if nxt.Len > 0 && dir != bad {
			tmp = append(tmp, nxt)
		}
	}
	tmp.sort()
	return tmp
}

type direction int

const (
	empty direction = iota
	leftdown
	rightup
	bad
)

// overlap trims prop so that it does not overlap exist.
func overlap(exist, prop diag) (direction, diag) {
	if prop.X <= exist.X && exist.X < prop.X+prop.Len {
		delta := prop.X + prop.Len - exist.X
		prop.Len -= delta
		if prop.Len <= 0 {
			return empty, prop
		}
	}
	if exist.X <= prop.X && prop.X < exist.X+exist.Len {
		delta := exist.X + exist.Len - prop.X
		prop.Len -= delta
		if prop.Len <= 0 {
			return empty, prop
		}
		prop.X += delta
		prop.Y += delta
	}
	if prop.Y <= exist.Y && exist.Y < prop.Y+prop.Len {
		delta := prop.Y + prop.Len - exist.Y
		prop.Len -= delta
		if prop.Len <= 0 {
			return empty, prop
		}
	}
	if exist.Y <= prop.Y && prop.Y < exist.Y+exist.Len {
		delta := exist.Y + exist.Len - prop.Y
		prop.Len -= delta
		if prop.Len <= 0 {
			return empty, prop
		}
		prop.X += delta
		prop.Y += delta
	}
	if prop.X+prop.Len <= exist.X && prop.Y+prop.Len <= exist.Y {
		return leftdown, prop
	}
	if exist.X+exist.Len <= prop.X && exist.Y+exist.Len <= prop.Y {
		return rightup, prop
	}
	return bad, prop
}

func (l lcs) prepend(x, y int) lcs {
	if len(l) > 0 {
		d := &l[0]
		if d.X == x+1 && d.Y == y+1 {
			d.X, d.Y = x, y
			d.Len++
			return l
		}
	}
	r := diag{X: x, Y: y, Len: 1}
	return append([]diag{r}, l...)
}

func (l lcs) append(x, y int) lcs {
	if len(l) > 0 {
		last := &l[len(l)-1]
		if last.X+last.Len == x && last.Y+last.Len == y {
			last.Len++
			return l
		}
	}
	return append(l, diag{X: x, Y: y, Len: 1})
}

func ok(d, k int) bool {
	return d >= 0 && -d <= k && k <= d
}

func (l lcs) toDiffs(alen, blen int) []lcsDiff {
	var diffs []lcsDiff
	var pa, pb int
	for _, d := range l {
		if pa < d.X || pb < d.Y {
			diffs = append(diffs, lcsDiff{pa, d.X, pb, d.Y})
		}
		pa = d.X + d.Len
		pb = d.Y + d.Len
	}
	if pa < alen || pb < blen {
		diffs = append(diffs, lcsDiff{pa, alen, pb, blen})
	}
	return diffs
}

// sequences abstracts a pair of sequences.
type sequences interface {
	lengths() (int, int)
	commonPrefixLen(ai, aj, bi, bj int) int
	commonSuffixLen(ai, aj, bi, bj int) int
	slice(ai, aj, bi, bj int) sequences
}

type bytesSeqs struct{ a, b []byte }

func (s bytesSeqs) slice(ai, aj, bi, bj int) sequences { return bytesSeqs{s.a[ai:aj], s.b[bi:bj]} }

func (s bytesSeqs) lengths() (int, int) { return len(s.a), len(s.b) }
func (s bytesSeqs) commonPrefixLen(ai, aj, bi, bj int) int {
	a, b := s.a[ai:aj], s.b[bi:bj]
	n := min(len(a), len(b))
	i := 0
	for i < n && a[i] == b[i] {
		i++
	}
	return i
}
func (s bytesSeqs) commonSuffixLen(ai, aj, bi, bj int) int {
	a, b := s.a[ai:aj], s.b[bi:bj]
	n := min(len(a), len(b))
	i := 0
	for i < n && a[len(a)-1-i] == b[len(b)-1-i] {
		i++
	}
	return i
}

type linesSeqs struct{ a, b []string }

func (s linesSeqs) lengths() (int, int)                { return len(s.a), len(s.b) }
func (s linesSeqs) slice(ai, aj, bi, bj int) sequences { return linesSeqs{s.a[ai:aj], s.b[bi:bj]} }
func (s linesSeqs) commonPrefixLen(ai, aj, bi, bj int) int {
	a, b := s.a[ai:aj], s.b[bi:bj]
	n := min(len(a), len(b))
	i := 0
	for i < n && a[i] == b[i] {
		i++
	}
	return i
}
func (s linesSeqs) commonSuffixLen(ai, aj, bi, bj int) int {
	a, b := s.a[ai:aj], s.b[bi:bj]
	n := min(len(a), len(b))
	i := 0
	for i < n && a[len(a)-1-i] == b[len(b)-1-i] {
		i++
	}
	return i
}

type runesSeqs struct{ a, b []rune }

func (s runesSeqs) slice(ai, aj, bi, bj int) sequences { return runesSeqs{s.a[ai:aj], s.b[bi:bj]} }

func (s runesSeqs) lengths() (int, int) { return len(s.a), len(s.b) }
func (s runesSeqs) commonPrefixLen(ai, aj, bi, bj int) int {
	a, b := s.a[ai:aj], s.b[bi:bj]
	n := min(len(a), len(b))
	i := 0
	for i < n && a[i] == b[i] {
		i++
	}
	return i
}
func (s runesSeqs) commonSuffixLen(ai, aj, bi, bj int) int {
	a, b := s.a[ai:aj], s.b[bi:bj]
	n := min(len(a), len(b))
	i := 0
	for i < n && a[len(a)-1-i] == b[len(b)-1-i] {
		i++
	}
	return i
}

func lcsDiffs(seqs sequences) []lcsDiff {
	alen, blen := seqs.lengths()
	return search(seqs).toDiffs(alen, blen)
}

// search computes a longest common subsequence with the two-sided search.
func search(seqs sequences) lcs {
	const maxDiffs = 100
	limit := maxDiffs / 2
	alen, blen := seqs.lengths()
	g := &editGraph{
		seqs:  seqs,
		vf:    newtriang(limit),
		vb:    newtriang(limit),
		limit: limit,
		ux:    alen,
		uy:    blen,
		delta: alen - blen,
	}
	return twosided(g)
}

// label stores, for each D, the furthest x reached on each diagonal k.
type label struct {
	vec [][]int
}

func (t *label) set(D, k, x int) {
	for len(t.vec) <= D {
		t.vec = append(t.vec, nil)
	}
	if t.vec[D] == nil {
		t.vec[D] = make([]int, D+1)
	}
	t.vec[D][(D+k)/2] = x
}

func (t *label) get(d, k int) int {
	return t.vec[d][(d+k)/2]
}

func newtriang(limit int) label {
	if limit < 100 {
		return label{vec: make([][]int, limit)}
	}
	return label{}
}

type editGraph struct {
	seqs           sequences
	vf, vb         label
	limit          int
	lx, ly, ux, uy int
	delta          int
}

func (e *editGraph) forwardlcs(D, k int) lcs {
	var ans lcs
	for x := e.getForward(D, k); x != 0 || x-k != 0; {
		if ok(D-1, k-1) && x-1 == e.getForward(D-1, k-1) {
			D, k, x = D-1, k-1, x-1
			continue
		} else if ok(D-1, k+1) && x == e.getForward(D-1, k+1) {
			D, k = D-1, k+1
			continue
		}
		y := x - k
		ans = ans.prepend(x+e.lx-1, y+e.ly-1)
		x--
	}
	return ans
}

func (e *editGraph) lookForward(k, relx int) int {
	rely := relx - k
	x, y := relx+e.lx, rely+e.ly
	if x < e.ux && y < e.uy {
		x += e.seqs.commonPrefixLen(x, e.ux, y, e.uy)
	}
	return x
}

func (e *editGraph) setForward(d, k, relx int) {
	x := e.lookForward(k, relx)
	e.vf.set(d, k, x-e.lx)
}

func (e *editGraph) getForward(d, k int) int {
	return e.vf.get(d, k)
}

func (e *editGraph) fdone(D, k int) (bool, lcs) {
	x := e.vf.get(D, k)
	y := x - k
	if x == e.ux && y == e.uy {
		return true, e.forwardlcs(D, k)
	}
	return false, nil
}

func forward(e *editGraph) lcs {
	e.setForward(0, 0, e.lx)
	if ok, ans := e.fdone(0, 0); ok {
		return ans
	}
	for D := 0; D < e.limit; D++ {
		e.setForward(D+1, -(D + 1), e.getForward(D, -D))
		if ok, ans := e.fdone(D+1, -(D + 1)); ok {
			return ans
		}
		e.setForward(D+1, D+1, e.getForward(D, D)+1)
		if ok, ans := e.fdone(D+1, D+1); ok {
			return ans
		}
		for k := -D + 1; k <= D-1; k += 2 {
			lookv := e.lookForward(k, e.getForward(D, k-1)+1)
			lookh := e.lookForward(k, e.getForward(D, k+1))
			if lookv > lookh {
				e.setForward(D+1, k, lookv)
			} else {
				e.setForward(D+1, k, lookh)
			}
			if ok, ans := e.fdone(D+1, k); ok {
				return ans
			}
		}
	}
	kmax := -e.limit - 1
	diagmax := -1
	for k := -e.limit; k <= e.limit; k += 2 {
		x := e.getForward(e.limit, k)
		y := x - k
		if x+y > diagmax && x <= e.ux && y <= e.uy {
			diagmax, kmax = x+y, k
		}
	}
	return e.forwardlcs(e.limit, kmax)
}

func (e *editGraph) backwardlcs(D, k int) lcs {
	var ans lcs
	for x := e.getBackward(D, k); x != e.ux || x-(k+e.delta) != e.uy; {
		if ok(D-1, k-1) && x == e.getBackward(D-1, k-1) {
			D, k = D-1, k-1
			continue
		} else if ok(D-1, k+1) && x+1 == e.getBackward(D-1, k+1) {
			D, k, x = D-1, k+1, x+1
			continue
		}
		y := x - (k + e.delta)
		ans = ans.append(x+e.lx, y+e.ly)
		x++
	}
	return ans
}

func (e *editGraph) lookBackward(k, relx int) int {
	rely := relx - (k + e.delta)
	x, y := relx+e.lx, rely+e.ly
	if x > 0 && y > 0 {
		x -= e.seqs.commonSuffixLen(0, x, 0, y)
	}
	return x
}

func (e *editGraph) setBackward(d, k, relx int) {
	x := e.lookBackward(k, relx)
	e.vb.set(d, k, x-e.lx)
}

func (e *editGraph) getBackward(d, k int) int {
	return e.vb.get(d, k)
}

func twosided(e *editGraph) lcs {
	e.setForward(0, 0, e.lx)
	e.setBackward(0, 0, e.ux)
	for D := 0; D < e.limit; D++ {
		if got, ok := e.twoDone(D, D); ok {
			return e.twolcs(D, D, got)
		}
		e.setForward(D+1, -(D + 1), e.getForward(D, -D))
		e.setForward(D+1, D+1, e.getForward(D, D)+1)
		for k := -D + 1; k <= D-1; k += 2 {
			lookv := e.lookForward(k, e.getForward(D, k-1)+1)
			lookh := e.lookForward(k, e.getForward(D, k+1))
			if lookv > lookh {
				e.setForward(D+1, k, lookv)
			} else {
				e.setForward(D+1, k, lookh)
			}
		}
		if got, ok := e.twoDone(D+1, D); ok {
			return e.twolcs(D+1, D, got)
		}
		e.setBackward(D+1, -(D + 1), e.getBackward(D, -D)-1)
		e.setBackward(D+1, D+1, e.getBackward(D, D))
		for k := -D + 1; k <= D-1; k += 2 {
			lookv := e.lookBackward(k, e.getBackward(D, k-1))
			lookh := e.lookBackward(k, e.getBackward(D, k+1)-1)
			if lookv < lookh {
				e.setBackward(D+1, k, lookv)
			} else {
				e.setBackward(D+1, k, lookh)
			}
		}
	}

	kmax := -e.limit - 1
	diagmax := -1
	for k := -e.limit; k <= e.limit; k += 2 {
		x := e.getForward(e.limit, k)
		y := x - k
		if x+y > diagmax && x <= e.ux && y <= e.uy {
			diagmax, kmax = x+y, k
		}
	}
	if kmax < -e.limit {
		panic(fmt.Sprintf("no forward paths when limit=%d?", e.limit))
	}
	l := e.forwardlcs(e.limit, kmax)
	diagmin := 1 << 25
	for k := -e.limit; k <= e.limit; k += 2 {
		x := e.getBackward(e.limit, k)
		y := x - (k + e.delta)
		if x+y < diagmin && x >= 0 && y >= 0 {
			diagmin, kmax = x+y, k
		}
	}
	if kmax < -e.limit {
		panic(fmt.Sprintf("no backward paths when limit=%d?", e.limit))
	}
	l = append(l, e.backwardlcs(e.limit, kmax)...)
	return l.fix()
}

// twoDone reports whether the forward and backward searches have met.
func (e *editGraph) twoDone(df, db int) (int, bool) {
	if (df+db+e.delta)%2 != 0 {
		return 0, false
	}
	kmin := -db + e.delta
	if -df > kmin {
		kmin = -df
	}
	kmax := db + e.delta
	if df < kmax {
		kmax = df
	}
	for k := kmin; k <= kmax; k += 2 {
		x := e.vf.get(df, k)
		u := e.vb.get(db, k-e.delta)
		if u <= x {
			for l := k; l <= kmax; l += 2 {
				x := e.vf.get(df, l)
				y := x - l
				u := e.vb.get(db, l-e.delta)
				v := u - l
				if x == u || u == 0 || v == 0 || y == e.uy || x == e.ux {
					return l, true
				}
			}
			return k, true
		}
	}
	return 0, false
}

func (e *editGraph) twolcs(df, db, kf int) lcs {
	x := e.vf.get(df, kf)
	y := x - kf
	kb := kf - e.delta
	u := e.vb.get(db, kb)
	v := u - kf

	if x == u {
		l := e.forwardlcs(df, kf)
		l = append(l, e.backwardlcs(db, kb)...)
		return l.sort()
	}
	if u > 0 && ok(df-1, u-1-v) && e.vf.get(df-1, u-1-v) == u-1 {
		l := e.forwardlcs(df-1, u-1-v)
		l = append(l, e.backwardlcs(db, kb)...)
		return l.sort()
	}
	if v > 0 && ok(df-1, (u-(v-1))) && e.vf.get(df-1, u-(v-1)) == u {
		l := e.forwardlcs(df-1, u-(v-1))
		l = append(l, e.backwardlcs(db, kb)...)
		return l.sort()
	}
	if u == 0 || v == 0 || x == e.ux || y == e.uy {
		if u == 0 || v == 0 {
			return e.backwardlcs(db, kb)
		}
		return e.forwardlcs(df, kf)
	}
	if x+1 <= e.ux && ok(db-1, x+1-y-e.delta) && e.vb.get(db-1, x+1-y-e.delta) == x+1 {
		l := e.backwardlcs(db-1, kb+1)
		l = append(l, e.forwardlcs(df, kf)...)
		return l.sort()
	}
	if y+1 <= e.uy && ok(db-1, x-(y+1)-e.delta) && e.vb.get(db-1, x-(y+1)-e.delta) == x {
		l := e.backwardlcs(db-1, kb-1)
		l = append(l, e.forwardlcs(df, kf)...)
		return l.sort()
	}
	l := e.backwardlcs(db, kb)
	oldx, oldy := e.ux, e.uy
	e.ux = u
	e.uy = v
	l = append(l, forward(e)...)
	e.ux, e.uy = oldx, oldy
	return l.sort()
}
