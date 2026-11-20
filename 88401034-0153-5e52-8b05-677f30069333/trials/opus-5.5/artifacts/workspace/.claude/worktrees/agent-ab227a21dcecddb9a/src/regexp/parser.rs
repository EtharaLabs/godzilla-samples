//! Pattern parser: ECMAScript 2025 RegExp syntax (+ Annex B in non-unicode mode) into an
//! arena AST. Error messages replicate the original runtime's SyntaxError texts.

use super::charset::{self, CharSet, ClassSet, MAX_CP};

pub(crate) type NodeId = u32;

#[derive(Clone, Debug)]
pub(crate) enum Node {
    Empty,
    /// A single literal character (case-sensitive).
    Char(u32),
    /// A set of characters (classes, escapes, case-insensitive chars, dot).
    Set(u32),
    /// v-mode class containing strings: alternatives (strings longest first, then the
    /// single-character set). Index into `Ast::string_classes`.
    StringClass(u32),
    /// `^` (multiline flag)
    LineStart(bool),
    /// `$` (multiline flag)
    LineEnd(bool),
    /// `\b` / `\B`: (negated, unicode+ignoreCase word chars)
    WordBoundary(bool, bool),
    /// Backreference to one or more groups (duplicate named groups); ignoreCase flag.
    BackRef(Vec<u32>, bool),
    /// Named backreference not yet resolved (index into names of refs), ignoreCase.
    NamedRef(u32, bool),
    Group(Option<u32>, NodeId),
    /// `(?ims-ims:...)` group (flags already applied to its contents)
    ModGroup(NodeId),
    Look { behind: bool, negative: bool, child: NodeId },
    Quant { min: u32, max: u32, greedy: bool, child: NodeId, cap_lo: u32, cap_hi: u32 },
    Seq(Vec<NodeId>),
    Alt(Vec<NodeId>),
}

pub(crate) const INF: u32 = u32::MAX;

struct Braced {
    min: Option<u64>,
    max: BracedMax,
    end: usize,
}

enum BracedMax {
    Exact,
    Open,
    Bounded(Option<u64>),
}

pub(crate) struct StringClass {
    /// Strings of length >= 2 sorted by descending length, then the empty string if present.
    pub(crate) strings: Vec<Vec<u32>>,
    pub(crate) has_empty: bool,
    pub(crate) singles: u32,
    pub(crate) icase: bool,
}

pub(crate) struct Ast {
    pub(crate) nodes: Vec<Node>,
    pub(crate) sets: Vec<CharSet>,
    pub(crate) string_classes: Vec<StringClass>,
    pub(crate) root: NodeId,
    pub(crate) ncap: u32,
    /// (name as UTF-16, group index) in source order
    pub(crate) group_names: Vec<(Vec<u16>, u32)>,
}

#[derive(Clone, Copy)]
struct Mods {
    icase: bool,
    multiline: bool,
    dotall: bool,
}

/// One open group on the explicit parse stack.
struct Frame {
    kind: FrameKind,
    alts: Vec<NodeId>,
    seq: Vec<NodeId>,
    /// mods in effect outside this group (restored on close)
    saved_mods: Mods,
    /// capture count when the group was opened (for quantifier reset ranges)
    cap_before: u32,
}

enum FrameKind {
    Root,
    Capture(u32),
    NonCapture,
    Modifiers,
    Look(bool, bool),
}

struct NameDef {
    name: Vec<u16>,
    group: u32,
    /// interned name id (same name => same id)
    id: u32,
}

pub(crate) fn is_syntax_char(c: u32) -> bool {
    matches!(char::from_u32(c), Some('^' | '$' | '\\' | '.' | '*' | '+' | '?' | '(' | ')' | '[' | ']' | '{' | '}' | '|'))
}

fn hexval(c: u32) -> Option<u32> {
    match c {
        0x30..=0x39 => Some(c - 0x30),
        0x41..=0x46 => Some(c - 0x41 + 10),
        0x61..=0x66 => Some(c - 0x61 + 10),
        _ => None,
    }
}

fn is_high(c: u32) -> bool {
    (0xD800..=0xDBFF).contains(&c)
}
fn is_low(c: u32) -> bool {
    (0xDC00..=0xDFFF).contains(&c)
}

fn cp_to_string(c: u32) -> String {
    match char::from_u32(c) {
        Some(ch) => ch.to_string(),
        None => "\u{FFFD}".to_string(),
    }
}

pub(crate) fn word_set(unicode_icase: bool) -> CharSet {
    let mut v = vec![(0x30, 0x39), (0x41, 0x5A), (0x5F, 0x5F), (0x61, 0x7A)];
    if unicode_icase {
        v.push((0x17F, 0x17F));
        v.push((0x212A, 0x212A));
    }
    CharSet::from_ranges(v)
}

pub(crate) fn space_set() -> CharSet {
    CharSet::from_ranges(vec![
        (0x09, 0x0D),
        (0x20, 0x20),
        (0xA0, 0xA0),
        (0x1680, 0x1680),
        (0x2000, 0x200A),
        (0x2028, 0x2029),
        (0x202F, 0x202F),
        (0x205F, 0x205F),
        (0x3000, 0x3000),
        (0xFEFF, 0xFEFF),
    ])
}

pub(crate) fn line_terminators() -> CharSet {
    CharSet::from_ranges(vec![(0x0A, 0x0A), (0x0D, 0x0D), (0x2028, 0x2029)])
}

/// Result of parsing a class atom / escape inside a non-v class.
enum ClassAtom {
    Char(u32),
    Set(CharSet),
}

pub(crate) struct Parser {
    src: Vec<u32>,
    pos: usize,
    u: bool,
    v: bool,
    named: bool,
    total_caps: u32,
    mods: Mods,
    nodes: Vec<Node>,
    sets: Vec<CharSet>,
    string_classes: Vec<StringClass>,
    ncap: u32,
    names: Vec<NameDef>,
    /// group index -> index into `names`
    name_of_group: std::collections::HashMap<u32, usize>,
    /// name -> (name id, group indices in source order)
    name_index: std::collections::HashMap<Vec<u16>, (u32, Vec<u32>)>,
    /// names referenced by `\k<...>`, in source order
    named_refs: Vec<Vec<u16>>,
    numeric_refs: Vec<u32>,
    /// root node (set before post checks)
    root_for_checks: NodeId,
    class_depth: u32,
}

const MAX_CLASS_DEPTH: u32 = 20000;

