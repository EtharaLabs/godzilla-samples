// Façade packages: `pyfun add`, `pyfun install` and `pyfun remove`. A façade
// is a Python package that ships .pyfun files; installing one vendors those
// files under `.pyfun/facades/<package>/` next to pyfun.toml, where module
// lookup finds them, and records the version under [dependencies].

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const METADATA_SCRIPT: &str = "import importlib.metadata as m, sys
d = m.distribution(sys.argv[1])
print(d.version)
for f in d.files or []:
    if str(f).endswith('.pyfun'):
        print(d.locate_file(f))
";

fn fail(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(1);
}

/// pyfun.toml in the working directory or the nearest parent.
fn find_toml() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    cwd.ancestors().map(|d| d.join("pyfun.toml")).find(|p| p.is_file())
}

/// The façade directories a program at `main` sees: those vendored next to
/// the pyfun.toml found from the program's directory upward.
pub fn facade_dirs(main: &Path) -> Vec<PathBuf> {
    let parent = main.parent().unwrap_or(Path::new(""));
    for dir in parent.ancestors() {
        if dir.join("pyfun.toml").is_file() {
            let mut dirs: Vec<PathBuf> = match std::fs::read_dir(dir.join(".pyfun").join("facades")) {
                Ok(rd) => rd.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.is_dir()).collect(),
                Err(_) => Vec::new(),
            };
            dirs.sort();
            return dirs;
        }
    }
    Vec::new()
}

/// The interpreter for package work: PYFUN_PYTHON, else `python`, else `python3`.
pub fn package_python() -> String {
    match crate::find_python(true) {
        Ok(p) => p,
        Err(_) => fail("no Python interpreter found (set PYFUN_PYTHON)"),
    }
}

fn have_uv() -> bool {
    Command::new("uv")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// The package name a requirement names (`pkg==1.0`, `pkg[extra]` → `pkg`).
fn package_name(spec: &str) -> String {
    let end = spec.find(|c: char| matches!(c, '=' | '<' | '>' | '!' | '~' | '[' | ';' | '@') || c.is_whitespace()).unwrap_or(spec.len());
    let name = &spec[..end];
    if name.is_empty() {
        fail(&format!("cannot read a package name from `{}`", spec));
    }
    name.to_string()
}

/// The normalized name a package's façade directory goes by.
fn normalized(name: &str) -> String {
    name.to_lowercase().split(|c| matches!(c, '-' | '_' | '.')).filter(|s| !s.is_empty()).collect::<Vec<_>>().join("-")
}

// ---- pyfun.toml, edited line by line ------------------------------------

struct Toml {
    path: PathBuf,
    lines: Vec<String>,
}

fn section_of(line: &str) -> Option<String> {
    let t = line.trim();
    if t.starts_with('[') && t.ends_with(']') && t.len() >= 2 {
        Some(t[1..t.len() - 1].trim().to_string())
    } else {
        None
    }
}

/// `key = "value"` (a trailing comment allowed): the key and value.
fn dep_entry(line: &str) -> Option<(String, String)> {
    if line.trim_start().starts_with('#') {
        return None;
    }
    let (k, v) = line.split_once('=')?;
    let k = k.trim();
    let k = if k.len() >= 2 && k.starts_with('"') && k.ends_with('"') { &k[1..k.len() - 1] } else { k };
    let v = v.trim().strip_prefix('"')?;
    let close = v.find('"')?;
    let rest = v[close + 1..].trim();
    if !rest.is_empty() && !rest.starts_with('#') {
        return None;
    }
    Some((k.to_string(), v[..close].to_string()))
}

impl Toml {
    fn load(path: &Path) -> Toml {
        let text = match std::fs::read_to_string(path) {
            Ok(t) => t,
            Err(e) => fail(&format!("cannot read {}: {}", path.display(), e)),
        };
        Toml { path: path.to_path_buf(), lines: text.lines().map(|l| l.to_string()).collect() }
    }

    /// Each dependency entry: (line index, name, version).
    fn deps(&self) -> Vec<(usize, String, String)> {
        let mut out = Vec::new();
        let mut in_deps = false;
        for (i, l) in self.lines.iter().enumerate() {
            if let Some(s) = section_of(l) {
                in_deps = s == "dependencies";
                continue;
            }
            if in_deps {
                if let Some((k, v)) = dep_entry(l) {
                    out.push((i, k, v));
                }
            }
        }
        out
    }

    fn set(&mut self, name: &str, version: &str) {
        let entry = format!("{} = \"{}\"", name, version);
        if let Some((i, _, _)) = self.deps().into_iter().find(|(_, k, _)| k == name) {
            self.lines[i] = entry;
            return;
        }
        // after the last entry of the dependencies section (or its header)
        let mut at: Option<usize> = None;
        let mut in_deps = false;
        for (i, l) in self.lines.iter().enumerate() {
            if let Some(s) = section_of(l) {
                in_deps = s == "dependencies";
                if in_deps {
                    at = Some(i);
                }
                continue;
            }
            let t = l.trim();
            if in_deps && !t.is_empty() && !t.starts_with('#') {
                at = Some(i);
            }
        }
        match at {
            Some(i) => self.lines.insert(i + 1, entry),
            None => {
                if self.lines.last().map_or(false, |l| !l.trim().is_empty()) {
                    self.lines.push(String::new());
                }
                self.lines.push("[dependencies]".to_string());
                self.lines.push(entry);
            }
        }
    }

    fn remove(&mut self, name: &str) -> bool {
        match self.deps().into_iter().find(|(_, k, _)| k == name) {
            Some((i, _, _)) => {
                self.lines.remove(i);
                true
            }
            None => false,
        }
    }

    fn save(&self) {
        let mut text = self.lines.join("\n");
        text.push('\n');
        if let Err(e) = std::fs::write(&self.path, text) {
            fail(&format!("cannot write {}: {}", self.path.display(), e));
        }
    }
}

// ---- installing ----------------------------------------------------------

/// Install `spec`, vendor its .pyfun files and record it.
fn add_one(spec: &str, toml: &mut Toml) {
    let name = package_name(spec);
    let python = package_python();
    let status = if have_uv() {
        Command::new("uv").args(["pip", "install", "--python", &python, spec]).status()
    } else {
        Command::new(&python).args(["-m", "pip", "install", spec]).status()
    };
    match status {
        Ok(s) if s.success() => {}
        Ok(_) => fail(&format!("installing `{}` failed (see the installer's output above)", spec)),
        Err(e) => fail(&format!("cannot run the installer: {}", e)),
    }
    let out = match Command::new(&python).arg("-c").arg(METADATA_SCRIPT).arg(&name).stdin(Stdio::null()).output() {
        Ok(o) => o,
        Err(e) => fail(&format!("cannot run {}: {}", python, e)),
    };
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        fail(&format!("cannot read the installed metadata of `{}`: {}", name, err.trim_end()));
    }
    let text = String::from_utf8_lossy(&out.stdout).to_string();
    let mut lines = text.lines();
    let version = lines.next().unwrap_or("").trim().to_string();
    let files: Vec<&str> = lines.collect();
    if files.is_empty() {
        fail(&format!("`{}` installed, but it ships no .pyfun files, so it is not a Pyfun façade", name));
    }
    let root = toml.path.parent().map(|p| p.to_path_buf()).unwrap_or_default();
    let dir = root.join(".pyfun").join("facades").join(normalized(&name));
    if dir.exists() {
        let _ = std::fs::remove_dir_all(&dir);
    }
    if let Err(e) = std::fs::create_dir_all(&dir) {
        fail(&format!("cannot create {}: {}", dir.display(), e));
    }
    let mut modules = Vec::new();
    for f in files {
        let src = Path::new(f);
        let Some(fname) = src.file_name() else { fail(&format!("odd façade path {}", f)) };
        if let Err(e) = std::fs::copy(src, dir.join(fname)) {
            fail(&format!("cannot copy {}: {}", f, e));
        }
        modules.push(crate::project::module_name_of(src));
    }
    modules.sort();
    toml.set(&name, &version);
    toml.save();
    println!("added {} {} (import {})", name, version, modules.join(", "));
}

