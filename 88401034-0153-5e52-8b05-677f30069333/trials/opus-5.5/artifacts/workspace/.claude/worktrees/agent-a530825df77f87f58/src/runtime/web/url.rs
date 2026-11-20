// URL, URLSearchParams, URLPattern and the node `url` / `querystring` modules.
//
// The URL parser is the reference runtime's simplified one (not full WHATWG): no percent-
// encoding, no IDNA (non-ASCII hosts are rejected), hosts are ASCII-lowercased, default ports
// dropped, `.`/`..` and empty path segments collapsed for hierarchical URLs.

use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

// =============================================================================================
// string conversions (lone surrogates survive via the engine's escape range)
// =============================================================================================

pub fn to_rs(s: &JsStr) -> String {
    let b = super::encoding::engine_utf8(s.units());
    String::from_utf8(b).unwrap_or_default()
}

pub fn from_rs(s: &str) -> JsStr {
    JsStr::from_units(super::encoding::engine_utf16(s.as_bytes()))
}

pub fn rs_val(s: &str) -> Value {
    Value::Str(from_rs(s))
}

// =============================================================================================
// the parser
// =============================================================================================

#[derive(Clone, Debug, Default)]
pub struct UrlRec {
    pub scheme: String,
    pub username: String,
    pub password: String,
    pub host: String,
    pub port: String,
    pub path: String,
    pub query: String,
    pub fragment: String,
}

fn is_special(scheme: &str) -> bool {
    matches!(scheme, "http" | "https" | "ftp" | "ws" | "wss" | "file")
}

fn default_port(scheme: &str) -> Option<u16> {
    match scheme {
        "http" | "ws" => Some(80),
        "https" | "wss" => Some(443),
        "ftp" => Some(21),
        _ => None,
    }
}

impl UrlRec {
    pub fn href(&self) -> String {
        let mut s = format!("{}:", self.scheme);
        if !self.host.is_empty() || self.scheme == "file" {
            s.push_str("//");
            if !self.username.is_empty() || !self.password.is_empty() {
                s.push_str(&self.username);
                if !self.password.is_empty() {
                    s.push(':');
                    s.push_str(&self.password);
                }
                s.push('@');
            }
            s.push_str(&self.host);
            if !self.port.is_empty() {
                s.push(':');
                s.push_str(&self.port);
            }
        }
        s.push_str(&self.path);
        s.push_str(&self.query);
        s.push_str(&self.fragment);
        s
    }
    pub fn origin(&self) -> String {
        if self.port.is_empty() {
            format!("{}://{}", self.scheme, self.host)
        } else {
            format!("{}://{}:{}", self.scheme, self.host, self.port)
        }
    }
}

/// `scheme:` prefix (ASCII alpha followed by alnum / + - .), returning (scheme, rest).
fn split_scheme(s: &str) -> Option<(&str, &str)> {
    let b = s.as_bytes();
    if b.is_empty() || !b[0].is_ascii_alphabetic() {
        return None;
    }
    let mut i = 1;
    while i < b.len() && (b[i].is_ascii_alphanumeric() || matches!(b[i], b'+' | b'-' | b'.')) {
        i += 1;
    }
    if i < b.len() && b[i] == b':' {
        Some((&s[..i], &s[i + 1..]))
    } else {
        None
    }
}

/// Collapse `.`/`..` and empty segments; the result always starts with `/`.
fn normalize_path(path: &str) -> String {
    if path.is_empty() {
        return String::new();
    }
    let segs: Vec<&str> = path.split('/').collect();
    let n = segs.len();
    let mut out: Vec<&str> = Vec::new();
    let mut trailing = false;
    for (i, seg) in segs.iter().enumerate() {
        let last = i + 1 == n;
        match *seg {
            "" | "." => {
                if last && i > 0 {
                    trailing = true;
                }
            }
            ".." => {
                out.pop();
                if last {
                    trailing = true;
                }
            }
            s => {
                out.push(s);
                trailing = false;
            }
        }
    }
    let mut r = String::from("/");
    r.push_str(&out.join("/"));
    if trailing && !out.is_empty() {
        r.push('/');
    }
    r
}

fn split_pqf(rest: &str) -> (&str, &str, &str) {
    let (before, frag) = match rest.find('#') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, ""),
    };
    let (path, query) = match before.find('?') {
        Some(i) => (&before[..i], &before[i..]),
        None => (before, ""),
    };
    (path, query, frag)
}

fn trim_c0(s: &str) -> &str {
    s.trim_matches(|c: char| (c as u32) <= 0x20)
}

/// Port per the reference: Rust-style u16 parse, default port dropped.
fn parse_port(scheme: &str, port: &str) -> Result<String, String> {
    if port.is_empty() {
        return Ok(String::new());
    }
    match port.parse::<u16>() {
        Ok(p) => {
            if default_port(scheme) == Some(p) {
                Ok(String::new())
            } else {
                Ok(p.to_string())
            }
        }
        Err(_) => Err(format!("URL: invalid port '{}'", port)),
    }
}

fn parse_absolute(scheme: &str, rest: &str, shown: &str) -> Result<UrlRec, String> {
    let special = is_special(scheme);
    let mut rec = UrlRec { scheme: scheme.to_string(), ..Default::default() };
    if let Some(after) = rest.strip_prefix("//") {
        let auth_end = after.find(|c| c == '/' || c == '?' || c == '#').unwrap_or(after.len());
        let authority = &after[..auth_end];
        let remainder = &after[auth_end..];
        let (userinfo, hostport) = match authority.rfind('@') {
            Some(i) => (Some(&authority[..i]), &authority[i + 1..]),
            None => (None, authority),
        };
        if let Some(u) = userinfo {
            match u.find(':') {
                Some(j) => {
                    rec.username = u[..j].to_string();
                    rec.password = u[j + 1..].to_string();
                }
                None => rec.username = u.to_string(),
            }
        }
        let (host, port) = if hostport.starts_with('[') {
            match hostport.find(']') {
                Some(j) => {
                    let after_b = &hostport[j + 1..];
                    let port = after_b.strip_prefix(':').unwrap_or("");
                    let port = if after_b.starts_with(':') { port } else { "" };
                    (&hostport[..=j], port)
                }
                None => return Err(format!("URL: invalid host '{}'", hostport)),
            }
        } else {
            match hostport.find(':') {
                Some(j) => (&hostport[..j], &hostport[j + 1..]),
                None => (hostport, ""),
            }
        };
        if !host.is_ascii() {
            return Err(format!("URL: non-ASCII host '{}' (IDNA is not implemented yet)", host));
        }
        rec.port = parse_port(scheme, port)?;
        if host.is_empty() && special && scheme != "file" {
            return Err(format!("URL: invalid URL '{}': missing host", shown));
        }
        rec.host = host.to_ascii_lowercase();
        let (path, query, frag) = split_pqf(remainder);
        let mut p = normalize_path(path);
        if p.is_empty() && special {
            p = "/".to_string();
        }
        rec.path = p;
        rec.query = query.to_string();
        rec.fragment = frag.to_string();
        Ok(rec)
    } else {
        if special {
            return Err(format!("URL: invalid URL '{}': special scheme without //", shown));
        }
        let (path, query, frag) = split_pqf(rest);
        rec.path = path.to_string();
        rec.query = query.to_string();
        rec.fragment = frag.to_string();
        Ok(rec)
    }
}

/// `__url.parse(input, base)`
pub fn url_parse(input: &str, base: Option<&str>) -> Result<UrlRec, String> {
    let s = trim_c0(input);
    if let Some((scheme, rest)) = split_scheme(s) {
        return parse_absolute(&scheme.to_ascii_lowercase(), rest, s);
    }
    let base = match base {
        None => return Err(format!("URL: invalid URL '{}' (relative, and no base given)", s)),
        Some(b) => b,
    };
    let b = match url_parse(base, None) {
        Ok(b) => b,
        Err(_) => return Err(format!("URL: invalid base URL '{}'", base)),
    };
    if s.starts_with("//") {
        let href = format!("{}:{}", b.scheme, s);
        return url_parse(&href, None);
    }
    let (rpath, rquery, rfrag) = split_pqf(s);
    let mut r = b.clone();
    if s.starts_with('/') {
        r.path = normalize_path(rpath);
        r.query = rquery.to_string();
        r.fragment = rfrag.to_string();
    } else if s.starts_with('?') {
        r.query = rquery.to_string();
        r.fragment = rfrag.to_string();
    } else if s.starts_with('#') {
        r.fragment = rfrag.to_string();
    } else if s.is_empty() {
        r.fragment = String::new();
    } else {
        let dir = match b.path.rfind('/') {
            Some(i) => &b.path[..=i],
            None => "",
        };
        r.path = normalize_path(&format!("{}{}", dir, rpath));
        r.query = rquery.to_string();
        r.fragment = rfrag.to_string();
    }
    let href = r.href();
    url_parse(&href, None)
}

fn rec_to_obj(vm: &mut Vm, r: &UrlRec) -> Value {
    let o = vm.obj_from(vec![
        ("scheme", rs_val(&r.scheme)),
        ("username", rs_val(&r.username)),
        ("password", rs_val(&r.password)),
        ("host", rs_val(&r.host)),
        ("port", rs_val(&r.port)),
        ("path", rs_val(&r.path)),
        ("query", rs_val(&r.query)),
        ("fragment", rs_val(&r.fragment)),
        ("href", rs_val(&r.href())),
        ("origin", rs_val(&r.origin())),
    ]);
    Value::Obj(o)
}

/// `__url.parse(input, base)` producing the record object, or throwing the TypeError.
fn parse_to_obj(vm: &mut Vm, input: &JsStr, base: Option<&JsStr>) -> JsResult<Value> {
    let i = to_rs(input);
    let b = base.map(to_rs);
    match url_parse(&i, b.as_deref()) {
        Ok(r) => Ok(rec_to_obj(vm, &r)),
        Err(m) => {
            let e = vm.make_error("TypeError", "");
            if let Value::Obj(o) = &e {
                o.set_prop(vm.intr.key_message.clone(), Value::Str(from_rs(&m)), WC);
            }
            Err(e)
        }
    }
}

// =============================================================================================
// URL
// =============================================================================================

