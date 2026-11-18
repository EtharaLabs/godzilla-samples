//! JSON-RPC 2.0 as the server speaks it, and its tools, on either backend.

use super::{bridge::Bridge, local::Local, text};
use crate::json::{Map, Value};

/// Where the tools run: a session of the server's own, or a window's.
pub enum Backend {
    Local(Local),
    Bridge(Bridge),
}

impl Backend {
    fn execute(&mut self, cmd: &str, params: Value) -> Result<Value, String> {
        match self {
            Backend::Local(l) => l.execute(cmd, &params),
            Backend::Bridge(b) => b.execute(cmd, params),
        }
    }
    /// A script's results, one for each line run.
    fn script(&mut self, text: &str, atomic: bool) -> Result<Value, String> {
        match self {
            Backend::Local(l) => l.script(text, atomic),
            Backend::Bridge(b) => b.script(text, atomic),
        }
    }
    fn new_model(&mut self, args: Value) -> Result<Value, String> {
        match self {
            Backend::Local(l) => l.new_model(&args),
            Backend::Bridge(_) => Err(Bridge::REPLACES_PROJECT.to_string()),
        }
    }
    fn open(&mut self, path: &Value) -> Result<Value, String> {
        match self {
            Backend::Local(l) => l.open_tool(path),
            Backend::Bridge(_) => Err(Bridge::REPLACES_PROJECT.to_string()),
        }
    }
    fn instructions(&self) -> String {
        let (bridged, read_only) = match self {
            Backend::Local(l) => (false, l.read_only),
            Backend::Bridge(b) => (true, b.read_only || b.window_read_only),
        };
        let mut s = text::INSTRUCTIONS.to_string();
        if bridged {
            s.push_str(text::BRIDGE_NOTE);
        }
        if read_only {
            s.push_str(text::READ_ONLY_NOTE);
        }
        s
    }
}

/// The protocol versions the server speaks; any other asked for gets the last.
const PROTOCOL_VERSIONS: [&str; 3] = ["2024-11-05", "2025-03-26", "2025-06-18"];

const TOOL_NAMES: [&str; 10] = [
    "execute",
    "script",
    "list_commands",
    "inspect_model",
    "query_elements",
    "schedule",
    "render",
    "new_model",
    "open",
    "save",
];

/// The parameters `render` is sent: these, and only these, null where the agent gives none.
const RENDER_KEYS: [&str; 11] = [
    "azimuth",
    "ceiling",
    "elevation",
    "family",
    "height",
    "mode",
    "path",
    "type",
    "view",
    "wall_thickness",
    "width",
];

pub struct Server {
    pub backend: Backend,
}

type RpcErr = (i64, String);

fn obj(items: Vec<(&str, Value)>) -> Value {
    let mut m = Map::new();
    for (k, v) in items {
        m.insert(k, v);
    }
    Value::Obj(m)
}

fn error_reply(id: Value, code: i64, message: &str) -> Value {
    obj(vec![
        ("error", obj(vec![("code", Value::i(code)), ("message", Value::s(message))])),
        ("id", id),
        ("jsonrpc", Value::s("2.0")),
    ])
}

/// A tool's result: its text (or a picture and its caption), and whether it is an error.
fn tool_text(text: String, is_error: bool) -> Value {
    let mut items = vec![("content", Value::Arr(vec![obj(vec![("text", Value::Str(text)), ("type", Value::s("text"))])]))];
    if is_error {
        items.push(("isError", Value::Bool(true)));
    }
    obj(items)
}

fn tool_result(r: Result<Value, String>) -> Value {
    match r {
        Ok(v) => tool_text(v.sorted().to_pretty(), false),
        Err(e) => tool_text(e, true),
    }
}

impl Server {
    pub fn new(backend: Backend) -> Server {
        Server { backend }
    }

    /// The reply to a line (a message or a batch of them); none to notifications and replies.
    pub fn handle_line(&mut self, line: &str) -> Option<Value> {
        let v = match crate::json::parse(line) {
            Ok(v) => v,
            Err(e) => return Some(error_reply(Value::Null, -32700, &format!("parse error: {}", e))),
        };
        match v {
            Value::Arr(items) => {
                if items.is_empty() {
                    return Some(error_reply(Value::Null, -32600, "empty batch"));
                }
                let out: Vec<Value> = items.iter().filter_map(|m| self.handle_message(m)).collect();
                if out.is_empty() {
                    None
                } else {
                    Some(Value::Arr(out))
                }
            }
            m => self.handle_message(&m),
        }
    }

