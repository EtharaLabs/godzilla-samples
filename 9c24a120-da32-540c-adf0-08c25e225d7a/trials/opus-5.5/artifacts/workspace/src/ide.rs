// What the checker remembers for the language server: the type of every
// expression and binding (for hover), every definition and use of a name
// (for go-to-definition, references and rename), and where constructors and
// types are mentioned.

use crate::source::Span;
use crate::types::Ty;
use std::collections::HashMap;

pub const NO_DEF: usize = usize::MAX;

/// Where a hover's documentation comes from.
#[derive(Clone, Debug)]
pub enum Doc {
    None,
    /// a user definition (its `##` comment)
    Def(usize),
    /// a library function, by name
    Builtin(String),
    /// written out
    Text(String),
}

/// Something with a type at a span.
#[derive(Clone, Debug)]
pub struct Item {
    pub span: Span,
    /// None for a binding whose type could not be found
    pub ty: Option<Ty>,
    pub doc: Doc,
}

#[derive(Clone, Debug)]
pub struct Def {
    pub name: String,
    pub span: Span,
    pub doc: Option<String>,
}

#[derive(Clone, Debug, Default)]
pub struct Ide {
    /// hoverable things in the order they were checked
    pub items: Vec<Item>,
    pub defs: Vec<Def>,
    /// a use of a name: (span, definition)
    pub uses: Vec<(Span, usize)>,
    /// definitions by the span that introduces them
    pub def_at: HashMap<(usize, usize), usize>,
    /// constructor mentions in expressions and patterns: (span, name)
    pub ctor_uses: Vec<(Span, String)>,
    /// type names mentioned in types, record literals and record patterns
    pub type_uses: Vec<(Span, String)>,
    /// library names used: (span, name)
    pub builtin_uses: Vec<(Span, String)>,
    /// names that resolve to nothing: (span, name)
    pub unbound_uses: Vec<(Span, String)>,
    /// types the program declares
    pub user_types: std::collections::HashSet<String>,
    /// checking a `let` destructuring pattern
    pub in_let_pattern: bool,
}

impl Ide {
    /// The definition introduced at `span`, made on first sight.
    pub fn def(&mut self, name: &str, span: Span, doc: Option<String>) -> (usize, bool) {
        if let Some(&d) = self.def_at.get(&(span.lo, span.hi)) {
            return (d, false);
        }
        let id = self.defs.len();
        self.defs.push(Def { name: name.to_string(), span, doc });
        self.def_at.insert((span.lo, span.hi), id);
        (id, true)
    }

    pub fn item(&mut self, span: Span, ty: &Ty, doc: Doc) {
        self.items.push(Item { span, ty: Some(ty.clone()), doc });
    }

    /// A binding that failed to check: only its documentation is known.
    pub fn untyped(&mut self, span: Span, doc: Doc) {
        self.items.push(Item { span, ty: None, doc });
    }
}
