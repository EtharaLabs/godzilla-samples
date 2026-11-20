// RegExp objects and regex-based String methods.

use crate::object::*;
use crate::regexp::{self, CompiledRegex, RegexFlags};
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let proto = vm.intr.regexp_proto.clone();
    let ctor = vm.native_ctor("RegExp", 2, regexp_ctor, &proto);
    vm.def_sym_getter(&ctor, &vm.intr.sym_species.clone(), "[Symbol.species]", |_vm, a| Ok(a.this.clone()));
    vm.def_method(&ctor, "escape", 1, regexp_escape);
    // legacy statics
    for (name, idx) in [("$1", 1), ("$2", 2), ("$3", 3), ("$4", 4), ("$5", 5), ("$6", 6), ("$7", 7), ("$8", 8), ("$9", 9)] {
        let g = vm.native_closure("get", 0, legacy_group, vec![Value::Num(idx as f64)]);
        ctor.set_accessor(PropKey::from_str(name), Some(g), None, CONFIGURABLE);
    }
    for (names, kind) in [(["input", "$_"], 0), (["lastMatch", "$&"], 1), (["lastParen", "$+"], 2), (["leftContext", "$`"], 3), (["rightContext", "$'"], 4)] {
        for n in names {
            // (the reference engine names these accessors plain "get"/"set")
            let g = vm.native_closure("get", 0, legacy_other, vec![Value::Num(kind as f64)]);
            let s = vm.native_closure("set", 1, legacy_set_input, vec![Value::Num(kind as f64)]);
            ctor.set_accessor(PropKey::from_str(n), Some(g), if kind == 0 { Some(s) } else { None }, CONFIGURABLE);
        }
    }
    vm.def_getter(&proto, "source", source_getter);
    vm.def_getter(&proto, "flags", flags_getter);
    for (n, f) in [
        ("global", get_global as NativeFn),
        ("ignoreCase", get_ignore_case),
        ("multiline", get_multiline),
        ("dotAll", get_dot_all),
        ("sticky", get_sticky),
        ("unicode", get_unicode),
        ("hasIndices", get_has_indices),
        ("unicodeSets", get_unicode_sets),
    ] {
        vm.def_getter(&proto, n, f);
    }
    vm.def_method(&proto, "compile", 2, compile);
    vm.def_method(&proto, "exec", 1, exec);
    vm.def_method(&proto, "test", 1, test);
    vm.def_method(&proto, "toString", 0, to_string);
    move_to_end(&proto, &vm.intr.key_constructor.clone());
    vm.def_sym_method(&proto, &vm.intr.sym_match.clone(), "[Symbol.match]", 1, sym_match);
    vm.def_sym_method(&proto, &vm.intr.sym_replace.clone(), "[Symbol.replace]", 2, sym_replace);
    vm.def_sym_method(&proto, &vm.intr.sym_search.clone(), "[Symbol.search]", 1, sym_search);
    vm.def_sym_method(&proto, &vm.intr.sym_split.clone(), "[Symbol.split]", 2, sym_split);
    vm.def_sym_method(&proto, &vm.intr.sym_match_all.clone(), "[Symbol.matchAll]", 1, sym_match_all);
    let rsip = vm.intr.regexp_string_iterator_proto.clone();
    vm.def_method(&rsip, "next", 0, regexp_string_iter_next);
    vm.set_tag(&rsip, "RegExp String Iterator");
    vm.def_global("RegExp", Value::Obj(ctor));
}

pub struct LegacyState {
    pub input: JsStr,
    pub groups: Vec<Option<(usize, usize)>>,
}

thread_local! {
    static LEGACY: std::cell::RefCell<Option<LegacyState>> = std::cell::RefCell::new(None);
}

fn legacy_group(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let i = a.slot(0).as_num().unwrap() as usize;
    Ok(LEGACY.with(|l| match &*l.borrow() {
        Some(st) => match st.groups.get(i) {
            Some(Some((s, e))) => Value::Str(st.input.substring(*s, *e)),
            _ => Value::str(""),
        },
        None => Value::str(""),
    }))
}

fn legacy_other(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let k = a.slot(0).as_num().unwrap() as usize;
    Ok(LEGACY.with(|l| match &*l.borrow() {
        Some(st) => {
            let m = st.groups.first().cloned().flatten();
            match k {
                0 => Value::Str(st.input.clone()),
                1 => m.map(|(s, e)| Value::Str(st.input.substring(s, e))).unwrap_or(Value::str("")),
                2 => {
                    if st.groups.len() > 1 {
                        match st.groups.last().cloned().flatten() {
                            Some((s, e)) => Value::Str(st.input.substring(s, e)),
                            None => Value::str(""),
                        }
                    } else {
                        Value::str("")
                    }
                }
                3 => m.map(|(s, _)| Value::Str(st.input.substring(0, s))).unwrap_or(Value::str("")),
                _ => m.map(|(_, e)| Value::Str(st.input.substring(e, st.input.len()))).unwrap_or(Value::str("")),
            }
        }
        None => Value::str(""),
    }))
}

fn legacy_set_input(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    LEGACY.with(|l| {
        let mut b = l.borrow_mut();
        match &mut *b {
            Some(st) => st.input = s,
            None => *b = Some(LegacyState { input: s, groups: Vec::new() }),
        }
    });
    Ok(Value::Undefined)
}

pub fn regexp_alloc(vm: &mut Vm, proto: Obj, pattern: JsStr, flags: JsStr) -> JsResult<Obj> {
    let rf = match regexp::parse_flags(flags.units()) {
        Ok(f) => f,
        Err(m) => return vm.throw_syntax(m),
    };
    let compiled = match regexp::compile(pattern.units(), rf) {
        Ok(c) => c,
        Err(m) => return vm.throw_syntax(m),
    };
    let o = Obj::with_class(Some(proto), ObjKind::RegExp(Box::new(RegExpData { source: pattern, flags: JsStr::from_str(&rf.to_flags_string()), compiled, rflags: rf, legacy: true })), "RegExp");
    o.set_prop(PropKey::from_str("lastIndex"), Value::Num(0.0), WRITABLE);
    Ok(o)
}

