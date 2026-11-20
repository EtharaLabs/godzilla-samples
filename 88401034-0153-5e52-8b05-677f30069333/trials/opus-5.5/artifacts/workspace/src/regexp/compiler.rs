//! Compiles the parsed AST into a program for the backtracking VM.

use super::charset::CharSet;
use super::parser::{Ast, Node, NodeId, INF};

/// A character set prepared for fast membership tests.
#[derive(Clone, Debug)]
pub(crate) struct MatchSet {
    ascii: u128,
    ranges: Vec<(u32, u32)>,
}

impl MatchSet {
    pub(crate) fn new(set: &CharSet) -> MatchSet {
        let mut ascii = 0u128;
        for &(a, b) in &set.r {
            if a >= 128 {
                break;
            }
            for c in a..=b.min(127) {
                ascii |= 1u128 << c;
            }
        }
        MatchSet { ascii, ranges: set.r.clone() }
    }

    #[inline(always)]
    pub(crate) fn contains(&self, c: u32) -> bool {
        if c < 128 {
            return (self.ascii >> c) & 1 != 0;
        }
        let r = &self.ranges;
        let mut lo = 0usize;
        let mut hi = r.len();
        while lo < hi {
            let mid = (lo + hi) / 2;
            let (a, b) = r[mid];
            if c < a {
                hi = mid;
            } else if c > b {
                lo = mid + 1;
            } else {
                return true;
            }
        }
        false
    }
}

/// Single-character matcher used by simple repeats.
#[derive(Clone, Copy, Debug)]
pub(crate) enum CharMatcher {
    Char(u32),
    Set(u32),
}

#[derive(Clone, Debug)]
pub(crate) enum Inst {
    Match,
    Char(u32),
    CharBack(u32),
    Set(u32),
    SetBack(u32),
    /// Exact code-unit string (forward only, no surrogates); index into `strs`.
    Str(u32),
    LineStart,
    LineStartM,
    LineEnd,
    LineEndM,
    /// (negated, unicode-ignoreCase word characters)
    WordB(bool, bool),
    Jmp(u32),
    /// Loop back-edge (counts as a step of the emulated matcher).
    LoopJmp(u32),
    /// Back-edge of an `x+` loop.
    PlusJmp(u32),
    /// Try the first target, on failure the second.
    Split(u32, u32),
    /// Capture slot write: slot := pos (undo-logged)
    Save(u32),
    /// Reset capture groups lo..=hi to undefined
    ResetCaps(u32, u32),
    /// `regs[reg] := 0`
    CounterInit(u32),
    LoopHead { reg: u32, min: u32, max: u32, greedy: bool, exit: u32 },
    /// First instruction of a counted loop body: charges the iteration's depth
    /// (+1 for optional iterations, +1 when the body has captures).
    LoopBody { reg: u32, min: u32, caps: bool, finite: bool },
    /// Adds to the recursion depth of the emulated recursive matcher; fails when the
    /// original runtime's depth limit would be exceeded.
    Depth(u32),
    /// Depth +1 for a simple (single character) repeat or a lookaround; weighs less in
    /// the step budget.
    RepeatDepth,
    /// Entry frame of a capture / modifier group: depth +1 (the step cost of both the entry
    /// and the exit frame is charged here).
    GroupEnter,
    /// Exit frame of a capture / modifier group: depth +1, no step cost. The original's
    /// recursive matcher pushes it only once the group's contents have matched, so it is not
    /// part of the depth seen by lookaround bodies inside the group.
    GroupExit,
    /// Increments the counter (and performs the empty check if `pos_reg` != NONE)
    LoopTail { reg: u32, pos_reg: u32, min: u32, head: u32 },
    SavePos(u32),
    /// Fails if `pos == regs[reg]`
    CheckEmpty(u32),
    Repeat { m: CharMatcher, min: u32, max: u32, greedy: bool, back: bool },
    BackRef { refs: u32, icase: bool, back: bool },
    /// `leak`: positive lookaround not nested in a negative one; captures set by its
    /// body are not restored when backtracking past it (original runtime behaviour).
    LookStart { negative: bool, leak: bool, end: u32 },
    LookEnd,
}

pub(crate) const NONE: u32 = u32::MAX;

