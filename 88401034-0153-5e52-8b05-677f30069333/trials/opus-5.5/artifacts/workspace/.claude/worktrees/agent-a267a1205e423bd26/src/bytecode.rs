// Bytecode definitions shared by compiler and VM.

use crate::ast::FuncKind;
use crate::value::*;
use std::rc::Rc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BindKind {
    Var,
    Let,
    Const,
    Class,
    Function,
    Param,
    CatchParam,
    /// internal bindings: this, arguments, new.target, home, private names
    Internal,
    /// the name of a named function expression (immutable, silently ignores writes in sloppy)
    FuncName,
    Import,
}

#[derive(Debug)]
pub struct ScopeInfo {
    pub names: Vec<JsStr>,
    pub kinds: Vec<BindKind>,
    pub is_function: bool,
}

impl ScopeInfo {
    pub fn find(&self, name: &JsStr) -> Option<usize> {
        self.names.iter().position(|n| n == name)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MethodTarget {
    Proto,
    Ctor,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MKind {
    Method,
    Getter,
    Setter,
}

#[derive(Debug)]
pub struct TemplateData {
    pub cooked: Vec<Option<JsStr>>,
    pub raw: Vec<JsStr>,
    pub id: usize,
}

#[derive(Clone, Copy, Debug)]
pub enum Op {
    // constants
    Undef,
    Null,
    True,
    False,
    Int(i32),
    Const(u32),
    Empty,
    // stack
    Pop,
    Dup,
    Dup2,
    Swap,
    /// [a b c] -> [c a b]
    Rot3,
    /// [a b c d] -> [d a b c]
    Rot4,
    /// copy the value n below the top: [.. x a1..an] -> [.. x a1..an x]
    Pick(u16),
    // locals / env
    GetLocal(u32),
    GetLocalChk(u32, u32),
    SetLocal(u32),
    InitLocal(u32),
    ClearLocal(u32),
    GetEnv(u16, u32),
    GetEnvChk(u16, u32, u32),
    SetEnv(u16, u32),
    SetEnvChk(u16, u32, u32),
    InitEnv(u16, u32),
    GetName(u32),
    SetName(u32),
    TypeofName(u32),
    DeleteName(u32),
    /// pushes [this, func] for a call to an identifier (with-scope aware)
    GetNameCall(u32),
    GetGlobal(u32),
    SetGlobal(u32),
    TypeofGlobal(u32),
    /// declare global var (name, is_function)
    DeclareGlobalVar(u32),
    DeclareGlobalFunc(u32),
    DeclareGlobalLex(u32, bool),
    InitGlobalLex(u32),
    PushScope(u32),
    PopScope,
    CopyScope,
    PushWith,
    ThrowConst(u32),
    // function frame
    This,
    ThisChk,
    SetThis,
    NewTarget,
    GetArg(u32),
    GetRest(u32),
    CreateArguments(bool),
    Callee,
    Home,
    // properties
    GetProp(u32),
    GetPropOpt(u32),
    GetElem,
    SetProp(u32),
    SetElem,
    DeleteProp(u32),
    DeleteElem,
    GetSuper(u32),
    GetSuperElem,
    SetSuper(u32),
    SetSuperElem,
    GetPrivate,
    SetPrivate,
    PrivateIn,
    /// [obj] -> [obj, obj.key]  (for method calls: leaves this then func)
    GetMethod(u32),
    GetMethodElem,
    ToPropKey,
    // literals
    NewObject,
    NewArray(u32),
    ArrayPush,
    ArrayHole,
    ArraySpread,
    DefineField(u32),
    DefineFieldComputed,
    DefineAccessor(u32, MKind),
    DefineAccessorComputed(MKind),
    CopyDataProps,
    /// [target source excludedKeys...(n)] object rest
    CopyDataPropsExcept(u32),
    SetProtoLit,
    RegExp(u32),
    Template(u32),
    // functions & classes
    Closure(u32),
    /// [home] -> [home, closure]
    Method(u32),
    SetFunctionName(u8),
    /// [heritage?] -> [F, proto]
    CreateClass(u32, bool),
    /// [F proto (key)?] method definition
    DefineMethod(u32, MethodTarget, MKind, u32),
    DefineMethodComputed(MethodTarget, MKind, u32),
    /// [F proto key?] -> instance field registration (key idx or computed when u32::MAX)
    AddField(u32, u32, bool),
    AddFieldComputed(u32, bool),
    /// [F proto sym] private method/accessor for instances
    AddPrivateMethod(u32, MKind, bool),
    /// [F proto] run static field initializer with key
    StaticField(u32, u32),
    StaticFieldComputed(u32),
    /// [F proto sym]
    StaticPrivateField(u32),
    StaticBlock(u32),
    NewPrivateName(u32),
    // operators
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
    Neg,
    Plus,
    Not,
    BitNot,
    Typeof,
    Void,
    Inc,
    Dec,
    ToNumeric,
    ToStr,
    // control
    Jump(u32),
    JumpIfFalse(u32),
    JumpIfTrue(u32),
    JumpIfFalseKeep(u32),
    JumpIfTrueKeep(u32),
    JumpIfNullishKeep(u32),
    JumpIfNotNullishKeep(u32),
    /// jump if top is undefined (pops if not jumping? no: always pops)
    JumpIfNotUndef(u32),
    /// jumps if top is null or undefined (pops)
    JumpIfNullish(u32),
    Return,
    TryStart(u32),
    TryEnd,
    Throw,
    ThrowRef(u32),
    ThrowType(u32),
    // calls (stack: this, func, args...)
    Call(u32, u32),
    CallArray(u32),
    CallEval(u32),
    CallEvalArray,
    New(u32),
    NewArray_,
    SuperCall(u32),
    SuperCallArray,
    // iteration
    GetIterator,
    GetAsyncIterator,
    /// [iter next] -> [iter next value] or jump when done
    IterNext(u32),
    IterClose,
    IterCloseSilent,
    /// destructuring: [iter next done] -> [iter next done value]
    IterValue,
    IterRest,
    IterDone,
    ForInStart,
    ForInNext(u32),
    // generators / async
    Yield,
    /// after resume from yield: handles throw/return; return jumps to target
    GenResume(u32),
    Await,
    /// [iter next received] delegation step; done -> push value, continue
    YieldStar(u32, bool),
    AsyncIterValue,
    /// convert iterator result of async iteration: [iter next result] -> value or jump when done
    AsyncIterCheck(u32),
    // misc
    Debugger,
    ImportMeta,
    DynamicImport,
    Nop,
    /// [obj] -> [obj] throws if not object (iterator results etc.)
    CheckObj,
    /// push undefined if top is Empty (used by super calls)
    /// dispose resources at scope exit (using declarations)
    AddDisposable(bool),
    DisposeScope(u32),
    /// generator: suspend after prologue
    GenStart,
    GetImport(u32),
    SuperCallForward,
    /// [iter next] -> [iter next result] (no done check)
    IterCallNext,
    /// [iter next] -> [awaitable] calls return() for async iterator close
    IterCloseAsync,
    /// [F proto sym] instance private field
    AddFieldPrivate(u32),
    /// module: end of instantiation part
    ModuleBodyStart,
    /// set completion value slot (eval/repl)
    SetCompletion(u32),
    /// [exc iter next] close iterator ignoring errors then rethrow exc
    IterCloseThrow,
    /// object pattern: throw if value is null/undefined (keeps it)
    RequireObjCoercible,
    /// array destructuring: [value] -> [iter next done]
    DestructIter,
    /// store frame `this` (derived constructor after super)
    BindThis,
    /// [result F] run instance field initializers of F on result -> [result]
    InitFields,
    /// bind `this` in an env slot (derived constructor, captured this): errors if already bound
    BindThisEnv(u16, u32),
}

pub struct FunctionCode {
    pub name: JsStr,
    pub ops: Vec<Op>,
    pub consts: Vec<Value>,
    pub keys: Vec<PropKey>,
    pub funcs: Vec<Rc<FunctionCode>>,
    pub scopes: Vec<Rc<ScopeInfo>>,
    pub templates: Vec<Rc<TemplateData>>,
    pub regexps: Vec<(JsStr, JsStr)>,
    pub strings: Vec<JsStr>,
    pub nlocals: u32,
    pub length: u32,
    pub kind: FuncKind,
    pub is_async: bool,
    pub is_generator: bool,
    pub strict: bool,
    pub source: Rc<str>,
    pub src_start: usize,
    pub src_end: usize,
    pub is_arrow: bool,
    pub has_simple_params: bool,
    pub line: u32,
    /// a function with no own `prototype` (methods, arrows, async functions, ...)
    pub no_prototype: bool,
    pub class_source: bool,
    /// name set from a class/declaration (affects toString for default ctor)
    pub is_default_ctor: bool,
    pub is_script: bool,
    pub is_module: bool,
    pub is_eval: bool,
}

impl FunctionCode {
    pub fn is_constructor(&self) -> bool {
        matches!(self.kind, FuncKind::Normal | FuncKind::ClassConstructor | FuncKind::DerivedConstructor)
            && !self.is_async
            && !self.is_generator
    }
    pub fn source_text(&self) -> String {
        if self.is_default_ctor {
            return String::new();
        }
        self.source.chars().skip(self.src_start).take(self.src_end.saturating_sub(self.src_start)).collect()
    }
}

impl std::fmt::Debug for FunctionCode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        writeln!(f, "function {} (locals={}, strict={})", self.name, self.nlocals, self.strict)?;
        for (i, op) in self.ops.iter().enumerate() {
            writeln!(f, "  {:4} {:?}", i, op)?;
        }
        for (i, func) in self.funcs.iter().enumerate() {
            writeln!(f, "-- nested #{}:", i)?;
            write!(f, "{:?}", func)?;
        }
        Ok(())
    }
}