pub fn regexp_create(vm: &mut Vm, pattern: &Value, flags: &Value) -> JsResult<Value> {
    let p = if pattern.is_undefined() { JsStr::empty() } else { vm.to_string(pattern)? };
    let f = if flags.is_undefined() { JsStr::empty() } else { vm.to_string(flags)? };
    let proto = vm.intr.regexp_proto.clone();
    Ok(Value::Obj(regexp_alloc(vm, proto, p, f)?))
}

fn is_regexp(vm: &mut Vm, v: &Value) -> JsResult<bool> {
    if let Value::Obj(o) = v {
        let m = vm.get(o, &PropKey::Sym(vm.intr.sym_match.clone()), v)?;
        if !m.is_undefined() {
            return Ok(m.truthy());
        }
        return Ok(matches!(o.borrow().kind, ObjKind::RegExp(_)));
    }
    Ok(false)
}

fn regexp_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let pattern = a.arg(0);
    let flags = a.arg(1);
    let pattern_is_re = is_regexp(vm, &pattern)?;
    if a.new_target.is_none() && pattern_is_re && flags.is_undefined() {
        let pc = vm.get_prop_of(&pattern, &vm.intr.key_constructor.clone())?;
        if let Value::Obj(pco) = &pc {
            if pco.ptr_eq(a.callee) {
                return Ok(pattern);
            }
        }
    }
    let (p, f) = if let Value::Obj(po) = &pattern {
        let data = match &po.borrow().kind {
            ObjKind::RegExp(r) => Some((r.source.clone(), r.flags.clone())),
            _ => None,
        };
        if let Some((src, fl)) = data {
            (Value::Str(src), if flags.is_undefined() { Value::Str(fl) } else { flags.clone() })
        } else if pattern_is_re {
            let src = vm.get_str(po, "source")?;
            let fl = if flags.is_undefined() { vm.get_str(po, "flags")? } else { flags.clone() };
            (src, fl)
        } else {
            (pattern.clone(), flags.clone())
        }
    } else {
        (pattern.clone(), flags.clone())
    };
    let nt = a.new_target.clone().or_else(|| Some(a.callee.clone()));
    let proto = vm.proto_from_nt(&nt, &vm.intr.regexp_proto.clone())?;
    let ps = if p.is_undefined() { JsStr::empty() } else { vm.to_string(&p)? };
    let fs = if f.is_undefined() { JsStr::empty() } else { vm.to_string(&f)? };
    Ok(Value::Obj(regexp_alloc(vm, proto, ps, fs)?))
}

fn regexp_escape(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = match a.arg(0) {
        Value::Str(s) => s,
        _ => return vm.throw_type("RegExp.escape requires a string"),
    };
    let mut out: Vec<u16> = Vec::new();
    let u = s.units();
    for (i, &c) in u.iter().enumerate() {
        let ch = c;
        let is_alnum = (ch as u8 as u16 == ch) && (ch as u8).is_ascii_alphanumeric();
        if i == 0 && is_alnum {
            out.extend(format!("\\x{:02x}", ch).encode_utf16());
            continue;
        }
        if ch < 128 && "^$\\.*+?()[]{}|/".contains(ch as u8 as char) {
            out.push(b'\\' as u16);
            out.push(ch);
        } else if ch < 128 && ",-=<>#&!%:;@~'`\"".contains(ch as u8 as char) {
            out.extend(format!("\\x{:02x}", ch).encode_utf16());
        } else if ch == 9 {
            out.extend("\\t".encode_utf16());
        } else if ch == 10 {
            out.extend("\\n".encode_utf16());
        } else if ch == 11 {
            out.extend("\\v".encode_utf16());
        } else if ch == 12 {
            out.extend("\\f".encode_utf16());
        } else if ch == 13 {
            out.extend("\\r".encode_utf16());
        } else if ch == 32 {
            out.extend("\\x20".encode_utf16());
        } else if crate::numconv::is_js_whitespace(ch) || ch == 0x2028 || ch == 0x2029 || ch == 0xFEFF {
            out.extend(format!("\\u{:04x}", ch).encode_utf16());
        } else if (0xD800..0xE000).contains(&ch) {
            let paired = if ch < 0xDC00 {
                u.get(i + 1).map_or(false, |n| (0xDC00..0xE000).contains(n))
            } else {
                i > 0 && (0xD800..0xDC00).contains(&u[i - 1])
            };
            if paired {
                out.push(ch);
            } else {
                out.extend(format!("\\u{:04x}", ch).encode_utf16());
            }
        } else {
            out.push(ch);
        }
    }
    Ok(Value::Str(JsStr::from_units(out)))
}

fn re_data(v: &Value) -> Option<(CompiledRegex, RegexFlags, JsStr, JsStr)> {
    match v {
        Value::Obj(o) => match &o.borrow().kind {
            ObjKind::RegExp(r) => Some((r.compiled.clone(), r.rflags, r.source.clone(), r.flags.clone())),
            _ => None,
        },
        _ => None,
    }
}

fn source_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        if o.ptr_eq(&vm.intr.regexp_proto) {
            return Ok(Value::str("(?:)"));
        }
    }
    match re_data(&a.this) {
        Some((_, _, src, _)) => Ok(Value::Str(JsStr::from_units(regexp::escape_source(src.units())))),
        None => vm.throw_type("RegExp.prototype.source called on a non-RegExp"),
    }
}