pub fn setup(vm: &mut Vm) {
    setup_search_params(vm);
    let (c, p) = make_class(vm, "URL", "URL.prototype", 2, url_ctor, None);
    method(vm, &p, "_recompose", 1, url_recompose_method);
    accessor(vm, &p, "href", url_href_get, url_href_set);
    getter(vm, &p, "origin", url_origin_get);
    getter(vm, &p, "protocol", url_protocol_get);
    getter(vm, &p, "username", url_username_get);
    getter(vm, &p, "password", url_password_get);
    getter(vm, &p, "host", url_host_get);
    accessor(vm, &p, "hostname", url_hostname_get, url_hostname_set);
    accessor(vm, &p, "port", url_port_get, url_port_set);
    accessor(vm, &p, "pathname", url_pathname_get, url_pathname_set);
    accessor(vm, &p, "search", url_search_get, url_search_set);
    accessor(vm, &p, "hash", url_hash_get, url_hash_set);
    getter(vm, &p, "searchParams", url_search_params_get);
    method(vm, &p, "toString", 0, url_href_get_m);
    method(vm, &p, "toJSON", 0, url_href_get_m);
    method(vm, &c, "canParse", 2, url_can_parse);
    method(vm, &c, "parse", 2, url_static_parse);

    // URLSearchParams was created first (URL's searchParams uses it) but the reference
    // defines the URLSearchParams global before URL.
    let sp = reg(vm, "URLSearchParams");
    set_global(vm, "URLSearchParams", Value::Obj(sp));
    set_global(vm, "URL", Value::Obj(c));
    setup_pattern(vm);
}

fn url_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "URL.prototype")?;
    let ov = Value::Obj(o);
    url_init(vm, &ov, &a.arg(0), &a.arg(1))?;
    Ok(ov)
}

fn url_init(vm: &mut Vm, ov: &Value, input: &Value, base: &Value) -> JsResult<()> {
    let i = js_string(vm, input)?;
    let b = if base.is_undefined() { None } else { Some(js_string(vm, base)?) };
    let c = parse_to_obj(vm, &i, b.as_ref())?;
    set(vm, ov, "_c", c)?;
    set(vm, ov, "_searchParams", Value::Null)?;
    Ok(())
}

/// `new URL(input, base)` from native code.
pub fn construct_url(vm: &mut Vm, input: &Value, base: &Value) -> JsResult<Value> {
    let p = reg(vm, "URL.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    with_frame(vm, "URL", |vm| url_init(vm, &ov, input, base))?;
    Ok(ov)
}

fn c_field(vm: &mut Vm, this: &Value, f: &str) -> JsResult<Value> {
    let c = get(vm, this, "_c")?;
    get(vm, &c, f)
}

fn url_href_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "href")
}

/// toString()/toJSON(): `return this.href`
fn url_href_get_m(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    get(vm, &a.this, "href")
}

fn reset_search_params(vm: &mut Vm, this: &Value) -> JsResult<()> {
    let sp = get(vm, this, "_searchParams")?;
    if sp.truthy() {
        let q = c_field(vm, this, "query")?;
        let sp = get(vm, this, "_searchParams")?;
        invoke(vm, &sp, "_reset", &[q])?;
    }
    Ok(())
}

fn url_href_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let c = parse_to_obj(vm, &s, None)?;
    set(vm, &a.this, "_c", c)?;
    reset_search_params(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn url_origin_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "origin")
}

fn url_protocol_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = c_field(vm, &a.this, "scheme")?;
    let s = vm.to_string(&s)?;
    Ok(Value::Str(JsStr::concat(&s, &JsStr::from_str(":"))))
}

fn url_username_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "username")
}

fn url_password_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "password")
}

fn url_host_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let port = c_field(vm, &a.this, "port")?;
    if Value::strict_eq(&port, &Value::str("")) {
        return c_field(vm, &a.this, "host");
    }
    let h = c_field(vm, &a.this, "host")?;
    let h = vm.to_string(&h)?;
    let p = c_field(vm, &a.this, "port")?;
    let p = vm.to_string(&p)?;
    Ok(Value::str(&format!("{}:{}", h, p)))
}

fn url_hostname_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "host")
}

fn url_port_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "port")
}

fn url_pathname_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "path")
}

fn url_search_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "query")
}

fn url_hash_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    c_field(vm, &a.this, "fragment")
}

const REC_FIELDS: [&str; 8] = ["scheme", "username", "password", "host", "port", "path", "query", "fragment"];

/// `this._recompose(patch)` from the setters.
fn recompose(vm: &mut Vm, this: &Value, patch: &[(&str, Value)], reset: bool) -> JsResult<()> {
    with_frame(vm, "_recompose", |vm| recompose_inner(vm, this, patch, reset))
}

/// `_recompose(patch)`: rebuild the href from `{ ...this._c, ...patch }` and reparse it.
fn recompose_inner(vm: &mut Vm, this: &Value, patch: &[(&str, Value)], reset: bool) -> JsResult<()> {
    let c = get(vm, this, "_c")?;
    let mut vals: Vec<Value> = Vec::with_capacity(8);
    for f in REC_FIELDS {
        if let Some((_, v)) = patch.iter().find(|(k, _)| *k == f) {
            vals.push(v.clone());
        } else if c.is_nullish() {
            vals.push(Value::Undefined);
        } else {
            let has = match &c {
                Value::Obj(o) => {
                    let k = key(f);
                    match vm.get_own_property(o, &k)? {
                        Some(d) => d.enumerable == Some(true),
                        None => false,
                    }
                }
                _ => false,
            };
            vals.push(if has { get(vm, &c, f)? } else { Value::Undefined });
        }
    }
    let empty = Value::str("");
    let mut href = String::new();
    let ts = |vm: &mut Vm, v: &Value| -> JsResult<String> { Ok(to_rs(&vm.to_string(v)?)) };
    href.push_str(&ts(vm, &vals[0])?);
    href.push(':');
    if !Value::strict_eq(&vals[3], &empty) || Value::strict_eq(&vals[0], &Value::str("file")) {
        href.push_str("//");
        if !Value::strict_eq(&vals[1], &empty) || !Value::strict_eq(&vals[2], &empty) {
            href.push_str(&ts(vm, &vals[1])?);
            if !Value::strict_eq(&vals[2], &empty) {
                href.push(':');
                href.push_str(&ts(vm, &vals[2])?);
            }
            href.push('@');
        }
        href.push_str(&ts(vm, &vals[3])?);
        if !Value::strict_eq(&vals[4], &empty) {
            href.push(':');
            href.push_str(&ts(vm, &vals[4])?);
        }
    }
    let tail = vm.op_add(&vals[5], &vals[6])?;
    let tail = vm.op_add(&tail, &vals[7])?;
    href.push_str(&ts(vm, &tail)?);
    let nc = parse_to_obj(vm, &from_rs(&href), None)?;
    set(vm, this, "_c", nc)?;
    if reset {
        reset_search_params(vm, this)?;
    }
    Ok(())
}

fn url_recompose_method(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let patch = a.arg(0);
    let mut pairs: Vec<(&str, Value)> = Vec::new();
    if let Value::Obj(po) = &patch {
        let keys = vm.enumerable_own_keys(po)?;
        for f in REC_FIELDS {
            if keys.iter().any(|k| k.eq_str(f)) {
                let v = get(vm, &patch, f)?;
                pairs.push((f, v));
            }
        }
    }
    recompose_inner(vm, &a.this, &pairs, true)?;
    Ok(Value::Undefined)
}

fn url_hostname_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = Value::Str(js_string(vm, &a.arg(0))?);
    recompose(vm, &a.this, &[("host", v)], true)?;
    Ok(Value::Undefined)
}

fn url_port_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = Value::Str(js_string(vm, &a.arg(0))?);
    recompose(vm, &a.this, &[("port", v)], true)?;
    Ok(Value::Undefined)
}

fn url_pathname_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = Value::Str(js_string(vm, &a.arg(0))?);
    recompose(vm, &a.this, &[("path", v)], true)?;
    Ok(Value::Undefined)
}

fn url_search_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = js_string(vm, &a.arg(0))?;
    let q = if v.is_empty() || v.units()[0] == b'?' as u16 { v } else { JsStr::concat(&JsStr::from_str("?"), &v) };
    recompose(vm, &a.this, &[("query", Value::Str(q))], true)?;
    Ok(Value::Undefined)
}

fn url_hash_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let v = js_string(vm, &a.arg(0))?;
    let f = if v.is_empty() || v.units()[0] == b'#' as u16 { v } else { JsStr::concat(&JsStr::from_str("#"), &v) };
    recompose(vm, &a.this, &[("fragment", Value::Str(f))], true)?;
    Ok(Value::Undefined)
}

fn url_search_params_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let this = a.this.clone();
    let cur = get(vm, &this, "_searchParams")?;
    if !cur.truthy() {
        let q = c_field(vm, &this, "query")?;
        let sp = construct_search_params(vm, &q)?;
        let f = vm.native_closure("", 0, url_sp_onchange, vec![this.clone(), sp.clone()]);
        set(vm, &sp, "_onchange", Value::Obj(f))?;
        set(vm, &this, "_searchParams", sp)?;
    }
    get(vm, &this, "_searchParams")
}

/// The `_onchange` hook a URL installs on its searchParams.
fn url_sp_onchange(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let url = a.slot(0);
    let sp = a.slot(1);
    with_frame(vm, "<anonymous>", |vm| url_sp_onchange_body(vm, url, sp))
}

fn url_sp_onchange_body(vm: &mut Vm, url: Value, sp: Value) -> JsResult<Value> {
    let q = invoke(vm, &sp, "toString", &[])?;
    let saved = get(vm, &url, "_searchParams")?;
    set(vm, &url, "_searchParams", Value::Null)?;
    let query = if Value::strict_eq(&q, &Value::str("")) {
        Value::str("")
    } else {
        let qs = vm.to_string(&q)?;
        Value::Str(JsStr::concat(&JsStr::from_str("?"), &qs))
    };
    let r = recompose(vm, &url, &[("query", query)], true);
    r?;
    set(vm, &url, "_searchParams", saved)?;
    Ok(Value::Undefined)
}

fn url_can_parse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Bool(construct_url(vm, &a.arg(0), &a.arg(1)).is_ok()))
}

fn url_static_parse(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(construct_url(vm, &a.arg(0), &a.arg(1)).unwrap_or(Value::Null))
}

// =============================================================================================
// form encoding (application/x-www-form-urlencoded) and URI component coding
// =============================================================================================

fn hexval(c: u16) -> Option<u8> {
    match c {
        0x30..=0x39 => Some((c - 0x30) as u8),
        0x41..=0x46 => Some((c - 0x41 + 10) as u8),
        0x61..=0x66 => Some((c - 0x61 + 10) as u8),
        _ => None,
    }
}

