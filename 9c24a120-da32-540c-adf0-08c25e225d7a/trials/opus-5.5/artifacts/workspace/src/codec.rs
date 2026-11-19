// `Decode.auto`: a decoder derived from the type it is used at. Each use's
// type is fixed by the end of checking; it becomes a codec descriptor, and
// the records and sum types it reaches go into the module's `_pf_codecs`
// registry (keyed by the type as written, `Box int`).

use crate::diag::Diag;
use crate::infer::*;
use crate::types::*;
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub enum Codec {
    /// int, float, bool, str, unit
    Prim(&'static str),
    Ref(String),
    Option(Box<Codec>),
    List(Box<Codec>),
    Set(Box<Codec>),
    Map(Box<Codec>, Box<Codec>),
    Tuple(Vec<Codec>),
    /// a record class (declaring module, name) and its fields
    Record(Option<String>, String, Vec<(String, Codec)>),
    /// cases: (declaring module, constructor, nullary, argument codecs)
    Adt(Vec<(Option<String>, String, bool, Vec<Codec>)>),
}

const OPEN: &str = "cannot tell what `Decode.auto` decodes into here: its type is still open (`Decoder 'a`); use it where the decoded value's type is fixed, such as a `match` over the decoded record, a field access, or an argument to a function whose parameter type names it";

impl Checker {
    /// Settle every `Decode.auto` once the program is checked.
    pub fn check_autos(&mut self) {
        let uses = std::mem::take(&mut self.auto_types);
        for (span, t, _) in &uses {
            let inner = match self.st.resolve(t) {
                Ty::Con(_, args) if args.len() == 1 => args[0].clone(),
                other => other,
            };
            let mut reg = std::mem::take(&mut self.codecs);
            let r = self.codec_of(&inner, &mut reg);
            match r {
                Ok(c) => {
                    self.codecs = reg;
                    self.auto_codecs.insert(key(*span), c);
                }
                Err(msg) => {
                    self.codecs = reg;
                    self.errors.push(Diag::error(msg, *span));
                }
            }
        }
        self.auto_types = uses;
    }

    fn codec_of(&self, t: &Ty, reg: &mut BTreeMap<String, Codec>) -> Result<Codec, String> {
        let t = self.st.resolve(t);
        match &t {
            Ty::Var(_) | Ty::Gen(_) => Err(OPEN.to_string()),
            Ty::Num(k, _) => Ok(Codec::Prim(match self.st.kind(*k) {
                Kind::Float => "float",
                _ => "int",
            })),
            Ty::Fun(..) => Err(format!("cannot derive a decoder for `{}`: a function has no JSON form", self.st.show(&t))),
            Ty::Tuple(ts) => Ok(Codec::Tuple(ts.iter().map(|x| self.codec_of(x, reg)).collect::<Result<_, _>>()?)),
            Ty::Con(n, args) => match (n.as_str(), args.len()) {
                ("bool", 0) => Ok(Codec::Prim("bool")),
                ("string", 0) => Ok(Codec::Prim("str")),
                ("unit", 0) => Ok(Codec::Prim("unit")),
                ("Option", 1) => Ok(Codec::Option(Box::new(self.codec_of(&args[0], reg)?))),
                ("List", 1) => Ok(Codec::List(Box::new(self.codec_of(&args[0], reg)?))),
                ("Set", 1) => Ok(Codec::Set(Box::new(self.codec_of(&args[0], reg)?))),
                ("Map", 2) => {
                    let k = self.codec_of(&args[0], reg)?;
                    let v = self.codec_of(&args[1], reg)?;
                    Ok(Codec::Map(Box::new(k), Box::new(v)))
                }
                ("Result", 2) => {
                    let ok = self.codec_of(&args[0], reg)?;
                    let err = self.codec_of(&args[1], reg)?;
                    Ok(Codec::Adt(vec![(None, "Ok".into(), false, vec![ok]), (None, "Error".into(), false, vec![err])]))
                }
                ("Seq", _) => Err("cannot derive a decoder for a lazy `Seq`: decode a `List` and convert with `Seq.ofList`".to_string()),
                _ => self.user_codec(n, args, &t, reg),
            },
        }
    }

    fn user_codec(&self, n: &str, args: &[Ty], t: &Ty, reg: &mut BTreeMap<String, Codec>) -> Result<Codec, String> {
        let Some(info) = self.types.get(n) else {
            return Err(format!("cannot derive a decoder for `{}`: it has no JSON form", self.st.show(t)));
        };
        let subst = |x: &Ty| subst_gens(x, args);
        match &info.def {
            TypeDef::Opaque(u) => self.codec_of(&subst(u), reg),
            TypeDef::Extern => Err(format!(
                "cannot derive a decoder for `{}`: it is an extern type, so only Python knows its shape; decode into a Pyfun record or sum type instead",
                self.st.show(t)
            )),
            TypeDef::Builtin => Err(format!("cannot derive a decoder for `{}`: it has no JSON form", self.st.show(t))),
            TypeDef::Record(fields) => {
                let name = self.st.show(t);
                if !reg.contains_key(&name) {
                    // a placeholder first: the record may refer to itself
                    reg.insert(name.clone(), Codec::Prim("unit"));
                    let mut fs = Vec::new();
                    for (f, ft) in fields {
                        fs.push((f.clone(), self.codec_of(&subst(ft), reg)?));
                    }
                    reg.insert(name.clone(), Codec::Record(info.module.clone(), n.to_string(), fs));
                }
                Ok(Codec::Ref(name))
            }
            TypeDef::Adt(ctors) => {
                let name = self.st.show(t);
                if !reg.contains_key(&name) {
                    reg.insert(name.clone(), Codec::Prim("unit"));
                    let mut cases = Vec::new();
                    for c in ctors {
                        let Some(ci) = self.ctor_info_of(n, c) else { continue };
                        let mut cs = Vec::new();
                        for a in &ci.args {
                            cs.push(self.codec_of(&subst(a), reg)?);
                        }
                        cases.push((ci.module.clone(), c.clone(), ci.args.is_empty(), cs));
                    }
                    reg.insert(name.clone(), Codec::Adt(cases));
                }
                Ok(Codec::Ref(name))
            }
        }
    }

    fn ctor_info_of(&self, type_name: &str, ctor: &str) -> Option<CtorInfo> {
        self.ctors.values().find(|c| c.type_name == type_name && c.name == ctor).cloned()
    }
}


/// The descriptor as Python source; `class` names a record class or a
/// constructor (module, name, nullary) as the emitted module spells it.
pub fn render(c: &Codec, class: &dyn Fn(&Option<String>, &str, bool) -> String) -> String {
    match c {
        Codec::Prim(p) => format!("(\"{}\",)", p),
        Codec::Ref(n) => format!("(\"ref\", {})", py_str(n)),
        Codec::Option(x) => format!("(\"option\", {})", render(x, class)),
        Codec::List(x) => format!("(\"list\", {})", render(x, class)),
        Codec::Set(x) => format!("(\"set\", {})", render(x, class)),
        Codec::Map(k, v) => format!("(\"map\", {}, {})", render(k, class), render(v, class)),
        Codec::Tuple(xs) => {
            let v: Vec<String> = xs.iter().map(|x| render(x, class)).collect();
            format!("(\"tuple\", [{}])", v.join(", "))
        }
        Codec::Record(m, n, fs) => {
            let v: Vec<String> = fs.iter().map(|(f, x)| format!("({}, {})", py_str(f), render(x, class))).collect();
            format!("(\"record\", {}, [{}])", class(m, n, false), v.join(", "))
        }
        Codec::Adt(cases) => {
            let v: Vec<String> = cases
                .iter()
                .map(|(m, c, nullary, xs)| {
                    let a: Vec<String> = xs.iter().map(|x| render(x, class)).collect();
                    format!("{}: ({}, [{}])", py_str(c), class(m, c, *nullary), a.join(", "))
                })
                .collect();
            format!("(\"adt\", {{{}}})", v.join(", "))
        }
    }
}

fn py_str(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}
