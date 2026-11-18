// Colour maths: OKLCH → sRGB hex.

pub fn oklch_to_srgb(l: f64, c: f64, h: f64) -> (f64, f64, f64) {
    let hr = h.to_radians();
    let a = c * hr.cos();
    let b = c * hr.sin();
    oklab_to_srgb(l, a, b)
}

pub fn oklab_to_srgb(l: f64, a: f64, b: f64) -> (f64, f64, f64) {
    let l_ = l + 0.3963377774 * a + 0.2158037573 * b;
    let m_ = l - 0.1055613458 * a - 0.0638541728 * b;
    let s_ = l - 0.0894841775 * a - 1.2914855480 * b;
    let l3 = l_ * l_ * l_;
    let m3 = m_ * m_ * m_;
    let s3 = s_ * s_ * s_;
    let r = 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3;
    let g = -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3;
    let bb = -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3;
    (gamma(r), gamma(g), gamma(bb))
}

fn gamma(x: f64) -> f64 {
    if x <= 0.0031308 {
        12.92 * x
    } else {
        1.055 * x.powf(1.0 / 2.4) - 0.055
    }
}

pub fn to_byte(x: f64) -> u8 {
    (x.clamp(0.0, 1.0) * 255.0).round() as u8
}

pub fn oklch_hex(l: f64, c: f64, h: f64, alpha: Option<f64>) -> String {
    let (r, g, b) = oklch_to_srgb(l, c, h);
    match alpha {
        Some(a) if a < 1.0 => format!("#{:02x}{:02x}{:02x}{:02x}", to_byte(r), to_byte(g), to_byte(b), to_byte(a)),
        _ => format!("#{:02x}{:02x}{:02x}", to_byte(r), to_byte(g), to_byte(b)),
    }
}
