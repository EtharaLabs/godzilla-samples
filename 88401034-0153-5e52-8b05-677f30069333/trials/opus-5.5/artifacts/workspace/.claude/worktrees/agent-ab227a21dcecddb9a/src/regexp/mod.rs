//! ECMAScript regular expressions (ES2025, incl. Annex B, `v` flag, duplicate named
//! groups and pattern modifiers) for lumen, reproducing the original runtime's behaviour.
//!
//! # API
//!
//! * [`parse_flags`] — flags string -> [`RegexFlags`]; `Err` is the exact SyntaxError text.
//! * [`compile`] — pattern (UTF-16) + flags -> [`CompiledRegex`] (cheap `Rc` clone); `Err` is
//!   the exact SyntaxError text. The same texts are used for regex *literals*: the original
//!   reports them as early errors when the script is parsed (`Uncaught SyntaxError: nothing to
//!   repeat`; inside `eval`/`Function` they are thrown as SyntaxError with the same message).
//!   Only the lexer-level `/[/` case differs: "unterminated regular expression".
//! * [`CompiledRegex::exec`] — RegExpBuiltinExec core: `exec(input, last_index)` searches from
//!   `last_index` (only *at* it when sticky) and returns UTF-16 spans for groups
//!   `0..=capture_count()`, `None` for non-participating groups. In u/v mode a `last_index`
//!   pointing at the low half of a surrogate pair starts the attempt at the pair (the original
//!   reports `index` = pair start, e.g. `/./gu` with lastIndex 1 on "😀" gives index 0,
//!   lastIndex 2). `last_index > len` -> `None`. The JS layer handles lastIndex itself:
//!   pass 0 when neither `g` nor `y`.
//! * [`CompiledRegex::group_names`] (or the borrowing `group_names_ref`) — named groups in
//!   source order, each with all its group indices (duplicate names in different
//!   alternatives). `groups.name` is the value of the first participating index (or
//!   undefined); property order = first occurrence order. `capture_count()`, `flags()`,
//!   `has_named_groups()` are also available.
//! * [`escape_source`] — `RegExp.prototype.source` text: "" -> `(?:)`; `/` outside classes
//!   -> `\/` (kept raw inside `[...]`, an already escaped `\/` is kept); LF/CR/U+2028/U+2029
//!   -> `\n` `\r` ` ` ` ` (also when escaped: `\<LF>` -> `\n`); tabs etc. raw.
//! * [`RegexFlags::to_flags_string`] — the `flags` getter order "dgimsuvy".
//!
//! # Error messages (SyntaxError `message`, no prefix)
//!
//! Flags (scanned left to right, u+v checked last): `invalid regular expression flag X`,
//! `duplicate regular expression flag X`, `the u and v regular expression flags are mutually
//! exclusive` (X = the character; the original keeps lone surrogates raw, we emit U+FFFD).
//!
//! Pattern (first error in a left-to-right parse; then, after a successful parse: unknown
//! `\k<name>` -> duplicate group names -> largest numeric back reference > group count ->
//! `repetition count too large`):
//! `unterminated character class`, `expected ')' in pattern`, `unexpected character in pattern`
//! (lone `)`), `nothing to repeat`, `unsupported group`, `unterminated capture group name`,
//! `invalid capture group name <NAME>` (NAME decoded, invalid escapes/lone surrogates shown
//! as U+FFFD; raw lone surrogate in the name: `invalid capture group name` without <>),
//! `invalid escape in capture group name`, `invalid named back reference <NAME>`,
//! `expected '<' in named back reference`, `duplicate group name NAME` (when several names
//! conflict the original's choice is random — HashMap order — we report the first in a
//! recursive sequence walk), `back reference \N exceeds the number of capture groups`,
//! `numbers out of order in {} quantifier`, `range out of order in character class`,
//! `invalid character class range`, `trailing backslash`, `bad escape in class`
//! (`[\` at end; v-mode: `trailing backslash in class`), `invalid \c escape in unicode
//! pattern` (v-mode class: `invalid \c escape in class set`), `invalid code point escape`,
//! `invalid hexadecimal escape`, `invalid unicode escape`, `legacy octal escape in unicode
//! pattern`, `invalid identity escape \X in unicode pattern` / `... in unicode class` /
//! `... in v-mode class`, `lone ']' is not valid in a unicode pattern` (also `'}'`, `'{'`),
//! `quantifier on an assertion` (lookbehind always, lookahead in u/v), `invalid property
//! escape: expected '{'`, `unterminated property escape`, `invalid character in property
//! escape` (anything but `[A-Za-z0-9_=]`), `invalid unicode property TEXT` (TEXT = raw text
//! between the braces, e.g. `Script=Foo`), `\P of a property of strings is invalid`,
//! `inline modifier flag added and removed`, `duplicate inline modifier flag`, `empty inline
//! modifier`, `invalid inline modifier`, `repetition count too large` (non-simple atom with a
//! finite count > 1000), v-mode classes: `'(' must be escaped in a v-mode class` (also `)`
//! `{` `}` `/` `-` `|`), `reserved doubled punctuator '&&' in class set`, `unexpected '&&&'
//! in class set`, `cannot mix '&&' with a union in a class set` (also `'--'`), `expected ']'
//! in pattern`, `cannot negate a class set containing strings`, `unterminated \q{...}`,
//! `expected '{' after \q`; deep nesting beyond our limits: `regular expression too large`.
//!
//! # Engine-level quirks of the original that are reproduced
//!
//! * Recursion depth limit: the original matcher is recursive and fails a path when its depth
//!   exceeds 2999 frames. Frame costs: reaching the end of the whole pattern 1 (the end of a
//!   lookaround body 0), capture/modifier group 1 on entry + 1 once its contents matched (so
//!   a lookaround body inside the group sees only the entry frame), k-th of n alternatives
//!   min(k, n-1), lookaround 1 (body frames released afterwards), simple (single char/class)
//!   repeat 1, complex quantifier: unbounded loop 1 + 2 per optional iteration, bounded
//!   optional level 2 if taken / 1 if not, +1 per iteration when the body has captures,
//!   mandatory copies 0 (+1 with captures). So e.g. `"ab".repeat(2000).match(/(?:a|b)*/)[0]`
//!   has length 999; on "a".repeat(3000) `(?:b|a)` repeated 2998 times (written as
//!   `(?:(?:b|a){1000}){2}(?:b|a){998}`) still matches inside `^(?=...)` but only 2996 inside
//!   `^(...)`; `/(a|b)*c/` on `"ab".repeat(200000)+"c"` matches at 399501.
//! * Per-attempt step budget (2,000,000 steps of the emulated matcher): when exceeded the
//!   attempt at that start position fails and the search continues at the next position
//!   (catastrophic patterns return quickly, e.g. `/(?:a|a)*c|a+b/` on "a".repeat(21)+"b"
//!   matches at index 4). The step weights are calibrated against the original's thresholds
//!   on ~25 pattern families; a few families differ by one input character. No memoisation.
//! * Captures set inside a successful positive lookaround are not restored when the
//!   continuation fails and an earlier alternative is taken (`/(?=(a))b|a/` on "a" ->
//!   ["a","a"]); a quantifier iteration that fails restores its own groups.
//! * Quantifiers on `^ $ \b \B` are accepted in every mode (`/^*a/`); quantifier numbers that
//!   overflow u64 become 0 and skip the order check (`a{99999999999999999999,1}` = `a{0,1}`;
//!   `{n,m}` with m < n after overflow runs n mandatory iterations).
//! * Named-group mode in non-u patterns is enabled by a naive `(?<` + not `=`/`!` scan
//!   (even inside classes/escapes); capture counting for `\N` is class aware.
//! * v-mode: set operations and negation work on raw (unfolded) sets, case closure is applied
//!   to the final set (`/[^a]/vi` matches "a"; `[\w--[a-z]]` with `vi` matches "a"); inside
//!   classes `\w`/`\W` never include U+017F/U+212A. Any single code point operand (`a`,
//!   `[a]`, `\q{a}`, `\p{Zl}`) may be a range endpoint (`[[a]-c]`). Lone surrogates are
//!   matched by a class range only if exactly one endpoint is a surrogate. `\0` followed by a
//!   digit is accepted inside v-mode classes (`[\01]` = {NUL, 1}); `\"` `\'` are valid
//!   identity escapes there. Class strings are tried longest first (ties by code point
//!   order), then the empty string, then single characters.
//! * Unicode data (properties, case folding) is Unicode 17.0 via `crate::unicode`.
//!
//! # JS-facing behaviour of the original (for the RegExp object layer)
//!
//! * `source`/`flags`/`toString`: see [`escape_source`]; `toString()` = "/" + source + "/" +
//!   flags; `String(RegExp.prototype)` = "/(?:)/", `RegExp.prototype.source` = "(?:)",
//!   `RegExp.prototype.flags` = "", `RegExp.prototype.global` (etc.) = undefined. The flags
//!   getter reads hasIndices, global, ignoreCase, multiline, dotAll, unicode, unicodeSets,
//!   sticky (in that order) on any object. Assigning `source` is silently ignored (sloppy).
//! * Own property: only `lastIndex` {writable, non-enumerable, non-configurable}, initial 0.
//!   Prototype own names order: source, flags, global, ignoreCase, multiline, dotAll, sticky,
//!   unicode, hasIndices, unicodeSets, compile, exec, test, toString, constructor; symbols:
//!   Symbol.match, replace, search, split, matchAll.
//! * exec result: array with keys 0..n, index, input, groups (+ indices when `d`;
//!   `indices.groups`); `groups` has a null prototype and is undefined without named groups.
//!   lastIndex: ToLength (−1 -> 0, 1.5 -> 1, NaN -> 0, Infinity -> fail); set to the match end
//!   for g/y, set to 0 on failure for g/y, untouched otherwise; frozen regex -> TypeError
//!   "Cannot assign to read only property 'lastIndex'". Empty matches in global
//!   match/replace/matchAll advance by one code point in u/v mode (AdvanceStringIndex).
//! * Replacement patterns: `$$` `$&` `` $` `` `$'` `$n`/`$nn` (two digits if that group exists,
//!   else one digit; `$0`, `$00`, out-of-range stay literal), `$<name>` (only when the regex
//!   has named groups; undefined -> ""; unterminated `$<` literal). Replacer functions get
//!   (match, p1..pn, offset, string[, groups]). replace/split/search on a non-global regex
//!   keep lastIndex; `search` restores it; `split` uses a sticky copy (lastIndex untouched).
//! * TypeErrors: "exec on non-RegExp", "exec called on a non-RegExp object" (test on a plain
//!   object without exec), "RegExp exec method returned something other than an Object or
//!   null", "RegExp.prototype getter called on a non-RegExp" (flag getters),
//!   "RegExp.prototype.source called on a non-RegExp", "RegExp.prototype.flags getter called
//!   on non-object", "RegExp.prototype.toString requires an object", "[Symbol.match] called on
//!   a non-object" (also replace/split/search/matchAll), "compile called on non-RegExp",
//!   "cannot supply flags when compiling a RegExp", "replaceAll must be called with a global
//!   RegExp", "String.prototype.matchAll called with a non-global RegExp", "argument must not
//!   be a regular expression" (startsWith/endsWith/includes), "RegExp.escape requires a
//!   string".
//! * `RegExp(re)` returns `re` itself; `new RegExp(re, flags)` copies; `RegExp(null)` ->
//!   /null/; flags `null` -> SyntaxError "invalid regular expression flag n". ES2025
//!   `RegExp.escape` is implemented (initial alnum -> `\xHH`, syntax chars backslashed,
//!   punctuators `,-=<>#&!%:;@~'`"` and spaces -> `\xHH`, line terminators/FEFF -> `\n`.. /
//!   `\uXXXX`, lone surrogates -> `\uXXXX`). Legacy statics exist: RegExp.$1..$9, input/$_,
//!   lastMatch/$&, lastParen/$+, leftContext/$`, rightContext/$' (accessors, updated by every
//!   successful builtin exec, also via replace/test; setting $1 throws "cannot set getter-only
//!   property '$1'" in strict code), plus leaked own props `__legacy_*`.

