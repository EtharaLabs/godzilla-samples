//! Intl.Segmenter.
//!
//! Slots: `__sg: true`, `__sg_locale`, `__sg_granularity`.
//!
//! `segment(str)` precomputes every segment and returns a plain object with
//! own (non-enumerable) properties `__seg_records` (array of
//! `{segment, index, input[, isWordLike]}` records), `containing` and
//! `[Symbol.iterator]` (fresh functions per call).  `containing(n)` does
//! ToIntegerOrInfinity(n) and then scans `this.__seg_records` (ordinary
//! [[Get]]s) for the first record with `index <= n < index + segment.length`
//! (index via ToIntegerOrInfinity, length 0 unless the segment is a string);
//! the iterator is `this.__seg_records.values()`.
//!
//! Segmentation as observed in the original (locale-independent):
//! * grapheme: UAX #29 extended grapheme clusters on Unicode 17 data,
//!   without Prepend (Prepended_Concatenation_Mark format characters count
//!   as Control, the other Prepend letters as Other) and without the
//!   Indic-conjunct rule GB9c; SpacingMark is every gc=Mc character that is
//!   not Grapheme_Extend (no exceptions / additions); unassigned code points
//!   are Other; GB11 is `ExtPict (Extend | ZWJ)* ZWJ x ExtPict`.
//! * word: UAX #29 rules over a simplified class table: ASCII letters and
//!   *every* non-ASCII code point (except lone surrogates) are letters, ASCII
//!   digits are numeric, `.` and `'` MidNumLet, `:` MidLetter, `,` and `;`
//!   MidNum, U+0020 sequences stay together, everything else (other ASCII,
//!   controls, CR/LF, `_`, lone surrogates) is a single-unit segment.
//!   `isWordLike` = the segment starts with a letter or digit.
//! * sentence: a segment ends after each ASCII `.`, `!` or `?` plus the
//!   U+0020 / LF characters that follow it.
//! * the granularity slot is read back as: "word" -> word, missing /
//!   non-string / "grapheme" -> grapheme, any other string -> sentence.

use super::*;
use std::sync::OnceLock;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "Segmenter",
        0,
        sg_ctor,
        &[Member::Method("segment", 1, sg_segment), Member::Method("resolvedOptions", 0, sg_resolved_options)],
        true,
    );
}

fn sg_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_new(vm, a, "Segmenter")?;
    let requested = locale_list(vm, &a.arg(0))?;
    let opts = get_options(vm, &a.arg(1), OptionsMode::Strict)?;
    read_locale_matcher(vm, &opts)?;
    let gran = get_opt_str(vm, &opts, "granularity", &["grapheme", "word", "sentence"])?
        .unwrap_or_else(|| "grapheme".to_string());
    let r = resolve_locale(&requested);
    let o = alloc_instance(vm, a)?;
    set_slot(&o, "__sg", Value::Bool(true));
    set_slot(&o, "__sg_locale", Value::str(&r.base));
    set_slot(&o, "__sg_granularity", Value::str(&gran));
    Ok(Value::Obj(o))
}

fn sg_resolved_options(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__sg")?;
    let r = vm.new_object();
    for (key, slot_name) in [("locale", "__sg_locale"), ("granularity", "__sg_granularity")] {
        if let Some(v) = slot(&o, slot_name) {
            if !v.is_undefined() {
                r.set_str(key, v, WEC);
            }
        }
    }
    Ok(Value::Obj(r))
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Granularity {
    Grapheme,
    Word,
    Sentence,
}

fn sg_segment(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = branded_this(vm, &a.this, "__sg")?;
    let input = vm.to_string(&a.arg(0))?;
    let gran = match slot_str(&o, "__sg_granularity").as_deref() {
        None | Some("grapheme") => Granularity::Grapheme,
        Some("word") => Granularity::Word,
        Some(_) => Granularity::Sentence,
    };
    let units = input.units();
    let bounds = match gran {
        Granularity::Grapheme => grapheme_bounds(units),
        Granularity::Word => word_bounds(units),
        Granularity::Sentence => sentence_bounds(units),
    };
    let mut records = Vec::with_capacity(bounds.len().saturating_sub(1));
    for w in bounds.windows(2) {
        let (s, e) = (w[0], w[1]);
        let r = vm.new_object();
        r.set_str("segment", Value::Str(input.substring(s, e)), WEC);
        r.set_str("index", Value::Num(s as f64), WEC);
        r.set_str("input", Value::Str(input.clone()), WEC);
        if gran == Granularity::Word {
            let wl = matches!(word_class(first_cp(&units[s..e])), WordClass::Letter | WordClass::Numeric);
            r.set_str("isWordLike", Value::Bool(wl), WEC);
        }
        records.push(Value::Obj(r));
    }
    let arr = vm.new_array(records);
    let segs = vm.new_object();
    set_slot(&segs, "__seg_records", Value::Obj(arr));
    let containing = vm.native_fn("containing", 1, segments_containing);
    set_slot(&segs, "containing", Value::Obj(containing));
    let iter = vm.native_fn("[Symbol.iterator]", 0, segments_iterator);
    let key = PropKey::Sym(vm.intr.sym_iterator.clone());
    segs.set_prop(key, Value::Obj(iter), WC);
    Ok(Value::Obj(segs))
}

fn segments_containing(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_integer_or_infinity(&a.arg(0))?;
    let recs = vm.get_prop_of(&a.this, &PropKey::from_str("__seg_records"))?;
    let lenv = vm.get_prop_of(&recs, &PropKey::from_str("length"))?;
    let len = vm.to_length(&lenv)?;
    let mut i: u64 = 0;
    while i < len {
        let key = if i < u32::MAX as u64 { PropKey::from_index(i as u32) } else { PropKey::from_str(&i.to_string()) };
        i += 1;
        let r = vm.get_prop_of(&recs, &key)?;
        let idxv = vm.get_prop_of(&r, &PropKey::from_str("index"))?;
        let idx = vm.to_integer_or_infinity(&idxv)?;
        let seg = vm.get_prop_of(&r, &PropKey::from_str("segment"))?;
        let slen = match &seg {
            Value::Str(s) => s.len() as f64,
            _ => 0.0,
        };
        if idx <= n && n < idx + slen {
            return Ok(r);
        }
    }
    Ok(Value::Undefined)
}

fn segments_iterator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let recs = vm.get_prop_of(&a.this, &PropKey::from_str("__seg_records"))?;
    let values = vm.get_prop_of(&recs, &PropKey::from_str("values"))?;
    vm.call(&values, recs, &[])
}

