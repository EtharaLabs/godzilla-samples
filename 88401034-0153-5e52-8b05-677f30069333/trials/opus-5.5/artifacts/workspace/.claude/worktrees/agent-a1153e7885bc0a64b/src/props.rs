// Object internal methods: [[Get]], [[Set]], [[DefineOwnProperty]], etc. with exotic behaviors.

use crate::builtins::proxy;
use crate::builtins::typedarray as ta;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

enum GetR {
    Found(Value),
    Getter(Option<Obj>),
    Next(Option<Obj>),
    Proxy,
    Namespace,
}

/// Canonical numeric index string check for typed arrays. Returns Some(n) if the key is numeric.
pub fn canonical_numeric(key: &PropKey) -> Option<f64> {
    let s = match key {
        PropKey::Str(s) => s,
        _ => return None,
    };
    if let Some(i) = s.as_array_index() {
        return Some(i as f64);
    }
    let u = s.units();
    if u.is_empty() {
        return None;
    }
    let c = u[0];
    if !(c == b'-' as u16 || (c >= b'0' as u16 && c <= b'9' as u16) || c == b'I' as u16 || c == b'N' as u16) {
        return None;
    }
    if s.eq_str("-0") {
        return Some(-0.0);
    }
    let n = crate::numconv::string_to_number(u);
    let back = crate::numconv::number_to_string(n);
    if s.eq_str(&back) {
        Some(n)
    } else {
        None
    }
}

impl Vm {
    // ---------------- prototype / extensibility ----------------

    pub fn get_prototype_of(&mut self, o: &Obj) -> JsResult<Option<Obj>> {
        if o.is_proxy() {
            return proxy::proxy_get_prototype_of(self, o);
        }
        Ok(o.borrow().proto.clone())
    }

    pub fn set_prototype_of(&mut self, o: &Obj, p: Option<Obj>) -> JsResult<bool> {
        if o.is_proxy() {
            return proxy::proxy_set_prototype_of(self, o, p);
        }
        let cur = o.borrow().proto.clone();
        let same = match (&cur, &p) {
            (Some(a), Some(b)) => a.ptr_eq(b),
            (None, None) => true,
            _ => false,
        };
        if same {
            return Ok(true);
        }
        if !o.borrow().extensible {
            return Ok(false);
        }
        // immutable prototype exotic: Object.prototype
        if o.ptr_eq(&self.intr.object_proto) {
            return Ok(false);
        }
        // cycle check
        let mut pp = p.clone();
        while let Some(x) = pp {
            if x.ptr_eq(o) {
                return Ok(false);
            }
            if x.is_proxy() {
                break;
            }
            pp = x.borrow().proto.clone();
        }
        o.borrow_mut().proto = p;
        Ok(true)
    }

    pub fn is_extensible(&mut self, o: &Obj) -> JsResult<bool> {
        if o.is_proxy() {
            return proxy::proxy_is_extensible(self, o);
        }
        Ok(o.borrow().extensible)
    }

    pub fn prevent_extensions(&mut self, o: &Obj) -> JsResult<bool> {
        if o.is_proxy() {
            return proxy::proxy_prevent_extensions(self, o);
        }
        let is_ta = matches!(o.borrow().kind, ObjKind::TypedArray(_));
        if is_ta {
            // length-tracking / resizable-backed typed arrays cannot be made non-extensible
            let ok = {
                let b = o.borrow();
                if let ObjKind::TypedArray(t) = &b.kind {
                    let resizable = t.buf.borrow().max_len.is_some();
                    !(t.length.is_none() || resizable)
                } else {
                    true
                }
            };
            if !ok {
                return Ok(false);
            }
        }
        o.borrow_mut().extensible = false;
        Ok(true)
    }

    // ---------------- own properties ----------------

    /// Own property (no proxy traps) as a Prop.
    pub fn ordinary_get_own(&mut self, o: &Obj, key: &PropKey) -> Option<Prop> {
        let b = o.borrow();
        match &b.kind {
            ObjKind::Array(a) => {
                if key.eq_str("length") {
                    return Some(Prop::Data { value: Value::Num(a.len as f64), flags: if a.length_writable { WRITABLE } else { 0 } });
                }
                if !a.sparse {
                    if let Some(i) = key.as_index() {
                        return match a.dense.get(i as usize) {
                            Some(v) if !v.is_empty() => Some(Prop::Data { value: v.clone(), flags: WEC }),
                            _ => None,
                        };
                    }
                }
            }
            ObjKind::String(s) => {
                if let Some(i) = key.as_index() {
                    if (i as usize) < s.len() {
                        let c = s.units()[i as usize];
                        return Some(Prop::Data { value: Value::Str(JsStr::from_units(vec![c])), flags: ENUMERABLE });
                    }
                }
                if key.eq_str("length") {
                    return Some(Prop::Data { value: Value::Num(s.len() as f64), flags: 0 });
                }
            }
            ObjKind::TypedArray(t) => {
                if let Some(n) = canonical_numeric(key) {
                    return ta::ta_get_index(t, n).map(|v| Prop::Data { value: v, flags: WEC });
                }
            }
            ObjKind::Arguments(ad) => {
                if let Some(i) = key.as_index() {
                    if let Some(Some((env, slot))) = ad.mapped.get(i as usize) {
                        if let Some(Prop::Data { flags, .. }) = b.props.get(key) {
                            let v = env.0.vars.borrow()[*slot as usize].clone();
                            return Some(Prop::Data { value: v, flags: *flags });
                        }
                    }
                }
            }
            _ => {}
        }
        b.props.get(key).cloned()
    }

