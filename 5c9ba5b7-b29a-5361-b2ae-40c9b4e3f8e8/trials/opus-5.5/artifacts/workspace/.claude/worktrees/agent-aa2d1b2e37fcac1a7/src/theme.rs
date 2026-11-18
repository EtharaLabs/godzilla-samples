// Built-in themes: the palette as `--lini-*` custom properties, plus
// `--theme FILE` overrides and `--theme A/B` light/dark pairs.

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

// One theme variable: the text written into the stylesheet, and its two sides.
#[derive(Clone, Debug)]
pub struct ThemeVar {
    pub raw: String,
    pub light: String,
    pub dark: String,
}

impl ThemeVar {
    fn new(raw: String) -> ThemeVar {
        let (light, dark) = split_light_dark(&raw).unwrap_or((raw.clone(), raw.clone()));
        ThemeVar { raw, light, dark }
    }
}

#[derive(Clone, Debug)]
pub struct Theme {
    // var name (without --lini-) → value
    pub vars: HashMap<String, ThemeVar>,
}

// Strip `/* … */` comments.
fn strip_comments(css: &str) -> String {
    let mut o = String::new();
    let mut rest = css;
    while let Some(p) = rest.find("/*") {
        o.push_str(&rest[..p]);
        match rest[p + 2..].find("*/") {
            Some(q) => rest = &rest[p + 2 + q + 2..],
            None => {
                rest = "";
                break;
            }
        }
    }
    o.push_str(rest);
    o
}

// `--lini-NAME: VALUE` declarations: comments dropped, split at ';', the
// first `--lini-` in each piece names the variable, the first ':' after it
// starts the value (trimmed). Later declarations win.
pub fn parse_theme_vars(css: &str) -> Vec<(String, String)> {
    let text = strip_comments(css);
    let mut out: Vec<(String, String)> = Vec::new();
    for piece in text.split(|c| c == ';' || c == '}') {
        let p = match piece.find("--lini-") {
            Some(p) => p,
            None => continue,
        };
        let rest = &piece[p + 7..];
        let colon = match rest.find(':') {
            Some(c) => c,
            None => continue,
        };
        let name = rest[..colon].trim().to_string();
        let val = rest[colon + 1..].trim().to_string();
        if name.is_empty() {
            continue;
        }
        out.retain(|(n, _)| n != &name);
        out.push((name, val));
    }
    out
}

fn theme_from_css(css: &str) -> Theme {
    let mut vars = HashMap::new();
    vars.insert("font-family".to_string(), ThemeVar::new(FONT_FAMILY.to_string()));
    for (k, v) in parse_theme_vars(css) {
        vars.insert(k, ThemeVar::new(v));
    }
    Theme { vars }
}

pub fn builtin(name: &str) -> Option<Theme> {
    css_of(name).map(theme_from_css)
}

// A light/dark pair of built-ins: A's light side with B's dark side.
fn pair(a: &Theme, b: &Theme) -> Theme {
    let mut vars = HashMap::new();
    let mut names: Vec<&String> = a.vars.keys().collect();
    for k in b.vars.keys() {
        if !a.vars.contains_key(k) {
            names.push(k);
        }
    }
    for k in names {
        let l = a.vars.get(k).map(|v| v.light.clone()).or_else(|| b.vars.get(k).map(|v| v.light.clone())).unwrap_or_default();
        let d = b.vars.get(k).map(|v| v.dark.clone()).unwrap_or_else(|| l.clone());
        let raw = if l == d { l.clone() } else { format!("light-dark({}, {})", l, d) };
        vars.insert(k.clone(), ThemeVar { raw, light: l, dark: d });
    }
    Theme { vars }
}

pub enum ThemeErr {
    // exit 2: the spec was read as a file and that failed
    Io(String),
    // exit 3: --no-fs and not a built-in
    NoFs(String),
}

// Resolve a --theme spec: a built-in, a built-in pair `A/B`, or a CSS file of
// `--lini-*` overrides on top of the default theme.
pub fn load(spec: &str, no_fs: bool) -> Result<Theme, ThemeErr> {
    if let Some(t) = builtin(spec) {
        return Ok(t);
    }
    if let Some((a, b)) = spec.split_once('/') {
        if let (Some(ta), Some(tb)) = (builtin(a), builtin(b)) {
            return Ok(pair(&ta, &tb));
        }
    }
    let names = NAMES.join(", ");
    if no_fs {
        return Err(ThemeErr::NoFs(format!(
            "error: theme '{}' is not a built-in (try: {}), and --no-fs reads no theme file",
            spec, names
        )));
    }
    match std::fs::read(spec) {
        Ok(bytes) => {
            let text = String::from_utf8_lossy(&bytes).to_string();
            let mut t = builtin("default").unwrap();
            for (k, v) in parse_theme_vars(&text) {
                t.vars.insert(k, ThemeVar::new(normalize(&v)));
            }
            Ok(t)
        }
        Err(e) => Err(ThemeErr::Io(format!(
            "error: theme '{}': not a built-in (try: {}), and reading it as a file failed: {}",
            spec,
            names,
            e
        ))),
    }
}

// A theme file's value as the stylesheet writes it: a lone number in
// canonical form; a value ending in `)` after a bare name is a call whose
// arguments (split at top-level commas, trimmed) normalise the same way;
// anything else stays as written.
pub fn normalize(v: &str) -> String {
    let s = v.trim();
    if let Ok(x) = s.parse::<f64>() {
        if x.is_finite() {
            return crate::util::f4(x);
        }
    }
    if let (Some(open), true) = (s.find('('), s.ends_with(')')) {
        let name = &s[..open];
        if !name.is_empty() && !name.contains(char::is_whitespace) {
            let inner = &s[open + 1..s.len() - 1];
            let mut args = Vec::new();
            let mut depth = 0i32;
            let mut start = 0;
            for (i, c) in inner.char_indices() {
                match c {
                    '(' => depth += 1,
                    ')' => depth -= 1,
                    ',' if depth == 0 => {
                        args.push(normalize(&inner[start..i]));
                        start = i + 1;
                    }
                    _ => {}
                }
            }
            args.push(normalize(&inner[start..]));
            return format!("{}({})", name, args.join(", "));
        }
    }
    s.to_string()
}

// The theme a compile uses (validated earlier by `load`).
pub fn resolve(spec: &str) -> Option<Theme> {
    THEME_CACHE.with(|c| {
        let mut c = c.borrow_mut();
        if let Some((s, t)) = &*c {
            if s == spec {
                return Some(t.clone());
            }
        }
        let t = load(spec, false).ok()?;
        *c = Some((spec.to_string(), t.clone()));
        Some(t)
    })
}

thread_local! {
    static THEME_CACHE: std::cell::RefCell<Option<(String, Theme)>> = std::cell::RefCell::new(None);
}

impl Theme {
    // The value as the stylesheet writes it (`light-dark(…)` for a pair).
    pub fn css_value(&self, var: &str) -> Option<String> {
        self.vars.get(var).map(|v| v.raw.clone())
    }
    // the light-side literal value (for --static baking)
    pub fn light_value(&self, var: &str) -> Option<String> {
        self.vars.get(var).map(|x| x.light.clone())
    }
}
