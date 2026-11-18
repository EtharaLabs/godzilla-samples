//! Whether a linked drawing's DXF file, read again on opening, is one the original takes: an
//! ASCII DXF of group codes and values, with an ENTITIES section that draws something in model
//! space, its numbers numbers a drawing holds. What it says of one it doesn't take.

type R<T> = Result<T, String>;

/// A group code and its value, with the lines they are on.
struct Pair<'a> {
    code: i64,
    value: &'a str,
    value_line: usize,
}

/// The most a coordinate (or any number) of a drawing may be, either way.
const MAX: f64 = 1e12;

pub fn check(bytes: &[u8]) -> R<()> {
    if bytes.starts_with(b"AutoCAD Binary DXF") {
        return Err("it's a binary DXF; save it as an ASCII DXF (any version) and bring that in".into());
    }
    // UTF-8, else each byte a character
    let text: String = match std::str::from_utf8(bytes) {
        Ok(t) => t.to_string(),
        Err(_) => bytes.iter().map(|&b| b as char).collect(),
    };
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
    let lines: Vec<&str> = text.lines().collect();
    let mut pairs = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        let c = lines[i].trim();
        if c.is_empty() {
            i += 1;
            continue;
        }
        let code: i64 = c.parse().map_err(|_| format!("line {}: `{}` isn't a group code", i + 1, c))?;
        if i + 1 >= lines.len() {
            return Err(format!("line {}: the file ends after group code {}, with no value", i + 1, code));
        }
        pairs.push(Pair { code, value: lines[i + 1], value_line: i + 2 });
        i += 2;
    }
    // the sections, each to its ENDSEC
    let mut entities: Vec<&[Pair]> = Vec::new();
    let mut blocks: Vec<&[Pair]> = Vec::new();
    let is = |p: &Pair, code: i64, v: &str| p.code == code && p.value.trim() == v;
    let mut k = 0;
    while k < pairs.len() {
        if !is(&pairs[k], 0, "SECTION") {
            k += 1;
            continue;
        }
        let name = match pairs.get(k + 1) {
            Some(p) if p.code == 2 => p.value.trim(),
            Some(p) => return Err(format!("line {}: a SECTION with no name", p.value_line)),
            None => return Err(format!("line {}: a SECTION with no name", pairs[k].value_line + 1)),
        };
        let start = k + 2;
        let mut end = start;
        while end < pairs.len() && !is(&pairs[end], 0, "ENDSEC") {
            end += 1;
        }
        match name {
            "ENTITIES" => entities.push(&pairs[start.min(end)..end]),
            "BLOCKS" => blocks.push(&pairs[start.min(end)..end]),
            _ => {}
        }
        k = end + 1;
    }
    if entities.is_empty() {
        return Err("it isn't a DXF: there's no ENTITIES section".into());
    }
    let blocks: Vec<(String, Vec<Entity>)> = blocks.iter().flat_map(|b| block_list(b)).collect();
    let mut draws = false;
    for sec in &entities {
        let list = split(sec);
        for (n, e) in list.iter().enumerate() {
            e.numbers()?;
            if !draws && e.int(67) != Some(1) && e.draws(&list[n + 1..], &blocks, 0) {
                draws = true;
            }
        }
    }
    if !draws {
        return Err("it draws nothing in model space".into());
    }
    Ok(())
}

/// An entity: its kind, the line its kind is on, and its group codes.
struct Entity<'a> {
    kind: &'a str,
    line: usize,
    codes: Vec<&'a Pair<'a>>,
}

/// The kinds the original reads (the others it passes over).
const KNOWN: &[&str] = &[
    "LINE", "POINT", "CIRCLE", "ARC", "ELLIPSE", "LWPOLYLINE", "POLYLINE", "VERTEX", "SPLINE", "TEXT", "MTEXT", "INSERT",
    "SOLID", "TRACE", "HATCH", "DIMENSION",
];

