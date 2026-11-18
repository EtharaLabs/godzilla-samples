//! The headless backend: a session of the server's own, read-only with `--read-only`.
//!
//! Read-only is the agent's side of it: the project is opened as ever, then nothing the agent
//! asks may change it, step through its history, replace it or write over its file. A command
//! that would replace the project (or step through the history) is refused before it runs; one
//! that names the project's own file as its `path` too; anything else runs, and if it would have
//! made an undo step it is taken back and refused. Its errors come first, so a command given
//! wrong parameters says what is wrong with them.

use crate::json::{Map, Value};
use crate::session::{Session, Step, MAX_UNDO};

pub struct Local {
    pub s: Session,
    pub read_only: bool,
}

/// Why an agent may not change the project here.
const READ_ONLY_REASON: &str = "this MCP server was started with --read-only: start it without to edit";

/// The commands that put another project in place of this one.
const REPLACES: [&str; 4] = ["new", "open", "recover", "highrise"];

fn would(cid: &str, what: &str) -> String {
    format!("`{}` would {}, which is read-only for agents: {}", cid, what, READ_ONLY_REASON)
}

/// Whether two paths name one file: as the file system resolves them, or as written when it can't.
fn same_file(a: &str, b: &str) -> bool {
    let canon = |p: &str| std::fs::canonicalize(p).unwrap_or_else(|_| std::path::PathBuf::from(p));
    canon(a) == canon(b)
}

impl Local {
    pub fn new(read_only: bool) -> Local {
        Local { s: Session::new(), read_only }
    }

    /// Opens the FILE the server was started with; the error is the whole message.
    pub fn open_file(&mut self, path: &str) -> Result<(), String> {
        self.open(path).map(|_| ())
    }

    /// Opens a project or imports a file by its extension; a Revit import's error is a whole
    /// message, the path first, and the others say `open: `.
    fn open(&mut self, path: &str) -> Result<Value, String> {
        crate::commands::open_path(&mut self.s, path).map_err(|e| {
            if crate::rvt::is_revit_path(path) {
                e
            } else {
                format!("open: {}", e)
            }
        })
    }

    /// The `open` tool: `path` as the `open` command reads it, then the file by its extension.
    pub fn open_tool(&mut self, path: &Value) -> Result<Value, String> {
        if self.read_only {
            return Err(would("open", "replace the project"));
        }
        let mut m = Map::new();
        m.insert("path", path.clone());
        let path = crate::commands::params::opt_text(&Value::Obj(m), "open", "path")?.unwrap_or_default();
        self.open(&path)
    }

    /// The `new_model` tool: `new` with the agent's arguments.
    pub fn new_model(&mut self, args: &Value) -> Result<Value, String> {
        if self.read_only {
            return Err(would("new", "replace the project"));
        }
        self.s.execute("new", args)
    }

    /// Runs a command, as the agent may.
    pub fn execute(&mut self, cmd: &str, params: &Value) -> Result<Value, String> {
        if !self.read_only {
            return self.s.execute(cmd, params);
        }
        let Some((cid, _)) = crate::commands::resolve(cmd) else {
            return self.s.execute(cmd, params);
        };
        if REPLACES.contains(&cid.as_str()) {
            return Err(would(&cid, "replace the project"));
        }
        if matches!(cid.as_str(), "undo" | "redo") {
            return Err(would(&cid, "change the project"));
        }
        if let Some(own) = self.s.path.clone() {
            if cid == "save" {
                let target = match params.get("path") {
                    None | Some(Value::Null) => Some(own.clone()),
                    Some(Value::Str(p)) => Some(p.clone()),
                    Some(_) => None,
                };
                if target.map(|t| same_file(&t, &own)).unwrap_or(false) {
                    return Err(would("save", "write over the project's own file"));
                }
            } else if let Some(p) = params.get("path").and_then(|x| x.as_str()) {
                if same_file(p, &own) {
                    return Err(would(&cid, "use the project's own file (`path`)"));
                }
            }
        }
        // nothing an agent does here moves the history, so it is empty: a step made is a change,
        // and so is anything else a command that changes the model changed (the phase it is in)
        let model = crate::commands::changes_model(&cid);
        let before = self.s.project.clone();
        let path = self.s.path.clone();
        let phase = (self.s.now_phase.clone(), self.s.now_option.clone());
        let r = self.s.execute(cmd, params);
        // a copy saved elsewhere leaves the project's file where it was
        self.s.path = path;
        let changed = !self.s.undo.is_empty()
            || !self.s.redo.is_empty()
            || (model
                && r.is_ok()
                && (phase != (self.s.now_phase.clone(), self.s.now_option.clone())
                    || self.s.project.to_value() != before.to_value()));
        if changed {
            self.s.undo.clear();
            self.s.redo.clear();
            self.s.project = before;
            self.s.now_phase = phase.0;
            self.s.now_option = phase.1;
            return Err(would(&cid, "change the project"));
        }
        r
    }