#![allow(dead_code)]

mod charset;
mod compiler;
mod parser;
mod vm;

#[cfg(test)]
mod tests;

use std::cell::RefCell;
use std::rc::Rc;

/// Parsed RegExp flags.
#[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
pub struct RegexFlags {
    pub has_indices: bool,
    pub global: bool,
    pub ignore_case: bool,
    pub multiline: bool,
    pub dot_all: bool,
    pub unicode: bool,
    pub unicode_sets: bool,
    pub sticky: bool,
}

impl RegexFlags {
    /// The canonical flags string ("dgimsuvy" order), as RegExp.prototype.flags returns.
    pub fn to_flags_string(&self) -> String {
        let mut s = String::new();
        if self.has_indices {
            s.push('d');
        }
        if self.global {
            s.push('g');
        }
        if self.ignore_case {
            s.push('i');
        }
        if self.multiline {
            s.push('m');
        }
        if self.dot_all {
            s.push('s');
        }
        if self.unicode {
            s.push('u');
        }
        if self.unicode_sets {
            s.push('v');
        }
        if self.sticky {
            s.push('y');
        }
        s
    }
}

/// Parses a flags string. `Err` is the SyntaxError message of the original runtime.
pub fn parse_flags(flags: &[u16]) -> Result<RegexFlags, String> {
    let mut f = RegexFlags::default();
    for ch in char::decode_utf16(flags.iter().copied()) {
        let ch = ch.unwrap_or('\u{FFFD}');
        let slot = match ch {
            'd' => &mut f.has_indices,
            'g' => &mut f.global,
            'i' => &mut f.ignore_case,
            'm' => &mut f.multiline,
            's' => &mut f.dot_all,
            'u' => &mut f.unicode,
            'v' => &mut f.unicode_sets,
            'y' => &mut f.sticky,
            _ => return Err(format!("invalid regular expression flag {}", ch)),
        };
        if *slot {
            return Err(format!("duplicate regular expression flag {}", ch));
        }
        *slot = true;
    }
    if f.unicode && f.unicode_sets {
        return Err("the u and v regular expression flags are mutually exclusive".into());
    }
    Ok(f)
}

