//! Reading a favorites file as serde reads it into the original's structs: the same errors
//! (`invalid type`, `missing field`, `unknown field`…) at the same line and column. The text is
//! known to be well-formed JSON here (its syntax errors come from `json::parse`).

use crate::json::Value;

pub struct De<'a> {
    s: &'a [u8],
    i: usize,
}

type R<T> = Result<T, String>;

/// A field of a struct: its name, and whether it may be left out.
struct Field {
    name: &'static str,
    required: bool,
}

const fn f(name: &'static str, required: bool) -> Field {
    Field { name, required }
}

impl<'a> De<'a> {
    pub fn new(s: &'a [u8]) -> De<'a> {
        De { s, i: 0 }
    }

    fn at(&self, i: usize) -> String {
        let i = i.min(self.s.len());
        let start = self.s[..i].iter().rposition(|&c| c == b'\n').map(|p| p + 1).unwrap_or(0);
        let line = 1 + self.s[..start].iter().filter(|&&c| c == b'\n').count();
        format!("line {} column {}", line, i - start)
    }
    fn err(&self, msg: &str) -> String {
        format!("{} at {}", msg, self.at(self.i))
    }
    fn peek_err(&self, msg: &str) -> String {
        format!("{} at {}", msg, self.at(self.i + 1))
    }
    fn ws(&mut self) -> Option<u8> {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
        self.s.get(self.i).copied()
    }
    fn eat(&mut self, c: u8) {
        if self.ws() == Some(c) {
            self.i += 1;
        }
    }

    /// The end of a string whose opening quote is at `self.i`.
    fn string(&mut self) -> String {
        let start = self.i;
        self.i += 1;
        while self.i < self.s.len() {
            match self.s[self.i] {
                b'\\' => self.i += 2,
                b'"' => {
                    self.i += 1;
                    break;
                }
                _ => self.i += 1,
            }
        }
        match crate::json::parse_bytes(&self.s[start..self.i]) {
            Ok(Value::Str(s)) => s,
            _ => String::new(),
        }
    }
    /// A scalar or a whole value, parsed (the text being well-formed).
    fn scalar(&mut self) -> Value {
        let rest = std::str::from_utf8(&self.s[self.i..]).unwrap_or("");
        match crate::json::parse_prefix(rest) {
            Ok((v, n)) => {
                self.i += n;
                v
            }
            Err(_) => {
                self.i = self.s.len();
                Value::Null
            }
        }
    }
    fn skip(&mut self) {
        self.ws();
        self.scalar();
    }

    /// serde_json's "invalid type" for the value ahead: scalars are read first, `[` and `{` not.
    fn invalid_type(&mut self, exp: &str) -> String {
        match self.ws() {
            Some(b'[') => self.err(&format!("invalid type: sequence, expected {}", exp)),
            Some(b'{') => self.err(&format!("invalid type: map, expected {}", exp)),
            Some(b'"') => {
                let s = self.string();
                self.err(&format!("invalid type: string {:?}, expected {}", s, exp))
            }
            _ => {
                let v = self.scalar();
                let what = match &v {
                    Value::Null => "null".to_string(),
                    Value::Bool(b) => format!("boolean `{}`", b),
                    other => other.kind_name(),
                };
                self.err(&format!("invalid type: {}, expected {}", what, exp))
            }
        }
    }

    fn u_int(&mut self, max: u64, exp: &str) -> R<u64> {
        match self.ws() {
            Some(c) if c == b'-' || c.is_ascii_digit() => {
                let v = self.scalar();
                match v {
                    Value::Num(crate::json::Num::U(u)) if u <= max => Ok(u),
                    Value::Num(crate::json::Num::U(u)) => Err(self.err(&format!("invalid value: integer `{}`, expected {}", u, exp))),
                    Value::Num(crate::json::Num::I(i)) => Err(self.err(&format!("invalid value: integer `{}`, expected {}", i, exp))),
                    other => Err(self.err(&format!("invalid type: {}, expected {}", other.kind_name(), exp))),
                }
            }
            _ => Err(self.invalid_type(exp)),
        }
    }

    fn f64(&mut self) -> R<f64> {
        match self.ws() {
            Some(c) if c == b'-' || c.is_ascii_digit() => {
                let v = self.scalar();
                Ok(v.as_f64().unwrap_or(0.0))
            }
            _ => Err(self.invalid_type("f64")),
        }
    }

    fn string_value(&mut self) -> R<String> {
        match self.ws() {
            Some(b'"') => Ok(self.string()),
            _ => Err(self.invalid_type("a string")),
        }
    }

    fn opt<T>(&mut self, inner: impl FnOnce(&mut Self) -> R<T>) -> R<Option<T>> {
        if self.ws() == Some(b'n') {
            self.scalar();
            return Ok(None);
        }
        inner(self).map(Some)
    }

    /// A unit-variant enum, as a string of one of `variants`.
    fn variant(&mut self, variants: &[&str]) -> R<String> {
        match self.ws() {
            Some(b'"') => {
                let s = self.string();
                if variants.contains(&s.as_str()) {
                    Ok(s)
                } else {
                    let list: Vec<String> = variants.iter().map(|v| format!("`{}`", v)).collect();
                    Err(self.err(&format!("unknown variant `{}`, expected one of {}", s, list.join(", "))))
                }
            }
            _ => Err(self.peek_err("expected value")),
        }
    }

    /// `[T; n]`.
    fn array<T>(&mut self, n: usize, mut elem: impl FnMut(&mut Self) -> R<T>) -> R<Vec<T>> {
        let exp = format!("an array of length {}", n);
        if self.ws() != Some(b'[') {
            return Err(self.invalid_type(&exp));
        }
        self.i += 1;
        let mut out = Vec::new();
        for k in 0..n {
            if self.ws() == Some(b']') {
                self.i += 1;
                return Err(self.err(&format!("invalid length {}, expected {}", k, exp)));
            }
            if k > 0 {
                self.eat(b',');
            }
            out.push(elem(self)?);
        }
        match self.ws() {
            Some(b']') => {
                self.i += 1;
                Ok(out)
            }
            _ => {
                self.eat(b',');
                self.ws();
                Err(self.peek_err("trailing characters"))
            }
        }
    }

    /// A map of strings to values.
    fn map<T>(&mut self, mut val: impl FnMut(&mut Self, &str) -> R<T>) -> R<Vec<(String, T)>> {
        if self.ws() != Some(b'{') {
            return Err(self.invalid_type("a map"));
        }
        self.i += 1;
        let mut out: Vec<(String, T)> = Vec::new();
        let mut first = true;
        loop {
            if self.ws() == Some(b'}') {
                self.i += 1;
                return Ok(out);
            }
            if !first {
                self.eat(b',');
            }
            first = false;
            self.ws();
            let k = self.string();
            self.eat(b':');
            let v = val(self, &k)?;
            if let Some(slot) = out.iter_mut().find(|(kk, _)| *kk == k) {
                slot.1 = v;
            } else {
                out.push((k, v));
            }
        }
    }

    /// A struct with these fields (unknown ones refused): `val` reads the value of field `i`.
    fn strukt(&mut self, name: &str, fields: &[Field], mut val: impl FnMut(&mut Self, usize) -> R<()>) -> R<()> {
        let exp = format!("struct {}", name);
        match self.ws() {
            Some(b'{') => {}
            Some(b'[') => {
                // a struct may come as a sequence of its fields
                self.i += 1;
                let mut k = 0;
                loop {
                    if self.ws() == Some(b']') {
                        self.i += 1;
                        break;
                    }
                    if k > 0 {
                        self.eat(b',');
                    }
                    if k >= fields.len() {
                        self.ws();
                        return Err(self.peek_err("trailing characters"));
                    }
                    val(self, k)?;
                    k += 1;
                }
                if let Some(missing) = fields.iter().skip(k).find(|f| f.required) {
                    let _ = missing;
                    return Err(self.err(&format!("invalid length {}, expected {}", k, exp)));
                }
                return Ok(());
            }
            _ => return Err(self.invalid_type(&exp)),
        }
        self.i += 1;
        let mut seen = vec![false; fields.len()];
        let mut first = true;
        loop {
            if self.ws() == Some(b'}') {
                self.i += 1;
                break;
            }
            if !first {
                self.eat(b',');
            }
            first = false;
            self.ws();
            let k = self.string();
            match fields.iter().position(|f| f.name == k) {
                Some(fi) => {
                    if seen[fi] {
                        return Err(self.err(&format!("duplicate field `{}`", k)));
                    }
                    seen[fi] = true;
                    self.eat(b':');
                    val(self, fi)?;
                }
                None => {
                    let names: Vec<String> = fields.iter().map(|f| format!("`{}`", f.name)).collect();
                    let expected = match names.len() {
                        1 => format!("expected {}", names[0]),
                        2 => format!("expected {} or {}", names[0], names[1]),
                        _ => format!("expected one of {}", names.join(", ")),
                    };
                    return Err(self.err(&format!("unknown field `{}`, {}", k, expected)));
                }
            }
        }
        for (fi, fd) in fields.iter().enumerate() {
            if fd.required && !seen[fi] {
                return Err(self.err(&format!("missing field `{}`", fd.name)));
            }
        }
        Ok(())
    }
}

// ---------------------------------------------------------------- the favorites file

/// A picture kept with a favorite.
#[derive(Clone)]
pub struct PictureFile {
    pub name: String,
    pub png: String,
}

/// A favorite material: the material as the favorites file has it (patterns and its picture by
/// name), and the pictures it needs.
#[derive(Clone)]
pub struct MaterialEntry {
    /// The material, in file order (its texture's `image` a picture's id).
    pub material: Value,
    pub images: Vec<(String, PictureFile)>,
}

#[derive(Clone)]
pub struct FamilyEntry {
    pub family: Value,
    pub materials: Vec<(String, MaterialEntry)>,
}

#[derive(Default)]
pub struct Favorites {
    pub materials: Vec<(String, MaterialEntry)>,
    pub families: Vec<(String, FamilyEntry)>,
}

const PATTERNS: [&str; 10] = super::material::PATTERNS;
const KINDS: [&str; 11] = super::material::KINDS;

fn pair(de: &mut De) -> R<Value> {
    let a = de.array(2, |d| d.f64())?;
    Ok(Value::Arr(vec![Value::f(a[0]), Value::f(a[1])]))
}

fn texture(de: &mut De) -> R<Value> {
    let fields = [f("kind", true), f("size", true), f("angle", false), f("offset", false), f("image", false)];
    let mut kind = String::new();
    let mut size = Value::Null;
    let mut angle = 0.0;
    let mut offset = Value::Null;
    let mut image: Option<String> = None;
    de.strukt("Texture", &fields, |d, i| {
        match i {
            0 => kind = d.variant(&KINDS)?,
            1 => size = pair(d)?,
            2 => angle = d.f64()?,
            3 => offset = pair(d)?,
            _ => image = d.opt(|d| d.string_value())?,
        }
        Ok(())
    })?;
    let mut m = crate::json::Map::new();
    m.insert("kind", Value::Str(kind));
    m.insert("size", size);
    if angle != 0.0 {
        m.insert("angle", Value::f(angle));
    }
    if let Some(a) = offset.as_arr() {
        if a.iter().any(|x| x.as_f64() != Some(0.0)) {
            m.insert("offset", offset.clone());
        }
    }
    if let Some(g) = image {
        m.insert("image", Value::Str(g));
    }
    Ok(Value::Obj(m))
}

fn material(de: &mut De) -> R<Value> {
    let fields = [
        f("color", true),
        f("cut", false),
        f("surface", false),
        f("cut_pattern", false),
        f("surface_pattern", false),
        f("texture", false),
        f("transparency", false),
    ];
    let mut color = Value::Null;
    let mut cut = "none".to_string();
    let mut surface = "none".to_string();
    let mut cut_pattern = None;
    let mut surface_pattern = None;
    let mut tex = None;
    let mut transparency = 0u64;
    de.strukt("Material", &fields, |d, i| {
        match i {
            0 => {
                let c = d.array(3, |d| d.u_int(255, "u8"))?;
                color = Value::Arr(c.into_iter().map(Value::u).collect());
            }
            1 => cut = d.variant(&PATTERNS)?,
            2 => surface = d.variant(&PATTERNS)?,
            3 => cut_pattern = d.opt(|d| d.string_value())?,
            4 => surface_pattern = d.opt(|d| d.string_value())?,
            5 => tex = d.opt(texture)?,
            _ => transparency = d.u_int(255, "u8")?,
        }
        Ok(())
    })?;
    let mut m = crate::json::Map::new();
    m.insert("color", color);
    m.insert("cut", Value::Str(cut));
    m.insert("surface", Value::Str(surface));
    if let Some(p) = cut_pattern {
        m.insert("cut_pattern", Value::Str(p));
    }
    if let Some(p) = surface_pattern {
        m.insert("surface_pattern", Value::Str(p));
    }
    if let Some(t) = tex {
        m.insert("texture", t);
    }
    if transparency != 0 {
        m.insert("transparency", Value::u(transparency));
    }
    Ok(Value::Obj(m))
}

fn picture_file(de: &mut De) -> R<PictureFile> {
    let fields = [f("name", true), f("png", true)];
    let mut name = String::new();
    let mut png = String::new();
    de.strukt("PictureFile", &fields, |d, i| {
        if i == 0 {
            name = d.string_value()?;
        } else {
            png = d.string_value()?;
        }
        Ok(())
    })?;
    Ok(PictureFile { name, png })
}

fn material_entry(de: &mut De) -> R<MaterialEntry> {
    let fields = [f("material", true), f("images", false)];
    let mut mat = Value::Null;
    let mut images = Vec::new();
    de.strukt("MaterialEntry", &fields, |d, i| {
        if i == 0 {
            mat = material(d)?;
        } else {
            let mut v = d.map(|d, _| picture_file(d))?;
            v.sort_by(|a, b| a.0.cmp(&b.0));
            images = v;
        }
        Ok(())
    })?;
    Ok(MaterialEntry { material: mat, images })
}

fn family_entry(de: &mut De) -> R<FamilyEntry> {
    let fields = [f("family", true), f("materials", false)];
    let mut fam = Value::Null;
    let mut mats = Vec::new();
    de.strukt("FamilyEntry", &fields, |d, i| {
        if i == 0 {
            if d.ws() != Some(b'{') {
                return Err(d.invalid_type("struct Family"));
            }
            fam = d.scalar();
        } else {
            let mut v = d.map(|d, _| material_entry(d))?;
            v.sort_by(|a, b| a.0.cmp(&b.0));
            mats = v;
        }
        Ok(())
    })?;
    Ok(FamilyEntry { family: fam, materials: mats })
}

/// Reads a favorites file's text (already known to be JSON).
pub fn favorites(text: &[u8]) -> R<Favorites> {
    let mut de = De::new(text);
    let fields = [f("version", false), f("materials", false), f("families", false)];
    let mut out = Favorites::default();
    de.strukt("Favorites", &fields, |d, i| {
        match i {
            0 => {
                d.u_int(u32::MAX as u64, "u32")?;
            }
            1 => {
                let mut v = d.map(|d, _| material_entry(d))?;
                v.sort_by(|a, b| a.0.cmp(&b.0));
                out.materials = v;
            }
            _ => {
                let mut v = d.map(|d, _| family_entry(d))?;
                v.sort_by(|a, b| a.0.cmp(&b.0));
                out.families = v;
            }
        }
        Ok(())
    })?;
    if de.ws().is_some() {
        return Err(de.peek_err("trailing characters"));
    }
    let _ = De::skip;
    Ok(out)
}