    pub fn get_own_property(&mut self, o: &Obj, key: &PropKey) -> JsResult<Option<PropDesc>> {
        if o.is_proxy() {
            return proxy::proxy_get_own_property(self, o, key);
        }
        if let ObjKind::Namespace(_) = &o.borrow().kind {
            return crate::modules::namespace_get_own(self, o, key);
        }
        Ok(self.ordinary_get_own(o, key).map(|p| PropDesc::from_prop(&p)))
    }

    pub fn has_own_property(&mut self, o: &Obj, key: &PropKey) -> JsResult<bool> {
        Ok(self.get_own_property(o, key)?.is_some())
    }

    pub fn has_property(&mut self, o: &Obj, key: &PropKey) -> JsResult<bool> {
        let mut cur = o.clone();
        loop {
            if cur.is_proxy() {
                return proxy::proxy_has(self, &cur, key);
            }
            {
                let b = cur.borrow();
                match &b.kind {
                    ObjKind::TypedArray(t) => {
                        if let Some(n) = canonical_numeric(key) {
                            return Ok(ta::ta_valid_index(t, n));
                        }
                    }
                    ObjKind::Namespace(_) => {
                        drop(b);
                        return Ok(crate::modules::namespace_get_own(self, &cur, key)?.is_some());
                    }
                    _ => {}
                }
            }
            if self.ordinary_get_own(&cur, key).is_some() {
                return Ok(true);
            }
            let p = cur.borrow().proto.clone();
            match p {
                Some(p) => cur = p,
                None => return Ok(false),
            }
        }
    }

    // ---------------- [[Get]] ----------------

    pub fn get(&mut self, o: &Obj, key: &PropKey, receiver: &Value) -> JsResult<Value> {
        let mut cur = o.clone();
        loop {
            let r = {
                let b = cur.borrow();
                let mut special = None;
                match &b.kind {
                    ObjKind::Proxy(_) => special = Some(GetR::Proxy),
                    ObjKind::Array(a) => {
                        if !a.sparse {
                            if let Some(i) = key.as_index() {
                                special = Some(match a.dense.get(i as usize) {
                                    Some(v) if !v.is_empty() => GetR::Found(v.clone()),
                                    _ => GetR::Next(b.proto.clone()),
                                });
                            }
                        }
                        if special.is_none() && key.eq_str("length") {
                            special = Some(GetR::Found(Value::Num(a.len as f64)));
                        }
                    }
                    ObjKind::String(s) => {
                        if let Some(i) = key.as_index() {
                            if (i as usize) < s.len() {
                                special = Some(GetR::Found(Value::Str(JsStr::from_units(vec![s.units()[i as usize]]))));
                            }
                        } else if key.eq_str("length") {
                            special = Some(GetR::Found(Value::Num(s.len() as f64)));
                        }
                    }
                    ObjKind::TypedArray(t) => {
                        if let Some(n) = canonical_numeric(key) {
                            special = Some(GetR::Found(ta::ta_get_index(t, n).unwrap_or(Value::Undefined)));
                        }
                    }
                    ObjKind::Namespace(_) => special = Some(GetR::Namespace),
                    ObjKind::Arguments(ad) => {
                        if let Some(i) = key.as_index() {
                            if let Some(Some((env, slot))) = ad.mapped.get(i as usize) {
                                if b.props.contains(key) {
                                    special = Some(GetR::Found(env.0.vars.borrow()[*slot as usize].clone()));
                                }
                            }
                        }
                    }
                    _ => {}
                }
                match special {
                    Some(s) => s,
                    None => match b.props.get(key) {
                        Some(Prop::Data { value, .. }) => GetR::Found(value.clone()),
                        Some(Prop::Accessor { get, .. }) => GetR::Getter(get.clone()),
                        None => GetR::Next(b.proto.clone()),
                    },
                }
            };
            match r {
                GetR::Found(v) => return Ok(v),
                GetR::Getter(Some(g)) => return self.call_obj(&g, receiver.clone(), &[]),
                GetR::Getter(None) => return Ok(Value::Undefined),
                GetR::Next(Some(p)) => cur = p,
                GetR::Next(None) => return Ok(Value::Undefined),
                GetR::Proxy => return proxy::proxy_get(self, &cur, key, receiver),
                GetR::Namespace => return crate::modules::namespace_get(self, &cur, key),
            }
        }
    }

    pub fn get_str(&mut self, o: &Obj, key: &str) -> JsResult<Value> {
        self.get(o, &PropKey::from_str(key), &Value::Obj(o.clone()))
    }

    /// GetV on any value (primitives use their prototype)
    pub fn get_prop_of(&mut self, base: &Value, key: &PropKey) -> JsResult<Value> {
        match base {
            Value::Obj(o) => {
                // fast path: own data property on ordinary object
                {
                    let b = o.borrow();
                    if let ObjKind::Ordinary = b.kind {
                        if let Some(Prop::Data { value, .. }) = b.props.get(key) {
                            return Ok(value.clone());
                        }
                    }
                }
                self.get(o, key, base)
            }
            Value::Str(s) => {
                if let Some(i) = key.as_index() {
                    if (i as usize) < s.len() {
                        return Ok(Value::Str(JsStr::from_units(vec![s.units()[i as usize]])));
                    }
                } else if key.eq_str("length") {
                    return Ok(Value::Num(s.len() as f64));
                }
                let p = self.intr.string_proto.clone();
                self.get(&p, key, base)
            }
            Value::Num(_) => {
                let p = self.intr.number_proto.clone();
                self.get(&p, key, base)
            }
            Value::Bool(_) => {
                let p = self.intr.boolean_proto.clone();
                self.get(&p, key, base)
            }
            Value::Sym(_) => {
                let p = self.intr.symbol_proto.clone();
                self.get(&p, key, base)
            }
            Value::BigInt(_) => {
                let p = self.intr.bigint_proto.clone();
                self.get(&p, key, base)
            }
            Value::Undefined | Value::Null | Value::Empty => {
                let what = if base.is_null() { "null" } else { "undefined" };
                self.throw_type(format!("cannot read property '{}' of {}", key.to_display(), what))
            }
        }
    }