struct Inner {
    prog: compiler::Program,
    flags: RegexFlags,
    group_names: Vec<(Vec<u16>, Vec<usize>)>,
    vm: RefCell<Option<vm::Vm>>,
}

/// A compiled regular expression (cheap to clone; shares the program).
#[derive(Clone)]
pub struct CompiledRegex {
    inner: Rc<Inner>,
}

impl std::fmt::Debug for CompiledRegex {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CompiledRegex").field("flags", &self.inner.flags).field("captures", &self.inner.prog.ncap).finish()
    }
}

/// Compiles `pattern` (UTF-16) with `flags`. `Err` is the exact SyntaxError message.
pub fn compile(pattern: &[u16], flags: RegexFlags) -> Result<CompiledRegex, String> {
    // Parsing/compilation recurse on the pattern's nesting depth; deeply nested patterns
    // are compiled on a helper thread with a large stack so they cannot overflow ours.
    let (prog, names) = if nesting_depth(pattern) > 200 {
        let pat = pattern.to_vec();
        std::thread::scope(|s| {
            std::thread::Builder::new()
                .stack_size(1 << 30)
                .spawn_scoped(s, move || compile_program(&pat, flags))
                .map_err(|e| e.to_string())?
                .join()
                .unwrap_or_else(|_| Err("regular expression too large".to_string()))
        })?
    } else {
        compile_program(pattern, flags)?
    };
    Ok(CompiledRegex { inner: Rc::new(Inner { prog, flags, group_names: names, vm: RefCell::new(None) }) })
}

