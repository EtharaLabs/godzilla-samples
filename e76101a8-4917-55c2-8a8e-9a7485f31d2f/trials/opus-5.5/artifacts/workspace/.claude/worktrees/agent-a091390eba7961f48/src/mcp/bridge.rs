//! The bridge (`mcp --connect [PORT]`): the tools run on the project a desktop window has open,
//! through its control port.
//!
//! The window listens on 127.0.0.1 and writes its port and a token to `bridge.json` beside the
//! favorites. Each request is one line of JSON (keys sorted) holding the token, and each reply
//! one line: `{"ok": result}` or `{"error": "message"}`. The first request is
//! `{"op": "hello", "token": …}`, answered `{"ok": {"app": "bimcraft", "read_only"?: true}}`;
//! then `{"op": "execute", "command", "params", "token"}` for a command and
//! `{"op": "script", "text", "atomic", "token"}` for a script, each with `"read_only": true`
//! when the server was started with --read-only. The window answers between its frames, so
//! the server waits for each reply as long as it takes.

use crate::json::{Map, Num, Value};
use std::io::{BufRead, BufReader, Write};
use std::net::TcpStream;
use std::path::PathBuf;

pub struct Bridge {
    stream: TcpStream,
    reader: BufReader<TcpStream>,
    token: String,
    /// Asked for with --read-only: each request says so.
    pub read_only: bool,
    /// The window lets agents only read its project (its hello said so).
    pub window_read_only: bool,
}

/// Where `bridge.json` is: beside the favorites, which `BIMCRAFT_FAVORITES` names, else in the
/// configuration folder (`$XDG_CONFIG_HOME/bimcraft`, else `~/.config/bimcraft`).
pub fn bridge_path() -> Option<PathBuf> {
    let set = |k: &str| std::env::var_os(k).filter(|v| !v.is_empty());
    if let Some(f) = set("BIMCRAFT_FAVORITES") {
        return Some(PathBuf::from(f).with_file_name("bridge.json"));
    }
    if let Some(x) = set("XDG_CONFIG_HOME") {
        return Some(PathBuf::from(x).join("bimcraft").join("bridge.json"));
    }
    let home = set("HOME")?;
    Some(PathBuf::from(home).join(".config").join("bimcraft").join("bridge.json"))
}

/// The port and the token a bridge file holds, if it holds them.
fn read_bridge_file(path: &PathBuf) -> Option<(u16, String)> {
    let text = std::fs::read_to_string(path).ok()?;
    let v = crate::json::parse(&text).ok()?;
    let port = v.get("port").and_then(|p| p.as_u64()).filter(|p| *p <= u16::MAX as u64)? as u16;
    let token = v.get("token").and_then(|t| t.as_str()).filter(|t| !t.is_empty())?.to_string();
    Some((port, token))
}

/// Writes a value as JSON a piece at a time, as a serializer writing straight to the stream
/// does (a window that has gone is found by the write that fails, as it would be).
fn emit(w: &mut impl Write, v: &Value) -> std::io::Result<()> {
    match v {
        Value::Null => w.write_all(b"null"),
        Value::Bool(b) => w.write_all(if *b { b"true" } else { b"false" }),
        Value::Num(n) => {
            let s = match n {
                Num::U(u) => u.to_string(),
                Num::I(i) => i.to_string(),
                Num::F(f) => crate::json::fmt_f64(*f),
            };
            w.write_all(s.as_bytes())
        }
        Value::Str(s) => emit_str(w, s),
        Value::Arr(a) => {
            w.write_all(b"[")?;
            for (i, x) in a.iter().enumerate() {
                if i > 0 {
                    w.write_all(b",")?;
                }
                emit(w, x)?;
            }
            w.write_all(b"]")
        }
        Value::Obj(m) => {
            w.write_all(b"{")?;
            for (i, (k, x)) in m.items.iter().enumerate() {
                if i > 0 {
                    w.write_all(b",")?;
                }
                emit_str(w, k)?;
                w.write_all(b":")?;
                emit(w, x)?;
            }
            w.write_all(b"}")
        }
    }
}

fn emit_str(w: &mut impl Write, s: &str) -> std::io::Result<()> {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    w.write_all(b"\"")?;
    let bytes = s.as_bytes();
    let mut start = 0;
    for (i, &b) in bytes.iter().enumerate() {
        let esc: Option<&[u8]> = match b {
            b'"' => Some(b"\\\""),
            b'\\' => Some(b"\\\\"),
            b'\n' => Some(b"\\n"),
            b'\r' => Some(b"\\r"),
            b'\t' => Some(b"\\t"),
            0x08 => Some(b"\\b"),
            0x0c => Some(b"\\f"),
            0..=0x1f => None,
            _ => continue,
        };
        if start < i {
            w.write_all(&bytes[start..i])?;
        }
        match esc {
            Some(e) => w.write_all(e)?,
            None => w.write_all(&[b'\\', b'u', b'0', b'0', HEX[(b >> 4) as usize], HEX[(b & 0xf) as usize]])?,
        }
        start = i + 1;
    }
    if start < bytes.len() {
        w.write_all(&bytes[start..])?;
    }
    w.write_all(b"\"")
}

