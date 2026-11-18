//! PTS and XYZ text: a point a line, `x y z`, then an intensity, a colour (`r g b`), or both,
//! by spaces, tabs or commas; blank lines and `#` or `//` comments passed over. A PTS file's
//! lines of one number (its count, a station's) are passed over too.

use super::read::{Raw, Source};

pub struct Text<'a> {
    data: &'a [u8],
    pts: bool,
}

impl<'a> Text<'a> {
    pub fn new(data: &'a [u8], pts: bool) -> Text<'a> {
        Text { data, pts }
    }
}

impl<'a> Source for Text<'a> {
    fn unit_rule(&self) -> bool {
        true
    }
    fn each(&mut self, f: &mut dyn FnMut(&Raw) -> Result<(), String>) -> Result<(), String> {
        let mut vals: Vec<f64> = Vec::with_capacity(8);
        for (k, line) in self.data.split(|b| *b == b'\n').enumerate() {
            let no = k + 1;
            let s = std::str::from_utf8(line).map_err(|_| format!("line {} isn't text", no))?;
            let t = s.trim();
            if t.is_empty() || t.starts_with('#') || t.starts_with("//") {
                continue;
            }
            vals.clear();
            let mut first = "";
            for tok in t.split(|c: char| c.is_whitespace() || c == ',').filter(|x| !x.is_empty()) {
                let v: f64 = tok.parse().map_err(|_| format!("line {}: {} isn't a number", no, tok))?;
                if !v.is_finite() {
                    return Err(format!("line {}: {} isn't a number BIMCraft can place", no, tok));
                }
                if vals.is_empty() {
                    first = tok;
                }
                vals.push(v);
            }
            // a PTS file counts its points (or a station's) on a line of their own
            if self.pts && vals.len() == 1 && first.parse::<u64>().is_ok() {
                continue;
            }
            let p = [vals.first().copied().unwrap_or(0.0), vals.get(1).copied().unwrap_or(0.0), vals.get(2).copied().unwrap_or(0.0)];
            let raw = match vals.len() {
                3 => Raw { p, ..Default::default() },
                4 => Raw { p, intensity: Some(vals[3]), ..Default::default() },
                6 => Raw { p, rgb: Some([vals[3], vals[4], vals[5]]), ..Default::default() },
                7 => Raw { p, intensity: Some(vals[3]), rgb: Some([vals[4], vals[5], vals[6]]), ..Default::default() },
                n => {
                    return Err(format!(
                        "line {}: {} columns; a point is x y z, then an intensity, a colour (r g b), or both",
                        no, n
                    ))
                }
            };
            f(&raw)?;
        }
        Ok(())
    }
}