/// `decodeURIComponent` (None where it would throw URIError).
pub fn decode_uri_component(u: &[u16]) -> Option<Vec<u16>> {
    let mut out = Vec::with_capacity(u.len());
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c != b'%' as u16 {
            out.push(c);
            i += 1;
            continue;
        }
        if i + 2 >= u.len() {
            return None;
        }
        let b0 = (hexval(u[i + 1])? << 4) | hexval(u[i + 2])?;
        i += 3;
        if b0 < 0x80 {
            out.push(b0 as u16);
            continue;
        }
        let n = if b0 & 0xE0 == 0xC0 {
            2
        } else if b0 & 0xF0 == 0xE0 {
            3
        } else if b0 & 0xF8 == 0xF0 {
            4
        } else {
            return None;
        };
        let mut bytes = vec![b0];
        for _ in 1..n {
            if i + 2 >= u.len() || u[i] != b'%' as u16 {
                return None;
            }
            let b = (hexval(u[i + 1])? << 4) | hexval(u[i + 2])?;
            if b & 0xC0 != 0x80 {
                return None;
            }
            bytes.push(b);
            i += 3;
        }
        let s = std::str::from_utf8(&bytes).ok()?;
        for ch in s.chars() {
            let mut buf = [0u16; 2];
            out.extend_from_slice(ch.encode_utf16(&mut buf));
        }
    }
    Some(out)
}

fn uri_unreserved(c: u16) -> bool {
    if c >= 0x80 {
        return false;
    }
    let b = c as u8;
    b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'!' | b'~' | b'*' | b'\'' | b'(' | b')')
}

/// `encodeURIComponent` (Err for lone surrogates -> URIError "URI malformed").
pub fn encode_uri_component(u: &[u16]) -> Result<String, ()> {
    let mut out = String::with_capacity(u.len());
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if uri_unreserved(c) {
            out.push(c as u8 as char);
            i += 1;
            continue;
        }
        let cp: u32 = if (0xD800..0xDC00).contains(&c) {
            if i + 1 < u.len() && (0xDC00..0xE000).contains(&u[i + 1]) {
                let cp = 0x10000 + (((c as u32) - 0xD800) << 10) + ((u[i + 1] as u32) - 0xDC00);
                i += 1;
                cp
            } else {
                return Err(());
            }
        } else if (0xDC00..0xE000).contains(&c) {
            return Err(());
        } else {
            c as u32
        };
        i += 1;
        let ch = char::from_u32(cp).unwrap_or('\u{fffd}');
        let mut buf = [0u8; 4];
        for b in ch.encode_utf8(&mut buf).bytes() {
            out.push_str(&format!("%{:02X}", b));
        }
    }
    Ok(out)
}

fn uri_malformed<T>(vm: &mut Vm) -> JsResult<T> {
    vm.throw_error("URIError", "URI malformed")
}

/// formDecode: strip one leading "?", split on "&", '+' -> ' ', percent-decode (raw on failure).
fn form_decode(s: &[u16]) -> Vec<(Vec<u16>, Vec<u16>)> {
    let s = if s.first() == Some(&(b'?' as u16)) { &s[1..] } else { s };
    let mut out = Vec::new();
    for part in s.split(|&c| c == b'&' as u16) {
        if part.is_empty() {
            continue;
        }
        let (k, v) = match part.iter().position(|&c| c == b'=' as u16) {
            Some(i) => (&part[..i], &part[i + 1..]),
            None => (part, &part[part.len()..]),
        };
        let dec = |x: &[u16]| -> Vec<u16> {
            let sp: Vec<u16> = x.iter().map(|&c| if c == b'+' as u16 { b' ' as u16 } else { c }).collect();
            decode_uri_component(&sp).unwrap_or(sp)
        };
        out.push((dec(k), dec(v)));
    }
    out
}

fn form_encode_one(vm: &mut Vm, s: &JsStr) -> JsResult<String> {
    match encode_uri_component(s.units()) {
        Ok(e) => Ok(e.replace("%20", "+")),
        Err(_) => uri_malformed(vm),
    }
}

// =============================================================================================
// URLSearchParams
// =============================================================================================

fn setup_search_params(vm: &mut Vm) {
    let (_c, p) = make_class(vm, "URLSearchParams", "URLSearchParams.prototype", 0, sp_ctor, None);
    method(vm, &p, "_changed", 0, sp_changed);
    method(vm, &p, "_reset", 1, sp_reset);
    method(vm, &p, "append", 2, sp_append);
    method(vm, &p, "delete", 1, sp_delete);
    method(vm, &p, "get", 1, sp_get);
    method(vm, &p, "getAll", 1, sp_get_all);
    method(vm, &p, "has", 1, sp_has);
    method(vm, &p, "set", 2, sp_set);
    method(vm, &p, "sort", 0, sp_sort);
    method(vm, &p, "forEach", 2, sp_for_each);
    gen_method(vm, &p, "entries", GenKind::SpEntries);
    gen_method(vm, &p, "keys", GenKind::SpKeys);
    gen_method(vm, &p, "values", GenKind::SpValues);
    vm.def_getter(&p, "size", sp_size);
    let it = vm.intr.sym_iterator.clone();
    vm.def_sym_method(&p, &it, "[Symbol.iterator]", 0, sp_iterator);
    method(vm, &p, "toString", 0, sp_to_string);
}

fn pairs_to_list(vm: &mut Vm, pairs: Vec<(Vec<u16>, Vec<u16>)>) -> Value {
    let items: Vec<Value> = pairs
        .into_iter()
        .map(|(k, v)| array(vm, vec![Value::Str(JsStr::from_units(k)), Value::Str(JsStr::from_units(v))]))
        .collect();
    array(vm, items)
}

fn sp_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "URLSearchParams.prototype")?;
    let ov = Value::Obj(o);
    sp_init(vm, &ov, &a.arg(0))?;
    Ok(ov)
}