fn flags_getter(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("RegExp.prototype.flags getter called on non-object"),
    };
    let mut s = String::new();
    for (name, ch) in [("hasIndices", 'd'), ("global", 'g'), ("ignoreCase", 'i'), ("multiline", 'm'), ("dotAll", 's'), ("unicode", 'u'), ("unicodeSets", 'v'), ("sticky", 'y')] {
        if vm.get_str(&o, name)?.truthy() {
            s.push(ch);
        }
    }
    Ok(Value::str(&s))
}

fn flag_getter(vm: &mut Vm, a: &Args, f: fn(&RegexFlags) -> bool) -> JsResult<Value> {
    if let Value::Obj(o) = &a.this {
        if o.ptr_eq(&vm.intr.regexp_proto) {
            return Ok(Value::Undefined);
        }
    }
    match re_data(&a.this) {
        Some((_, rf, _, _)) => Ok(Value::Bool(f(&rf))),
        None => vm.throw_type("RegExp.prototype getter called on a non-RegExp"),
    }
}

fn get_global(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.global)
}
fn get_ignore_case(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.ignore_case)
}
fn get_multiline(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.multiline)
}
fn get_dot_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.dot_all)
}
fn get_sticky(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.sticky)
}
fn get_unicode(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.unicode)
}
fn get_has_indices(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.has_indices)
}
fn get_unicode_sets(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    flag_getter(vm, a, |f| f.unicode_sets)
}

fn compile(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::RegExp(_)) => o.clone(),
        _ => return vm.throw_type("compile called on non-RegExp"),
    };
    let pattern = a.arg(0);
    let flags = a.arg(1);
    let (p, f) = match re_data(&pattern) {
        Some((_, _, src, fl)) => {
            if !flags.is_undefined() {
                return vm.throw_type("cannot supply flags when compiling a RegExp");
            }
            (src, fl)
        }
        None => (
            if pattern.is_undefined() { JsStr::empty() } else { vm.to_string(&pattern)? },
            if flags.is_undefined() { JsStr::empty() } else { vm.to_string(&flags)? },
        ),
    };
    let rf = match regexp::parse_flags(f.units()) {
        Ok(x) => x,
        Err(m) => return vm.throw_syntax(m),
    };
    let compiled = match regexp::compile(p.units(), rf) {
        Ok(c) => c,
        Err(m) => return vm.throw_syntax(m),
    };
    if let ObjKind::RegExp(r) = &mut o.borrow_mut().kind {
        r.source = p;
        r.flags = JsStr::from_str(&rf.to_flags_string());
        r.compiled = compiled;
        r.rflags = rf;
    }
    let ov = Value::Obj(o.clone());
    vm.set_or_throw(&o, PropKey::from_str("lastIndex"), Value::Num(0.0))?;
    Ok(ov)
}

fn to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("RegExp.prototype.toString requires an object"),
    };
    let src = vm.get_str(&o, "source")?;
    let src = vm.to_string(&src)?;
    let fl = vm.get_str(&o, "flags")?;
    let fl = vm.to_string(&fl)?;
    Ok(Value::str(&format!("/{}/{}", src, fl)))
}

fn last_index_key() -> PropKey {
    PropKey::from_str("lastIndex")
}

fn set_last_index(vm: &mut Vm, o: &Obj, v: f64) -> JsResult<()> {
    // fast path for own writable data property
    {
        let mut b = o.borrow_mut();
        if let ObjKind::RegExp(_) = b.kind {
            if let Some(Prop::Data { value, flags }) = b.props.get_mut(&last_index_key()) {
                if *flags & WRITABLE != 0 {
                    *value = Value::Num(v);
                    return Ok(());
                }
            }
        }
    }
    vm.set_or_throw(o, last_index_key(), Value::Num(v))
}

/// RegExpBuiltinExec: returns match spans or None
pub fn builtin_exec_raw(vm: &mut Vm, o: &Obj, s: &JsStr) -> JsResult<Option<Vec<Option<(usize, usize)>>>> {
    let (compiled, rf) = match &o.borrow().kind {
        ObjKind::RegExp(r) => (r.compiled.clone(), r.rflags),
        _ => unreachable!(),
    };
    let li = {
        let b = o.borrow();
        match b.props.get(&last_index_key()) {
            Some(Prop::Data { value: Value::Num(n), .. }) => Some(*n),
            _ => None,
        }
    };
    let li = match li {
        Some(n) => crate::ops::integer_or_infinity(n).max(0.0),
        None => {
            let v = vm.get(o, &last_index_key(), &Value::Obj(o.clone()))?;
            vm.to_length(&v)? as f64
        }
    };
    let global_or_sticky = rf.global || rf.sticky;
    let start = if global_or_sticky { li } else { 0.0 };
    if start > s.len() as f64 {
        if global_or_sticky {
            set_last_index(vm, o, 0.0)?;
        }
        return Ok(None);
    }
    let r = compiled.exec(s.units(), start as usize);
    match r {
        None => {
            if global_or_sticky {
                set_last_index(vm, o, 0.0)?;
            }
            Ok(None)
        }
        Some(spans) => {
            if global_or_sticky {
                let end = spans[0].map(|(_, e)| e).unwrap_or(0);
                set_last_index(vm, o, end as f64)?;
            }
            LEGACY.with(|l| *l.borrow_mut() = Some(LegacyState { input: s.clone(), groups: spans.clone() }));
            Ok(Some(spans))
        }
    }
}

