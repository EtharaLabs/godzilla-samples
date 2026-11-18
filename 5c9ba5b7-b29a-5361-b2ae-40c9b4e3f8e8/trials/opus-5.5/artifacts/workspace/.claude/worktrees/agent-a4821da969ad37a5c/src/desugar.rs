// `lini desugar`: the document lowered to primitives and `.lini-*` classes.
//
//   syntax.rs    a structural reading over the formatter's tokens, values in
//                canonical text
//   lower.rs     nodes onto primitives, labels, define bodies, links
//   sheet.rs     the stylesheet: root config, `.lini-*` rules, user rules
//   registry.rs  rule order and the internal classes' default text
//   out.rs       the desugared tree and its printer (fmt's layout rules)
//   table.rs …   the families' lowering

mod drawing;
mod lower;
mod out;
mod page;
mod registry;
mod sch_geo;
mod schematic;
mod sheet;
mod syntax;
mod table;
mod tree;

use crate::diag::Diag;

// built-in contextual rules, in the order they are written
pub static CTX_RULES: &[(&str, &str)] = &[
    (".lini-sequence .lini-note", "padding: 6 10; font-size: 13;"),
    (".lini-drawing .lini-note", "padding: 6 10; font-size: 13;"),
    (".lini-mindmap .lini-topic", "max-width: 160; font-weight: medium;"),
];

// The passes run in the original's order, so that of several errors the
// same one is reported: `|link|` nodes, the define table, the trees (a dry
// run of the lowering), the selectors, the lowering itself (a schematic
// scope checks every wire's operators on entry and resolves its endpoints
// after its content), the density, and the units last.
pub fn desugar(src: &str) -> Result<String, Diag> {
    crate::format::syntax_check(src)?;
    let doc = syntax::parse(src)?;
    let defines: Vec<syntax::Define> = doc
        .sheet
        .iter()
        .filter_map(|(it, _)| match it {
            syntax::SItem::Define(d) => Some(d.clone()),
            _ => None,
        })
        .collect();
    lower::link_check(&defines, &doc.stmts)?;
    let mut cx = lower::Cx::new(src, defines.clone());
    sheet::check_defines(&cx)?;
    {
        let mut tc = lower::Cx::new(src, defines);
        tc.tree_check = true;
        setup(&mut tc, &doc)?;
        let mut items = Vec::new();
        tc.stmts(&doc.stmts, &mut items)?;
    }
    setup(&mut cx, &doc)?;
    sheet::check_selectors(&cx, &doc.sheet)?;
    if cx.root_layout == "schematic" {
        cx.sch_ops(&doc.stmts)?;
        let plan = cx.sch_plan(&doc.stmts, true, 0)?;
        cx.root_sch = Some(plan);
    }
    let mut items = Vec::new();
    cx.stmts(&doc.stmts, &mut items)?;
    if let Some((_, e)) = cx.root_sch.as_ref().and_then(|p| p.error.clone()) {
        return Err(e);
    }
    if let Some(e) = cx.density_err.take() {
        return Err(e);
    }
    if let Some(e) = cx.unit_err.take() {
        return Err(e);
    }
    let items = cx.resolve(items);
    let sheet = sheet::build(&cx, &doc.sheet)?;
    let mut p = out::Printer::new();
    p.doc(&sheet, &items);
    Ok(p.finish())
}

// the root's config: layout, unit, density, and the scene as a tree
fn setup(cx: &mut lower::Cx, doc: &syntax::Doc) -> Result<(), Diag> {
    if let Some(l) = sheet::root_layout(&doc.sheet) {
        cx.root_layout = l;
    }
    for (it, _) in &doc.sheet {
        if let syntax::SItem::Decl(d) = it {
            if d.name == "unit" {
                cx.root_unit = d.first().map(|s| s.to_string());
            }
            if d.name == "thickness" {
                cx.root_thickness = lower::thickness_of(d);
            }
            if d.name == "density" {
                match d.first().and_then(|s| s.parse::<f64>().ok()) {
                    Some(v) if v > 0.0 => cx.density = v,
                    _ => {
                        if cx.density_err.is_none() {
                            cx.density_err = Some(Diag::error("value", "'density' must be > 0", d.span));
                        }
                    }
                }
            }
        }
    }
    // the root's unit is checked before any node's
    let unit = doc.sheet.iter().rev().find_map(|(it, _)| match it {
        syntax::SItem::Decl(d) if d.name == "unit" => Some(d),
        _ => None,
    });
    if let Some(d) = unit {
        if !sheet::unit_ok(d) {
            cx.unit_err = Some(lower::err("'unit' is px, mm, cm, m, or in", d.span));
        }
    }
    // a scene of sheets alone sits flush
    cx.root_pages = !doc.stmts.is_empty()
        && doc.stmts.iter().all(|s| match s {
            syntax::Stmt::Node(n) => {
                let ty = n.ty.clone().unwrap_or_else(|| "box".to_string());
                cx.chain(&ty).map_or(false, |(_, c)| c.iter().any(|t| t == "page"))
            }
            _ => false,
        });
    if cx.root_layout == "sequence" {
        cx.mark("line");
        cx.mark("block");
    }
    // the scene as a tree: `layout: tree`, or mindmaps at the top
    if cx.root_layout == "tree" {
        let d = doc.sheet.iter().rev().find_map(|(it, _)| match it {
            syntax::SItem::Decl(d) if d.name == "direction" => d.first().map(|s| s.to_string()),
            _ => None,
        });
        // mindmaps in the tree bring their direction and routing
        let mindmaps = tree::has_mindmap(cx, &doc.stmts);
        tree::check_roots(cx, &doc.stmts, crate::diag::Span::new(0, 0))?;
        let hoisted = mindmaps && d.is_none();
        let dir = if hoisted {
            match tree::mindmap_dir(cx, &doc.stmts) {
                Some((d, sp)) => tree::read_dir(cx, Some(d), sp)?,
                None => "bilateral".to_string(),
            }
        } else {
            tree::read_dir(cx, d, crate::diag::Span::new(0, 0))?
        };
        if mindmaps {
            cx.root_mindmap = true;
            cx.root_mindmap_dir = dir.clone();
        }
        let sem = if hoisted { "column".to_string() } else { dir.clone() };
        cx.root_tree = Some(tree::TreeMode { mindmap: false, dir, level: 0, side: None, hue: None, hoisted, sem });
    } else if !doc.sheet.iter().any(|(it, _)| matches!(it, syntax::SItem::Decl(d) if d.name == "layout"))
        && doc.stmts.iter().any(|s| matches!(s, syntax::Stmt::Node(n) if tree::is_mindmap(cx, n)))
    {
        cx.root_layout = "tree".to_string();
        cx.root_mindmap = true;
        let own_dir = doc.sheet.iter().rev().find_map(|(it, _)| match it {
            syntax::SItem::Decl(d) if d.name == "direction" => d.first().map(|s| s.to_string()),
            _ => None,
        });
        let hoisted = own_dir.is_none();
        let dir = match own_dir {
            // the scene's own direction lays out, unchecked
            Some(d) => d,
            None => match tree::mindmap_dir(cx, &doc.stmts) {
                Some((d, sp)) => tree::read_dir(cx, Some(d), sp)?,
                None => "bilateral".to_string(),
            },
        };
        cx.root_mindmap_dir = dir.clone();
        cx.root_tree =
            Some(tree::TreeMode { mindmap: true, dir, level: 0, side: None, hue: None, hoisted, sem: "bilateral".to_string() });
    }
    Ok(())
}