/// `new URLSearchParams(init)` from native code.
pub fn construct_search_params(vm: &mut Vm, init: &Value) -> JsResult<Value> {
    let p = reg(vm, "URLSearchParams.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    with_frame(vm, "URLSearchParams", |vm| sp_init(vm, &ov, init))?;
    Ok(ov)
}

fn sp_init(vm: &mut Vm, this: &Value, init: &Value) -> JsResult<()> {
    let init = if init.is_undefined() { Value::str("") } else { init.clone() };
    let l = array(vm, Vec::new());
    set(vm, this, "_list", l)?;
    set(vm, this, "_onchange", Value::Null)?;
    let spc = Value::Obj(reg(vm, "URLSearchParams"));
    if let Value::Str(s) = &init {
        let pairs = form_decode(s.units());
        let l = pairs_to_list(vm, pairs);
        set(vm, this, "_list", l)?;
    } else if init.is_object() && vm.instance_of(&init, &spc)? {
        let src = get(vm, &init, "_list")?;
        let mut copies = Vec::new();
        for p in list_for(vm, &src, "map")? {
            let items = vm.iterate_to_vec(&p)?;
            copies.push(array(vm, items));
        }
        let l = array(vm, copies);
        set(vm, this, "_list", l)?;
    } else if crate::builtins::array::is_array(vm, &init)? {
        for pair in vm.iterate_to_vec(&init)? {
            let bad = if !pair.truthy() {
                true
            } else {
                let len = get(vm, &pair, "length")?;
                !Value::strict_eq(&len, &Value::Num(2.0))
            };
            if bad {
                return vm.throw_type("URLSearchParams: each init pair needs exactly two items");
            }
            let list = get(vm, this, "_list")?;
            let k = get_key(vm, &pair, &PropKey::from_index(0))?;
            let k = js_string(vm, &k)?;
            let v = get_key(vm, &pair, &PropKey::from_index(1))?;
            let v = js_string(vm, &v)?;
            let p = array(vm, vec![Value::Str(k), Value::Str(v)]);
            arr_push(vm, &list, p)?;
        }
    } else if init.truthy() && is_object_type(&init) {
        let o = init.as_obj().unwrap().clone();
        for k in vm.enumerable_own_keys(&o)? {
            let list = get(vm, this, "_list")?;
            let v = vm.get(&o, &PropKey::Str(k.clone()), &init)?;
            let v = js_string(vm, &v)?;
            let p = array(vm, vec![Value::Str(k), Value::Str(v)]);
            arr_push(vm, &list, p)?;
        }
    }
    Ok(())
}

fn sp_changed(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = get(vm, &a.this, "_onchange")?;
    if f.truthy() {
        invoke(vm, &a.this, "_onchange", &[])?;
    }
    Ok(Value::Undefined)
}

fn changed(vm: &mut Vm, this: &Value) -> JsResult<()> {
    invoke(vm, this, "_changed", &[])?;
    Ok(())
}

fn sp_reset(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let pairs = form_decode(s.units());
    let l = pairs_to_list(vm, pairs);
    set(vm, &a.this, "_list", l)?;
    Ok(Value::Undefined)
}

fn pair_key(vm: &mut Vm, p: &Value) -> JsResult<Value> {
    get_key(vm, p, &PropKey::from_index(0))
}

fn pair_val(vm: &mut Vm, p: &Value) -> JsResult<Value> {
    get_key(vm, p, &PropKey::from_index(1))
}

fn sp_append(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = get(vm, &a.this, "_list")?;
    let k = js_string(vm, &a.arg(0))?;
    let v = js_string(vm, &a.arg(1))?;
    let p = array(vm, vec![Value::Str(k), Value::Str(v)]);
    arr_push(vm, &list, p)?;
    changed(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn sp_delete(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = get(vm, &a.this, "_list")?;
    let mut keep = Vec::new();
    for p in list_for(vm, &list, "filter")? {
        let k = pair_key(vm, &p)?;
        if !Value::strict_eq(&k, &name) {
            keep.push(p);
        }
    }
    let nl = array(vm, keep);
    set(vm, &a.this, "_list", nl)?;
    changed(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn sp_get(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = get(vm, &a.this, "_list")?;
    for p in list_for(vm, &list, "find")? {
        let k = pair_key(vm, &p)?;
        if Value::strict_eq(&k, &name) {
            return pair_val(vm, &p);
        }
    }
    Ok(Value::Null)
}

fn sp_get_all(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = get(vm, &a.this, "_list")?;
    let mut out = Vec::new();
    for p in list_for(vm, &list, "filter")? {
        let k = pair_key(vm, &p)?;
        if Value::strict_eq(&k, &name) {
            out.push(pair_val(vm, &p)?);
        }
    }
    Ok(array(vm, out))
}

fn sp_has(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = get(vm, &a.this, "_list")?;
    for p in list_for(vm, &list, "some")? {
        let k = pair_key(vm, &p)?;
        if Value::strict_eq(&k, &name) {
            return Ok(Value::Bool(true));
        }
    }
    Ok(Value::Bool(false))
}

fn sp_set(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = Value::Str(js_string(vm, &a.arg(0))?);
    let list = get(vm, &a.this, "_list")?;
    let items = list_for(vm, &list, "findIndex")?;
    let mut found = None;
    for (i, p) in items.iter().enumerate() {
        let k = pair_key(vm, p)?;
        if Value::strict_eq(&k, &name) {
            found = Some(i);
            break;
        }
    }
    match found {
        Some(i) => {
            let list = get(vm, &a.this, "_list")?;
            let pair = get_key(vm, &list, &PropKey::from_index(i as u32))?;
            let v = js_string(vm, &a.arg(1))?;
            set_key(vm, &pair, PropKey::from_index(1), Value::Str(v))?;
            let list = get(vm, &a.this, "_list")?;
            let mut keep = Vec::new();
            for (j, p) in list_items(vm, &list)?.into_iter().enumerate() {
                let k = pair_key(vm, &p)?;
                if !Value::strict_eq(&k, &name) || j <= i {
                    keep.push(p);
                }
            }
            let nl = array(vm, keep);
            set(vm, &a.this, "_list", nl)?;
        }
        None => {
            let list = get(vm, &a.this, "_list")?;
            let v = js_string(vm, &a.arg(1))?;
            let p = array(vm, vec![name, Value::Str(v)]);
            arr_push(vm, &list, p)?;
        }
    }
    changed(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn sp_sort(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = get(vm, &a.this, "_list")?;
    let items = list_for(vm, &list, "sort")?;
    let mut keyed = Vec::with_capacity(items.len());
    for p in items {
        let k = pair_key(vm, &p)?;
        let ks = match &k {
            Value::Str(s) => s.clone(),
            other => js_string(vm, other)?,
        };
        keyed.push((ks, p));
    }
    keyed.sort_by(|x, y| x.0.units().cmp(y.0.units()));
    for (i, (_, p)) in keyed.into_iter().enumerate() {
        set_key(vm, &list, PropKey::from_index(i as u32), p)?;
    }
    changed(vm, &a.this)?;
    Ok(Value::Undefined)
}

fn sp_for_each(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let f = a.arg(0);
    let this_arg = a.arg(1);
    let list = get(vm, &a.this, "_list")?;
    let snapshot = list_for(vm, &list, ITER)?;
    for p in snapshot {
        let kv = vm.iterate_to_vec(&p)?;
        let k = kv.first().cloned().unwrap_or(Value::Undefined);
        let v = kv.get(1).cloned().unwrap_or(Value::Undefined);
        let call = get(vm, &f, "call")?;
        if !call.is_callable() {
            return vm.throw_type("(intermediate value).call is not a function");
        }
        vm.call(&call, f.clone(), &[this_arg.clone(), v, k, a.this.clone()])?;
    }
    Ok(Value::Undefined)
}

fn sp_size(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = get(vm, &a.this, "_list")?;
    get(vm, &list, "length")
}

fn sp_iterator(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    invoke(vm, &a.this, "entries", &[])
}

fn sp_to_string(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let list = get(vm, &a.this, "_list")?;
    // formEncode(list): list.map(([k, v]) => enc(k) + "=" + enc(v)).join("&")
    with_frame(vm, "formEncode", |vm| {
        let mut parts = Vec::new();
        for p in list_for(vm, &list, "map")? {
            let s = with_frame(vm, "<anonymous>", |vm| {
                let kv = vm.iterate_to_vec(&p)?;
                let k = kv.first().cloned().unwrap_or(Value::Undefined);
                let v = kv.get(1).cloned().unwrap_or(Value::Undefined);
                let ke = with_frame(vm, "enc", |vm| {
                    let ks = vm.to_string(&k)?;
                    form_encode_one(vm, &ks)
                })?;
                let ve = with_frame(vm, "enc", |vm| {
                    let vs = vm.to_string(&v)?;
                    form_encode_one(vm, &vs)
                })?;
                Ok(format!("{}={}", ke, ve))
            })?;
            parts.push(s);
        }
        Ok(Value::str(&parts.join("&")))
    })
}

// ---------------------------------------------------------------------------------------------
// generator-like iterators for URLSearchParams / FormData
// ---------------------------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq)]
pub enum GenKind {
    SpEntries,
    SpKeys,
    SpValues,
    FdEntries,
    FdKeys,
    FdValues,
}

pub struct NativeGen {
    pub kind: GenKind,
    pub target: Value,
    pub started: bool,
    pub done: bool,
    pub source: Value,
    pub index: usize,
}

fn gen_shared_proto(vm: &mut Vm) -> Obj {
    if let Some(p) = reg_get("%NativeGeneratorProto%") {
        return p;
    }
    let p = Obj::new(Some(vm.intr.generator_proto.clone()), ObjKind::Ordinary);
    vm.def_method(&p, "next", 1, gen_next);
    vm.def_method(&p, "return", 1, gen_return);
    vm.def_method(&p, "throw", 1, gen_throw);
    reg_set("%NativeGeneratorProto%", &p);
    p
}

fn gen_kind_from(v: &Value) -> GenKind {
    match v.as_num().unwrap_or(0.0) as u32 {
        0 => GenKind::SpEntries,
        1 => GenKind::SpKeys,
        2 => GenKind::SpValues,
        3 => GenKind::FdEntries,
        4 => GenKind::FdKeys,
        _ => GenKind::FdValues,
    }
}

fn gen_kind_num(k: GenKind) -> f64 {
    match k {
        GenKind::SpEntries => 0.0,
        GenKind::SpKeys => 1.0,
        GenKind::SpValues => 2.0,
        GenKind::FdEntries => 3.0,
        GenKind::FdKeys => 4.0,
        GenKind::FdValues => 5.0,
    }
}

/// A `*name()` generator method: the function has its own `prototype` object, iterators
/// inherit from it (and through it from %GeneratorPrototype%).
pub fn gen_method(vm: &mut Vm, target: &Obj, name: &str, kind: GenKind) -> Obj {
    let shared = gen_shared_proto(vm);
    let fproto = Obj::new(Some(shared), ObjKind::Ordinary);
    let f = vm.native_closure(name, 0, gen_start, vec![Value::Num(gen_kind_num(kind)), Value::Obj(fproto.clone())]);
    f.borrow_mut().proto = Some(vm.intr.generator_function_proto.clone());
    f.set_prop(vm.intr.key_prototype.clone(), Value::Obj(fproto), WRITABLE);
    target.set_prop(key(name), Value::Obj(f.clone()), WC);
    f
}

fn gen_start(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    if a.new_target.is_some() {
        return vm.throw_type("(intermediate value) is not a constructor");
    }
    let kind = gen_kind_from(&a.slot(0));
    let proto = match a.slot(1) {
        Value::Obj(p) => p,
        _ => vm.intr.generator_proto.clone(),
    };
    let g = NativeGen { kind, target: a.this.clone(), started: false, done: false, source: Value::Undefined, index: 0 };
    Ok(Value::Obj(Obj::new(Some(proto), ObjKind::Host(Box::new(std::cell::RefCell::new(g))))))
}

fn with_gen<R>(o: &Value, f: impl FnOnce(&mut NativeGen) -> R) -> Option<R> {
    if let Value::Obj(ob) = o {
        let b = ob.borrow();
        if let ObjKind::Host(h) = &b.kind {
            if let Some(cell) = h.downcast_ref::<std::cell::RefCell<NativeGen>>() {
                let mut g = cell.borrow_mut();
                return Some(f(&mut g));
            }
        }
    }
    None
}

fn gen_this_check(vm: &mut Vm, a: &Args, method: &str) -> JsResult<()> {
    if with_gen(&a.this, |_| ()).is_none() {
        return vm.throw_type(format!("{} method called on incompatible receiver", method));
    }
    Ok(())
}

fn gen_next(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    gen_this_check(vm, a, "next")?;
    let (done, started, kind, target) = with_gen(&a.this, |g| (g.done, g.started, g.kind, g.target.clone())).unwrap();
    if done {
        return Ok(vm.iter_result(Value::Undefined, true));
    }
    if !started {
        with_gen(&a.this, |g| g.started = true);
        let src = match kind {
            GenKind::SpEntries => {
                let list = get(vm, &target, "_list");
                let list = match list {
                    Ok(l) => l,
                    Err(e) => {
                        with_gen(&a.this, |g| g.done = true);
                        return Err(e);
                    }
                };
                let r: JsResult<Value> = (|| {
                    let mut copies = Vec::new();
                    for p in list_for(vm, &list, "map")? {
                        let items = vm.iterate_to_vec(&p)?;
                        copies.push(array(vm, items));
                    }
                    Ok(array(vm, copies))
                })();
                match r {
                    Ok(v) => v,
                    Err(e) => {
                        with_gen(&a.this, |g| g.done = true);
                        return Err(e);
                    }
                }
            }
            GenKind::SpKeys | GenKind::SpValues => match get(vm, &target, "_list") {
                Ok(l) => l,
                Err(e) => {
                    with_gen(&a.this, |g| g.done = true);
                    return Err(e);
                }
            },
            GenKind::FdEntries | GenKind::FdKeys | GenKind::FdValues => {
                let k = super::blob::form_entries_key(vm);
                match get_key(vm, &target, &k) {
                    Ok(l) => l,
                    Err(e) => {
                        with_gen(&a.this, |g| g.done = true);
                        return Err(e);
                    }
                }
            }
        };
        if src.is_nullish() && kind != GenKind::SpEntries {
            // `for (... of this._list)` over a missing list
            with_gen(&a.this, |g| g.done = true);
            list_for(vm, &src, ITER)?;
        }
        with_gen(&a.this, |g| g.source = src);
    }
    let (src, idx) = with_gen(&a.this, |g| (g.source.clone(), g.index)).unwrap();
    let r: JsResult<Option<Value>> = (|| {
        let len = match &src {
            Value::Obj(o) => vm.length_of(o)?,
            _ => {
                let l = get(vm, &src, "length")?;
                vm.to_length(&l)?
            }
        };
        if idx as u64 >= len {
            return Ok(None);
        }
        let item = get_key(vm, &src, &PropKey::from_index(idx as u32))?;
        let v = match kind {
            GenKind::SpEntries => item,
            GenKind::SpKeys | GenKind::FdKeys => pair_key(vm, &item)?,
            GenKind::SpValues | GenKind::FdValues => pair_val(vm, &item)?,
            GenKind::FdEntries => {
                let k = pair_key(vm, &item)?;
                let v = pair_val(vm, &item)?;
                array(vm, vec![k, v])
            }
        };
        Ok(Some(v))
    })();
    match r {
        Ok(Some(v)) => {
            with_gen(&a.this, |g| g.index += 1);
            Ok(vm.iter_result(v, false))
        }
        Ok(None) => {
            with_gen(&a.this, |g| {
                g.done = true;
                g.source = Value::Undefined;
            });
            Ok(vm.iter_result(Value::Undefined, true))
        }
        Err(e) => {
            with_gen(&a.this, |g| g.done = true);
            Err(e)
        }
    }
}

fn gen_return(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    gen_this_check(vm, a, "return")?;
    with_gen(&a.this, |g| {
        g.done = true;
        g.source = Value::Undefined;
    });
    Ok(vm.iter_result(a.arg(0), true))
}

fn gen_throw(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    gen_this_check(vm, a, "throw")?;
    with_gen(&a.this, |g| {
        g.done = true;
        g.source = Value::Undefined;
    });
    Err(a.arg(0))
}

// =============================================================================================
// URLPattern
// =============================================================================================

const COMPONENTS: [&str; 8] = ["protocol", "username", "password", "hostname", "port", "pathname", "search", "hash"];

fn setup_pattern(vm: &mut Vm) {
    let (c, p) = make_class(vm, "URLPattern", "URLPattern.prototype", 0, pattern_ctor, None);
    method(vm, &p, "_match", 2, pattern_match_method);
    method(vm, &p, "test", 2, pattern_test);
    method(vm, &p, "exec", 2, pattern_exec);
    set_global(vm, "URLPattern", Value::Obj(c));
}

fn regex_escape_char(c: char, out: &mut String) {
    if matches!(c, '.' | '*' | '+' | '?' | '^' | '$' | '{' | '}' | '(' | ')' | '|' | '[' | ']' | '\\' | '/') {
        out.push('\\');
    }
    out.push(c);
}

fn is_name_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_'
}

/// compileComponent(pattern, sep) -> (regex source, group names)
fn compile_component(pattern: Option<&str>, sep: &str) -> (String, Vec<String>) {
    let pattern = match pattern {
        None => return ("^.*$".to_string(), Vec::new()),
        Some(p) => p,
    };
    let chars: Vec<char> = pattern.chars().collect();
    let seg_class = if sep.is_empty() {
        "[^]".to_string()
    } else {
        let mut s = String::from("[^");
        s.push_str(sep);
        s.push(']');
        s
    };
    let (body, names) = compile_body(&chars, &seg_class);
    (format!("^{}$", body), names)
}

/// Regex body + group names for a pattern; `{...}` groups compile recursively (their unnamed
/// groups numbered from 0 again) and a lone `*` is `.*`.
fn compile_body(chars: &[char], seg_class: &str) -> (String, Vec<String>) {
    if chars.len() == 1 && chars[0] == '*' {
        return (".*".to_string(), vec!["0".to_string()]);
    }
    let mut names: Vec<String> = Vec::new();
    let mut counter = 0usize;
    let mut body = String::new();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        match c {
            ':' => {
                let mut j = i + 1;
                let mut name = String::new();
                while j < chars.len() && is_name_char(chars[j]) {
                    name.push(chars[j]);
                    j += 1;
                }
                names.push(name);
                if j < chars.len() && chars[j] == '(' {
                    let (re, end) = read_paren(&chars, j);
                    body.push('(');
                    body.push_str(&re);
                    body.push(')');
                    i = end;
                } else {
                    body.push('(');
                    body.push_str(seg_class);
                    body.push_str("+?)");
                    i = j;
                }
            }
            '(' => {
                let (re, end) = read_paren(&chars, i);
                names.push(counter.to_string());
                counter += 1;
                body.push('(');
                body.push_str(&re);
                body.push(')');
                i = end;
            }
            '*' => {
                names.push(counter.to_string());
                counter += 1;
                body.push_str("(.*)");
                i += 1;
            }
            '{' => {
                // matching '}' (nested braces counted); unterminated runs to the end
                let mut depth = 0usize;
                let mut j = i;
                let mut close = None;
                while j < chars.len() {
                    if chars[j] == '{' {
                        depth += 1;
                    } else if chars[j] == '}' {
                        depth -= 1;
                        if depth == 0 {
                            close = Some(j);
                            break;
                        }
                    }
                    j += 1;
                }
                let end = close.unwrap_or(chars.len());
                let (inner, inner_names) = compile_body(&chars[i + 1..end], seg_class);
                body.push_str("(?:");
                body.push_str(&inner);
                body.push(')');
                names.extend(inner_names);
                i = end + 1;
                if close.is_some() && i < chars.len() && matches!(chars[i], '?' | '+' | '*') {
                    body.push(chars[i]);
                    i += 1;
                }
            }
            _ => {
                regex_escape_char(c, &mut body);
                i += 1;
            }
        }
    }
    (body, names)
}

/// Read a balanced `( ... )` starting at `start` (which is '('); returns (inner, index after).
fn read_paren(chars: &[char], start: usize) -> (String, usize) {
    let mut depth = 0usize;
    let mut i = start;
    let mut inner = String::new();
    while i < chars.len() {
        let c = chars[i];
        if c == '(' {
            depth += 1;
            if depth > 1 {
                inner.push(c);
            }
        } else if c == ')' {
            depth -= 1;
            if depth == 0 {
                return (inner, i + 1);
            }
            inner.push(c);
        } else {
            inner.push(c);
        }
        i += 1;
    }
    (inner, chars.len())
}

/// componentsFromInput(input, baseURL): pattern strings per component (None = unspecified).
fn components_from_input(vm: &mut Vm, input: &Value, base: &Value) -> JsResult<Vec<Option<String>>> {
    let mut comps: Vec<Option<String>> = vec![None; 8];
    if is_object_type(input) {
        for (i, k) in COMPONENTS.iter().enumerate() {
            let v = get(vm, input, k)?;
            if !v.is_undefined() {
                comps[i] = Some(to_rs(&js_string(vm, &v)?));
            }
        }
        return Ok(comps);
    }
    let s = to_rs(&js_string(vm, input)?);
    if let Some(caps) = split_absolute_pattern(&s) {
        comps = caps;
        return Ok(comps);
    }
    // relative pattern: pathname[?search][#hash]
    let (path, rest) = match s.find(|c| c == '?' || c == '#') {
        Some(i) => (&s[..i], &s[i..]),
        None => (s.as_str(), ""),
    };
    let (search, hash) = if let Some(r) = rest.strip_prefix('?') {
        match r.find('#') {
            Some(i) => (Some(&r[..i]), Some(&r[i + 1..])),
            None => (Some(r), None),
        }
    } else if let Some(h) = rest.strip_prefix('#') {
        (None, Some(h))
    } else {
        (None, None)
    };
    comps[5] = Some(if path.is_empty() { "*".to_string() } else { path.to_string() });
    comps[6] = search.map(|x| x.to_string());
    comps[7] = hash.map(|x| x.to_string());
    if !base.is_undefined() {
        let u = construct_url(vm, base, &Value::Undefined)?;
        let proto = get(vm, &u, "protocol")?;
        let proto = to_rs(&vm.to_string(&proto)?);
        let proto = proto.strip_suffix(':').unwrap_or(&proto).to_string();
        let hostname = get(vm, &u, "hostname")?;
        let hostname = to_rs(&vm.to_string(&hostname)?);
        comps[0] = Some(proto);
        comps[3] = Some(hostname);
    }
    Ok(comps)
}

/// `scheme://[user[:pass]@]host[:port]/path?search#hash` split of an absolute pattern string.
fn split_absolute_pattern(s: &str) -> Option<Vec<Option<String>>> {
    let idx = s.find("://")?;
    let scheme = &s[..idx];
    if scheme.is_empty() || scheme.contains(|c| c == ':' || c == '/' || c == '?' || c == '#') {
        return None;
    }
    let rest = &s[idx + 3..];
    let auth_end = rest.find(|c| c == '/' || c == '?' || c == '#').unwrap_or(rest.len());
    let authority = &rest[..auth_end];
    let tail = &rest[auth_end..];
    let mut comps: Vec<Option<String>> = vec![None; 8];
    comps[0] = Some(scheme.to_string());
    let (userinfo, hostport) = match authority.rfind('@') {
        Some(i) => (Some(&authority[..i]), &authority[i + 1..]),
        None => (None, authority),
    };
    if let Some(u) = userinfo {
        match u.find(':') {
            Some(j) => {
                comps[1] = Some(u[..j].to_string());
                comps[2] = Some(u[j + 1..].to_string());
            }
            None => comps[1] = Some(u.to_string()),
        }
    }
    // `host:port` splits at the last ':' unless the port part holds a '(' (a regexp group)
    match hostport.rfind(':') {
        Some(j) if !hostport[j + 1..].contains('(') => {
            comps[3] = Some(hostport[..j].to_string());
            comps[4] = Some(hostport[j + 1..].to_string());
        }
        _ => comps[3] = Some(hostport.to_string()),
    }
    let (path, rest2) = match tail.find(|c| c == '?' || c == '#') {
        Some(i) => (&tail[..i], &tail[i..]),
        None => (tail, ""),
    };
    comps[5] = Some(if path.is_empty() { "/".to_string() } else { path.to_string() });
    if let Some(r) = rest2.strip_prefix('?') {
        match r.find('#') {
            Some(i) => {
                comps[6] = Some(r[..i].to_string());
                comps[7] = Some(r[i + 1..].to_string());
            }
            None => comps[6] = Some(r.to_string()),
        }
    } else if let Some(h) = rest2.strip_prefix('#') {
        comps[7] = Some(h.to_string());
    }
    Some(comps)
}

fn pattern_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let o = new_this(vm, a, "URLPattern.prototype")?;
    let ov = Value::Obj(o);
    let input = if a.arg(0).is_undefined() { Value::Obj(vm.new_object()) } else { a.arg(0) };
    let mut base = a.arg(1);
    let options = a.arg(2);
    if base.type_of() == "object" && options.is_undefined() {
        base = Value::Undefined;
    }
    let comps = components_from_input(vm, &input, &base)?;
    let parts = vm.new_object();
    let pv = Value::Obj(parts.clone());
    set(vm, &ov, "_parts", pv.clone())?;
    for (i, k) in COMPONENTS.iter().enumerate() {
        let sep = if *k == "pathname" {
            "/"
        } else if *k == "hostname" {
            "."
        } else {
            ""
        };
        let (src, names) = compile_component(comps[i].as_deref(), sep);
        let re = crate::builtins::regexp::regexp_create(vm, &rs_val(&src), &Value::str("su"))?;
        let names_v: Vec<Value> = names.iter().map(|n| rs_val(n)).collect();
        let na = array(vm, names_v);
        let part = plain(vm, vec![("regex", re), ("names", na)]);
        set(vm, &pv, k, Value::Obj(part))?;
        let shown = comps[i].clone().unwrap_or_else(|| "*".to_string());
        set(vm, &ov, k, rs_val(&shown))?;
    }
    Ok(ov)
}

fn exec_part(vm: &mut Vm, this: &Value, k: &str, value: &Value) -> JsResult<Option<Value>> {
    let parts = get(vm, this, "_parts")?;
    let part = get(vm, &parts, k)?;
    let re = get(vm, &part, "regex")?;
    let m = invoke(vm, &re, "exec", &[value.clone()])?;
    if m.is_nullish() {
        return Ok(None);
    }
    let names = get(vm, &part, "names")?;
    let groups = vm.new_object();
    let gv = Value::Obj(groups);
    let names = list_items(vm, &names)?;
    for (i, n) in names.iter().enumerate() {
        let g = get_key(vm, &m, &PropKey::from_index(i as u32 + 1))?;
        let g = if g.is_nullish() { Value::str("") } else { g };
        let pk = vm.to_property_key(n)?;
        vm.set_prop_of(&gv, pk, g, true)?;
    }
    Ok(Some(gv))
}

fn pattern_match(vm: &mut Vm, this: &Value, input: &Value, base: &Value) -> JsResult<Value> {
    if is_object_type(input) {
        let r: JsResult<Option<Vec<(Value, Value)>>> = (|| {
            let mut res = Vec::new();
            for k in COMPONENTS {
                let v = get(vm, input, k)?;
                let s = if v.is_undefined() { Value::str("") } else { Value::Str(js_string(vm, &v)?) };
                match exec_part(vm, this, k, &s)? {
                    Some(g) => res.push((s, g)),
                    None => return Ok(None),
                }
            }
            Ok(Some(res))
        })();
        let res = match r {
            Ok(Some(res)) => res,
            Ok(None) | Err(_) => return Ok(Value::Null),
        };
        let inputs = array(vm, vec![input.clone()]);
        let out = plain(vm, vec![("inputs", inputs)]);
        for (i, (s, g)) in res.into_iter().enumerate() {
            let entry = plain(vm, vec![("input", s), ("groups", g)]);
            out.set_prop(key(COMPONENTS[i]), Value::Obj(entry), WEC);
        }
        return Ok(Value::Obj(out));
    }
    let url = match construct_url(vm, input, base) {
        Ok(u) => u,
        Err(_) => return Ok(Value::Null),
    };
    let mut values: Vec<Value> = Vec::new();
    for k in ["protocol", "username", "password", "hostname", "port", "pathname", "search", "hash"] {
        let v = get(vm, &url, k)?;
        let s = vm.to_string(&v)?;
        let s = match k {
            "protocol" if s.units().last() == Some(&(b':' as u16)) => s.substring(0, s.len() - 1),
            "search" if s.units().first() == Some(&(b'?' as u16)) => s.substring(1, s.len()),
            "hash" if s.units().first() == Some(&(b'#' as u16)) => s.substring(1, s.len()),
            _ => s,
        };
        values.push(Value::Str(s));
    }
    let inputs = array(vm, vec![input.clone()]);
    let out = plain(vm, vec![("inputs", inputs)]);
    for (i, k) in COMPONENTS.iter().enumerate() {
        match exec_part(vm, this, k, &values[i])? {
            Some(g) => {
                let entry = plain(vm, vec![("input", values[i].clone()), ("groups", g)]);
                out.set_prop(key(k), Value::Obj(entry), WEC);
            }
            None => return Ok(Value::Null),
        }
    }
    Ok(Value::Obj(out))
}

fn pattern_match_method(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    pattern_match(vm, &a.this, &a.arg(0), &a.arg(1))
}

fn pattern_test(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let r = invoke(vm, &a.this, "_match", &[a.arg(0), a.arg(1)])?;
    Ok(Value::Bool(!r.is_null()))
}

fn pattern_exec(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    invoke(vm, &a.this, "_match", &[a.arg(0), a.arg(1)])
}

// =============================================================================================
// node:querystring
// =============================================================================================

fn qs_unescape_units(u: &[u16]) -> Option<Vec<u16>> {
    let sp: Vec<u16> = u.iter().map(|&c| if c == b'+' as u16 { b' ' as u16 } else { c }).collect();
    decode_uri_component(&sp)
}

fn qs_escape_val(vm: &mut Vm, s: &JsStr) -> JsResult<String> {
    match encode_uri_component(s.units()) {
        Ok(e) => Ok(e),
        Err(_) => uri_malformed(vm),
    }
}

/// `querystring.parse(str, sep = "&", eq = "=")`
pub fn qs_parse(vm: &mut Vm, s: &Value, sep: &Value, eq: &Value) -> JsResult<Value> {
    let obj = Obj::new(None, ObjKind::Ordinary);
    let ov = Value::Obj(obj.clone());
    let st = match s {
        Value::Str(st) if !st.is_empty() => st.clone(),
        _ => return Ok(ov),
    };
    let sep = if sep.is_undefined() { Value::str("&") } else { sep.clone() };
    let eq = if eq.is_undefined() { Value::str("=") } else { eq.clone() };
    let parts = invoke(vm, &Value::Str(st), "split", &[sep])?;
    let eqs = match &eq {
        Value::Str(e) => e.clone(),
        other => vm.to_string(other)?,
    };
    for part in list_items(vm, &parts)? {
        let p = match &part {
            Value::Str(p) => p.clone(),
            other => vm.to_string(other)?,
        };
        if p.is_empty() {
            continue;
        }
        let idx = p.index_of(eqs.units(), 0);
        let (k, v) = match idx {
            None => (qs_unescape_js(&p), JsStr::empty()),
            Some(i) => {
                let kraw = p.substring(0, i);
                let vstart = (i + eqs.len()).min(p.len());
                let vraw = p.substring(vstart, p.len());
                (qs_unescape_js(&kraw), qs_unescape_js(&vraw))
            }
        };
        let pk = PropKey::Str(k.clone());
        let exists = vm.has_property(&obj, &pk)?;
        if exists {
            let cur = vm.get(&obj, &pk, &ov)?;
            if crate::builtins::array::is_array(vm, &cur)? {
                arr_push(vm, &cur, Value::Str(v))?;
            } else {
                let a = array(vm, vec![cur, Value::Str(v)]);
                vm.set_prop_of(&ov, pk, a, true)?;
            }
        } else {
            obj.set_prop(pk, Value::Str(v), WEC);
        }
    }
    Ok(ov)
}

fn qs_unescape_js(s: &JsStr) -> JsStr {
    match qs_unescape_units(s.units()) {
        Some(u) => JsStr::from_units(u),
        None => s.clone(),
    }
}

/// `querystring.stringify(obj, sep = "&", eq = "=")`
pub fn qs_stringify(vm: &mut Vm, obj: &Value, sep: &Value, eq: &Value) -> JsResult<Value> {
    if !is_object_type(obj) {
        return Ok(Value::str(""));
    }
    let sep = if sep.is_undefined() { Value::str("&") } else { sep.clone() };
    let eq = if eq.is_undefined() { Value::str("=") } else { eq.clone() };
    let o = obj.as_obj().unwrap().clone();
    let mut pairs: Vec<Value> = Vec::new();
    let eqs = vm.to_string(&eq)?;
    for k in vm.enumerable_own_keys(&o)? {
        let ek = qs_escape_val(vm, &k)?;
        let v = vm.get(&o, &PropKey::Str(k), obj)?;
        if crate::builtins::array::is_array(vm, &v)? {
            for item in vm.iterate_to_vec(&v)? {
                let s = js_string(vm, &item)?;
                let ev = qs_escape_val(vm, &s)?;
                pairs.push(Value::str(&format!("{}{}{}", ek, eqs, ev)));
            }
        } else {
            let s = if v.is_nullish() { JsStr::empty() } else { js_string(vm, &v)? };
            let ev = qs_escape_val(vm, &s)?;
            pairs.push(Value::str(&format!("{}{}{}", ek, eqs, ev)));
        }
    }
    let arr = array(vm, pairs);
    invoke(vm, &arr, "join", &[sep])
}

fn qs_parse_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    qs_parse(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

fn qs_stringify_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    qs_stringify(vm, &a.arg(0), &a.arg(1), &a.arg(2))
}

fn qs_escape_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.to_string(&a.arg(0))?;
    Ok(Value::str(&qs_escape_val(vm, &s)?))
}

fn qs_unescape_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = a.arg(0);
    match &s {
        Value::Str(st) => Ok(Value::Str(qs_unescape_js(st))),
        Value::Obj(_) => {
            let r: JsResult<Value> = (|| {
                let replaced = invoke(vm, &s, "replace", &[Value::str("+"), Value::str(" ")])?;
                let _ = replaced;
                Ok(Value::Undefined)
            })();
            match r {
                Ok(_) => Ok(s),
                Err(_) => Ok(s),
            }
        }
        _ => Ok(s),
    }
}

fn qs_unescape_buffer_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let decode_spaces = a.arg(1).truthy();
    let u = s.units();
    let mut out: Vec<u8> = Vec::with_capacity(u.len());
    let mut i = 0;
    while i < u.len() {
        let c = u[i];
        if c == 0x2b && decode_spaces {
            out.push(0x20);
            i += 1;
            continue;
        }
        if c == 0x25 && i + 2 < u.len() {
            if let (Some(hi), Some(lo)) = (hexval(u[i + 1]), hexval(u[i + 2])) {
                out.push((hi << 4) | lo);
                i += 3;
                continue;
            }
        }
        out.push(c as u8);
        i += 1;
    }
    crate::runtime::buffer::new_buffer_value(vm, out)
}

pub fn create_querystring_module(vm: &mut Vm) -> Value {
    let m = vm.new_object();
    let parse = plain_fn(vm, "parse", 1, qs_parse_fn);
    let stringify = plain_fn(vm, "stringify", 1, qs_stringify_fn);
    m.set_prop(key("parse"), Value::Obj(parse.clone()), WEC);
    m.set_prop(key("stringify"), Value::Obj(stringify.clone()), WEC);
    m.set_prop(key("decode"), Value::Obj(parse), WEC);
    m.set_prop(key("encode"), Value::Obj(stringify), WEC);
    let esc = vm.native_fn("qsEscape", 1, qs_escape_fn);
    m.set_prop(key("escape"), Value::Obj(esc), WEC);
    let unesc = vm.native_fn("qsUnescape", 1, qs_unescape_fn);
    m.set_prop(key("unescape"), Value::Obj(unesc), WEC);
    let ub = plain_fn(vm, "unescapeBuffer", 1, qs_unescape_buffer_fn);
    m.set_prop(key("unescapeBuffer"), Value::Obj(ub), WEC);
    Value::Obj(m)
}

// =============================================================================================
// node:url
// =============================================================================================

/// The legacy `url.parse(urlStr, parseQueryString, slashesDenoteHost)` result object.
fn legacy_parse(vm: &mut Vm, url_str: &Value, parse_qs: bool, slashes_host: bool) -> JsResult<Value> {
    let o = vm.obj_from(vec![
        ("protocol", Value::Null),
        ("slashes", Value::Null),
        ("auth", Value::Null),
        ("host", Value::Null),
        ("port", Value::Null),
        ("hostname", Value::Null),
        ("hash", Value::Null),
        ("search", Value::Null),
        ("query", Value::Null),
        ("pathname", Value::Null),
        ("path", Value::Null),
        ("href", url_str.clone()),
    ]);
    let ov = Value::Obj(o.clone());
    let mut rest: Vec<u16> = js_string(vm, url_str)?.units().to_vec();
    let put = |o: &Obj, k: &str, v: Value| o.set_prop(key(k), v, WEC);
    let find = |s: &[u16], c: u16| s.iter().position(|&x| x == c);
    if let Some(h) = find(&rest, b'#' as u16) {
        put(&o, "hash", Value::Str(JsStr::from_slice(&rest[h..])));
        rest.truncate(h);
    }
    // protocol: /^([a-z0-9.+-]+:)/i
    let mut plen = 0;
    while plen < rest.len() && (rest[plen] < 128 && ((rest[plen] as u8).is_ascii_alphanumeric() || matches!(rest[plen] as u8, b'.' | b'+' | b'-'))) {
        plen += 1;
    }
    let mut has_proto = false;
    if plen > 0 && plen < rest.len() && rest[plen] == b':' as u16 {
        let p: Vec<u16> = rest[..=plen].iter().map(|&c| if (0x41..=0x5A).contains(&c) { c + 32 } else { c }).collect();
        put(&o, "protocol", Value::Str(JsStr::from_units(p)));
        rest.drain(..=plen);
        has_proto = true;
    }
    let starts_slashes = rest.len() >= 2 && rest[0] == b'/' as u16 && rest[1] == b'/' as u16;
    if (has_proto && starts_slashes) || (slashes_host && starts_slashes) {
        put(&o, "slashes", Value::Bool(true));
        rest.drain(..2);
        let mut host_end = rest.len();
        for ch in [b'/', b'?', b'#'] {
            if let Some(i) = find(&rest, ch as u16) {
                if i < host_end {
                    host_end = i;
                }
            }
        }
        let mut host: Vec<u16> = rest[..host_end].to_vec();
        rest.drain(..host_end);
        if let Some(at) = host.iter().rposition(|&c| c == b'@' as u16) {
            put(&o, "auth", Value::Str(JsStr::from_slice(&host[..at])));
            host = host[at + 1..].to_vec();
        }
        put(&o, "host", Value::Str(JsStr::from_slice(&host)));
        match host.iter().rposition(|&c| c == b':' as u16) {
            Some(c) => {
                put(&o, "hostname", Value::Str(JsStr::from_slice(&host[..c])));
                put(&o, "port", Value::Str(JsStr::from_slice(&host[c + 1..])));
            }
            None => put(&o, "hostname", Value::Str(JsStr::from_slice(&host))),
        }
    }
    match find(&rest, b'?' as u16) {
        Some(q) => {
            put(&o, "search", Value::Str(JsStr::from_slice(&rest[q..])));
            put(&o, "pathname", Value::Str(JsStr::from_slice(&rest[..q])));
        }
        None => put(&o, "pathname", Value::Str(JsStr::from_slice(&rest))),
    }
    let search = get(vm, &ov, "search")?;
    if search.truthy() {
        let s = vm.to_string(&search)?;
        let tail = Value::Str(s.substring(1, s.len()));
        let q = if parse_qs { qs_parse(vm, &tail, &Value::Undefined, &Value::Undefined)? } else { tail };
        put(&o, "query", q);
    } else {
        let q = if parse_qs { Value::Obj(Obj::new(None, ObjKind::Ordinary)) } else { Value::Null };
        put(&o, "query", q);
    }
    let pathname = get(vm, &ov, "pathname")?;
    let host = get(vm, &ov, "host")?;
    if Value::strict_eq(&pathname, &Value::str("")) && host.truthy() {
        put(&o, "pathname", Value::str("/"));
    }
    let pathname = get(vm, &ov, "pathname")?;
    let search = get(vm, &ov, "search")?;
    let search = if search.truthy() { search } else { Value::str("") };
    let path = vm.op_add(&pathname, &search)?;
    put(&o, "path", path);
    Ok(ov)
}

fn url_legacy_parse_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let pq = if a.arg(1).is_undefined() { false } else { a.arg(1).truthy() };
    let sh = if a.arg(2).is_undefined() { false } else { a.arg(2).truthy() };
    legacy_parse(vm, &a.arg(0), pq, sh)
}

