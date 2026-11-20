//! Backtracking VM with an explicit backtrack stack and undo log (no recursion).

use super::charset::{legacy_canon, scf};
use super::compiler::{CharMatcher, Inst, Program, NONE};

const UNDEF: u32 = u32::MAX;

/// Recursion depth limit of the original runtime's matcher (in its frame units): a path
/// fails as soon as its depth exceeds this. Reaching the end of the whole pattern costs one
/// more frame (the final accept), the end of a lookaround body costs none.
pub(crate) const DEPTH_LIMIT: u32 = 2999;
/// Per-attempt step budget of the original runtime's matcher.
pub(crate) const STEP_BUDGET: u64 = 2_000_000;
/// Step weights (calibrated against the original's budget on pathological patterns):
/// a frame of the emulated recursive matcher, a frame of a simple repeat or lookaround,
/// a backtrack resume, and a loop back-edge of an unbounded loop with a non-nullable body.
const STEP_PER_DEPTH: u64 = 2;
const STEP_PER_LIGHT_DEPTH: u64 = 1;
const STEP_PER_RESUME: u64 = 1;
const STEP_PER_ITERATION: u64 = 1;

#[derive(Clone, Copy, Debug)]
enum Bt {
    /// Resume at `pc` with position `pos` (and emulated depth).
    Branch { pc: u32, pos: u32, depth: u32 },
    /// Restore a capture slot.
    Cap { slot: u32, old: u32 },
    /// Restore a register.
    Reg { reg: u32, old: u32 },
    /// Greedy simple repeat: may give back characters down to `min_pos`.
    Greedy { pc: u32, pos: u32, min_pos: u32, depth: u32 },
    /// Lazy simple repeat: may take more characters (count so far).
    Lazy { pc: u32, pos: u32, count: u32, depth: u32 },
    /// Lookaround frame.
    Look { end: u32, pos: u32, depth: u32, negative: bool, leak: bool },
}

pub(crate) struct Vm {
    stack: Vec<Bt>,
    pub(crate) caps: Vec<u32>,
    regs: Vec<u32>,
}

#[inline(always)]
fn is_lt(c: u32) -> bool {
    c == 0x0A || c == 0x0D || c == 0x2028 || c == 0x2029
}

#[inline(always)]
fn is_word(c: u32, ui: bool) -> bool {
    (c < 128 && {
        let b = c as u8;
        b.is_ascii_alphanumeric() || b == b'_'
    }) || (ui && (c == 0x17F || c == 0x212A))
}

/// Reads the character at `pos` going forward: (char, next pos).
#[inline(always)]
fn fwd<const U: bool>(input: &[u16], pos: usize) -> Option<(u32, usize)> {
    let c = *input.get(pos)? as u32;
    if U && (c & 0xFC00) == 0xD800 {
        if let Some(&d) = input.get(pos + 1) {
            let d = d as u32;
            if (d & 0xFC00) == 0xDC00 {
                return Some((0x10000 + ((c - 0xD800) << 10) + (d - 0xDC00), pos + 2));
            }
        }
    }
    Some((c, pos + 1))
}

/// Reads the character before `pos` going backward: (char, new pos).
#[inline(always)]
fn bwd<const U: bool>(input: &[u16], pos: usize) -> Option<(u32, usize)> {
    if pos == 0 {
        return None;
    }
    let c = input[pos - 1] as u32;
    if U && (c & 0xFC00) == 0xDC00 && pos >= 2 {
        let h = input[pos - 2] as u32;
        if (h & 0xFC00) == 0xD800 {
            return Some((0x10000 + ((h - 0xD800) << 10) + (c - 0xDC00), pos - 2));
        }
    }
    Some((c, pos - 1))
}

impl Vm {
    pub(crate) fn new() -> Vm {
        Vm { stack: Vec::new(), caps: Vec::new(), regs: Vec::new() }
    }

    #[inline(always)]
    fn matches(prog: &Program, m: CharMatcher, c: u32) -> bool {
        match m {
            CharMatcher::Char(x) => c == x,
            CharMatcher::Set(s) => prog.sets[s as usize].contains(c),
        }
    }

