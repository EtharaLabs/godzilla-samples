//! Writing a project as IFC4.
//!
//! The file is written in one pass over the elements in id order, doors and windows (with
//! their openings) and what hangs on stairs and ramps after the rest, then what relates them:
//! material layer sets, the storeys' contents, the common property sets, the type objects,
//! phasing and the project's parameters.
//!
//! How an element's writer works (each kind in its own `export_*.rs`, as `impl Ex` methods):
//! - `self.add("IFCWALL(...)")` appends an entity and returns its number; entities are
//!   numbered in the order they are added, so write them in the order the file has them.
//! - Numbers go through `step::real` (lengths, areas, colours: six places, `3000.`, `0.`, a
//!   negative zero as `0.`) and `step::dir` (direction ratios: twelve places); strings through
//!   `step::st` (quoted and escaped). An element's GlobalId is `gid(its GUID)`; a relationship's
//!   or a property set's is `self.fresh()`.
//! - `placement(rel, at, xdir)`, `closed_polyline`, `open_polyline`, `quantities`, `material`
//!   (an `IfcMaterial` with its style, written once), `typed` (a type object and its
//!   occurrences, written at the end, sorted by class and name), `contain` (the storey a
//!   product is in), `finish` (called right after the product's entity: its common property
//!   set, phasing and project parameters).
//! - The original computes in plan as glam does: a unit vector is `v * (1 / length)`
//!   (`geom::V2::normalize`), points on a line are `start + dir * t`, and a point is brought into
//!   an element's axes as `((p - o).dot(x), (p - o).dot(x.perp()))`; the last bits of a result
//!   show only in the sign of a zero (`-0.` is a tiny negative), so compute as it does.

use crate::json::Value;
use crate::project::Project;
use std::collections::{BTreeMap, HashMap};

#[path = "export_step.rs"]
pub mod step;
#[path = "export_geom.rs"]
pub mod geom;
#[path = "export_walls.rs"]
pub mod walls;
#[path = "export_openings.rs"]
pub mod openings;
#[path = "export_family.rs"]
pub mod family;
#[path = "export_roofs.rs"]
pub mod roofs;
#[path = "export_rooms.rs"]
pub mod rooms;
#[path = "export_stairs.rs"]
pub mod stairs;
#[path = "export_components.rs"]
pub mod components;
#[path = "export_runs.rs"]
pub mod runs;
#[path = "export_skeleton.rs"]
pub mod skeleton;
#[path = "export_slabs.rs"]
pub mod slabs;
#[path = "export_cdt.rs"]
pub mod cdt;
#[path = "export_shaped.rs"]
pub mod shaped;
#[path = "export_csg.rs"]
pub mod csg;

use geom::*;
use step::{dir, gid, real, refs, st, Step};

/// The project as an IFC4 file's text.
pub fn export(pr: &Project, _path: &str) -> String {
    let mut ex = Ex::new(pr);
    ex.write_all();
    let mut out = String::new();
    out.push_str("ISO-10303-21;\nHEADER;\n");
    out.push_str("FILE_DESCRIPTION(('ViewDefinition [DesignTransferView]'),'2;1');\n");
    out.push_str(&format!(
        "FILE_NAME({},'{}',(''),(''),'BIMCraft 0.10.0','BIMCraft 0.10.0','');\n",
        st(&format!("{}.ifc", pr.name())),
        timestamp()
    ));
    out.push_str("FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n");
    out.push_str(&ex.st.text());
    out.push_str("ENDSEC;\nEND-ISO-10303-21;\n");
    out
}

/// Writes the project to an IFC file, as `save` does with a `.ifc` path.
/// Whether a path saves as IFC: its extension (as a path has one) is `ifc`, in any case.
pub fn is_ifc_path(path: &str) -> bool {
    std::path::Path::new(path).extension().map_or(false, |e| e.to_string_lossy().eq_ignore_ascii_case("ifc"))
}

pub fn save(pr: &Project, path: &str) -> Result<(), String> {
    let text = export(pr, path);
    std::fs::write(path, text).map_err(|e| format!("{}: {}", path, crate::commands::io_err(&e)))
}

fn timestamp() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let days = secs.div_euclid(86400);
    let rem = secs.rem_euclid(86400);
    let (y, m, d) = civil_from_days(days);
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", y, m, d, rem / 3600, rem % 3600 / 60, rem % 60)
}

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// A storey: its level's GUID, its entity and its placement.
pub struct Storey {
    pub level: u64,
    pub guid: String,
    pub ent: usize,
    pub place: usize,
    pub elevation: f64,
}

/// A type object to write at the end, with the occurrences of it.
#[derive(Default)]
pub struct TypeObj {
    /// Its name, where the key isn't it.
    pub name: Option<String>,
    /// What follows the name: `$,$,$,$,$,$,.STANDARD.`
    pub tail: String,
    pub occ: Vec<usize>,
    /// Entities written after its `IfcRelDefinesByType` (its material profile set).
    pub after: Vec<TypeExtra>,
}

/// What a type object carries besides its occurrences.
#[derive(Clone)]
pub enum TypeExtra {
    /// A material profile set of one profile: (name, material entity or none, profile entity),
    /// and the usages of it by cardinal point with the occurrences placed by each.
    Profile { material: Option<String>, profile: usize, usages: BTreeMap<i32, Vec<usize>> },
}

/// A common property set (`Pset_WallCommon`…) of an element: the properties written with
/// the element, and whether a `Status` goes in it.
pub struct Common {
    pub element: u64,
    pub product: usize,
    pub name: String,
    pub props: Vec<usize>,
    pub status: Option<String>,
}

