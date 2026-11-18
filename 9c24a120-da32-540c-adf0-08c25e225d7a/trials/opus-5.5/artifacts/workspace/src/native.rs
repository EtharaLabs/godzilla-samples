// `--native`: annotations for mypyc. Module-level values, function
// signatures and class fields carry Python types where they say something
// mypyc can use; sum types get a union alias; ordering methods are written
// out instead of `functools.total_ordering`.

use crate::infer::*;
use crate::lower::Lowerer;
use crate::types::*;

impl<'a> Lowerer<'a> {
    /// The annotation for a value of type `t`, if it has one: functions,
    /// lazy and asynchronous values and foreign types have none. An unknown
    /// part reads as `Any` when `vars` (module-level values), and leaves
    /// the annotation out otherwise (signatures).
    pub fn native_ann(&mut self, t: &Ty, vars: bool) -> Option<String> {
        let t = self.ck.st.resolve(t);
        match &t {
            Ty::Var(_) | Ty::Gen(_) => {
                if vars {
                    self.needs.any = true;
                    Some("Any".into())
                } else {
                    None
                }
            }
            Ty::Num(k, _) => Some(if self.ck.st.kind(*k) == Kind::Float { "float".into() } else { "int".into() }),
            Ty::Fun(..) => None,
            Ty::Tuple(ts) => {
                let mut parts = Vec::new();
                for x in ts {
                    parts.push(self.native_ann(x, vars)?);
                }
                Some(format!("tuple[{}]", parts.join(", ")))
            }
            Ty::Con(n, args) => match (n.as_str(), args.len()) {
                ("bool", 0) => Some("bool".into()),
                ("string", 0) => Some("str".into()),
                ("unit", 0) => Some("None".into()),
                ("List", 1) => Some(format!("list[{}]", self.native_ann(&args[0], vars)?)),
                ("Set", 1) => Some(format!("set[{}]", self.native_ann(&args[0], vars)?)),
                ("Map", 2) => {
                    let k = self.native_ann(&args[0], vars)?;
                    let v = self.native_ann(&args[1], vars)?;
                    Some(format!("dict[{}, {}]", k, v))
                }
                // whether the classes exist is known once the module is lowered
                ("Option", 1) => Some(OPTION_MARK.to_string()),
                ("Result", 2) => Some(RESULT_MARK.to_string()),
                _ => self.user_type_ann(n),
            },
        }
    }

    /// A type this module declares, by the name its class or alias goes by.
    fn user_type_ann(&self, n: &str) -> Option<String> {
        let info = self.ck.types.get(n)?;
        if info.module.is_some() || !self.has_code {
            return None;
        }
        match &info.def {
            TypeDef::Adt(ctors) if !ctors.iter().any(|c| c == n) => Some(n.to_string()),
            TypeDef::Record(_) => Some(n.to_string()),
            _ => None,
        }
    }

    /// A class field's annotation: the plain types as they are, the
    /// containers bare, a type declared here as a forward reference.
    pub fn native_field_ann(&mut self, t: &Ty) -> String {
        let s = match t {
            Ty::Num(Kind::Int, _) => "int".to_string(),
            Ty::Num(Kind::Float, _) => "float".to_string(),
            Ty::Tuple(_) => "tuple".to_string(),
            Ty::Con(n, args) => match n.as_str() {
                "string" => "str".to_string(),
                "bool" => "bool".to_string(),
                "List" => "list".to_string(),
                "Map" => "dict".to_string(),
                "Set" => "set".to_string(),
                // (a forward reference still brings in `Any`)
                _ if args.is_empty() => match self.user_type_ann(n) {
                    Some(a) => {
                        self.needs.any = true;
                        format!("\"{}\"", a)
                    }
                    None => "Any".to_string(),
                },
                _ => "Any".to_string(),
            },
            _ => "Any".to_string(),
        };
        if s == "Any" {
            self.needs.any = true;
        }
        s
    }