pub(crate) struct Program {
    pub(crate) insts: Vec<Inst>,
    pub(crate) sets: Vec<MatchSet>,
    pub(crate) strs: Vec<Vec<u16>>,
    pub(crate) backrefs: Vec<Vec<u32>>,
    pub(crate) nregs: usize,
    pub(crate) ncap: usize,
    pub(crate) unicode: bool,
    /// Captures may leak out of positive lookarounds (see Inst::LookStart).
    pub(crate) leaky: bool,
    /// Pattern can only match at position 0 (leading non-multiline `^`).
    pub(crate) anchored: bool,
    /// Pattern starts with multiline `^` in every alternative.
    pub(crate) line_anchored: bool,
    /// Possible first code units of a match (None = unknown / may be empty).
    pub(crate) first: Option<MatchSet>,
    /// Literal prefix (code units) every match starts with.
    pub(crate) prefix: Vec<u16>,
    /// Leading greedy unbounded single-char repeat (index of its set/char matcher):
    /// a failed attempt at p lets the search skip to the end of the run.
    pub(crate) lead_repeat: Option<(CharMatcher, u32)>,
    /// A code unit set one of whose members every match must contain (outside
    /// lookarounds); used to bound the search.
    pub(crate) required: Option<MatchSet>,
}

pub(crate) struct Compiler<'a> {
    ast: &'a Ast,
    insts: Vec<Inst>,
    sets: Vec<MatchSet>,
    strs: Vec<Vec<u16>>,
    backrefs: Vec<Vec<u32>>,
    nregs: u32,
    unicode: bool,
    /// nesting depth of negative lookarounds during emission
    neg_depth: u32,
    /// some positive lookaround may leak captures
    pub(crate) leaky: bool,
}

/// Repetition counts above this are rejected for non-simple atoms.
const MAX_COMPLEX_REPEAT: u32 = 1000;

impl Program {
    /// Is the counted loop whose head is at `pc` unbounded?
    pub(crate) fn insts_max_inf(&self, head: u32) -> bool {
        matches!(self.insts[head as usize], Inst::LoopHead { max: u32::MAX, .. })
    }
}

impl<'a> Compiler<'a> {
    pub(crate) fn compile(ast: &'a Ast, unicode: bool) -> Result<Program, String> {
        let mut c = Compiler { ast, insts: Vec::new(), sets: Vec::new(), strs: Vec::new(), backrefs: Vec::new(), nregs: 0, unicode, neg_depth: 0, leaky: false };
        c.sets = ast.sets.iter().map(MatchSet::new).collect();
        c.check_repeats()?;
        c.emit(ast.root, false);
        c.insts.push(Inst::Match);
        let anchored = c.starts_with_anchor(ast.root, false);
        let line_anchored = !anchored && c.starts_with_anchor(ast.root, true);
        let first = c.first_set(ast.root).map(|s| MatchSet::new(&s));
        let prefix = c.literal_prefix();
        let lead_repeat = c.leading_repeat(ast.root);
        let required = c.required_set(ast.root).map(|s| MatchSet::new(&s));
        Ok(Program {
            insts: c.insts,
            sets: c.sets,
            strs: c.strs,
            backrefs: c.backrefs,
            nregs: c.nregs as usize,
            ncap: ast.ncap as usize,
            unicode,
            leaky: c.leaky,
            anchored,
            line_anchored,
            first,
            prefix,
            lead_repeat,
            required,
        })
    }

