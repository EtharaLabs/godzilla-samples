// Directory traversal honoring hidden-file and ignore-file rules.

use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
struct Pattern {
    negated: bool,
    dir_only: bool,
    anchored: bool,
    glob: Vec<char>,
}

#[derive(Debug, Clone, Default)]
struct IgnoreFile {
    /// Directory the patterns are relative to.
    base: PathBuf,
    patterns: Vec<Pattern>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Match {
    None,
    Ignore,
    Whitelist,
}

fn parse_ignore(content: &str, base: &Path) -> IgnoreFile {
    let mut patterns = Vec::new();
    for raw in content.lines() {
        let mut line = raw.trim_end_matches('\r').to_string();
        if line.starts_with('#') || line.is_empty() {
            continue;
        }
        // Trailing unescaped spaces are ignored.
        while line.ends_with(' ') && !line.ends_with("\\ ") {
            line.pop();
        }
        if line.is_empty() {
            continue;
        }
        let mut negated = false;
        if let Some(r) = line.strip_prefix('!') {
            negated = true;
            line = r.to_string();
        } else if line.starts_with("\\!") || line.starts_with("\\#") {
            line = line[1..].to_string();
        }
        let mut dir_only = false;
        if line.ends_with('/') && line.len() > 1 {
            dir_only = true;
            line.pop();
        }
        let anchored;
        if let Some(r) = line.strip_prefix('/') {
            anchored = true;
            line = r.to_string();
        } else {
            anchored = line.contains('/') && !line.starts_with("**/");
        }
        let line = if !anchored && !line.starts_with("**/") {
            format!("**/{}", line)
        } else {
            line
        };
        patterns.push(Pattern { negated, dir_only, anchored, glob: line.chars().collect() });
    }
    IgnoreFile { base: base.to_path_buf(), patterns }
}

fn class_match(pat: &[char], c: char) -> Option<(bool, usize)> {
    // pat starts after '['; returns (matched, consumed incl. closing ']')
    let mut i = 0;
    let mut negate = false;
    if i < pat.len() && (pat[i] == '!' || pat[i] == '^') {
        negate = true;
        i += 1;
    }
    let mut matched = false;
    let mut first = true;
    while i < pat.len() {
        if pat[i] == ']' && !first {
            return Some((matched != negate, i + 1));
        }
        first = false;
        let lo = if pat[i] == '\\' && i + 1 < pat.len() {
            i += 1;
            pat[i]
        } else {
            pat[i]
        };
        if i + 2 < pat.len() && pat[i + 1] == '-' && pat[i + 2] != ']' {
            let hi = pat[i + 2];
            if lo <= c && c <= hi {
                matched = true;
            }
            i += 3;
        } else {
            if lo == c {
                matched = true;
            }
            i += 1;
        }
    }
    None
}

fn glob_match(p: &[char], s: &[char]) -> bool {
    if p.is_empty() {
        return s.is_empty();
    }
    // `**` handling
    if p.len() >= 2 && p[0] == '*' && p[1] == '*' {
        let rest = &p[2..];
        if rest.is_empty() {
            return true;
        }
        if rest[0] == '/' {
            let rest2 = &rest[1..];
            // Match zero or more directories.
            if glob_match(rest2, s) {
                return true;
            }
            for i in 0..s.len() {
                if s[i] == '/' && glob_match(rest2, &s[i + 1..]) {
                    return true;
                }
            }
            return false;
        }
        // Treat like single star otherwise.
        for i in 0..=s.len() {
            if glob_match(rest, &s[i..]) {
                return true;
            }
        }
        return false;
    }
    match p[0] {
        '*' => {
            for i in 0..=s.len() {
                if i > 0 && s[i - 1] == '/' {
                    break;
                }
                if glob_match(&p[1..], &s[i..]) {
                    return true;
                }
            }
            false
        }
        '?' => !s.is_empty() && s[0] != '/' && glob_match(&p[1..], &s[1..]),
        '[' => {
            if s.is_empty() || s[0] == '/' {
                return false;
            }
            match class_match(&p[1..], s[0]) {
                Some((true, used)) => glob_match(&p[1 + used..], &s[1..]),
                Some((false, _)) => false,
                None => s[0] == '[' && glob_match(&p[1..], &s[1..]),
            }
        }
        '\\' if p.len() > 1 => !s.is_empty() && s[0] == p[1] && glob_match(&p[2..], &s[1..]),
        c => !s.is_empty() && s[0] == c && glob_match(&p[1..], &s[1..]),
    }
}

impl IgnoreFile {
    fn matched(&self, path: &Path, is_dir: bool) -> Match {
        let rel = match path.strip_prefix(&self.base) {
            Ok(r) => r,
            Err(_) => return Match::None,
        };
        let rel_s: Vec<char> = rel.to_string_lossy().chars().collect();
        if rel_s.is_empty() {
            return Match::None;
        }
        for pat in self.patterns.iter().rev() {
            if pat.dir_only && !is_dir {
                continue;
            }
            let _ = pat.anchored;
            if glob_match(&pat.glob, &rel_s) {
                return if pat.negated { Match::Whitelist } else { Match::Ignore };
            }
        }
        Match::None
    }
}

struct DirIgnores {
    dir: PathBuf,
    ignore: Option<IgnoreFile>,
    gitignore: Option<IgnoreFile>,
    git_exclude: Option<IgnoreFile>,
    has_git: bool,
}

fn load_dir(dir: &Path) -> DirIgnores {
    let ignore = fs::read_to_string(dir.join(".ignore")).ok().map(|c| parse_ignore(&c, dir));
    let gitignore = fs::read_to_string(dir.join(".gitignore")).ok().map(|c| parse_ignore(&c, dir));
    let has_git = dir.join(".git").exists();
    let git_exclude = if has_git {
        fs::read_to_string(dir.join(".git").join("info").join("exclude"))
            .ok()
            .map(|c| parse_ignore(&c, dir))
    } else {
        None
    };
    DirIgnores { dir: dir.to_path_buf(), ignore, gitignore, git_exclude, has_git }
}

fn global_gitignore() -> Option<String> {
    let home = std::env::var_os("HOME").map(PathBuf::from);
    let mut excludes: Option<PathBuf> = None;
    let mut configs = Vec::new();
    if let Some(h) = &home {
        configs.push(h.join(".gitconfig"));
    }
    let xdg = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| home.as_ref().map(|h| h.join(".config")));
    if let Some(x) = &xdg {
        configs.push(x.join("git").join("config"));
    }
    for cfg in configs {
        if let Ok(content) = fs::read_to_string(&cfg) {
            let mut in_core = false;
            for line in content.lines() {
                let t = line.trim();
                if t.starts_with('[') {
                    in_core = t.to_ascii_lowercase().starts_with("[core");
                    continue;
                }
                if in_core {
                    if let Some(eq) = t.find('=') {
                        let k = t[..eq].trim();
                        if k.eq_ignore_ascii_case("excludesfile") {
                            let mut v = t[eq + 1..].trim().trim_matches('"').to_string();
                            if let Some(r) = v.strip_prefix("~/") {
                                if let Some(h) = &home {
                                    v = h.join(r).to_string_lossy().into_owned();
                                }
                            }
                            excludes = Some(PathBuf::from(v));
                        }
                    }
                }
            }
        }
    }
    let path = excludes.or_else(|| xdg.map(|x| x.join("git").join("ignore")))?;
    fs::read_to_string(path).ok()
}