impl Parser {
    pub(crate) fn new(pattern: &[u16], u: bool, v: bool, icase: bool, multiline: bool, dotall: bool) -> Parser {
        let unicode = u || v;
        let src: Vec<u32> = if unicode {
            let mut out = Vec::with_capacity(pattern.len());
            let mut i = 0;
            while i < pattern.len() {
                let c = pattern[i] as u32;
                if is_high(c) && i + 1 < pattern.len() && is_low(pattern[i + 1] as u32) {
                    out.push(0x10000 + ((c - 0xD800) << 10) + (pattern[i + 1] as u32 - 0xDC00));
                    i += 2;
                } else {
                    out.push(c);
                    i += 1;
                }
            }
            out
        } else {
            pattern.iter().map(|&c| c as u32).collect()
        };
        let mut p = Parser {
            src,
            pos: 0,
            u: unicode,
            v,
            named: unicode,
            total_caps: 0,
            mods: Mods { icase, multiline, dotall },
            nodes: Vec::new(),
            sets: Vec::new(),
            string_classes: Vec::new(),
            ncap: 0,
            names: Vec::new(),
            name_of_group: std::collections::HashMap::new(),
            name_index: std::collections::HashMap::new(),
            named_refs: Vec::new(),
            numeric_refs: Vec::new(),
            root_for_checks: 0,
            class_depth: 0,
        };
        p.prescan();
        p
    }

    /// Counts capturing groups (class/escape aware) and detects named groups (naive
    /// "(?<" scan, exactly like the original).
    fn prescan(&mut self) {
        let s = &self.src;
        let n = s.len();
        let mut i = 0;
        let mut count = 0u32;
        let mut class_depth = 0u32;
        let lt = '<' as u32;
        let q = '?' as u32;
        while i < n {
            let c = s[i];
            if c == '\\' as u32 {
                i += 2;
                continue;
            }
            if class_depth > 0 {
                if c == ']' as u32 {
                    class_depth -= 1;
                } else if c == '[' as u32 && self.v {
                    class_depth += 1;
                }
            } else if c == '[' as u32 {
                class_depth = 1;
            } else if c == '(' as u32 {
                if i + 1 >= n || s[i + 1] != q {
                    count += 1;
                } else if i + 2 < n && s[i + 2] == lt && (i + 3 >= n || (s[i + 3] != '=' as u32 && s[i + 3] != '!' as u32)) {
                    count += 1;
                }
            }
            i += 1;
        }
        self.total_caps = count;
        if !self.named {
            for i in 0..n {
                if s[i] == '(' as u32 && i + 2 < n && s[i + 1] == q && s[i + 2] == lt && (i + 3 >= n || (s[i + 3] != '=' as u32 && s[i + 3] != '!' as u32)) {
                    self.named = true;
                    break;
                }
            }
        }
    }

    #[inline]
    fn peek(&self) -> Option<u32> {
        self.src.get(self.pos).copied()
    }
    #[inline]
    fn peek_at(&self, k: usize) -> Option<u32> {
        self.src.get(self.pos + k).copied()
    }
    #[inline]
    fn is(&self, ch: char) -> bool {
        self.peek() == Some(ch as u32)
    }
    #[inline]
    fn is_at(&self, k: usize, ch: char) -> bool {
        self.peek_at(k) == Some(ch as u32)
    }
    fn eat(&mut self, ch: char) -> bool {
        if self.is(ch) {
            self.pos += 1;
            true
        } else {
            false
        }
    }

    fn add(&mut self, n: Node) -> NodeId {
        self.nodes.push(n);
        (self.nodes.len() - 1) as NodeId
    }

    fn add_set(&mut self, s: CharSet) -> NodeId {
        self.sets.push(s);
        let id = (self.sets.len() - 1) as u32;
        self.add(Node::Set(id))
    }

    /// Node for a literal character under the current modifiers.
    fn char_node(&mut self, c: u32) -> NodeId {
        if self.mods.icase {
            let cls = if self.u { charset::scf_classes() } else { charset::legacy_classes() };
            if let Some(members) = cls.class_of(c) {
                let set = CharSet::from_ranges(members.iter().map(|&m| (m, m)).collect());
                return self.add_set(set);
            }
        }
        self.add(Node::Char(c))
    }

    fn universe(&self) -> u32 {
        if self.u {
            MAX_CP
        } else {
            0xFFFF
        }
    }

    // -----------------------------------------------------------------------
    // Top level
    // -----------------------------------------------------------------------

    pub(crate) fn parse(mut self) -> Result<Ast, String> {
        let mut stack: Vec<Frame> = Vec::new();
        let mut cur = Frame { kind: FrameKind::Root, alts: Vec::new(), seq: Vec::new(), saved_mods: self.mods, cap_before: 0 };
        loop {
            let c = match self.peek() {
                None => {
                    if !stack.is_empty() {
                        return Err("expected ')' in pattern".into());
                    }
                    break;
                }
                Some(c) => c,
            };
            if c == '|' as u32 {
                self.pos += 1;
                let seq = std::mem::take(&mut cur.seq);
                let n = self.make_seq(seq);
                cur.alts.push(n);
                continue;
            }
            if c == ')' as u32 {
                if stack.is_empty() {
                    return Err("unexpected character in pattern".into());
                }
                self.pos += 1;
                let frame = std::mem::replace(&mut cur, stack.pop().unwrap());
                self.mods = frame.saved_mods;
                let cap_before = frame.cap_before;
                let (kind, body) = self.finish_frame(frame);
                let node = match kind {
                    FrameKind::Capture(idx) => self.add(Node::Group(Some(idx), body)),
                    FrameKind::NonCapture => self.add(Node::Group(None, body)),
                    FrameKind::Modifiers => self.add(Node::ModGroup(body)),
                    FrameKind::Look(behind, negative) => self.add(Node::Look { behind, negative, child: body }),
                    FrameKind::Root => unreachable!(),
                };
                let is_look = matches!(kind, FrameKind::Look(..));
                let is_behind = matches!(kind, FrameKind::Look(true, _));
                let q = self.parse_quantifier(node, cap_before, is_look, is_behind)?;
                cur.seq.push(q);
                continue;
            }
            if c == '(' as u32 {
                self.pos += 1;
                let saved = self.mods;
                let cap_before = self.ncap;
                let kind = self.parse_group_open()?;
                stack.push(std::mem::replace(&mut cur, Frame { kind, alts: Vec::new(), seq: Vec::new(), saved_mods: saved, cap_before }));
                continue;
            }
            let cap_before = self.ncap;
            let atom = self.parse_atom()?;
            let q = self.parse_quantifier(atom, cap_before, false, false)?;
            cur.seq.push(q);
        }
        let (_, root) = self.finish_frame(cur);
        self.root_for_checks = root;
        self.post_checks()?;
        let group_names = self.names.iter().map(|d| (d.name.clone(), d.group)).collect();
        Ok(Ast { nodes: self.nodes, sets: self.sets, string_classes: self.string_classes, root, ncap: self.ncap, group_names })
    }

    fn make_seq(&mut self, mut seq: Vec<NodeId>) -> NodeId {
        match seq.len() {
            0 => self.add(Node::Empty),
            1 => seq.pop().unwrap(),
            _ => self.add(Node::Seq(seq)),
        }
    }

