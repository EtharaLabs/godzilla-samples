// JSON.parse / JSON.stringify

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let j = vm.new_object();
    vm.def_method(&j, "parse", 2, parse);
    vm.def_method(&j, "stringify", 3, stringify);
    vm.def_method(&j, "rawJSON", 1, raw_json);
    vm.def_method(&j, "isRawJSON", 1, is_raw_json);
    vm.set_tag(&j, "JSON");
    vm.def_global("JSON", Value::Obj(j));
}

struct Parser<'a> {
    s: &'a [u16],
    i: usize,
    /// record the source text of values (JSON.parse with a reviver)
    rec: bool,
}

/// Snapshot of a parsed JSON value with the source text of its primitive values, passed to
/// revivers as `context.source`.
enum SrcRec {
    Prim(Value, JsStr),
    Arr(Value, Vec<SrcRec>),
    Obj(Value, Vec<(JsStr, SrcRec)>),
}

impl SrcRec {
    fn value(&self) -> &Value {
        match self {
            SrcRec::Prim(v, _) | SrcRec::Arr(v, _) | SrcRec::Obj(v, _) => v,
        }
    }
}

type PR<T> = Result<T, &'static str>;

impl<'a> Parser<'a> {
    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], 0x20 | 0x09 | 0x0a | 0x0d) {
            self.i += 1;
        }
    }
    fn peek(&self) -> Option<u16> {
        self.s.get(self.i).copied()
    }
    fn value(&mut self, vm: &mut Vm) -> PR<(Value, Option<SrcRec>)> {
        self.ws();
        let c = match self.peek() {
            None => return Err("Unexpected end of JSON input"),
            Some(c) => c,
        };
        let start = self.i;
        let v = match c {
            0x7b => return self.object(vm),
            0x5b => return self.array(vm),
            0x22 => Value::Str(self.string()?),
            0x74 => self.literal("true", Value::Bool(true))?,
            0x66 => self.literal("false", Value::Bool(false))?,
            0x6e => self.literal("null", Value::Null)?,
            0x2d | 0x30..=0x39 => self.number()?,
            _ => return Err("Unexpected token in JSON"),
        };
        let rec = if self.rec { Some(SrcRec::Prim(v.clone(), JsStr::from_slice(&self.s[start..self.i]))) } else { None };
        Ok((v, rec))
    }
    fn literal(&mut self, word: &str, v: Value) -> PR<Value> {
        for b in word.bytes() {
            if self.peek() != Some(b as u16) {
                return Err("Invalid literal in JSON");
            }
            self.i += 1;
        }
        Ok(v)
    }
    fn number(&mut self) -> PR<Value> {
        let start = self.i;
        if self.peek() == Some(0x2d) {
            self.i += 1;
        }
        match self.peek() {
            Some(0x30) => {
                self.i += 1;
            }
            Some(c) if (0x31..=0x39).contains(&c) => {
                while matches!(self.peek(), Some(c) if (0x30..=0x39).contains(&c)) {
                    self.i += 1;
                }
            }
            _ => return Err("Invalid number in JSON"),
        }
        if self.peek() == Some(0x2e) {
            self.i += 1;
            if !matches!(self.peek(), Some(c) if (0x30..=0x39).contains(&c)) {
                return Err("Invalid number in JSON");
            }
            while matches!(self.peek(), Some(c) if (0x30..=0x39).contains(&c)) {
                self.i += 1;
            }
        }
        if matches!(self.peek(), Some(0x65 | 0x45)) {
            self.i += 1;
            if matches!(self.peek(), Some(0x2b | 0x2d)) {
                self.i += 1;
            }
            if !matches!(self.peek(), Some(c) if (0x30..=0x39).contains(&c)) {
                return Err("Invalid number in JSON");
            }
            while matches!(self.peek(), Some(c) if (0x30..=0x39).contains(&c)) {
                self.i += 1;
            }
        }
        Ok(Value::Num(crate::numconv::string_to_number(&self.s[start..self.i])))
    }
    fn string(&mut self) -> PR<JsStr> {
        self.i += 1;
        let mut out: Vec<u16> = Vec::new();
        loop {
            let c = match self.peek() {
                None => return Err("Unterminated JSON string"),
                Some(c) => c,
            };
            self.i += 1;
            match c {
                0x22 => break,
                0x5c => {
                    let e = match self.peek() {
                        None => return Err("Unterminated JSON string"),
                        Some(e) => e,
                    };
                    self.i += 1;
                    match e {
                        0x22 => out.push(0x22),
                        0x5c => out.push(0x5c),
                        0x2f => out.push(0x2f),
                        0x62 => out.push(8),
                        0x66 => out.push(12),
                        0x6e => out.push(10),
                        0x72 => out.push(13),
                        0x74 => out.push(9),
                        0x75 => {
                            let mut v = 0u16;
                            for _ in 0..4 {
                                let d = match self.peek().and_then(|c| char::from_u32(c as u32)).and_then(|c| c.to_digit(16)) {
                                    Some(d) => d,
                                    None => return Err("Bad \\u escape in JSON"),
                                };
                                v = v * 16 + d as u16;
                                self.i += 1;
                            }
                            out.push(v);
                        }
                        _ => return Err("Bad escape in JSON"),
                    }
                }
                c if c < 0x20 => return Err("Unescaped control character in JSON string"),
                c => out.push(c),
            }
        }
        Ok(JsStr::from_units(out))
    }
    fn array(&mut self, vm: &mut Vm) -> PR<(Value, Option<SrcRec>)> {
        self.i += 1;
        let mut items = Vec::new();
        let mut recs = Vec::new();
        self.ws();
        if self.peek() == Some(0x5d) {
            self.i += 1;
            let v = Value::Obj(vm.new_array(items));
            let rec = if self.rec { Some(SrcRec::Arr(v.clone(), recs)) } else { None };
            return Ok((v, rec));
        }
        loop {
            let (v, r) = self.value(vm)?;
            items.push(v);
            if let Some(r) = r {
                recs.push(r);
            }
            self.ws();
            match self.peek() {
                Some(0x2c) => {
                    self.i += 1;
                }
                Some(0x5d) => {
                    self.i += 1;
                    break;
                }
                _ => return Err("Expected ',' or ']' in JSON array"),
            }
        }
        let v = Value::Obj(vm.new_array(items));
        let rec = if self.rec { Some(SrcRec::Arr(v.clone(), recs)) } else { None };
        Ok((v, rec))
    }
    fn object(&mut self, vm: &mut Vm) -> PR<(Value, Option<SrcRec>)> {
        self.i += 1;
        let o = vm.new_object();
        let mut recs: Vec<(JsStr, SrcRec)> = Vec::new();
        self.ws();
        if self.peek() == Some(0x7d) {
            self.i += 1;
            let v = Value::Obj(o);
            let rec = if self.rec { Some(SrcRec::Obj(v.clone(), recs)) } else { None };
            return Ok((v, rec));
        }
        loop {
            self.ws();
            if self.peek() != Some(0x22) {
                return Err("Expected string key in JSON object");
            }
            let k = self.string()?;
            self.ws();
            if self.peek() != Some(0x3a) {
                return Err("Expected ':' in JSON object");
            }
            self.i += 1;
            let (v, r) = self.value(vm)?;
            if let Some(r) = r {
                recs.retain(|(rk, _)| *rk != k);
                recs.push((k.clone(), r));
            }
            let key = PropKey::Str(k);
            if key.as_index().is_some() || key.eq_str("__proto__") {
                // __proto__ in JSON is an ordinary own property
                o.borrow_mut().props.insert(key, Prop::Data { value: v, flags: WEC });
            } else {
                o.set_prop(key, v, WEC);
            }
            self.ws();
            match self.peek() {
                Some(0x2c) => {
                    self.i += 1;
                }
                Some(0x7d) => {
                    self.i += 1;
                    break;
                }
                _ => return Err("Expected ',' or '}' in JSON object"),
            }
        }
        let v = Value::Obj(o);
        let rec = if self.rec { Some(SrcRec::Obj(v.clone(), recs)) } else { None };
        Ok((v, rec))
    }
}