fn url_format(vm: &mut Vm, u: &Value) -> JsResult<Value> {
    if let Value::Str(_) = u {
        return Ok(u.clone());
    }
    let url_ctor = Value::Obj(reg(vm, "URL"));
    if u.is_object() && vm.instance_of(u, &url_ctor)? {
        return get(vm, u, "href");
    }
    let mut out = String::new();
    let ts = |vm: &mut Vm, v: &Value| -> JsResult<String> { Ok(to_rs(&vm.to_string(v)?)) };
    let protocol = get(vm, u, "protocol")?;
    if protocol.truthy() {
        out.push_str(&ts(vm, &protocol)?);
        let slashes = get(vm, u, "slashes")?;
        let slashes = if slashes.truthy() { true } else { get(vm, u, "host")?.truthy() };
        if slashes {
            out.push_str("//");
        }
    }
    let auth = get(vm, u, "auth")?;
    if auth.truthy() {
        out.push_str(&ts(vm, &auth)?);
        out.push('@');
    }
    let host = get(vm, u, "host")?;
    if host.truthy() {
        out.push_str(&ts(vm, &host)?);
    } else {
        let hostname = get(vm, u, "hostname")?;
        if hostname.truthy() {
            out.push_str(&ts(vm, &hostname)?);
            let port = get(vm, u, "port")?;
            if port.truthy() {
                out.push(':');
                out.push_str(&ts(vm, &port)?);
            }
        }
    }
    let pathname = get(vm, u, "pathname")?;
    if pathname.truthy() {
        out.push_str(&ts(vm, &pathname)?);
    }
    let search = get(vm, u, "search")?;
    if search.truthy() {
        out.push_str(&ts(vm, &search)?);
    } else {
        let query = get(vm, u, "query")?;
        if query.truthy() && is_object_type(&query) {
            let q = qs_stringify(vm, &query, &Value::Undefined, &Value::Undefined)?;
            let qs = ts(vm, &q)?;
            out.push('?');
            out.push_str(&qs);
        }
    }
    let hash = get(vm, u, "hash")?;
    if hash.truthy() {
        out.push_str(&ts(vm, &hash)?);
    }
    Ok(rs_val(&out))
}