    fn finish_frame(&mut self, mut f: Frame) -> (FrameKind, NodeId) {
        let seq = std::mem::take(&mut f.seq);
        let last = self.make_seq(seq);
        let body = if f.alts.is_empty() {
            last
        } else {
            let mut alts = std::mem::take(&mut f.alts);
            alts.push(last);
            self.add(Node::Alt(alts))
        };
        (f.kind, body)
    }

    /// Post-parse validation in the original's order: named references, duplicate
    /// names, numeric back reference counts.
    fn post_checks(&mut self) -> Result<(), String> {
        // named references
        let refs = std::mem::take(&mut self.named_refs);
        for name in &refs {
            if !self.name_index.contains_key(name) {
                return Err(format!("invalid named back reference <{}>", String::from_utf16_lossy(name)));
            }
        }
        // duplicate names: a recursive walk where each sequence accumulates the names
        // defined by its terms (alternatives never conflict with each other)
        self.check_dup_names(self.root_for_checks)?;
        // numeric back references: the largest one is reported
        if let Some(&n) = self.numeric_refs.iter().max() {
            if n > self.ncap {
                return Err(format!("back reference \\{} exceeds the number of capture groups", n));
            }
        }
        // resolve named references
        for i in 0..self.nodes.len() {
            if let Node::NamedRef(k, icase) = self.nodes[i] {
                let groups = self.name_index[&refs[k as usize]].1.clone();
                self.nodes[i] = Node::BackRef(groups, icase);
            }
        }
        Ok(())
    }

    /// Returns the name ids of the named groups a node may define (in source order);
    /// errors on the first pair of same-named groups that might both participate. Each
    /// sequence accumulates the names of its terms; alternatives never conflict.
    fn check_dup_names(&self, id: NodeId) -> Result<Vec<u32>, String> {
        let dup = |k: u32| -> String {
            let d = self.names.iter().find(|d| d.id == k).unwrap();
            format!("duplicate group name {}", String::from_utf16_lossy(&d.name))
        };
        match &self.nodes[id as usize] {
            Node::Group(cap, child) => {
                let mut names = self.check_dup_names(*child)?;
                if let Some(&k) = cap.and_then(|g| self.name_of_group.get(&g)) {
                    let nid = self.names[k].id;
                    if names.contains(&nid) {
                        return Err(dup(nid));
                    }
                    names.push(nid);
                }
                Ok(names)
            }
            Node::Look { child, .. } | Node::Quant { child, .. } | Node::ModGroup(child) => self.check_dup_names(*child),
            Node::Seq(items) => {
                let mut acc: Vec<u32> = Vec::new();
                let mut seen = std::collections::HashSet::new();
                for &it in items {
                    let n = self.check_dup_names(it)?;
                    for &k in &n {
                        if seen.contains(&k) {
                            return Err(dup(k));
                        }
                    }
                    for k in n {
                        seen.insert(k);
                        acc.push(k);
                    }
                }
                Ok(acc)
            }
            Node::Alt(alts) => {
                let mut acc: Vec<u32> = Vec::new();
                for &a in alts {
                    acc.extend(self.check_dup_names(a)?);
                }
                Ok(acc)
            }
            _ => Ok(Vec::new()),
        }
    }

    // -----------------------------------------------------------------------
    // Groups
    // -----------------------------------------------------------------------

    /// Called after '('. Returns the frame kind; updates modifiers for modifier groups.
    fn parse_group_open(&mut self) -> Result<FrameKind, String> {
        if !self.is('?') {
            self.ncap += 1;
            return Ok(FrameKind::Capture(self.ncap));
        }
        self.pos += 1; // '?'
        match self.peek().and_then(char::from_u32) {
            Some(':') => {
                self.pos += 1;
                Ok(FrameKind::NonCapture)
            }
            Some('=') => {
                self.pos += 1;
                Ok(FrameKind::Look(false, false))
            }
            Some('!') => {
                self.pos += 1;
                Ok(FrameKind::Look(false, true))
            }
            Some('<') => {
                if self.is_at(1, '=') {
                    self.pos += 2;
                    return Ok(FrameKind::Look(true, false));
                }
                if self.is_at(1, '!') {
                    self.pos += 2;
                    return Ok(FrameKind::Look(true, true));
                }
                self.pos += 1;
                let name = self.parse_group_name()?;
                self.ncap += 1;
                let next_id = self.names.len() as u32;
                let entry = self.name_index.entry(name.clone()).or_insert((next_id, Vec::new()));
                entry.1.push(self.ncap);
                let id = entry.0;
                self.name_of_group.insert(self.ncap, self.names.len());
                self.names.push(NameDef { name, group: self.ncap, id });
                Ok(FrameKind::Capture(self.ncap))
            }
            Some('i' | 'm' | 's' | '-') => {
                self.parse_modifiers()?;
                Ok(FrameKind::Modifiers)
            }
            _ => Err("unsupported group".into()),
        }
    }

    fn parse_modifiers(&mut self) -> Result<(), String> {
        let mut add = [false; 3];
        let mut rem = [false; 3];
        let idx = |c: u32| -> Option<usize> {
            match char::from_u32(c) {
                Some('i') => Some(0),
                Some('m') => Some(1),
                Some('s') => Some(2),
                _ => None,
            }
        };
        let mut nadd = 0;
        while let Some(k) = self.peek().and_then(idx) {
            if add[k] {
                return Err("duplicate inline modifier flag".into());
            }
            add[k] = true;
            nadd += 1;
            self.pos += 1;
        }
        let mut has_dash = false;
        let mut nrem = 0;
        if self.is('-') {
            has_dash = true;
            self.pos += 1;
            while let Some(k) = self.peek().and_then(idx) {
                if rem[k] {
                    return Err("duplicate inline modifier flag".into());
                }
                rem[k] = true;
                nrem += 1;
                self.pos += 1;
            }
        }
        if !self.is(':') {
            return Err("invalid inline modifier".into());
        }
        self.pos += 1;
        if has_dash && nadd == 0 && nrem == 0 {
            return Err("empty inline modifier".into());
        }
        for k in 0..3 {
            if add[k] && rem[k] {
                return Err("inline modifier flag added and removed".into());
            }
        }
        if add[0] {
            self.mods.icase = true;
        }
        if rem[0] {
            self.mods.icase = false;
        }
        if add[1] {
            self.mods.multiline = true;
        }
        if rem[1] {
            self.mods.multiline = false;
        }
        if add[2] {
            self.mods.dotall = true;
        }
        if rem[2] {
            self.mods.dotall = false;
        }
        Ok(())
    }

