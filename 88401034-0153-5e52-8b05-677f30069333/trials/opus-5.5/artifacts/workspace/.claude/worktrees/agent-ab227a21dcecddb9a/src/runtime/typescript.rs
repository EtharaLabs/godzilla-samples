// TypeScript type stripping ("strip" mode): type syntax is overwritten with spaces so that every
// remaining character keeps its position (line breaks are preserved). This is a lexical,
// pattern-based eraser, not a parser — it reproduces the behavior of the original runtime's
// stripper, including what it does not understand:
//
//  * a lexical mask protects comments, string literals and template literals (as a whole)
//    from pattern detection (regex literals are not recognized);
//  * declarations: `enum` / `namespace` are rejected, `interface ... { }` and `type ...` (up to
//    `;` or a line break) are erased, with a leading `export` / `import`;
//  * the first declarator of `let` / `const` / `var` loses its `: Type` annotation;
//  * every `( ... )` followed by `{`, `:` or `=>` is treated as a parameter list: `: Type`
//    annotations inside it are erased, and so is a `: ReturnType` after it;
//  * `as Type` / `satisfies Type` assertions are erased.
//
// Detection always runs on the original text; erasures go to a separate copy.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

const NL: u16 = b'\n' as u16;

fn c(ch: char) -> u16 {
    ch as u16
}

fn is_word(u: u16) -> bool {
    u < 128 && ((u as u8).is_ascii_alphanumeric() || u == c('_') || u == c('$'))
}

fn is_ident_start(u: u16) -> bool {
    u < 128 && ((u as u8).is_ascii_alphabetic() || u == c('_') || u == c('$'))
}

fn is_space(u: u16) -> bool {
    matches!(u, 0x09..=0x0d | 0x20 | 0xa0 | 0x1680 | 0x2000..=0x200a | 0x2028 | 0x2029 | 0x202f | 0x205f | 0x3000 | 0xfeff)
}

struct Stripper<'a> {
    s: &'a [u16],
    mask: Vec<bool>,
    out: Vec<u16>,
}

type R<T> = Result<T, String>;

