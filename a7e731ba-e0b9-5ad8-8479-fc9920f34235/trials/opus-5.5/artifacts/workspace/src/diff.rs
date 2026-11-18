// Unified diff generation (Myers divide-and-conquer with grouped hunks).

#[derive(Clone, Copy, Debug)]
enum Op {
    Equal { old: usize, new: usize, len: usize },
    Delete { old: usize, len: usize, new: usize },
    Insert { old: usize, new: usize, len: usize },
    Replace { old: usize, old_len: usize, new: usize, new_len: usize },
}

impl Op {
    fn old_range(&self) -> (usize, usize) {
        match *self {
            Op::Equal { old, len, .. } => (old, old + len),
            Op::Delete { old, len, .. } => (old, old + len),
            Op::Insert { old, .. } => (old, old),
            Op::Replace { old, old_len, .. } => (old, old + old_len),
        }
    }
    fn new_range(&self) -> (usize, usize) {
        match *self {
            Op::Equal { new, len, .. } => (new, new + len),
            Op::Delete { new, .. } => (new, new),
            Op::Insert { new, len, .. } => (new, new + len),
            Op::Replace { new, new_len, .. } => (new, new + new_len),
        }
    }
}

/// Collects raw hook events and merges adjacent delete/insert runs into replaces.
struct Collector {
    ops: Vec<Op>,
    eq: Option<(usize, usize, usize)>,
    del: Option<(usize, usize, usize)>,
    ins: Option<(usize, usize, usize)>,
}

impl Collector {
    fn new() -> Self {
        Collector { ops: Vec::new(), eq: None, del: None, ins: None }
    }
    fn flush_eq(&mut self) {
        if let Some((o, n, l)) = self.eq.take() {
            self.ops.push(Op::Equal { old: o, new: n, len: l });
        }
    }
    fn flush_del_ins(&mut self) {
        if let Some((o, l, n)) = self.del.take() {
            if let Some((_, ni, nl)) = self.ins.take() {
                self.ops.push(Op::Replace { old: o, old_len: l, new: ni, new_len: nl });
            } else {
                self.ops.push(Op::Delete { old: o, len: l, new: n });
            }
        } else if let Some((o, n, l)) = self.ins.take() {
            self.ops.push(Op::Insert { old: o, new: n, len: l });
        }
    }
    fn equal(&mut self, old: usize, new: usize, len: usize) {
        self.flush_del_ins();
        self.eq = match self.eq.take() {
            Some((o, n, l)) => Some((o, n, l + len)),
            None => Some((old, new, len)),
        };
    }
    fn delete(&mut self, old: usize, len: usize, new: usize) {
        self.flush_eq();
        self.del = match self.del.take() {
            Some((o, l, n)) => Some((o, l + len, n)),
            None => Some((old, len, new)),
        };
    }
    fn insert(&mut self, old: usize, new: usize, len: usize) {
        self.flush_eq();
        self.ins = match self.ins.take() {
            Some((o, n, l)) => Some((o, n, l + len)),
            None => Some((old, new, len)),
        };
    }
    fn finish(&mut self) {
        self.flush_eq();
        self.flush_del_ins();
    }
}

struct V {
    offset: isize,
    v: Vec<usize>,
}

impl V {
    fn new(max_d: usize) -> Self {
        V { offset: max_d as isize, v: vec![0; 2 * max_d] }
    }
    fn get(&self, i: isize) -> usize {
        self.v[(i + self.offset) as usize]
    }
    fn set(&mut self, i: isize, val: usize) {
        let idx = (i + self.offset) as usize;
        self.v[idx] = val;
    }
}

fn max_d(len1: usize, len2: usize) -> usize {
    (len1 + len2 + 1) / 2 + 1
}

fn common_prefix_len(old: &[&str], os: usize, oe: usize, new: &[&str], ns: usize, ne: usize) -> usize {
    if os >= oe || ns >= ne {
        return 0;
    }
    let mut i = 0;
    while os + i < oe && ns + i < ne && old[os + i] == new[ns + i] {
        i += 1;
    }
    i
}

fn common_suffix_len(old: &[&str], os: usize, oe: usize, new: &[&str], ns: usize, ne: usize) -> usize {
    if os >= oe || ns >= ne {
        return 0;
    }
    let mut i = 0;
    while i < oe - os && i < ne - ns && old[oe - i - 1] == new[ne - i - 1] {
        i += 1;
    }
    i
}