fn url_format_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    url_format(vm, &a.arg(0))
}

/// `(from, to) => new URL(to, new URL(from, "http://localhost")).href`
fn url_resolve(vm: &mut Vm, from: &Value, to: &Value) -> JsResult<Value> {
    let base = construct_url(vm, from, &Value::str("http://localhost"))?;
    let u = construct_url(vm, to, &base)?;
    get(vm, &u, "href")
}

fn url_resolve_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    url_resolve(vm, &a.arg(0), &a.arg(1))
}

fn url_resolve_object_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let source = a.arg(0);
    let relative = a.arg(1);
    if !source.truthy() {
        return Ok(relative);
    }
    let s = if let Value::Str(_) = &source { source.clone() } else { url_format(vm, &source)? };
    let r = url_resolve(vm, &s, &relative)?;
    legacy_parse(vm, &r, false, false)
}

fn url_to_http_options_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let u = a.arg(0);
    let protocol = get(vm, &u, "protocol")?;
    let hostname = get(vm, &u, "hostname")?;
    let hostname = match &hostname {
        Value::Str(h) if h.units().first() == Some(&(b'[' as u16)) => {
            let n = h.len();
            Value::Str(h.substring(1, if n >= 1 { n - 1 } else { 0 }.max(1)))
        }
        _ => hostname,
    };
    let hash = get(vm, &u, "hash")?;
    let search = get(vm, &u, "search")?;
    let pathname = get(vm, &u, "pathname")?;
    let p1 = get(vm, &u, "pathname")?;
    let p1 = if p1.truthy() { p1 } else { Value::str("") };
    let s1 = get(vm, &u, "search")?;
    let s1 = if s1.truthy() { s1 } else { Value::str("") };
    let p1s = vm.to_string(&p1)?;
    let s1s = vm.to_string(&s1)?;
    let path = Value::Str(JsStr::concat(&p1s, &s1s));
    let href = get(vm, &u, "href")?;
    let o = vm.obj_from(vec![
        ("protocol", protocol),
        ("hostname", hostname),
        ("hash", hash),
        ("search", search),
        ("pathname", pathname),
        ("path", path),
        ("href", href),
    ]);
    let port = get(vm, &u, "port")?;
    if !Value::strict_eq(&port, &Value::str("")) {
        let n = vm.to_number(&port)?;
        o.set_prop(key("port"), Value::Num(n), WEC);
    }
    let user = get(vm, &u, "username")?;
    let pass = get(vm, &u, "password")?;
    if user.truthy() || pass.truthy() {
        let us = vm.to_string(&user)?;
        let ps = vm.to_string(&pass)?;
        let du = match decode_uri_component(us.units()) {
            Some(x) => JsStr::from_units(x),
            None => return uri_malformed(vm),
        };
        let dp = match decode_uri_component(ps.units()) {
            Some(x) => JsStr::from_units(x),
            None => return uri_malformed(vm),
        };
        o.set_prop(key("auth"), Value::str(&format!("{}:{}", du, dp)), WEC);
    }
    Ok(Value::Obj(o))
}