    /// Parses a group name after '<' up to and including '>'. Returns UTF-16 units.
    fn parse_group_name(&mut self) -> Result<Vec<u16>, String> {
        let mut units: Vec<u16> = Vec::new();
        loop {
            let c = match self.peek() {
                None => return Err("unterminated capture group name".into()),
                Some(c) => c,
            };
            self.pos += 1;
            if c == '>' as u32 {
                break;
            }
            if c == '\\' as u32 {
                if !self.is('u') {
                    return Err("invalid escape in capture group name".into());
                }
                self.pos += 1;
                let cp = self.parse_name_unicode_escape()?;
                push_utf16(&mut units, cp);
                continue;
            }
            // raw character; in non-unicode mode combine surrogate pairs
            let mut cp = c;
            if !self.u && is_high(c) {
                if let Some(d) = self.peek() {
                    if is_low(d) {
                        self.pos += 1;
                        cp = 0x10000 + ((c - 0xD800) << 10) + (d - 0xDC00);
                    }
                }
            }
            if (0xD800..=0xDFFF).contains(&cp) {
                return Err("invalid capture group name".into());
            }
            push_utf16(&mut units, cp);
        }
        // validate
        let cps: Vec<u32> = decode_utf16_lossy(&units);
        let mut ok = !cps.is_empty();
        let mut lone = false;
        for (i, &cp) in cps.iter().enumerate() {
            if cp == 0xFFFD_0000 {
                lone = true;
                ok = false;
                continue;
            }
            let good = if i == 0 { crate::unicode::is_js_id_start(cp) } else { crate::unicode::is_js_id_continue(cp) };
            if !good {
                ok = false;
            }
        }
        let _ = lone;
        if !ok {
            let shown: String = cps.iter().map(|&c| if c == 0xFFFD_0000 { '\u{FFFD}' } else { char::from_u32(c).unwrap_or('\u{FFFD}') }).collect();
            return Err(format!("invalid capture group name <{}>", shown));
        }
        Ok(units)
    }

    /// After `\u` inside a group name. Invalid escapes yield U+FFFD (as the original does).
    fn parse_name_unicode_escape(&mut self) -> Result<u32, String> {
        if self.is('{') {
            self.pos += 1;
            let start = self.pos;
            loop {
                match self.peek() {
                    None => return Err("unterminated capture group name".into()),
                    Some(c) if c == '}' as u32 => break,
                    Some(_) => self.pos += 1,
                }
            }
            let digits = &self.src[start..self.pos];
            self.pos += 1; // '}'
            if digits.is_empty() {
                return Ok(0xFFFD);
            }
            let mut v: u64 = 0;
            for &d in digits {
                match hexval(d) {
                    Some(h) => {
                        v = v * 16 + h as u64;
                        if v > 0x10FFFF {
                            return Ok(0xFFFD);
                        }
                    }
                    None => return Ok(0xFFFD),
                }
            }
            return Ok(v as u32);
        }
        let mut v = 0u32;
        let mut n = 0;
        while n < 4 {
            match self.peek().and_then(hexval) {
                Some(h) => {
                    v = v * 16 + h;
                    self.pos += 1;
                    n += 1;
                }
                None => break,
            }
        }
        if n == 0 {
            return Ok(0xFFFD);
        }
        Ok(v)
    }

    // -----------------------------------------------------------------------
    // Quantifiers
    // -----------------------------------------------------------------------

    /// Tries to parse a braced quantifier at the current position (which must be '{').
    fn scan_braced(&self) -> Option<Braced> {
        let s = &self.src;
        let mut i = self.pos + 1;
        let start = i;
        while i < s.len() && (0x30..=0x39).contains(&s[i]) {
            i += 1;
        }
        if i == start {
            return None;
        }
        let min = parse_u64(&s[start..i]);
        if i < s.len() && s[i] == '}' as u32 {
            return Some(Braced { min, max: BracedMax::Exact, end: i + 1 });
        }
        if i >= s.len() || s[i] != ',' as u32 {
            return None;
        }
        i += 1;
        let start2 = i;
        while i < s.len() && (0x30..=0x39).contains(&s[i]) {
            i += 1;
        }
        if i >= s.len() || s[i] != '}' as u32 {
            return None;
        }
        if i == start2 {
            return Some(Braced { min, max: BracedMax::Open, end: i + 1 });
        }
        let max = parse_u64(&s[start2..i]);
        Some(Braced { min, max: BracedMax::Bounded(max), end: i + 1 })
    }

    /// Error to report for a quantifier that has nothing to repeat: the original checks
    /// the braced numbers' order first.
    fn nothing_to_repeat(&self) -> String {
        if self.is('{') {
            if let Some(b) = self.scan_braced() {
                if let (Some(lo), BracedMax::Bounded(Some(hi))) = (b.min, &b.max) {
                    if lo > *hi {
                        return "numbers out of order in {} quantifier".into();
                    }
                }
            }
        }
        "nothing to repeat".into()
    }

    /// Is there a quantifier at the current position?
    fn at_quantifier(&self) -> bool {
        match self.peek().and_then(char::from_u32) {
            Some('*' | '+' | '?') => true,
            Some('{') => self.scan_braced().is_some(),
            _ => false,
        }
    }

    /// Parses an optional quantifier following `atom`.
    fn parse_quantifier(&mut self, atom: NodeId, cap_before: u32, is_look: bool, is_behind: bool) -> Result<NodeId, String> {
        let c = match self.peek().and_then(char::from_u32) {
            Some(c) => c,
            None => return Ok(atom),
        };
        let (min, max, end) = match c {
            '*' => (0u32, INF, self.pos + 1),
            '+' => (1, INF, self.pos + 1),
            '?' => (0, 1, self.pos + 1),
            '{' => match self.scan_braced() {
                None => {
                    if self.u {
                        return Err("lone '{' is not valid in a unicode pattern".into());
                    }
                    return Ok(atom);
                }
                Some(b) => {
                    // u64 overflow of either number: the value becomes 0 and the order
                    // check is skipped (original runtime quirk)
                    let mut overflowed = b.min.is_none();
                    let lo = b.min.unwrap_or(0);
                    let hi: Option<u64> = match b.max {
                        BracedMax::Exact => Some(lo),
                        BracedMax::Open => None,
                        BracedMax::Bounded(Some(m)) => Some(m),
                        BracedMax::Bounded(None) => {
                            overflowed = true;
                            Some(0)
                        }
                    };
                    if !overflowed {
                        if let Some(h) = hi {
                            if lo > h {
                                return Err("numbers out of order in {} quantifier".into());
                            }
                        }
                    }
                    let lo32 = lo.min(INF as u64 - 1) as u32;
                    let hi32 = match hi {
                        None => INF,
                        Some(h) => h.min(INF as u64 - 1) as u32,
                    };
                    (lo32, hi32, b.end)
                }
            },
            _ => return Ok(atom),
        };
        if is_behind || (is_look && self.u) {
            return Err("quantifier on an assertion".into());
        }
        self.pos = end;
        let greedy = !self.eat('?');
        if self.at_quantifier() {
            return Err(self.nothing_to_repeat());
        }
        let cap_hi = self.ncap;
        Ok(self.add(Node::Quant { min, max, greedy, child: atom, cap_lo: cap_before + 1, cap_hi }))
    }

