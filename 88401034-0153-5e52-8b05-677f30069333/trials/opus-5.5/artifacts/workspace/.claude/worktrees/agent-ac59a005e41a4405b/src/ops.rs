// Type conversions, operators and iteration helpers.

use crate::bigint::BigInt;
use crate::bytecode::Op;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::rc::Rc;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Hint {
    Default,
    Number,
    String,
}

impl Vm {
    pub fn to_primitive(&mut self, v: &Value, hint: Hint) -> JsResult<Value> {
        let o = match v {
            Value::Obj(o) => o.clone(),
            _ => return Ok(v.clone()),
        };
        let ex = self.get(&o, &PropKey::Sym(self.intr.sym_to_primitive.clone()), v)?;
        if !ex.is_nullish() {
            if !ex.is_callable() {
                return self.throw_type("@@toPrimitive is not callable");
            }
            let h = match hint {
                Hint::Default => "default",
                Hint::Number => "number",
                Hint::String => "string",
            };
            let r = self.call(&ex, v.clone(), &[Value::str(h)])?;
            if r.is_object() {
                return self.throw_type("Cannot convert object to a primitive value");
            }
            return Ok(r);
        }
        let order: [&str; 2] = if hint == Hint::String { ["toString", "valueOf"] } else { ["valueOf", "toString"] };
        for name in order {
            let k = if name == "toString" { self.intr.key_to_string.clone() } else { self.intr.key_value_of.clone() };
            let f = self.get(&o, &k, v)?;
            if f.is_callable() {
                let r = self.call(&f, v.clone(), &[])?;
                if !r.is_object() {
                    return Ok(r);
                }
            }
        }
        self.throw_type("cannot convert object to primitive value")
    }

    pub fn to_number(&mut self, v: &Value) -> JsResult<f64> {
        match v {
            Value::Num(n) => Ok(*n),
            Value::Undefined | Value::Empty => Ok(f64::NAN),
            Value::Null => Ok(0.0),
            Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
            Value::Str(s) => Ok(crate::numconv::string_to_number(s.units())),
            Value::Sym(_) => self.throw_type("Cannot convert a Symbol value to a number"),
            Value::BigInt(_) => self.throw_type("Cannot convert a BigInt value to a number"),
            Value::Obj(_) => {
                let p = self.to_primitive(v, Hint::Number)?;
                self.to_number(&p)
            }
        }
    }

    pub fn to_numeric(&mut self, v: &Value) -> JsResult<Value> {
        match v {
            Value::Num(_) | Value::BigInt(_) => Ok(v.clone()),
            Value::Obj(_) => {
                let p = self.to_primitive(v, Hint::Number)?;
                if let Value::BigInt(_) = p {
                    return Ok(p);
                }
                Ok(Value::Num(self.to_number(&p)?))
            }
            _ => Ok(Value::Num(self.to_number(v)?)),
        }
    }

    pub fn to_string(&mut self, v: &Value) -> JsResult<JsStr> {
        match v {
            Value::Str(s) => Ok(s.clone()),
            Value::Num(n) => Ok(num_to_jsstr(*n)),
            Value::Undefined | Value::Empty => Ok(self.intr.str_undefined.clone()),
            Value::Null => Ok(self.intr.str_null.clone()),
            Value::Bool(b) => Ok(if *b { self.intr.str_true.clone() } else { self.intr.str_false.clone() }),
            Value::Sym(_) => self.throw_type("Cannot convert a Symbol value to a string"),
            Value::BigInt(b) => Ok(JsStr::from_str(&b.to_string_radix(10))),
            Value::Obj(_) => {
                let p = self.to_primitive(v, Hint::String)?;
                self.to_string(&p)
            }
        }
    }

    pub fn to_rust_string(&mut self, v: &Value) -> JsResult<String> {
        Ok(self.to_string(v)?.to_rust_string())
    }