impl<'a> Stripper<'a> {
    fn new(s: &'a [u16]) -> Stripper<'a> {
        let mask = lexical_mask(s);
        Stripper { s, mask, out: s.to_vec() }
    }

    fn at(&self, i: usize) -> u16 {
        self.s.get(i).copied().unwrap_or(0)
    }

    fn erase(&mut self, a: usize, b: usize) {
        let b = b.min(self.out.len());
        for i in a..b {
            if self.out[i] != NL {
                self.out[i] = c(' ');
            }
        }
    }

    /// `word` starts at `i` as a whole word, outside comments/strings/templates.
    fn word_at(&self, i: usize, word: &str) -> bool {
        if self.mask.get(i).copied().unwrap_or(true) {
            return false;
        }
        if i > 0 && is_word(self.s[i - 1]) {
            return false;
        }
        let w: Vec<u16> = word.encode_utf16().collect();
        if self.s.len() < i + w.len() || self.s[i..i + w.len()] != w[..] {
            return false;
        }
        !is_word(self.at(i + w.len()))
    }

    /// Start of a `prefix` keyword (e.g. `export`) right before position `i` (only whitespace
    /// between), or `i` itself.
    fn with_prefix(&self, i: usize, prefixes: &[&str]) -> usize {
        let mut j = i;
        while j > 0 && is_space(self.s[j - 1]) {
            j -= 1;
        }
        if j == i {
            return i;
        }
        for p in prefixes {
            let n = p.len();
            if j >= n && self.word_at(j - n, p) {
                return j - n;
            }
        }
        i
    }

    fn skip_space(&self, mut j: usize) -> usize {
        while j < self.s.len() && is_space(self.s[j]) {
            j += 1;
        }
        j
    }

    /// Scan a type from `from` to its end. Each bracket kind — `( )`, `[ ]`, `{ }` and `< >` —
    /// nests on its own counter (a closer never goes below zero and does not affect the other
    /// kinds); while all counters are zero, `stop` decides whether a character ends the type.
    fn scan_type(&self, from: usize, stop: &dyn Fn(u16) -> bool) -> usize {
        let mut depth = [0usize; 4];
        let mut j = from;
        while j < self.s.len() {
            if self.mask[j] {
                j += 1;
                continue;
            }
            let ch = self.s[j];
            if depth == [0; 4] && stop(ch) {
                return j;
            }
            const OPEN: [char; 4] = ['(', '[', '{', '<'];
            const CLOSE: [char; 4] = [')', ']', '}', '>'];
            for k in 0..4 {
                if ch == c(OPEN[k]) {
                    depth[k] += 1;
                } else if ch == c(CLOSE[k]) {
                    depth[k] = depth[k].saturating_sub(1);
                }
            }
            j += 1;
        }
        self.s.len()
    }

    fn check_not_empty(&self, a: usize, b: usize) -> R<()> {
        if self.s[a..b.min(self.s.len())].iter().all(|&u| is_space(u)) {
            return Err("Empty TypeScript type annotation".into());
        }
        Ok(())
    }

    // ---------------- declarations ----------------

    fn erase_declarations(&mut self) -> R<()> {
        let n = self.s.len();
        let mut i = 0;
        while i < n {
            if self.mask[i] || !is_word(self.s[i]) || (i > 0 && is_word(self.s[i - 1])) {
                i += 1;
                continue;
            }
            if self.word_at(i, "enum") {
                return Err("TypeScript enum declarations require transformation".into());
            }
            if self.word_at(i, "namespace") {
                return Err("TypeScript namespace declarations require transformation".into());
            }
            if self.word_at(i, "interface") {
                let start = self.with_prefix(i, &["export"]);
                // the body is the next '{' character, which must not be inside a comment/string
                let mut open = i + 9;
                while open < n && self.s[open] != c('{') {
                    open += 1;
                }
                if open >= n || self.mask[open] {
                    return Err("Invalid TypeScript interface declaration".into());
                }
                let close = self.match_brace(open)?;
                self.erase(start, close + 1);
                i = close + 1;
                continue;
            }
            if self.word_at(i, "type") {
                let start = self.with_prefix(i, &["export", "import"]);
                let end = self.scan_type(i + 4, &|ch| ch == c(';') || ch == NL);
                let end = if end < n && self.s[end] == c(';') { end + 1 } else { end };
                self.erase(start, end);
                i = end;
                continue;
            }
            // skip the rest of this word
            while i < n && is_word(self.s[i]) {
                i += 1;
            }
        }
        Ok(())
    }

    fn match_brace(&self, open: usize) -> R<usize> {
        let mut depth = 0usize;
        for j in open..self.s.len() {
            if self.mask[j] {
                continue;
            }
            if self.s[j] == c('{') {
                depth += 1;
            } else if self.s[j] == c('}') {
                depth -= 1;
                if depth == 0 {
                    return Ok(j);
                }
            }
        }
        Err("Unterminated '{' in TypeScript source".into())
    }

    // ---------------- variable annotations ----------------

    fn erase_variable_annotations(&mut self) -> R<()> {
        let n = self.s.len();
        let mut i = 0;
        while i < n {
            if self.mask[i] || !is_word(self.s[i]) || (i > 0 && is_word(self.s[i - 1])) {
                i += 1;
                continue;
            }
            let kw = ["let", "const", "var"].iter().find(|k| self.word_at(i, k)).map(|k| k.len());
            let kw_len = match kw {
                Some(l) => l,
                None => {
                    while i < n && is_word(self.s[i]) {
                        i += 1;
                    }
                    continue;
                }
            };
            let mut j = i + kw_len;
            i = j;
            if !is_space(self.at(j)) {
                continue;
            }
            j = self.skip_space(j);
            if !is_ident_start(self.at(j)) {
                continue;
            }
            while j < n && is_word(self.s[j]) {
                j += 1;
            }
            j = self.skip_space(j);
            if self.at(j) == c('?') {
                j = self.skip_space(j + 1);
            }
            if self.at(j) != c(':') || self.mask[j] {
                continue;
            }
            let colon = j;
            let start = if colon > 0 && self.s[colon - 1] == c('?') { colon - 1 } else { colon };
            let end = self.scan_type(colon + 1, &|ch| ch == c('=') || ch == c(';') || ch == c(',') || ch == NL);
            self.check_not_empty(colon + 1, end)?;
            self.erase(start, end);
            i = end;
        }
        Ok(())
    }

    // ---------------- functions ----------------

    fn match_paren(&self, open: usize) -> R<usize> {
        let mut depth = 0usize;
        for j in open..self.s.len() {
            if self.mask[j] {
                continue;
            }
            if self.s[j] == c('(') {
                depth += 1;
            } else if self.s[j] == c(')') {
                depth -= 1;
                if depth == 0 {
                    return Ok(j);
                }
            }
        }
        Err("Unterminated '(' in TypeScript source".into())
    }

    /// Parameter lists: a `( ... )` followed by `{`, `:` or `=>`. Groups nested inside a
    /// parameter list are not visited separately (scanning resumes after its `)`).
    fn erase_functions(&mut self) -> R<()> {
        let n = self.s.len();
        let mut p = 0;
        while p < n {
            if self.mask[p] || self.s[p] != c('(') {
                p += 1;
                continue;
            }
            let close = self.match_paren(p)?;
            let k = self.skip_space(close + 1);
            let next = self.at(k);
            let is_fn = next == c('{') || next == c(':') || (next == c('=') && self.at(k + 1) == c('>'));
            if !is_fn {
                p += 1;
                continue;
            }
            self.erase_params(p + 1, close)?;
            if next == c(':') {
                let end = self.scan_type(k + 1, &|ch| ch == c('{') || ch == c('=') || ch == c('>'));
                self.check_not_empty(k + 1, end)?;
                self.erase(k, end);
            }
            p = close + 1;
        }
        Ok(())
    }

    fn erase_params(&mut self, start: usize, close: usize) -> R<()> {
        let mut depth = 0usize;
        let mut j = start;
        while j < close {
            if self.mask[j] {
                j += 1;
                continue;
            }
            let ch = self.s[j];
            if ch == c('(') || ch == c('[') || ch == c('{') || ch == c('<') {
                depth += 1;
            } else if ch == c(')') || ch == c(']') || ch == c('}') || ch == c('>') {
                depth = depth.saturating_sub(1);
            } else if ch == c(':') && depth == 0 {
                let from = if j > start && self.s[j - 1] == c('?') { j - 1 } else { j };
                let end = self.scan_type(j + 1, &|ch| ch == c(',') || ch == c('=') || ch == c(')'));
                self.check_not_empty(j + 1, end)?;
                self.erase(from, end);
                j = end;
                continue;
            }
            j += 1;
        }
        Ok(())
    }

    // ---------------- assertions ----------------

    fn erase_assertions(&mut self) -> R<()> {
        let n = self.s.len();
        let mut i = 0;
        while i < n {
            if self.mask[i] || !is_word(self.s[i]) || (i > 0 && is_word(self.s[i - 1])) {
                i += 1;
                continue;
            }
            let kw = if self.word_at(i, "as") {
                2
            } else if self.word_at(i, "satisfies") {
                9
            } else {
                while i < n && is_word(self.s[i]) {
                    i += 1;
                }
                continue;
            };
            let end = self.scan_type(i + kw, &|ch| ch == c(';') || ch == c(',') || ch == c(')') || ch == c(']') || ch == c('}') || ch == NL);
            self.erase(i, end);
            i = end;
        }
        Ok(())
    }
}

/// Positions inside comments, string literals and template literals (including their
/// substitutions).
fn lexical_mask(s: &[u16]) -> Vec<bool> {
    let n = s.len();
    let mut mask = vec![false; n];
    let mut i = 0;
    while i < n {
        let end = token_end(s, i);
        if end > i {
            for m in mask.iter_mut().take(end).skip(i) {
                *m = true;
            }
            i = end;
        } else {
            i += 1;
        }
    }
    mask
}

/// End of a comment / string / template starting at `i`, or `i` if none starts there.
fn token_end(s: &[u16], i: usize) -> usize {
    let n = s.len();
    let at = |j: usize| s.get(j).copied().unwrap_or(0);
    let ch = at(i);
    if ch == c('/') && at(i + 1) == c('/') {
        let mut j = i + 2;
        while j < n && s[j] != NL {
            j += 1;
        }
        return j;
    }
    if ch == c('/') && at(i + 1) == c('*') {
        let mut j = i + 2;
        while j < n {
            if s[j] == c('*') && at(j + 1) == c('/') {
                return j + 2;
            }
            j += 1;
        }
        return n;
    }
    if ch == c('"') || ch == c('\'') {
        let mut j = i + 1;
        while j < n {
            if s[j] == c('\\') {
                j += 2;
                continue;
            }
            if s[j] == ch {
                return j + 1;
            }
            j += 1;
        }
        return n;
    }
    if ch == c('`') {
        return template_end(s, i);
    }
    i
}

fn template_end(s: &[u16], i: usize) -> usize {
    let n = s.len();
    let mut j = i + 1;
    while j < n {
        let ch = s[j];
        if ch == c('\\') {
            j += 2;
            continue;
        }
        if ch == c('`') {
            return j + 1;
        }
        if ch == c('$') && s.get(j + 1).copied() == Some(c('{')) {
            // substitution: nested braces, strings, templates and comments
            j += 2;
            let mut depth = 0usize;
            while j < n {
                let e = token_end(s, j);
                if e > j {
                    j = e;
                    continue;
                }
                if s[j] == c('{') {
                    depth += 1;
                } else if s[j] == c('}') {
                    if depth == 0 {
                        break;
                    }
                    depth -= 1;
                }
                j += 1;
            }
            j += 1;
            continue;
        }
        j += 1;
    }
    n
}

/// Strip TypeScript types from UTF-16 source; Err carries a SyntaxError message.
pub fn strip_units(src: &[u16]) -> Result<Vec<u16>, String> {
    let mut st = Stripper::new(src);
    st.erase_declarations()?;
    st.erase_variable_annotations()?;
    st.erase_functions()?;
    st.erase_assertions()?;
    Ok(st.out)
}

pub fn strip_types(src: &str) -> Result<String, String> {
    let units: Vec<u16> = src.encode_utf16().collect();
    let out = strip_units(&units)?;
    Ok(String::from_utf16_lossy(&out))
}

/// `stripTypeScriptTypes(code, options = {})` (global `__lumenStripTypeScriptTypes` and
/// `module.stripTypeScriptTypes`).
pub fn strip_typescript_types(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let code = match a.arg(0) {
        Value::Str(s) => s,
        _ => return vm.throw_type("The \"code\" argument must be of type string"),
    };
    let options = match a.arg(1) {
        Value::Undefined => None,
        Value::Obj(o) if !o.is_callable() => Some(o.clone()),
        _ => return vm.throw_type("The \"options\" argument must be of type object"),
    };
    let mut source_url = Value::Undefined;
    if let Some(o) = &options {
        let mode = vm.get_str(o, "mode")?;
        if !mode.is_undefined() && !matches!(&mode, Value::Str(s) if s.to_rust_string() == "strip") {
            return vm.throw_type("Only TypeScript strip mode is supported");
        }
        if vm.get_str(o, "sourceMap")?.truthy() {
            return vm.throw_type("sourceMap is not available in TypeScript strip mode");
        }
        source_url = vm.get_str(o, "sourceUrl")?;
    }
    let mut out = match strip_units(code.units()) {
        Ok(u) => u,
        Err(msg) => return vm.throw_syntax(msg),
    };
    if !source_url.is_undefined() {
        let u = vm.to_string(&source_url)?;
        out.extend("\n\n//# sourceURL=".encode_utf16());
        out.extend_from_slice(u.units());
        out.push(c(';'));
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

pub fn make_strip_fn(vm: &mut Vm) -> Obj {
    vm.native_fn("stripTypeScriptTypes", 1, strip_typescript_types)
}