    fn node(&self, id: NodeId) -> &'a Node {
        &self.ast.nodes[id as usize]
    }

    fn reg(&mut self) -> u32 {
        self.nregs += 1;
        self.nregs - 1
    }

    fn pc(&self) -> u32 {
        self.insts.len() as u32
    }

    fn push(&mut self, i: Inst) -> u32 {
        self.insts.push(i);
        self.pc() - 1
    }

    /// Is `id` a single-character matcher (for simple repeats)?
    fn simple_matcher(&self, id: NodeId) -> Option<CharMatcher> {
        match self.node(id) {
            Node::Char(c) => Some(CharMatcher::Char(*c)),
            Node::Set(s) => Some(CharMatcher::Set(*s)),
            Node::StringClass(i) => {
                let sc = &self.ast.string_classes[*i as usize];
                if sc.strings.is_empty() && !sc.has_empty {
                    Some(CharMatcher::Set(sc.singles))
                } else {
                    None
                }
            }
            _ => None,
        }
    }

    /// "repetition count too large" check (performed after parsing, in source order).
    fn check_repeats(&self) -> Result<(), String> {
        for n in &self.ast.nodes {
            if let Node::Quant { min, max, child, .. } = n {
                if self.simple_matcher(*child).is_none() && (*min > MAX_COMPLEX_REPEAT || (*max != INF && *max > MAX_COMPLEX_REPEAT)) {
                    return Err("repetition count too large".into());
                }
            }
        }
        Ok(())
    }

    pub(crate) fn can_be_empty(&self, id: NodeId) -> bool {
        match self.node(id) {
            Node::Empty | Node::LineStart(_) | Node::LineEnd(_) | Node::WordBoundary(..) | Node::Look { .. } | Node::BackRef(..) | Node::NamedRef(..) => true,
            Node::Char(_) | Node::Set(_) => false,
            Node::StringClass(i) => self.ast.string_classes[*i as usize].has_empty,
            Node::Group(_, c) | Node::ModGroup(c) => self.can_be_empty(*c),
            Node::Quant { min, max, child, .. } => *min == 0 || *max == 0 || self.can_be_empty(*child),
            Node::Seq(v) => v.iter().all(|&c| self.can_be_empty(c)),
            Node::Alt(v) => v.iter().any(|&c| self.can_be_empty(c)),
        }
    }

    fn emit(&mut self, id: NodeId, back: bool) {
        match self.node(id) {
            Node::Empty => {}
            Node::Char(c) => {
                let c = *c;
                self.push(if back { Inst::CharBack(c) } else { Inst::Char(c) });
            }
            Node::Set(s) => {
                let s = *s;
                self.push(if back { Inst::SetBack(s) } else { Inst::Set(s) });
            }
            Node::StringClass(i) => self.emit_string_class(*i, back),
            Node::LineStart(m) => {
                let m = *m;
                self.push(if m { Inst::LineStartM } else { Inst::LineStart });
            }
            Node::LineEnd(m) => {
                let m = *m;
                self.push(if m { Inst::LineEndM } else { Inst::LineEnd });
            }
            Node::WordBoundary(neg, ui) => {
                let (neg, ui) = (*neg, *ui);
                self.push(Inst::WordB(neg, ui));
            }
            Node::ModGroup(child) => {
                let child = *child;
                self.push(Inst::GroupEnter);
                self.emit(child, back);
                self.push(Inst::GroupExit);
            }
            Node::BackRef(groups, icase) => {
                let icase = *icase;
                self.backrefs.push(groups.clone());
                let refs = (self.backrefs.len() - 1) as u32;
                self.push(Inst::BackRef { refs, icase, back });
            }
            Node::NamedRef(..) => unreachable!("unresolved named reference"),
            Node::Group(cap, child) => {
                let child = *child;
                match cap {
                    Some(g) => {
                        let g = *g;
                        // forward: start slot first; backward: end slot first
                        let (first, second) = if back { (2 * g + 1, 2 * g) } else { (2 * g, 2 * g + 1) };
                        self.push(Inst::GroupEnter);
                        self.push(Inst::Save(first));
                        self.emit(child, back);
                        self.push(Inst::Save(second));
                        self.push(Inst::GroupExit);
                    }
                    None => self.emit(child, back),
                }
            }
            Node::Look { behind, negative, child } => {
                let (behind, negative, child) = (*behind, *negative, *child);
                let leak = !negative && self.neg_depth == 0;
                if leak {
                    self.leaky = true;
                }
                self.push(Inst::RepeatDepth);
                let start = self.push(Inst::LookStart { negative, leak, end: 0 });
                if negative {
                    self.neg_depth += 1;
                }
                self.emit(child, behind);
                if negative {
                    self.neg_depth -= 1;
                }
                self.push(Inst::LookEnd);
                let end = self.pc();
                if let Inst::LookStart { end: e, .. } = &mut self.insts[start as usize] {
                    *e = end;
                }
            }
            Node::Seq(items) => {
                let items = items.clone();
                if back {
                    for &it in items.iter().rev() {
                        self.emit(it, back);
                    }
                } else {
                    let mut i = 0;
                    while i < items.len() {
                        // merge runs of literal chars into a string instruction
                        let mut j = i;
                        let mut units: Vec<u16> = Vec::new();
                        while j < items.len() {
                            if let Node::Char(c) = self.node(items[j]) {
                                let c = *c;
                                if (0xD800..=0xDFFF).contains(&c) {
                                    break;
                                }
                                if c >= 0x10000 {
                                    let v = c - 0x10000;
                                    units.push((0xD800 + (v >> 10)) as u16);
                                    units.push((0xDC00 + (v & 0x3FF)) as u16);
                                } else {
                                    units.push(c as u16);
                                }
                                j += 1;
                            } else {
                                break;
                            }
                        }
                        if j - i >= 2 {
                            self.strs.push(units);
                            let k = (self.strs.len() - 1) as u32;
                            self.push(Inst::Str(k));
                            i = j;
                        } else {
                            self.emit(items[i], back);
                            i += 1;
                        }
                    }
                }
            }
            Node::Alt(alts) => {
                let alts = alts.clone();
                self.emit_alternation(alts.len(), |c, k, back| c.emit(alts[k], back), back);
            }
            Node::Quant { min, max, greedy, child, cap_lo, cap_hi, .. } => {
                let (min, mut max, greedy, child, cap_lo, cap_hi) = (*min, *max, *greedy, *child, *cap_lo, *cap_hi);
                if max != INF && max < min {
                    max = min;
                }
                if let Some(m) = self.simple_matcher(child) {
                    // simple repeats are one frame of the emulated matcher, whatever the counts
                    self.push(Inst::RepeatDepth);
                    if max == 0 {
                        return;
                    }
                    if min == 1 && max == 1 {
                        self.emit(child, back);
                    } else {
                        self.push(Inst::Repeat { m, min, max, greedy, back });
                    }
                    return;
                }
                if max == 0 {
                    return;
                }
                self.emit_loop(child, min, max, greedy, cap_lo, cap_hi, back);
            }
        }
    }

    /// Emits an alternation of `n` alternatives as a chain of nested two-way choices.
    /// Each nested choice is one frame of the emulated recursive matcher, so the k-th
    /// alternative runs at depth +min(k, n-1).
    fn emit_alternation<F: FnMut(&mut Self, usize, bool)>(&mut self, n: usize, mut each: F, back: bool) {
        let mut jumps = Vec::new();
        for k in 0..n {
            if k + 1 < n {
                self.push(Inst::Depth(1));
                let split = self.push(Inst::Split(0, 0));
                let body = self.pc();
                each(self, k, back);
                jumps.push(self.push(Inst::Jmp(0)));
                let next = self.pc();
                self.insts[split as usize] = Inst::Split(body, next);
            } else {
                each(self, k, back);
            }
        }
        let end = self.pc();
        for j in jumps {
            self.insts[j as usize] = Inst::Jmp(end);
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn emit_loop(&mut self, child: NodeId, min: u32, max: u32, greedy: bool, cap_lo: u32, cap_hi: u32, back: bool) {
        let has_caps = cap_lo <= cap_hi;
        let caps_cost = has_caps as u32;
        let nullable = self.can_be_empty(child);
        if min == 0 && (max == INF || max == 1) {
            // star / optional: head frame (+1), each iteration +1 (+1 with captures)
            let pos_reg = if nullable { self.reg() } else { NONE };
            let head = self.push(Inst::Depth(1));
            let split = self.push(Inst::Split(0, 0));
            let body = self.pc();
            self.push(Inst::Depth(1 + caps_cost));
            if pos_reg != NONE {
                self.push(Inst::SavePos(pos_reg));
            }
            if has_caps {
                self.push(Inst::ResetCaps(cap_lo, cap_hi));
            }
            self.emit(child, back);
            if pos_reg != NONE {
                self.push(Inst::CheckEmpty(pos_reg));
            }
            if max == INF {
                // a back-edge counts as a step only for non-nullable bodies
                self.push(if nullable { Inst::Jmp(head) } else { Inst::LoopJmp(head) });
            }
            let exit = self.pc();
            self.insts[split as usize] = if greedy { Inst::Split(body, exit) } else { Inst::Split(exit, body) };
            return;
        }
        if min == 1 && max == INF && !nullable {
            // x+ = x x*: first iteration mandatory
            if has_caps {
                self.push(Inst::Depth(caps_cost));
                self.push(Inst::ResetCaps(cap_lo, cap_hi));
            }
            let body = self.pc();
            self.emit(child, back);
            self.push(Inst::Depth(1));
            let split = self.push(Inst::Split(0, 0));
            let again = self.pc();
            self.push(Inst::Depth(1 + caps_cost));
            if has_caps {
                self.push(Inst::ResetCaps(cap_lo, cap_hi));
            }
            self.push(Inst::PlusJmp(body));
            let exit = self.pc();
            self.insts[split as usize] = if greedy { Inst::Split(again, exit) } else { Inst::Split(exit, again) };
            return;
        }
        // general counted loop
        let reg = self.reg();
        let pos_reg = if nullable && max > min { self.reg() } else { NONE };
        self.push(Inst::CounterInit(reg));
        let head = self.push(Inst::LoopHead { reg, min, max, greedy, exit: 0 });
        self.push(Inst::LoopBody { reg, min, caps: has_caps, finite: max != INF });
        if pos_reg != NONE {
            self.push(Inst::SavePos(pos_reg));
        }
        if has_caps {
            self.push(Inst::ResetCaps(cap_lo, cap_hi));
        }
        self.emit(child, back);
        self.push(Inst::LoopTail { reg, pos_reg, min, head });
        let exit = self.pc();
        if let Inst::LoopHead { exit: e, .. } = &mut self.insts[head as usize] {
            *e = exit;
        }
    }

    fn emit_string_class(&mut self, idx: u32, back: bool) {
        let sc = &self.ast.string_classes[idx as usize];
        let icase = sc.icase;
        let singles = sc.singles;
        // alternatives: strings (longest first, then by code points), the empty string,
        // then the singles set (always present, possibly empty)
        let mut alts: Vec<Option<Vec<u32>>> = sc.strings.iter().cloned().map(Some).collect();
        if sc.has_empty {
            alts.push(Some(Vec::new()));
        }
        alts.push(None);
        let n = alts.len();
        self.emit_alternation(
            n,
            |c, k, back| match &alts[k] {
                Some(s) => {
                    let chars: Vec<u32> = if back { s.iter().rev().copied().collect() } else { s.clone() };
                    for ch in chars {
                        c.emit_char(ch, icase, back);
                    }
                }
                None => {
                    c.push(if back { Inst::SetBack(singles) } else { Inst::Set(singles) });
                }
            },
            back,
        );
    }

    fn emit_char(&mut self, c: u32, icase: bool, back: bool) {
        if icase {
            let cls = if self.unicode { super::charset::scf_classes() } else { super::charset::legacy_classes() };
            if let Some(members) = cls.class_of(c) {
                let set = CharSet::from_ranges(members.iter().map(|&m| (m, m)).collect());
                self.sets.push(MatchSet::new(&set));
                let s = (self.sets.len() - 1) as u32;
                self.push(if back { Inst::SetBack(s) } else { Inst::Set(s) });
                return;
            }
        }
        self.push(if back { Inst::CharBack(c) } else { Inst::Char(c) });
    }

    // -----------------------------------------------------------------------
    // Search optimizations
    // -----------------------------------------------------------------------

    /// Does every match start with `^` (multiline or not, as requested)?
    fn starts_with_anchor(&self, id: NodeId, multiline: bool) -> bool {
        match self.node(id) {
            Node::LineStart(m) => *m == multiline,
            Node::Group(_, c) | Node::ModGroup(c) => self.starts_with_anchor(*c, multiline),
            Node::Seq(v) => !v.is_empty() && self.starts_with_anchor(v[0], multiline),
            Node::Alt(v) => v.iter().all(|&a| self.starts_with_anchor(a, multiline)),
            Node::Quant { min, child, .. } => *min >= 1 && self.starts_with_anchor(*child, multiline),
            _ => false,
        }
    }

    /// Conservative set of code units that can start a match; None if unknown or the
    /// pattern may match the empty string at the start position.
    fn first_set(&self, root: NodeId) -> Option<CharSet> {
        let (set, nullable) = self.first_of(root, 0)?;
        if nullable {
            return None;
        }
        Some(set)
    }

    /// Returns (first code units, may be empty) for a node.
    fn first_of(&self, id: NodeId, depth: u32) -> Option<(CharSet, bool)> {
        if depth > 64 {
            return None;
        }
        match self.node(id) {
            Node::Empty => Some((CharSet::new(), true)),
            Node::Char(c) => Some((CharSet::single(first_unit(*c)), false)),
            Node::Set(s) => Some((units_of(&self.ast.sets[*s as usize]), false)),
            Node::StringClass(i) => {
                let sc = &self.ast.string_classes[*i as usize];
                let firsts = CharSet::from_ranges(sc.strings.iter().map(|s| (s[0], s[0])).collect());
                let firsts = if sc.icase {
                    let cls = if self.unicode { super::charset::scf_classes() } else { super::charset::legacy_classes() };
                    cls.close(&firsts)
                } else {
                    firsts
                };
                let mut set = units_of(&self.ast.sets[sc.singles as usize]);
                set.add_set(&units_of(&firsts));
                Some((set, sc.has_empty))
            }
            Node::LineStart(_) | Node::LineEnd(_) | Node::WordBoundary(..) => Some((CharSet::new(), true)),
            Node::Look { .. } | Node::BackRef(..) | Node::NamedRef(..) => None,
            Node::Group(_, c) | Node::ModGroup(c) => self.first_of(*c, depth + 1),
            Node::Quant { min, max, child, .. } => {
                if *max == 0 {
                    return Some((CharSet::new(), true));
                }
                let (s, n) = self.first_of(*child, depth + 1)?;
                Some((s, n || *min == 0))
            }
            Node::Seq(v) => {
                let mut acc = CharSet::new();
                for &it in v {
                    let (s, n) = self.first_of(it, depth + 1)?;
                    acc.add_set(&s);
                    if !n {
                        return Some((acc, false));
                    }
                }
                Some((acc, true))
            }
            Node::Alt(v) => {
                let mut acc = CharSet::new();
                let mut nullable = false;
                for &a in v {
                    let (s, n) = self.first_of(a, depth + 1)?;
                    acc.add_set(&s);
                    nullable |= n;
                }
                Some((acc, nullable))
            }
        }
    }

    /// Literal code-unit prefix of the compiled program (from leading Str/Char insts).
    fn literal_prefix(&self) -> Vec<u16> {
        let mut out = Vec::new();
        for inst in &self.insts {
            match inst {
                Inst::Str(k) => out.extend_from_slice(&self.strs[*k as usize]),
                Inst::Char(c) => {
                    let c = *c;
                    if (0xD800..=0xDFFF).contains(&c) {
                        break;
                    }
                    if c >= 0x10000 {
                        let v = c - 0x10000;
                        out.push((0xD800 + (v >> 10)) as u16);
                        out.push((0xDC00 + (v & 0x3FF)) as u16);
                    } else {
                        out.push(c as u16);
                    }
                }
                Inst::Save(_) | Inst::Depth(_) | Inst::RepeatDepth | Inst::GroupEnter | Inst::GroupExit => continue,
                _ => break,
            }
        }
        out
    }

    /// A small set of code units such that every match contains one of them: the last
    /// mandatory single-character item of the top-level sequence (descending into
    /// groups). Only BMP non-surrogate characters are used.
    fn required_set(&self, root: NodeId) -> Option<CharSet> {
        let mut best: Option<CharSet> = None;
        self.collect_required(root, &mut best, 0);
        best
    }

    fn collect_required(&self, id: NodeId, best: &mut Option<CharSet>, depth: u32) {
        if depth > 32 {
            return;
        }
        match self.node(id) {
            Node::Char(c) => {
                if *c < 0xD800 || (0xE000..0x10000).contains(c) {
                    *best = Some(CharSet::single(*c));
                }
            }
            Node::Set(k) => {
                let set = &self.ast.sets[*k as usize];
                if set.count() <= 4 && set.r.iter().all(|&(a, b)| b < 0xD800 || (a >= 0xE000 && b < 0x10000)) {
                    *best = Some(set.clone());
                }
            }
            Node::Group(_, c) | Node::ModGroup(c) => self.collect_required(*c, best, depth + 1),
            Node::Quant { min, child, .. } if *min >= 1 => self.collect_required(*child, best, depth + 1),
            Node::Seq(items) => {
                for &it in items {
                    self.collect_required(it, best, depth + 1);
                }
            }
            _ => {}
        }
    }

    /// Leading greedy, unbounded simple repeat outside any group: (matcher, min).
    fn leading_repeat(&self, root: NodeId) -> Option<(CharMatcher, u32)> {
        let first = match self.node(root) {
            Node::Seq(v) => v[0],
            _ => root,
        };
        if let Node::Quant { min, max, greedy: true, child, .. } = self.node(first) {
            if *max == INF {
                if let Some(m) = self.simple_matcher(*child) {
                    return Some((m, *min));
                }
            }
        }
        None
    }
}

fn first_unit(c: u32) -> u32 {
    if c >= 0x10000 {
        0xD800 + ((c - 0x10000) >> 10)
    } else {
        c
    }
}

/// Maps a code point set to the set of possible first code units.
fn units_of(set: &CharSet) -> CharSet {
    let mut v: Vec<(u32, u32)> = Vec::new();
    for &(a, b) in &set.r {
        if b < 0x10000 {
            v.push((a, b));
        } else {
            if a < 0x10000 {
                v.push((a, 0xFFFF));
            }
            let lo = a.max(0x10000);
            v.push((first_unit(lo), first_unit(b)));
        }
    }
    CharSet::from_ranges(v)
}
