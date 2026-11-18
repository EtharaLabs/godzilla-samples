// The session engine behind the Jupyter kernel: length-framed requests on
// stdin, `status / info / code` frame triples on stdout.

use crate::ast::Decl;
use crate::session::{EvalErr, EvalOk, Mode, Session};
use std::io::{Read, Write};

fn read_frame(r: &mut impl Read) -> Option<Vec<u8>> {
    let mut header = [0u8; 8];
    r.read_exact(&mut header).ok()?;
    let s = std::str::from_utf8(&header).ok()?;
    if !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let n: usize = s.parse().ok()?;
    let mut buf = vec![0u8; n];
    r.read_exact(&mut buf).ok()?;
    Some(buf)
}

fn frame(out: &mut Vec<u8>, s: &str) {
    out.extend_from_slice(format!("{:08}", s.len()).as_bytes());
    out.extend_from_slice(s.as_bytes());
}

fn error_reply(e: EvalErr) -> (String, String, String) {
    match e {
        EvalErr::Parse(s) => ("error".to_string(), s, String::new()),
        EvalErr::Type(errs) => {
            let mut s = String::new();
            for e in errs {
                s.push_str(&e);
                s.push('\n');
            }
            ("error".to_string(), s, String::new())
        }
        EvalErr::Compile(_, errs) => ("error".to_string(), errs.join("\n"), String::new()),
    }
}

fn echo_text(r: &EvalOk) -> String {
    let mut info = String::new();
    for e in &r.echoes {
        info.push_str(e);
        info.push('\n');
    }
    info
}

/// A cell's definitions are entered first (and stay, whatever follows);
/// a trailing expression is then evaluated on its own. The cell is cut
/// where the expression's own text starts (inside its parentheses, for a
/// parenthesized one), and the text before it, unless blank, is entered as
/// it stands.
fn eval_cell(session: &mut Session, cell: &str) -> (String, String, String) {
    let split = match crate::parser::parse_program(cell) {
        Ok(p) => match p.decls.last() {
            Some(Decl::Expr(e)) => Some(e.span.lo),
            Some(Decl::Assign(_, _, _, whole)) => Some(whole.lo),
            _ => None,
        },
        _ => None,
    };
    let Some(at) = split else {
        return match session.eval(cell, true) {
            Ok(r) => ("ok".to_string(), echo_text(&r), r.code),
            Err(e) => error_reply(e),
        };
    };
    let head = &cell[..at];
    let defs = if head.trim().is_empty() {
        None
    } else {
        match session.eval_part(head, true, true) {
            Ok(r) => Some(r),
            Err(e) => return error_reply(e),
        }
    };
    match session.eval(&cell[at..], true) {
        Ok(r) => {
            let Some(defs) = defs else {
                return ("ok".to_string(), echo_text(&r), r.code);
            };
            let mut info = echo_text(&defs);
            info.push_str(&echo_text(&r));
            let mut code = defs.code.clone();
            // an empty expression's `pass` only fills an otherwise empty reply
            if !(r.fallback_pass && (!defs.code.is_empty() || defs.all_dup)) {
                code.push_str(&r.code);
            }
            ("ok".to_string(), info, code)
        }
        Err(e) => error_reply(e),
    }
}

pub fn run_kernel() -> ! {
    let mut session = Session::new(Mode::Kernel);
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    let stdout = std::io::stdout();
    loop {
        let Some(op) = read_frame(&mut input) else { break };
        let Some(payload) = read_frame(&mut input) else { break };
        let op = String::from_utf8_lossy(&op).to_string();
        let payload = String::from_utf8_lossy(&payload).to_string();
        let (status, info, code) = match op.as_str() {
            "eval" => {
                let mut cell = payload.as_str();
                // a first line of `:reset` starts a fresh session
                let first = cell.lines().next().unwrap_or("");
                if first.trim() == ":reset" {
                    session.reset();
                    cell = match cell.find('\n') {
                        Some(i) => &cell[i + 1..],
                        None => "",
                    };
                }
                if cell.trim().is_empty() {
                    ("ok".to_string(), String::new(), String::new())
                } else {
                    eval_cell(&mut session, cell)
                }
            }
            "type" => match session.type_of(&payload) {
                Ok(s) => ("ok".to_string(), s, String::new()),
                Err(errs) => {
                    if errs.len() == 1 && errs[0].starts_with('(') {
                        ("error".to_string(), errs[0].clone(), String::new())
                    } else {
                        let mut s = String::new();
                        for e in errs {
                            s.push_str(&e);
                            s.push('\n');
                        }
                        ("error".to_string(), s, String::new())
                    }
                }
            },
            other => ("error".to_string(), format!("unknown op `{}`", other), String::new()),
        };
        let mut out = Vec::new();
        frame(&mut out, &status);
        frame(&mut out, &info);
        frame(&mut out, &code);
        let mut lock = stdout.lock();
        let _ = lock.write_all(&out);
        let _ = lock.flush();
    }
    std::process::exit(0);
}
