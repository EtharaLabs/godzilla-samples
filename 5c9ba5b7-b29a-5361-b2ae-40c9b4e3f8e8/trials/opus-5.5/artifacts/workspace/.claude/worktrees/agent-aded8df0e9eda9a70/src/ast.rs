// Syntax tree for a Lini document.

use crate::diag::Span;

#[derive(Debug, Clone)]
pub struct Doc {
    pub sheet: Option<Sheet>,
    pub stmts: Vec<Stmt>,
}

#[derive(Debug, Clone)]
pub struct Sheet {
    pub items: Vec<SheetItem>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum SheetItem {
    Decl(Decl),
    Var(Decl),
    Binding(Binding),
    Rule(Rule),
    Define(Define),
}

#[derive(Debug, Clone)]
pub struct Decl {
    pub name: String,
    pub name_span: Span,
    pub value: Value,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct Binding {
    pub name: String,
    pub params: Option<Vec<String>>,
    pub expr: Term,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct Rule {
    pub selector: Vec<Compound>,
    pub decls: Vec<Decl>,
    pub span: Span,
}

#[derive(Debug, Clone, Default)]
pub struct Compound {
    pub bars: bool,
    pub type_name: Option<String>, // '-' for the link selector |-|
    pub id: Option<String>,
    pub classes: Vec<String>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct Define {
    pub name: String,
    pub base: String,
    pub decls: Vec<Decl>,
    pub body: Option<Vec<Stmt>>,
    pub span: Span,
    pub head_span: Span,
}

#[derive(Debug, Clone)]
pub struct Value {
    // comma-separated groups, each a space-separated run of terms
    pub groups: Vec<Vec<Term>>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum Term {
    Num(f64, String, Span),
    Percent(f64, String, Span),
    Ident(String, Span),
    Str(String, Span),
    Hash(String, Span),
    Var(String, Span),
    Call(String, Vec<Expr>, Span),
    Group(Expr, Span),
    Tagged(Box<Term>, String, Span), // term ':' tag (draw segment names)
}

impl Term {
    pub fn span(&self) -> Span {
        match self {
            Term::Num(_, _, s)
            | Term::Percent(_, _, s)
            | Term::Ident(_, s)
            | Term::Str(_, s)
            | Term::Hash(_, s)
            | Term::Var(_, s)
            | Term::Call(_, _, s)
            | Term::Group(_, s)
            | Term::Tagged(_, _, s) => *s,
        }
    }
}

#[derive(Debug, Clone)]
pub enum Expr {
    Num(f64, Span),
    Percent(f64, Span),
    Ident(String, Span),
    Str(String, Span),
    Var(String, Span),
    Hash(String, Span),
    Call(String, Vec<Expr>, Span),
    Unary(String, Box<Expr>, Span),
    Bin(String, Box<Expr>, Box<Expr>, Span),
    Ternary(Box<Expr>, Box<Expr>, Box<Expr>, Span),
    Tuple(Vec<Expr>, Span),
    Block(Vec<(String, Expr)>, Box<Expr>, Span), // (a = 1; b = 2; expr)
}

impl Expr {
    pub fn span(&self) -> Span {
        match self {
            Expr::Num(_, s)
            | Expr::Percent(_, s)
            | Expr::Ident(_, s)
            | Expr::Str(_, s)
            | Expr::Var(_, s)
            | Expr::Hash(_, s)
            | Expr::Call(_, _, s)
            | Expr::Unary(_, _, s)
            | Expr::Bin(_, _, _, s)
            | Expr::Ternary(_, _, _, s)
            | Expr::Tuple(_, s)
            | Expr::Block(_, _, s) => *s,
        }
    }
}

#[derive(Debug, Clone)]
pub enum Stmt {
    Node(NodeStmt),
    Text(TextStmt),
    Link(LinkStmt),
}

#[derive(Debug, Clone)]
pub struct NodeStmt {
    pub type_name: Option<String>,
    pub id: Option<String>,
    pub label: Option<(String, Span)>,
    pub classes: Vec<String>,
    pub classes_span: Option<Span>,
    pub style: Option<Vec<Decl>>,
    pub style_span: Option<Span>,
    pub children: Option<Vec<Stmt>>,
    pub span: Span,
    pub head_span: Span,
}

#[derive(Debug, Clone)]
pub struct TextStmt {
    pub text: String,
    pub classes: Vec<String>,
    pub style: Option<Vec<Decl>>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum Endpoint {
    Path(PathRef),
    Node(Box<NodeStmt>),
    Text(String, Span),
}

#[derive(Debug, Clone)]
pub struct PathRef {
    pub parts: Vec<String>,
    pub index: Option<u32>,
    pub anchor: Option<String>,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub struct LinkStmt {
    // groups[i] are fanned endpoints; ops[i] joins groups[i] and groups[i+1]
    pub groups: Vec<Vec<Endpoint>>,
    pub ops: Vec<(String, Span)>,
    pub label: Option<(String, Span)>,
    pub classes: Vec<String>,
    pub style: Option<Vec<Decl>>,
    pub labels: Option<Vec<Stmt>>,
    pub span: Span,
}