    pub fn get_elem(&mut self, base: &Value, key: &Value) -> JsResult<Value> {
        // fast paths for arrays / typed arrays / strings with numeric keys
        if let Value::Num(n) = key {
            let n = *n;
            if n >= 0.0 && n < 4294967295.0 && n.fract() == 0.0 {
                let i = n as usize;
                match base {
                    Value::Obj(o) => {
                        let b = o.borrow();
                        match &b.kind {
                            ObjKind::Array(a) if !a.sparse => {
                                if let Some(v) = a.dense.get(i) {
                                    if !v.is_empty() {
                                        return Ok(v.clone());
                                    }
                                }
                            }
                            ObjKind::TypedArray(t) => {
                                return Ok(ta::ta_get_index(t, n).unwrap_or(Value::Undefined));
                            }
                            _ => {}
                        }
                    }
                    Value::Str(s) => {
                        if i < s.len() {
                            return Ok(Value::Str(JsStr::from_units(vec![s.units()[i]])));
                        }
                    }
                    _ => {}
                }
            }
        }
        if base.is_nullish() {
            return self.throw_type("cannot read property of null or undefined");
        }
        let k = self.to_property_key(key)?;
        self.get_prop_of(base, &k)
    }

    // ---------------- [[Set]] ----------------

    pub fn set(&mut self, o: &Obj, key: PropKey, v: Value, receiver: &Value) -> JsResult<bool> {
        enum SetR {
            OwnData(bool),
            Setter(Option<Obj>),
            Next(Option<Obj>),
            Proxy,
            TypedArray(f64),
            Done(bool),
        }
        // fast path: receiver is o, ordinary object, own writable data property
        if let Value::Obj(r) = receiver {
            if r.ptr_eq(o) {
                let mut b = o.borrow_mut();
                match &mut b.kind {
                    ObjKind::Ordinary | ObjKind::Closure(_) | ObjKind::Error => {
                        if let Some(Prop::Data { value, flags }) = b.props.get_mut(&key) {
                            if *flags & WRITABLE != 0 {
                                *value = v;
                                return Ok(true);
                            }
                            return Ok(false);
                        }
                    }
                    ObjKind::Array(a) => {
                        if !a.sparse {
                            if let Some(i) = key.as_index() {
                                let i = i as usize;
                                if i < a.dense.len() && !a.dense[i].is_empty() {
                                    a.dense[i] = v;
                                    return Ok(true);
                                }
                            }
                        }
                    }
                    _ => {}
                }
            }
        }
        let mut cur = o.clone();
        loop {
            let r = {
                let b = cur.borrow();
                let mut special = None;
                match &b.kind {
                    ObjKind::Proxy(_) => special = Some(SetR::Proxy),
                    ObjKind::Array(a) => {
                        if key.eq_str("length") {
                            special = Some(SetR::OwnData(a.length_writable));
                        } else if !a.sparse {
                            if let Some(i) = key.as_index() {
                                special = Some(match a.dense.get(i as usize) {
                                    Some(x) if !x.is_empty() => SetR::OwnData(true),
                                    _ => SetR::Next(b.proto.clone()),
                                });
                            }
                        }
                    }
                    ObjKind::String(s) => {
                        if let Some(i) = key.as_index() {
                            if (i as usize) < s.len() {
                                special = Some(SetR::OwnData(false));
                            }
                        } else if key.eq_str("length") {
                            special = Some(SetR::OwnData(false));
                        }
                    }
                    ObjKind::TypedArray(_) => {
                        if let Some(n) = canonical_numeric(&key) {
                            special = Some(SetR::TypedArray(n));
                        }
                    }
                    ObjKind::Namespace(_) => special = Some(SetR::Done(false)),
                    _ => {}
                }
                match special {
                    Some(s) => s,
                    None => match b.props.get(&key) {
                        Some(Prop::Data { flags, .. }) => SetR::OwnData(flags & WRITABLE != 0),
                        Some(Prop::Accessor { set, .. }) => SetR::Setter(set.clone()),
                        None => SetR::Next(b.proto.clone()),
                    },
                }
            };
            match r {
                SetR::Done(b) => return Ok(b),
                SetR::OwnData(false) => return Ok(false),
                SetR::OwnData(true) => return self.set_on_receiver(key, v, receiver),
                SetR::Setter(Some(s)) => {
                    self.call_obj(&s, receiver.clone(), &[v])?;
                    return Ok(true);
                }
                SetR::Setter(None) => return Ok(false),
                SetR::Next(Some(p)) => cur = p,
                SetR::Next(None) => return self.set_on_receiver(key, v, receiver),
                SetR::Proxy => return proxy::proxy_set(self, &cur, key, v, receiver),
                SetR::TypedArray(n) => {
                    let same = matches!(receiver, Value::Obj(r) if r.ptr_eq(&cur));
                    if same {
                        ta::ta_set_index(self, &cur, n, &v)?;
                        return Ok(true);
                    }
                    let valid = match &cur.borrow().kind {
                        ObjKind::TypedArray(t) => ta::ta_valid_index(t, n),
                        _ => false,
                    };
                    if !valid {
                        return Ok(true);
                    }
                    return self.set_on_receiver(key, v, receiver);
                }
            }
        }
    }

