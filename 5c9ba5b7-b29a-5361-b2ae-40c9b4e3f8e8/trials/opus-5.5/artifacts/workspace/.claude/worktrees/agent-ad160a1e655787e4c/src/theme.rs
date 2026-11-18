// Built-in themes: the palette as `--lini-*` custom properties.

use std::collections::HashMap;

pub static DEFAULT_CSS: &str = include_str!("../data/themes/default.css");
pub static LIGHT_CSS: &str = include_str!("../data/themes/light.css");
pub static DARK_CSS: &str = include_str!("../data/themes/dark.css");
pub static HC_CSS: &str = include_str!("../data/themes/high-contrast.css");
pub static BLUEPRINT_CSS: &str = include_str!("../data/themes/blueprint.css");
pub static LIST: &str = include_str!("../data/themes/list.txt");

pub const FONT_FAMILY: &str =
    "\"Google Sans\", system-ui, -apple-system, \"Segoe UI\", Roboto, \"Helvetica Neue\", Arial, sans-serif";

pub const NAMES: &[&str] = &["default", "light", "dark", "high-contrast", "blueprint"];

pub fn css_of(name: &str) -> Option<&'static str> {
    match name {
        "default" => Some(DEFAULT_CSS),
        "light" => Some(LIGHT_CSS),
        "dark" => Some(DARK_CSS),
        "high-contrast" => Some(HC_CSS),
        "blueprint" => Some(BLUEPRINT_CSS),
        _ => None,
    }
}

// Split "light-dark(a, b)" at its top-level comma.
pub fn split_light_dark(v: &str) -> Option<(String, String)> {
    let inner = v.strip_prefix("light-dark(")?.strip_suffix(')')?;
    let mut depth = 0;
    for (i, c) in inner.char_indices() {
        match c {
            '(' => depth += 1,
            ')' => depth -= 1,
            ',' if depth == 0 => {
                return Some((inner[..i].trim().to_string(), inner[i + 1..].trim().to_string()));
            }
            _ => {}
        }
    }
    None
}

#[derive(Clone, Debug)]
pub struct Theme {
    pub pair: bool,
    // var name (without --lini-) → (light, dark)
    pub vars: HashMap<String, (String, String)>,
}

pub fn parse_theme_css(css: &str) -> HashMap<String, (String, String)> {
    let mut m = HashMap::new();
    for line in css.lines() {
        let l = line.trim();
        if let Some(rest) = l.strip_prefix("--lini-") {
            if let Some(colon) = rest.find(':') {
                let name = rest[..colon].to_string();
                let val = rest[colon + 1..].trim().trim_end_matches(';').trim().to_string();
                let pair = split_light_dark(&val).unwrap_or((val.clone(), val.clone()));
                m.insert(name, pair);
            }
        }
    }
    m.insert("font-family".to_string(), (FONT_FAMILY.to_string(), FONT_FAMILY.to_string()));
    m
}

pub fn builtin(name: &str) -> Option<Theme> {
    let css = css_of(name)?;
    let pair = name == "default" || name == "high-contrast";
    Some(Theme { pair, vars: parse_theme_css(css) })
}

pub fn resolve(spec: &str) -> Option<Theme> {
    if let Some((a, b)) = spec.split_once('/') {
        let ta = builtin(a)?;
        let tb = builtin(b)?;
        let mut vars = HashMap::new();
        for (k, (l, _)) in &ta.vars {
            let d = tb.vars.get(k).map(|x| x.1.clone()).unwrap_or_else(|| l.clone());
            vars.insert(k.clone(), (l.clone(), d));
        }
        return Some(Theme { pair: true, vars });
    }
    builtin(spec)
}

impl Theme {
    pub fn css_value(&self, var: &str) -> Option<String> {
        let (l, d) = self.vars.get(var)?;
        if !self.pair || l == d {
            if !self.pair {
                return Some(l.clone());
            }
            return Some(l.clone());
        }
        Some(format!("light-dark({}, {})", l, d))
    }
    // the light-side literal value (for --static baking)
    pub fn light_value(&self, var: &str) -> Option<String> {
        self.vars.get(var).map(|x| x.0.clone())
    }
}