type NamedGroups = Vec<(Vec<u16>, Vec<usize>)>;

fn compile_program(pattern: &[u16], flags: RegexFlags) -> Result<(compiler::Program, NamedGroups), String> {
    let unicode = flags.unicode || flags.unicode_sets;
    let p = parser::Parser::new(pattern, flags.unicode, flags.unicode_sets, flags.ignore_case, flags.multiline, flags.dot_all);
    let ast = p.parse()?;
    let prog = compiler::Compiler::compile(&ast, unicode)?;
    // group names in source order, duplicates merged
    let mut names: NamedGroups = Vec::new();
    let mut index: std::collections::HashMap<&[u16], usize> = std::collections::HashMap::new();
    for (name, g) in &ast.group_names {
        match index.get(&name[..]) {
            Some(&k) => names[k].1.push(*g as usize),
            None => {
                index.insert(&name[..], names.len());
                names.push((name.clone(), vec![*g as usize]));
            }
        }
    }
    Ok((prog, names))
}

/// Upper bound of the group / class nesting depth of a pattern.
fn nesting_depth(pattern: &[u16]) -> usize {
    let (mut d, mut max) = (0usize, 0usize);
    let mut i = 0;
    while i < pattern.len() {
        match pattern[i] {
            0x5C => i += 1,
            0x28 | 0x5B => {
                d += 1;
                max = max.max(d);
            }
            0x29 | 0x5D => d = d.saturating_sub(1),
            _ => {}
        }
        i += 1;
    }
    max
}