pub fn build_exec_result(vm: &mut Vm, o: &Obj, s: &JsStr, spans: &[Option<(usize, usize)>]) -> Value {
    let (compiled, rf) = match &o.borrow().kind {
        ObjKind::RegExp(r) => (r.compiled.clone(), r.rflags),
        _ => unreachable!(),
    };
    let vals: Vec<Value> = spans.iter().map(|sp| match sp {
        Some((a, b)) => Value::Str(s.substring(*a, *b)),
        None => Value::Undefined,
    }).collect();
    let arr = vm.new_array(vals);
    let idx = spans[0].map(|(a, _)| a).unwrap_or(0);
    arr.set_prop(PropKey::from_str("index"), Value::Num(idx as f64), WEC);
    arr.set_prop(PropKey::from_str("input"), Value::Str(s.clone()), WEC);
    let groups = if compiled.has_named_groups() {
        let g = Obj::new(None, ObjKind::Ordinary);
        for (name, idxs) in compiled.group_names() {
            let mut v = Value::Undefined;
            for i in &idxs {
                if let Some(Some((a, b))) = spans.get(*i) {
                    v = Value::Str(s.substring(*a, *b));
                    break;
                }
            }
            g.set_prop(PropKey::Str(JsStr::from_units(name)), v, WEC);
        }
        Value::Obj(g)
    } else {
        Value::Undefined
    };
    arr.set_prop(PropKey::from_str("groups"), groups.clone(), WEC);
    if rf.has_indices {
        let ivals: Vec<Value> = spans
            .iter()
            .map(|sp| match sp {
                Some((a, b)) => Value::Obj(vm.new_array(vec![Value::Num(*a as f64), Value::Num(*b as f64)])),
                None => Value::Undefined,
            })
            .collect();
        let indices = vm.new_array(ivals);
        let ig = if compiled.has_named_groups() {
            let g = Obj::new(None, ObjKind::Ordinary);
            for (name, idxs) in compiled.group_names() {
                let mut v = Value::Undefined;
                for i in &idxs {
                    if let Some(Some((a, b))) = spans.get(*i) {
                        v = Value::Obj(vm.new_array(vec![Value::Num(*a as f64), Value::Num(*b as f64)]));
                        break;
                    }
                }
                g.set_prop(PropKey::Str(JsStr::from_units(name)), v, WEC);
            }
            Value::Obj(g)
        } else {
            Value::Undefined
        };
        indices.set_prop(PropKey::from_str("groups"), ig, WEC);
        arr.set_prop(PropKey::from_str("indices"), Value::Obj(indices), WEC);
    }
    Value::Obj(arr)
}

fn builtin_exec(vm: &mut Vm, o: &Obj, s: &JsStr) -> JsResult<Value> {
    match builtin_exec_raw(vm, o, s)? {
        Some(spans) => Ok(build_exec_result(vm, o, s, &spans)),
        None => Ok(Value::Null),
    }
}

/// Is the exec method the builtin one (allows fast paths)?
fn has_builtin_exec(vm: &mut Vm, o: &Obj) -> bool {
    if !matches!(o.borrow().kind, ObjKind::RegExp(_)) {
        return false;
    }
    if o.borrow().props.contains(&PropKey::from_str("exec")) {
        return false;
    }
    let proto = o.borrow().proto.clone();
    match proto {
        Some(p) if p.ptr_eq(&vm.intr.regexp_proto) => {
            let e = p.borrow().props.get(&PropKey::from_str("exec")).cloned();
            matches!(e, Some(Prop::Data { value: Value::Obj(f), .. }) if matches!(&f.borrow().kind, ObjKind::Native(n) if n.f as usize == exec as usize))
        }
        _ => false,
    }
}

pub fn regexp_exec(vm: &mut Vm, o: &Obj, s: &JsStr) -> JsResult<Value> {
    if has_builtin_exec(vm, o) {
        return builtin_exec(vm, o, s);
    }
    let ov = Value::Obj(o.clone());
    let e = vm.get(o, &PropKey::from_str("exec"), &ov)?;
    if e.is_callable() {
        let r = vm.call(&e, ov, &[Value::Str(s.clone())])?;
        if !r.is_object() && !r.is_null() {
            return vm.throw_type("RegExp exec method returned something other than an Object or null");
        }
        return Ok(r);
    }
    if !matches!(o.borrow().kind, ObjKind::RegExp(_)) {
        return vm.throw_type("exec called on a non-RegExp object");
    }
    builtin_exec(vm, o, s)
}

fn exec(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) if matches!(o.borrow().kind, ObjKind::RegExp(_)) => o.clone(),
        _ => return vm.throw_type("exec on non-RegExp"),
    };
    let s = vm.to_string(&a.arg(0))?;
    builtin_exec(vm, &o, &s)
}

fn test(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("RegExp.prototype.test requires an object"),
    };
    let s = vm.to_string(&a.arg(0))?;
    if has_builtin_exec(vm, &o) {
        return Ok(Value::Bool(builtin_exec_raw(vm, &o, &s)?.is_some()));
    }
    let r = regexp_exec(vm, &o, &s)?;
    Ok(Value::Bool(!r.is_null()))
}

fn this_re_obj(vm: &mut Vm, a: &Args, name: &str) -> JsResult<Obj> {
    match &a.this {
        Value::Obj(o) => Ok(o.clone()),
        _ => vm.throw_type(format!("[Symbol.{}] called on a non-object", name)),
    }
}

fn advance_index(s: &JsStr, i: usize, unicode: bool) -> usize {
    if !unicode || i + 1 >= s.len() {
        return i + 1;
    }
    let u = s.units();
    if (0xD800..0xDC00).contains(&u[i]) && (0xDC00..0xE000).contains(&u[i + 1]) {
        i + 2
    } else {
        i + 1
    }
}

fn flags_of(vm: &mut Vm, o: &Obj) -> JsResult<String> {
    if let Some((_, rf, _, _)) = re_data(&Value::Obj(o.clone())) {
        if has_builtin_exec(vm, o) && !o.borrow().props.contains(&PropKey::from_str("flags")) {
            return Ok(rf.to_flags_string());
        }
    }
    let f = vm.get_str(o, "flags")?;
    Ok(vm.to_string(&f)?.to_rust_string())
}