    // -----------------------------------------------------------------------
    // Atoms
    // -----------------------------------------------------------------------

    /// Parses an atom other than a group.
    fn parse_atom(&mut self) -> Result<NodeId, String> {
        let c = self.peek().unwrap();
        let ch = char::from_u32(c).unwrap_or('\u{FFFD}');
        match ch {
            '^' => {
                self.pos += 1;
                let m = self.mods.multiline;
                Ok(self.add(Node::LineStart(m)))
            }
            '$' => {
                self.pos += 1;
                let m = self.mods.multiline;
                Ok(self.add(Node::LineEnd(m)))
            }
            '.' => {
                self.pos += 1;
                let set = if self.mods.dotall {
                    CharSet::range(0, self.universe())
                } else {
                    line_terminators().complement(self.universe())
                };
                Ok(self.add_set(set))
            }
            '[' => {
                self.pos += 1;
                Ok(self.parse_class()?)
            }
            '*' | '+' | '?' => Err("nothing to repeat".into()),
            '{' => {
                if self.scan_braced().is_some() {
                    return Err(self.nothing_to_repeat());
                }
                if self.u {
                    return Err("lone '{' is not valid in a unicode pattern".into());
                }
                self.pos += 1;
                Ok(self.char_node(c))
            }
            '}' => {
                if self.u {
                    return Err("lone '}' is not valid in a unicode pattern".into());
                }
                self.pos += 1;
                Ok(self.char_node(c))
            }
            ']' => {
                if self.u {
                    return Err("lone ']' is not valid in a unicode pattern".into());
                }
                self.pos += 1;
                Ok(self.char_node(c))
            }
            '\\' => {
                self.pos += 1;
                self.parse_atom_escape()
            }
            _ => {
                self.pos += 1;
                Ok(self.char_node(c))
            }
        }
    }

    fn parse_atom_escape(&mut self) -> Result<NodeId, String> {
        let c = match self.peek() {
            None => return Err("trailing backslash".into()),
            Some(c) => c,
        };
        let ch = char::from_u32(c).unwrap_or('\u{FFFD}');
        match ch {
            'b' | 'B' => {
                self.pos += 1;
                let ui = self.u && self.mods.icase;
                Ok(self.add(Node::WordBoundary(ch == 'B', ui)))
            }
            '1'..='9' => {
                let start = self.pos;
                let mut n: u64 = 0;
                while let Some(d) = self.peek() {
                    if (0x30..=0x39).contains(&d) {
                        n = (n * 10 + (d - 0x30) as u64).min(u32::MAX as u64);
                        self.pos += 1;
                    } else {
                        break;
                    }
                }
                let n = n as u32;
                if self.u {
                    self.numeric_refs.push(n);
                    let icase = self.mods.icase;
                    return Ok(self.add(Node::BackRef(vec![n], icase)));
                }
                if n <= self.total_caps {
                    let icase = self.mods.icase;
                    return Ok(self.add(Node::BackRef(vec![n], icase)));
                }
                // legacy octal / identity escape
                self.pos = start;
                if c >= '8' as u32 {
                    self.pos += 1;
                    return Ok(self.char_node(c));
                }
                let v = self.parse_legacy_octal();
                Ok(self.char_node(v))
            }
            'k' => {
                self.pos += 1;
                if self.named {
                    if !self.eat('<') {
                        return Err("expected '<' in named back reference".into());
                    }
                    let name = self.parse_group_name()?;
                    let k = self.named_refs.len() as u32;
                    self.named_refs.push(name);
                    let icase = self.mods.icase;
                    return Ok(self.add(Node::NamedRef(k, icase)));
                }
                Ok(self.char_node('k' as u32))
            }
            'd' | 'D' | 's' | 'S' | 'w' | 'W' => {
                self.pos += 1;
                let set = self.class_escape_set(ch, self.u && self.mods.icase);
                let set = self.finish_atom_set(set);
                Ok(self.add_set(set))
            }
            'p' | 'P' if self.u => {
                self.pos += 1;
                let neg = ch == 'P';
                let cs = self.parse_property(neg)?;
                if !cs.strings.is_empty() {
                    let node = self.string_class_node(cs);
                    return Ok(node);
                }
                let mut set = self.finish_atom_set(cs.chars);
                if self.v {
                    set = v_surrogate_quirk(set);
                }
                Ok(self.add_set(set))
            }
            _ => {
                let v = self.parse_character_escape(EscCtx::Atom)?;
                match v {
                    None => {
                        // Annex B: "\c" not followed by a letter -> literal backslash
                        Ok(self.char_node('\\' as u32))
                    }
                    Some(cp) => Ok(self.char_node(cp)),
                }
            }
        }
    }

    /// Applies case closure to a set used as an atom (outside classes).
    fn finish_atom_set(&self, set: CharSet) -> CharSet {
        if self.mods.icase {
            let cls = if self.u { charset::scf_classes() } else { charset::legacy_classes() };
            return cls.close(&set);
        }
        set
    }

    /// Legacy octal escape (non-unicode); position at first digit (0-7).
    fn parse_legacy_octal(&mut self) -> u32 {
        let d0 = self.peek().unwrap() - 0x30;
        self.pos += 1;
        let mut v = d0;
        let is_oct = |c: Option<u32>| matches!(c, Some(x) if (0x30..=0x37).contains(&x));
        if is_oct(self.peek()) {
            v = v * 8 + (self.peek().unwrap() - 0x30);
            self.pos += 1;
            if d0 <= 3 && is_oct(self.peek()) {
                v = v * 8 + (self.peek().unwrap() - 0x30);
                self.pos += 1;
            }
        }
        v
    }

    /// `\d \D \s \S \w \W`; `extras` adds the u+i word characters (U+017F, U+212A).
    fn class_escape_set(&self, ch: char, extras: bool) -> CharSet {
        let uni = self.universe();
        match ch {
            'd' => CharSet::range(0x30, 0x39),
            'D' => CharSet::range(0x30, 0x39).complement(uni),
            's' => space_set(),
            'S' => space_set().complement(uni),
            'w' => word_set(extras),
            'W' => word_set(extras).complement(uni),
            _ => unreachable!(),
        }
    }