fn url_domain_to_ascii_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let lower = invoke(vm, &Value::Str(s), "toLowerCase", &[])?;
    let l = vm.to_string(&lower)?;
    Ok(Value::Str(punycode_to_ascii(&l)))
}

fn url_domain_to_unicode_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = js_string(vm, &a.arg(0))?;
    let lower = invoke(vm, &Value::Str(s), "toLowerCase", &[])?;
    let l = vm.to_string(&lower)?;
    match punycode_to_unicode(&l) {
        Ok(r) => Ok(Value::Str(r)),
        Err(m) => vm.throw_range(m),
    }
}

/// `(u) => (typeof u === "string" ? u : u.pathname).replace(/^file:\/\//, "")`
fn url_file_url_to_path_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let u = a.arg(0);
    let s = if let Value::Str(_) = &u { u.clone() } else { get(vm, &u, "pathname")? };
    let st = match &s {
        Value::Str(st) => st.clone(),
        _ => {
            return invoke(vm, &s, "replace", &[Value::str("file://"), Value::str("")]);
        }
    };
    let pre: Vec<u16> = "file://".encode_utf16().collect();
    if st.units().starts_with(&pre) {
        return Ok(Value::Str(st.substring(pre.len(), st.len())));
    }
    Ok(Value::Str(st))
}