    fn handle_message(&mut self, m: &Value) -> Option<Value> {
        let Some(o) = m.as_obj() else {
            return Some(error_reply(Value::Null, -32600, "a message must be an object"));
        };
        let id = o.get("id").cloned();
        let Some(method) = o.get("method").and_then(|x| x.as_str()) else {
            // a reply to something of ours: there is nothing it answers
            if o.contains("result") || o.contains("error") {
                return None;
            }
            return Some(error_reply(id.unwrap_or(Value::Null), -32600, "missing `method`"));
        };
        // a notification is never answered, nor acted on
        let id = id?;
        match self.dispatch(method, o.get("params")) {
            Ok(result) => Some(obj(vec![("id", id), ("jsonrpc", Value::s("2.0")), ("result", result)])),
            Err((code, msg)) => Some(error_reply(id, code, &msg)),
        }
    }

    fn dispatch(&mut self, method: &str, params: Option<&Value>) -> Result<Value, RpcErr> {
        match method {
            "initialize" => {
                let asked = params.and_then(|p| p.get("protocolVersion")).and_then(|v| v.as_str());
                let version = match asked {
                    Some(v) if PROTOCOL_VERSIONS.contains(&v) => v,
                    _ => PROTOCOL_VERSIONS[PROTOCOL_VERSIONS.len() - 1],
                };
                Ok(obj(vec![
                    ("capabilities", obj(vec![("tools", obj(vec![("listChanged", Value::Bool(false))]))])),
                    ("instructions", Value::Str(self.backend.instructions())),
                    ("protocolVersion", Value::s(version)),
                    (
                        "serverInfo",
                        obj(vec![
                            ("name", Value::s("bimcraft")),
                            ("title", Value::s("BIMCraft")),
                            ("version", Value::s(crate::VERSION)),
                        ]),
                    ),
                ]))
            }
            "ping" => Ok(Value::obj()),
            "tools/list" => Ok(obj(vec![("tools", crate::json::parse(text::TOOLS).unwrap())])),
            "tools/call" => self.call_tool(params),
            _ => Err((-32601, format!("method `{}` not found", method))),
        }
    }

    fn call_tool(&mut self, params: Option<&Value>) -> Result<Value, RpcErr> {
        let Some(name) = params.and_then(|p| p.get("name")).and_then(|v| v.as_str()) else {
            return Err((-32602, "missing tool `name`".into()));
        };
        if !TOOL_NAMES.contains(&name) {
            return Err((-32602, format!("unknown tool `{}`", name)));
        }
        let args = match params.and_then(|p| p.get("arguments")) {
            None | Some(Value::Null) => Map::new(),
            Some(Value::Obj(m)) => m.clone(),
            Some(_) => return Err((-32602, format!("the arguments of `{}` must be an object", name))),
        };
        // a key given as null is as good as none
        let given = |k: &str| args.get(k).filter(|v| !v.is_null());
        let b = &mut self.backend;
        Ok(match name {
            "execute" => {
                let Some(command) = given("command") else {
                    return Err((-32602, "`execute` needs `command`".into()));
                };
                let command = command.as_str().unwrap_or("").to_string();
                let p = args.get("params").cloned().unwrap_or_else(Value::obj);
                tool_result(b.execute(&command, p))
            }
            "script" => {
                let Some(text) = given("text") else {
                    return Err((-32602, "`script` needs `text`".into()));
                };
                let text = text.as_str().unwrap_or("").to_string();
                let atomic = match given("atomic") {
                    None => false,
                    Some(Value::Bool(x)) => *x,
                    Some(v) => return Err((-32602, format!("`atomic` is true or false, not {}", v.to_compact()))),
                };
                tool_result(b.script(&text, atomic).map(|r| obj(vec![("results", r)])))
            }
            "list_commands" => {
                let filter = args.get("filter").and_then(|v| v.as_str());
                tool_result(Ok(list_commands(filter)))
            }
            "inspect_model" => tool_result(b.execute("inspect", Value::obj())),
            "query_elements" => tool_result(b.execute("elements", Value::Obj(args))),
            "schedule" => tool_result(b.execute("schedule", Value::Obj(args))),
            "render" => {
                let mut p = Map::new();
                for k in RENDER_KEYS {
                    p.insert(k, args.get(k).cloned().unwrap_or(Value::Null));
                }
                match b.execute("render", Value::Obj(p)) {
                    Ok(v) => render_content(&v),
                    Err(e) => tool_text(e, true),
                }
            }
            "new_model" => tool_result(b.new_model(Value::Obj(args))),
            "open" => {
                let Some(path) = given("path") else {
                    return Err((-32602, "`open` needs `path`".into()));
                };
                let path = path.clone();
                tool_result(b.open(&path))
            }
            "save" => tool_result(b.execute("save", Value::Obj(args))),
            _ => unreachable!(),
        })
    }
}