    pub fn to_property_key(&mut self, v: &Value) -> JsResult<PropKey> {
        match v {
            Value::Str(s) => Ok(PropKey::Str(s.clone())),
            Value::Sym(s) => Ok(PropKey::Sym(s.clone())),
            Value::Num(n) => {
                let n = *n;
                if n >= 0.0 && n < 4294967295.0 && n.fract() == 0.0 {
                    return Ok(PropKey::from_index(n as u32));
                }
                Ok(PropKey::Str(num_to_jsstr(n)))
            }
            Value::Obj(_) => {
                let p = self.to_primitive(v, Hint::String)?;
                self.to_property_key(&p)
            }
            other => Ok(PropKey::Str(self.to_string(other)?)),
        }
    }

    pub fn to_object(&mut self, v: &Value) -> JsResult<Obj> {
        match v {
            Value::Obj(o) => Ok(o.clone()),
            Value::Undefined | Value::Null | Value::Empty => self.throw_type("cannot convert undefined or null to object"),
            Value::Bool(b) => Ok(Obj::with_class(Some(self.intr.boolean_proto.clone()), ObjKind::Boolean(*b), "Boolean")),
            Value::Num(n) => Ok(Obj::with_class(Some(self.intr.number_proto.clone()), ObjKind::Number(*n), "Number")),
            Value::Str(s) => Ok(Obj::with_class(Some(self.intr.string_proto.clone()), ObjKind::String(s.clone()), "String")),
            Value::Sym(s) => Ok(Obj::with_class(Some(self.intr.symbol_proto.clone()), ObjKind::Symbol(s.clone()), "Symbol")),
            Value::BigInt(b) => Ok(Obj::with_class(Some(self.intr.bigint_proto.clone()), ObjKind::BigInt(b.clone()), "BigInt")),
        }
    }

    pub fn to_integer_or_infinity(&mut self, v: &Value) -> JsResult<f64> {
        let n = self.to_number(v)?;
        Ok(integer_or_infinity(n))
    }

    pub fn to_length(&mut self, v: &Value) -> JsResult<u64> {
        let n = self.to_integer_or_infinity(v)?;
        if n <= 0.0 {
            return Ok(0);
        }
        Ok(n.min(9007199254740991.0) as u64)
    }

    pub fn to_index(&mut self, v: &Value) -> JsResult<usize> {
        self.to_index_msg(v, "index out of range")
    }

    /// ToIndex with a caller-specific RangeError message
    pub fn to_index_msg(&mut self, v: &Value, msg: &str) -> JsResult<usize> {
        if v.is_undefined() {
            return Ok(0);
        }
        let n = self.to_integer_or_infinity(v)?;
        if !(0.0..=9007199254740991.0).contains(&n) {
            return self.throw_range(msg);
        }
        Ok(n as usize)
    }

    pub fn to_int32(&mut self, v: &Value) -> JsResult<i32> {
        let n = self.to_number(v)?;
        Ok(crate::builtins::number::to_int32(n))
    }

    pub fn to_uint32(&mut self, v: &Value) -> JsResult<u32> {
        let n = self.to_number(v)?;
        Ok(crate::builtins::number::to_uint32(n))
    }

    pub fn to_bigint(&mut self, v: &Value) -> JsResult<Rc<BigInt>> {
        let p = self.to_primitive(v, Hint::Number)?;
        match &p {
            Value::BigInt(b) => Ok(b.clone()),
            Value::Bool(b) => Ok(Rc::new(BigInt::from_i64(*b as i64))),
            Value::Str(s) => match BigInt::parse(s.units()) {
                Some(b) => Ok(Rc::new(b)),
                None => self.throw_syntax("Cannot convert string to a BigInt"),
            },
            Value::Num(_) => self.throw_type("Cannot convert a Number to a BigInt"),
            _ => self.throw_type("Cannot convert value to a BigInt"),
        }
    }

    // ---------------- operators ----------------