fn sym_match(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rx = this_re_obj(vm, a, "match")?;
    let s = vm.to_string(&a.arg(0))?;
    let flags = flags_of(vm, &rx)?;
    if !flags.contains('g') {
        return regexp_exec(vm, &rx, &s);
    }
    let full_unicode = flags.contains('u') || flags.contains('v');
    set_last_index(vm, &rx, 0.0)?;
    let mut out = Vec::new();
    let fast = has_builtin_exec(vm, &rx);
    loop {
        if fast {
            match builtin_exec_raw(vm, &rx, &s)? {
                None => break,
                Some(spans) => {
                    let (st, en) = spans[0].unwrap();
                    out.push(Value::Str(s.substring(st, en)));
                    if st == en {
                        let li = advance_index(&s, en, full_unicode);
                        set_last_index(vm, &rx, li as f64)?;
                    }
                }
            }
            continue;
        }
        let r = regexp_exec(vm, &rx, &s)?;
        let ro = match &r {
            Value::Null => break,
            Value::Obj(o) => o.clone(),
            _ => break,
        };
        let m = vm.get(&ro, &PropKey::from_index(0), &r)?;
        let ms = vm.to_string(&m)?;
        if ms.is_empty() {
            let li = vm.get(&rx, &last_index_key(), &Value::Obj(rx.clone()))?;
            let li = vm.to_length(&li)? as usize;
            set_last_index(vm, &rx, advance_index(&s, li, full_unicode) as f64)?;
        }
        out.push(Value::Str(ms));
    }
    if out.is_empty() {
        return Ok(Value::Null);
    }
    Ok(Value::Obj(vm.new_array(out)))
}

/// GetSubstitution
pub fn get_substitution(vm: &mut Vm, matched: &JsStr, s: &JsStr, position: usize, captures: &[Value], named: &Value, replacement: &JsStr) -> JsResult<JsStr> {
    let r = replacement.units();
    let su = s.units();
    let m = captures.len();
    let mut out: Vec<u16> = Vec::new();
    let mut i = 0;
    let tail_pos = (position + matched.len()).min(su.len());
    while i < r.len() {
        let c = r[i];
        if c == b'$' as u16 && i + 1 < r.len() {
            let n = r[i + 1];
            match n {
                0x24 => {
                    out.push(0x24);
                    i += 2;
                    continue;
                }
                0x26 => {
                    out.extend_from_slice(matched.units());
                    i += 2;
                    continue;
                }
                0x60 => {
                    out.extend_from_slice(&su[..position.min(su.len())]);
                    i += 2;
                    continue;
                }
                0x27 => {
                    out.extend_from_slice(&su[tail_pos..]);
                    i += 2;
                    continue;
                }
                0x30..=0x39 => {
                    let d1 = (n - 0x30) as usize;
                    let two = if i + 2 < r.len() && (0x30..=0x39).contains(&r[i + 2]) { Some(d1 * 10 + (r[i + 2] - 0x30) as usize) } else { None };
                    if let Some(nn) = two {
                        if nn >= 1 && nn <= m {
                            if let Value::Str(cs) = &captures[nn - 1] {
                                out.extend_from_slice(cs.units());
                            }
                            i += 3;
                            continue;
                        }
                    }
                    if d1 >= 1 && d1 <= m {
                        if let Value::Str(cs) = &captures[d1 - 1] {
                            out.extend_from_slice(cs.units());
                        }
                        i += 2;
                        continue;
                    }
                    out.push(c);
                    i += 1;
                    continue;
                }
                0x3c => {
                    if named.is_undefined() {
                        out.push(c);
                        i += 1;
                        continue;
                    }
                    let close = r[i + 2..].iter().position(|&x| x == 0x3e);
                    match close {
                        None => {
                            out.push(c);
                            i += 1;
                            continue;
                        }
                        Some(p) => {
                            let name = JsStr::from_slice(&r[i + 2..i + 2 + p]);
                            let v = vm.get_prop_of(named, &PropKey::Str(name))?;
                            if !v.is_undefined() {
                                let vs = vm.to_string(&v)?;
                                out.extend_from_slice(vs.units());
                            }
                            i += 3 + p;
                            continue;
                        }
                    }
                }
                _ => {}
            }
        }
        out.push(c);
        i += 1;
    }
    Ok(JsStr::from_units(out))
}