    /// Parses a CharacterEscape (after the backslash). Returns None for the Annex B
    /// `\c` case (backslash taken literally, `c` not consumed).
    fn parse_character_escape(&mut self, ctx: EscCtx) -> Result<Option<u32>, String> {
        let c = self.peek().unwrap();
        let ch = char::from_u32(c).unwrap_or('\u{FFFD}');
        match ch {
            'f' => {
                self.pos += 1;
                Ok(Some(0x0C))
            }
            'n' => {
                self.pos += 1;
                Ok(Some(0x0A))
            }
            'r' => {
                self.pos += 1;
                Ok(Some(0x0D))
            }
            't' => {
                self.pos += 1;
                Ok(Some(0x09))
            }
            'v' => {
                self.pos += 1;
                Ok(Some(0x0B))
            }
            'c' => {
                if let Some(l) = self.peek_at(1) {
                    if (0x41..=0x5A).contains(&l) || (0x61..=0x7A).contains(&l) {
                        self.pos += 2;
                        return Ok(Some(l % 32));
                    }
                    if ctx == EscCtx::Class && !self.u && ((0x30..=0x39).contains(&l) || l == '_' as u32) {
                        self.pos += 2;
                        return Ok(Some(l % 32));
                    }
                }
                if self.u {
                    if ctx == EscCtx::VClass {
                        return Err("invalid \\c escape in class set".into());
                    }
                    return Err("invalid \\c escape in unicode pattern".into());
                }
                // Annex B: the backslash is a literal; 'c' is parsed next
                Ok(None)
            }
            '0' => {
                let next_digit = matches!(self.peek_at(1), Some(d) if (0x30..=0x39).contains(&d));
                if self.u {
                    if next_digit && ctx != EscCtx::VClass {
                        return Err("legacy octal escape in unicode pattern".into());
                    }
                    self.pos += 1;
                    return Ok(Some(0));
                }
                Ok(Some(self.parse_legacy_octal()))
            }
            '1'..='9' => {
                // only reached inside classes
                if self.u {
                    let msg = if ctx == EscCtx::VClass { "v-mode class" } else { "unicode class" };
                    return Err(format!("invalid identity escape \\{} in {}", ch, msg));
                }
                if c >= '8' as u32 {
                    self.pos += 1;
                    return Ok(Some(c));
                }
                Ok(Some(self.parse_legacy_octal()))
            }
            'x' => {
                self.pos += 1;
                if let (Some(a), Some(b)) = (self.peek().and_then(hexval), self.peek_at(1).and_then(hexval)) {
                    self.pos += 2;
                    return Ok(Some(a * 16 + b));
                }
                if self.u {
                    return Err("invalid hexadecimal escape".into());
                }
                Ok(Some('x' as u32))
            }
            'u' => {
                self.pos += 1;
                match self.parse_unicode_escape_body()? {
                    Some(v) => Ok(Some(v)),
                    None => {
                        if self.u {
                            return Err("invalid unicode escape".into());
                        }
                        Ok(Some('u' as u32))
                    }
                }
            }
            _ => {
                if self.u {
                    let ok = match ctx {
                        EscCtx::Atom => is_syntax_char(c) || c == '/' as u32,
                        EscCtx::Class => is_syntax_char(c) || c == '/' as u32 || c == '-' as u32,
                        EscCtx::VClass => is_syntax_char(c) || matches!(char::from_u32(c), Some('/' | '-' | '&' | '!' | '#' | '%' | ',' | ':' | ';' | '<' | '=' | '>' | '@' | '`' | '~' | '"' | '\'')),
                    };
                    if !ok {
                        let msg = match ctx {
                            EscCtx::Atom => "unicode pattern",
                            EscCtx::Class => "unicode class",
                            EscCtx::VClass => "v-mode class",
                        };
                        return Err(format!("invalid identity escape \\{} in {}", cp_to_string(c), msg));
                    }
                }
                self.pos += 1;
                Ok(Some(c))
            }
        }
    }

    /// After `\u`. Returns Some(value) for a valid escape; None if not an escape
    /// (non-unicode fallback). Errors for invalid `\u{...}` in unicode mode.
    fn parse_unicode_escape_body(&mut self) -> Result<Option<u32>, String> {
        if self.u && self.is('{') {
            let save = self.pos;
            self.pos += 1;
            let mut v: u64 = 0;
            let mut n = 0;
            while let Some(h) = self.peek().and_then(hexval) {
                v = v * 16 + h as u64;
                if v > 0x10FFFF {
                    return Err("invalid code point escape".into());
                }
                n += 1;
                self.pos += 1;
            }
            if n == 0 || !self.eat('}') {
                let _ = save;
                return Err("invalid code point escape".into());
            }
            return Ok(Some(v as u32));
        }
        let v = match self.hex4(self.pos) {
            Some(v) => v,
            None => return Ok(None),
        };
        self.pos += 4;
        if self.u && is_high(v) {
            // surrogate pair \uHHHH\uLLLL
            if self.is('\\') && self.is_at(1, 'u') {
                if let Some(lo) = self.hex4(self.pos + 2) {
                    if is_low(lo) {
                        self.pos += 6;
                        return Ok(Some(0x10000 + ((v - 0xD800) << 10) + (lo - 0xDC00)));
                    }
                }
            }
        }
        Ok(Some(v))
    }

    fn hex4(&self, at: usize) -> Option<u32> {
        let mut v = 0;
        for k in 0..4 {
            let h = hexval(*self.src.get(at + k)?)?;
            v = v * 16 + h;
        }
        Some(v)
    }

    // -----------------------------------------------------------------------
    // Unicode properties
    // -----------------------------------------------------------------------

    /// After `\p` / `\P`. Returns the raw (un-folded) set; `\P` is the complement over
    /// all code points.
    fn parse_property(&mut self, negated: bool) -> Result<ClassSet, String> {
        if !self.eat('{') {
            return Err("invalid property escape: expected '{'".into());
        }
        let start = self.pos;
        loop {
            match self.peek() {
                None => return Err("unterminated property escape".into()),
                Some(c) if c == '}' as u32 => break,
                Some(c) => {
                    let ok = (0x41..=0x5A).contains(&c) || (0x61..=0x7A).contains(&c) || (0x30..=0x39).contains(&c) || c == '_' as u32 || c == '=' as u32;
                    if !ok {
                        return Err("invalid character in property escape".into());
                    }
                    self.pos += 1;
                }
            }
        }
        let text: String = self.src[start..self.pos].iter().map(|&c| char::from_u32(c).unwrap_or('?')).collect();
        self.pos += 1; // '}'
        let (name, value) = match text.find('=') {
            Some(i) => (&text[..i], Some(&text[i + 1..])),
            None => (&text[..], None),
        };
        if value.is_none() && self.v {
            if let Some((chars, strings)) = crate::unicode::string_property(name) {
                if negated {
                    return Err("\\P of a property of strings is invalid".into());
                }
                let mut cs = ClassSet::from_chars(CharSet::from_ranges(chars));
                for s in strings {
                    cs.add_string(s);
                }
                return Ok(cs);
            }
        }
        let ranges = match value {
            Some(v) if v.contains('=') => None,
            _ => crate::unicode::property_ranges(name, value),
        };
        let ranges = match ranges {
            Some(r) => r,
            None => return Err(format!("invalid unicode property {}", text)),
        };
        let mut set = CharSet::from_ranges(ranges);
        if negated {
            set = set.complement(MAX_CP);
        }
        Ok(ClassSet::from_chars(set))
    }

