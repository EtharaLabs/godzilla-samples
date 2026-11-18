//! Components: a family's type placed, written as the IFC class its category says, each form
//! a closed face set in its material's colour.

use super::geom::*;
use super::step::{gid, real, refs, st};
use super::Ex;
use crate::json::Value;

/// A family category's IFC class, its occurrences' predefined type, its type object's class
/// and predefined type, and the object type of a proxy.
pub fn class_of(cat: &str, kind: &str) -> (&'static str, String, &'static str, String, Option<&'static str>) {
    let nd = || "NOTDEFINED".to_string();
    match cat {
        "plumbing" => {
            let p = match kind {
                "wc" => "TOILETPAN",
                "lav" => "WASHHANDBASIN",
                "sink" | "laundry" => "SINK",
                "shower" => "SHOWER",
                "bath" => "BATH",
                "bidet" => "BIDET",
                "urinal" => "URINAL",
                _ => "NOTDEFINED",
            };
            ("IFCSANITARYTERMINAL", p.into(), "IFCSANITARYTERMINALTYPE", p.into(), None)
        }
        "drain" => {
            let p = match kind {
                "floor_drain" => "FLOORTRAP",
                "floor_waste" => "FLOORWASTE",
                "roof_drain" => "ROOFDRAIN",
                _ => "NOTDEFINED",
            };
            ("IFCWASTETERMINAL", p.into(), "IFCWASTETERMINALTYPE", p.into(), None)
        }
        "pipefitting" => {
            let p = match kind {
                "bend" => "BEND",
                "tee" | "cross" => "JUNCTION",
                "transition" => "TRANSITION",
                "coupling" => "CONNECTOR",
                _ => "NOTDEFINED",
            };
            ("IFCPIPEFITTING", p.into(), "IFCPIPEFITTINGTYPE", p.into(), None)
        }
        "pipeaccessory" => ("IFCVALVE", nd(), "IFCVALVETYPE", nd(), None),
        "equipment" => ("IFCELECTRICDISTRIBUTIONBOARD", "DISTRIBUTIONBOARD".into(), "IFCELECTRICDISTRIBUTIONBOARDTYPE", nd(), None),
        "lighting" => ("IFCLIGHTFIXTURE", nd(), "IFCLIGHTFIXTURETYPE", nd(), None),
        "outlet" => ("IFCOUTLET", "POWEROUTLET".into(), "IFCOUTLETTYPE", nd(), None),
        "dataoutlet" => ("IFCOUTLET", "DATAOUTLET".into(), "IFCOUTLETTYPE", nd(), None),
        "voiceoutlet" => ("IFCOUTLET", "TELEPHONEOUTLET".into(), "IFCOUTLETTYPE", nd(), None),
        "switch" => ("IFCSWITCHINGDEVICE", "TOGGLESWITCH".into(), "IFCSWITCHINGDEVICETYPE", nd(), None),
        "patchpanel" => ("IFCCOMMUNICATIONSAPPLIANCE", "NETWORKAPPLIANCE".into(), "IFCCOMMUNICATIONSAPPLIANCETYPE", nd(), None),
        "rack" => ("IFCBUILDINGELEMENTPROXY", "USERDEFINED".into(), "IFCBUILDINGELEMENTPROXYTYPE", nd(), Some("Rack")),
        "airterminal" => ("IFCBUILDINGELEMENTPROXY", "USERDEFINED".into(), "IFCBUILDINGELEMENTPROXYTYPE", nd(), Some("LightningTerminal")),
        "earthing" => ("IFCBUILDINGELEMENTPROXY", "USERDEFINED".into(), "IFCBUILDINGELEMENTPROXYTYPE", nd(), Some("EarthingRod")),
        "inspectionbox" => ("IFCBUILDINGELEMENTPROXY", "USERDEFINED".into(), "IFCBUILDINGELEMENTPROXYTYPE", nd(), Some("InspectionBox")),
        "generic" => ("IFCBUILDINGELEMENTPROXY", "NOTDEFINED".into(), "IFCBUILDINGELEMENTPROXYTYPE", nd(), None),
        _ => ("IFCFURNITURE", nd(), "IFCFURNITURETYPE", nd(), None),
    }
}

