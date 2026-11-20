// AST definitions.

use std::cell::Cell;
use std::rc::Rc;

pub type P<T> = Box<T>;

/// Scope id assigned by the resolver (u32::MAX = none).
#[derive(Debug)]
pub struct ScopeId(pub Cell<u32>);
impl ScopeId {
    pub fn new() -> ScopeId {
        ScopeId(Cell::new(u32::MAX))
    }
    pub fn get(&self) -> u32 {
        self.0.get()
    }
    pub fn set(&self, v: u32) {
        self.0.set(v)
    }
}
impl Default for ScopeId {
    fn default() -> Self {
        ScopeId::new()
    }
}

#[derive(Debug)]
pub struct Program {
    pub body: Vec<Stmt>,
    pub strict: bool,
    pub is_module: bool,
    pub scope: ScopeId,
    pub source: Rc<str>,
    pub has_top_level_await: bool,
    /// early error found while parsing that is reported after the scope analysis (misused
    /// or undeclared private names, like the reference engine)
    pub deferred_error: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VarKind {
    Var,
    Let,
    Const,
    Using,
    AwaitUsing,
}

#[derive(Debug)]
pub struct VarDecl {
    pub kind: VarKind,
    pub decls: Vec<VarDeclarator>,
}

#[derive(Debug)]
pub struct VarDeclarator {
    pub target: Pattern,
    pub init: Option<Expr>,
}

#[derive(Debug)]
pub enum Pattern {
    Ident(Ident),
    Object { props: Vec<ObjPatProp>, rest: Option<P<Pattern>> },
    Array { elems: Vec<Option<PatElem>>, rest: Option<P<Pattern>> },
    /// only in assignment patterns: arbitrary member expression target
    Expr(P<Expr>),
}

#[derive(Debug)]
pub struct PatElem {
    pub target: Pattern,
    pub default: Option<Expr>,
}

#[derive(Debug)]
pub struct ObjPatProp {
    pub key: PropKey,
    pub target: Pattern,
    pub default: Option<Expr>,
}

#[derive(Debug, Clone)]
pub struct Ident {
    pub name: Rc<str>,
    pub line: u32,
}

#[derive(Debug)]
pub enum PropKey {
    Ident(Rc<str>),   // identifier or string literal name
    Str(Rc<[u16]>),   // string literal (utf16)
    Num(f64),
    Computed(P<Expr>),
    Private(Rc<str>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FuncKind {
    Normal,
    Arrow,
    Method,
    Getter,
    Setter,
    ClassConstructor,
    DerivedConstructor,
    ClassFieldInit,
    StaticBlock,
}

#[derive(Debug)]
pub struct Function {
    pub name: Option<Ident>,
    pub params: Vec<Param>,
    pub body: Vec<Stmt>,
    /// arrow with expression body: body contains a single Return statement
    pub expr_body: bool,
    pub kind: FuncKind,
    pub is_async: bool,
    pub is_generator: bool,
    pub strict: bool,
    pub simple_params: bool,
    pub src_start: usize,
    pub src_end: usize,
    pub scope: ScopeId,
    /// scope for the body when parameters have expressions (separate var scope)
    pub body_scope: ScopeId,
    /// is this a function expression (named function expressions bind their own name)
    pub is_expr: bool,
    pub is_decl: bool,
    pub line: u32,
    pub has_use_strict_directive: bool,
}

#[derive(Debug)]
pub struct Param {
    pub pat: Pattern,
    pub default: Option<Expr>,
    pub rest: bool,
}

#[derive(Debug)]
pub struct Class {
    pub name: Option<Ident>,
    pub extends: Option<P<Expr>>,
    pub members: Vec<ClassMember>,
    pub constructor: Option<Rc<Function>>,
    pub src_start: usize,
    pub src_end: usize,
    pub scope: ScopeId,
    pub decorators: Vec<Expr>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MethodKind {
    Method,
    Getter,
    Setter,
}

#[derive(Debug)]
pub enum ClassMember {
    Method { key: PropKey, func: Rc<Function>, kind: MethodKind, is_static: bool, decorators: Vec<Expr> },
    Field { key: PropKey, value: Option<Rc<Function>>, is_static: bool, is_accessor: bool, decorators: Vec<Expr> },
    StaticBlock(Rc<Function>),
}

#[derive(Debug)]
pub enum Stmt {
    Expr(Expr),
    Var(VarDecl),
    Function(Rc<Function>),
    Class(Rc<Class>),
    Return(Option<Expr>),
    If(Expr, P<Stmt>, Option<P<Stmt>>),
    Block(Block),
    For(P<ForStmt>),
    ForIn(P<ForInOf>),
    ForOf(P<ForInOf>),
    While(Expr, P<Stmt>),
    DoWhile(P<Stmt>, Expr),
    Break(Option<Rc<str>>),
    Continue(Option<Rc<str>>),
    Throw(Expr),
    Try(P<TryStmt>),
    Switch(P<SwitchStmt>),
    Labeled(Rc<str>, P<Stmt>),
    Empty,
    Debugger,
    With(Expr, P<Stmt>, ScopeId),
    Import(P<ImportDecl>),
    Export(P<ExportDecl>),
}

#[derive(Debug)]
pub struct Block {
    pub body: Vec<Stmt>,
    pub scope: ScopeId,
}

#[derive(Debug)]
pub enum ForInit {
    Var(VarDecl),
    Expr(Expr),
}

#[derive(Debug)]
pub struct ForStmt {
    pub init: Option<ForInit>,
    pub test: Option<Expr>,
    pub update: Option<Expr>,
    pub body: Stmt,
    pub scope: ScopeId,
}

#[derive(Debug)]
pub enum ForHead {
    /// var/let/const declaration with a single binding pattern
    Decl(VarKind, Pattern),
    /// assignment target (expression or pattern)
    Target(Pattern),
}

#[derive(Debug)]
pub struct ForInOf {
    pub head: ForHead,
    pub right: Expr,
    pub body: Stmt,
    pub is_await: bool,
    pub scope: ScopeId,
    /// for (var x = init in obj) legacy initializer
    pub var_init: Option<Expr>,
}

#[derive(Debug)]
pub struct TryStmt {
    pub block: Block,
    pub param: Option<Pattern>,
    pub handler: Option<Block>,
    pub catch_scope: ScopeId,
    pub finalizer: Option<Block>,
}

#[derive(Debug)]
pub struct SwitchStmt {
    pub disc: Expr,
    pub cases: Vec<SwitchCase>,
    pub scope: ScopeId,
}

#[derive(Debug)]
pub struct SwitchCase {
    pub test: Option<Expr>,
    pub body: Vec<Stmt>,
}

#[derive(Debug)]
pub struct ImportDecl {
    pub specifier: Rc<str>,
    pub default: Option<Ident>,
    pub namespace: Option<Ident>,
    pub named: Vec<(Rc<str>, Ident)>, // (imported name, local)
    pub phase: ImportPhase,
    pub attributes: Vec<(Rc<str>, Rc<str>)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImportPhase {
    Evaluation,
    Defer,
    Source,
}

#[derive(Debug)]
pub enum ExportDecl {
    /// export { a as b, c }  (local, exported)
    Named(Vec<(Rc<str>, Rc<str>)>),
    /// export { a as b } from "mod" ; (imported, exported)
    From { specifier: Rc<str>, names: Vec<(Rc<str>, Rc<str>)> },
    /// export * from "mod"
    All { specifier: Rc<str> },
    /// export * as ns from "mod"
    AllAs { specifier: Rc<str>, name: Rc<str> },
    /// export var/let/const/function/class
    Decl(Stmt),
    /// export default expression
    DefaultExpr(Expr),
    /// export default function/class declaration (possibly anonymous)
    DefaultFunc(Rc<Function>),
    DefaultClass(Rc<Class>),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BinOp {
    Add,
    Sub,
    Mul,
    Div,
    Mod,
    Exp,
    Shl,
    Shr,
    UShr,
    BitAnd,
    BitOr,
    BitXor,
    Eq,
    Ne,
    StrictEq,
    StrictNe,
    Lt,
    Le,
    Gt,
    Ge,
    In,
    InstanceOf,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogicalOp {
    And,
    Or,
    Nullish,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnaryOp {
    Neg,
    Plus,
    Not,
    BitNot,
    Typeof,
    Void,
    Delete,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AssignOp {
    Assign,
    Bin(BinOp),
    Logical(LogicalOp),
}

#[derive(Debug)]
pub enum MemberProp {
    Name(Rc<str>),
    Computed(P<Expr>),
    Private(Rc<str>),
}

#[derive(Debug)]
pub enum ArrayElem {
    Expr(Expr),
    Spread(Expr),
}

#[derive(Debug)]
pub enum PropDef {
    KeyValue(PropKey, Expr),
    /// shorthand {a}
    Shorthand(Ident),
    Method { key: PropKey, func: Rc<Function>, kind: MethodKind },
    Spread(Expr),
    /// __proto__: value
    Proto(Expr),
}

#[derive(Debug)]
pub struct TemplateQuasi {
    pub cooked: Option<Rc<[u16]>>,
    pub raw: Rc<[u16]>,
}

#[derive(Debug)]
pub enum Expr {
    Num(f64),
    Str(Rc<[u16]>),
    BigInt(Rc<str>),
    Regex { pattern: Rc<[u16]>, flags: Rc<[u16]> },
    Template { quasis: Vec<TemplateQuasi>, exprs: Vec<Expr> },
    TaggedTemplate { tag: P<Expr>, quasis: Rc<Vec<TemplateQuasi>>, exprs: Vec<Expr>, id: usize },
    Bool(bool),
    Null,
    Ident(Ident),
    This,
    SuperMember(MemberProp),
    SuperCall(Vec<ArrayElem>),
    NewTarget,
    ImportMeta,
    Array(Vec<Option<ArrayElem>>),
    Object(Vec<PropDef>),
    Function(Rc<Function>),
    Arrow(Rc<Function>),
    Class(Rc<Class>),
    Unary(UnaryOp, P<Expr>),
    Update { inc: bool, prefix: bool, target: P<Expr> },
    Binary(BinOp, P<Expr>, P<Expr>),
    Logical(LogicalOp, P<Expr>, P<Expr>),
    Assign { op: AssignOp, target: P<Pattern>, value: P<Expr> },
    Cond(P<Expr>, P<Expr>, P<Expr>),
    Call { callee: P<Expr>, args: Vec<ArrayElem>, optional: bool },
    New { callee: P<Expr>, args: Vec<ArrayElem> },
    Member { obj: P<Expr>, prop: MemberProp, optional: bool },
    /// boundary of an optional chain a?.b.c
    OptChain(P<Expr>),
    Seq(Vec<Expr>),
    Yield { arg: Option<P<Expr>>, delegate: bool },
    Await(P<Expr>),
    PrivateIn(Rc<str>, P<Expr>),
    ImportCall(P<Expr>, Option<P<Expr>>),
    /// parenthesized expression (kept for validation of assignment targets & name inference)
    Paren(P<Expr>),
}

impl Expr {
    pub fn unparen(&self) -> &Expr {
        let mut e = self;
        while let Expr::Paren(inner) = e {
            e = inner;
        }
        e
    }
    pub fn is_anonymous_fn(&self) -> bool {
        match self {
            Expr::Function(f) => f.name.is_none(),
            Expr::Arrow(_) => true,
            Expr::Class(c) => c.name.is_none(),
            _ => false,
        }
    }
}