fn split<'a>(pairs: &'a [Pair<'a>]) -> Vec<Entity<'a>> {
    let mut out: Vec<Entity> = Vec::new();
    for p in pairs {
        if p.code == 0 {
            out.push(Entity { kind: p.value.trim(), line: p.value_line, codes: Vec::new() });
        } else if let Some(e) = out.last_mut() {
            e.codes.push(p);
        }
    }
    out
}

/// The blocks of a BLOCKS section: each BLOCK's name and its entities, to its ENDBLK.
fn block_list<'a>(pairs: &'a [Pair<'a>]) -> Vec<(String, Vec<Entity<'a>>)> {
    let all = split(pairs);
    let mut out: Vec<(String, Vec<Entity>)> = Vec::new();
    let mut cur: Option<(String, Vec<Entity>)> = None;
    for e in all {
        match e.kind {
            "BLOCK" => {
                if let Some(b) = cur.take() {
                    out.push(b);
                }
                let name = e.codes.iter().find(|p| p.code == 2).map(|p| p.value.trim().to_string()).unwrap_or_default();
                cur = Some((name, Vec::new()));
            }
            "ENDBLK" => {
                if let Some(b) = cur.take() {
                    out.push(b);
                }
            }
            _ => {
                if let Some(b) = cur.as_mut() {
                    b.1.push(e);
                }
            }
        }
    }
    if let Some(b) = cur.take() {
        out.push(b);
    }
    out
}

fn float_code(c: i64) -> bool {
    matches!(c, 10..=59 | 110..=149 | 210..=239 | 1010..=1059)
}

fn int_code(c: i64) -> bool {
    matches!(c, 60..=99 | 160..=179 | 270..=289 | 370..=389 | 400..=409 | 420..=429 | 440..=459 | 1060..=1071)
}

impl<'a> Entity<'a> {
    fn known(&self) -> bool {
        KNOWN.contains(&self.kind)
    }
    /// Its numbers read: those every entity has (its colour, its space…), and for a kind the
    /// original reads, all of them.
    fn numbers(&self) -> R<()> {
        for p in &self.codes {
            let common = matches!(p.code, 62 | 67 | 370 | 420 | 440);
            if !(common || self.known()) {
                continue;
            }
            let v = p.value.trim();
            if float_code(p.code) {
                let x: f64 = v.parse().map_err(|_| format!("line {}: `{}` isn't a number", self.line, v))?;
                if !x.is_finite() {
                    return Err(format!("line {}: `{}` isn't a number a drawing can hold", self.line, v));
                }
                if x.abs() > MAX {
                    return Err(format!("line {}: {} is past what a drawing holds (1000000000000)", self.line, v));
                }
            } else if int_code(p.code) {
                v.parse::<i64>().map_err(|_| format!("line {}: `{}` isn't a number", self.line, v))?;
            }
        }
        Ok(())
    }
    fn has(&self, c: i64) -> bool {
        self.codes.iter().any(|p| p.code == c)
    }
    fn num(&self, c: i64) -> Option<f64> {
        self.codes.iter().find(|p| p.code == c).and_then(|p| p.value.trim().parse().ok())
    }
    fn int(&self, c: i64) -> Option<i64> {
        self.codes.iter().find(|p| p.code == c).and_then(|p| p.value.trim().parse().ok())
    }
    fn count(&self, c: i64) -> usize {
        self.codes.iter().filter(|p| p.code == c).count()
    }
    fn text(&self) -> String {
        self.codes.iter().filter(|p| p.code == 1 || p.code == 3).map(|p| p.value).collect::<Vec<_>>().join("")
    }
    /// Whether it draws something (`after`: the entities after it, for a polyline's vertices).
    fn draws(&self, after: &[Entity], blocks: &[(String, Vec<Entity>)], depth: usize) -> bool {
        let at = |x: i64| self.has(x) && self.has(x + 10);
        match self.kind {
            "LINE" => at(10) && at(11),
            "POINT" => at(10),
            "CIRCLE" | "ARC" => self.num(40).map(|r| r > 0.0).unwrap_or(false),
            "ELLIPSE" => at(10) && at(11),
            "LWPOLYLINE" => self.count(10) >= 2,
            "POLYLINE" => after.iter().take_while(|e| e.kind == "VERTEX").count() >= 2,
            "SPLINE" => self.count(10) >= 2 || self.count(11) >= 2,
            "TEXT" | "MTEXT" => !self.text().trim().is_empty() && self.num(40).map(|h| h > 0.0).unwrap_or(false),
            "SOLID" | "TRACE" => at(10),
            "HATCH" => self.int(91).map(|n| n > 0).unwrap_or(false),
            "INSERT" | "DIMENSION" => {
                if depth > 16 {
                    return false;
                }
                let name = self.codes.iter().find(|p| p.code == 2).map(|p| p.value.trim()).unwrap_or("");
                blocks.iter().filter(|(n, _)| n == name).any(|(_, es)| {
                    es.iter().enumerate().any(|(i, e)| e.int(67) != Some(1) && e.draws(&es[i + 1..], blocks, depth + 1))
                })
            }
            _ => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::check;

    fn ents(body: &str) -> String {
        format!("0\nSECTION\n2\nENTITIES\n{}0\nENDSEC\n0\nEOF\n", body)
    }

    const LINE: &str = "0\nLINE\n8\nW\n10\n0\n20\n0\n11\n100\n21\n0\n";

    #[test]
    fn what_the_original_says_of_broken_drawings() {
        assert_eq!(check(ents(LINE).as_bytes()), Ok(()));
        assert_eq!(check(b"garbage"), Err("line 1: `garbage` isn't a group code".into()));
        assert_eq!(check(b""), Err("it isn't a DXF: there's no ENTITIES section".into()));
        assert_eq!(check(ents("").as_bytes()), Err("it draws nothing in model space".into()));
        assert_eq!(check(b"0\nSECTION\n2\nENTITIES\n0"), Err("line 5: the file ends after group code 0, with no value".into()));
        assert_eq!(check(b"0\nSECTION\n0\nENDSEC\n"), Err("line 4: a SECTION with no name".into()));
        assert_eq!(check(b"0\nSECTION\n"), Err("line 3: a SECTION with no name".into()));
        let bad = |from: &str, to: &str| check(ents(&LINE.replace(from, to)).as_bytes());
        assert_eq!(bad("10\n0\n", "10\nabc\n"), Err("line 6: `abc` isn't a number".into()));
        assert_eq!(bad("10\n0\n", "10\n1e20\n"), Err("line 6: 1e20 is past what a drawing holds (1000000000000)".into()));
        assert_eq!(bad("10\n0\n", "10\nnan\n"), Err("line 6: `nan` isn't a number a drawing can hold".into()));
        assert_eq!(
            check(b"AutoCAD Binary DXF\r\n\x1a\x00"),
            Err("it's a binary DXF; save it as an ASCII DXF (any version) and bring that in".into())
        );
    }

    #[test]
    fn what_draws_nothing() {
        // a line without its end, a circle of no radius, blank text, paper space
        for body in [
            "0\nLINE\n8\nW\n10\n0\n20\n0\n",
            "0\nCIRCLE\n8\nW\n10\n0\n20\n0\n40\n0\n",
            "0\nTEXT\n8\nW\n10\n0\n20\n0\n40\n2.5\n1\n   \n",
            "0\nLINE\n8\nW\n67\n1\n10\n0\n20\n0\n11\n100\n21\n0\n",
            "0\nINSERT\n8\nW\n2\nNOBLOCK\n10\n0\n20\n0\n",
        ] {
            assert_eq!(check(ents(body).as_bytes()), Err("it draws nothing in model space".into()), "{}", body);
        }
    }
}
