//! Code point sets (sorted inclusive ranges) and the case-folding helpers used by the
//! regexp compiler.

use std::collections::BTreeSet;
use std::sync::OnceLock;

pub(crate) const MAX_CP: u32 = 0x10FFFF;

/// A set of code points / code units stored as sorted, non-overlapping, non-adjacent
/// inclusive ranges.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct CharSet {
    pub(crate) r: Vec<(u32, u32)>,
}

impl CharSet {
    pub(crate) fn new() -> CharSet {
        CharSet { r: Vec::new() }
    }

    pub(crate) fn single(c: u32) -> CharSet {
        CharSet { r: vec![(c, c)] }
    }

    pub(crate) fn range(lo: u32, hi: u32) -> CharSet {
        CharSet { r: vec![(lo, hi)] }
    }

    /// Builds a normalized set from arbitrary ranges.
    pub(crate) fn from_ranges(mut v: Vec<(u32, u32)>) -> CharSet {
        normalize(&mut v);
        CharSet { r: v }
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.r.is_empty()
    }

    pub(crate) fn single_char(&self) -> Option<u32> {
        if self.r.len() == 1 && self.r[0].0 == self.r[0].1 {
            Some(self.r[0].0)
        } else {
            None
        }
    }

    pub(crate) fn count(&self) -> u64 {
        self.r.iter().map(|&(a, b)| (b - a) as u64 + 1).sum()
    }

    #[inline]
    pub(crate) fn contains(&self, c: u32) -> bool {
        let r = &self.r;
        // small sets: linear scan
        if r.len() <= 4 {
            for &(a, b) in r {
                if c < a {
                    return false;
                }
                if c <= b {
                    return true;
                }
            }
            return false;
        }
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

    pub(crate) fn union(&self, o: &CharSet) -> CharSet {
        if o.r.is_empty() {
            return self.clone();
        }
        if self.r.is_empty() {
            return o.clone();
        }
        let mut v = Vec::with_capacity(self.r.len() + o.r.len());
        v.extend_from_slice(&self.r);
        v.extend_from_slice(&o.r);
        CharSet::from_ranges(v)
    }

    pub(crate) fn add_set(&mut self, o: &CharSet) {
        if o.r.is_empty() {
            return;
        }
        self.r.extend_from_slice(&o.r);
        normalize(&mut self.r);
    }

    pub(crate) fn intersect(&self, o: &CharSet) -> CharSet {
        let mut out = Vec::new();
        let (mut i, mut j) = (0, 0);
        while i < self.r.len() && j < o.r.len() {
            let (a1, b1) = self.r[i];
            let (a2, b2) = o.r[j];
            let lo = a1.max(a2);
            let hi = b1.min(b2);
            if lo <= hi {
                out.push((lo, hi));
            }
            if b1 < b2 {
                i += 1;
            } else {
                j += 1;
            }
        }
        CharSet { r: out }
    }

    /// Complement within `[0, max]`.
    pub(crate) fn complement(&self, max: u32) -> CharSet {
        let mut out = Vec::new();
        let mut next = 0u32;
        for &(a, b) in &self.r {
            if a > max {
                break;
            }
            if a > next {
                out.push((next, a - 1));
            }
            if b >= max {
                next = max + 1;
                break;
            }
            next = b + 1;
        }
        if next <= max {
            out.push((next, max));
        }
        CharSet { r: out }
    }

    pub(crate) fn subtract(&self, o: &CharSet) -> CharSet {
        if o.r.is_empty() || self.r.is_empty() {
            return self.clone();
        }
        self.intersect(&o.complement(MAX_CP))
    }
}

fn normalize(v: &mut Vec<(u32, u32)>) {
    if v.len() <= 1 {
        return;
    }
    v.sort_unstable();
    let mut w = 0usize;
    for i in 1..v.len() {
        let (a, b) = v[i];
        let last = v[w];
        if a <= last.1.saturating_add(1) {
            if b > last.1 {
                v[w].1 = b;
            }
        } else {
            w += 1;
            v[w] = (a, b);
        }
    }
    v.truncate(w + 1);
}

/// A v-mode class value: single code points plus strings (strings never have length 1;
/// they may be empty).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub(crate) struct ClassSet {
    pub(crate) chars: CharSet,
    pub(crate) strings: BTreeSet<Vec<u32>>,
}

impl ClassSet {
    pub(crate) fn from_chars(chars: CharSet) -> ClassSet {
        ClassSet { chars, strings: BTreeSet::new() }
    }

    pub(crate) fn add_string(&mut self, s: Vec<u32>) {
        if s.len() == 1 {
            self.chars.add_set(&CharSet::single(s[0]));
        } else {
            self.strings.insert(s);
        }
    }

    pub(crate) fn union(&self, o: &ClassSet) -> ClassSet {
        let mut strings = self.strings.clone();
        for s in &o.strings {
            strings.insert(s.clone());
        }
        ClassSet { chars: self.chars.union(&o.chars), strings }
    }