fn sym_replace(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rx = this_re_obj(vm, a, "replace")?;
    let s = vm.to_string(&a.arg(0))?;
    let mut replace_value = a.arg(1);
    let functional = replace_value.is_callable();
    if !functional {
        replace_value = Value::Str(vm.to_string(&replace_value)?);
    }
    let flags = flags_of(vm, &rx)?;
    let global = flags.contains('g');
    let full_unicode = flags.contains('u') || flags.contains('v');
    if global {
        set_last_index(vm, &rx, 0.0)?;
    }
    let fast = has_builtin_exec(vm, &rx);
    // collect results
    let mut results: Vec<Value> = Vec::new();
    let mut fast_results: Vec<Vec<Option<(usize, usize)>>> = Vec::new();
    loop {
        if fast {
            match builtin_exec_raw(vm, &rx, &s)? {
                None => break,
                Some(spans) => {
                    let (st, en) = spans[0].unwrap();
                    fast_results.push(spans);
                    if !global {
                        break;
                    }
                    if st == en {
                        let li = advance_index(&s, en, full_unicode);
                        set_last_index(vm, &rx, li as f64)?;
                    }
                }
            }
            continue;
        }
        let r = regexp_exec(vm, &rx, &s)?;
        if r.is_null() {
            break;
        }
        results.push(r.clone());
        if !global {
            break;
        }
        let ro = r.as_obj().unwrap().clone();
        let m = vm.get(&ro, &PropKey::from_index(0), &r)?;
        let ms = vm.to_string(&m)?;
        if ms.is_empty() {
            let li = vm.get(&rx, &last_index_key(), &Value::Obj(rx.clone()))?;
            let li = vm.to_length(&li)? as usize;
            set_last_index(vm, &rx, advance_index(&s, li, full_unicode) as f64)?;
        }
    }
    let mut acc: Vec<u16> = Vec::new();
    let mut next_pos = 0usize;
    let su = s.units();
    if fast {
        let (compiled, _) = match &rx.borrow().kind {
            ObjKind::RegExp(r) => (r.compiled.clone(), r.rflags),
            _ => unreachable!(),
        };
        for spans in fast_results {
            let (st, en) = spans[0].unwrap();
            let matched = s.substring(st, en);
            let caps: Vec<Value> = spans[1..].iter().map(|sp| sp.map(|(x, y)| Value::Str(s.substring(x, y))).unwrap_or(Value::Undefined)).collect();
            let named = if compiled.has_named_groups() {
                let g = Obj::new(None, ObjKind::Ordinary);
                for (name, idxs) in compiled.group_names() {
                    let mut v = Value::Undefined;
                    for i in &idxs {
                        if let Some(Some((x, y))) = spans.get(*i) {
                            v = Value::Str(s.substring(*x, *y));
                            break;
                        }
                    }
                    g.set_prop(PropKey::Str(JsStr::from_units(name)), v, WEC);
                }
                Value::Obj(g)
            } else {
                Value::Undefined
            };
            let rep = if functional {
                let mut args = vec![Value::Str(matched.clone())];
                args.extend(caps);
                args.push(Value::Num(st as f64));
                args.push(Value::Str(s.clone()));
                if !named.is_undefined() {
                    args.push(named);
                }
                let r = vm.call(&replace_value, Value::Undefined, &args)?;
                vm.to_string(&r)?
            } else {
                let rs = match &replace_value {
                    Value::Str(x) => x.clone(),
                    _ => unreachable!(),
                };
                get_substitution(vm, &matched, &s, st, &caps, &named, &rs)?
            };
            if st >= next_pos {
                acc.extend_from_slice(&su[next_pos..st]);
                acc.extend_from_slice(rep.units());
                next_pos = en;
            }
        }
    } else {
        for r in results {
            let ro = r.as_obj().unwrap().clone();
            let ncap = vm.length_of(&ro)?.saturating_sub(1) as usize;
            let m0 = vm.get(&ro, &PropKey::from_index(0), &r)?;
            let matched = vm.to_string(&m0)?;
            let posv = vm.get_str(&ro, "index")?;
            let pos = vm.to_integer_or_infinity(&posv)?.max(0.0).min(su.len() as f64) as usize;
            let mut caps = Vec::new();
            for n in 1..=ncap {
                let c = vm.get(&ro, &PropKey::from_index(n as u32), &r)?;
                caps.push(if c.is_undefined() { c } else { Value::Str(vm.to_string(&c)?) });
            }
            let named = vm.get_str(&ro, "groups")?;
            let rep = if functional {
                let mut args = vec![Value::Str(matched.clone())];
                args.extend(caps);
                args.push(Value::Num(pos as f64));
                args.push(Value::Str(s.clone()));
                if !named.is_undefined() {
                    args.push(named);
                }
                let r = vm.call(&replace_value, Value::Undefined, &args)?;
                vm.to_string(&r)?
            } else {
                let named = if named.is_undefined() { named } else { Value::Obj(vm.to_object(&named)?) };
                let rs = match &replace_value {
                    Value::Str(x) => x.clone(),
                    _ => unreachable!(),
                };
                get_substitution(vm, &matched, &s, pos, &caps, &named, &rs)?
            };
            if pos >= next_pos {
                acc.extend_from_slice(&su[next_pos..pos]);
                acc.extend_from_slice(rep.units());
                next_pos = pos + matched.len();
            }
        }
    }
    if next_pos < su.len() {
        acc.extend_from_slice(&su[next_pos..]);
    }
    Ok(Value::Str(JsStr::from_units(acc)))
}

fn sym_search(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rx = this_re_obj(vm, a, "search")?;
    let s = vm.to_string(&a.arg(0))?;
    let rxv = Value::Obj(rx.clone());
    let prev = vm.get(&rx, &last_index_key(), &rxv)?;
    if !Value::same_value(&prev, &Value::Num(0.0)) {
        set_last_index(vm, &rx, 0.0)?;
    }
    let r = regexp_exec(vm, &rx, &s)?;
    let cur = vm.get(&rx, &last_index_key(), &rxv)?;
    if !Value::same_value(&cur, &prev) {
        vm.set(&rx, last_index_key(), prev, &rxv)?;
    }
    match &r {
        Value::Null => Ok(Value::Num(-1.0)),
        Value::Obj(o) => vm.get_str(o, "index"),
        _ => Ok(Value::Num(-1.0)),
    }
}

