// Tables (table, entity, title-block, and defines on them): bare strings
// become `|cell|` blocks, the label a caption — or, on an entity, the title
// header cell.

use super::lower::{Cx, R};
use super::out::{Item, ONode};
use super::syntax::{Decl, Node};

pub fn mark_used(cx: &mut Cx) {
    for c in ["header", "align-start", "align-end", "justify-start", "justify-end"] {
        cx.mark(c);
    }
}

pub fn wrap_cells(cx: &mut Cx, items: Vec<Item>) -> Vec<Item> {
    items
        .into_iter()
        .map(|it| match it {
            Item::Text(t) => {
                let mut c = cx.typed("cell");
                c.children.push(Item::Text(t));
                Item::Node(c)
            }
            other => other,
        })
        .collect()
}

pub fn lower(cx: &mut Cx, n: &Node, mut o: ONode, chain: &[String]) -> R<ONode> {
    mark_used(cx);
    let entity = chain.iter().any(|c| c == "entity");
    let label = n.label.as_ref().map(|l| l.trim().to_string()).filter(|l| !l.is_empty());
    let bodies = cx.bodies(chain)?;
    let mut kids = Vec::new();
    if let Some(ch) = &n.children {
        cx.stmts(ch, &mut kids)?;
    }
    let mut children = Vec::new();
    children.extend(wrap_cells(cx, bodies));
    let title_block = chain.iter().any(|c| c == "title-block");
    let label = if title_block {
        let in_page = cx.parent_is("page");
        let cells = super::page::title_block(cx, n, &mut o, in_page);
        if !cells.is_empty() {
            cx.mark("field");
        }
        children.extend(cells);
        None
    } else {
        label
    };
    if let Some(l) = &label {
        if entity {
            let mut h = cx.typed("header");
            h.decls.push(Decl::val("cell", "1 1"));
            h.children.push(Cx::text_item(l));
            children.push(Item::Node(h));
        } else {
            let c = cx.caption(l);
            children.push(c);
        }
    }
    children.extend(wrap_cells(cx, kids));
    o.children = children;
    Ok(o)
}