fn json_parse_rec(vm: &mut Vm, s: &JsStr, rec: bool) -> JsResult<(Value, Option<SrcRec>)> {
    let mut p = Parser { s: s.units(), i: 0, rec };
    let r = p.value(vm);
    let v = match r {
        Ok(v) => v,
        Err(m) => return vm.throw_syntax(m),
    };
    p.ws();
    if p.i < p.s.len() {
        return vm.throw_syntax("Unexpected non-whitespace after JSON");
    }
    Ok(v)
}

pub fn json_parse(vm: &mut Vm, s: &JsStr) -> JsResult<Value> {
    Ok(json_parse_rec(vm, s, false)?.0)
}

fn parse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let reviver = a.arg(1);
    let (v, rec) = json_parse_rec(vm, &s, reviver.is_callable())?;
    if reviver.is_callable() {
        let root = vm.new_object();
        root.set_prop(PropKey::from_str(""), v, WEC);
        return internalize(vm, &root, PropKey::from_str(""), &reviver, rec.as_ref());
    }
    Ok(v)
}

fn internalize(vm: &mut Vm, holder: &Obj, name: PropKey, reviver: &Value, rec: Option<&SrcRec>) -> JsResult<Value> {
    let val = vm.get(holder, &name, &Value::Obj(holder.clone()))?;
    // the reviver's context: the source text of unmodified primitive values
    let context = vm.new_object();
    let rec = rec.filter(|r| Value::same_value(r.value(), &val));
    if let Some(SrcRec::Prim(_, src)) = rec {
        context.set_prop(PropKey::from_str("source"), Value::Str(src.clone()), WEC);
    }
    if let Value::Obj(o) = &val {
        if crate::builtins::array::is_array(vm, &val)? {
            let len = vm.length_of(o)?;
            let elems = match rec {
                Some(SrcRec::Arr(_, e)) => Some(e),
                _ => None,
            };
            for i in 0..len {
                let k = PropKey::from_index(i as u32);
                let r = elems.and_then(|e| e.get(i as usize));
                let nv = internalize(vm, o, k.clone(), reviver, r)?;
                if nv.is_undefined() {
                    vm.delete(o, &k)?;
                } else {
                    vm.create_data_property(o, k, nv)?;
                }
            }
        } else {
            let keys = vm.enumerable_own_keys(o)?;
            let entries = match rec {
                Some(SrcRec::Obj(_, e)) => Some(e),
                _ => None,
            };
            for k in keys {
                let r = entries.and_then(|e| e.iter().find(|(rk, _)| *rk == k).map(|(_, r)| r));
                let pk = PropKey::Str(k);
                let nv = internalize(vm, o, pk.clone(), reviver, r)?;
                if nv.is_undefined() {
                    vm.delete(o, &pk)?;
                } else {
                    vm.create_data_property(o, pk, nv)?;
                }
            }
        }
    }
    let n = match &name {
        PropKey::Str(s) => Value::Str(s.clone()),
        PropKey::Sym(s) => Value::Sym(s.clone()),
    };
    vm.call(reviver, Value::Obj(holder.clone()), &[n, val, Value::Obj(context)])
}

