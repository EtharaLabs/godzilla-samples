//! A small XML parser for E57's XML section: elements, attributes, text and CDATA; comments,
//! declarations and processing instructions passed over; no entities decoded. Capped in depth.

/// The deepest elements may nest.
pub const MAX_DEPTH: usize = 64;

#[derive(Clone, Debug, Default)]
pub struct Element {
    pub name: String,
    pub attrs: Vec<(String, String)>,
    /// The element's own text (its text and CDATA, not its children's), as written.
    pub text: String,
    pub children: Vec<Element>,
}

impl Element {
    pub fn attr(&self, k: &str) -> Option<&str> {
        self.attrs.iter().find(|(kk, _)| kk == k).map(|(_, v)| v.as_str())
    }
    pub fn child(&self, name: &str) -> Option<&Element> {
        self.children.iter().find(|c| c.name == name)
    }
}

fn find(s: &[u8], from: usize, needle: &[u8]) -> Option<usize> {
    if from > s.len() || s.len() - from < needle.len() {
        return None;
    }
    (from..=s.len() - needle.len()).find(|&i| &s[i..i + needle.len()] == needle)
}

fn lossy(b: &[u8]) -> String {
    String::from_utf8_lossy(b).into_owned()
}

/// XML's five named entities read as what they stand for (in one pass); any other `&` stays.
fn unescape(s: &str) -> String {
    if !s.contains('&') {
        return s.to_string();
    }
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(i) = rest.find('&') {
        out.push_str(&rest[..i]);
        rest = &rest[i..];
        let mut done = false;
        for (ent, ch) in [("&amp;", '&'), ("&lt;", '<'), ("&gt;", '>'), ("&quot;", '"'), ("&apos;", '\'')] {
            if rest.starts_with(ent) {
                out.push(ch);
                rest = &rest[ent.len()..];
                done = true;
                break;
            }
        }
        if !done {
            out.push('&');
            rest = &rest[1..];
        }
    }
    out.push_str(rest);
    out
}

fn is_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0c)
}

fn trim(mut b: &[u8]) -> &[u8] {
    while let Some((&f, rest)) = b.split_first() {
        if is_ws(f) {
            b = rest;
        } else {
            break;
        }
    }
    while let Some((&l, rest)) = b.split_last() {
        if is_ws(l) {
            b = rest;
        } else {
            break;
        }
    }
    b
}

fn trim_start(mut b: &[u8]) -> &[u8] {
    while let Some((&f, rest)) = b.split_first() {
        if is_ws(f) {
            b = rest;
        } else {
            break;
        }
    }
    b
}

/// A start tag's name and attributes, from what lies between `<` and `>` (less a closing `/`).
fn start_tag(inner: &[u8]) -> Option<Element> {
    let s = trim_start(inner);
    let name_end = s.iter().position(|b| is_ws(*b)).unwrap_or(s.len());
    let name = &s[..name_end];
    if name.is_empty() {
        return None;
    }
    let mut el = Element { name: lossy(name), ..Default::default() };
    let mut rest = &s[name_end..];
    loop {
        rest = trim_start(rest);
        if rest.is_empty() {
            break;
        }
        let eq = rest.iter().position(|b| *b == b'=')?;
        let key = trim(&rest[..eq]);
        rest = trim_start(&rest[eq + 1..]);
        let q = *rest.first()?;
        if q != b'"' && q != b'\'' {
            return None;
        }
        let close = rest[1..].iter().position(|b| *b == q)?;
        let value = &rest[1..1 + close];
        el.attrs.push((lossy(key), unescape(&lossy(value))));
        rest = &rest[close + 2..];
    }
    Some(el)
}

fn broken(what: String) -> String {
    format!("its XML is broken: {}", what)
}