    pub fn op_add(&mut self, a: &Value, b: &Value) -> JsResult<Value> {
        let pa = self.to_primitive(a, Hint::Default)?;
        let pb = self.to_primitive(b, Hint::Default)?;
        if matches!(pa, Value::Str(_)) || matches!(pb, Value::Str(_)) {
            let sa = self.to_string(&pa)?;
            let sb = self.to_string(&pb)?;
            return Ok(Value::Str(JsStr::concat(&sa, &sb)));
        }
        let na = self.to_numeric(&pa)?;
        let nb = self.to_numeric(&pb)?;
        match (&na, &nb) {
            (Value::Num(x), Value::Num(y)) => Ok(Value::Num(x + y)),
            (Value::BigInt(x), Value::BigInt(y)) => Ok(Value::BigInt(Rc::new(x.add(y)))),
            _ => self.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
        }
    }

    pub fn op_arith(&mut self, op: Op, a: &Value, b: &Value) -> JsResult<Value> {
        let na = self.to_numeric(a)?;
        let nb = self.to_numeric(b)?;
        match (&na, &nb) {
            (Value::Num(x), Value::Num(y)) => Ok(crate::vm::num_binop(op, *x, *y)),
            (Value::BigInt(x), Value::BigInt(y)) => {
                let r = match op {
                    Op::Sub => Ok(x.sub(y)),
                    Op::Mul => Ok(x.mul(y)),
                    Op::Div => x.div(y).ok_or(crate::bigint::BigIntError::DivisionByZero),
                    Op::Mod => x.rem(y).ok_or(crate::bigint::BigIntError::DivisionByZero),
                    Op::Exp => x.pow(y),
                    Op::Shl => x.shl(y),
                    Op::Shr => x.shr(y),
                    Op::BitAnd => Ok(x.bitand(y)),
                    Op::BitOr => Ok(x.bitor(y)),
                    Op::BitXor => Ok(x.bitxor(y)),
                    Op::UShr => return self.throw_type("unsupported BigInt operator"),
                    _ => return self.throw_type("unsupported BigInt operator"),
                };
                match r {
                    Ok(v) => Ok(Value::BigInt(Rc::new(v))),
                    Err(e) => self.throw_range(e.message()),
                }
            }
            _ => self.throw_type("Cannot mix BigInt and other types, use explicit conversions"),
        }
    }

    /// returns Some(true/false) or None for undefined (NaN)
    fn less_than(&mut self, a: &Value, b: &Value, left_first: bool) -> JsResult<Option<bool>> {
        let (pa, pb) = if left_first {
            let pa = self.to_primitive(a, Hint::Number)?;
            let pb = self.to_primitive(b, Hint::Number)?;
            (pa, pb)
        } else {
            let pb = self.to_primitive(b, Hint::Number)?;
            let pa = self.to_primitive(a, Hint::Number)?;
            (pa, pb)
        };
        if let (Value::Str(x), Value::Str(y)) = (&pa, &pb) {
            return Ok(Some(x.units() < y.units()));
        }
        if let (Value::BigInt(x), Value::Str(y)) = (&pa, &pb) {
            return Ok(BigInt::parse(y.units()).map(|yb| **x < yb));
        }
        if let (Value::Str(x), Value::BigInt(y)) = (&pa, &pb) {
            return Ok(BigInt::parse(x.units()).map(|xb| xb < **y));
        }
        let na = self.to_numeric(&pa)?;
        let nb = self.to_numeric(&pb)?;
        Ok(match (&na, &nb) {
            (Value::Num(x), Value::Num(y)) => {
                if x.is_nan() || y.is_nan() {
                    None
                } else {
                    Some(x < y)
                }
            }
            (Value::BigInt(x), Value::BigInt(y)) => Some(x < y),
            (Value::BigInt(x), Value::Num(y)) => x.cmp_f64(*y).map(|o| o == std::cmp::Ordering::Less),
            (Value::Num(x), Value::BigInt(y)) => y.cmp_f64(*x).map(|o| o == std::cmp::Ordering::Greater),
            _ => None,
        })
    }

    pub fn op_compare(&mut self, op: Op, a: &Value, b: &Value) -> JsResult<bool> {
        Ok(match op {
            Op::Lt => self.less_than(a, b, true)? == Some(true),
            Op::Gt => self.less_than(b, a, false)? == Some(true),
            Op::Le => self.less_than(b, a, false)? == Some(false),
            Op::Ge => self.less_than(a, b, true)? == Some(false),
            _ => false,
        })
    }

