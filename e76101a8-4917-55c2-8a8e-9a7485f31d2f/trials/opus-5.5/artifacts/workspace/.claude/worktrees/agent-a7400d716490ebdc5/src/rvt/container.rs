//! A Revit file's container: a Compound File opened with limits, its streams listed and read.

use super::cfb::{self, Cfb};

pub const MAX_STREAMS: usize = 1024;
pub const MAX_STREAM_LEN: u64 = 512 << 20;
const SIGNATURE: [u8; 8] = [0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1];

pub struct Container {
    cfb: Cfb,
    /// The streams, by path (no leading slash), in the order of their paths.
    pub streams: Vec<(String, usize)>,
}

/// Opens a Revit file's container; the error is the whole message, the path first.
pub fn open(path: &str) -> Result<Container, String> {
    let meta = std::fs::metadata(path).map_err(|e| format!("{}: {}: {}", path, path, e))?;
    if meta.is_dir() {
        return Err(format!("{}: {}: is a folder, not a Revit file", path, path));
    }
    let data = std::fs::read(path).map_err(|e| format!("{}: {}: {}", path, path, e))?;
    if data.is_empty() {
        return Err(format!("{}: the file is empty, so it is not a Revit file", path));
    }
    let head = &data[..data.len().min(8)];
    if head.len() < 8 || head != SIGNATURE {
        let hex: Vec<String> = head.iter().map(|b| format!("{:02X}", b)).collect();
        return Err(format!(
            "{}: not a Revit file: it starts with {}, not the Compound File signature D0 CF 11 E0 A1 B1 1A E1 that Revit files start with",
            path,
            hex.join(" ")
        ));
    }
    let cfb = cfb::open(data).map_err(|e| format!("{}: the Compound File container is damaged: {}", path, e))?;
    let mut streams: Vec<(String, usize)> =
        cfb.walk().into_iter().filter(|(_, i)| cfb::is_stream(&cfb.entries[*i])).collect();
    // by path, as the original lists them
    streams.sort_by(|a, b| a.0.cmp(&b.0));
    if streams.len() > MAX_STREAMS {
        return Err(format!("{}: the file has {} streams, over the limit of {}", path, streams.len(), MAX_STREAMS));
    }
    Ok(Container { cfb, streams })
}

impl Container {
    pub fn has(&self, name: &str) -> bool {
        self.streams.iter().any(|(p, _)| p == name)
    }

    /// The paths of the streams.
    pub fn names(&self) -> Vec<String> {
        self.streams.iter().map(|(p, _)| p.clone()).collect()
    }

    /// The stream's bytes, if the container lists it: opened by its path, as the original opens
    /// it (so a path the listing gives may name another entry, or none).
    pub fn read(&self, name: &str) -> Result<Option<Vec<u8>>, String> {
        if !self.streams.iter().any(|(p, _)| p == name) {
            return Ok(None);
        }
        let idx = self.cfb.open_stream(name).map_err(|e| format!("stream {} cannot be read: {}", name, e))?;
        let len = self.cfb.entries[idx].len;
        if len > MAX_STREAM_LEN {
            return Err(format!("stream {} is {} bytes, over the limit of {}", name, len, MAX_STREAM_LEN));
        }
        self.cfb.read_stream(idx).map(Some).map_err(|e| format!("stream {} cannot be read: {}", name, e))
    }
}