pub fn cmd_add(args: &[String]) {
    if args.is_empty() {
        fail("`add` needs a package, e.g. `pyfun add pyfun-textwrap`");
    }
    let path = match find_toml() {
        Some(p) => p,
        None => {
            let cwd = std::env::current_dir().unwrap_or_default();
            let name = cwd.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
            let p = cwd.join("pyfun.toml");
            if let Err(e) = std::fs::write(&p, format!("[project]\nname = \"{}\"\n\n[dependencies]\n", name)) {
                fail(&format!("cannot write {}: {}", p.display(), e));
            }
            println!("created pyfun.toml");
            p
        }
    };
    let mut toml = Toml::load(&path);
    for spec in args {
        add_one(spec, &mut toml);
    }
}

pub fn cmd_install(_args: &[String]) {
    let Some(path) = find_toml() else { fail("no pyfun.toml here or in any parent directory (`pyfun add <package>` creates one)") };
    let mut toml = Toml::load(&path);
    let deps = toml.deps();
    if deps.is_empty() {
        println!("no dependencies in pyfun.toml");
        return;
    }
    for (_, name, version) in deps {
        let spec = if version.is_empty() { name.clone() } else { format!("{}=={}", name, version) };
        add_one(&spec, &mut toml);
    }
}

pub fn cmd_remove(args: &[String]) {
    if args.is_empty() {
        fail("`remove` needs a package name");
    }
    let Some(path) = find_toml() else { fail("no pyfun.toml here or in any parent directory (`pyfun add <package>` creates one)") };
    let mut toml = Toml::load(&path);
    let root = path.parent().map(|p| p.to_path_buf()).unwrap_or_default();
    for name in args {
        if !toml.remove(name) {
            fail(&format!("`{}` is not a dependency in pyfun.toml", name));
        }
        let python = package_python();
        let _ = if have_uv() {
            Command::new("uv").args(["pip", "uninstall", "--python", &python, name]).status()
        } else {
            Command::new(&python).args(["-m", "pip", "uninstall", "-y", name]).status()
        };
        let dir = root.join(".pyfun").join("facades").join(normalized(name));
        let _ = std::fs::remove_dir_all(&dir);
        println!("removed {}", name);
    }
    toml.save();
}