pub fn quote(s: &[u16], out: &mut Vec<u16>) {
    out.push(b'"' as u16);
    let mut i = 0;
    while i < s.len() {
        let c = s[i];
        match c {
            0x22 => out.extend_from_slice(&[0x5c, 0x22]),
            0x5c => out.extend_from_slice(&[0x5c, 0x5c]),
            0x08 => out.extend_from_slice(&[0x5c, b'b' as u16]),
            0x0c => out.extend_from_slice(&[0x5c, b'f' as u16]),
            0x0a => out.extend_from_slice(&[0x5c, b'n' as u16]),
            0x0d => out.extend_from_slice(&[0x5c, b'r' as u16]),
            0x09 => out.extend_from_slice(&[0x5c, b't' as u16]),
            c if c < 0x20 => {
                for b in format!("\\u{:04x}", c).encode_utf16() {
                    out.push(b);
                }
            }
            c if (0xD800..0xDC00).contains(&c) => {
                if i + 1 < s.len() && (0xDC00..0xE000).contains(&s[i + 1]) {
                    out.push(c);
                    out.push(s[i + 1]);
                    i += 1;
                } else {
                    for b in format!("\\u{:04x}", c).encode_utf16() {
                        out.push(b);
                    }
                }
            }
            c if (0xDC00..0xE000).contains(&c) => {
                for b in format!("\\u{:04x}", c).encode_utf16() {
                    out.push(b);
                }
            }
            c => out.push(c),
        }
        i += 1;
    }
    out.push(b'"' as u16);
}

struct Stringifier {
    replacer: Option<Value>,
    allow: Option<Vec<PropKey>>,
    gap: Vec<u16>,
    indent: Vec<u16>,
    stack: Vec<Obj>,
}

impl Stringifier {
    fn ser(&mut self, vm: &mut Vm, holder: &Obj, key: PropKey, out: &mut Vec<u16>) -> JsResult<bool> {
        let mut value = vm.get(holder, &key, &Value::Obj(holder.clone()))?;
        self.ser_value(vm, holder, key, &mut value, out)
    }