#[allow(clippy::too_many_arguments)]
fn find_middle_snake(
    old: &[&str],
    os: usize,
    oe: usize,
    new: &[&str],
    ns: usize,
    ne: usize,
    vf: &mut V,
    vb: &mut V,
) -> Option<(usize, usize)> {
    let n = oe - os;
    let m = ne - ns;
    let delta = n as isize - m as isize;
    let odd = delta & 1 == 1;
    vf.set(1, 0);
    vb.set(1, 0);
    let d_max = max_d(n, m);
    for d in 0..d_max as isize {
        let mut k = d;
        while k >= -d {
            let mut x = if k == -d || (k != d && vf.get(k - 1) < vf.get(k + 1)) {
                vf.get(k + 1)
            } else {
                vf.get(k - 1) + 1
            };
            let y = (x as isize - k) as usize;
            let (x0, y0) = (x, y);
            if x < n && y < m {
                let adv = common_prefix_len(old, os + x, oe, new, ns + y, ne);
                x += adv;
            }
            vf.set(k, x);
            if odd && (k - delta).abs() <= (d - 1) && vf.get(k) + vb.get(-(k - delta)) >= n {
                return Some((x0 + os, y0 + ns));
            }
            k -= 2;
        }
        let mut k = d;
        while k >= -d {
            let mut x = if k == -d || (k != d && vb.get(k - 1) < vb.get(k + 1)) {
                vb.get(k + 1)
            } else {
                vb.get(k - 1) + 1
            };
            let mut y = (x as isize - k) as usize;
            if x < n && y < m {
                let adv = common_suffix_len(old, os, os + n - x, new, ns, ns + m - y);
                x += adv;
                y += adv;
            }
            vb.set(k, x);
            if !odd && (k - delta).abs() <= d && vb.get(k) + vf.get(-(k - delta)) >= n {
                return Some((n - x + os, m - y + ns));
            }
            k -= 2;
        }
    }
    None
}

#[allow(clippy::too_many_arguments)]
fn conquer(
    c: &mut Collector,
    old: &[&str],
    mut os: usize,
    mut oe: usize,
    new: &[&str],
    mut ns: usize,
    mut ne: usize,
    vf: &mut V,
    vb: &mut V,
) {
    let pre = common_prefix_len(old, os, oe, new, ns, ne);
    if pre > 0 {
        c.equal(os, ns, pre);
    }
    os += pre;
    ns += pre;
    let suf = common_suffix_len(old, os, oe, new, ns, ne);
    let suffix_start = (oe - suf, ne - suf);
    oe -= suf;
    ne -= suf;
    if os >= oe && ns >= ne {
    } else if ns >= ne {
        c.delete(os, oe - os, ns);
    } else if os >= oe {
        c.insert(os, ns, ne - ns);
    } else if let Some((xs, ys)) = find_middle_snake(old, os, oe, new, ns, ne, vf, vb) {
        conquer(c, old, os, xs, new, ns, ys, vf, vb);
        conquer(c, old, xs, oe, new, ys, ne, vf, vb);
    } else {
        c.delete(os, oe - os, ns);
        c.insert(os, ns, ne - ns);
    }
    if suf > 0 {
        c.equal(suffix_start.0, suffix_start.1, suf);
    }
}

#[allow(dead_code)]
fn diff_ops_dc(old: &[&str], new: &[&str]) -> Vec<Op> {
    let mut c = Collector::new();
    let md = max_d(old.len(), new.len());
    let mut vf = V::new(md);
    let mut vb = V::new(md);
    conquer(&mut c, old, 0, old.len(), new, 0, new.len(), &mut vf, &mut vb);
    c.finish();
    c.ops
}

/// Classic greedy forward Myers diff with backtracking.
fn diff_ops(old: &[&str], new: &[&str]) -> Vec<Op> {
    let n = old.len() as isize;
    let m = new.len() as isize;
    let max = (n + m) as usize;
    let off = max as isize + 1;
    let mut v: Vec<isize> = vec![0; 2 * max + 3];
    let mut trace: Vec<Vec<isize>> = Vec::new();
    let mut found = false;
    for d in 0..=max as isize {
        trace.push(v.clone());
        let mut k = -d;
        while k <= d {
            let idx = (k + off) as usize;
            let mut x = if k == -d || (k != d && v[idx - 1] < v[idx + 1]) { v[idx + 1] } else { v[idx - 1] + 1 };
            let mut y = x - k;
            while x < n && y < m && old[x as usize] == new[y as usize] {
                x += 1;
                y += 1;
            }
            v[idx] = x;
            if x >= n && y >= m {
                found = true;
                break;
            }
            k += 2;
        }
        if found {
            break;
        }
    }
    // Backtrack.
    let mut edits: Vec<(char, usize, usize)> = Vec::new(); // ('=', old, new) / ('-', old, new) / ('+', old, new)
    let mut x = n;
    let mut y = m;
    for d in (0..trace.len() as isize).rev() {
        let vd = &trace[d as usize];
        let k = x - y;
        let idx = |kk: isize| (kk + off) as usize;
        let prev_k = if k == -d || (k != d && vd[idx(k - 1)] < vd[idx(k + 1)]) { k + 1 } else { k - 1 };
        let prev_x = if d == 0 { 0 } else { vd[idx(prev_k)] };
        let prev_y = prev_x - prev_k;
        while x > prev_x && y > prev_y {
            x -= 1;
            y -= 1;
            edits.push(('=', x as usize, y as usize));
        }
        if d > 0 {
            if x == prev_x {
                edits.push(('+', x as usize, (y - 1) as usize));
            } else {
                edits.push(('-', (x - 1) as usize, y as usize));
            }
        }
        x = prev_x;
        y = prev_y;
        if d == 0 {
            // Remaining diagonal at the start.
            while x > 0 && y > 0 {
                x -= 1;
                y -= 1;
                edits.push(('=', x as usize, y as usize));
            }
        }
    }
    edits.reverse();
    let mut c = Collector::new();
    for (t, o, nw) in edits {
        match t {
            '=' => c.equal(o, nw, 1),
            '-' => c.delete(o, 1, nw),
            _ => c.insert(o, nw, 1),
        }
    }
    c.finish();
    c.ops
}