fn obj(items: Vec<(&str, Value)>) -> Value {
    let mut m = Map::new();
    for (k, v) in items {
        m.insert(k, v);
    }
    Value::Obj(m).sorted()
}

impl Bridge {
    /// What `new_model` and `open` say on a window's project.
    pub const REPLACES_PROJECT: &'static str = "that would replace the project the window has open, which is the user's: an agent never starts or opens a project in a window; the user does, with File > New and File > Open (or run `bimcraft-cli mcp` without --connect for a project of the agent's own)";

    /// Finds the window (on `port`, or the bridge file's), connects and says hello.
    pub fn connect(port: Option<u16>, read_only: bool) -> Result<Bridge, String> {
        let path = bridge_path().ok_or_else(|| "there is no folder for the bridge file here: set BIMCRAFT_FAVORITES".to_string())?;
        let shown = path.display().to_string();
        let (file_port, token) = read_bridge_file(&path).ok_or_else(|| {
            format!("{}: no window has opened a control port (start one with `bimcraft --control 0`)", shown)
        })?;
        if let Some(p) = port {
            if p != file_port {
                return Err(format!(
                    "{} has the token of the window on port {}, not {}: start that window with `--control {}` again, or connect without a port",
                    shown, file_port, p, p
                ));
            }
        }
        let stream = TcpStream::connect(("127.0.0.1", file_port)).map_err(|e| {
            format!(
                "no window answers on port {}: {} (is it still open? the bridge file may be left from one that closed)",
                file_port, e
            )
        })?;
        // each piece goes as it is written, as the window reads a line
        let _ = stream.set_nodelay(true);
        let reader = BufReader::new(stream.try_clone().map_err(|e| e.to_string())?);
        let mut b = Bridge { stream, reader, token, read_only, window_read_only: false };
        let hello = obj(vec![("op", Value::s("hello")), ("token", Value::Str(b.token.clone()))]);
        let reply = b.request(&hello)?;
        if reply.get("app").and_then(|a| a.as_str()) != Some("bimcraft") {
            return Err(format!("port {} is not a BIMCraft window", file_port));
        }
        b.window_read_only = reply.get("read_only").and_then(|r| r.as_bool()) == Some(true);
        Ok(b)
    }

    /// Sends one request and waits for its reply: the result, or the window's error.
    fn request(&mut self, req: &Value) -> Result<Value, String> {
        let closed = |e: std::io::Error| format!("the window closed the connection ({})", e);
        emit(&mut self.stream, req).map_err(closed)?;
        self.stream.write_all(b"\n").map_err(closed)?;
        let mut line = String::new();
        let n = self.reader.read_line(&mut line).map_err(|e| match e.kind() {
            // a reply that is not text, or none in time: the window is there but said nothing
            std::io::ErrorKind::InvalidData | std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock => {
                format!("the window did not answer: {}", e)
            }
            _ => closed(e),
        })?;
        if n == 0 {
            return Err("the window closed the connection".into());
        }
        let v = crate::json::parse(&line).map_err(|e| format!("the window's reply is not JSON: {}", e))?;
        if let Some(ok) = v.get("ok") {
            return Ok(ok.clone());
        }
        if let Some(e) = v.get("error").and_then(|e| e.as_str()) {
            return Err(e.to_string());
        }
        Err("the window's reply says neither ok nor error".into())
    }

    fn with_access(&self, mut items: Vec<(&'static str, Value)>) -> Value {
        if self.read_only {
            items.push(("read_only", Value::Bool(true)));
        }
        items.push(("token", Value::Str(self.token.clone())));
        obj(items)
    }

    /// A command, run on the window's session as a button runs it.
    pub fn execute(&mut self, cmd: &str, params: Value) -> Result<Value, String> {
        let req = self.with_access(vec![("command", Value::s(cmd)), ("op", Value::s("execute")), ("params", params)]);
        self.request(&req)
    }

    /// A script, which the window reads through before it runs; its results.
    pub fn script(&mut self, text: &str, atomic: bool) -> Result<Value, String> {
        let req = self.with_access(vec![("atomic", Value::Bool(atomic)), ("op", Value::s("script")), ("text", Value::s(text))]);
        self.request(&req)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn emits_as_compact() {
        let v = crate::json::parse(r#"{"a":[1,-2,0.5,"x\n\u0001é"],"b":{},"c":[],"d":null,"e":true}"#).unwrap();
        let mut out = Vec::new();
        emit(&mut out, &v).unwrap();
        assert_eq!(String::from_utf8(out).unwrap(), v.to_compact());
    }
}