pub struct Walker {
    stack: Vec<DirIgnores>,
    global: Option<String>,
    global_parsed: Option<IgnoreFile>,
}

impl Walker {
    pub fn new() -> Self {
        Walker { stack: Vec::new(), global: global_gitignore(), global_parsed: None }
    }

    fn is_ignored(&self, path: &Path, is_dir: bool) -> bool {
        let any_git = self.stack.iter().any(|d| d.has_git);
        let mut m_ignore = Match::None;
        let mut m_gi = Match::None;
        let mut m_ex = Match::None;
        let mut saw_git = false;
        for d in self.stack.iter().rev() {
            if m_ignore == Match::None {
                if let Some(f) = &d.ignore {
                    m_ignore = f.matched(path, is_dir);
                }
            }
            if any_git && !saw_git && m_gi == Match::None {
                if let Some(f) = &d.gitignore {
                    m_gi = f.matched(path, is_dir);
                }
            }
            if any_git && !saw_git && m_ex == Match::None {
                if let Some(f) = &d.git_exclude {
                    m_ex = f.matched(path, is_dir);
                }
            }
            saw_git = saw_git || d.has_git;
            let _ = &d.dir;
        }
        let mut m = if m_ignore != Match::None {
            m_ignore
        } else if m_gi != Match::None {
            m_gi
        } else {
            m_ex
        };
        if m == Match::None && any_git {
            if let Some(g) = &self.global_parsed {
                if let Some(root) = self.stack.iter().rev().find(|d| d.has_git) {
                    let mut g2 = g.clone();
                    g2.base = root.dir.clone();
                    m = g2.matched(path, is_dir);
                }
            }
        }
        m == Match::Ignore
    }

    /// Walk `root` (a directory), returning files in traversal order.
    pub fn walk(&mut self, root: &Path) -> Vec<PathBuf> {
        let mut out = Vec::new();
        self.stack.clear();
        // Ancestors of the root contribute ignore rules.
        let abs = fs::canonicalize(root).unwrap_or_else(|_| root.to_path_buf());
        let mut ancestors: Vec<PathBuf> = abs.ancestors().skip(1).map(|p| p.to_path_buf()).collect();
        ancestors.reverse();
        let mut parents = Vec::new();
        for a in ancestors {
            parents.push(load_dir(&a));
        }
        // Use absolute paths for matching ancestors; we match with absolute paths throughout.
        self.stack = parents;
        if let Some(g) = &self.global {
            self.global_parsed = Some(parse_ignore(g, Path::new("")));
        }
        self.walk_dir(root, &abs, &mut out);
        out
    }

    fn walk_dir(&mut self, dir: &Path, abs_dir: &Path, out: &mut Vec<PathBuf>) {
        let d = load_dir(abs_dir);
        self.stack.push(d);
        let mut entries: Vec<(String, PathBuf, bool)> = Vec::new();
        if let Ok(rd) = fs::read_dir(dir) {
            for e in rd.flatten() {
                let name = e.file_name().to_string_lossy().into_owned();
                let ft = match e.file_type() {
                    Ok(f) => f,
                    Err(_) => continue,
                };
                if ft.is_symlink() {
                    continue;
                }
                entries.push((name, e.path(), ft.is_dir()));
            }
        }
        entries.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        for (name, path, is_dir) in entries {
            if name.starts_with('.') {
                continue;
            }
            let abs_path = abs_dir.join(&name);
            if self.is_ignored_global_rel(&abs_path, is_dir) {
                continue;
            }
            if is_dir {
                self.walk_dir(&path, &abs_path, out);
            } else {
                out.push(path);
            }
        }
        self.stack.pop();
    }

    fn is_ignored_global_rel(&self, abs_path: &Path, is_dir: bool) -> bool {
        // Global patterns are matched against the path relative to the repository root.
        if self.is_ignored(abs_path, is_dir) {
            return true;
        }
        false
    }
}

impl IgnoreFile {
    #[allow(dead_code)]
    fn is_empty(&self) -> bool {
        self.patterns.is_empty()
    }
}