    pub(crate) fn intersect(&self, o: &ClassSet) -> ClassSet {
        let strings = self.strings.intersection(&o.strings).cloned().collect();
        ClassSet { chars: self.chars.intersect(&o.chars), strings }
    }

    pub(crate) fn subtract(&self, o: &ClassSet) -> ClassSet {
        let strings = self.strings.difference(&o.strings).cloned().collect();
        ClassSet { chars: self.chars.subtract(&o.chars), strings }
    }

    /// The single code point this set consists of, if it is exactly one code point.
    pub(crate) fn single_char(&self) -> Option<u32> {
        if self.strings.is_empty() {
            self.chars.single_char()
        } else {
            None
        }
    }
}

// ---------------------------------------------------------------------------
// Case folding equivalence classes
// ---------------------------------------------------------------------------

/// Equivalence classes of a canonicalization function (only classes with >= 2 members).
pub(crate) struct CaseClasses {
    /// (char, class index), sorted by char.
    index: Vec<(u32, u32)>,
    /// class members, each sorted ascending.
    classes: Vec<Vec<u32>>,
}

impl CaseClasses {
    fn build(table: &[(u32, u32)]) -> CaseClasses {
        use std::collections::BTreeMap;
        let mut groups: BTreeMap<u32, Vec<u32>> = BTreeMap::new();
        for &(c, f) in table {
            let g = groups.entry(f).or_insert_with(|| vec![f]);
            g.push(c);
        }
        let mut classes = Vec::new();
        let mut index = Vec::new();
        for (_, mut g) in groups {
            g.sort_unstable();
            g.dedup();
            if g.len() < 2 {
                continue;
            }
            let id = classes.len() as u32;
            for &c in &g {
                index.push((c, id));
            }
            classes.push(g);
        }
        index.sort_unstable();
        CaseClasses { index, classes }
    }

    /// The members of `c`'s class (None when `c` is alone).
    pub(crate) fn class_of(&self, c: u32) -> Option<&[u32]> {
        match self.index.binary_search_by_key(&c, |&(a, _)| a) {
            Ok(i) => Some(&self.classes[self.index[i].1 as usize]),
            Err(_) => None,
        }
    }

    /// All characters equivalent to some member of `set` (including the set itself).
    pub(crate) fn close(&self, set: &CharSet) -> CharSet {
        if set.is_empty() {
            return set.clone();
        }
        let mut extra = Vec::new();
        for cls in &self.classes {
            if cls.iter().any(|&c| set.contains(c)) {
                for &c in cls {
                    extra.push((c, c));
                }
            }
        }
        if extra.is_empty() {
            return set.clone();
        }
        let mut v = set.r.clone();
        v.extend(extra);
        CharSet::from_ranges(v)
    }
}

pub(crate) fn scf_classes() -> &'static CaseClasses {
    static C: OnceLock<CaseClasses> = OnceLock::new();
    C.get_or_init(|| CaseClasses::build(crate::unicode::simple_case_fold_table()))
}

pub(crate) fn legacy_classes() -> &'static CaseClasses {
    static C: OnceLock<CaseClasses> = OnceLock::new();
    C.get_or_init(|| CaseClasses::build(crate::unicode::legacy_canonicalize_table()))
}

/// scf for a single code point.
#[inline]
pub(crate) fn scf(c: u32) -> u32 {
    if c < 0x80 {
        if (b'A' as u32..=b'Z' as u32).contains(&c) {
            return c + 32;
        }
        return c;
    }
    crate::unicode::simple_case_fold(c)
}

/// Legacy (non-unicode) Canonicalize for a code unit.
#[inline]
pub(crate) fn legacy_canon(c: u32) -> u32 {
    if c < 0x80 {
        if (b'a' as u32..=b'z' as u32).contains(&c) {
            return c - 32;
        }
        return c;
    }
    crate::unicode::legacy_canonicalize(c)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn set_ops() {
        let a = CharSet::from_ranges(vec![(5, 10), (1, 3), (11, 12), (20, 30)]);
        assert_eq!(a.r, vec![(1, 3), (5, 12), (20, 30)]);
        let b = CharSet::from_ranges(vec![(2, 6), (25, 40)]);
        assert_eq!(a.intersect(&b).r, vec![(2, 3), (5, 6), (25, 30)]);
        assert_eq!(a.subtract(&b).r, vec![(1, 1), (7, 12), (20, 24)]);
        assert_eq!(a.complement(35).r, vec![(0, 0), (4, 4), (13, 19), (31, 35)]);
        assert!(a.contains(21) && !a.contains(4));
        assert_eq!(CharSet::new().complement(10).r, vec![(0, 10)]);
        assert_eq!(CharSet::range(0, 10).complement(10).r, vec![]);
    }
}