/// The export as it goes: the file, and what later entities point back at.
pub struct Ex<'a> {
    pub pr: &'a Project,
    pub st: Step,
    /// The context of 3D bodies (`#5`), of axes (`#6`), the model's context (`#4`), the world's
    /// origin placement (`#3`) and its up direction (`#2`).
    pub body: usize,
    pub axis: usize,
    pub model: usize,
    pub origin: usize,
    pub up: usize,
    pub project: usize,
    pub building_place: usize,
    pub building: usize,
    pub storeys: Vec<Storey>,
    /// By level GUID: what each storey contains, and the spaces it aggregates.
    pub contained: BTreeMap<String, Vec<usize>>,
    pub spaces: BTreeMap<String, Vec<usize>>,
    /// Products and placements by element id, as written.
    pub products: HashMap<u64, usize>,
    pub placements: HashMap<u64, usize>,
    /// Type objects by IFC class and name.
    pub types: BTreeMap<(String, String), TypeObj>,
    /// Materials written, by name: the `IfcMaterial` and its surface style.
    pub materials: HashMap<String, (usize, usize)>,
    /// Layer set usages to write: by layer set key and offset, the occurrences.
    pub layer_sets: BTreeMap<String, usize>,
    pub layer_usages: Vec<LayerUse>,
    pub commons: Vec<Common>,
    /// The walls of the project and their outlines, by element id.
    pub walls: Vec<walls::Wall>,
    pub wall_outlines: HashMap<u64, Vec<V2>>,
    pub wall_raw_outlines: HashMap<u64, Vec<V2>>,
    /// Every product finished, in the order written: (element id, product).
    pub finished: Vec<(u64, usize)>,
    /// What shafts cut, in the order written: (element id, product, placement, unused).
    pub cuttable: Vec<(u64, usize, usize, f64)>,
    /// Section profiles written, by section.
    pub profiles: HashMap<String, usize>,
    /// Runs by the system they're in.
    pub systems: BTreeMap<String, Vec<usize>>,
    /// Reinforcing bars by the element id of their host.
    pub rebar_hosts: BTreeMap<u64, Vec<usize>>,
    /// Components with connectors: (element id, product).
    pub devices: Vec<(u64, usize)>,
    /// Stairs and ramps as written: (element id, product, its parts), railings on them added.
    pub stair_parts: Vec<(u64, usize, Vec<usize>)>,
    /// Whether the project uses phases or options, and its phases in order.
    pub phased: bool,
    /// Whether an element holds a phase or a design option (then each says its `Status`).
    pub held: bool,
    pub phases: Vec<String>,
}

/// Elements related to a layer set: a wall's or a slab's (with a usage at an offset), or a
/// covering's (the set itself).
pub struct LayerUse {
    pub kind: LayerKind,
    pub type_key: String,
    pub type_name: String,
    pub layers: Vec<Value>,
    pub offset: f64,
    pub product: usize,
}

#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum LayerKind {
    Wall,
    Slab,
    Covering,
    Roof,
}