    /// Runs the program anchored at `start`. On success the capture slots are in `caps`.
    pub(crate) fn run(&mut self, prog: &Program, input: &[u16], start: usize) -> bool {
        if prog.unicode {
            self.run_impl::<true>(prog, input, start)
        } else {
            self.run_impl::<false>(prog, input, start)
        }
    }

    fn run_impl<const U: bool>(&mut self, prog: &Program, input: &[u16], start: usize) -> bool {
        let nslots = 2 * (prog.ncap + 1);
        self.caps.clear();
        self.caps.resize(nslots, UNDEF);
        self.regs.clear();
        self.regs.resize(prog.nregs, 0);
        self.stack.clear();
        let insts = &prog.insts[..];
        let len = input.len();
        let mut pc: usize = 0;
        let mut pos: usize = start;
        let mut depth: u32 = 0;
        let mut steps: u64 = 0;
        let stack = &mut self.stack;
        let caps = &mut self.caps;
        let regs = &mut self.regs;
        'main: loop {
            let ok: bool = match &insts[pc] {
                Inst::Match => {
                    if depth + 1 > DEPTH_LIMIT {
                        false
                    } else {
                        caps[0] = start as u32;
                        caps[1] = pos as u32;
                        return true;
                    }
                }
                Inst::Char(c) => match fwd::<U>(input, pos) {
                    Some((x, np)) if x == *c => {
                        pos = np;
                        pc += 1;
                        true
                    }
                    _ => false,
                },
                Inst::CharBack(c) => match bwd::<U>(input, pos) {
                    Some((x, np)) if x == *c => {
                        pos = np;
                        pc += 1;
                        true
                    }
                    _ => false,
                },
                Inst::Set(s) => match fwd::<U>(input, pos) {
                    Some((x, np)) if prog.sets[*s as usize].contains(x) => {
                        pos = np;
                        pc += 1;
                        true
                    }
                    _ => false,
                },
                Inst::SetBack(s) => match bwd::<U>(input, pos) {
                    Some((x, np)) if prog.sets[*s as usize].contains(x) => {
                        pos = np;
                        pc += 1;
                        true
                    }
                    _ => false,
                },
                Inst::Str(k) => {
                    let s = &prog.strs[*k as usize];
                    if pos + s.len() <= len && &input[pos..pos + s.len()] == &s[..] {
                        // in unicode mode the string must not end in the middle of a pair
                        if U && pos + s.len() < len && (s[s.len() - 1] & 0xFC00) == 0xD800 && (input[pos + s.len()] & 0xFC00) == 0xDC00 {
                            false
                        } else {
                            pos += s.len();
                            pc += 1;
                            true
                        }
                    } else {
                        false
                    }
                }
                Inst::LineStart => {
                    if pos == 0 {
                        pc += 1;
                        true
                    } else {
                        false
                    }
                }
                Inst::LineStartM => {
                    if pos == 0 || is_lt(input[pos - 1] as u32) {
                        pc += 1;
                        true
                    } else {
                        false
                    }
                }
                Inst::LineEnd => {
                    if pos == len {
                        pc += 1;
                        true
                    } else {
                        false
                    }
                }
                Inst::LineEndM => {
                    if pos == len || is_lt(input[pos] as u32) {
                        pc += 1;
                        true
                    } else {
                        false
                    }
                }
                Inst::WordB(neg, ui) => {
                    let a = pos > 0 && is_word(input[pos - 1] as u32, *ui);
                    let b = pos < len && is_word(input[pos] as u32, *ui);
                    if (a != b) != *neg {
                        pc += 1;
                        true
                    } else {
                        false
                    }
                }
                Inst::Jmp(t) => {
                    pc = *t as usize;
                    true
                }
                Inst::LoopJmp(t) => {
                    steps += STEP_PER_ITERATION;
                    pc = *t as usize;
                    true
                }
                Inst::PlusJmp(t) => {
                    pc = *t as usize;
                    true
                }
                Inst::Split(a, b) => {
                    stack.push(Bt::Branch { pc: *b, pos: pos as u32, depth });
                    pc = *a as usize;
                    true
                }
                Inst::Depth(k) => {
                    depth += *k;
                    steps += STEP_PER_DEPTH * *k as u64;
                    if depth > DEPTH_LIMIT {
                        false
                    } else {
                        pc += 1;
                        true
                    }
                }
                Inst::GroupEnter => {
                    depth += 1;
                    steps += 2 * STEP_PER_DEPTH;
                    if depth > DEPTH_LIMIT {
                        false
                    } else {
                        pc += 1;
                        true
                    }
                }
                Inst::GroupExit => {
                    depth += 1;
                    if depth > DEPTH_LIMIT {
                        false
                    } else {
                        pc += 1;
                        true
                    }
                }
                Inst::RepeatDepth => {
                    depth += 1;
                    steps += STEP_PER_LIGHT_DEPTH;
                    if depth > DEPTH_LIMIT {
                        false
                    } else {
                        pc += 1;
                        true
                    }
                }
                Inst::LoopBody { reg, min, caps, finite } => {
                    let k = regs[*reg as usize];
                    let opt = k >= *min;
                    let cost = opt as u32 + *caps as u32;
                    depth += cost;
                    // optional levels of a bounded repeat weigh less in the step budget
                    steps += STEP_PER_DEPTH * *caps as u64
                        + if opt {
                            if *finite {
                                STEP_PER_DEPTH / 2
                            } else {
                                STEP_PER_DEPTH
                            }
                        } else {
                            0
                        };
                    if depth > DEPTH_LIMIT {
                        false
                    } else {
                        pc += 1;
                        true
                    }
                }
                Inst::Save(slot) => {
                    let slot = *slot as usize;
                    stack.push(Bt::Cap { slot: slot as u32, old: caps[slot] });
                    caps[slot] = pos as u32;
                    pc += 1;
                    true
                }
                Inst::ResetCaps(lo, hi) => {
                    let leaky = prog.leaky;
                    for slot in (2 * *lo as usize)..=(2 * *hi as usize + 1) {
                        if leaky || caps[slot] != UNDEF {
                            stack.push(Bt::Cap { slot: slot as u32, old: caps[slot] });
                            caps[slot] = UNDEF;
                        }
                    }
                    pc += 1;
                    true
                }
                Inst::CounterInit(r) => {
                    let r = *r as usize;
                    stack.push(Bt::Reg { reg: r as u32, old: regs[r] });
                    regs[r] = 0;
                    pc += 1;
                    true
                }
                Inst::LoopHead { reg, min, max, greedy, exit } => {
                    let k = regs[*reg as usize];
                    if k < *min {
                        pc += 1;
                        true
                    } else if *max != u32::MAX && k >= *max {
                        pc = *exit as usize;
                        true
                    } else {
                        // optional iteration: one frame for the repeat matcher
                        depth += 1;
                        steps += STEP_PER_DEPTH;
                        if depth > DEPTH_LIMIT {
                            false
                        } else {
                            if *greedy {
                                stack.push(Bt::Branch { pc: *exit, pos: pos as u32, depth });
                                pc += 1;
                            } else {
                                stack.push(Bt::Branch { pc: pc as u32 + 1, pos: pos as u32, depth });
                                pc = *exit as usize;
                            }
                            true
                        }
                    }
                }
                Inst::LoopTail { reg, pos_reg, min, head } => {
                    let r = *reg as usize;
                    let k = regs[r];
                    if *pos_reg != NONE && k >= *min && regs[*pos_reg as usize] == pos as u32 {
                        false
                    } else {
                        stack.push(Bt::Reg { reg: r as u32, old: k });
                        regs[r] = k.saturating_add(1);
                        if *pos_reg == NONE && prog.insts_max_inf(*head) {
                            steps += STEP_PER_ITERATION;
                        }
                        pc = *head as usize;
                        true
                    }
                }
                Inst::SavePos(r) => {
                    let r = *r as usize;
                    stack.push(Bt::Reg { reg: r as u32, old: regs[r] });
                    regs[r] = pos as u32;
                    pc += 1;
                    true
                }
                Inst::CheckEmpty(r) => {
                    if regs[*r as usize] == pos as u32 {
                        false
                    } else {
                        pc += 1;
                        true
                    }
                }
                Inst::Repeat { m, min, max, greedy, back } => {
                    let (m, min, max) = (*m, *min, *max);
                    if *greedy {
                        let mut count = 0u32;
                        let mut p = pos;
                        let mut min_pos = if min == 0 { pos } else { usize::MAX };
                        if !*back {
                            while count < max {
                                match fwd::<U>(input, p) {
                                    Some((c, np)) if Self::matches(prog, m, c) => {
                                        p = np;
                                        count += 1;
                                        if count == min {
                                            min_pos = p;
                                        }
                                    }
                                    _ => break,
                                }
                            }
                        } else {
                            while count < max {
                                match bwd::<U>(input, p) {
                                    Some((c, np)) if Self::matches(prog, m, c) => {
                                        p = np;
                                        count += 1;
                                        if count == min {
                                            min_pos = p;
                                        }
                                    }
                                    _ => break,
                                }
                            }
                        }
                        if count < min {
                            false
                        } else {
                            if count > min {
                                stack.push(Bt::Greedy { pc: pc as u32, pos: p as u32, min_pos: min_pos as u32, depth });
                            }
                            pos = p;
                            pc += 1;
                            true
                        }
                    } else {
                        let mut count = 0u32;
                        let mut p = pos;
                        let mut ok = true;
                        while count < min {
                            let r = if !*back { fwd::<U>(input, p) } else { bwd::<U>(input, p) };
                            match r {
                                Some((c, np)) if Self::matches(prog, m, c) => {
                                    p = np;
                                    count += 1;
                                }
                                _ => {
                                    ok = false;
                                    break;
                                }
                            }
                        }
                        if !ok {
                            false
                        } else {
                            if count < max {
                                stack.push(Bt::Lazy { pc: pc as u32, pos: p as u32, count, depth });
                            }
                            pos = p;
                            pc += 1;
                            true
                        }
                    }
                }
                Inst::BackRef { refs, icase, back } => {
                    let groups = &prog.backrefs[*refs as usize];
                    let mut span = None;
                    for &g in groups {
                        let (s, e) = (caps[2 * g as usize], caps[2 * g as usize + 1]);
                        if s != UNDEF && e != UNDEF {
                            span = Some((s as usize, e as usize));
                            break;
                        }
                    }
                    match span {
                        None => {
                            pc += 1;
                            true
                        }
                        Some((s, e)) => match backref_match::<U>(input, s, e, pos, *icase, *back) {
                            Some(np) => {
                                pos = np;
                                pc += 1;
                                true
                            }
                            None => false,
                        },
                    }
                }
                Inst::LookStart { negative, leak, end } => {
                    stack.push(Bt::Look { end: *end, pos: pos as u32, depth, negative: *negative, leak: *leak });
                    pc += 1;
                    true
                }
                Inst::LookEnd => {
                    // find the innermost lookaround frame
                    let mut i = stack.len();
                    loop {
                        i -= 1;
                        if let Bt::Look { .. } = stack[i] {
                            break;
                        }
                    }
                    let (end, lpos, ldepth, negative, leak) = match stack[i] {
                        Bt::Look { end, pos, depth, negative, leak } => (end, pos, depth, negative, leak),
                        _ => unreachable!(),
                    };
                    if negative {
                        // body matched: undo everything above the frame and fail
                        while stack.len() > i + 1 {
                            match stack.pop().unwrap() {
                                Bt::Cap { slot, old } => caps[slot as usize] = old,
                                Bt::Reg { reg, old } => regs[reg as usize] = old,
                                _ => {}
                            }
                        }
                        stack.pop();
                        false
                    } else {
                        // keep undo records (except leaking capture writes), drop choice
                        // points and the frame
                        let mut w = i;
                        for k in i + 1..stack.len() {
                            match stack[k] {
                                Bt::Cap { .. } if leak => {}
                                Bt::Cap { .. } | Bt::Reg { .. } => {
                                    stack[w] = stack[k];
                                    w += 1;
                                }
                                _ => {}
                            }
                        }
                        stack.truncate(w);
                        pos = lpos as usize;
                        depth = ldepth;
                        pc = end as usize;
                        true
                    }
                }
            };
            if ok {
                continue;
            }
            // backtrack
            loop {
                let top = match stack.last_mut() {
                    None => return false,
                    Some(t) => t,
                };
                match *top {
                    Bt::Branch { pc: p, pos: q, depth: d } => {
                        stack.pop();
                        steps += STEP_PER_RESUME;
                        if steps > STEP_BUDGET {
                            return false;
                        }
                        pc = p as usize;
                        pos = q as usize;
                        depth = d;
                        continue 'main;
                    }
                    Bt::Cap { slot, old } => {
                        caps[slot as usize] = old;
                        stack.pop();
                    }
                    Bt::Reg { reg, old } => {
                        regs[reg as usize] = old;
                        stack.pop();
                    }
                    Bt::Greedy { pc: p, pos: q, min_pos, depth: d } => {
                        steps += STEP_PER_RESUME;
                        if steps > STEP_BUDGET {
                            return false;
                        }
                        depth = d;
                        let back = matches!(insts[p as usize], Inst::Repeat { back: true, .. });
                        // give back one character
                        let np = if !back {
                            let q = q as usize;
                            let mut np = q - 1;
                            if U && np > min_pos as usize && (input[np] & 0xFC00) == 0xDC00 && (input[np - 1] & 0xFC00) == 0xD800 {
                                np -= 1;
                            }
                            np
                        } else {
                            let q = q as usize;
                            let mut np = q + 1;
                            if U && np < min_pos as usize && (input[q] & 0xFC00) == 0xD800 && (input[np] & 0xFC00) == 0xDC00 {
                                np += 1;
                            }
                            np
                        };
                        if np as u32 == min_pos {
                            stack.pop();
                        } else if let Some(Bt::Greedy { pos, .. }) = stack.last_mut() {
                            *pos = np as u32;
                        }
                        pc = p as usize + 1;
                        pos = np;
                        continue 'main;
                    }
                    Bt::Lazy { pc: p, pos: q, count, depth: d } => {
                        let (m, max, back) = match insts[p as usize] {
                            Inst::Repeat { m, max, back, .. } => (m, max, back),
                            _ => unreachable!(),
                        };
                        let r = if !back { fwd::<U>(input, q as usize) } else { bwd::<U>(input, q as usize) };
                        match r {
                            Some((c, np)) if Self::matches(prog, m, c) => {
                                // only a successful extension counts as a step
                                steps += STEP_PER_RESUME;
                                if steps > STEP_BUDGET {
                                    return false;
                                }
                                depth = d;
                                let ncount = count + 1;
                                if ncount >= max {
                                    stack.pop();
                                } else if let Some(Bt::Lazy { pos, count, .. }) = stack.last_mut() {
                                    *pos = np as u32;
                                    *count = ncount;
                                }
                                pc = p as usize + 1;
                                pos = np;
                                continue 'main;
                            }
                            _ => {
                                stack.pop();
                            }
                        }
                    }
                    Bt::Look { end, pos: q, depth: d, negative, .. } => {
                        stack.pop();
                        if negative {
                            // body failed: negative lookaround succeeds
                            pc = end as usize;
                            pos = q as usize;
                            depth = d;
                            continue 'main;
                        }
                    }
                }
            }
        }
    }
}

