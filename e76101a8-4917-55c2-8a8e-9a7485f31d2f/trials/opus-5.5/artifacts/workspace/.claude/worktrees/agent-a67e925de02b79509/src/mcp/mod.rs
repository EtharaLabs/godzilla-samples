//! The MCP server (`bimcraft-cli mcp`): JSON-RPC over stdio, on a headless session or bridged
//! to a desktop window's control port (`--connect`).
//!
//! One JSON-RPC message (or batch) per line in, one reply line out, keys sorted. The tools run
//! on a [`local::Local`] session of the server's own, or are sent to a window by a
//! [`bridge::Bridge`]; [`rpc`] says the protocol and the tools in terms of either.

pub mod bridge;
pub mod local;
pub mod rpc;
pub mod text;

use std::io::{BufRead, Write};

pub const USAGE: &str = "usage: bimcraft-cli mcp [--read-only] [FILE | --connect [PORT]]";

/// What the arguments ask for.
#[derive(Debug, PartialEq)]
pub struct Args {
    pub read_only: bool,
    pub file: Option<String>,
    /// `--connect`, and the port it names, if it names one.
    pub connect: Option<Option<u16>>,
}

/// Reads `[--read-only] [FILE | --connect [PORT]]`, saying the first thing wrong.
pub fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut out = Args { read_only: false, file: None, connect: None };
    let mut i = 0;
    while i < args.len() {
        let a = args[i].as_str();
        if a == "--read-only" {
            out.read_only = true;
        } else if a == "--connect" && out.connect.is_none() {
            let mut port = None;
            if let Some(next) = args.get(i + 1) {
                if !next.starts_with("--") {
                    match next.parse::<u16>() {
                        Ok(p) => port = Some(p),
                        Err(_) => return Err(format!("`{}` is not a port: a number up to 65535", next)),
                    }
                    i += 1;
                }
            }
            out.connect = Some(port);
        } else if a.starts_with('-') {
            return Err(format!("`{}`: {}", a, USAGE));
        } else if out.file.is_some() {
            return Err(USAGE.to_string());
        } else {
            out.file = Some(a.to_string());
        }
        i += 1;
    }
    if out.connect.is_some() && out.file.is_some() {
        return Err(format!("a window has its own project: --connect takes no FILE ({})", USAGE));
    }
    Ok(out)
}

fn fail(msg: &str) -> ! {
    eprintln!("bimcraft-cli mcp: {}", msg);
    std::process::exit(1);
}

/// `bimcraft-cli mcp [--read-only] [FILE | --connect [PORT]]`; never returns.
pub fn main(args: &[String]) -> ! {
    let a = match parse_args(args) {
        Ok(a) => a,
        Err(e) => fail(&e),
    };
    let backend = match a.connect {
        Some(port) => match bridge::Bridge::connect(port, a.read_only) {
            Ok(b) => rpc::Backend::Bridge(b),
            Err(e) => fail(&e),
        },
        None => {
            let mut l = local::Local::new(a.read_only);
            if let Some(f) = &a.file {
                if let Err(e) = l.open_file(f) {
                    fail(&e);
                }
            }
            rpc::Backend::Local(l)
        }
    };
    let mut server = rpc::Server::new(backend);
    serve(&mut server)
}

/// Answers each line of stdin on stdout until stdin ends.
fn serve(server: &mut rpc::Server) -> ! {
    let stdin = std::io::stdin();
    let mut input = stdin.lock();
    let stdout = std::io::stdout();
    let mut line = String::new();
    loop {
        line.clear();
        match input.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => {}
            Err(e) => fail(&e.to_string()),
        }
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        if let Some(reply) = server.handle_line(t) {
            let mut out = stdout.lock();
            let mut s = reply.sorted().to_compact();
            s.push('\n');
            if let Err(e) = out.write_all(s.as_bytes()).and_then(|_| out.flush()) {
                fail(&e.to_string());
            }
        }
    }
    std::process::exit(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn p(a: &[&str]) -> Result<Args, String> {
        parse_args(&a.iter().map(|s| s.to_string()).collect::<Vec<_>>())
    }

    #[test]
    fn args() {
        assert_eq!(p(&[]).unwrap(), Args { read_only: false, file: None, connect: None });
        assert_eq!(p(&["--connect", "--read-only"]).unwrap().connect, Some(None));
        assert_eq!(p(&["--connect", "+80"]).unwrap().connect, Some(Some(80)));
        assert_eq!(p(&["--connect", "-1"]).unwrap_err(), "`-1` is not a port: a number up to 65535");
        assert_eq!(p(&["a", "b", "--bogus"]).unwrap_err(), USAGE);
        assert_eq!(p(&["--connect", "--connect"]).unwrap_err(), format!("`--connect`: {}", USAGE));
        assert!(p(&["--connect", "5555", "6666"]).unwrap_err().starts_with("a window has its own project"));
        assert_eq!(p(&["--read-only", "--read-only", "x"]).unwrap().file.as_deref(), Some("x"));
    }
}