    /// `name: T` for a value bound at module level.
    pub fn annotated_target(&mut self, py: &str, t: Option<Ty>) -> String {
        if !self.native {
            return py.to_string();
        }
        match t.and_then(|t| self.native_ann(&t, true)) {
            Some(a) => format!("{}{}", py, annotation(": ", &a)),
            None => py.to_string(),
        }
    }
}

/// Stand-ins for `Some | None_` and `Ok | Error` until the module is known
/// to define (or import) those classes.
pub const OPTION_MARK: &str = "\u{4}";
pub const RESULT_MARK: &str = "\u{5}";

/// `sep` and the annotation, bracketed for later resolution when it names
/// Option or Result.
pub fn annotation(sep: &str, ann: &str) -> String {
    if ann.contains(OPTION_MARK) || ann.contains(RESULT_MARK) {
        format!("\u{2}{}{}\u{3}", sep, ann)
    } else {
        format!("{}{}", sep, ann)
    }
}

/// Settle the bracketed annotations: kept (spelled out) when the classes
/// they name are present, dropped otherwise.
pub fn resolve_annotations(text: &str, option: bool, result: bool) -> String {
    if !text.contains('\u{2}') {
        return text.to_string();
    }
    let mut out = String::new();
    let mut rest = text;
    while let Some(i) = rest.find('\u{2}') {
        out.push_str(&rest[..i]);
        let after = &rest[i + 1..];
        let j = after.find('\u{3}').unwrap_or(after.len());
        let ann = &after[..j];
        if (!ann.contains(OPTION_MARK) || option) && (!ann.contains(RESULT_MARK) || result) {
            out.push_str(&ann.replace(OPTION_MARK, "Some | None_").replace(RESULT_MARK, "Ok | Error"));
        }
        rest = if j < after.len() { &after[j + 1..] } else { "" };
    }
    out.push_str(rest);
    out
}

/// A sum type's case class written for mypyc: ordering spelled out.
pub fn adt_class_native(name: &str, annots: &[String], ordered: Option<usize>, singleton: bool) -> String {
    adt_class_native_with(name, annots, ordered, singleton, true)
}

/// `annotate_singleton`: the shared instance of a field-less case is
/// annotated with its class (only in a program with code).
pub fn adt_class_native_with(name: &str, annots: &[String], ordered: Option<usize>, singleton: bool, annotate_singleton: bool) -> String {
    let mut s = String::new();
    s.push_str("@dataclass(frozen=True, slots=True, repr=False)\n");
    s.push_str(&format!("class {}:\n", name));
    for (i, a) in annots.iter().enumerate() {
        s.push_str(&format!("    _{}: {}\n", i, a));
    }
    s.push_str("    def __repr__(self):\n");
    if annots.is_empty() {
        s.push_str(&format!("        return \"{}\"\n", name));
    } else {
        let parts: Vec<String> = (0..annots.len()).map(|i| format!("{{self._{}!r}}", i)).collect();
        s.push_str(&format!("        return f\"{}({})\"\n", name, parts.join(", ")));
    }
    if let Some(idx) = ordered {
        s.push_str("    def __eq__(self, other):\n");
        s.push_str(&format!("        return type(other) is {} and self._pf_order_key() == other._pf_order_key()\n", name));
        for (m, op) in [("__lt__", "<"), ("__le__", "<="), ("__gt__", ">"), ("__ge__", ">=")] {
            s.push_str(&format!("    def {}(self, other):\n", m));
            s.push_str(&format!("        return self._pf_order_key() {} other._pf_order_key()\n", op));
        }
        s.push_str("    def _pf_order_key(self):\n");
        if annots.is_empty() {
            s.push_str(&format!("        return ({},)\n", idx));
        } else {
            let parts: Vec<String> = (0..annots.len()).map(|i| format!("self._{}", i)).collect();
            s.push_str(&format!("        return ({}, {})\n", idx, parts.join(", ")));
        }
    }
    if singleton {
        if annotate_singleton {
            s.push_str(&format!("_{}: {} = {}()\n", name, name, name));
        } else {
            s.push_str(&format!("_{} = {}()\n", name, name));
        }
    }
    s
}