    fn set_on_receiver(&mut self, key: PropKey, v: Value, receiver: &Value) -> JsResult<bool> {
        let ro = match receiver {
            Value::Obj(o) => o.clone(),
            _ => return Ok(false),
        };
        let existing = self.get_own_property(&ro, &key)?;
        match existing {
            Some(d) => {
                if d.is_accessor() {
                    return Ok(false);
                }
                if d.writable != Some(true) {
                    return Ok(false);
                }
                // fast in-place update for ordinary objects
                if !ro.is_proxy() {
                    let mut b = ro.borrow_mut();
                    if let ObjKind::Ordinary = b.kind {
                        if let Some(Prop::Data { value, .. }) = b.props.get_mut(&key) {
                            *value = v;
                            return Ok(true);
                        }
                    }
                }
                self.define_own_property(&ro, key, PropDesc { value: Some(v), ..Default::default() })
            }
            None => self.create_data_property(&ro, key, v),
        }
    }

    /// PutValue on any base (throws in strict mode on failure)
    pub fn set_prop_of(&mut self, base: &Value, key: PropKey, v: Value, strict: bool) -> JsResult<()> {
        match base {
            Value::Obj(o) => {
                let ok = self.set(o, key.clone(), v, base)?;
                if !ok && strict {
                    if let ObjKind::Namespace(_) = o.borrow().kind {
                        return Ok(());
                    }
                    let msg = self.set_failure_message(o, &key)?;
                    return self.throw_type(msg);
                }
                Ok(())
            }
            Value::Undefined | Value::Null | Value::Empty => {
                let what = if base.is_null() { "null" } else { "undefined" };
                self.throw_type(format!("cannot set property '{}' of {}", key.to_display(), what))
            }
            _ => {
                // primitive base: look up setter on prototype
                let proto = self.proto_for_primitive(base);
                let ok = self.set(&proto, key.clone(), v, base)?;
                if !ok && strict {
                    return self.throw_type(format!("Cannot create property '{}' on {} value", key.to_display(), base.type_of()));
                }
                Ok(())
            }
        }
    }

    /// Message for a failed strict-mode [[Set]].
    pub fn set_failure_message(&mut self, o: &Obj, key: &PropKey) -> JsResult<String> {
        let mut cur = Some(o.clone());
        let mut first = true;
        while let Some(c) = cur {
            if c.is_proxy() {
                break;
            }
            if let Some(p) = self.ordinary_get_own(&c, key) {
                match p {
                    Prop::Accessor { set: None, .. } => return Ok(format!("cannot set getter-only property '{}'", key.to_display())),
                    Prop::Data { flags, .. } if flags & WRITABLE == 0 => return Ok(format!("cannot assign to read-only property '{}'", key.to_display())),
                    _ => {
                        if first {
                            return Ok(format!("cannot assign to read-only property '{}'", key.to_display()));
                        }
                        break;
                    }
                }
            }
            first = false;
            cur = c.borrow().proto.clone();
        }
        if !o.borrow().extensible {
            return Ok("cannot add property, object is not extensible".to_string());
        }
        Ok(format!("cannot assign to read-only property '{}'", key.to_display()))
    }

    pub fn proto_for_primitive(&self, v: &Value) -> Obj {
        match v {
            Value::Str(_) => self.intr.string_proto.clone(),
            Value::Num(_) => self.intr.number_proto.clone(),
            Value::Bool(_) => self.intr.boolean_proto.clone(),
            Value::Sym(_) => self.intr.symbol_proto.clone(),
            Value::BigInt(_) => self.intr.bigint_proto.clone(),
            _ => self.intr.object_proto.clone(),
        }
    }

    pub fn set_elem(&mut self, base: &Value, key: &Value, v: Value, strict: bool) -> JsResult<()> {
        if let (Value::Obj(o), Value::Num(n)) = (base, key) {
            let n = *n;
            if n >= 0.0 && n < 4294967295.0 && n.fract() == 0.0 {
                let i = n as usize;
                let mut b = o.borrow_mut();
                let ext = b.extensible;
                match &mut b.kind {
                    ObjKind::Array(a) if !a.sparse => {
                        if i < a.dense.len() {
                            if !a.dense[i].is_empty() || ext {
                                a.dense[i] = v;
                                return Ok(());
                            }
                        } else if i == a.dense.len() && ext && a.length_writable && a.dense.len() as u32 == a.len {
                            a.dense.push(v);
                            a.len += 1;
                            return Ok(());
                        }
                    }
                    ObjKind::TypedArray(_) => {
                        drop(b);
                        ta::ta_set_index(self, o, n, &v)?;
                        return Ok(());
                    }
                    _ => {}
                }
            }
        }
        if base.is_nullish() {
            return self.throw_type("cannot access property of null or undefined");
        }
        let k = self.to_property_key(key)?;
        self.set_prop_of(base, k, v, strict)
    }

    // ---------------- [[DefineOwnProperty]] ----------------