    /// Node for a v-mode class value that contains strings.
    fn string_class_node(&mut self, cs: ClassSet) -> NodeId {
        let icase = self.mods.icase;
        let singles = if icase { charset::scf_classes().close(&cs.chars) } else { cs.chars.clone() };
        self.sets.push(v_surrogate_quirk(singles));
        let singles_id = (self.sets.len() - 1) as u32;
        let mut strings: Vec<Vec<u32>> = cs.strings.iter().filter(|s| !s.is_empty()).cloned().collect();
        strings.sort_by(|a, b| b.len().cmp(&a.len()));
        let has_empty = cs.strings.iter().any(|s| s.is_empty());
        self.string_classes.push(StringClass { strings, has_empty, singles: singles_id, icase });
        let id = (self.string_classes.len() - 1) as u32;
        self.add(Node::StringClass(id))
    }

    // -----------------------------------------------------------------------
    // Character classes
    // -----------------------------------------------------------------------

    /// After '['.
    fn parse_class(&mut self) -> Result<NodeId, String> {
        if self.v {
            let negated = self.eat('^');
            let cs = self.parse_class_v_contents(negated)?;
            if !cs.strings.is_empty() {
                return Ok(self.string_class_node(cs));
            }
            // v-mode: set operations / negation on raw sets, case closure at the end
            let set = if self.mods.icase { charset::scf_classes().close(&cs.chars) } else { cs.chars };
            return Ok(self.add_set(v_surrogate_quirk(set)));
        }
        let negated = self.eat('^');
        let mut ranges: Vec<(u32, u32)> = Vec::new();
        loop {
            match self.peek() {
                None => return Err("unterminated character class".into()),
                Some(c) if c == ']' as u32 => {
                    self.pos += 1;
                    break;
                }
                _ => {}
            }
            let a = self.parse_class_atom()?;
            if self.is('-') && !self.is_at(1, ']') {
                if self.peek_at(1).is_none() {
                    return Err("unterminated character class".into());
                }
                self.pos += 1;
                let b = self.parse_class_atom()?;
                match (a, b) {
                    (ClassAtom::Char(x), ClassAtom::Char(y)) => {
                        if x > y {
                            return Err("range out of order in character class".into());
                        }
                        ranges.push((x, y));
                    }
                    (a, b) => {
                        if self.u {
                            return Err("invalid character class range".into());
                        }
                        // Annex B: union of both atoms and '-'
                        for at in [a, b] {
                            match at {
                                ClassAtom::Char(x) => ranges.push((x, x)),
                                ClassAtom::Set(s) => ranges.extend_from_slice(&s.r),
                            }
                        }
                        ranges.push(('-' as u32, '-' as u32));
                    }
                }
            } else {
                match a {
                    ClassAtom::Char(x) => ranges.push((x, x)),
                    ClassAtom::Set(s) => ranges.extend_from_slice(&s.r),
                }
            }
        }
        let mut set = CharSet::from_ranges(ranges);
        if self.mods.icase {
            let cls = if self.u { charset::scf_classes() } else { charset::legacy_classes() };
            set = cls.close(&set);
        }
        if negated {
            set = set.complement(self.universe());
        }
        Ok(self.add_set(set))
    }

    fn parse_class_atom(&mut self) -> Result<ClassAtom, String> {
        let c = match self.peek() {
            None => return Err("unterminated character class".into()),
            Some(c) => c,
        };
        self.pos += 1;
        if c != '\\' as u32 {
            return Ok(ClassAtom::Char(c));
        }
        let e = match self.peek() {
            None => return Err("bad escape in class".into()),
            Some(e) => e,
        };
        let ech = char::from_u32(e).unwrap_or('\u{FFFD}');
        match ech {
            'b' => {
                self.pos += 1;
                Ok(ClassAtom::Char(8))
            }
            '-' if self.u => {
                self.pos += 1;
                Ok(ClassAtom::Char('-' as u32))
            }
            'd' | 'D' | 's' | 'S' | 'w' | 'W' => {
                self.pos += 1;
                Ok(ClassAtom::Set(self.class_escape_set(ech, self.u && self.mods.icase)))
            }
            'p' | 'P' if self.u => {
                self.pos += 1;
                let cs = self.parse_property(ech == 'P')?;
                Ok(ClassAtom::Set(cs.chars))
            }
            'k' if self.u => Err("invalid identity escape \\k in unicode class".into()),
            'B' if self.u => Err("invalid identity escape \\B in unicode class".into()),
            _ => match self.parse_character_escape(EscCtx::Class)? {
                Some(v) => Ok(ClassAtom::Char(v)),
                None => Ok(ClassAtom::Char('\\' as u32)),
            },
        }
    }

    // ---- v-mode class sets ----

    /// Parses class contents after '[' and optional '^' up to and including ']'.
    fn parse_class_v_contents(&mut self, negated: bool) -> Result<ClassSet, String> {
        self.class_depth += 1;
        if self.class_depth > MAX_CLASS_DEPTH {
            return Err("regular expression too large".into());
        }
        let r = self.parse_class_v_inner(negated);
        self.class_depth -= 1;
        r
    }

    fn parse_class_v_inner(&mut self, negated: bool) -> Result<ClassSet, String> {
        if self.eat(']') {
            return v_negate(ClassSet::default(), negated);
        }
        if self.peek().is_none() {
            return Err("unterminated character class".into());
        }
        let first = self.parse_v_operand()?;
        let result = if self.is('&') && self.is_at(1, '&') {
            let mut acc = first;
            while self.is('&') && self.is_at(1, '&') {
                self.pos += 2;
                if self.is('&') {
                    return Err("unexpected '&&&' in class set".into());
                }
                let op = self.parse_v_operand()?;
                acc = acc.intersect(&op);
            }
            if !self.eat(']') {
                return Err("expected ']' in pattern".into());
            }
            acc
        } else if self.is('-') && self.is_at(1, '-') {
            let mut acc = first;
            while self.is('-') && self.is_at(1, '-') {
                self.pos += 2;
                let op = self.parse_v_operand()?;
                acc = acc.subtract(&op);
            }
            if !self.eat(']') {
                return Err("expected ']' in pattern".into());
            }
            acc
        } else {
            let mut acc = self.v_maybe_range(first)?;
            loop {
                if self.eat(']') {
                    break;
                }
                if self.peek().is_none() {
                    return Err("expected ']' in pattern".into());
                }
                if self.is('&') && self.is_at(1, '&') {
                    return Err("cannot mix '&&' with a union in a class set".into());
                }
                if self.is('-') && self.is_at(1, '-') {
                    return Err("cannot mix '--' with a union in a class set".into());
                }
                let op = self.parse_v_operand()?;
                let item = self.v_maybe_range(op)?;
                acc = acc.union(&item);
            }
            acc
        };
        v_negate(result, negated)
    }

