//! A Revit file read for its elements: the schema, the declared ElementIds, the partitions and
//! their records, in the order the checks are made.

use super::container::Container;
use super::elemtable::{self, ElemTable};
use super::gzip;
use super::records::{self, Record, Tags};
use super::schema::{self, Schema};

pub struct Part {
    pub name: String,
    /// The number in `Partitions/NN`, if it is one.
    pub number: Option<u64>,
    pub data: Vec<u8>,
}

pub struct Doc {
    pub release: u32,
    pub schema: Schema,
    pub table: ElemTable,
    pub parts: Vec<Part>,
    pub records: Vec<Record>,
    pub tags: Tags,
    pub plane: u16,
}

impl Doc {
    /// Ids are `u64` from 2024, `u32` before.
    pub fn wide(&self) -> bool {
        self.release >= 2024
    }
    pub fn declared(&self, id: u64) -> bool {
        self.table.ids.contains(&id)
    }
    /// The partitions from the highest-numbered down (the newest copy first).
    pub fn parts_newest_first(&self) -> Vec<usize> {
        let mut v: Vec<usize> = (0..self.parts.len()).collect();
        v.sort_by(|a, b| {
            let ka = self.parts[*a].number.map(|n| n as i128).unwrap_or(-1);
            let kb = self.parts[*b].number.map(|n| n as i128).unwrap_or(-1);
            kb.cmp(&ka).then(a.cmp(b))
        });
        v
    }
}

pub fn read(c: &Container, release: u32) -> Result<Doc, String> {
    if !(2015..=2027).contains(&release) {
        return Err(format!(
            "Revit {}: this reader knows the element records of releases 2015 to 2027 and does not guess at others",
            release
        ));
    }
    let fl = c.read("Formats/Latest")?.ok_or_else(|| "the file has no stream named Formats/Latest".to_string())?;
    let fl = gzip::inflate_single("Formats/Latest", &fl)?;
    let schema = schema::parse(&fl)?;
    let need = |n: &str| -> Result<u16, String> {
        schema
            .tag(n)
            .ok_or_else(|| format!("Formats/Latest has no class {}, so the element records cannot be found", n))
    };
    let outline = need("Outline")?;
    let parents = need("ElementParents")?;
    let header = need("ElementHeader")?;
    let plane = need("Plane")?;
    let et = c.read("Global/ElemTable")?.ok_or_else(|| "the file has no stream named Global/ElemTable".to_string())?;
    let et = gzip::inflate_single("Global/ElemTable", &et)?;
    let table = elemtable::parse(&et, release)?;
    let names: Vec<String> = c.names().into_iter().filter(|n| n.starts_with("Partitions/")).collect();
    if names.is_empty() {
        return Err("the file has no Partitions stream, so it holds no elements".into());
    }
    let mut parts = Vec::new();
    for n in names {
        let raw = c.read(&n)?.unwrap_or_default();
        let m = gzip::inflate_members(&n, &raw)?;
        let number = n["Partitions/".len()..].parse::<u64>().ok();
        parts.push(Part { name: n, number, data: m.data });
    }
    let tags = Tags { outline, parents, header };
    let mut recs = Vec::new();
    for (i, p) in parts.iter().enumerate() {
        if release >= 2024 {
            let decl = |id: u64| table.ids.contains(&id);
            recs.extend(records::chain(&p.data, &tags, i, &decl));
        } else {
            recs.extend(records::markers(&p.data, &tags, i));
        }
    }
    Ok(Doc { release, schema, table, parts, records: recs, tags, plane })
}