/// The catalog, or the commands whose id, label or a shortcut holds `filter` (in any case).
pub fn list_commands(filter: Option<&str>) -> Value {
    let all = crate::json::parse(crate::catalog::CATALOG).unwrap();
    let Some(f) = filter else { return all };
    let f = f.to_ascii_lowercase();
    let holds = |v: Option<&Value>| v.and_then(|x| x.as_str()).map(|s| s.to_ascii_lowercase().contains(&f)).unwrap_or(false);
    let list = all.as_arr().cloned().unwrap_or_default();
    Value::Arr(
        list.into_iter()
            .filter(|c| {
                holds(c.get("id"))
                    || holds(c.get("label"))
                    || c.get("aliases").and_then(|a| a.as_arr()).map(|a| a.iter().any(|x| holds(Some(x)))).unwrap_or(false)
            })
            .collect(),
    )
}

/// What `render` gives the agent: the picture, if it came back as one, and a line saying what it
/// is: `Level 1 (plan), 1600 x 1000 px`, `3D view from -45° round, 30° up, …`, `…, written to x.png`.
pub fn render_content(v: &Value) -> Value {
    let mut content = Vec::new();
    if let Some(png) = v.get("pngBase64").and_then(|x| x.as_str()) {
        content.push(obj(vec![
            ("data", Value::s(png)),
            ("mimeType", Value::s("image/png")),
            ("type", Value::s("image")),
        ]));
    }
    content.push(obj(vec![("text", Value::Str(render_caption(v))), ("type", Value::s("text"))]));
    obj(vec![("content", Value::Arr(content))])
}

pub fn render_caption(v: &Value) -> String {
    let kind = v.get("kind").and_then(|x| x.as_str());
    let mut s = if kind == Some("3D view") {
        let deg = |k: &str| v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0);
        format!("3D view from {}° round, {}° up", deg("azimuth"), deg("elevation"))
    } else {
        let view = v.get("view").and_then(|x| x.as_str()).unwrap_or("");
        match kind {
            Some(k) => format!("{} ({})", view, k),
            None => view.to_string(),
        }
    };
    if let (Some(w), Some(h)) = (v.get("width").and_then(|x| x.as_u64()), v.get("height").and_then(|x| x.as_u64())) {
        s.push_str(&format!(", {} x {} px", w, h));
    }
    if let Some(p) = v.get("path").and_then(|x| x.as_str()) {
        s.push_str(&format!(", written to {}", p));
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cap(s: &str) -> String {
        render_caption(&crate::json::parse(s).unwrap())
    }

    #[test]
    fn captions() {
        assert_eq!(cap(r#"{"kind":"plan","view":"Level 1","width":100,"height":80}"#), "Level 1 (plan), 100 x 80 px");
        assert_eq!(cap(r#"{"kind":"3D view","azimuth":-45.0,"elevation":30.0}"#), "3D view from -45° round, 30° up");
        assert_eq!(cap(r#"{"kind":"3D view","azimuth":1e20,"elevation":-0.0}"#), "3D view from 100000000000000000000° round, -0° up");
        assert_eq!(cap(r#"{"view":"L","width":100.5,"height":80}"#), "L");
        assert_eq!(cap(r#"{"path":"x.png"}"#), ", written to x.png");
        assert_eq!(cap(r#"{"view":"","kind":""}"#), " ()");
        assert_eq!(cap("5"), "");
    }

    #[test]
    fn filters() {
        let ids = |f: &str| -> Vec<String> {
            list_commands(Some(f)).as_arr().unwrap().iter().map(|c| c.get("id").unwrap().as_str().unwrap().to_string()).collect()
        };
        assert_eq!(ids("WA"), vec!["wall", "wall_by_face", "strip_footing", "water_size"]);
        assert_eq!(ids("fw"), vec!["strip_footing"]);
        assert!(ids("\u{212a}").is_empty());
    }
}
