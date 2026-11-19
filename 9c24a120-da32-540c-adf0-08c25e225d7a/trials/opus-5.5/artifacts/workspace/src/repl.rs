// The interactive REPL: a session plus a Python worker process.

use crate::session::{EvalErr, Mode, Session};
use std::io::{BufRead, Read, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};

pub const WORKER_SCRIPT: &str = "
import io, sys, traceback
ns = {}
inp = sys.stdin.buffer
out = sys.stdout.buffer
while True:
    header = inp.read(8)
    if len(header) < 8:
        break
    code = inp.read(int(header)).decode('utf-8')
    buf = io.StringIO()
    saved = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        exec(code, ns)
    except BaseException:
        traceback.print_exc()
    finally:
        sys.stdout, sys.stderr = saved
    payload = buf.getvalue().encode('utf-8')
    out.write(b'%08d' % len(payload))
    out.write(payload)
    out.flush()
";

const HELP: &str = "Commands:
  :type <expr>   show an expression's inferred type (no evaluation)
  :{ … :}        enter a multi-line block (e.g. mutually-recursive defs)
  :reset         forget all definitions entered this session
  :help          show this help
  :quit          exit (or Ctrl-D)
Enter a `let`/`type`/`extern` definition to remember it, or an
expression to evaluate it.";

pub struct Worker {
    child: Child,
    stdin: ChildStdin,
    stdout: ChildStdout,
}

impl Worker {
    pub fn spawn(python: &str) -> Result<Worker, String> {
        let mut child = Command::new(python)
            .arg("-c")
            .arg(WORKER_SCRIPT)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| e.to_string())?;
        let stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        Ok(Worker { child, stdin, stdout })
    }

    pub fn request(&mut self, code: &str) -> Result<String, String> {
        let bytes = code.as_bytes();
        let mut msg = format!("{:08}", bytes.len()).into_bytes();
        msg.extend_from_slice(bytes);
        self.stdin.write_all(&msg).map_err(|e| e.to_string())?;
        self.stdin.flush().map_err(|e| e.to_string())?;
        let mut header = [0u8; 8];
        self.stdout.read_exact(&mut header).map_err(|e| e.to_string())?;
        let n: usize = std::str::from_utf8(&header)
            .ok()
            .and_then(|s| if s.bytes().all(|b| b.is_ascii_digit()) { s.parse().ok() } else { None })
            .ok_or_else(|| "bad response header".to_string())?;
        let mut payload = vec![0u8; n];
        self.stdout.read_exact(&mut payload).map_err(|e| e.to_string())?;
        Ok(String::from_utf8_lossy(&payload).into_owned())
    }

    pub fn kill(mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct Repl {
    session: Session,
    python: String,
    worker: Option<Worker>,
}

impl Repl {
    /// Run code in the worker, restarting it once on failure.
    fn run(&mut self, code: &str) {
        let out = std::io::stdout();
        if self.worker.is_none() {
            match Worker::spawn(&self.python) {
                Ok(w) => self.worker = Some(w),
                Err(e) => {
                    eprintln!("cannot start python worker: {}", e);
                    return;
                }
            }
            match self.worker.as_mut().unwrap().request(code) {
                Ok(o) => {
                    print!("{}", o);
                    let _ = out.lock().flush();
                }
                Err(e) => {
                    eprintln!("cannot start python worker: {}", e);
                    if let Some(w) = self.worker.take() {
                        w.kill();
                    }
                }
            }
            return;
        }
        match self.worker.as_mut().unwrap().request(code) {
            Ok(o) => {
                print!("{}", o);
                let _ = out.lock().flush();
                return;
            }
            Err(e) => eprintln!("python worker error: {}", e),
        }
        if let Some(w) = self.worker.take() {
            w.kill();
        }
        let mut w = match Worker::spawn(&self.python) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("cannot restart python worker: {}", e);
                return;
            }
        };
        if let Some(rebuild) = self.session.rebuild_code() {
            eprintln!("(python worker restarted — definitions re-executed to rebuild state)");
            match w.request(&rebuild) {
                Ok(o) => {
                    print!("{}", o);
                    let _ = out.lock().flush();
                }
                Err(e) => {
                    eprintln!("cannot restart python worker: {}", e);
                    w.kill();
                    return;
                }
            }
        } else {
            self.session.sent.clear();
        }
        match w.request(code) {
            Ok(o) => {
                print!("{}", o);
                let _ = out.lock().flush();
                self.worker = Some(w);
            }
            Err(e) => {
                eprintln!("python worker failed again: {}", e);
                w.kill();
            }
        }
    }

    fn eval(&mut self, input: &str, block: bool) {
        match self.session.eval(input, block) {
            Ok(r) => {
                for e in &r.echoes {
                    println!("{}", e);
                }
                if !r.code.is_empty() {
                    self.run(&r.code);
                }
            }
            Err(EvalErr::Parse(s)) => eprintln!("{}", s),
            Err(EvalErr::Type(errs)) => {
                for e in errs {
                    eprintln!("{}", e);
                }
            }
            Err(EvalErr::Compile(echoes, errs)) => {
                for e in &echoes {
                    println!("{}", e);
                }
                for e in errs {
                    eprintln!("{}", e);
                }
            }
        }
    }
}