fn sym_split(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rx = this_re_obj(vm, a, "split")?;
    let s = vm.to_string(&a.arg(0))?;
    let flags = flags_of(vm, &rx)?;
    let unicode = flags.contains('u') || flags.contains('v');
    let new_flags = if flags.contains('y') { flags.clone() } else { format!("{}y", flags) };
    // species constructor
    let default = vm.global.get_own_str("RegExp").unwrap_or(Value::Undefined);
    let c = {
        let cv = vm.get(&rx, &vm.intr.key_constructor.clone(), &Value::Obj(rx.clone()))?;
        if cv.is_undefined() {
            default.clone()
        } else if let Value::Obj(co) = &cv {
            let sp = vm.get(co, &PropKey::Sym(vm.intr.sym_species.clone()), &cv)?;
            if sp.is_nullish() {
                default.clone()
            } else {
                sp
            }
        } else {
            return vm.throw_type("constructor is not an object");
        }
    };
    let splitter = vm.construct(&c, &[Value::Obj(rx.clone()), Value::str(&new_flags)], None)?;
    let sp = splitter.as_obj().unwrap().clone();
    let lim = if a.arg(1).is_undefined() { u32::MAX } else { vm.to_uint32(&a.arg(1))? };
    let mut out = Vec::new();
    if lim == 0 {
        return Ok(Value::Obj(vm.new_array(out)));
    }
    let size = s.len();
    if size == 0 {
        let z = regexp_exec(vm, &sp, &s)?;
        if z.is_null() {
            out.push(Value::Str(s));
        }
        return Ok(Value::Obj(vm.new_array(out)));
    }
    let fast = has_builtin_exec(vm, &sp);
    let mut p = 0usize;
    let mut q = 0usize;
    while q < size {
        set_last_index(vm, &sp, q as f64)?;
        let (matched, e, caps): (bool, usize, Vec<Value>) = if fast {
            match builtin_exec_raw(vm, &sp, &s)? {
                None => (false, 0, Vec::new()),
                Some(spans) => {
                    let e = spans[0].unwrap().1.min(size);
                    let caps = spans[1..].iter().map(|x| x.map(|(a, b)| Value::Str(s.substring(a, b))).unwrap_or(Value::Undefined)).collect();
                    (true, e, caps)
                }
            }
        } else {
            let z = regexp_exec(vm, &sp, &s)?;
            if z.is_null() {
                (false, 0, Vec::new())
            } else {
                let li = vm.get(&sp, &last_index_key(), &splitter)?;
                let e = (vm.to_length(&li)? as usize).min(size);
                let zo = z.as_obj().unwrap().clone();
                let n = vm.length_of(&zo)?.saturating_sub(1);
                let mut caps = Vec::new();
                for i in 1..=n {
                    caps.push(vm.get(&zo, &PropKey::from_index(i as u32), &z)?);
                }
                (true, e, caps)
            }
        };
        if !matched || e == p {
            q = advance_index(&s, q, unicode);
            continue;
        }
        out.push(Value::Str(s.substring(p, q)));
        if out.len() as u32 >= lim {
            return Ok(Value::Obj(vm.new_array(out)));
        }
        p = e;
        for c in caps {
            out.push(c);
            if out.len() as u32 >= lim {
                return Ok(Value::Obj(vm.new_array(out)));
            }
        }
        q = p;
    }
    out.push(Value::Str(s.substring(p, size)));
    Ok(Value::Obj(vm.new_array(out)))
}

fn sym_match_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let rx = this_re_obj(vm, a, "matchAll")?;
    let s = vm.to_string(&a.arg(0))?;
    let flags = flags_of(vm, &rx)?;
    let default = vm.global.get_own_str("RegExp").unwrap_or(Value::Undefined);
    let c = {
        let cv = vm.get(&rx, &vm.intr.key_constructor.clone(), &Value::Obj(rx.clone()))?;
        if cv.is_undefined() {
            default.clone()
        } else if let Value::Obj(co) = &cv {
            let sp = vm.get(co, &PropKey::Sym(vm.intr.sym_species.clone()), &cv)?;
            if sp.is_nullish() {
                default.clone()
            } else {
                sp
            }
        } else {
            return vm.throw_type("constructor is not an object");
        }
    };
    let matcher = vm.construct(&c, &[Value::Obj(rx.clone()), Value::str(&flags)], None)?;
    let mo = matcher.as_obj().unwrap().clone();
    let li = vm.get(&rx, &last_index_key(), &Value::Obj(rx.clone()))?;
    let li = vm.to_length(&li)?;
    set_last_index(vm, &mo, li as f64)?;
    let st = IterState::RegExpStr { re: mo, s, global: flags.contains('g'), unicode: flags.contains('u') || flags.contains('v'), done: false };
    Ok(Value::Obj(Obj::new(Some(vm.intr.regexp_string_iterator_proto.clone()), ObjKind::Iterator(Box::new(st)))))
}

fn regexp_string_iter_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let it = match &a.this {
        Value::Obj(o) => o.clone(),
        _ => return vm.throw_type("next called on a non-RegExp-String-Iterator"),
    };
    let (re, s, global, unicode, done) = match &it.borrow().kind {
        ObjKind::Iterator(st) => match &**st {
            IterState::RegExpStr { re, s, global, unicode, done } => (re.clone(), s.clone(), *global, *unicode, *done),
            _ => return Err(vm.make_error("TypeError", "next called on a non-RegExp-String-Iterator")),
        },
        _ => return Err(vm.make_error("TypeError", "next called on a non-RegExp-String-Iterator")),
    };
    if done {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    let set_done = |it: &Obj| {
        if let ObjKind::Iterator(st) = &mut it.borrow_mut().kind {
            if let IterState::RegExpStr { done, .. } = &mut **st {
                *done = true;
            }
        }
    };
    let r = regexp_exec(vm, &re, &s)?;
    if r.is_null() {
        set_done(&it);
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    if !global {
        set_done(&it);
        return Ok(vm.iter_result(r, false));
    }
    let ro = r.as_obj().unwrap().clone();
    let m = vm.get(&ro, &PropKey::from_index(0), &r)?;
    let ms = vm.to_string(&m)?;
    if ms.is_empty() {
        let li = vm.get(&re, &last_index_key(), &Value::Obj(re.clone()))?;
        let li = vm.to_length(&li)? as usize;
        set_last_index(vm, &re, advance_index(&s, li, unicode) as f64)?;
    }
    Ok(vm.iter_result(r, false))
}

// ---------------- String.prototype methods dispatching to regexps ----------------

fn require_this(vm: &mut Vm, a: &Args, name: &str) -> JsResult<()> {
    if a.this.is_nullish() {
        return vm.throw_type(format!("String.prototype.{} called on null or undefined", name));
    }
    Ok(())
}

pub fn string_match(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_this(vm, a, "match")?;
    let rx = a.arg(0);
    if !rx.is_nullish() {
        if let Some(m) = vm.get_method(&rx, &PropKey::Sym(vm.intr.sym_match.clone()))? {
            return vm.call(&m, rx, &[a.this.clone()]);
        }
    }
    let s = vm.to_string(&a.this)?;
    let re = regexp_create(vm, &rx, &Value::Undefined)?;
    let f = vm.get_prop_of(&re, &PropKey::Sym(vm.intr.sym_match.clone()))?;
    vm.call(&f, re, &[Value::Str(s)])
}

pub fn string_match_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_this(vm, a, "matchAll")?;
    let rx = a.arg(0);
    if !rx.is_nullish() {
        if is_regexp(vm, &rx)? {
            let fl = vm.get_prop_of(&rx, &PropKey::from_str("flags"))?;
            if fl.is_nullish() {
                return vm.throw_type("String.prototype.matchAll called with a non-global RegExp");
            }
            let fs = vm.to_string(&fl)?;
            if !fs.units().contains(&(b'g' as u16)) {
                return vm.throw_type("String.prototype.matchAll called with a non-global RegExp");
            }
        }
        if let Some(m) = vm.get_method(&rx, &PropKey::Sym(vm.intr.sym_match_all.clone()))? {
            return vm.call(&m, rx, &[a.this.clone()]);
        }
    }
    let s = vm.to_string(&a.this)?;
    let re = regexp_create(vm, &rx, &Value::str("g"))?;
    let f = vm.get_prop_of(&re, &PropKey::Sym(vm.intr.sym_match_all.clone()))?;
    vm.call(&f, re, &[Value::Str(s)])
}