fn group_ops(mut ops: Vec<Op>, n: usize) -> Vec<Vec<Op>> {
    if ops.is_empty() {
        return vec![];
    }
    let mut pending: Vec<Op> = Vec::new();
    let mut rv = Vec::new();
    if let Some(Op::Equal { old, new, len }) = ops.first_mut() {
        let offset = len.saturating_sub(n);
        *old += offset;
        *new += offset;
        *len -= offset;
    }
    if let Some(Op::Equal { len, .. }) = ops.last_mut() {
        *len -= len.saturating_sub(n);
    }
    for op in ops.into_iter() {
        if let Op::Equal { old, new, len } = op {
            if len > n * 2 {
                pending.push(Op::Equal { old, new, len: n });
                rv.push(pending);
                let offset = len.saturating_sub(n);
                pending = vec![Op::Equal { old: old + offset, new: new + offset, len: len - offset }];
                continue;
            }
        }
        pending.push(op);
    }
    match pending.as_slice() {
        [] | [Op::Equal { .. }] => {}
        _ => rv.push(pending),
    }
    rv
}

fn range_str(start: usize, end: usize) -> String {
    let mut beginning = start + 1;
    let len = end.saturating_sub(start);
    if len == 1 {
        format!("{}", beginning)
    } else {
        if len == 0 {
            beginning -= 1;
        }
        format!("{},{}", beginning, len)
    }
}

/// Split text into lines, each keeping a flag for whether it ended with a newline.
fn split_lines(s: &str) -> Vec<(&str, bool)> {
    let mut out = Vec::new();
    let mut rest = s;
    while !rest.is_empty() {
        match rest.find('\n') {
            Some(p) => {
                let line = &rest[..p];
                let line = line.strip_suffix('\r').unwrap_or(line);
                out.push((line, true));
                rest = &rest[p + 1..];
            }
            None => {
                out.push((rest, false));
                rest = "";
            }
        }
    }
    out
}

pub fn unified_diff(old_text: &str, new_text: &str, old_name: &str, new_name: &str) -> String {
    let old_lines = split_lines(old_text);
    let new_lines = split_lines(new_text);
    // Lines compare including their newline status, as line-based diffs do.
    let old_keys: Vec<String> = old_lines
        .iter()
        .map(|(l, nl)| if *nl { format!("{}\n", l) } else { l.to_string() })
        .collect();
    let new_keys: Vec<String> = new_lines
        .iter()
        .map(|(l, nl)| if *nl { format!("{}\n", l) } else { l.to_string() })
        .collect();
    let ok: Vec<&str> = old_keys.iter().map(|s| s.as_str()).collect();
    let nk: Vec<&str> = new_keys.iter().map(|s| s.as_str()).collect();
    let ops = diff_ops(&ok, &nk);
    let groups = group_ops(ops, 3);
    if groups.is_empty() {
        return String::new();
    }
    let mut out = String::new();
    out.push_str(&format!("--- {}\n+++ {}\n", old_name, new_name));
    for g in groups {
        let first = g.first().unwrap();
        let last = g.last().unwrap();
        let (os, _) = first.old_range();
        let (ns, _) = first.new_range();
        let (_, oe) = last.old_range();
        let (_, ne) = last.new_range();
        out.push_str(&format!("@@ -{} +{} @@\n", range_str(os, oe), range_str(ns, ne)));
        for op in g {
            let mut emit = |tag: char, line: &(&str, bool)| {
                out.push(tag);
                out.push_str(line.0);
                out.push('\n');
                if !line.1 {
                    out.push_str("\\ No newline at end of file\n");
                }
            };
            match op {
                Op::Equal { old, len, .. } => {
                    for i in old..old + len {
                        emit(' ', &old_lines[i]);
                    }
                }
                Op::Delete { old, len, .. } => {
                    for i in old..old + len {
                        emit('-', &old_lines[i]);
                    }
                }
                Op::Insert { new, len, .. } => {
                    for i in new..new + len {
                        emit('+', &new_lines[i]);
                    }
                }
                Op::Replace { old, old_len, new, new_len } => {
                    for i in old..old + old_len {
                        emit('-', &old_lines[i]);
                    }
                    for i in new..new + new_len {
                        emit('+', &new_lines[i]);
                    }
                }
            }
        }
    }
    out
}