enum Line {
    Text(String),
    Eof,
    Invalid,
}

fn read_line(stdin: &mut std::io::StdinLock) -> Line {
    let mut buf = Vec::new();
    match stdin.read_until(b'\n', &mut buf) {
        Ok(0) => Line::Eof,
        Ok(_) => match String::from_utf8(buf) {
            Ok(s) => Line::Text(s.trim_end_matches('\n').trim_end_matches('\r').to_string()),
            Err(_) => Line::Invalid,
        },
        Err(_) => Line::Invalid,
    }
}

fn prompt(p: &str) {
    print!("{}", p);
    let _ = std::io::stdout().flush();
}

pub fn run_repl() -> ! {
    let python = match crate::find_python(false) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("{}", e);
            std::process::exit(1);
        }
    };
    println!("Pyfun REPL — :help for commands, :quit to exit.");
    let mut repl = Repl { session: Session::new(Mode::Repl), python, worker: None };
    let stdin = std::io::stdin();
    let mut lock = stdin.lock();
    loop {
        prompt("pyfun> ");
        let line = match read_line(&mut lock) {
            Line::Eof => {
                println!();
                break;
            }
            Line::Invalid => {
                eprintln!("input error: stream did not contain valid UTF-8");
                break;
            }
            Line::Text(t) => t,
        };
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        if t.starts_with(':') {
            let (word, rest) = match t.find(|c: char| c.is_whitespace()) {
                Some(i) => (&t[..i], t[i..].trim()),
                None => (t, ""),
            };
            match word {
                ":" => continue,
                ":quit" | ":q" | ":exit" => {
                    let _ = std::io::stdout().flush();
                    if let Some(w) = repl.worker.take() {
                        w.kill();
                    }
                    std::process::exit(0);
                }
                ":help" | ":h" | ":?" => println!("{}", HELP),
                ":reset" => {
                    repl.session.reset();
                    if let Some(w) = repl.worker.take() {
                        w.kill();
                    }
                    println!("(session reset)");
                }
                ":type" | ":t" => {
                    if rest.is_empty() {
                        println!("usage: :type <expression>");
                    } else {
                        match repl.session.type_of(rest) {
                            Ok(s) => println!("{}", s),
                            Err(errs) => {
                                for e in errs {
                                    if e.starts_with('(') {
                                        println!("{}", e);
                                    } else {
                                        eprintln!("{}", e);
                                    }
                                }
                            }
                        }
                    }
                }
                ":{" => {
                    let mut lines: Vec<String> = Vec::new();
                    let mut eof = false;
                    loop {
                        prompt("...... ");
                        match read_line(&mut lock) {
                            Line::Eof => {
                                eof = true;
                                break;
                            }
                            Line::Invalid => {
                                eprintln!("input error: stream did not contain valid UTF-8");
                                std::process::exit(0);
                            }
                            Line::Text(l) => {
                                if l.trim() == ":}" {
                                    break;
                                }
                                lines.push(l);
                            }
                        }
                    }
                    // (each of the block's lines keeps its line end)
                    let text: String = lines.iter().map(|l| format!("{}\n", l)).collect();
                    if !text.trim().is_empty() {
                        repl.eval(&text, true);
                    }
                    if eof {
                        // the block ended at end of input
                        prompt("pyfun> ");
                        println!();
                        break;
                    }
                }
                _ => println!("unknown command `{}` — :help for the list", word),
            }
            continue;
        }
        repl.eval(t, false);
    }
    if let Some(w) = repl.worker.take() {
        w.kill();
    }
    std::process::exit(0);
}