#[inline]
fn is_high(u: u16) -> bool {
    (u & 0xFC00) == 0xD800
}
#[inline]
fn is_low(u: u16) -> bool {
    (u & 0xFC00) == 0xDC00
}

impl CompiledRegex {
    /// Number of capturing groups (not counting group 0).
    pub fn capture_count(&self) -> usize {
        self.inner.prog.ncap
    }

    /// Named groups in source order: name -> group indices.
    pub fn group_names(&self) -> Vec<(Vec<u16>, Vec<usize>)> {
        self.inner.group_names.clone()
    }

    /// Borrowing variant of [`CompiledRegex::group_names`].
    pub fn group_names_ref(&self) -> &[(Vec<u16>, Vec<usize>)] {
        &self.inner.group_names
    }

    /// Does the pattern define any named group?
    pub fn has_named_groups(&self) -> bool {
        !self.inner.group_names.is_empty()
    }

    pub fn flags(&self) -> RegexFlags {
        self.inner.flags
    }

    /// RegExpBuiltinExec core: finds a match starting the search at `last_index`
    /// (sticky: only at `last_index`). Returns code-unit spans for groups
    /// 0..=capture_count.
    pub fn exec(&self, input: &[u16], last_index: usize) -> Option<Vec<Option<(usize, usize)>>> {
        let inner = &*self.inner;
        if input.len() >= u32::MAX as usize {
            // positions are stored as u32 internally
            return None;
        }
        let mut guard = inner.vm.try_borrow_mut().ok();
        let mut local;
        let vm: &mut vm::Vm = match guard.as_mut() {
            Some(g) => g.get_or_insert_with(vm::Vm::new),
            None => {
                local = vm::Vm::new();
                &mut local
            }
        };
        if !search(&inner.prog, inner.flags.sticky, vm, input, last_index) {
            return None;
        }
        let n = inner.prog.ncap + 1;
        let mut out = Vec::with_capacity(n);
        for g in 0..n {
            let (s, e) = (vm.caps[2 * g], vm.caps[2 * g + 1]);
            if s == u32::MAX || e == u32::MAX {
                out.push(None);
            } else {
                out.push(Some((s as usize, e as usize)));
            }
        }
        Some(out)
    }
}

