// SVG path data: parsing and exact bounding boxes.

#[derive(Clone, Copy, Debug)]
pub struct BBox {
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

impl BBox {
    pub fn empty() -> BBox {
        BBox { x0: f64::INFINITY, y0: f64::INFINITY, x1: f64::NEG_INFINITY, y1: f64::NEG_INFINITY }
    }
    pub fn add(&mut self, x: f64, y: f64) {
        self.x0 = self.x0.min(x);
        self.y0 = self.y0.min(y);
        self.x1 = self.x1.max(x);
        self.y1 = self.y1.max(y);
    }
    pub fn is_empty(&self) -> bool {
        self.x0 > self.x1
    }
    pub fn w(&self) -> f64 {
        if self.is_empty() {
            0.0
        } else {
            self.x1 - self.x0
        }
    }
    pub fn h(&self) -> f64 {
        if self.is_empty() {
            0.0
        } else {
            self.y1 - self.y0
        }
    }
    pub fn cx(&self) -> f64 {
        if self.is_empty() {
            0.0
        } else {
            (self.x0 + self.x1) / 2.0
        }
    }
    pub fn cy(&self) -> f64 {
        if self.is_empty() {
            0.0
        } else {
            (self.y0 + self.y1) / 2.0
        }
    }
}

fn tokenize(d: &str) -> Vec<String> {
    let mut out = Vec::new();
    let b: Vec<char> = d.chars().collect();
    let mut i = 0;
    while i < b.len() {
        let c = b[i];
        if c.is_ascii_alphabetic() && c != 'e' && c != 'E' {
            out.push(c.to_string());
            i += 1;
        } else if c.is_ascii_digit() || c == '-' || c == '+' || c == '.' {
            let st = i;
            let mut seen_dot = c == '.';
            i += 1;
            while i < b.len() {
                let d = b[i];
                if d.is_ascii_digit() {
                    i += 1;
                } else if d == '.' && !seen_dot {
                    seen_dot = true;
                    i += 1;
                } else if (d == 'e' || d == 'E') && i + 1 < b.len() {
                    i += 1;
                    if b[i] == '-' || b[i] == '+' {
                        i += 1;
                    }
                } else {
                    break;
                }
            }
            out.push(b[st..i].iter().collect());
        } else {
            i += 1;
        }
    }
    out
}

fn quad_extrema(p0: f64, p1: f64, p2: f64) -> Vec<f64> {
    let den = p0 - 2.0 * p1 + p2;
    if den.abs() < 1e-12 {
        return vec![];
    }
    let t = (p0 - p1) / den;
    if t > 0.0 && t < 1.0 {
        vec![t]
    } else {
        vec![]
    }
}

fn cubic_extrema(p0: f64, p1: f64, p2: f64, p3: f64) -> Vec<f64> {
    let a = -p0 + 3.0 * p1 - 3.0 * p2 + p3;
    let b = 2.0 * (p0 - 2.0 * p1 + p2);
    let c = p1 - p0;
    let mut ts = Vec::new();
    if a.abs() < 1e-12 {
        if b.abs() > 1e-12 {
            ts.push(-c / b);
        }
    } else {
        let disc = b * b - 4.0 * a * c;
        if disc >= 0.0 {
            let s = disc.sqrt();
            ts.push((-b + s) / (2.0 * a));
            ts.push((-b - s) / (2.0 * a));
        }
    }
    ts.into_iter().filter(|t| *t > 0.0 && *t < 1.0).collect()
}

fn cubic_at(p0: f64, p1: f64, p2: f64, p3: f64, t: f64) -> f64 {
    let mt = 1.0 - t;
    mt * mt * mt * p0 + 3.0 * mt * mt * t * p1 + 3.0 * mt * t * t * p2 + t * t * t * p3
}

fn quad_at(p0: f64, p1: f64, p2: f64, t: f64) -> f64 {
    let mt = 1.0 - t;
    mt * mt * p0 + 2.0 * mt * t * p1 + t * t * p2
}

pub fn arc_bbox(bb: &mut BBox, x1: f64, y1: f64, rx: f64, ry: f64, phi_deg: f64, large: bool, sweep: bool, x2: f64, y2: f64) {
    bb.add(x2, y2);
    if rx == 0.0 || ry == 0.0 {
        return;
    }
    let (mut rx, mut ry) = (rx.abs(), ry.abs());
    let phi = phi_deg.to_radians();
    let (cp, sp) = (phi.cos(), phi.sin());
    let dx = (x1 - x2) / 2.0;
    let dy = (y1 - y2) / 2.0;
    let x1p = cp * dx + sp * dy;
    let y1p = -sp * dx + cp * dy;
    let lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry);
    if lam > 1.0 {
        rx *= lam.sqrt();
        ry *= lam.sqrt();
    }
    let num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
    let den = rx * rx * y1p * y1p + ry * ry * x1p * x1p;
    let mut co = if den == 0.0 { 0.0 } else { (num / den).max(0.0).sqrt() };
    if large == sweep {
        co = -co;
    }
    let cxp = co * rx * y1p / ry;
    let cyp = -co * ry * x1p / rx;
    let cx = cp * cxp - sp * cyp + (x1 + x2) / 2.0;
    let cy = sp * cxp + cp * cyp + (y1 + y2) / 2.0;
    let ang = |ux: f64, uy: f64, vx: f64, vy: f64| -> f64 {
        let d = (ux * vx + uy * vy) / ((ux * ux + uy * uy).sqrt() * (vx * vx + vy * vy).sqrt());
        let a = d.clamp(-1.0, 1.0).acos();
        if ux * vy - uy * vx < 0.0 {
            -a
        } else {
            a
        }
    };
    let th1 = ang(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry);
    let mut dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
    if !sweep && dth > 0.0 {
        dth -= 2.0 * std::f64::consts::PI;
    } else if sweep && dth < 0.0 {
        dth += 2.0 * std::f64::consts::PI;
    }
    // arcs bound by 24 samples along the sweep (not their exact extremes)
    for k in 1..24 {
        let t = th1 + dth * k as f64 / 24.0;
        let x = cx + rx * t.cos() * cp - ry * t.sin() * sp;
        let y = cy + rx * t.cos() * sp + ry * t.sin() * cp;
        bb.add(x, y);
    }
}

