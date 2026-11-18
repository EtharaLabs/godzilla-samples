//! The MCP server (`bimcraft-cli mcp`): JSON-RPC over stdio, on a headless session or bridged
//! to a desktop window's control port (`--connect`).

/// `bimcraft-cli mcp [--read-only] [FILE | --connect [PORT]]`; never returns.
pub fn main(args: &[String]) -> ! {
    let _ = args;
    std::process::exit(1);
}