impl<'a> Ex<'a> {
    pub fn new(pr: &'a Project) -> Ex<'a> {
        let uid = pr.get("uid").and_then(|v| v.as_u64()).unwrap_or(0);
        Ex {
            pr,
            st: Step::new(uid),
            body: 0,
            axis: 0,
            model: 0,
            origin: 0,
            up: 0,
            project: 0,
            building_place: 0,
            building: 0,
            storeys: Vec::new(),
            contained: BTreeMap::new(),
            spaces: BTreeMap::new(),
            products: HashMap::new(),
            placements: HashMap::new(),
            types: BTreeMap::new(),
            materials: HashMap::new(),
            layer_sets: BTreeMap::new(),
            layer_usages: Vec::new(),
            commons: Vec::new(),
            walls: Vec::new(),
            wall_outlines: HashMap::new(),
            wall_raw_outlines: HashMap::new(),
            finished: Vec::new(),
            cuttable: Vec::new(),
            profiles: HashMap::new(),
            systems: BTreeMap::new(),
            rebar_hosts: BTreeMap::new(),
            devices: Vec::new(),
            stair_parts: Vec::new(),
            phased: false,
            held: false,
            phases: Vec::new(),
        }
    }

    pub fn add<S: Into<String>>(&mut self, s: S) -> usize {
        self.st.add(s)
    }

    pub fn fresh(&mut self) -> String {
        self.st.fresh_gid()
    }

    fn write_all(&mut self) {
        self.write_head();
        self.write_storeys();
        self.prepare();
        self.write_elements();
        self.write_tail();
    }

    fn write_head(&mut self) {
        let o = self.st.point3(0.0, 0.0, 0.0);
        self.up = self.st.dir3(0.0, 0.0, 1.0);
        self.origin = self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", o));
        self.model = self.add(format!("IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#{},$)", self.origin));
        self.body = self.add(format!(
            "IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#{},$,.MODEL_VIEW.,$)",
            self.model
        ));
        self.axis = self.add(format!(
            "IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Axis','Model',*,*,*,*,#{},$,.GRAPH_VIEW.,$)",
            self.model
        ));
        let u1 = self.add("IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)");
        let u2 = self.add("IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.)");
        let u3 = self.add("IFCSIUNIT(*,.VOLUMEUNIT.,$,.CUBIC_METRE.)");
        let u4 = self.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)");
        let units = self.add(format!("IFCUNITASSIGNMENT(({}))", refs(&[u1, u2, u3, u4])));
        let name = st(&self.pr.name());
        let g = self.fresh();
        let project = self.add(format!("IFCPROJECT('{}',$,{},$,$,$,$,(#{}),#{})", g, name, self.model, units));
        self.project = project;
        let p = self.st.point3(0.0, 0.0, 0.0);
        let a = self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p));
        let site_place = self.add(format!("IFCLOCALPLACEMENT($,#{})", a));
        let g = self.fresh();
        let site = self.add(format!("IFCSITE('{}',$,'Site',$,$,#{},$,$,.ELEMENT.,$,$,$,$,$)", g, site_place));
        let p = self.st.point3(0.0, 0.0, 0.0);
        let a = self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p));
        self.building_place = self.add(format!("IFCLOCALPLACEMENT(#{},#{})", site_place, a));
        let g = self.fresh();
        let building = self.add(format!(
            "IFCBUILDING('{}',$,{},$,$,#{},$,$,.ELEMENT.,$,$,$)",
            g, name, self.building_place
        ));
        self.building = building;
        let g = self.fresh();
        self.add(format!("IFCRELAGGREGATES('{}',$,$,$,#{},(#{}))", g, project, site));
        let g = self.fresh();
        self.add(format!("IFCRELAGGREGATES('{}',$,$,$,#{},(#{}))", g, site, building));
    }

    fn write_storeys(&mut self) {
        let levels = crate::model::levels(self.pr);
        for l in levels {
            let e = self.pr.el(l).unwrap();
            let elev = e.get("elevation").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let guid = e.get("guid").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let name = e.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let p = self.st.point3(0.0, 0.0, elev);
            let a = self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p));
            let place = self.add(format!("IFCLOCALPLACEMENT(#{},#{})", self.building_place, a));
            let ent = self.add(format!(
                "IFCBUILDINGSTOREY('{}',$,{},$,$,#{},$,$,.ELEMENT.,{})",
                gid(&guid),
                st(&name),
                place,
                real(elev)
            ));
            self.storeys.push(Storey { level: l, guid, ent, place, elevation: elev });
        }
        // the building aggregates its storeys in the order of their GUIDs
        let mut by_guid: Vec<(&str, usize)> = self.storeys.iter().map(|s| (s.guid.as_str(), s.ent)).collect();
        by_guid.sort();
        let ids: Vec<usize> = by_guid.iter().map(|x| x.1).collect();
        if !ids.is_empty() {
            let g = self.fresh();
            let b = self.building;
            self.add(format!("IFCRELAGGREGATES('{}',$,$,$,#{},({}))", g, b, refs(&ids)));
        }
    }

    /// What the writing of elements needs from all of them first: the walls' outlines.
    fn prepare(&mut self) {
        self.prepare_phasing();
        let pr = self.pr;
        for (id, e) in &pr.elements {
            if e.get("category").and_then(|c| c.as_str()) == Some("wall") {
                self.walls.push(walls::wall_of(pr, *id, e));
            }
        }
        // the heights each wall spans: to what it is attached to, past its own top or base
        for k in 0..self.walls.len() {
            let id = self.walls[k].id;
            let Some(e) = pr.el(id) else { continue };
            let base = self.level_elev(&self.walls[k].level) + e.get("base_offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let mut z0 = base;
            let mut z1 = self.wall_top(e, base);
            for (key, up) in [("attach_top", true), ("attach_base", false)] {
                let Some(hid) = e.get(key).and_then(|v| v.as_str()).and_then(|g| pr.find_guid(g)) else { continue };
                let Some(he) = pr.el(hid) else { continue };
                if let Some((lo, hi, _)) = self.host_span(hid, he) {
                    if up {
                        z1 = z1.max(hi);
                    } else {
                        z0 = z0.min(lo);
                    }
                }
            }
            self.walls[k].z0 = z0;
            self.walls[k].z1 = z1;
        }
        let outl = walls::outlines(&self.walls);
        for (w, o) in self.walls.iter().zip(outl.into_iter()) {
            self.wall_outlines.insert(w.id, o);
        }
        let raw = walls::raw_outlines(&self.walls);
        for (w, o) in self.walls.iter().zip(raw.into_iter()) {
            self.wall_raw_outlines.insert(w.id, o);
        }
    }

    fn write_elements(&mut self) {
        let pr = self.pr;
        let mut openings = Vec::new();
        let mut hosted = Vec::new();
        for (id, e) in &pr.elements {
            let id = *id;
            let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
            match cat {
                "wall" => self.write_wall(id, e),
                "door" | "window" => openings.push(id),
                "roof" => self.write_roof(id, e),
                "room" => self.write_room(id, e),
                "stair" => self.write_stair(id, e),
                "ramp" => self.write_ramp(id, e),
                "railing" => {
                    // a railing on a stair or a ramp goes after the rest, with its host's parts
                    if e.get("host").and_then(|h| h.as_str()).map(|h| !h.is_empty()).unwrap_or(false) {
                        hosted.push(id);
                    } else {
                        self.write_railing(id, e);
                    }
                }
                "component" => self.write_component(id, e),
                "roomseparator" => self.write_separator(id, e),
                "column" | "structuralcolumn" | "footing" => self.write_column(id, e),
                "beam" | "stripfooting" | "pipe" | "duct" | "conduit" | "cabletray" | "wire" | "downconductor"
                | "groundconductor" | "cable" => self.write_run(id, e),
                "rebar" => self.write_rebar(id, e),
                "floor" => self.write_floor(id, e),
                "ceiling" => self.write_ceiling(id, e),
                "mass" => self.write_mass(id, e),
                _ => {}
            }
        }
        for id in hosted {
            let e = pr.el(id).unwrap();
            self.write_railing(id, e);
        }
        self.write_stair_aggregates();
        self.write_shafts();
        for id in openings {
            let e = pr.el(id).unwrap();
            self.write_opening(id, e);
        }
        self.write_rebar_aggregates();
    }

    fn write_tail(&mut self) {
        self.write_systems();
        self.write_layer_sets();
        self.write_containment();
        self.write_devices();
        self.write_project_parameters();
        self.write_commons();
        self.write_types();
        self.write_phasing();
    }

    /// Each element's phase and design option, and the project's phases (in a phased project).
    fn write_phasing(&mut self) {
        if !self.phased {
            return;
        }
        let pr = self.pr;
        let phases = self.phases.clone();
        let first = phases.first().cloned().unwrap_or_default();
        let mut done = self.finished.clone();
        done.sort_by_key(|x| x.0);
        for (id, product) in done {
            let Some(e) = pr.el(id) else { continue };
            let Some(ps) = e.get("params").and_then(|p| p.as_obj()) else { continue };
            let created = ps.get("Phase Created").and_then(|v| v.as_str()).and_then(|g| pr.lib_name(g));
            let demolished = ps.get("Phase Demolished").and_then(|v| v.as_str()).and_then(|g| pr.lib_name(g));
            let option = ps.get("Design Option").and_then(|v| v.as_str()).and_then(|g| pr.lib_name(g));
            if created.is_none() && demolished.is_none() && option.is_none() {
                continue;
            }
            let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
            let opening = cat == "door" || cat == "window";
            let mut props = Vec::new();
            match &created {
                Some(c) => props.push(self.add(format!("IFCPROPERTYSINGLEVALUE('Phase Created',$,IFCTEXT({}),$)", st(c)))),
                None if !opening => props.push(self.add(format!(
                    "IFCPROPERTYSINGLEVALUE('Phase Created','Implied: no phase is set for it, so it was made in the first phase',IFCTEXT({}),$)",
                    st(&first)
                ))),
                None => {}
            }
            if let Some(d) = &demolished {
                props.push(self.add(format!("IFCPROPERTYSINGLEVALUE('Phase Demolished',$,IFCTEXT({}),$)", st(d))));
            }
            if let Some(o) = &option {
                props.push(self.add(format!("IFCPROPERTYSINGLEVALUE('Design Option',$,IFCTEXT({}),$)", st(o))));
            }
            let g = self.fresh();
            let pset = self.add(format!("IFCPROPERTYSET('{}',$,'BIMCraft_Phasing',$,({}))", g, refs(&props)));
            let g = self.fresh();
            self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, product, pset));
        }
        // the project's: its phases, and what it changed of the filters, overrides and option sets
        let mut props = Vec::new();
        let list: Vec<String> = phases.iter().map(|p| format!("IFCTEXT({})", st(p))).collect();
        props.push(self.add(format!("IFCPROPERTYLISTVALUE('Phases',$,({}),$)", list.join(","))));
        if let Some(f) = pr.get("phase_filters") {
            if !f.is_null() {
                props.push(self.add(format!("IFCPROPERTYSINGLEVALUE('Phase Filters',$,IFCTEXT({}),$)", st(&f.to_compact()))));
            }
        }
        if let Some(o) = pr.get("phase_overrides") {
            if !o.is_null() {
                props.push(self.add(format!("IFCPROPERTYSINGLEVALUE('Phase Overrides',$,IFCTEXT({}),$)", st(&o.to_compact()))));
            }
        }
        if let Some(Value::Obj(sets)) = pr.get("option_sets") {
            if !sets.is_empty() {
                let mut out = crate::json::Map::new();
                for (name, set) in &sets.items {
                    let mut m = crate::json::Map::new();
                    let options = set.get("options").cloned().unwrap_or(Value::Arr(Vec::new()));
                    m.insert("options", options);
                    if let Some(pg) = set.get("primary").and_then(|v| v.as_str()) {
                        let full = pr.lib_name(pg).unwrap_or_else(|| pg.to_string());
                        let short = full.strip_prefix(&format!("{}: ", name)).map(|x| x.to_string()).unwrap_or(full);
                        m.insert("primary", Value::Str(short));
                    }
                    out.insert(name, Value::Obj(m));
                }
                props.push(self.add(format!(
                    "IFCPROPERTYSINGLEVALUE('Design Option Sets',$,IFCTEXT({}),$)",
                    st(&Value::Obj(out).to_compact())
                )));
            }
        }
        let g = self.fresh();
        let pset = self.add(format!("IFCPROPERTYSET('{}',$,'BIMCraft_Phasing',$,({}))", g, refs(&props)));
        let g = self.fresh();
        let project = self.project;
        self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, project, pset));
    }

    /// Whether the project uses phases or design options (it changed its phases, filters or
    /// overrides, has an option set, or an element holds a phase or an option), and its phases.
    fn prepare_phasing(&mut self) {
        let pr = self.pr;
        self.phases = match pr.get("phases").and_then(|p| p.as_arr()) {
            Some(a) => a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect(),
            None => vec!["Existing".to_string(), "New Construction".to_string()],
        };
        // changed: phases or filters other than a new project's in the project's language,
        // overrides, or a set of options
        let lang = pr.get("language").and_then(|l| l.as_str()).unwrap_or("en").to_string();
        let (def_phases, def_filters) = default_phasing(&lang);
        let phases_changed = self.phases.iter().map(|s| s.as_str()).collect::<Vec<_>>() != def_phases;
        let filters_changed = match pr.get("phase_filters") {
            Some(f) if !f.is_null() => !filters_are(f, &def_filters),
            _ => default_phasing("en").1.iter().map(|x| x.0).collect::<Vec<_>>() != def_filters.iter().map(|x| x.0).collect::<Vec<_>>(),
        };
        let changed = phases_changed
            || filters_changed
            || pr.get("phase_overrides").map(|v| !v.is_null()).unwrap_or(false)
            || pr.get("option_sets").and_then(|o| o.as_obj()).map(|o| !o.is_empty()).unwrap_or(false);
        let held = pr.elements.values().any(|e| {
            e.get("params").and_then(|p| p.as_obj()).map(|p| p.contains("Phase Created") || p.contains("Phase Demolished") || p.contains("Design Option")).unwrap_or(false)
        });
        self.phased = changed || held;
        self.held = held;
    }

    /// Each element's values of the project parameters, by name, in a `Project Parameters` set.
    fn write_project_parameters(&mut self) {
        let pr = self.pr;
        let defs = pr.section("parameters").cloned().unwrap_or_default();
        let mut done = self.finished.clone();
        done.sort_by_key(|x| x.0);
        for (id, product) in done {
            let Some(e) = pr.el(id) else { continue };
            let Some(ps) = e.get("params").and_then(|p| p.as_obj()) else { continue };
            let mut vals: Vec<(String, String)> = Vec::new();
            for (k, v) in &ps.items {
                let name = match pr.lib_find_guid(k).and_then(|l| pr.library.get(&l)) {
                    Some(l) if l.get("kind").and_then(|x| x.as_str()) == Some("parameter") => {
                        l.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string()
                    }
                    _ => continue,
                };
                let kind = defs.get(&name).and_then(|d| d.get("kind")).and_then(|x| x.as_str()).unwrap_or("text");
                let val = match (kind, v) {
                    ("yesno", Value::Bool(b)) => format!("IFCBOOLEAN(.{}.)", if *b { "T" } else { "F" }),
                    ("number", _) => match v.as_f64() {
                        Some(x) => format!("IFCREAL({})", real(x)),
                        None => continue,
                    },
                    ("length", _) => match v.as_f64() {
                        Some(x) => format!("IFCLENGTHMEASURE({})", real(x)),
                        None => continue,
                    },
                    (_, Value::Str(t)) => format!("IFCTEXT({})", st(t)),
                    (_, Value::Bool(b)) => format!("IFCBOOLEAN(.{}.)", if *b { "T" } else { "F" }),
                    (_, Value::Num(n)) => format!("IFCREAL({})", real(n.as_f64())),
                    _ => continue,
                };
                vals.push((name, val));
            }
            if vals.is_empty() {
                continue;
            }
            vals.sort();
            let ids: Vec<usize> = vals
                .iter()
                .map(|(n, v)| self.add(format!("IFCPROPERTYSINGLEVALUE({},$,{},$)", st(n), v)))
                .collect();
            let g = self.fresh();
            let pset = self.add(format!("IFCPROPERTYSET('{}',$,'Project Parameters',$,({}))", g, refs(&ids)));
            let g = self.fresh();
            self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, product, pset));
        }
    }

    // ------------------------------------------------------------ shared pieces

    /// The storey of a level GUID.
    pub fn storey_of(&self, level: &str) -> Option<&Storey> {
        self.storeys.iter().find(|s| s.guid == level)
    }

    pub fn storey_place(&self, level: &str) -> usize {
        self.storey_of(level).map(|s| s.place).unwrap_or(self.building_place)
    }

    pub fn level_elev(&self, level: &str) -> f64 {
        self.storey_of(level).map(|s| s.elevation).unwrap_or(0.0)
    }

    /// Puts a product in its level's storey.
    pub fn contain(&mut self, level: &str, product: usize) {
        self.contained.entry(level.to_string()).or_default().push(product);
    }

    /// Notes a product of a type object.
    pub fn typed(&mut self, class: &str, name: &str, tail: &str, product: usize) {
        let t = self.types.entry((class.to_string(), name.to_string())).or_default();
        if t.tail.is_empty() {
            t.tail = tail.to_string();
        } else if class == "IFCROOFTYPE" && t.tail != tail {
            // a roof type is flat only while all its roofs are
            t.tail = "$,$,$,$,$,$,.NOTDEFINED.".to_string();
        }
        t.occ.push(product);
    }

    /// `IFCLOCALPLACEMENT` relative to another, at a point, turned to a direction in plan
    /// (none: the identity's axes).
    pub fn placement(&mut self, rel: usize, at: V3, xdir: Option<V2>) -> usize {
        let p = self.st.point3(at.x, at.y, at.z);
        let a = match xdir {
            Some(d) => {
                let dd = self.st.dir3(d.x, d.y, 0.0);
                self.add(format!("IFCAXIS2PLACEMENT3D(#{},#{},#{})", p, self.up, dd))
            }
            None => self.add(format!("IFCAXIS2PLACEMENT3D(#{},$,$)", p)),
        };
        self.add(format!("IFCLOCALPLACEMENT(#{},#{})", rel, a))
    }

    /// A closed `IFCPOLYLINE` of plan points, its first point again at the end.
    pub fn closed_polyline(&mut self, pts: &[V2]) -> usize {
        let ids: Vec<usize> = pts.iter().map(|p| self.st.point2(p.x, p.y)).collect();
        let mut all = ids.clone();
        if let Some(f) = ids.first() {
            all.push(*f);
        }
        self.add(format!("IFCPOLYLINE(({}))", refs(&all)))
    }

    pub fn open_polyline(&mut self, pts: &[V2]) -> usize {
        let ids: Vec<usize> = pts.iter().map(|p| self.st.point2(p.x, p.y)).collect();
        self.add(format!("IFCPOLYLINE(({}))", refs(&ids)))
    }

    /// An element quantity set and its relation to the product.
    pub fn quantities(&mut self, name: &str, product: usize, qs: &[(&str, &str, f64)]) {
        let mut ids = Vec::new();
        for (kind, qn, v) in qs {
            let ent = match *kind {
                "L" => format!("IFCQUANTITYLENGTH('{}',$,$,{},$)", qn, real(*v)),
                "A" => format!("IFCQUANTITYAREA('{}',$,$,{},$)", qn, real(*v)),
                _ => format!("IFCQUANTITYVOLUME('{}',$,$,{},$)", qn, real(*v)),
            };
            ids.push(self.add(ent));
        }
        let g = self.fresh();
        let q = self.add(format!("IFCELEMENTQUANTITY('{}',$,'{}',$,$,({}))", g, name, refs(&ids)));
        let g = self.fresh();
        self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, product, q));
    }

    /// A material of the library by name: `IFCMATERIAL` and its colour, written the first
    /// time it's needed. Returns the material and its surface style.
    pub fn material(&mut self, name: &str) -> (usize, usize) {
        if let Some(m) = self.materials.get(name) {
            return *m;
        }
        let md = self.pr.get("materials").and_then(|m| m.get(name));
        let col = md.and_then(|m| m.get("color")).and_then(|c| c.as_arr()).cloned().unwrap_or_default();
        let c = |i: usize| col.get(i).and_then(|x| x.as_f64()).unwrap_or(200.0) / 255.0;
        let transparency = md.and_then(|m| m.get("transparency")).and_then(|t| t.as_f64()).unwrap_or(0.0);
        let mat = self.add(format!("IFCMATERIAL({},$,$)", st(name)));
        let rgb = self.add(format!("IFCCOLOURRGB($,{},{},{})", real(c(0)), real(c(1)), real(c(2))));
        let tr = if transparency > 0.0 { real(transparency / 100.0) } else { "$".to_string() };
        let shading = self.add(format!("IFCSURFACESTYLESHADING(#{},{})", rgb, tr));
        let style = self.add(format!("IFCSURFACESTYLE({},.BOTH.,(#{}))", st(name), shading));
        let item = self.add(format!("IFCSTYLEDITEM($,(#{}),$)", style));
        let srep = self.add(format!("IFCSTYLEDREPRESENTATION(#{},'Style','Material',(#{}))", self.model, item));
        self.add(format!("IFCMATERIALDEFINITIONREPRESENTATION($,$,(#{}),#{})", srep, mat));
        self.materials.insert(name.to_string(), (mat, style));
        (mat, style)
    }

    /// The name of a material given by GUID (a library entry), or by name.
    pub fn material_name(&self, g: &str) -> Option<String> {
        if let Some(n) = self.pr.lib_name(g) {
            return Some(n);
        }
        if self.pr.get("materials").and_then(|m| m.get(g)).is_some() {
            return Some(g.to_string());
        }
        None
    }

    /// What every product gets once it is written, called right after its entity: its common
    /// property set (`Pset_WallCommon`…, with `LoadBearing` for a structural element, written
    /// now, and `Status` at the end in a phased project), its phase and design option
    /// (`BIMCraft_Phasing`) and its values of the project parameters, both at the end.
    pub fn finish(&mut self, id: u64, e: &Value, product: usize, common: Option<&str>, load_bearing: bool) {
        let mut props = Vec::new();
        if load_bearing {
            props.push(self.add("IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.T.),$)"));
        }
        if let Some(name) = common {
            self.commons.push(Common {
                element: id,
                product,
                name: name.to_string(),
                props,
                status: self.status_of(id, e),
            });
        }
        self.finished.push((id, product));
    }

    /// The `Status` a phased project gives an element (none in a project without phases of its own).
    pub fn status_of(&self, id: u64, e: &Value) -> Option<String> {
        let _ = id;
        if !self.held {
            return None;
        }
        let pr = self.pr;
        let phase_of = |e: &Value, k: &str| -> Option<usize> {
            let g = e.get("params")?.get(k)?.as_str()?;
            let n = pr.lib_name(g)?;
            self.phases.iter().position(|p| *p == n)
        };
        // a door or a window has its wall's phases where it has none of its own
        let cat = e.get("category").and_then(|c| c.as_str()).unwrap_or("");
        let host = if cat == "door" || cat == "window" {
            e.get("host").and_then(|h| h.as_str()).and_then(|h| pr.find_guid(h)).and_then(|h| pr.el(h))
        } else {
            None
        };
        let phase = |k: &str| phase_of(e, k).or_else(|| host.and_then(|h| phase_of(h, k)));
        let c = phase("Phase Created").unwrap_or(0);
        let s = match phase("Phase Demolished") {
            Some(d) if d == c => "TEMPORARY",
            Some(_) => "DEMOLISH",
            None if c == 0 => "EXISTING",
            None => "NEW",
        };
        Some(s.to_string())
    }

    // ------------------------------------------------------------ walls

    fn write_wall(&mut self, id: u64, e: &Value) {
        let Some(w) = self.walls.iter().find(|w| w.id == id).cloned() else { return };
        let outline = self.wall_outlines.get(&id).cloned().unwrap_or_default();
        let base_offset = e.get("base_offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let level_elev = self.level_elev(&w.level);
        let top = self.wall_top(e, level_elev + base_offset);
        let height = top - (level_elev + base_offset);
        let origin = w.start;
        let d = w.start_dir();
        let n = d.perp();
        let local = |p: V2| {
            let v = p - origin;
            v2(v.dot(d), v.dot(n))
        };
        let place_rel = self.storey_place(&w.level);
        let place = self.placement(place_rel, v3(origin.x, origin.y, base_offset), Some(d));
        self.placements.insert(id, place);
        let axis_pts: Vec<V2> = w.offset_points(0.0).into_iter().map(local).collect();
        let axis_poly = self.open_polyline(&axis_pts);
        let axis_rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Axis','Curve2D',(#{}))", self.axis, axis_poly));
        // attached to a roof or a floor: closed shells following it; else swept up
        let base_abs = level_elev + base_offset;
        let raw = self.wall_raw_outlines.get(&id).cloned().unwrap_or_default();
        let attached = self.attached_breps(e, &raw, &local, base_abs, base_abs, top);
        let body = match &attached {
            Some(breps) => self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Brep',({}))", self.body, refs(breps))),
            None => {
                let prof_pts: Vec<V2> = outline.iter().map(|p| local(*p)).collect();
                let poly = self.closed_polyline(&prof_pts);
                let prof = self.add(format!("IFCARBITRARYCLOSEDPROFILEDEF(.AREA.,$,#{})", poly));
                let solid = self.add(format!(
                    "IFCEXTRUDEDAREASOLID(#{},#{},#{},{})",
                    prof,
                    self.origin,
                    self.up,
                    real(height)
                ));
                self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','SweptSolid',(#{}))", self.body, solid))
            }
        };
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{},#{}))", body, axis_rep));
        let name = st(&w.type_name);
        let product = self.add(format!(
            "IFCWALL('{}',$,{},$,{},#{},#{},'{}',.STANDARD.)",
            gid(&w.guid),
            name,
            name,
            place,
            shape,
            id
        ));
        self.products.insert(id, product);
        self.finish(id, e, product, Some("Pset_WallCommon"), false);
        // quantities: gross, and less what the doors and windows in it take, each cut to its height
        let length = w.length();
        let gross = length * height / 1e6;
        let mut holes_mm = 0.0;
        for (oid, oe) in &self.pr.elements {
            let _ = oid;
            let cat = oe.get("category").and_then(|c| c.as_str()).unwrap_or("");
            if (cat == "door" || cat == "window") && oe.get("host").and_then(|h| h.as_str()) == Some(w.guid.as_str()) {
                let (ow, oh) = openings::opening_size(self.pr, oe);
                let sill = oe.get("sill").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let lo = sill.max(0.0);
                let hi = (sill + oh).min(height);
                if hi > lo {
                    holes_mm += ow * (hi - lo);
                }
            }
        }
        let net = (length * height - holes_mm) / 1e6;
        let t = w.thickness;
        // the volumes from the side in mm², less the holes, through the thickness
        let (gv, nv) = (length * height * t / 1e9, (length * height - holes_mm) * t / 1e9);
        if attached.is_some() {
            // its height varies along it
            self.quantities("Qto_WallBaseQuantities", product, &[("L", "Length", length), ("L", "Width", t)]);
        } else {
            self.quantities(
                "Qto_WallBaseQuantities",
                product,
                &[
                    ("L", "Length", length),
                    ("L", "Width", t),
                    ("L", "Height", height),
                    ("A", "GrossSideArea", gross),
                    ("A", "NetSideArea", net),
                    ("V", "GrossVolume", gv),
                    ("V", "NetVolume", nv),
                ],
            );
        }
        let level = w.level.clone();
        self.contain(&level, product);
        self.typed("IFCWALLTYPE", &w.type_name, "$,$,$,$,$,$,.STANDARD.", product);
        // a layered type: a layer set used at the offset of its exterior face from the axis
        if let Some(layers) = walls::type_data(self.pr, "wall", &w.type_guid)
            .and_then(|t| t.get("layers"))
            .and_then(|l| l.as_arr())
            .cloned()
        {
            if !layers.is_empty() {
                self.layer_usages.push(LayerUse {
                    kind: LayerKind::Wall,
                    type_key: format!("wall:{}", w.type_guid),
                    type_name: w.type_name.clone(),
                    layers,
                    offset: w.left,
                    product,
                });
            }
        }
    }

    /// The height of a wall's top: its top level's elevation plus its top offset, or its
    /// base plus its height.
    pub fn wall_top(&self, e: &Value, base: f64) -> f64 {
        match e.get("top_level").and_then(|v| v.as_str()) {
            Some(tl) if self.storey_of(tl).is_some() => {
                self.level_elev(tl) + e.get("top_offset").and_then(|v| v.as_f64()).unwrap_or(0.0)
            }
            _ => base + e.get("height").and_then(|v| v.as_f64()).unwrap_or(3000.0),
        }
    }

    // ------------------------------------------------------------ the tail

    /// Material layer sets: the walls' sets first (by type name), then each covering type's set
    /// with its coverings, each slab type's set with a usage for each offset its slabs stand
    /// at, and last the walls' usages, by type name and offset.
    fn write_layer_sets(&mut self) {
        let uses = std::mem::take(&mut self.layer_usages);
        let by_name = |kind: LayerKind| -> Vec<String> {
            let mut names: Vec<String> = uses.iter().filter(|u| u.kind == kind).map(|u| u.type_name.clone()).collect();
            names.sort();
            names.dedup();
            names
        };
        let first_of = |kind: LayerKind, name: &str| uses.iter().position(|u| u.kind == kind && u.type_name == name).unwrap();
        for name in by_name(LayerKind::Wall) {
            let i = first_of(LayerKind::Wall, &name);
            self.layer_set(&uses[i]);
        }
        for name in by_name(LayerKind::Covering) {
            let i = first_of(LayerKind::Covering, &name);
            let set = self.layer_set(&uses[i]);
            let prods: Vec<usize> =
                uses.iter().filter(|u| u.kind == LayerKind::Covering && u.type_name == name).map(|u| u.product).collect();
            let g = self.fresh();
            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,({}),#{})", g, refs(&prods), set));
        }
        let usages = |ex: &mut Ex, kind: LayerKind, name: &str, set: usize| {
            let mut offs: Vec<(String, f64)> = Vec::new();
            for u in uses.iter().filter(|u| u.kind == kind && u.type_name == name) {
                let k = real(u.offset);
                if !offs.iter().any(|o| o.0 == k) {
                    offs.push((k, u.offset));
                }
            }
            offs.sort_by(|a, b| a.0.cmp(&b.0));
            let axis = if kind == LayerKind::Wall { ".AXIS2." } else { ".AXIS3." };
            for (k, _) in offs {
                let prods: Vec<usize> = uses
                    .iter()
                    .filter(|u| u.kind == kind && u.type_name == name && real(u.offset) == k)
                    .map(|u| u.product)
                    .collect();
                let usage = ex.add(format!("IFCMATERIALLAYERSETUSAGE(#{},{},.NEGATIVE.,{},$)", set, axis, k));
                let g = ex.fresh();
                ex.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,({}),#{})", g, refs(&prods), usage));
            }
        };
        for name in by_name(LayerKind::Slab) {
            let i = first_of(LayerKind::Slab, &name);
            let set = self.layer_set(&uses[i]);
            usages(self, LayerKind::Slab, &name, set);
        }
        for name in by_name(LayerKind::Roof) {
            let i = first_of(LayerKind::Roof, &name);
            let set = self.layer_set(&uses[i]);
            let prods: Vec<usize> =
                uses.iter().filter(|u| u.kind == LayerKind::Roof && u.type_name == name).map(|u| u.product).collect();
            let g = self.fresh();
            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,({}),#{})", g, refs(&prods), set));
        }
        for name in by_name(LayerKind::Wall) {
            let i = first_of(LayerKind::Wall, &name);
            let set = self.layer_set(&uses[i]);
            usages(self, LayerKind::Wall, &name, set);
        }
    }

    fn layer_set(&mut self, u: &LayerUse) -> usize {
        if let Some(s) = self.layer_sets.get(&u.type_key) {
            return *s;
        }
        let mut ids = Vec::new();
        for l in &u.layers {
            let mg = l.get("material").and_then(|m| m.as_str()).unwrap_or("");
            let mat = match self.material_name(mg) {
                Some(n) => format!("#{}", self.material(&n).0),
                None => "$".to_string(),
            };
            let th = l.get("thickness").and_then(|t| t.as_f64()).unwrap_or(0.0);
            let cat = match l.get("function").and_then(|f| f.as_str()).unwrap_or("") {
                "finish" => "Finish",
                "thermal" => "Insulation",
                "structure" => "LoadBearing",
                "substrate" => "Substrate",
                "membrane" => "Membrane",
                _ => "Finish",
            };
            let desc = if l.get("variable").and_then(|v| v.as_bool()).unwrap_or(false) { "'Variable'" } else { "$" };
            ids.push(self.add(format!("IFCMATERIALLAYER({},{},$,$,{},'{}',$)", mat, real(th), desc, cat)));
        }
        let set = self.add(format!("IFCMATERIALLAYERSET(({}),{},$)", refs(&ids), st(&u.type_name)));
        self.layer_sets.insert(u.type_key.clone(), set);
        set
    }

    fn write_containment(&mut self) {
        let mut levels: Vec<String> = self.storeys.iter().map(|s| s.guid.clone()).collect();
        levels.sort();
        for l in levels {
            let ent = self.storey_of(&l).unwrap().ent;
            if let Some(c) = self.contained.get(&l).cloned() {
                if !c.is_empty() {
                    let g = self.fresh();
                    self.add(format!("IFCRELCONTAINEDINSPATIALSTRUCTURE('{}',$,$,$,({}),#{})", g, refs(&c), ent));
                }
            }
            if let Some(s) = self.spaces.get(&l).cloned() {
                if !s.is_empty() {
                    let g = self.fresh();
                    self.add(format!("IFCRELAGGREGATES('{}',$,$,$,#{},({}))", g, ent, refs(&s)));
                }
            }
        }
    }

    fn write_commons(&mut self) {
        let mut cs = std::mem::take(&mut self.commons);
        cs.sort_by_key(|c| c.element);
        for c in cs.iter_mut() {
            if let Some(s) = &c.status {
                let p = self.add(format!("IFCPROPERTYENUMERATEDVALUE('Status',$,(IFCLABEL('{}')),$)", s));
                c.props.push(p);
            }
        }
        for c in &cs {
            if c.props.is_empty() {
                continue;
            }
            let g = self.fresh();
            let ps = self.add(format!("IFCPROPERTYSET('{}',$,'{}',$,({}))", g, c.name, refs(&c.props)));
            let g = self.fresh();
            self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, c.product, ps));
        }
    }

    fn write_types(&mut self) {
        let types = std::mem::take(&mut self.types);
        // by class, a door's or a window's by how it opens, then by name
        let mut types: Vec<((String, String), TypeObj)> = types.into_iter().collect();
        types.sort_by(|((ca, ka), ta), ((cb, kb), tb)| {
            let by_tail = |c: &str| c == "IFCDOORTYPE" || c == "IFCWINDOWTYPE";
            let sa = if by_tail(ca) { ta.tail.as_str() } else { "" };
            let sb = if by_tail(cb) { tb.tail.as_str() } else { "" };
            (ca, sa, ka).cmp(&(cb, sb, kb))
        });
        for ((class, key), t) in types {
            let name = t.name.clone().unwrap_or(key);
            let g = self.fresh();
            let ty = self.add(format!("{}('{}',$,{},{})", class, g, st(&name), t.tail));
            let g = self.fresh();
            self.add(format!("IFCRELDEFINESBYTYPE('{}',$,$,$,({}),#{})", g, refs(&t.occ), ty));
            for x in &t.after {
                match x {
                    TypeExtra::Profile { material, profile, usages } => {
                        let m = match material {
                            Some(mn) => format!("#{}", self.material(mn).0),
                            None => "$".to_string(),
                        };
                        let mp = self.add(format!("IFCMATERIALPROFILE({},$,{},#{},$,$)", st(&name), m, profile));
                        let set = self.add(format!("IFCMATERIALPROFILESET({},$,(#{}),$)", st(&name), mp));
                        let g = self.fresh();
                        self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,(#{}),#{})", g, ty, set));
                        for (cp, occ) in usages {
                            let u = self.add(format!("IFCMATERIALPROFILESETUSAGE(#{},{},$)", set, cp));
                            let g = self.fresh();
                            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,({}),#{})", g, refs(occ), u));
                        }
                    }
                }
            }
        }
    }
}