pub fn path_bbox(d: &str) -> BBox {
    let toks = tokenize(d);
    let mut bb = BBox::empty();
    let mut i = 0;
    let (mut cx, mut cy) = (0.0f64, 0.0f64);
    let (mut sx, mut sy) = (0.0f64, 0.0f64);
    let mut last_ctrl: Option<(f64, f64)> = None;
    let mut last_q: Option<(f64, f64)> = None;
    let mut cmd = 'M';
    let num = |i: &mut usize| -> f64 {
        let v = toks.get(*i).and_then(|s| s.parse::<f64>().ok()).unwrap_or(0.0);
        *i += 1;
        v
    };
    while i < toks.len() {
        if toks[i].chars().next().map(|c| c.is_ascii_alphabetic()).unwrap_or(false) {
            cmd = toks[i].chars().next().unwrap();
            i += 1;
            if cmd == 'Z' || cmd == 'z' {
                cx = sx;
                cy = sy;
                last_ctrl = None;
                last_q = None;
                continue;
            }
        }
        if i >= toks.len() {
            break;
        }
        let rel = cmd.is_ascii_lowercase();
        let (ox, oy) = if rel { (cx, cy) } else { (0.0, 0.0) };
        match cmd.to_ascii_uppercase() {
            'M' => {
                let x = num(&mut i) + ox;
                let y = num(&mut i) + oy;
                cx = x;
                cy = y;
                sx = x;
                sy = y;
                bb.add(x, y);
                cmd = if rel { 'l' } else { 'L' };
                last_ctrl = None;
                last_q = None;
            }
            'L' => {
                let x = num(&mut i) + ox;
                let y = num(&mut i) + oy;
                cx = x;
                cy = y;
                bb.add(x, y);
                last_ctrl = None;
                last_q = None;
            }
            'H' => {
                let x = num(&mut i) + ox;
                cx = x;
                bb.add(cx, cy);
                last_ctrl = None;
                last_q = None;
            }
            'V' => {
                let y = num(&mut i) + oy;
                cy = y;
                bb.add(cx, cy);
                last_ctrl = None;
                last_q = None;
            }
            'C' | 'S' => {
                let (x1, y1) = if cmd.to_ascii_uppercase() == 'C' {
                    (num(&mut i) + ox, num(&mut i) + oy)
                } else {
                    match last_ctrl {
                        Some((lx, ly)) => (2.0 * cx - lx, 2.0 * cy - ly),
                        None => (cx, cy),
                    }
                };
                let x2 = num(&mut i) + ox;
                let y2 = num(&mut i) + oy;
                let x = num(&mut i) + ox;
                let y = num(&mut i) + oy;
                bb.add(x, y);
                for t in cubic_extrema(cx, x1, x2, x) {
                    bb.add(cubic_at(cx, x1, x2, x, t), cubic_at(cy, y1, y2, y, t));
                }
                for t in cubic_extrema(cy, y1, y2, y) {
                    bb.add(cubic_at(cx, x1, x2, x, t), cubic_at(cy, y1, y2, y, t));
                }
                last_ctrl = Some((x2, y2));
                last_q = None;
                cx = x;
                cy = y;
            }
            'Q' | 'T' => {
                let (x1, y1) = if cmd.to_ascii_uppercase() == 'Q' {
                    (num(&mut i) + ox, num(&mut i) + oy)
                } else {
                    match last_q {
                        Some((lx, ly)) => (2.0 * cx - lx, 2.0 * cy - ly),
                        None => (cx, cy),
                    }
                };
                let x = num(&mut i) + ox;
                let y = num(&mut i) + oy;
                bb.add(x, y);
                for t in quad_extrema(cx, x1, x) {
                    bb.add(quad_at(cx, x1, x, t), quad_at(cy, y1, y, t));
                }
                for t in quad_extrema(cy, y1, y) {
                    bb.add(quad_at(cx, x1, x, t), quad_at(cy, y1, y, t));
                }
                last_q = Some((x1, y1));
                last_ctrl = None;
                cx = x;
                cy = y;
            }
            'A' => {
                let rx = num(&mut i);
                let ry = num(&mut i);
                let rot = num(&mut i);
                let large = num(&mut i) != 0.0;
                let sweep = num(&mut i) != 0.0;
                let x = num(&mut i) + ox;
                let y = num(&mut i) + oy;
                arc_bbox(&mut bb, cx, cy, rx, ry, rot, large, sweep, x, y);
                cx = x;
                cy = y;
                last_ctrl = None;
                last_q = None;
            }
            _ => {
                i += 1;
            }
        }
    }
    bb
}
