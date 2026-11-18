// `|image|`: a raster or SVG file, embedded.
//
// `src:` is an http(s) URL or data: URI (referenced as is) or a local path,
// read relative to the input file's directory. Rasters (sniffed by magic:
// PNG, JPEG, GIF, WebP) embed as a base64 data: URI in an `<image>`; an SVG
// file is inlined as a nested `<svg>` with its ids namespaced. `fit` maps to
// preserveAspectRatio (contain/auto: the default meet, cover: slice,
// stretch: none).

use crate::ast::{Term, Value};
use crate::compile::Ctx;
use crate::diag::Diag;
use crate::scene::{Node, SheetModel};
use crate::style::single_term;
use crate::util::{base64, f4, hash8, xml_escape};
use std::path::{Path, PathBuf};

pub enum Payload {
    Href(String),
    Svg(String),
}

pub fn is_url(s: &str) -> bool {
    let l = s.to_ascii_lowercase();
    l.starts_with("http://") || l.starts_with("https://") || l.starts_with("data:")
}

pub fn resolve_path(file: &str, src: &str) -> PathBuf {
    let base = Path::new(file).parent().unwrap_or(Path::new(""));
    base.join(src)
}

fn sniff(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some("image/png")
    } else if bytes.starts_with(b"\xff\xd8\xff") {
        Some("image/jpeg")
    } else if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        Some("image/gif")
    } else if bytes.len() >= 12 && &bytes[0..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        Some("image/webp")
    } else {
        None
    }
}

// Read and classify a local image. Err carries the reason after the dash.
pub fn load(path: &Path) -> Result<Payload, String> {
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                return Err("no such file".to_string());
            }
            return Err(e.to_string());
        }
    };
    if let Some(mime) = sniff(&bytes) {
        return Ok(Payload::Href(format!("data:{};base64,{}", mime, base64(&bytes))));
    }
    if let Ok(text) = std::str::from_utf8(&bytes) {
        if svg_root(text).is_some() {
            return Ok(Payload::Svg(text.to_string()));
        }
    }
    Err("not an SVG or raster (PNG/JPEG/GIF/WebP)".to_string())
}

// Resolve-time check of `src:` (and the read itself).
pub fn check_src(sheet: &SheetModel, n: &Node, file: &str, opts: &crate::Options) -> Result<(), Diag> {
    let d = match crate::icon::winning_decl(sheet, n, "src") {
        Some(d) => d,
        None => return Ok(()),
    };
    let s = match single_term(&d.value) {
        Some(Term::Str(s, _)) => s.clone(),
        Some(Term::Ident(..)) => {
            return Err(Diag::error("resolve", "'src' takes a quoted string — write src: \"…\"", d.span));
        }
        _ => return Ok(()),
    };
    if is_url(&s) {
        return Ok(());
    }
    // a read failure points at the node's own `src:`, else at the node
    let span = if n.inline.iter().any(|x| std::ptr::eq(x, d)) { d.span } else { n.span };
    if opts.no_fs {
        return Err(Diag::error(
            "asset-no-fs",
            &format!("cannot read image '{}' — local files are off (--no-fs); use an http(s) URL or a data: URI", s),
            span,
        ));
    }
    match load(&resolve_path(file, &s)) {
        Ok(_) => Ok(()),
        Err(why) => Err(Diag::error("asset-not-found", &format!("cannot read image '{}' — {}", s, why), span)),
    }
}

// Before layout: a childless image needs both sides.
pub fn check_sizes(ctx: &Ctx) -> Result<(), Diag> {
    for (i, n) in ctx.nodes.iter().enumerate() {
        if n.prim == crate::types::Prim::Image && n.children.is_empty() {
            let c = &ctx.comp[i];
            if c.width.is_none() || c.height.is_none() {
                return Err(Diag::error("missing-required-property", "'|image|' requires 'width' and 'height'", n.span));
            }
        }
    }
    Ok(())
}