/// `(p) => new URL("file://" + p)`
fn url_path_to_file_url_fn(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let s = vm.op_add(&Value::str("file://"), &a.arg(0))?;
    construct_url(vm, &s, &Value::Undefined)
}

fn url_ctor_noop(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let _ = vm;
    Ok(Value::Undefined)
}

pub fn create_url_module(vm: &mut Vm) -> Value {
    let m = vm.new_object();
    let put = |vm: &mut Vm, m: &Obj, k: &str, v: Obj| {
        let _ = vm;
        m.set_prop(key(k), Value::Obj(v), WEC);
    };
    let f = plain_fn(vm, "legacyParse", 1, url_legacy_parse_fn);
    put(vm, &m, "parse", f);
    let f = plain_fn(vm, "format", 1, url_format_fn);
    put(vm, &m, "format", f);
    let f = vm.native_fn("resolve", 2, url_resolve_fn);
    put(vm, &m, "resolve", f);
    let f = plain_fn(vm, "resolveObject", 2, url_resolve_object_fn);
    put(vm, &m, "resolveObject", f);
    let f = plain_fn(vm, "urlToHttpOptions", 1, url_to_http_options_fn);
    put(vm, &m, "urlToHttpOptions", f);
    let u = reg(vm, "URL");
    put(vm, &m, "URL", u);
    let sp = reg(vm, "URLSearchParams");
    put(vm, &m, "URLSearchParams", sp);
    let f = plain_fn(vm, "Url", 0, url_ctor_noop);
    put(vm, &m, "Url", f);
    let f = vm.native_fn("domainToASCII", 1, url_domain_to_ascii_fn);
    put(vm, &m, "domainToASCII", f);
    let f = vm.native_fn("domainToUnicode", 1, url_domain_to_unicode_fn);
    put(vm, &m, "domainToUnicode", f);
    let f = vm.native_fn("fileURLToPath", 1, url_file_url_to_path_fn);
    put(vm, &m, "fileURLToPath", f);
    let f = vm.native_fn("pathToFileURL", 1, url_path_to_file_url_fn);
    put(vm, &m, "pathToFileURL", f);
    Value::Obj(m)
}

// =============================================================================================
// punycode (RFC 3492) as used by domainToASCII / domainToUnicode
// =============================================================================================

const BASE: u32 = 36;
const TMIN: u32 = 1;
const TMAX: u32 = 26;
const SKEW: u32 = 38;
const DAMP: u32 = 700;
const INITIAL_BIAS: u32 = 72;
const INITIAL_N: u32 = 128;

fn adapt(mut delta: u32, num_points: u32, first: bool) -> u32 {
    delta = if first { delta / DAMP } else { delta / 2 };
    delta += delta / num_points;
    let mut k = 0;
    while delta > ((BASE - TMIN) * TMAX) / 2 {
        delta /= BASE - TMIN;
        k += BASE;
    }
    k + (BASE - TMIN + 1) * delta / (delta + SKEW)
}

fn digit_to_basic(d: u32) -> u16 {
    if d < 26 {
        (b'a' as u32 + d) as u16
    } else {
        (b'0' as u32 + d - 26) as u16
    }
}

fn basic_to_digit(c: u32) -> u32 {
    if c >= 0x30 && c < 0x3A {
        26 + (c - 0x30)
    } else if c >= 0x41 && c < 0x5B {
        c - 0x41
    } else if c >= 0x61 && c < 0x7B {
        c - 0x61
    } else {
        BASE
    }
}

/// UCS-2 decode (surrogate pairs combined) as punycode.js does.
fn ucs2_decode(u: &[u16]) -> Vec<u32> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < u.len() {
        let c = u[i] as u32;
        i += 1;
        if (0xD800..=0xDBFF).contains(&c) && i < u.len() {
            let extra = u[i] as u32;
            if extra & 0xFC00 == 0xDC00 {
                out.push(((c & 0x3FF) << 10) + (extra & 0x3FF) + 0x10000);
                i += 1;
                continue;
            }
        }
        out.push(c);
    }
    out
}

fn ucs2_encode(cps: &[u32]) -> Vec<u16> {
    let mut out = Vec::new();
    for &c in cps {
        if c > 0xFFFF {
            let v = c - 0x10000;
            out.push(0xD800 + (v >> 10) as u16);
            out.push(0xDC00 + (v & 0x3FF) as u16);
        } else {
            out.push(c as u16);
        }
    }
    out
}

fn puny_encode(label: &[u16]) -> Result<Vec<u16>, &'static str> {
    let input = ucs2_decode(label);
    let mut out: Vec<u16> = Vec::new();
    let mut n = INITIAL_N;
    let mut delta: u32 = 0;
    let mut bias = INITIAL_BIAS;
    for &c in &input {
        if c < 0x80 {
            out.push(c as u16);
        }
    }
    let basic_len = out.len() as u32;
    let mut handled = basic_len;
    if basic_len > 0 {
        out.push(b'-' as u16);
    }
    let total = input.len() as u32;
    while handled < total {
        let mut m = u32::MAX;
        for &c in &input {
            if c >= n && c < m {
                m = c;
            }
        }
        let inc = (m - n).checked_mul(handled + 1).ok_or("Overflow: input needs wider integers to process")?;
        delta = delta.checked_add(inc).ok_or("Overflow: input needs wider integers to process")?;
        n = m;
        for &c in &input {
            if c < n {
                delta = delta.checked_add(1).ok_or("Overflow: input needs wider integers to process")?;
            }
            if c == n {
                let mut q = delta;
                let mut k = BASE;
                loop {
                    let t = if k <= bias {
                        TMIN
                    } else if k >= bias + TMAX {
                        TMAX
                    } else {
                        k - bias
                    };
                    if q < t {
                        break;
                    }
                    let qmt = q - t;
                    let bmt = BASE - t;
                    out.push(digit_to_basic(t + qmt % bmt));
                    q = qmt / bmt;
                    k += BASE;
                }
                out.push(digit_to_basic(q));
                bias = adapt(delta, handled + 1, handled == basic_len);
                delta = 0;
                handled += 1;
            }
        }
        delta += 1;
        n += 1;
    }
    Ok(out)
}

fn puny_decode(input: &[u16]) -> Result<Vec<u16>, &'static str> {
    let mut output: Vec<u32> = Vec::new();
    let input_len = input.len();
    let mut i: u32 = 0;
    let mut n = INITIAL_N;
    let mut bias = INITIAL_BIAS;
    let basic = input.iter().rposition(|&c| c == b'-' as u16).unwrap_or(0);
    for j in 0..basic {
        if input[j] >= 0x80 {
            return Err("Illegal input >= 0x80 (not a basic code point)");
        }
        output.push(input[j] as u32);
    }
    let mut index = if basic > 0 { basic + 1 } else { 0 };
    while index < input_len {
        let old_i = i;
        let mut w: u32 = 1;
        let mut k = BASE;
        loop {
            if index >= input_len {
                return Err("Invalid input");
            }
            let digit = basic_to_digit(input[index] as u32);
            index += 1;
            if digit >= BASE {
                return Err("Invalid input");
            }
            if digit > (u32::MAX - i) / w {
                return Err("Overflow: input needs wider integers to process");
            }
            i += digit * w;
            let t = if k <= bias {
                TMIN
            } else if k >= bias + TMAX {
                TMAX
            } else {
                k - bias
            };
            if digit < t {
                break;
            }
            let base_minus_t = BASE - t;
            if w > u32::MAX / base_minus_t {
                return Err("Overflow: input needs wider integers to process");
            }
            w *= base_minus_t;
            k += BASE;
        }
        let out_len = output.len() as u32 + 1;
        bias = adapt(i - old_i, out_len, old_i == 0);
        if i / out_len > u32::MAX - n {
            return Err("Overflow: input needs wider integers to process");
        }
        n += i / out_len;
        i %= out_len;
        output.insert(i as usize, n);
        i += 1;
    }
    Ok(ucs2_encode(&output))
}

fn is_separator(c: u16) -> bool {
    matches!(c, 0x2E | 0x3002 | 0xFF0E | 0xFF61)
}

fn map_domain(s: &JsStr, f: &mut dyn FnMut(&[u16]) -> Result<Vec<u16>, &'static str>) -> Result<JsStr, &'static str> {
    // punycode.js mapDomain: with '@'s, keep parts[0] + "@" and map only parts[1]
    let u = s.units();
    let parts: Vec<&[u16]> = u.split(|&c| c == b'@' as u16).collect();
    let (prefix, domain): (Vec<u16>, &[u16]) = if parts.len() > 1 {
        let mut p = parts[0].to_vec();
        p.push(b'@' as u16);
        (p, parts[1])
    } else {
        (Vec::new(), u)
    };
    let mut out = prefix;
    let mut first = true;
    for label in domain.split(|&c| is_separator(c)) {
        if !first {
            out.push(b'.' as u16);
        }
        first = false;
        out.extend(f(label)?);
    }
    Ok(JsStr::from_units(out))
}

pub fn punycode_to_ascii(s: &JsStr) -> JsStr {
    let r = map_domain(s, &mut |label: &[u16]| {
        if label.iter().any(|&c| c >= 0x80) {
            let mut v: Vec<u16> = "xn--".encode_utf16().collect();
            v.extend(puny_encode(label)?);
            Ok(v)
        } else {
            Ok(label.to_vec())
        }
    });
    r.unwrap_or_else(|_| s.clone())
}

pub fn punycode_to_unicode(s: &JsStr) -> Result<JsStr, &'static str> {
    map_domain(s, &mut |label: &[u16]| {
        let pre: Vec<u16> = "xn--".encode_utf16().collect();
        if label.starts_with(&pre) {
            let lower: Vec<u16> = label[4..].iter().map(|&c| if (0x41..=0x5A).contains(&c) { c + 32 } else { c }).collect();
            puny_decode(&lower)
        } else {
            Ok(label.to_vec())
        }
    })
}