/// The search loop over start positions. On success the VM's capture slots hold the
/// match.
fn search(prog: &compiler::Program, sticky: bool, vm: &mut vm::Vm, input: &[u16], last_index: usize) -> bool {
    let len = input.len();
    if last_index > len {
        return false;
    }
    let mut start = last_index;
    let unicode = prog.unicode;
    if unicode && start > 0 && start < len && is_low(input[start]) && is_high(input[start - 1]) {
        // inside a surrogate pair: the match attempt starts at the pair
        start -= 1;
    }
    // every match contains a member of `required` at or after its start: `req_next` is
    // the first such position >= the current candidate (found lazily, scanning forward)
    let find_req = |from: usize| -> Option<usize> {
        match &prog.required {
            None => Some(from),
            Some(req) => input[from..].iter().position(|&u| req.contains(u as u32)).map(|p| from + p),
        }
    };
    let mut req_next = match find_req(start) {
        None => return false,
        Some(p) => p,
    };
    if sticky {
        return vm.run(prog, input, start);
    }
    if prog.anchored {
        return start == 0 && vm.run(prog, input, 0);
    }
    let is_lt = |u: u16| u == 0x0A || u == 0x0D || u == 0x2028 || u == 0x2029;
    let mut s = start;
    loop {
        if s > req_next {
            match find_req(s) {
                None => return false,
                Some(p) => req_next = p,
            }
        }
        // candidate filters
        if !prog.prefix.is_empty() {
            let pre = &prog.prefix[..];
            let first = pre[0];
            let mut i = s;
            loop {
                if i + pre.len() > len {
                    return false;
                }
                if input[i] == first && input[i..i + pre.len()] == *pre {
                    break;
                }
                i += 1;
            }
            s = i;
        } else if let Some(first) = &prog.first {
            while s < len && !first.contains(input[s] as u32) {
                s += 1;
            }
            if s >= len {
                return false;
            }
        } else if prog.line_anchored {
            while s > 0 && s < len && !is_lt(input[s - 1]) {
                s += 1;
            }
            if s > 0 && !is_lt(input[s - 1]) {
                return false;
            }
        }
        if s > req_next {
            match find_req(s) {
                None => return false,
                Some(p) => req_next = p,
            }
        }
        if unicode && s > start && s < len && is_low(input[s]) && is_high(input[s - 1]) {
            // not a code point boundary
            s += 1;
            continue;
        }
        if vm.run(prog, input, s) {
            return true;
        }
        if let Some((m, _min)) = prog.lead_repeat {
            // the attempt at s failed: every start inside the run of `m` fails too
            let mut q = s;
            loop {
                let (c, nq) = if unicode && q + 1 < len && is_high(input[q]) && is_low(input[q + 1]) {
                    (0x10000 + (((input[q] as u32) - 0xD800) << 10) + ((input[q + 1] as u32) - 0xDC00), q + 2)
                } else if q < len {
                    (input[q] as u32, q + 1)
                } else {
                    break;
                };
                let ok = match m {
                    compiler::CharMatcher::Char(x) => c == x,
                    compiler::CharMatcher::Set(k) => prog.sets[k as usize].contains(c),
                };
                if !ok {
                    break;
                }
                q = nq;
            }
            if q > s {
                s = q;
            }
        }
        if s >= len {
            return false;
        }
        s += if unicode && s + 1 < len && is_high(input[s]) && is_low(input[s + 1]) { 2 } else { 1 };
    }
}

/// RegExp.prototype.source rendering of a pattern (EscapeRegExpPattern).
pub fn escape_source(pattern: &[u16]) -> Vec<u16> {
    if pattern.is_empty() {
        return "(?:)".encode_utf16().collect();
    }
    let mut out = Vec::with_capacity(pattern.len() + 4);
    let mut in_class = false;
    let mut i = 0;
    while i < pattern.len() {
        let c = pattern[i];
        match c {
            0x5C => {
                // backslash: copy the escape verbatim (unless followed by a line terminator)
                out.push(c);
                if i + 1 < pattern.len() {
                    let d = pattern[i + 1];
                    match d {
                        0x0A => out.extend("n".encode_utf16()),
                        0x0D => out.extend("r".encode_utf16()),
                        0x2028 => out.extend("u2028".encode_utf16()),
                        0x2029 => out.extend("u2029".encode_utf16()),
                        _ => out.push(d),
                    }
                    i += 2;
                    continue;
                }
            }
            0x2F => {
                if in_class {
                    out.push(c);
                } else {
                    out.extend("\\/".encode_utf16());
                }
            }
            0x5B => {
                in_class = true;
                out.push(c);
            }
            0x5D => {
                in_class = false;
                out.push(c);
            }
            0x0A => out.extend("\\n".encode_utf16()),
            0x0D => out.extend("\\r".encode_utf16()),
            0x2028 => out.extend("\\u2028".encode_utf16()),
            0x2029 => out.extend("\\u2029".encode_utf16()),
            _ => out.push(c),
        }
        i += 1;
    }
    out
}