// No `.lini-image` rule is ever emitted, so the image type's own user rules
// are written inline: move them from the rule-level props into `own`.
// Returns the stroke width an image's dashes assume when none is set (0).
pub fn inline_type_rules(ctx: &Ctx, n: &Node, own: &mut Vec<(String, Value)>, rule_props: &mut Vec<(String, Value)>) -> f64 {
    let rules = ctx.sheet.type_rule("image");
    if !rules.is_empty() {
        for d in &rules {
            own.retain(|e| e.0 != d.name);
            own.push((d.name.clone(), d.value.clone()));
        }
        // rule-level props as the emitted CSS sees them: every rule but the image type's
        let mut props: Vec<(String, Value)> = Vec::new();
        let mut set = |k: &str, v: &Value| {
            if let Some(e) = props.iter_mut().find(|e| e.0 == k) {
                e.1 = v.clone();
            } else {
                props.push((k.to_string(), v.clone()));
            }
        };
        for t in n.chain.iter().rev() {
            for d in crate::style::type_defaults(t) {
                set(&d.name, &d.value);
            }
            if let Some(df) = ctx.sheet.define(t) {
                for d in &df.decls {
                    set(&d.name, &d.value);
                }
            }
            if t != "image" {
                for d in ctx.sheet.type_rule(t) {
                    set(&d.name, &d.value);
                }
            }
        }
        for c in &n.classes {
            if let Some(cr) = ctx.sheet.class(c) {
                for d in &cr.decls {
                    set(&d.name, &d.value);
                }
            }
        }
        *rule_props = props;
    }
    0.0
}

fn src_of(ctx: &Ctx, i: usize) -> Option<String> {
    match ctx.nodes[i].props.get("src").and_then(single_term) {
        Some(Term::Str(s, _)) => Some(s.clone()),
        _ => None,
    }
}

// The image element (unindented; an inlined SVG's content is emitted raw,
// its closing tag as the last line).
pub fn shape_lines(ctx: &Ctx, i: usize) -> Vec<String> {
    let src = match src_of(ctx, i) {
        Some(s) => s,
        None => return vec![],
    };
    let payload = if is_url(&src) {
        Payload::Href(src.clone())
    } else {
        match load(&resolve_path(&ctx.file, &src)) {
            Ok(p) => p,
            Err(_) => return vec![],
        }
    };
    let (w, h) = (ctx.nodes[i].w, ctx.nodes[i].h);
    let par = match crate::icon::fit_of(ctx, i) {
        "cover" => " preserveAspectRatio=\"xMidYMid slice\"",
        "stretch" => " preserveAspectRatio=\"none\"",
        _ => "",
    };
    let geo = format!("x=\"{}\" y=\"{}\" width=\"{}\" height=\"{}\"", f4(-w / 2.0), f4(-h / 2.0), f4(w), f4(h));
    match payload {
        Payload::Href(href) => vec![format!("<image href=\"{}\" {}{}/>", xml_escape(&href), geo, par)],
        Payload::Svg(text) => inline_svg(&text, &geo, par),
    }
}

// ------------------------------------------------------------------ SVG

struct Attr {
    name: String,
    value: String, // raw text between the quotes
}

struct Root {
    attrs: Vec<Attr>,
    inner: String,
}

fn skip_ws(s: &str, mut i: usize) -> usize {
    let b = s.as_bytes();
    while i < b.len() && (b[i] == b' ' || b[i] == b'\t' || b[i] == b'\n' || b[i] == b'\r') {
        i += 1;
    }
    i
}

// Parse the document down to its root `<svg>`: prolog, attributes, content.
fn svg_root(text: &str) -> Option<Root> {
    let s = text.strip_prefix('\u{feff}').unwrap_or(text);
    let mut i = 0;
    loop {
        i = skip_ws(s, i);
        let rest = &s[i..];
        if rest.starts_with("<?") {
            i += rest.find("?>")? + 2;
        } else if rest.starts_with("<!--") {
            i += rest.find("-->")? + 3;
        } else if rest.starts_with("<!") {
            // DOCTYPE, possibly with an internal subset
            let b = rest.as_bytes();
            let mut k = 2;
            let mut depth = 0;
            loop {
                if k >= b.len() {
                    return None;
                }
                match b[k] {
                    b'[' => depth += 1,
                    b']' => depth -= 1,
                    b'>' if depth <= 0 => break,
                    _ => {}
                }
                k += 1;
            }
            i += k + 1;
        } else {
            break;
        }
    }
    let rest = &s[i..];
    if !rest.starts_with("<svg") {
        return None;
    }
    let after = rest.as_bytes().get(4).copied();
    if !matches!(after, Some(b' ') | Some(b'\t') | Some(b'\n') | Some(b'\r') | Some(b'>') | Some(b'/')) {
        return None;
    }
    let b = rest.as_bytes();
    let mut k = 4;
    let mut attrs = Vec::new();
    let self_closing;
    loop {
        k = skip_ws(rest, k);
        if k >= b.len() {
            return None;
        }
        if b[k] == b'>' {
            self_closing = false;
            k += 1;
            break;
        }
        if b[k] == b'/' && b.get(k + 1) == Some(&b'>') {
            self_closing = true;
            k += 2;
            break;
        }
        let ns = k;
        while k < b.len() && !matches!(b[k], b'=' | b' ' | b'\t' | b'\n' | b'\r' | b'>' | b'/') {
            k += 1;
        }
        let name = rest[ns..k].to_string();
        if name.is_empty() {
            k += 1;
            continue;
        }
        k = skip_ws(rest, k);
        // a valueless attribute (`hidden`) is dropped
        if k < b.len() && b[k] == b'=' {
            k = skip_ws(rest, k + 1);
            let value;
            if k < b.len() && (b[k] == b'"' || b[k] == b'\'') {
                let q = b[k];
                let vs = k + 1;
                let mut e = vs;
                while e < b.len() && b[e] != q {
                    e += 1;
                }
                if e >= b.len() {
                    return None;
                }
                value = rest[vs..e].to_string();
                k = e + 1;
            } else {
                let vs = k;
                while k < b.len() && !matches!(b[k], b' ' | b'\t' | b'\n' | b'\r' | b'>') {
                    k += 1;
                }
                value = rest[vs..k].to_string();
            }
            attrs.push(Attr { name, value });
        }
    }
    let inner = if self_closing {
        String::new()
    } else {
        let body = &rest[k..];
        match body.rfind("</svg>") {
            Some(e) => body[..e].to_string(),
            None => body.to_string(),
        }
    };
    Some(Root { attrs, inner })
}