#[allow(dead_code)]
fn unused() {
    let _ = dir(0.0);
}

/// A new project's phases and phase filters in a language: the phases in order, and each
/// filter's name with how it shows new, existing, demolished and temporary work.
fn default_phasing(lang: &str) -> (Vec<&'static str>, Vec<(&'static str, [&'static str; 4])>) {
    const ALL: [&str; 4] = ["by-category", "by-category", "by-category", "by-category"];
    const COMPLETE: [&str; 4] = ["by-category", "by-category", "not-displayed", "by-category"];
    const NEW: [&str; 4] = ["by-category", "not-displayed", "not-displayed", "not-displayed"];
    const DEMO: [&str; 4] = ["not-displayed", "by-category", "overridden", "not-displayed"];
    const PREV: [&str; 4] = ["by-category", "overridden", "not-displayed", "by-category"];
    let (phases, names): (Vec<&str>, [&str; 5]) = match lang {
        "pt" => (vec!["Existente", "Nova construção"], ["Mostrar tudo", "Mostrar completo", "Mostrar novo", "Mostrar anterior + demolido", "Mostrar anterior + novo"]),
        "es" => (vec!["Existente", "Nueva construcción"], ["Mostrar todo", "Mostrar completo", "Mostrar nuevo", "Mostrar anterior + demolido", "Mostrar anterior + nuevo"]),
        "sv" => (vec!["Befintlig", "Nybyggnad"], ["Visa alla", "Visa färdigställt", "Visa nytt", "Visa tidigare + rivet", "Visa tidigare + nytt"]),
        "cs" => (vec!["Stávající", "Nová výstavba"], ["Zobrazit vše", "Zobrazit dokončené", "Zobrazit nové", "Zobrazit předchozí + bourané", "Zobrazit předchozí + nové"]),
        "fr" => (vec!["Existant", "Nouvelle construction"], ["Tout afficher", "Afficher complet", "Afficher nouveau", "Afficher précédent + démoli", "Afficher précédent + nouveau"]),
        "de" => (vec!["Bestand", "Neubau"], ["Alle anzeigen", "Vollständig anzeigen", "Nur Neu anzeigen", "Bestand + Abgebrochen anzeigen", "Bestand + Neu anzeigen"]),
        _ => (vec!["Existing", "New Construction"], ["Show All", "Show Complete", "Show New", "Show Previous + Demolished", "Show Previous + New"]),
    };
    let mut filters: Vec<(&str, [&str; 4])> = names.iter().zip([ALL, COMPLETE, NEW, DEMO, PREV]).map(|(n, f)| (*n, f)).collect();
    filters.sort_by(|a, b| a.0.cmp(b.0));
    (phases, filters)
}

/// Whether a project's phase filters are these, each showing the statuses as they say.
fn filters_are(f: &Value, def: &[(&str, [&str; 4])]) -> bool {
    let Some(m) = f.as_obj() else { return false };
    if m.items.len() != def.len() {
        return false;
    }
    def.iter().all(|(name, sts)| {
        m.get(name).map_or(false, |o| {
            ["new", "existing", "demolished", "temporary"].iter().zip(sts.iter()).all(|(k, v)| o.get(k).and_then(|x| x.as_str()) == Some(*v))
        })
    })
}