impl<'a> Ex<'a> {
    pub fn write_component(&mut self, id: u64, e: &Value) {
        let pr = self.pr;
        let level = e.get("level").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let fg = e.get("family").and_then(|v| v.as_str()).unwrap_or("");
        let Some(fname) = pr.lib_name(fg) else { return };
        let Some(fam) = pr.get("families").and_then(|f| f.get(&fname)) else { return };
        let tg = e.get("type").and_then(|v| v.as_str()).unwrap_or("");
        let tname = super::openings::short_type(&fname, &pr.lib_name(tg).unwrap_or_default());
        let at = super::walls::pt(e.get("at"));
        let angle = e.get("angle").and_then(|v| v.as_f64()).unwrap_or(0.0).to_radians();
        let offset = e.get("offset").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let rel = self.storey_place(&level);
        let place = self.placement(rel, v3(at.x, at.y, offset), Some(v2(angle.cos(), angle.sin())));
        self.placements.insert(id, place);
        let meshes = super::family::meshes(pr, fam, &tname, e, None);
        let mut mats = Vec::new();
        let items = self.face_sets(&meshes, &mut mats);
        let rep = self.add(format!("IFCSHAPEREPRESENTATION(#{},'Body','Tessellation',({}))", self.body, refs(&items)));
        let shape = self.add(format!("IFCPRODUCTDEFINITIONSHAPE($,$,(#{}))", rep));
        let cat = fam.get("category").and_then(|c| c.as_str()).unwrap_or("furniture");
        let kind = fam.get("kind").and_then(|c| c.as_str()).unwrap_or("");
        let (class, predef, tclass, tpredef, proxy) = class_of(cat, kind);
        let name = st(&format!("{}:{}", fname, tname));
        let g = gid(e.get("guid").and_then(|g| g.as_str()).unwrap_or(""));
        let otype = match proxy {
            Some(p) => st(p),
            None => name.clone(),
        };
        let product = self.add(format!("{}('{}',$,{},$,{},#{},#{},'{}',.{}.)", class, g, name, otype, place, shape, id, predef));
        self.products.insert(id, product);
        self.finish(id, e, product, None, false);
        if mats.len() == 1 {
            let gg = self.fresh();
            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,(#{}),#{})", gg, product, mats[0]));
        } else if mats.len() > 1 {
            let cons: Vec<usize> = mats.iter().map(|m| self.add(format!("IFCMATERIALCONSTITUENT($,$,#{},$,$)", m))).collect();
            let set = self.add(format!("IFCMATERIALCONSTITUENTSET({},$,({}))", name, refs(&cons)));
            let gg = self.fresh();
            self.add(format!("IFCRELASSOCIATESMATERIAL('{}',$,$,$,(#{}),#{})", gg, product, set));
        }
        self.contain(&level, product);
        let tail = if tclass == "IFCFURNITURETYPE" {
            "$,$,$,$,$,$,.NOTDEFINED.,.NOTDEFINED.".to_string()
        } else {
            format!("$,$,$,$,$,$,.{}.", tpredef)
        };
        self.typed(tclass, &format!("{}:{}", fname, tname), &tail, product);
        if fam.get("connectors").and_then(|c| c.as_arr()).map(|c| !c.is_empty()).unwrap_or(false) {
            self.devices.push((id, product));
        }
    }

    /// Each device's connector, after the storeys' contents: `Pset_ElectricalDeviceCommon`
    /// and `BIMCraft_Connector`.
    pub fn write_devices(&mut self) {
        let pr = self.pr;
        let devices = std::mem::take(&mut self.devices);
        for (id, product) in devices {
            let Some(e) = pr.el(id) else { continue };
            let fg = e.get("family").and_then(|v| v.as_str()).unwrap_or("");
            let Some(fname) = pr.lib_name(fg) else { continue };
            let Some(fam) = pr.get("families").and_then(|f| f.get(&fname)) else { continue };
            let full = pr.lib_name(e.get("type").and_then(|v| v.as_str()).unwrap_or("")).unwrap_or_default();
            let tname = super::openings::short_type(&fname, &full);
            let vals = super::family::values(pr, fam, &tname, e, None);
            let conns = fam.get("connectors").and_then(|c| c.as_arr()).cloned().unwrap_or_default();
            for c in conns {
                let kind = c.get("kind").and_then(|v| v.as_str()).unwrap_or("");
                let power = kind == "power";
                let poles = c.get("poles").and_then(|v| v.as_f64()).unwrap_or(1.0);
                let mut p1 = vec![self.add(format!("IFCPROPERTYSINGLEVALUE('NumberOfPoles',$,IFCINTEGER({}),$)", poles as i64))];
                if power {
                    let pf = c.get("power_factor").and_then(|v| v.as_f64()).unwrap_or(1.0);
                    p1.push(self.add(format!("IFCPROPERTYSINGLEVALUE('PowerFactor',$,IFCNORMALISEDRATIOMEASURE({}),$)", real(pf))));
                    let v = c.get("voltage").and_then(|v| v.as_f64()).unwrap_or(0.0);
                    p1.push(self.add(format!(
                        "IFCPROPERTYBOUNDEDVALUE('RatedVoltage',$,$,$,$,IFCELECTRICVOLTAGEMEASURE({}))",
                        real(v)
                    )));
                }
                let g = self.fresh();
                let ps = self.add(format!("IFCPROPERTYSET('{}',$,'Pset_ElectricalDeviceCommon',$,({}))", g, refs(&p1)));
                let g = self.fresh();
                self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, product, ps));
                let system = c.get("system").and_then(|v| v.as_str()).unwrap_or("");
                let class = c.get("classification").and_then(|v| v.as_str()).unwrap_or("");
                let mut p2 = vec![
                    self.add(format!("IFCPROPERTYSINGLEVALUE('System',$,IFCTEXT({}),$)", st(system))),
                    self.add(format!("IFCPROPERTYSINGLEVALUE('Classification',$,IFCTEXT({}),$)", st(class))),
                ];
                if power {
                    let load_of = |v: &Value| -> f64 {
                        match v {
                            Value::Str(s) => vals.get(s).copied().unwrap_or(0.0),
                            Value::Num(n) => n.as_f64(),
                            _ => 0.0,
                        }
                    };
                    let phases: Vec<f64> = match c.get("load_va") {
                        Some(Value::Arr(a)) => a.iter().map(load_of).collect(),
                        Some(v) => vec![load_of(v)],
                        None => vec![],
                    };
                    let total: f64 = phases.iter().sum();
                    p2.push(self.add(format!("IFCPROPERTYSINGLEVALUE('LoadVA',$,IFCREAL({}),$)", real(total))));
                    for (i, l) in phases.iter().enumerate() {
                        p2.push(self.add(format!("IFCPROPERTYSINGLEVALUE('LoadVAPhase{}',$,IFCREAL({}),$)", i + 1, real(*l))));
                    }
                }
                let g = self.fresh();
                let ps = self.add(format!("IFCPROPERTYSET('{}',$,'BIMCraft_Connector',$,({}))", g, refs(&p2)));
                let g = self.fresh();
                self.add(format!("IFCRELDEFINESBYPROPERTIES('{}',$,$,$,(#{}),#{})", g, product, ps));
            }
        }
    }
}