// A width/height usable for a synthesised viewBox: a plain number, optionally in px.
fn plain_len(v: &str) -> Option<String> {
    let t = v.trim();
    let t = t.strip_suffix("px").unwrap_or(t);
    if t.parse::<f64>().is_ok() && !t.is_empty() && !t.contains(|c: char| c.is_alphabetic()) {
        Some(t.to_string())
    } else {
        None
    }
}

fn attr_out(name: &str, value: &str) -> String {
    format!(" {}=\"{}\"", name, value.replace('"', "&quot;"))
}

// Rewrite `url(#id)` references to defined ids.
fn rewrite_urls(s: &str, ids: &[String], prefix: &str) -> String {
    let mut out = String::new();
    let mut rest = s;
    while let Some(p) = rest.find("url(") {
        out.push_str(&rest[..p + 4]);
        rest = &rest[p + 4..];
        let end = rest.find(')').unwrap_or(rest.len());
        let inner = &rest[..end];
        let lead = inner.len() - inner.trim_start_matches(|c: char| c == ' ' || c == '"' || c == '\'').len();
        let core = inner.trim_matches(|c: char| c == ' ' || c == '"' || c == '\'');
        if let Some(id) = core.strip_prefix('#') {
            if ids.iter().any(|x| x == id) {
                out.push_str(&inner[..lead]);
                out.push('#');
                out.push_str(prefix);
                out.push_str(id);
                out.push_str(&inner[lead + core.len()..]);
                rest = &rest[end..];
                continue;
            }
        }
        out.push_str(inner);
        rest = &rest[end..];
    }
    out.push_str(rest);
    out
}

fn rewrite_attr(name: &str, value: &str, ids: &[String], prefix: &str) -> String {
    if name == "id" {
        return format!("{}{}", prefix, value);
    }
    if name == "href" || name == "xlink:href" {
        if let Some(id) = value.strip_prefix('#') {
            if ids.iter().any(|x| x == id) {
                return format!("#{}{}", prefix, id);
            }
        }
    }
    rewrite_urls(value, ids, prefix)
}

// Collect every `id="…"` attribute in the content (outside comments).
fn collect_ids(content: &str, ids: &mut Vec<String>) {
    scan(content, &mut |tok: Tok| {
        if let Tok::Attr(name, value) = tok {
            if name == "id" {
                ids.push(value.to_string());
            }
        }
    });
}

