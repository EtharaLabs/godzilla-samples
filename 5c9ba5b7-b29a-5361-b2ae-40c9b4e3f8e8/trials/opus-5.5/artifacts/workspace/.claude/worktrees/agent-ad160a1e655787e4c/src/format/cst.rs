// Concrete syntax tree for `lini fmt`: just enough structure to reprint a
// document, with comments and blank lines attached to the items they sit
// between. Leaf values are kept pre-rendered in canonical form.

#[derive(Clone, Debug)]
pub enum Triv {
    Blank,
    // own: the comment starts its source line; otherwise it trails code
    // (an opening bracket, or something the printer drops).
    Comment { text: String, own: bool },
}

// An entry's leading trivia also carries the previous entry's trailing
// comment (a comment that follows code on its line).
#[derive(Clone, Debug)]
pub struct Entry<T> {
    pub lead: Vec<Triv>,
    pub item: T,
}

#[derive(Clone, Debug)]
pub struct Block<T> {
    pub entries: Vec<Entry<T>>,
    pub close: Vec<Triv>,
    // any comment or blank line between the brackets, even inside entries
    pub any_trivia: bool,
    pub any_comment: bool,
    // any trivia after the first entry's first token, through the last entry
    pub trivia_among: bool,
}

impl<T> Block<T> {
    pub fn empty() -> Self {
        Block { entries: Vec::new(), close: Vec::new(), any_trivia: false, any_comment: false, trivia_among: false }
    }
}

#[derive(Clone, Debug)]
pub struct Decl {
    pub name: String, // includes the leading '--' for variables
    pub groups: Vec<Vec<String>>,
    pub draw: bool,
    pub tracks: i64, // grid tracks, when read as a `columns:` value
}

impl Decl {
    pub fn value_text(&self) -> String {
        self.groups.iter().map(|g| g.join(" ")).collect::<Vec<_>>().join(", ")
    }
    pub fn text(&self) -> String {
        format!("{}: {};", self.name, self.value_text())
    }
}

#[derive(Clone, Debug)]
pub enum SheetItem {
    Decl(Decl),
    Var(Decl),
    Binding(String), // "k = v;"
    Rule { selector: String, block: Block<Decl> },
    Define { head: String, style: Option<Block<Decl>>, body: Option<Block<Stmt>> },
}

#[derive(Clone, Debug)]
pub struct Node {
    pub head: String, // "|box#id|"
    pub ty: Option<String>,
    pub label: Option<String>,
    pub classes: String, // ".a.b" or ""
    pub style: Option<Block<Decl>>,
    pub children: Option<Block<Stmt>>,
    pub columns: Option<i64>, // from the node's own `columns:`
}

#[derive(Clone, Debug)]
pub struct Text {
    pub text: String, // rendered with quotes
    pub classes: String,
    pub style: Option<Block<Decl>>,
}

#[derive(Clone, Debug)]
pub struct Link {
    pub head: String, // endpoints and operators
    // the inline label and the '[ ]' entries, merged
    pub labels: Block<Stmt>,
    pub classes: String,
    pub style: Option<Block<Decl>>,
    // a comment anywhere inside the statement keeps labels in '[ ]'
    pub has_comment: bool,
}

#[derive(Clone, Debug)]
pub enum Stmt {
    Node(Node),
    Text(Text),
    Link(Link),
}

#[derive(Clone, Debug)]
pub struct Doc {
    // the stylesheet (None when absent); `sheet_lead` holds what came before it
    pub sheet: Option<Block<SheetItem>>,
    pub sheet_lead: Vec<Triv>,
    pub stmts: Block<Stmt>,
    // user defines (name -> base), when they resolve
    pub types: Option<std::collections::HashMap<String, String>>,
}