/// Matches the captured text input[s..e] at `pos` (forward) or ending at `pos` (backward).
fn backref_match<const U: bool>(input: &[u16], s: usize, e: usize, pos: usize, icase: bool, back: bool) -> Option<usize> {
    let n = e - s;
    let (from, to) = if back {
        if n > pos {
            return None;
        }
        (pos - n, pos)
    } else {
        if pos + n > input.len() {
            return None;
        }
        (pos, pos + n)
    };
    if U {
        // must not split surrogate pairs at the boundaries
        if back && from > 0 && n > 0 && (input[from] & 0xFC00) == 0xDC00 && (input[from - 1] & 0xFC00) == 0xD800 {
            return None;
        }
        if !back && to < input.len() && n > 0 && (input[to - 1] & 0xFC00) == 0xD800 && (input[to] & 0xFC00) == 0xDC00 {
            return None;
        }
    }
    if !icase {
        if input[s..e] == input[from..to] {
            return Some(if back { from } else { to });
        }
        return None;
    }
    if U {
        let mut i = s;
        let mut j = from;
        while i < e {
            let (a, ni) = fwd::<true>(&input[..e], i)?;
            let (b, nj) = fwd::<true>(&input[..to], j)?;
            if a != b && scf(a) != scf(b) {
                return None;
            }
            i = ni;
            j = nj;
        }
        if j != to {
            return None;
        }
    } else {
        for k in 0..n {
            let a = input[s + k] as u32;
            let b = input[from + k] as u32;
            if a != b && legacy_canon(a) != legacy_canon(b) {
                return None;
            }
        }
    }
    Some(if back { from } else { to })
}