    fn ser_value(&mut self, vm: &mut Vm, holder: &Obj, key: PropKey, value: &mut Value, out: &mut Vec<u16>) -> JsResult<bool> {
        if matches!(value, Value::Obj(_) | Value::BigInt(_)) {
            let tj = vm.get_prop_of(value, &PropKey::from_str("toJSON"))?;
            if tj.is_callable() {
                let k = match &key {
                    PropKey::Str(s) => Value::Str(s.clone()),
                    PropKey::Sym(s) => Value::Sym(s.clone()),
                };
                *value = vm.call(&tj, value.clone(), &[k])?;
            }
        }
        if let Some(r) = &self.replacer {
            let k = match &key {
                PropKey::Str(s) => Value::Str(s.clone()),
                PropKey::Sym(s) => Value::Sym(s.clone()),
            };
            let r = r.clone();
            *value = vm.call(&r, Value::Obj(holder.clone()), &[k, value.clone()])?;
        }
        if let Value::Obj(o) = value.clone() {
            let unwrapped = match &o.borrow().kind {
                ObjKind::Number(_) => Some(1),
                ObjKind::String(_) => Some(2),
                ObjKind::Boolean(b) => {
                    *value = Value::Bool(*b);
                    None
                }
                ObjKind::BigInt(b) => {
                    *value = Value::BigInt(b.clone());
                    None
                }
                _ => None,
            };
            match unwrapped {
                Some(1) => *value = Value::Num(vm.to_number(value)?),
                Some(2) => *value = Value::Str(vm.to_string(value)?),
                _ => {}
            }
        }
        match value {
            Value::Null => {
                out.extend("null".encode_utf16());
                Ok(true)
            }
            Value::Bool(b) => {
                out.extend(if *b { "true" } else { "false" }.encode_utf16());
                Ok(true)
            }
            Value::Str(s) => {
                quote(s.units(), out);
                Ok(true)
            }
            Value::Num(n) => {
                if n.is_finite() {
                    out.extend(crate::numconv::number_to_string(*n).encode_utf16());
                } else {
                    out.extend("null".encode_utf16());
                }
                Ok(true)
            }
            Value::BigInt(_) => vm.throw_type(crate::bigint::MSG_JSON_SERIALIZE),
            Value::Obj(o) => {
                if o.is_callable() {
                    return Ok(false);
                }
                if let Some(raw) = raw_json_text(o) {
                    out.extend(raw.units());
                    return Ok(true);
                }
                let o = o.clone();
                if self.stack.iter().any(|x| x.ptr_eq(&o)) {
                    return vm.throw_type("Converting circular structure to JSON");
                }
                vm.enter()?;
                self.stack.push(o.clone());
                let r = if crate::builtins::array::is_array(vm, value)? { self.ser_array(vm, &o, out) } else { self.ser_object(vm, &o, out) };
                self.stack.pop();
                vm.depth -= 1;
                r?;
                Ok(true)
            }
            _ => Ok(false),
        }
    }

    fn ser_object(&mut self, vm: &mut Vm, o: &Obj, out: &mut Vec<u16>) -> JsResult<()> {
        let stepback = self.indent.clone();
        self.indent.extend_from_slice(&self.gap.clone());
        let keys: Vec<PropKey> = match &self.allow {
            Some(a) => a.clone(),
            None => {
                let keys = vm.enumerable_own_keys(o)?;
                if matches!(o.borrow().kind, ObjKind::TypedArray(_)) {
                    // the reference engine does not serialize typed array elements
                    keys.into_iter().filter(|k| crate::props::canonical_numeric(&PropKey::Str(k.clone())).is_none()).map(PropKey::Str).collect()
                } else {
                    keys.into_iter().map(PropKey::Str).collect()
                }
            }
        };
        out.push(b'{' as u16);
        let mut first = true;
        for k in keys {
            let mut piece = Vec::new();
            let mut v = vm.get(o, &k, &Value::Obj(o.clone()))?;
            if !self.ser_value(vm, o, k.clone(), &mut v, &mut piece)? {
                continue;
            }
            if !first {
                out.push(b',' as u16);
            }
            first = false;
            if !self.gap.is_empty() {
                out.push(b'\n' as u16);
                out.extend_from_slice(&self.indent);
            }
            if let PropKey::Str(s) = &k {
                quote(s.units(), out);
            }
            out.push(b':' as u16);
            if !self.gap.is_empty() {
                out.push(b' ' as u16);
            }
            out.extend(piece);
        }
        if !first && !self.gap.is_empty() {
            out.push(b'\n' as u16);
            out.extend_from_slice(&stepback);
        }
        out.push(b'}' as u16);
        self.indent = stepback;
        Ok(())
    }