    /// Runs a script a line at a time, stopping at the first that fails (or isn't JSON). With
    /// `atomic`, a failing line takes back all before it, and a script that goes through is one
    /// undo step, `Script`; it steps through a history of its own meanwhile.
    pub fn script(&mut self, text: &str, atomic: bool) -> Result<Value, String> {
        if !atomic {
            let mut results = Vec::new();
            for (n, raw) in text.lines().enumerate() {
                if let Some((id, params)) = parse_line(raw, n + 1)? {
                    let v = self.execute(&id, &params).map_err(|e| format!("line {} ({}): {}", n + 1, id, e))?;
                    results.push(v);
                }
            }
            return Ok(Value::Arr(results));
        }
        let before = self.s.project.clone();
        let path = self.s.path.clone();
        let phase = (self.s.now_phase.clone(), self.s.now_option.clone());
        let undo = std::mem::take(&mut self.s.undo);
        let redo = std::mem::take(&mut self.s.redo);
        let mut results = Vec::new();
        let mut replaced = false;
        let mut failed = None;
        for (n, raw) in text.lines().enumerate() {
            let (id, params) = match parse_line(raw, n + 1) {
                Ok(Some(x)) => x,
                Ok(None) => continue,
                Err(e) => {
                    failed = Some(e);
                    break;
                }
            };
            match self.execute(&id, &params) {
                Ok(v) => {
                    results.push(v);
                    let cid = crate::commands::resolve(&id).map(|(c, _)| c).unwrap_or_default();
                    if REPLACES.contains(&cid.as_str()) {
                        replaced = true;
                    }
                }
                Err(e) => {
                    failed = Some(format!("line {} ({}): {}", n + 1, id, e));
                    break;
                }
            }
        }
        if let Some(e) = failed {
            self.s.project = before;
            self.s.path = path;
            self.s.now_phase = phase.0;
            self.s.now_option = phase.1;
            self.s.undo = undo;
            self.s.redo = redo;
            return Err(e);
        }
        if !replaced {
            // the script's own steps become one; another project opened keeps its history
            let stepped = !self.s.undo.is_empty();
            self.s.undo = undo;
            if stepped {
                self.s.redo.clear();
                self.s.undo.push(Step { before, after: self.s.project.clone(), label: "Script".into() });
                if self.s.undo.len() > MAX_UNDO {
                    self.s.undo.remove(0);
                }
            } else {
                self.s.redo = redo;
            }
        }
        Ok(Value::Arr(results))
    }
}

/// One line of a script: `id {json}`; none for a blank line or a `#` comment.
fn parse_line(raw: &str, n: usize) -> Result<Option<(String, Value)>, String> {
    let t = raw.trim();
    if t.is_empty() || t.starts_with('#') {
        return Ok(None);
    }
    let (id, rest) = match t.find(char::is_whitespace) {
        Some(i) => (&t[..i], t[i..].trim()),
        None => (t, ""),
    };
    let params = if rest.is_empty() {
        Value::obj()
    } else {
        crate::json::parse(rest).map_err(|e| format!("line {}: bad JSON after `{}`: {}", n, id, e))?
    };
    Ok(Some((id.to_string(), params)))
}