    pub fn loose_eq(&mut self, a: &Value, b: &Value) -> JsResult<bool> {
        match (a, b) {
            (Value::Undefined | Value::Null, Value::Undefined | Value::Null) => Ok(true),
            (Value::Num(x), Value::Num(y)) => Ok(x == y),
            (Value::Str(x), Value::Str(y)) => Ok(x == y),
            (Value::Bool(x), Value::Bool(y)) => Ok(x == y),
            (Value::Sym(x), Value::Sym(y)) => Ok(x == y),
            (Value::BigInt(x), Value::BigInt(y)) => Ok(x == y),
            (Value::Obj(x), Value::Obj(y)) => Ok(x.ptr_eq(y)),
            (Value::Obj(o), Value::Undefined | Value::Null) | (Value::Undefined | Value::Null, Value::Obj(o)) => Ok(o.is_htmldda()),
            (Value::Undefined | Value::Null, _) | (_, Value::Undefined | Value::Null) => Ok(false),
            (Value::Num(x), Value::Str(s)) => Ok(*x == crate::numconv::string_to_number(s.units())),
            (Value::Str(s), Value::Num(y)) => Ok(crate::numconv::string_to_number(s.units()) == *y),
            (Value::BigInt(x), Value::Str(s)) | (Value::Str(s), Value::BigInt(x)) => Ok(match BigInt::parse(s.units()) {
                Some(y) => **x == y,
                None => false,
            }),
            (Value::Bool(x), _) => {
                let n = Value::Num(if *x { 1.0 } else { 0.0 });
                self.loose_eq(&n, b)
            }
            (_, Value::Bool(y)) => {
                let n = Value::Num(if *y { 1.0 } else { 0.0 });
                self.loose_eq(a, &n)
            }
            (Value::Obj(_), Value::Num(_) | Value::Str(_) | Value::BigInt(_) | Value::Sym(_)) => {
                let p = self.to_primitive(a, Hint::Default)?;
                self.loose_eq(&p, b)
            }
            (Value::Num(_) | Value::Str(_) | Value::BigInt(_) | Value::Sym(_), Value::Obj(_)) => {
                let p = self.to_primitive(b, Hint::Default)?;
                self.loose_eq(a, &p)
            }
            (Value::BigInt(x), Value::Num(y)) | (Value::Num(y), Value::BigInt(x)) => Ok(x.eq_f64(*y)),
            _ => Ok(false),
        }
    }

    pub fn instance_of(&mut self, v: &Value, target: &Value) -> JsResult<bool> {
        let t = match target {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type("right-hand side of instanceof is not an object"),
        };
        let h = self.get(&t, &PropKey::Sym(self.intr.sym_has_instance.clone()), target)?;
        if !h.is_nullish() {
            if h.is_callable() {
                // fast path: the default Function.prototype[@@hasInstance]
                let is_default = matches!(&h, Value::Obj(ho) if ho.ptr_eq(&self.intr.function_has_instance));
                if !is_default {
                    let r = self.call(&h, target.clone(), &[v.clone()])?;
                    return Ok(r.truthy());
                }
            } else {
                return self.throw_type("Symbol.hasInstance is not a function");
            }
        }
        if !t.is_callable() {
            return self.throw_type("right-hand side of instanceof is not callable");
        }
        self.ordinary_has_instance(&t, v)
    }

    pub fn ordinary_has_instance(&mut self, c: &Obj, v: &Value) -> JsResult<bool> {
        if !c.is_callable() {
            return Ok(false);
        }
        let bound_target = match &c.borrow().kind {
            ObjKind::Bound(b) => Some(b.target.clone()),
            _ => None,
        };
        if let Some(bt) = bound_target {
            return self.instance_of(v, &Value::Obj(bt));
        }
        let o = match v {
            Value::Obj(o) => o.clone(),
            _ => return Ok(false),
        };
        let p = self.get(c, &self.intr.key_prototype.clone(), &Value::Obj(c.clone()))?;
        let p = match p {
            Value::Obj(p) => p,
            _ => return self.throw_type("Function has non-object prototype in instanceof check"),
        };
        let mut cur = self.get_prototype_of(&o)?;
        while let Some(x) = cur {
            if x.ptr_eq(&p) {
                return Ok(true);
            }
            cur = self.get_prototype_of(&x)?;
        }
        Ok(false)
    }