enum Tok<'a> {
    Raw(&'a str),               // markup copied as is (tag names, comments, spacing)
    Text(&'a str),              // character data (and CDATA)
    Attr(&'a str, &'a str), // attribute name, raw value (between its quotes)
}

// A small XML scanner: splits content into raw markup, text and attribute values.
fn scan<'a>(s: &'a str, f: &mut dyn FnMut(Tok<'a>)) {
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if s[i..].starts_with("<!--") {
            let e = s[i..].find("-->").map(|p| i + p + 3).unwrap_or(b.len());
            f(Tok::Raw(&s[i..e]));
            i = e;
        } else if s[i..].starts_with("<![CDATA[") {
            f(Tok::Raw(&s[i..i + 9]));
            let e = s[i + 9..].find("]]>").map(|p| i + 9 + p).unwrap_or(b.len());
            f(Tok::Text(&s[i + 9..e]));
            let e2 = (e + 3).min(b.len());
            f(Tok::Raw(&s[e..e2]));
            i = e2;
        } else if b[i] == b'<' && (s[i..].starts_with("<?") || s[i..].starts_with("<!") || s[i..].starts_with("</")) {
            let e = s[i..].find('>').map(|p| i + p + 1).unwrap_or(b.len());
            f(Tok::Raw(&s[i..e]));
            i = e;
        } else if b[i] == b'<' {
            // start tag: name, then attributes
            let mut k = i + 1;
            while k < b.len() && !matches!(b[k], b' ' | b'\t' | b'\n' | b'\r' | b'>' | b'/') {
                k += 1;
            }
            f(Tok::Raw(&s[i..k]));
            loop {
                let ws = k;
                k = skip_ws(s, k);
                if k > ws {
                    f(Tok::Raw(&s[ws..k]));
                }
                if k >= b.len() {
                    break;
                }
                if b[k] == b'>' {
                    f(Tok::Raw(">"));
                    k += 1;
                    break;
                }
                if b[k] == b'/' {
                    f(Tok::Raw("/"));
                    k += 1;
                    continue;
                }
                let ns = k;
                while k < b.len() && !matches!(b[k], b'=' | b' ' | b'\t' | b'\n' | b'\r' | b'>' | b'/') {
                    k += 1;
                }
                let name = &s[ns..k];
                if name.is_empty() {
                    f(Tok::Raw(&s[k..k + 1]));
                    k += 1;
                    continue;
                }
                let mut j = skip_ws(s, k);
                if j < b.len() && b[j] == b'=' {
                    j = skip_ws(s, j + 1);
                    if j < b.len() && (b[j] == b'"' || b[j] == b'\'') {
                        let q = b[j];
                        let mut e = j + 1;
                        while e < b.len() && b[e] != q {
                            e += 1;
                        }
                        // name and everything up to the opening quote stay raw
                        f(Tok::Raw(&s[ns..j + 1]));
                        f(Tok::Attr(name, &s[j + 1..e.min(b.len())]));
                        let e2 = (e + 1).min(b.len());
                        f(Tok::Raw(&s[e.min(b.len())..e2]));
                        k = e2;
                        continue;
                    }
                }
                f(Tok::Raw(&s[ns..k]));
            }
            i = k;
        } else {
            let e = s[i..].find('<').map(|p| i + p).unwrap_or(b.len());
            f(Tok::Text(&s[i..e]));
            i = e;
        }
    }
}

fn inline_svg(text: &str, geo: &str, par: &str) -> Vec<String> {
    let root = match svg_root(text) {
        Some(r) => r,
        None => return vec![],
    };
    let prefix = format!("lini-a{}-", hash8(text));
    let mut ids: Vec<String> = root.attrs.iter().filter(|a| a.name == "id").map(|a| a.value.clone()).collect();
    collect_ids(&root.inner, &mut ids);
    let mut head = format!("<svg {}{}", geo, par);
    let has_vb = root.attrs.iter().any(|a| a.name == "viewBox");
    if !has_vb {
        let w = root.attrs.iter().find(|a| a.name == "width").and_then(|a| plain_len(&a.value));
        let h = root.attrs.iter().find(|a| a.name == "height").and_then(|a| plain_len(&a.value));
        if let (Some(w), Some(h)) = (w, h) {
            head.push_str(&format!(" viewBox=\"0 0 {} {}\"", w, h));
        }
    }
    for a in &root.attrs {
        if matches!(a.name.as_str(), "xmlns" | "width" | "height" | "x" | "y" | "preserveAspectRatio") {
            continue;
        }
        head.push_str(&attr_out(&a.name, &rewrite_attr(&a.name, &a.value, &ids, &prefix)));
    }
    head.push('>');
    let mut body = String::new();
    scan(&root.inner, &mut |tok: Tok| match tok {
        Tok::Raw(r) => body.push_str(r),
        Tok::Text(t) => body.push_str(&rewrite_urls(t, &ids, &prefix)),
        Tok::Attr(name, value) => body.push_str(&rewrite_attr(name, value, &ids, &prefix)),
    });
    let body = body.trim_matches('\n');
    if body.is_empty() {
        vec![head, "</svg>".to_string()]
    } else {
        vec![format!("{}\n{}", head, body), "</svg>".to_string()]
    }
}