/// The first element of a document, with what it holds.
pub fn parse(src: &[u8]) -> Result<Element, String> {
    let n = src.len();
    let mut stack: Vec<Element> = Vec::new();
    let mut root: Option<Element> = None;
    let mut i = 0;
    fn attach(stack: &mut [Element], root: &mut Option<Element>, el: Element) {
        if let Some(top) = stack.last_mut() {
            top.children.push(el);
        } else if root.is_none() {
            *root = Some(el);
        }
    }
    while i < n {
        if src[i] != b'<' {
            let end = src[i..].iter().position(|b| *b == b'<').map(|p| i + p).unwrap_or(n);
            if let Some(top) = stack.last_mut() {
                top.text.push_str(&unescape(&String::from_utf8_lossy(&src[i..end])));
            }
            i = end;
            continue;
        }
        if src[i..].starts_with(b"<!--") {
            let end = find(src, i + 4, b"-->").ok_or_else(|| broken("a comment isn't closed".into()))?;
            i = end + 3;
            continue;
        }
        if src[i..].starts_with(b"<![CDATA[") {
            let end = find(src, i + 9, b"]]>").ok_or_else(|| broken("a CDATA isn't closed".into()))?;
            if let Some(top) = stack.last_mut() {
                top.text.push_str(&String::from_utf8_lossy(&src[i + 9..end]));
            }
            i = end + 3;
            continue;
        }
        if src[i..].starts_with(b"<!") || src[i..].starts_with(b"<?") {
            let end = find(src, i + 2, b">").ok_or_else(|| broken("a declaration isn't closed".into()))?;
            i = end + 1;
            continue;
        }
        if src[i..].starts_with(b"</") {
            let end = find(src, i + 2, b">").ok_or_else(|| broken("an end tag isn't closed".into()))?;
            let name = lossy(trim(&src[i + 2..end]));
            let top = match stack.pop() {
                None => return Err(broken(format!("</{}> closes nothing", name))),
                Some(t) => t,
            };
            if top.name != name {
                return Err(broken(format!("<{}> is closed by </{}>", top.name, name)));
            }
            attach(&mut stack, &mut root, top);
            i = end + 1;
            continue;
        }
        // a start tag: its end is the first `>` outside quotes
        let mut q: Option<u8> = None;
        let mut end = None;
        for (j, &b) in src.iter().enumerate().skip(i + 1) {
            match q {
                Some(c) => {
                    if b == c {
                        q = None;
                    }
                }
                None => {
                    if b == b'"' || b == b'\'' {
                        q = Some(b);
                    } else if b == b'>' {
                        end = Some(j);
                        break;
                    }
                }
            }
        }
        let end = end.ok_or_else(|| broken("a tag isn't closed".into()))?;
        let content = &src[i + 1..end];
        let self_closing = content.last() == Some(&b'/');
        let inner = if self_closing { &content[..content.len() - 1] } else { content };
        let el = start_tag(inner).ok_or_else(|| broken(format!("<{}>", lossy(inner))))?;
        if self_closing {
            attach(&mut stack, &mut root, el);
        } else {
            stack.push(el);
            if stack.len() > MAX_DEPTH {
                return Err(format!("its XML nests deeper than {}", MAX_DEPTH));
            }
        }
        i = end + 1;
    }
    if let Some(top) = stack.last() {
        return Err(broken(format!("<{}> isn't closed", top.name)));
    }
    root.ok_or_else(|| broken("it has no root element".into()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn err(s: &str) -> String {
        parse(s.as_bytes()).unwrap_err()
    }

    #[test]
    fn reads_what_e57_writes() {
        let r = parse(b"<?xml version=\"1.0\"?><!-- c --><r a='1' b=\"x &amp; y\"><n><![CDATA[s & t]]></n><e/>t</r>").unwrap();
        assert_eq!(r.name, "r");
        assert_eq!(r.attr("b"), Some("x & y"));
        assert_eq!(r.child("n").unwrap().text, "s & t");
        assert_eq!(r.children.len(), 2);
        assert_eq!(r.text, "t");
    }

    #[test]
    fn says_how_it_is_broken() {
        assert_eq!(err("<a></b>"), "its XML is broken: <a> is closed by </b>");
        assert_eq!(err("<a></a></x>"), "its XML is broken: </x> closes nothing");
        assert_eq!(err("<a>< ></a>"), "its XML is broken: < >");
        assert_eq!(err("<a>"), "its XML is broken: <a> isn't closed");
        assert_eq!(err("<a"), "its XML is broken: a tag isn't closed");
        assert_eq!(err("<!-- c"), "its XML is broken: a comment isn't closed");
        assert_eq!(err("  "), "its XML is broken: it has no root element");
        assert_eq!(err(&"<a>".repeat(65)), "its XML nests deeper than 64");
        assert!(parse("<a>".repeat(64).as_bytes()).is_err());
    }
}