// ============================================================================
// Code point helpers
// ============================================================================

/// Code points of a UTF-16 string with their unit offsets (lone surrogates
/// are their own code points).
fn code_points(units: &[u16]) -> Vec<(u32, usize)> {
    let mut out = Vec::with_capacity(units.len());
    let mut i = 0;
    while i < units.len() {
        let u = units[i] as u32;
        if (0xD800..0xDC00).contains(&u) && i + 1 < units.len() {
            let v = units[i + 1] as u32;
            if (0xDC00..0xE000).contains(&v) {
                out.push((0x10000 + ((u - 0xD800) << 10) + (v - 0xDC00), i));
                i += 2;
                continue;
            }
        }
        out.push((u, i));
        i += 1;
    }
    out
}

fn first_cp(units: &[u16]) -> u32 {
    code_points(&units[..units.len().min(2)]).first().map(|c| c.0).unwrap_or(0)
}

fn in_ranges(r: &[(u32, u32)], c: u32) -> bool {
    let i = r.partition_point(|&(_, e)| e < c);
    i < r.len() && r[i].0 <= c
}

fn prop_table(cell: &'static OnceLock<Vec<(u32, u32)>>, name: &str) -> &'static [(u32, u32)] {
    cell.get_or_init(|| crate::unicode::property_ranges(name, None).unwrap_or_default())
}

fn grapheme_extend(c: u32) -> bool {
    static T: OnceLock<Vec<(u32, u32)>> = OnceLock::new();
    in_ranges(prop_table(&T, "Grapheme_Extend"), c)
}

fn emoji_modifier(c: u32) -> bool {
    static T: OnceLock<Vec<(u32, u32)>> = OnceLock::new();
    in_ranges(prop_table(&T, "Emoji_Modifier"), c)
}

fn ext_pict(c: u32) -> bool {
    static T: OnceLock<Vec<(u32, u32)>> = OnceLock::new();
    in_ranges(prop_table(&T, "Extended_Pictographic"), c)
}

// ============================================================================
// Grapheme clusters
// ============================================================================

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Gcb {
    Other,
    CR,
    LF,
    Control,
    Extend,
    Zwj,
    SpacingMark,
    L,
    V,
    T,
    LV,
    LVT,
    RI,
    ExtPict,
}

fn gcb(c: u32) -> Gcb {
    use crate::unicode::GeneralCategory as G;
    match c {
        0x0D => return Gcb::CR,
        0x0A => return Gcb::LF,
        0x200D => return Gcb::Zwj,
        0xD800..=0xDFFF => return Gcb::Other,
        0x1100..=0x115F | 0xA960..=0xA97C => return Gcb::L,
        0x1160..=0x11A7 | 0xD7B0..=0xD7C6 => return Gcb::V,
        0x11A8..=0x11FF | 0xD7CB..=0xD7FB => return Gcb::T,
        0xAC00..=0xD7A3 => return if (c - 0xAC00) % 28 == 0 { Gcb::LV } else { Gcb::LVT },
        0x1F1E6..=0x1F1FF => return Gcb::RI,
        _ => {}
    }
    if c < 0x80 {
        return if c < 0x20 || c == 0x7F { Gcb::Control } else { Gcb::Other };
    }
    if grapheme_extend(c) || emoji_modifier(c) {
        return Gcb::Extend;
    }
    match crate::unicode::general_category(c) {
        G::Cc | G::Cf | G::Zl | G::Zp => return Gcb::Control,
        G::Mc => return Gcb::SpacingMark,
        _ => {}
    }
    if ext_pict(c) {
        return Gcb::ExtPict;
    }
    Gcb::Other
}

/// Segment boundaries (unit offsets, starting with 0 and ending with len).
fn grapheme_bounds(units: &[u16]) -> Vec<usize> {
    let cps = code_points(units);
    let mut bounds = vec![0];
    if cps.is_empty() {
        return bounds;
    }
    let mut prev = gcb(cps[0].0);
    let mut emoji = prev == Gcb::ExtPict;
    let mut ri_run = if prev == Gcb::RI { 1 } else { 0 };
    for &(c, at) in &cps[1..] {
        let cur = gcb(c);
        let join = match (prev, cur) {
            (Gcb::CR, Gcb::LF) => true,
            (Gcb::Control | Gcb::CR | Gcb::LF, _) => false,
            (_, Gcb::Control | Gcb::CR | Gcb::LF) => false,
            (Gcb::L, Gcb::L | Gcb::V | Gcb::LV | Gcb::LVT) => true,
            (Gcb::LV | Gcb::V, Gcb::V | Gcb::T) => true,
            (Gcb::LVT | Gcb::T, Gcb::T) => true,
            (_, Gcb::Extend | Gcb::Zwj | Gcb::SpacingMark) => true,
            (Gcb::Zwj, Gcb::ExtPict) => emoji,
            (Gcb::RI, Gcb::RI) => ri_run % 2 == 1,
            _ => false,
        };
        if !join {
            bounds.push(at);
        }
        emoji = cur == Gcb::ExtPict || (emoji && matches!(cur, Gcb::Extend | Gcb::Zwj));
        ri_run = if cur == Gcb::RI { ri_run + 1 } else { 0 };
        prev = cur;
    }
    bounds.push(units.len());
    bounds
}

// ============================================================================
// Words
// ============================================================================

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum WordClass {
    Letter,
    Numeric,
    MidLetter,
    MidNum,
    MidNumLet,
    Space,
    Other,
}

fn word_class(c: u32) -> WordClass {
    match c {
        0x41..=0x5A | 0x61..=0x7A => WordClass::Letter,
        0x30..=0x39 => WordClass::Numeric,
        0x3A => WordClass::MidLetter,
        0x2C | 0x3B => WordClass::MidNum,
        0x2E | 0x27 => WordClass::MidNumLet,
        0x20 => WordClass::Space,
        0..=0x7F => WordClass::Other,
        0xD800..=0xDFFF => WordClass::Other,
        _ => WordClass::Letter,
    }
}

fn word_bounds(units: &[u16]) -> Vec<usize> {
    use WordClass::*;
    let cps = code_points(units);
    let mut bounds = vec![0];
    let cls: Vec<WordClass> = cps.iter().map(|&(c, _)| word_class(c)).collect();
    let n = cls.len();
    for i in 1..n {
        let prev = cls[i - 1];
        let cur = cls[i];
        let next = if i + 1 < n { Some(cls[i + 1]) } else { None };
        let prev2 = if i >= 2 { Some(cls[i - 2]) } else { None };
        let alnum = |c: WordClass| matches!(c, Letter | Numeric);
        let join = (prev == Space && cur == Space)
            || (alnum(prev) && alnum(cur))
            || (prev == Letter && matches!(cur, MidLetter | MidNumLet) && next == Some(Letter))
            || (prev2 == Some(Letter) && matches!(prev, MidLetter | MidNumLet) && cur == Letter)
            || (prev == Numeric && matches!(cur, MidNum | MidNumLet) && next == Some(Numeric))
            || (prev2 == Some(Numeric) && matches!(prev, MidNum | MidNumLet) && cur == Numeric);
        if !join {
            bounds.push(cps[i].1);
        }
    }
    bounds.push(units.len());
    if units.is_empty() {
        bounds.truncate(1);
    }
    bounds
}

// ============================================================================
// Sentences
// ============================================================================

fn sentence_bounds(units: &[u16]) -> Vec<usize> {
    let mut bounds = vec![0];
    let n = units.len();
    let mut i = 0;
    while i < n {
        let u = units[i];
        i += 1;
        if u == b'.' as u16 || u == b'!' as u16 || u == b'?' as u16 {
            while i < n && (units[i] == 0x20 || units[i] == 0x0A) {
                i += 1;
            }
            bounds.push(i);
        }
    }
    if *bounds.last().unwrap() != n {
        bounds.push(n);
    }
    bounds
}