    // ---------------- iteration ----------------

    /// TypeError thrown by GetIterator on null/undefined: the reference engine reports the
    /// failed GetV of the well-known symbol using its internal key spelling ("\0" + id;
    /// @@iterator is 1, @@asyncIterator is 2).
    pub fn nullish_iterator_error(&mut self, v: &Value, sym_id: u32) -> Value {
        let what = if v.is_null() { "null" } else { "undefined" };
        self.make_error("TypeError", &format!("cannot read property '\u{0}{}' of {}", sym_id, what))
    }

    pub fn get_iterator(&mut self, v: &Value) -> JsResult<(Obj, Value)> {
        if v.is_nullish() {
            return Err(self.nullish_iterator_error(v, 1));
        }
        let m = self.get_prop_of(v, &PropKey::Sym(self.intr.sym_iterator.clone()))?;
        if !m.is_callable() {
            return self.throw_type("value is not iterable");
        }
        self.get_iterator_from_method(v, &m)
    }

    /// GetIterator with an up-front check of the `next` method (the reference engine's
    /// Map/Set/WeakMap/WeakSet constructors).
    pub fn get_iterator_next_checked(&mut self, v: &Value) -> JsResult<(Obj, Value)> {
        let (it, next) = self.get_iterator(v)?;
        if !next.is_callable() {
            return self.throw_type("iterator.next is not a function");
        }
        Ok((it, next))
    }

    /// The reference engine's iteration for spread and several builtins: the iterator returned
    /// by @@iterator need not be an object (its `next` is read like a property of any value).
    /// `not_callable` is the message for a non-callable @@iterator; with `check_next` a
    /// non-callable `next` fails up front ("iterator.next is not a function").
    pub fn get_iterator_loose(&mut self, v: &Value, not_callable: &str, check_next: bool) -> JsResult<(Value, Value)> {
        if v.is_nullish() {
            return Err(self.nullish_iterator_error(v, 1));
        }
        let m = self.get_prop_of(v, &PropKey::Sym(self.intr.sym_iterator.clone()))?;
        if m.is_nullish() {
            return self.throw_type("value is not iterable");
        }
        if !m.is_callable() {
            return self.throw_type(not_callable.to_string());
        }
        let it = self.call(&m, v.clone(), &[])?;
        let next = self.loose_next(&it)?;
        if check_next && !next.is_callable() {
            return self.throw_type("iterator.next is not a function");
        }
        Ok((it, next))
    }

    /// `iterator.next` read from any value (TypeError for undefined/null)
    pub fn loose_next(&mut self, it: &Value) -> JsResult<Value> {
        match it {
            Value::Undefined => self.throw_type("cannot read property 'next' of undefined"),
            Value::Null => self.throw_type("cannot read property 'next' of null"),
            _ => self.get_prop_of(it, &self.intr.key_next.clone()),
        }
    }

    /// Spread-style iteration to a vector (see `get_iterator_loose`).
    pub fn iterate_spread(&mut self, v: &Value, not_callable: &str) -> JsResult<Vec<Value>> {
        if self.is_plain_array_iteration(v) {
            return self.iterate_to_vec(v);
        }
        let (it, next) = self.get_iterator_loose(v, not_callable, true)?;
        let mut out = Vec::new();
        while let Some(x) = self.iter_step(&it, &next)? {
            out.push(x);
        }
        Ok(out)
    }

    pub fn get_iterator_from_method(&mut self, v: &Value, m: &Value) -> JsResult<(Obj, Value)> {
        if !m.is_callable() {
            return self.throw_type("@@iterator is not callable");
        }
        let it = self.call(m, v.clone(), &[])?;
        let io = match &it {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type("@@iterator returned a non-object"),
        };
        let next = self.get(&io, &self.intr.key_next.clone(), &it)?;
        Ok((io, next))
    }