    /// In a union: an operand possibly followed by `-` and a range end. Any operand that
    /// is exactly one code point may be a range endpoint (original runtime behaviour).
    fn v_maybe_range(&mut self, op: ClassSet) -> Result<ClassSet, String> {
        if self.is('-') && !self.is_at(1, '-') && !self.is_at(1, ']') {
            if let Some(lo) = op.single_char() {
                self.pos += 1;
                let end = self.parse_v_operand()?;
                let hi = match end.single_char() {
                    Some(h) => h,
                    None => return Err("invalid character class range".into()),
                };
                if lo > hi {
                    return Err("range out of order in character class".into());
                }
                return Ok(ClassSet::from_chars(CharSet::range(lo, hi)));
            }
        }
        Ok(op)
    }

    /// Parses a ClassSetOperand (nested class, \q{...}, escape or character); raw set.
    fn parse_v_operand(&mut self) -> Result<ClassSet, String> {
        let c = match self.peek() {
            None => return Err("unterminated character class".into()),
            Some(c) => c,
        };
        let ch = char::from_u32(c).unwrap_or('\u{FFFD}');
        if ch == '[' {
            self.pos += 1;
            let negated = self.eat('^');
            return self.parse_class_v_contents(negated);
        }
        if ch == '\\' {
            self.pos += 1;
            let e = match self.peek() {
                None => return Err("trailing backslash in class".into()),
                Some(e) => e,
            };
            let ech = char::from_u32(e).unwrap_or('\u{FFFD}');
            return match ech {
                'q' => {
                    self.pos += 1;
                    if !self.eat('{') {
                        return Err("expected '{' after \\q".into());
                    }
                    self.parse_q_strings()
                }
                'd' | 'D' | 's' | 'S' | 'w' | 'W' => {
                    self.pos += 1;
                    Ok(ClassSet::from_chars(self.class_escape_set(ech, false)))
                }
                'p' | 'P' => {
                    self.pos += 1;
                    self.parse_property(ech == 'P')
                }
                'b' => {
                    self.pos += 1;
                    Ok(ClassSet::from_chars(CharSet::single(8)))
                }
                'k' | 'B' => Err(format!("invalid identity escape \\{} in v-mode class", ech)),
                _ => {
                    let v = self.parse_character_escape(EscCtx::VClass)?.unwrap_or('\\' as u32);
                    Ok(ClassSet::from_chars(CharSet::single(v)))
                }
            };
        }
        // reserved double punctuators
        if let Some(n) = self.peek_at(1) {
            if n == c && matches!(ch, '&' | '!' | '#' | '$' | '%' | '*' | '+' | ',' | '.' | ':' | ';' | '<' | '=' | '>' | '?' | '@' | '^' | '`' | '~') {
                return Err(format!("reserved doubled punctuator '{}{}' in class set", ch, ch));
            }
        }
        if matches!(ch, '(' | ')' | '{' | '}' | '/' | '-' | '|') {
            return Err(format!("'{}' must be escaped in a v-mode class", ch));
        }
        self.pos += 1;
        Ok(ClassSet::from_chars(CharSet::single(c)))
    }

    /// After `\q{`: alternatives separated by `|` up to `}`.
    fn parse_q_strings(&mut self) -> Result<ClassSet, String> {
        let mut cs = ClassSet::default();
        let mut cur: Vec<u32> = Vec::new();
        loop {
            let c = match self.peek() {
                None => return Err("unterminated \\q{...}".into()),
                Some(c) => c,
            };
            if c == '}' as u32 {
                self.pos += 1;
                break;
            }
            if c == '|' as u32 {
                self.pos += 1;
                cs.add_string(std::mem::take(&mut cur));
                continue;
            }
            if c == '\\' as u32 {
                self.pos += 1;
                let e = match self.peek() {
                    None => return Err("trailing backslash in class".into()),
                    Some(e) => e,
                };
                if e == 'b' as u32 {
                    self.pos += 1;
                    cur.push(8);
                    continue;
                }
                if matches!(char::from_u32(e), Some('d' | 'D' | 's' | 'S' | 'w' | 'W' | 'p' | 'P' | 'q' | 'k' | 'B')) {
                    return Err(format!("invalid identity escape \\{} in v-mode class", cp_to_string(e)));
                }
                let v = self.parse_character_escape(EscCtx::VClass)?.unwrap_or('\\' as u32);
                cur.push(v);
                continue;
            }
            self.pos += 1;
            cur.push(c);
        }
        cs.add_string(cur);
        Ok(cs)
    }
}

/// v-mode quirk of the original runtime: after a class / property set is computed, a
/// range matches lone surrogate code points only if exactly one of its endpoints is a
/// surrogate; ranges with two surrogate endpoints never match, and ranges with no
/// surrogate endpoint never match surrogates (they only match their non-surrogate part).
pub(crate) fn v_surrogate_quirk(set: CharSet) -> CharSet {
    let is_s = |c: u32| (0xD800..=0xDFFF).contains(&c);
    let mut out = Vec::with_capacity(set.r.len() + 1);
    for &(lo, hi) in &set.r {
        match (is_s(lo), is_s(hi)) {
            (true, true) => {}
            (false, false) => {
                if lo < 0xD800 && hi > 0xDFFF {
                    out.push((lo, 0xD7FF));
                    out.push((0xE000, hi));
                } else {
                    out.push((lo, hi));
                }
            }
            _ => out.push((lo, hi)),
        }
    }
    CharSet { r: out }
}

fn v_negate(cs: ClassSet, negated: bool) -> Result<ClassSet, String> {
    if !negated {
        return Ok(cs);
    }
    if !cs.strings.is_empty() {
        return Err("cannot negate a class set containing strings".into());
    }
    Ok(ClassSet::from_chars(cs.chars.complement(MAX_CP)))
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum EscCtx {
    Atom,
    Class,
    VClass,
}

fn push_utf16(units: &mut Vec<u16>, cp: u32) {
    if cp >= 0x10000 {
        let c = cp - 0x10000;
        units.push((0xD800 + (c >> 10)) as u16);
        units.push((0xDC00 + (c & 0x3FF)) as u16);
    } else {
        units.push(cp as u16);
    }
}

/// Decodes UTF-16; lone surrogates become the marker 0xFFFD_0000.
fn decode_utf16_lossy(units: &[u16]) -> Vec<u32> {
    char::decode_utf16(units.iter().copied()).map(|r| match r {
        Ok(c) => c as u32,
        Err(_) => 0xFFFD_0000,
    }).collect()
}

fn parse_u64(digits: &[u32]) -> Option<u64> {
    let mut v: u64 = 0;
    for &d in digits {
        v = v.checked_mul(10)?.checked_add((d - 0x30) as u64)?;
    }
    Some(v)
}
