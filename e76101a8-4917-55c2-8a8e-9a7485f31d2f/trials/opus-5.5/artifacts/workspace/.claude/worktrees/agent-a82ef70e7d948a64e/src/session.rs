//! A session: the project, its file, and its undo history; commands run here.

use crate::json::Value;
use crate::project::Project;

pub struct Step {
    pub before: Project,
    pub after: Project,
    pub label: String,
}

pub struct Session {
    pub project: Project,
    pub path: Option<String>,
    pub undo: Vec<Step>,
    pub redo: Vec<Step>,
    pub read_only: bool,
    /// The phase and design option this session makes elements in.
    pub now_phase: Option<String>,
    pub now_option: Option<String>,
}

pub const MAX_UNDO: usize = 200;

impl Session {
    pub fn new() -> Session {
        Session {
            project: Project::new("en"),
            path: None,
            undo: Vec::new(),
            redo: Vec::new(),
            read_only: false,
            now_phase: None,
            now_option: None,
        }
    }

    /// Runs a command by id (or alias, any case) with its parameters.
    pub fn execute(&mut self, id: &str, params: &Value) -> Result<Value, String> {
        let Some((cid, label)) = crate::commands::resolve(id) else {
            return Err(format!("unknown command `{}`; list_commands shows them", id));
        };
        let before = self.project.clone();
        // the phase and option this session makes elements in go back with a refused command
        let now_before = (self.now_phase.clone(), self.now_option.clone());
        let res = crate::commands::run(self, &cid, params);
        match res {
            Ok(out) => {
                if crate::commands::changes_model(&cid) && !crate::commands::is_history_cmd(&cid) {
                    if let Err(e) = crate::check::check(&self.project) {
                        self.project = before;
                        (self.now_phase, self.now_option) = now_before;
                        return Err(e);
                    }
                    if self.project.to_value() != before.to_value() || crate::commands::always_step(&cid) {
                        self.undo.push(Step { before, after: self.project.clone(), label: label.clone() });
                        if self.undo.len() > MAX_UNDO {
                            self.undo.remove(0);
                        }
                        self.redo.clear();
                    }
                }
                Ok(out)
            }
            Err(e) => {
                self.project = before;
                (self.now_phase, self.now_option) = now_before;
                Err(e)
            }
        }
    }

    pub fn history(&self) -> Vec<String> {
        self.undo.iter().map(|s| s.label.clone()).collect()
    }
}