    pub fn get_async_iterator(&mut self, v: &Value) -> JsResult<(Obj, Value)> {
        if v.is_nullish() {
            return Err(self.nullish_iterator_error(v, 2));
        }
        let m = self.get_prop_of(v, &PropKey::Sym(self.intr.sym_async_iterator.clone()))?;
        if m.is_nullish() {
            let (it, next) = self.get_iterator(v)?;
            return Ok(crate::builtins::iterator::create_async_from_sync(self, it, next));
        }
        if !m.is_callable() {
            return self.throw_type("@@asyncIterator is not callable");
        }
        let it = self.call(&m, v.clone(), &[])?;
        let io = match &it {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type("@@asyncIterator did not return an object"),
        };
        let next = self.get(&io, &self.intr.key_next.clone(), &it)?;
        Ok((io, next))
    }

    /// Is `v` an array whose iteration is unobservable (fast path)?
    pub fn is_plain_array_iteration(&mut self, v: &Value) -> bool {
        if let Value::Obj(o) = v {
            let is_dense_array = {
                let b = o.borrow();
                match &b.kind {
                    ObjKind::Array(a) => !a.sparse && b.props.get(&PropKey::Sym(self.intr.sym_iterator.clone())).is_none() && b.proto.as_ref().map_or(false, |p| p.ptr_eq(&self.intr.array_proto)),
                    _ => false,
                }
            };
            if !is_dense_array {
                return false;
            }
            let ap = self.intr.array_proto.clone();
            let cur = ap.borrow().props.get(&PropKey::Sym(self.intr.sym_iterator.clone())).cloned();
            let ok = matches!(cur, Some(Prop::Data { value: Value::Obj(f), .. }) if Value::Obj(f.clone()).as_obj().unwrap().ptr_eq(self.intr.array_values.as_obj().unwrap()));
            if !ok {
                return false;
            }
            let aip = self.intr.array_iterator_proto.clone();
            let next = aip.borrow().props.get(&self.intr.key_next.clone()).cloned();
            return matches!(next, Some(Prop::Data { value: Value::Obj(f), .. }) if f.ptr_eq(&self.intr.array_iter_next));
        }
        false
    }

    pub fn iterate_to_vec(&mut self, v: &Value) -> JsResult<Vec<Value>> {
        if self.is_plain_array_iteration(v) {
            let o = v.as_obj().unwrap();
            let b = o.borrow();
            if let ObjKind::Array(a) = &b.kind {
                let mut out: Vec<Value> = a.dense.iter().map(|x| if x.is_empty() { Value::Undefined } else { x.clone() }).collect();
                while (out.len() as u32) < a.len {
                    out.push(Value::Undefined);
                }
                return Ok(out);
            }
        }
        let (it, next) = self.get_iterator(v)?;
        let mut out = Vec::new();
        let itv = Value::Obj(it);
        loop {
            let r = self.call(&next, itv.clone(), &[])?;
            let ro = match &r {
                Value::Obj(o) => o.clone(),
                _ => return self.throw_type("iterator result is not an object"),
            };
            if self.get(&ro, &self.intr.key_done.clone(), &r)?.truthy() {
                break;
            }
            out.push(self.get(&ro, &self.intr.key_value.clone(), &r)?);
        }
        Ok(out)
    }

    /// Step an iterator record; returns None when done.
    pub fn iter_step(&mut self, it: &Value, next: &Value) -> JsResult<Option<Value>> {
        let r = self.call(next, it.clone(), &[])?;
        let ro = match &r {
            Value::Obj(o) => o.clone(),
            _ => return self.throw_type("iterator result is not an object"),
        };
        if self.get(&ro, &self.intr.key_done.clone(), &r)?.truthy() {
            return Ok(None);
        }
        Ok(Some(self.get(&ro, &self.intr.key_value.clone(), &r)?))
    }