    fn ser_array(&mut self, vm: &mut Vm, o: &Obj, out: &mut Vec<u16>) -> JsResult<()> {
        let stepback = self.indent.clone();
        self.indent.extend_from_slice(&self.gap.clone());
        let len = vm.length_of(o)?;
        out.push(b'[' as u16);
        for i in 0..len {
            if i > 0 {
                out.push(b',' as u16);
            }
            if !self.gap.is_empty() {
                out.push(b'\n' as u16);
                out.extend_from_slice(&self.indent);
            }
            let mut piece = Vec::new();
            if !self.ser(vm, o, PropKey::from_index(i as u32), &mut piece)? {
                out.extend("null".encode_utf16());
            } else {
                out.extend(piece);
            }
        }
        if len > 0 && !self.gap.is_empty() {
            out.push(b'\n' as u16);
            out.extend_from_slice(&stepback);
        }
        out.push(b']' as u16);
        self.indent = stepback;
        Ok(())
    }
}

pub fn json_stringify(vm: &mut Vm, v: &Value, replacer: &Value, space: &Value) -> JsResult<Option<JsStr>> {
    let mut st = Stringifier { replacer: None, allow: None, gap: Vec::new(), indent: Vec::new(), stack: Vec::new() };
    if replacer.is_callable() {
        st.replacer = Some(replacer.clone());
    } else if crate::builtins::array::is_array(vm, replacer)? {
        let ro = replacer.as_obj().unwrap().clone();
        let len = vm.length_of(&ro)?;
        let mut list: Vec<PropKey> = Vec::new();
        for i in 0..len {
            let e = vm.get(&ro, &PropKey::from_index(i as u32), replacer)?;
            let item = match &e {
                Value::Str(s) => Some(s.clone()),
                Value::Num(_) => Some(vm.to_string(&e)?),
                Value::Obj(o) => {
                    let is = matches!(o.borrow().kind, ObjKind::String(_) | ObjKind::Number(_));
                    if is {
                        Some(vm.to_string(&e)?)
                    } else {
                        None
                    }
                }
                _ => None,
            };
            if let Some(s) = item {
                let k = PropKey::Str(s);
                if !list.contains(&k) {
                    list.push(k);
                }
            }
        }
        st.allow = Some(list);
    }
    let mut space = space.clone();
    if let Value::Obj(o) = &space {
        let k = match &o.borrow().kind {
            ObjKind::Number(_) => 1,
            ObjKind::String(_) => 2,
            _ => 0,
        };
        if k == 1 {
            space = Value::Num(vm.to_number(&space)?);
        } else if k == 2 {
            space = Value::Str(vm.to_string(&space)?);
        }
    }
    match &space {
        Value::Num(n) => {
            let k = crate::ops::integer_or_infinity(*n).clamp(0.0, 10.0) as usize;
            st.gap = vec![b' ' as u16; k];
        }
        Value::Str(s) => {
            let u = s.units();
            st.gap = u[..u.len().min(10)].to_vec();
        }
        _ => {}
    }
    let wrapper = vm.new_object();
    wrapper.set_prop(PropKey::from_str(""), v.clone(), WEC);
    let mut out = Vec::new();
    if st.ser(vm, &wrapper, PropKey::from_str(""), &mut out)? {
        Ok(Some(JsStr::from_units(out)))
    } else {
        Ok(None)
    }
}

fn stringify(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    match json_stringify(vm, &a.arg(0), &a.arg(1), &a.arg(2))? {
        Some(s) => Ok(Value::Str(s)),
        None => Ok(Value::Undefined),
    }
}

fn raw_json_text(o: &Obj) -> Option<JsStr> {
    let b = o.borrow();
    if let ObjKind::Host(h) = &b.kind {
        if let Some(r) = h.downcast_ref::<RawJson>() {
            return Some(r.0.clone());
        }
    }
    None
}

struct RawJson(JsStr);

fn raw_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    let u = s.units();
    if u.is_empty() || matches!(u[0], 0x09 | 0x0a | 0x0d | 0x20) || matches!(u[u.len() - 1], 0x09 | 0x0a | 0x0d | 0x20) {
        return vm.throw_syntax("Invalid value for JSON.rawJSON");
    }
    let v = json_parse(vm, &s)?;
    if v.is_object() {
        return vm.throw_syntax("Invalid value for JSON.rawJSON");
    }
    let o = Obj::new(None, ObjKind::Host(Box::new(RawJson(s.clone()))));
    o.set_prop(PropKey::from_str("rawJSON"), Value::Str(s), ENUMERABLE);
    o.borrow_mut().extensible = false;
    Ok(Value::Obj(o))
}

fn is_raw_json(_vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(matches!(&a.arg(0), Value::Obj(o) if raw_json_text(o).is_some())))
}
