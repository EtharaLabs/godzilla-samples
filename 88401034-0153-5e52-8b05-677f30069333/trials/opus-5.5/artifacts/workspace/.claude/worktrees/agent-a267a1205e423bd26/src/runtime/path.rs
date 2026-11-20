// node:path (posix)

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn create_module(vm: &mut Vm) -> Value {
    let o = vm.new_object();
    o.set_str("sep", Value::str("/"), WEC);
    o.set_str("delimiter", Value::str(":"), WEC);
    let fns: &[(&str, u32, NativeFn)] = &[
        ("isAbsolute", 1, is_absolute),
        ("normalize", 1, normalize_fn),
        ("join", 0, join),
        ("resolve", 0, resolve_fn),
        ("dirname", 1, dirname),
        ("basename", 1, basename),
        ("extname", 1, extname),
        ("parse", 1, parse),
        ("format", 1, format),
        ("relative", 2, relative),
        ("matchesGlob", 2, matches_glob),
        ("toNamespacedPath", 1, |_vm, a| Ok(a.arg(0))),
        ("_makeLong", 1, |_vm, a| Ok(a.arg(0))),
    ];
    for (n, l, f) in fns {
        vm.def_method(&o, n, *l, *f);
    }
    o.set_str("posix", Value::Obj(o.clone()), WEC);
    o.set_str("win32", Value::Obj(o.clone()), WEC);
    Value::Obj(o)
}

fn str_arg(vm: &mut Vm, v: &Value, name: &str) -> JsResult<String> {
    match v {
        Value::Str(s) => Ok(s.to_rust_string()),
        other => {
            let d = crate::runtime::util::describe_received(vm, other);
            let e = vm.make_error("TypeError", &format!("The \"{}\" argument must be of type string. Received {}", name, d));
            if let Value::Obj(o) = &e {
                o.set_prop(PropKey::from_str("code"), Value::str("ERR_INVALID_ARG_TYPE"), WC);
            }
            Err(e)
        }
    }
}

pub fn normalize_str(path: &str, allow_above_root: bool) -> String {
    let mut res: Vec<&str> = Vec::new();
    for seg in path.split('/') {
        if seg.is_empty() || seg == "." {
            continue;
        }
        if seg == ".." {
            if !res.is_empty() && *res.last().unwrap() != ".." {
                res.pop();
            } else if allow_above_root {
                res.push("..");
            }
            continue;
        }
        res.push(seg);
    }
    res.join("/")
}

pub fn normalize(p: &str) -> String {
    if p.is_empty() {
        return ".".to_string();
    }
    let abs = p.starts_with('/');
    let trailing = p.ends_with('/');
    let mut n = normalize_str(p, !abs);
    if n.is_empty() && !abs {
        n = ".".to_string();
    }
    if !n.is_empty() && trailing {
        n.push('/');
    }
    if abs {
        format!("/{}", n)
    } else {
        n
    }
}

fn is_absolute(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    Ok(Value::Bool(p.starts_with('/')))
}

fn normalize_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    Ok(Value::str(&normalize(&p)))
}

pub fn join_strs(parts: &[String]) -> String {
    let joined: Vec<&str> = parts.iter().filter(|s| !s.is_empty()).map(|s| s.as_str()).collect();
    if joined.is_empty() {
        return ".".to_string();
    }
    normalize(&joined.join("/"))
}

fn join(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut parts = Vec::new();
    for v in a.args {
        parts.push(str_arg(vm, v, "path")?);
    }
    Ok(Value::str(&join_strs(&parts)))
}

pub fn resolve_strs(parts: &[String]) -> String {
    let mut resolved = String::new();
    let mut abs = false;
    for p in parts.iter().rev() {
        if p.is_empty() {
            continue;
        }
        resolved = if resolved.is_empty() { p.clone() } else { format!("{}/{}", p, resolved) };
        if p.starts_with('/') {
            abs = true;
            break;
        }
    }
    if !abs {
        let cwd = std::env::current_dir().map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|_| "/".into());
        resolved = if resolved.is_empty() { cwd } else { format!("{}/{}", cwd, resolved) };
    }
    let n = normalize_str(&resolved, false);
    format!("/{}", n)
}

fn resolve_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut parts = Vec::new();
    for v in a.args {
        parts.push(str_arg(vm, v, "paths[0]")?);
    }
    Ok(Value::str(&resolve_strs(&parts)))
}

pub fn dirname_str(p: &str) -> String {
    if p.is_empty() {
        return ".".into();
    }
    let has_root = p.starts_with('/');
    let b = p.as_bytes();
    let mut end: isize = -1;
    let mut matched_slash = true;
    let mut i = b.len() as isize - 1;
    while i >= 1 {
        if b[i as usize] == b'/' {
            if !matched_slash {
                end = i;
                break;
            }
        } else {
            matched_slash = false;
        }
        i -= 1;
    }
    if end == -1 {
        return if has_root { "/".into() } else { ".".into() };
    }
    if has_root && end == 1 {
        return "//".into();
    }
    p[..end as usize].to_string()
}

