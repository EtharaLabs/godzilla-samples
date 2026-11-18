// Surface syntax tree.

use crate::source::Span;

#[derive(Clone, Debug, PartialEq)]
pub struct Expr {
    pub kind: ExprKind,
    pub span: Span,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    FloorDiv,
    Mod,
    Pow,
    And,
    Or,
    PipeRight,
    PipeLeft,
    ComposeRight,
    ComposeLeft,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum CmpOp {
    Eq,
    Ne,
    Lt,
    Le,
    Gt,
    Ge,
}

impl BinOp {
    pub fn text(self) -> &'static str {
        match self {
            BinOp::Add => "+",
            BinOp::Sub => "-",
            BinOp::Mul => "*",
            BinOp::Div => "/",
            BinOp::FloorDiv => "//",
            BinOp::Mod => "%",
            BinOp::Pow => "**",
            BinOp::And => "and",
            BinOp::Or => "or",
            BinOp::PipeRight => "|>",
            BinOp::PipeLeft => "<|",
            BinOp::ComposeRight => ">>",
            BinOp::ComposeLeft => "<<",
        }
    }
}

impl CmpOp {
    pub fn text(self) -> &'static str {
        match self {
            CmpOp::Eq => "==",
            CmpOp::Ne => "!=",
            CmpOp::Lt => "<",
            CmpOp::Le => "<=",
            CmpOp::Gt => ">",
            CmpOp::Ge => ">=",
        }
    }
}

/// An operator section `(op)`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum SectionOp {
    Bin(BinOp),
    Cmp(CmpOp),
}