pub fn string_search(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_this(vm, a, "search")?;
    let rx = a.arg(0);
    if !rx.is_nullish() {
        if let Some(m) = vm.get_method(&rx, &PropKey::Sym(vm.intr.sym_search.clone()))? {
            return vm.call(&m, rx, &[a.this.clone()]);
        }
    }
    let s = vm.to_string(&a.this)?;
    let re = regexp_create(vm, &rx, &Value::Undefined)?;
    let f = vm.get_prop_of(&re, &PropKey::Sym(vm.intr.sym_search.clone()))?;
    vm.call(&f, re, &[Value::Str(s)])
}

pub fn string_replace(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_this(vm, a, "replace")?;
    let search = a.arg(0);
    let replace_value = a.arg(1);
    if !search.is_nullish() {
        if let Some(m) = vm.get_method(&search, &PropKey::Sym(vm.intr.sym_replace.clone()))? {
            return vm.call(&m, search, &[a.this.clone(), replace_value]);
        }
    }
    let s = vm.to_string(&a.this)?;
    let ss = vm.to_string(&search)?;
    let functional = replace_value.is_callable();
    let rv = if functional { None } else { Some(vm.to_string(&replace_value)?) };
    let pos = match s.index_of(ss.units(), 0) {
        Some(p) => p,
        None => return Ok(Value::Str(s)),
    };
    let rep = if functional {
        let r = vm.call(&replace_value, Value::Undefined, &[Value::Str(ss.clone()), Value::Num(pos as f64), Value::Str(s.clone())])?;
        vm.to_string(&r)?
    } else {
        get_substitution(vm, &ss, &s, pos, &[], &Value::Undefined, rv.as_ref().unwrap())?
    };
    let u = s.units();
    let mut out = u[..pos].to_vec();
    out.extend_from_slice(rep.units());
    out.extend_from_slice(&u[pos + ss.len()..]);
    Ok(Value::Str(JsStr::from_units(out)))
}

pub fn string_replace_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    require_this(vm, a, "replaceAll")?;
    let search = a.arg(0);
    let replace_value = a.arg(1);
    if !search.is_nullish() {
        if is_regexp(vm, &search)? {
            let fl = vm.get_prop_of(&search, &PropKey::from_str("flags"))?;
            if fl.is_nullish() {
                return vm.throw_type("replaceAll must be called with a global RegExp");
            }
            let fs = vm.to_string(&fl)?;
            if !fs.units().contains(&(b'g' as u16)) {
                return vm.throw_type("replaceAll must be called with a global RegExp");
            }
        }
        if let Some(m) = vm.get_method(&search, &PropKey::Sym(vm.intr.sym_replace.clone()))? {
            return vm.call(&m, search, &[a.this.clone(), replace_value]);
        }
    }
    let s = vm.to_string(&a.this)?;
    let ss = vm.to_string(&search)?;
    let functional = replace_value.is_callable();
    let rv = if functional { None } else { Some(vm.to_string(&replace_value)?) };
    let slen = ss.len();
    let mut positions = Vec::new();
    let mut p = s.index_of(ss.units(), 0);
    while let Some(pp) = p {
        positions.push(pp);
        // an empty search string matches between code points (not inside surrogate pairs),
        // like the reference engine
        let adv = if slen == 0 {
            let u = s.units();
            if pp + 1 < u.len() && (0xD800..0xDC00).contains(&u[pp]) && (0xDC00..0xE000).contains(&u[pp + 1]) {
                2
            } else {
                1
            }
        } else {
            slen
        };
        p = s.index_of(ss.units(), pp + adv);
    }
    let u = s.units();
    let mut end = 0;
    let mut out: Vec<u16> = Vec::new();
    for pos in positions {
        out.extend_from_slice(&u[end..pos]);
        let rep = if functional {
            let r = vm.call(&replace_value, Value::Undefined, &[Value::Str(ss.clone()), Value::Num(pos as f64), Value::Str(s.clone())])?;
            vm.to_string(&r)?
        } else {
            get_substitution(vm, &ss, &s, pos, &[], &Value::Undefined, rv.as_ref().unwrap())?
        };
        out.extend_from_slice(rep.units());
        end = pos + slen;
    }
    if end < u.len() {
        out.extend_from_slice(&u[end..]);
    }
    Ok(Value::Str(JsStr::from_units(out)))
}