fn dirname(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    Ok(Value::str(&dirname_str(&p)))
}

pub fn basename_str(p: &str, ext: Option<&str>) -> String {
    let trimmed = p.trim_end_matches('/');
    if trimmed.is_empty() {
        return if p.starts_with('/') { String::new() } else { String::new() };
    }
    let base = match trimmed.rfind('/') {
        Some(i) => &trimmed[i + 1..],
        None => trimmed,
    };
    if let Some(e) = ext {
        if !e.is_empty() && base.ends_with(e) && base != e {
            return base[..base.len() - e.len()].to_string();
        }
    }
    base.to_string()
}

fn basename(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    let ext = if a.arg(1).is_undefined() { None } else { Some(str_arg(vm, &a.arg(1), "ext")?) };
    Ok(Value::str(&basename_str(&p, ext.as_deref())))
}

pub fn extname_str(p: &str) -> String {
    let base = basename_str(p, None);
    match base.rfind('.') {
        Some(0) | None => String::new(),
        Some(i) => base[i..].to_string(),
    }
}

fn extname(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    Ok(Value::str(&extname_str(&p)))
}

fn parse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    let root = if p.starts_with('/') { "/" } else { "" };
    let base = basename_str(&p, None);
    let ext = extname_str(&p);
    let name = if ext.is_empty() { base.clone() } else { base[..base.len() - ext.len()].to_string() };
    let mut dir = dirname_str(&p);
    if !p.contains('/') {
        dir = String::new();
    }
    let o = vm.obj_from(vec![
        ("root", Value::str(root)),
        ("dir", Value::str(&dir)),
        ("base", Value::str(&base)),
        ("ext", Value::str(&ext)),
        ("name", Value::str(&name)),
    ]);
    Ok(Value::Obj(o))
}

fn format(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = match a.arg(0) {
        Value::Obj(o) => o,
        other => {
            let d = crate::runtime::util::describe_received(vm, &other);
            return vm.throw_type(format!("The \"pathObject\" argument must be of type object. Received {}", d));
        }
    };
    let get = |vm: &mut Vm, k: &str| -> JsResult<String> {
        let v = vm.get_str(&o, k)?;
        Ok(if v.is_nullish() { String::new() } else { vm.to_string(&v)?.to_rust_string() })
    };
    let dir = get(vm, "dir")?;
    let root = get(vm, "root")?;
    let base = get(vm, "base")?;
    let name = get(vm, "name")?;
    let ext = get(vm, "ext")?;
    let b = if base.is_empty() {
        let e = if !ext.is_empty() && !ext.starts_with('.') { format!(".{}", ext) } else { ext };
        format!("{}{}", name, e)
    } else {
        base
    };
    let d = if dir.is_empty() { root.clone() } else { dir.clone() };
    if d.is_empty() {
        return Ok(Value::str(&b));
    }
    if d == root {
        return Ok(Value::str(&format!("{}{}", d, b)));
    }
    Ok(Value::str(&format!("{}/{}", d, b)))
}

fn relative(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let from = str_arg(vm, &a.arg(0), "from")?;
    let to = str_arg(vm, &a.arg(1), "to")?;
    let f = resolve_strs(&[from]);
    let t = resolve_strs(&[to]);
    if f == t {
        return Ok(Value::str(""));
    }
    let fp: Vec<&str> = f.split('/').filter(|s| !s.is_empty()).collect();
    let tp: Vec<&str> = t.split('/').filter(|s| !s.is_empty()).collect();
    let mut i = 0;
    while i < fp.len() && i < tp.len() && fp[i] == tp[i] {
        i += 1;
    }
    let mut parts: Vec<String> = Vec::new();
    for _ in i..fp.len() {
        parts.push("..".into());
    }
    for s in &tp[i..] {
        parts.push(s.to_string());
    }
    Ok(Value::str(&parts.join("/")))
}

pub fn glob_match(pat: &str, s: &str) -> bool {
    fn m(p: &[u8], s: &[u8]) -> bool {
        if p.is_empty() {
            return s.is_empty();
        }
        if p.len() >= 2 && &p[..2] == b"**" {
            let rest = if p.len() > 2 && p[2] == b'/' { &p[3..] } else { &p[2..] };
            for i in 0..=s.len() {
                if m(rest, &s[i..]) {
                    return true;
                }
            }
            return false;
        }
        match p[0] {
            b'*' => {
                for i in 0..=s.len() {
                    if i > 0 && s[i - 1] == b'/' {
                        break;
                    }
                    if m(&p[1..], &s[i..]) {
                        return true;
                    }
                }
                false
            }
            b'?' => !s.is_empty() && s[0] != b'/' && m(&p[1..], &s[1..]),
            c => !s.is_empty() && s[0] == c && m(&p[1..], &s[1..]),
        }
    }
    m(pat.as_bytes(), s.as_bytes())
}

fn matches_glob(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = str_arg(vm, &a.arg(0), "path")?;
    let g = str_arg(vm, &a.arg(1), "pattern")?;
    Ok(Value::Bool(glob_match(&g, &p)))
}