impl SectionOp {
    pub fn text(self) -> &'static str {
        match self {
            SectionOp::Bin(b) => b.text(),
            SectionOp::Cmp(c) => c.text(),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum FPart {
    Text(String),
    Expr(Expr),
}

/// A unit-of-measure expression: a product of powers of named units (or
/// unit variables `'u`); `1` is the dimensionless unit.
#[derive(Clone, Debug, PartialEq)]
pub struct UnitExpr {
    /// numerator factors (name, exponent)
    pub num: Vec<(String, i64)>,
    /// denominator factors
    pub den: Vec<(String, i64)>,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq)]
pub enum ExprKind {
    Int(i64),
    Float(f64),
    Str(String),
    FStr(Vec<FPart>),
    Bool(bool),
    Unit,
    /// a lowercase name
    Var(String),
    /// a capitalized name (constructor), optionally module-qualified
    Ctor(Vec<String>, String),
    /// `Module.member` (member lowercase)
    Qual(Vec<String>, String, Span),
    Field(Box<Expr>, String, Span),
    App(Box<Expr>, Box<Expr>),
    Binary(BinOp, Box<Expr>, Box<Expr>),
    Chain(Box<Expr>, Vec<(CmpOp, Expr)>),
    Neg(Box<Expr>),
    Not(Box<Expr>),
    Try(Box<Expr>),
    If(Box<Expr>, Box<Expr>, Box<Expr>),
    Match(Box<Expr>, Vec<Arm>),
    Lambda(Vec<Pat>, Box<Expr>),
    Block(Vec<Stmt>),
    Tuple(Vec<Expr>),
    List(Vec<Expr>),
    /// `Ctor { f = e, ... }` (module path, ctor name, ctor span, fields)
    Record(Vec<String>, String, Span, Vec<(String, Span, Expr)>),
    /// `{ e with a.b = v, ... }`
    Update(Box<Expr>, Vec<(Vec<(String, Span)>, Expr)>),
    Section(SectionOp),
    Hole(Option<String>),
    /// numeric literal with a unit annotation
    Measured(Box<Expr>, UnitExpr),
    /// computation expression: builder (path, name), statements
    Ce(Vec<String>, String, Vec<CeStmt>),
    /// `x <- e` inside an expression (target name, target span, value)
    Assign(String, Span, Box<Expr>),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Arm {
    pub pat: Pat,
    pub guard: Option<Expr>,
    pub body: Expr,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Stmt {
    Let(LetDecl),
    /// `x <- v`: target, target span, value, and the whole statement
    Assign(String, Span, Expr, Span),
    Expr(Expr),
}

#[derive(Clone, Debug, PartialEq)]
pub struct LetDecl {
    pub pat: Pat,
    /// parameters, when this binds a function
    pub params: Vec<Pat>,
    pub mutable: bool,
    pub pure_: bool,
    pub value: Expr,
    pub doc: Option<String>,
    /// span of the binding name (or pattern)
    pub name_span: Span,
    /// span of the whole declaration
    pub span: Span,
    /// active-pattern cases (`let (|A|B|) x = ...`); partial ends with `_`
    pub active: Option<Vec<String>>,
    /// where each active-pattern case is named in the header
    pub case_spans: Vec<Span>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum CeStmt {
    LetBang(Pat, Expr, Span),
    DoBang(Expr, Span),
    Let(LetDecl),
    Return(Expr, Span),
    ReturnBang(Expr, Span),
    Yield(Expr, Span),
    YieldBang(Expr, Span),
    For(Pat, Expr, Vec<CeStmt>, Span),
    Assign(String, Span, Expr),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Pat {
    pub kind: PatKind,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq)]
pub enum PatKind {
    Wild,
    Var(String),
    Int(i64),
    Str(String),
    Bool(bool),
    Unit,
    /// constructor (module path, name, args)
    Ctor(Vec<String>, String, Vec<Pat>),
    Tuple(Vec<Pat>),
    /// list pattern; `Star(name)` entries hold `*rest` (None for `*_`)
    List(Vec<ListPatElem>),
    /// record pattern: path, ctor, fields (name, span, optional sub-pattern)
    /// (the span of the type's name, qualified)
    Record(Vec<String>, String, Span, Vec<(String, Span, Option<Pat>)>),
    Or(Vec<Pat>),
    As(Box<Pat>, String, Span),
}

#[derive(Clone, Debug, PartialEq)]
pub enum ListPatElem {
    Pat(Pat),
    Star(Option<String>, Span),
}

#[derive(Clone, Debug, PartialEq)]
pub struct TypeExpr {
    pub kind: TypeKind,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq)]
pub enum TypeKind {
    /// named type with arguments, possibly qualified
    Con(Vec<String>, String, Vec<TypeExpr>),
    Var(String),
    /// argument, declared effects (None = no braces), result
    Fun(Box<TypeExpr>, Option<Vec<String>>, Box<TypeExpr>),
    Tuple(Vec<TypeExpr>),
    /// `float<m>` / `int<'u>`
    Measured(Box<TypeExpr>, UnitExpr),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Variant {
    pub name: String,
    pub span: Span,
    pub args: Vec<TypeExpr>,
}

#[derive(Clone, Debug, PartialEq)]
pub enum TypeBody {
    Sum(Vec<Variant>),
    Record(Vec<(String, Span, TypeExpr)>),
    /// `opaque type T = underlying`
    Opaque(TypeExpr),
}

#[derive(Clone, Debug, PartialEq)]
pub struct TypeDecl {
    pub name: String,
    pub name_span: Span,
    pub params: Vec<String>,
    pub body: TypeBody,
    pub doc: Option<String>,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq)]
pub enum KwValue {
    Int(i64),
    Float(f64),
    Str(String),
    Bool(bool),
    /// `...`: taken from the caller
    Slot,
}

#[derive(Clone, Debug, PartialEq)]
pub enum ExternTarget {
    /// dotted path
    Path(Vec<String>),
    /// `.attr` (property) or `.meth()` (method call)
    Member(String, bool),
}

#[derive(Clone, Debug, PartialEq)]
pub struct ExternDecl {
    pub name: String,
    pub name_span: Span,
    pub pure_: bool,
    pub ty: TypeExpr,
    pub target: Option<ExternTarget>,
    /// `(kw = value, ...)` after the target; Some(vec![]) for `()`
    pub kwargs: Option<Vec<(String, KwValue)>>,
    pub target_span: Span,
    pub doc: Option<String>,
    pub span: Span,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Decl {
    Let(LetDecl),
    Type(TypeDecl),
    Measure(String, Option<UnitExpr>, Span),
    Extern(ExternDecl),
    ExternType(String, Vec<String>, Span, Option<String>),
    ExternImport(Vec<String>, Option<String>, Span),
    Module(String, Span, Vec<Decl>),
    Import(String, Span),
    Expr(Expr),
    Assign(String, Span, Expr, Span),
}

#[derive(Clone, Debug, PartialEq)]
pub struct Program {
    pub decls: Vec<Decl>,
}