    pub fn create_data_property(&mut self, o: &Obj, key: PropKey, v: Value) -> JsResult<bool> {
        // fast path for ordinary extensible objects with no existing property
        {
            let mut b = o.borrow_mut();
            if b.extensible {
                if let ObjKind::Ordinary = b.kind {
                    match b.props.get_mut(&key) {
                        None => {
                            b.props.insert(key, Prop::Data { value: v, flags: WEC });
                            return Ok(true);
                        }
                        Some(Prop::Data { value, flags }) if *flags & CONFIGURABLE != 0 => {
                            *value = v;
                            *flags = WEC;
                            return Ok(true);
                        }
                        _ => {}
                    }
                }
            }
        }
        self.define_own_property(o, key, PropDesc::data(v, WEC))
    }

    pub fn create_data_property_or_throw(&mut self, o: &Obj, key: PropKey, v: Value) -> JsResult<()> {
        if !self.create_data_property(o, key.clone(), v)? {
            return self.throw_type(format!("Cannot redefine property: {}", key.to_display()));
        }
        Ok(())
    }

    pub fn define_property_or_throw(&mut self, o: &Obj, key: PropKey, desc: PropDesc) -> JsResult<()> {
        if !self.define_own_property(o, key.clone(), desc)? {
            return self.throw_type(format!("Cannot redefine property: {}", key.to_display()));
        }
        Ok(())
    }

    pub fn define_own_property(&mut self, o: &Obj, key: PropKey, desc: PropDesc) -> JsResult<bool> {
        enum Kind {
            Ordinary,
            Array,
            TypedArray,
            Proxy,
            StringObj(usize),
            Namespace,
            Arguments,
        }
        let kind = match &o.borrow().kind {
            ObjKind::Array(_) => Kind::Array,
            ObjKind::TypedArray(_) => Kind::TypedArray,
            ObjKind::Proxy(_) => Kind::Proxy,
            ObjKind::String(s) => Kind::StringObj(s.len()),
            ObjKind::Namespace(_) => Kind::Namespace,
            ObjKind::Arguments(_) => Kind::Arguments,
            _ => Kind::Ordinary,
        };
        match kind {
            Kind::Proxy => proxy::proxy_define_own_property(self, o, key, desc),
            Kind::Array => self.array_define_own_property(o, key, desc),
            Kind::TypedArray => {
                if let Some(n) = canonical_numeric(&key) {
                    return ta::ta_define_own_property(self, o, n, desc);
                }
                Ok(self.ordinary_define_own_property(o, key, desc))
            }
            Kind::StringObj(len) => {
                if let Some(i) = key.as_index() {
                    if (i as usize) < len {
                        let cur = self.ordinary_get_own(o, &key);
                        return Ok(validate_and_apply(None, &key, false, &desc, cur));
                    }
                }
                if key.eq_str("length") {
                    let cur = self.ordinary_get_own(o, &key);
                    return Ok(validate_and_apply(None, &key, false, &desc, cur));
                }
                Ok(self.ordinary_define_own_property(o, key, desc))
            }
            Kind::Namespace => crate::modules::namespace_define(self, o, &key, &desc),
            Kind::Arguments => {
                // unmap on accessor or non-writable definitions
                let r = self.ordinary_define_own_property(o, key.clone(), desc.clone());
                if r {
                    if let Some(i) = key.as_index() {
                        let mut b = o.borrow_mut();
                        if let ObjKind::Arguments(ad) = &mut b.kind {
                            if let Some(Some((env, slot))) = ad.mapped.get(i as usize).cloned() {
                                if desc.is_accessor() {
                                    ad.mapped[i as usize] = None;
                                } else {
                                    if let Some(v) = &desc.value {
                                        env.0.vars.borrow_mut()[slot as usize] = v.clone();
                                    }
                                    if desc.writable == Some(false) {
                                        ad.mapped[i as usize] = None;
                                    }
                                }
                            }
                        }
                    }
                }
                Ok(r)
            }
            Kind::Ordinary => Ok(self.ordinary_define_own_property(o, key, desc)),
        }
    }

    pub fn ordinary_define_own_property(&mut self, o: &Obj, key: PropKey, desc: PropDesc) -> bool {
        let cur = o.borrow().props.get(&key).cloned();
        let ext = o.borrow().extensible;
        validate_and_apply(Some(o), &key, ext, &desc, cur)
    }

    fn array_to_sparse(o: &Obj) {
        let mut b = o.borrow_mut();
        let dense = match &mut b.kind {
            ObjKind::Array(a) => {
                if a.sparse {
                    return;
                }
                a.sparse = true;
                std::mem::take(&mut a.dense)
            }
            _ => return,
        };
        // indices must come first in key order; PropMap orders numerics separately anyway
        let old: Vec<(PropKey, Prop)> = b.props.iter().map(|(k, p)| (k.clone(), p.clone())).collect();
        b.props.clear();
        for (i, v) in dense.into_iter().enumerate() {
            if !v.is_empty() {
                b.props.insert(PropKey::from_index(i as u32), Prop::Data { value: v, flags: WEC });
            }
        }
        for (k, p) in old {
            b.props.insert(k, p);
        }
    }

