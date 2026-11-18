// `lini fmt`: reprint a document in canonical style.
//
// The formatter has its own lexer and parser (src/format/) that keep source
// positions, comments and blank lines; they follow the reference grammar and
// report the same first syntax error, which `parser::parse` reuses too.
//
//   lex.rs    tokens, each carrying the comments/blank lines in front of it
//   parse.rs  recursive descent into the concrete tree (cst.rs), errors
//   expr.rs   the math-expression reading of binding right-hand sides
//   print.rs  layout: 80 columns, 2-space indent, rows, runs, wrapping

mod cst;
pub(crate) mod expr;
pub(crate) mod lex;
pub(crate) mod parse;
mod print;

use crate::diag::Diag;

// The first syntax error, exactly as the reference compiler reports it (its
// `fmt` and compile commands share one parser). Ok(()) for a well-formed file.
pub fn syntax_check(src: &str) -> Result<(), Diag> {
    let lexed = lex::lex(src)?;
    let mut p = parse::Parser::new(src, &lexed.toks);
    p.parse_doc()?;
    Ok(())
}

pub fn format(src: &str) -> Result<String, Diag> {
    let lexed = lex::lex(src)?;
    let mut p = parse::Parser::new(src, &lexed.toks);
    let doc = p.parse_doc()?;
    let mut out = print::Out::new();
    out.doc(&doc);
    Ok(out.finish())
}
