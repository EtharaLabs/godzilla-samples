//! `BasicFileInfo`: the block of `Key: value` lines (UTF-16LE, CR LF) that starts at `Worksharing:`.

pub struct BasicInfo {
    pub release: u32,
    pub build: Option<String>,
    pub document: Option<String>,
    pub locale: Option<String>,
    pub worksharing: Option<String>,
    pub username: Option<String>,
    pub last_save_path: Option<String>,
}

fn wide(s: &str) -> Vec<u8> {
    s.encode_utf16().flat_map(|c| c.to_le_bytes()).collect()
}

fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if needle.is_empty() || hay.len() < needle.len() {
        return None;
    }
    (from..=hay.len() - needle.len()).find(|&i| &hay[i..i + needle.len()] == needle)
}

fn decode_wide(b: &[u8]) -> String {
    let units: Vec<u16> = b.chunks_exact(2).map(|c| u16::from_le_bytes([c[0], c[1]])).collect();
    String::from_utf16_lossy(&units)
}

/// The block's lines as (key, value), in file order.
fn lines(data: &[u8]) -> Option<Vec<(String, String)>> {
    let start = find(data, &wide("Worksharing:"), 0)?;
    let crlf = wide("\r\n");
    let mut out = Vec::new();
    let mut pos = start;
    while pos < data.len() {
        let (line, next) = match find(data, &crlf, pos) {
            Some(e) => (&data[pos..e], e + crlf.len()),
            None => (&data[pos..], data.len()),
        };
        let text = decode_wide(line);
        if let Some(i) = text.find(": ") {
            out.push((text[..i].to_string(), text[i + 2..].to_string()));
        } else if let Some(k) = text.strip_suffix(':') {
            out.push((k.to_string(), String::new()));
        } else {
            out.push((text.clone(), String::new()));
        }
        pos = next;
    }
    Some(out)
}

fn year_of(s: &str) -> Option<u32> {
    let head: String = s.chars().take(4).collect();
    if head.chars().count() != 4 || !head.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let y: u32 = head.parse().ok()?;
    if (2000..=2100).contains(&y) {
        Some(y)
    } else {
        None
    }
}

pub fn parse(data: &[u8]) -> Result<BasicInfo, String> {
    let lines = match lines(data) {
        Some(l) => l,
        None => return Err("BasicFileInfo has no block of `Key: value` lines, so it is not what Revit writes".into()),
    };
    let get = |k: &str| -> Option<String> {
        lines.iter().find(|(kk, _)| kk == k).map(|(_, v)| v.trim().to_string())
    };
    let nonempty = |v: Option<String>| v.filter(|s| !s.is_empty());
    let format = get("Format");
    let revit_build = get("Revit Build");
    let mut release = format.as_deref().and_then(year_of);
    if release.is_none() {
        if let Some(rb) = &revit_build {
            if let Some(rest) = rb.strip_prefix("Autodesk Revit ") {
                release = year_of(rest);
            }
        }
    }
    let release = match release {
        Some(r) => r,
        None => return Err("BasicFileInfo names no release (no `Format` or `Revit Build` line with a year)".into()),
    };
    let mut build = nonempty(get("Build"));
    if build.is_none() {
        if let Some(rb) = &revit_build {
            if let Some(i) = rb.find("(Build: ") {
                let rest = &rb[i + "(Build: ".len()..];
                let b = rest.split(')').next().unwrap_or("").trim();
                if !b.is_empty() {
                    build = Some(format!("{}(x64)", b));
                }
            }
        }
    }
    Ok(BasicInfo {
        release,
        build,
        document: nonempty(get("Unique Document GUID")),
        locale: nonempty(get("Locale when saved")),
        worksharing: nonempty(get("Worksharing")),
        username: nonempty(get("Username")),
        last_save_path: nonempty(get("Last Save Path")),
    })
}