    pub fn array_define_own_property(&mut self, o: &Obj, key: PropKey, desc: PropDesc) -> JsResult<bool> {
        if key.eq_str("length") {
            return self.array_set_length(o, desc);
        }
        if let Some(idx) = key.as_index() {
            let (len, len_writable, sparse) = match &o.borrow().kind {
                ObjKind::Array(a) => (a.len, a.length_writable, a.sparse),
                _ => unreachable!(),
            };
            if idx >= len && !len_writable {
                return Ok(false);
            }
            // fast dense path: plain data definition
            let plain = desc.get.is_none()
                && desc.set.is_none()
                && desc.writable != Some(false)
                && desc.enumerable != Some(false)
                && desc.configurable != Some(false);
            if !sparse {
                let i = idx as usize;
                let exists = match &o.borrow().kind {
                    ObjKind::Array(a) => a.dense.get(i).map_or(false, |v| !v.is_empty()),
                    _ => false,
                };
                let full = desc.writable == Some(true) && desc.enumerable == Some(true) && desc.configurable == Some(true);
                if plain && (exists || full) && (exists || o.borrow().extensible) {
                    let mut b = o.borrow_mut();
                    if let ObjKind::Array(a) = &mut b.kind {
                        if i < a.dense.len() || i <= a.dense.len() + 64 || i < (a.dense.len() * 2) {
                            if let Some(v) = desc.value.clone() {
                                if i >= a.dense.len() {
                                    a.dense.resize(i + 1, Value::Empty);
                                }
                                a.dense[i] = v;
                            } else if !exists {
                                if i >= a.dense.len() {
                                    a.dense.resize(i + 1, Value::Empty);
                                }
                                a.dense[i] = Value::Undefined;
                            }
                            if idx >= a.len {
                                a.len = idx + 1;
                            }
                            return Ok(true);
                        }
                    }
                }
                Self::array_to_sparse(o);
            }
            let ok = self.ordinary_define_own_property(o, key, desc);
            if !ok {
                return Ok(false);
            }
            if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
                if idx >= a.len {
                    a.len = idx + 1;
                }
            }
            return Ok(true);
        }
        Ok(self.ordinary_define_own_property(o, key, desc))
    }

    fn array_set_length(&mut self, o: &Obj, desc: PropDesc) -> JsResult<bool> {
        if desc.is_accessor() {
            return Ok(false);
        }
        let (old_len, writable) = match &o.borrow().kind {
            ObjKind::Array(a) => (a.len, a.length_writable),
            _ => unreachable!(),
        };
        if desc.configurable == Some(true) || desc.enumerable == Some(true) {
            return Ok(false);
        }
        let new_len = match &desc.value {
            None => {
                if desc.writable == Some(true) && !writable {
                    return Ok(false);
                }
                if desc.writable == Some(false) {
                    if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
                        a.length_writable = false;
                    }
                }
                return Ok(true);
            }
            Some(v) => {
                let n = self.to_number(v)?;
                let u = crate::builtins::number::to_uint32(n);
                let n2 = self.to_number(v)?;
                if u as f64 != n2 {
                    return self.throw_range("Invalid array length");
                }
                u
            }
        };
        if new_len == old_len {
            if desc.writable == Some(true) && !writable {
                return Ok(false);
            }
            if desc.writable == Some(false) {
                if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
                    a.length_writable = false;
                }
            }
            return Ok(true);
        }
        if !writable {
            return Ok(false);
        }
        let sparse = matches!(&o.borrow().kind, ObjKind::Array(a) if a.sparse);
        if new_len > old_len {
            if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
                a.len = new_len;
                if desc.writable == Some(false) {
                    a.length_writable = false;
                }
            }
            return Ok(true);
        }
        if !sparse {
            if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
                if (new_len as usize) < a.dense.len() {
                    a.dense.truncate(new_len as usize);
                }
                a.len = new_len;
                if desc.writable == Some(false) {
                    a.length_writable = false;
                }
            }
            return Ok(true);
        }
        // sparse: delete indices >= new_len from highest down
        let mut idxs: Vec<u32> = o.borrow().props.keys().iter().filter_map(|k| k.as_index()).filter(|i| *i >= new_len).collect();
        idxs.sort_unstable_by(|a, b| b.cmp(a));
        for i in idxs {
            let k = PropKey::from_index(i);
            let configurable = o.borrow().props.get(&k).map_or(true, |p| p.configurable());
            if !configurable {
                if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
                    a.len = i + 1;
                    if desc.writable == Some(false) {
                        a.length_writable = false;
                    }
                }
                return Ok(false);
            }
            o.borrow_mut().props.remove(&k);
        }
        if let ObjKind::Array(a) = &mut o.borrow_mut().kind {
            a.len = new_len;
            if desc.writable == Some(false) {
                a.length_writable = false;
            }
        }
        Ok(true)
    }

    // ---------------- [[Delete]] ----------------

    pub fn delete(&mut self, o: &Obj, key: &PropKey) -> JsResult<bool> {
        if o.is_proxy() {
            return proxy::proxy_delete(self, o, key);
        }
        let mut b = o.borrow_mut();
        match &mut b.kind {
            ObjKind::Array(a) => {
                if key.eq_str("length") {
                    return Ok(false);
                }
                if !a.sparse {
                    if let Some(i) = key.as_index() {
                        let i = i as usize;
                        if i < a.dense.len() {
                            if i + 1 == a.dense.len() {
                                a.dense.pop();
                                while matches!(a.dense.last(), Some(Value::Empty)) {
                                    a.dense.pop();
                                }
                            } else {
                                a.dense[i] = Value::Empty;
                            }
                        }
                        return Ok(true);
                    }
                }
            }
            ObjKind::String(s) => {
                if let Some(i) = key.as_index() {
                    if (i as usize) < s.len() {
                        return Ok(false);
                    }
                }
                if key.eq_str("length") {
                    return Ok(false);
                }
            }
            ObjKind::TypedArray(t) => {
                if let Some(n) = canonical_numeric(key) {
                    return Ok(!ta::ta_valid_index(t, n));
                }
            }
            ObjKind::Namespace(_) => {
                drop(b);
                return crate::modules::namespace_delete(self, o, key);
            }
            ObjKind::Arguments(ad) => {
                if let Some(i) = key.as_index() {
                    if let Some(m) = ad.mapped.get_mut(i as usize) {
                        *m = None;
                    }
                }
            }
            _ => {}
        }
        match b.props.get(key) {
            None => Ok(true),
            Some(p) => {
                if p.configurable() {
                    b.props.remove(key);
                    Ok(true)
                } else {
                    Ok(false)
                }
            }
        }
    }

    pub fn delete_prop_of(&mut self, base: &Value, key: &PropKey, strict: bool) -> JsResult<bool> {
        let o = match base {
            Value::Obj(o) => o.clone(),
            Value::Undefined | Value::Null => return self.throw_type("cannot convert undefined or null to object"),
            other => self.to_object(other)?,
        };
        let r = self.delete(&o, key)?;
        if !r && strict {
            return self.throw_type(format!("cannot delete non-configurable property '{}'", key.to_display()));
        }
        Ok(r)
    }

    // ---------------- [[OwnPropertyKeys]] ----------------

    pub fn own_property_keys(&mut self, o: &Obj) -> JsResult<Vec<PropKey>> {
        if o.is_proxy() {
            return proxy::proxy_own_keys(self, o);
        }
        if let ObjKind::Namespace(_) = &o.borrow().kind {
            return Ok(crate::modules::namespace_keys(self, o));
        }
        Ok(self.ordinary_own_keys(o))
    }

    pub fn ordinary_own_keys(&self, o: &Obj) -> Vec<PropKey> {
        let b = o.borrow();
        match &b.kind {
            ObjKind::Array(a) if !a.sparse => {
                let mut out: Vec<PropKey> = Vec::with_capacity(a.dense.len() + b.props.len() + 1);
                for (i, v) in a.dense.iter().enumerate() {
                    if !v.is_empty() {
                        out.push(PropKey::from_index(i as u32));
                    }
                }
                out.push(self.intr.key_length.clone());
                out.extend(b.props.ordered_keys());
                out
            }
            ObjKind::Array(_) => {
                let keys = b.props.ordered_keys();
                let mut out = Vec::with_capacity(keys.len() + 1);
                let mut inserted = false;
                for k in keys {
                    if !inserted && k.as_index().is_none() {
                        out.push(self.intr.key_length.clone());
                        inserted = true;
                    }
                    out.push(k);
                }
                if !inserted {
                    out.push(self.intr.key_length.clone());
                }
                out
            }
            ObjKind::String(s) => {
                let mut out: Vec<PropKey> = (0..s.len() as u32).map(PropKey::from_index).collect();
                let keys = b.props.ordered_keys();
                let mut rest = Vec::new();
                for k in keys {
                    if k.as_index().is_some() {
                        out.push(k);
                    } else {
                        rest.push(k);
                    }
                }
                out.push(self.intr.key_length.clone());
                out.extend(rest);
                out
            }
            ObjKind::TypedArray(t) => {
                let n = t.len();
                let mut out: Vec<PropKey> = (0..n as u32).map(PropKey::from_index).collect();
                out.extend(b.props.ordered_keys());
                out
            }
            _ => b.props.ordered_keys(),
        }
    }

    // ---------------- misc helpers ----------------

    pub fn get_method(&mut self, v: &Value, key: &PropKey) -> JsResult<Option<Value>> {
        let f = self.get_prop_of(v, key)?;
        if f.is_nullish() {
            return Ok(None);
        }
        if !f.is_callable() {
            return self.throw_type(format!("{} is not a function", key.to_display()));
        }
        Ok(Some(f))
    }

    pub fn copy_data_properties(&mut self, target: &Obj, src: &Value, excluded: &[PropKey]) -> JsResult<()> {
        let from = match src {
            Value::Undefined | Value::Null => return Ok(()),
            Value::Obj(o) => o.clone(),
            other => self.to_object(other)?,
        };
        // fast path: ordinary source
        let keys = self.own_property_keys(&from)?;
        for k in keys {
            if excluded.iter().any(|e| *e == k) {
                continue;
            }
            let desc = self.get_own_property(&from, &k)?;
            if let Some(d) = desc {
                if d.enumerable == Some(true) {
                    let v = self.get(&from, &k, &Value::Obj(from.clone()))?;
                    self.create_data_property(target, k, v)?;
                }
            }
        }
        Ok(())
    }

    /// Enumerable own string keys (for Object.keys etc.)
    pub fn enumerable_own_keys(&mut self, o: &Obj) -> JsResult<Vec<JsStr>> {
        let keys = self.own_property_keys(o)?;
        let mut out = Vec::new();
        let ordinary = !o.is_proxy();
        for k in keys {
            if let PropKey::Str(s) = &k {
                if ordinary {
                    if let Some(p) = self.ordinary_get_own(o, &k) {
                        if p.enumerable() {
                            out.push(s.clone());
                        }
                        continue;
                    }
                    if let ObjKind::Namespace(_) = &o.borrow().kind {
                    } else {
                        continue;
                    }
                }
                if let Some(d) = self.get_own_property(o, &k)? {
                    if d.enumerable == Some(true) {
                        out.push(s.clone());
                    }
                }
            }
        }
        Ok(out)
    }

    pub fn length_of(&mut self, o: &Obj) -> JsResult<u64> {
        if let ObjKind::Array(a) = &o.borrow().kind {
            return Ok(a.len as u64);
        }
        let v = self.get(o, &self.intr.key_length.clone(), &Value::Obj(o.clone()))?;
        self.to_length(&v)
    }
}