    pub fn iterator_close(&mut self, it: &Value) -> JsResult<()> {
        let ret = self.get_prop_of(it, &PropKey::from_str("return"))?;
        if ret.is_nullish() {
            return Ok(());
        }
        if !ret.is_callable() {
            return self.throw_type("iterator 'return' is not callable");
        }
        let r = self.call(&ret, it.clone(), &[])?;
        if !r.is_object() {
            return self.throw_type("iterator 'return' must return an object");
        }
        Ok(())
    }

    pub fn for_in_iterator(&mut self, v: &Value) -> JsResult<Obj> {
        let obj = match v {
            Value::Undefined | Value::Null => None,
            Value::Obj(o) => Some(o.clone()),
            other => Some(self.to_object(other)?),
        };
        let st = IterState::ForIn { obj, keys: Vec::new(), index: 0, visited: Vec::new(), started: false };
        Ok(Obj::new(None, ObjKind::Iterator(Box::new(st))))
    }

    pub fn for_in_next(&mut self, it: &Obj) -> JsResult<Option<JsStr>> {
        // Like the reference engine: all enumerable string keys of the receiver and its
        // prototype chain are collected up front; each key is re-checked with [[HasProperty]]
        // right before it is produced (so deleted properties are skipped).
        let (obj, started) = {
            let b = it.borrow();
            match &b.kind {
                ObjKind::Iterator(s) => match &**s {
                    IterState::ForIn { obj, started, .. } => (obj.clone(), *started),
                    _ => return Ok(None),
                },
                _ => return Ok(None),
            }
        };
        let obj = match obj {
            Some(o) => o,
            None => return Ok(None),
        };
        if !started {
            let mut out: Vec<JsStr> = Vec::new();
            let mut seen: std::collections::HashSet<JsStr> = std::collections::HashSet::new();
            let mut cur = Some(obj.clone());
            while let Some(o) = cur {
                let keys = self.own_property_keys(&o)?;
                let ordinary = !o.is_proxy() && !matches!(o.borrow().kind, ObjKind::Namespace(_));
                for k in keys {
                    if let PropKey::Str(s) = &k {
                        if !seen.insert(s.clone()) {
                            continue;
                        }
                        let enumerable = if ordinary {
                            match self.ordinary_get_own(&o, &k) {
                                Some(p) => p.enumerable(),
                                None => false,
                            }
                        } else {
                            matches!(self.get_own_property(&o, &k)?, Some(d) if d.enumerable == Some(true))
                        };
                        if enumerable {
                            out.push(s.clone());
                        }
                    }
                }
                cur = self.get_prototype_of(&o)?;
            }
            if let ObjKind::Iterator(s) = &mut it.borrow_mut().kind {
                if let IterState::ForIn { keys, index, started, .. } = &mut **s {
                    *keys = out;
                    *index = 0;
                    *started = true;
                }
            }
        }
        loop {
            let next_key = {
                let mut b = it.borrow_mut();
                match &mut b.kind {
                    ObjKind::Iterator(s) => match &mut **s {
                        IterState::ForIn { keys, index, .. } => {
                            if *index < keys.len() {
                                *index += 1;
                                Some(keys[*index - 1].clone())
                            } else {
                                None
                            }
                        }
                        _ => None,
                    },
                    _ => None,
                }
            };
            match next_key {
                Some(k) => {
                    if self.has_property(&obj, &PropKey::Str(k.clone()))? {
                        return Ok(Some(k));
                    }
                }
                None => return Ok(None),
            }
        }
    }
}

pub fn integer_or_infinity(n: f64) -> f64 {
    if n.is_nan() {
        0.0
    } else if n.is_infinite() {
        n
    } else {
        let t = n.trunc();
        if t == 0.0 {
            0.0
        } else {
            t
        }
    }
}

pub fn num_to_jsstr(n: f64) -> JsStr {
    if n >= 0.0 && n < 1024.0 && n.fract() == 0.0 && !(n == 0.0 && n.is_sign_negative()) {
        return index_to_jsstr(n as u64);
    }
    if n == 0.0 {
        return index_to_jsstr(0);
    }
    JsStr::from_str(&crate::numconv::number_to_string(n))
}