/// ValidateAndApplyPropertyDescriptor. If `o` is None, only validates.
pub fn validate_and_apply(o: Option<&Obj>, key: &PropKey, extensible: bool, desc: &PropDesc, current: Option<Prop>) -> bool {
    let cur = match current {
        None => {
            if !extensible {
                return false;
            }
            if let Some(o) = o {
                let prop = if desc.is_accessor() {
                    Prop::Accessor {
                        get: desc.get.clone().and_then(|v| v.as_obj().cloned()),
                        set: desc.set.clone().and_then(|v| v.as_obj().cloned()),
                        flags: desc.flags() & !WRITABLE,
                    }
                } else {
                    Prop::Data { value: desc.value.clone().unwrap_or(Value::Undefined), flags: desc.flags() }
                };
                o.borrow_mut().props.insert(key.clone(), prop);
            }
            return true;
        }
        Some(c) => c,
    };
    if desc.is_generic() && desc.enumerable.is_none() && desc.configurable.is_none() {
        return true;
    }
    let cur_conf = cur.configurable();
    if !cur_conf {
        if desc.configurable == Some(true) {
            return false;
        }
        if let Some(e) = desc.enumerable {
            if e != cur.enumerable() {
                return false;
            }
        }
        if !desc.is_generic() {
            let cur_is_acc = matches!(cur, Prop::Accessor { .. });
            if desc.is_accessor() != cur_is_acc {
                return false;
            }
            match &cur {
                Prop::Accessor { get, set, .. } => {
                    if let Some(g) = &desc.get {
                        let same = match (g, get) {
                            (Value::Obj(a), Some(b)) => a.ptr_eq(b),
                            (Value::Undefined, None) => true,
                            _ => false,
                        };
                        if !same {
                            return false;
                        }
                    }
                    if let Some(s) = &desc.set {
                        let same = match (s, set) {
                            (Value::Obj(a), Some(b)) => a.ptr_eq(b),
                            (Value::Undefined, None) => true,
                            _ => false,
                        };
                        if !same {
                            return false;
                        }
                    }
                }
                Prop::Data { value, flags } => {
                    if flags & WRITABLE == 0 {
                        if desc.writable == Some(true) {
                            return false;
                        }
                        if let Some(v) = &desc.value {
                            if !Value::same_value(v, value) {
                                return false;
                            }
                        }
                    }
                }
            }
        }
    }
    let o = match o {
        Some(o) => o,
        None => return true,
    };
    // apply
    let new_prop = match (&cur, desc.is_accessor(), desc.is_data()) {
        (Prop::Data { flags, .. }, true, _) => {
            let mut f = flags & (ENUMERABLE | CONFIGURABLE);
            if let Some(e) = desc.enumerable {
                f = if e { f | ENUMERABLE } else { f & !ENUMERABLE };
            }
            if let Some(c) = desc.configurable {
                f = if c { f | CONFIGURABLE } else { f & !CONFIGURABLE };
            }
            Prop::Accessor {
                get: desc.get.clone().and_then(|v| v.as_obj().cloned()),
                set: desc.set.clone().and_then(|v| v.as_obj().cloned()),
                flags: f,
            }
        }
        (Prop::Accessor { flags, .. }, false, true) => {
            let mut f = flags & (ENUMERABLE | CONFIGURABLE);
            if let Some(e) = desc.enumerable {
                f = if e { f | ENUMERABLE } else { f & !ENUMERABLE };
            }
            if let Some(c) = desc.configurable {
                f = if c { f | CONFIGURABLE } else { f & !CONFIGURABLE };
            }
            if desc.writable == Some(true) {
                f |= WRITABLE;
            }
            Prop::Data { value: desc.value.clone().unwrap_or(Value::Undefined), flags: f }
        }
        (Prop::Data { value, flags }, _, _) => {
            let mut f = *flags;
            if let Some(e) = desc.enumerable {
                f = if e { f | ENUMERABLE } else { f & !ENUMERABLE };
            }
            if let Some(c) = desc.configurable {
                f = if c { f | CONFIGURABLE } else { f & !CONFIGURABLE };
            }
            if let Some(w) = desc.writable {
                f = if w { f | WRITABLE } else { f & !WRITABLE };
            }
            Prop::Data { value: desc.value.clone().unwrap_or_else(|| value.clone()), flags: f }
        }
        (Prop::Accessor { get, set, flags }, _, _) => {
            let mut f = *flags;
            if let Some(e) = desc.enumerable {
                f = if e { f | ENUMERABLE } else { f & !ENUMERABLE };
            }
            if let Some(c) = desc.configurable {
                f = if c { f | CONFIGURABLE } else { f & !CONFIGURABLE };
            }
            Prop::Accessor {
                get: match &desc.get {
                    Some(v) => v.as_obj().cloned(),
                    None => get.clone(),
                },
                set: match &desc.set {
                    Some(v) => v.as_obj().cloned(),
                    None => set.clone(),
                },
                flags: f,
            }
        }
    };
    o.borrow_mut().props.insert(key.clone(), new_prop);
    true
}
