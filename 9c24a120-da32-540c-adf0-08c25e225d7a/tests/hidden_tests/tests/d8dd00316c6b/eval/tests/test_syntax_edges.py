"""Syntax edge cases: the lexer's literal and layout rules, every parse-error path the
CLI can reach (with its exact wording, caret span and recovery), the canonical
pretty-print of unusual syntax, and user computation-expression desugaring.

Each case writes `main.pyfun` and runs one command; the expected transcript (exit
code, stdout, stderr) was captured from the reference binary.
"""

import pytest

from conftest import case_transcript, golden_name, read_golden, run_case, transcript


def _c(id, src, cmd="check"):
    return {"id": id, "files": {"main.pyfun": src}, "args": [cmd, "main.pyfun"]}


def _check(run, workdir, case):
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


# ---------------------------------------------------------------- lexer

LEXER_CASES = [
    _c("and_and_operator", "let x = true && false\n"),
    _c("invalid_escape", 'let s = "a\\qb"\n'),
    _c("unicode_escape_without_brace", 'let s = "\\u1F600"\n'),
    _c("unicode_escape_unclosed", 'let s = "\\u{1F600"\n'),
    _c("unicode_escape_not_a_scalar", 'let s = "\\u{D800}"\n'),
    _c("unicode_escape_too_large", 'let s = "\\u{110000}"\n'),
    _c("unterminated_raw_string", 'let s = r"C:\\path\n'),
    _c("unterminated_raw_triple_string", 'let s = r"""line one\nline two\n'),
    _c("unterminated_triple_string", 'let s = """never closed\n'),
    _c("unterminated_string", 'let s = "never closed\n'),
    _c("unterminated_fstring", 'let s = f"abc\n'),
    _c("unterminated_triple_fstring", 'let s = f"""abc {1}\n'),
    _c("unterminated_fstring_hole", 'let x = 1\nlet s = f"abc {x\n'),
    _c("unterminated_string_inside_fstring_hole", 'let s = f"a {"x} b"\n'),
    _c("unterminated_triple_string_inside_fstring_hole", 'let s = f"a {"""x} b"\n'),
    _c("single_close_brace_in_fstring", 'let s = f"a } b"\n'),
    _c("empty_fstring_hole", 'let s = f"a {} b"\n'),
    _c("bad_character_inside_fstring_hole", 'let s = f"a {1 $ 2} b"\n'),
    _c("leftover_tokens_in_fstring_hole", 'let s = f"a {1 2 )} b"\n'),
    _c("fstring_hole_escaped_quote", 'let s = f"[{String.upper "a\\"b"}] {{literal}}"\nprint s\n', "run"),
    _c("fstring_hole_nested_braces", 'type P = { x: int }\nlet s = f"{(P { x = 1 }).x} and {[1, 2]}"\nprint s\n', "run"),
    _c("fstring_hole_triple_quoted_string", 'let s = f"<{String.upper """a{b}c"""}>"\nprint s\n', "run"),
    _c("fstring_debug_holes", 'let x = 3\nlet s = f"{x=} {x = } {x == 3} {x != 2} {x <= 9} {x >= 1}"\nprint s\n', "run"),
    _c("unexpected_character", "let x = 1 @ 2\n"),
    _c("unexpected_non_ascii_character", "let x = 1 \u00a7 2\n"),
    _c("invalid_hex_literal", "let x = 0x\n"),
    _c("integer_literal_too_large", "let x = 99999999999999999999\n"),
    _c("hex_literal_too_large", "let x = 0xFFFFFFFFFFFFFFFFFF\n"),
    _c("float_exponent_forms", "let a = 1e3\nlet b = 2.5E-2\nlet c = 1_000.5e+1\nlet d = 7e\n", "parse"),
    _c("trailing_dot_after_number", "let a = 1.\nlet b = 3\n"),
    _c("radix_prefix_then_separator", "let a = 0X_FF\n"),
    _c("radix_literals_with_separators", "let a = 0XF_F\nlet b = 0O17\nlet c = 0B1010_1010\nlet d = 0xdead_BEEF\nprint [a, b, c, d]\n", "run"),
    _c("string_escapes_round_trip", 'let s = "tab\\there \\"q\\" back\\\\slash\\r\\n"\nprint (String.len s)\n', "parse"),
    _c("fstring_literal_escapes_round_trip", 'let x = 1\nlet s = f"tab\\t \\"q\\" b\\\\s {{x}} {x}\\n"\n', "parse"),
    _c("crlf_inside_triple_quoted_strings",
       'let s = """a\r\nb\rc"""\r\nlet t = f"""x\r\n{s}"""\r\nlet r = r"""p\r\nq"""\r\n', "parse"),
    _c("raw_strings_keep_backslashes", 'let a = r"C:\\new\\table"\nlet b = r"""multi\n\\line"""\nprint a\nprint b\n', "run"),
    _c("doc_comment_where_an_expression_is_expected", "  let x = 1 +\n## stray doc\n"),
    _c("indented_first_line_then_column_zero", "    let x = 1\nlet y = 2\n"),
    _c("tab_inside_a_line_is_whitespace", "let x =\t1\t+\t2\nprint x\n", "run"),
    _c("comment_after_code_and_hash_hash_inline", "let x = 1 # trailing ## not a doc\n  ## indented hash-hash is a comment\nprint x\n", "run"),
    _c("doc_comment_with_hash_payload", "### heading-like doc\n##\n## second\nlet x = 1\n", "parse"),
]


@pytest.mark.parametrize("case", LEXER_CASES, ids=[c["id"] for c in LEXER_CASES])
def test_lexer_edge_cases(run, workdir, case):
    """CATCHES: a lexer that accepts malformed literals or escapes, words a lex error or
    places its caret differently, mishandles f-string holes (nested strings, braces,
    debug `=` markers), CR/CRLF inside strings, radix/exponent literals, or comments."""
    _check(run, workdir, case)


# ---------------------------------------------------------------- parse errors

PARSE_ERROR_CASES = [
    _c("def_with_bare_params", "def area w h = w * h\n"),
    _c("def_with_python_signature", "def area(w: int, h: int) -> int:\n    return w * h\n"),
    _c("def_with_no_params", "def greet():\n    print(\"hi\")\n"),
    _c("def_inside_a_block", "let f x =\n  def g y = y + 1\n  g x\n"),
    _c("def_called_as_a_function_is_fine", "let def x = x + 1\nprint (def 41)\n", "run"),
    _c("def_followed_by_newline_is_not_a_hint", "let def x = x\nlet y = def\n  1\n"),
    _c("module_body_with_non_let", "module M =\n  type T = A\n"),
    _c("module_body_trailing_separator", "module M =\n  let a = 1\n  let b = a + 1\nprint M.b\n", "run"),
    _c("duplicate_extern_keyword", 'extern op : string -> string = builtins.open(mode = "r", mode = "w")\n'),
    _c("extern_kwarg_negative_float", "extern rnd : float -> float = builtins.round(ndigits = -1.5)\n", "parse"),
    _c("extern_kwarg_negative_non_number", 'extern rnd : float -> float = builtins.round(ndigits = -"x")\n'),
    _c("extern_kwarg_false_and_float", "extern s : List int -> List int = builtins.sorted(reverse = false, key = 1.5)\n", "parse"),
    _c("extern_kwarg_not_a_literal", "extern s : List int -> List int = builtins.sorted(reverse = x)\n"),
    _c("extern_type_with_params", "extern type Ref a b\nextern mk : a -> Ref a b = weakref.ref\n", "parse"),
    _c("empty_record_type", "type R = {}\n"),
    _c("record_type_trailing_comma", "type R = { a: int, b: string, }\nlet r = R { a = 1, b = \"x\", }\nprint r\n", "run"),
    _c("type_expected", "type T = A (,)\n"),
    _c("type_tuple_payload", "type T = Pair (int, string) | Triple (int, int, int)\nlet p = Pair (1, \"a\")\nprint p\n", "run"),
    _c("indented_variants_with_trailing_separator",
       "type Color =\n  | Red\n  | Green\n  Blue\nlet c = Blue\nprint c\n", "run"),
    _c("active_pattern_underscore_first", "let (|_|) x = x\n"),
    _c("active_pattern_partial_two_cases", "let (|A|B|_|) x = Some x\n"),
    _c("active_pattern_without_parameter", "let (|Even|Odd|) = 1\n"),
    _c("active_pattern_doc_comment", "## Classify parity.\nlet (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\nprint (match 3:\n  case Even: \"even\"\n  case Odd: \"odd\")\n", "parse"),
    _c("function_binding_destructures", "let (a, b) x = x\n"),
    _c("mut_binding_destructures", "let mut (a, b) = (1, 2)\n"),
    _c("block_ends_with_let", "let f x =\n  let y = x + 1\n"),
    _c("assign_to_non_variable", "let mut xs = [1]\nlet f u =\n  List.head xs <- 2\n"),
    _c("capitalised_let_name", "let Point = 1\n"),
    _c("refutable_list_parameter", "let f ([a]) = a\n"),
    _c("refutable_or_parameter", "let f (1 | 2) = 0\n"),
    _c("refutable_as_parameter", "let f ((a, b) as p) = p\n"),
    _c("refutable_literal_parameter", "let f (\"x\") = 0\n"),
    _c("refutable_bool_in_tuple_parameter", "let f (a, true) = a\n"),
    _c("match_with_fsharp_arms", "let f x =\n  match x with\n  | 1 -> 2\n"),
    _c("match_arms_trailing_separator", "let f x =\n  match x:\n    case 1: \"one\"\n    case _: \"other\"\nprint (f 1)\n", "run"),
    _c("ce_item_that_is_a_custom_operation", "module Html =\n  let zero = 1\nlet page = Html { class_ \"board\" }\n"),
    _c("record_update_without_fields", "type P = { x: int }\nlet p = P { x = 1 }\nlet q = { p with }\n"),
    _c("record_literal_without_fields", "type P = { x: int }\nlet p = P { }\n"),
    _c("bare_record_literal", "let p = { x = 1 }\n"),
    _c("unit_body_empty", "measure m\nlet x = 1<>\n"),
    _c("unit_exponent_not_integer", "measure m\nlet x = 1<m^x>\n"),
    _c("unit_exponent_negative", "measure m\nmeasure s\nlet a = 1<m^2 s^-1>\n"),
    _c("unit_dimensionless_and_inverse", "measure s\nlet hz = 5.0<1/s>\nlet n = 3<1>\n", "parse"),
    _c("measure_alias_inverse", "measure s\nmeasure Hz = 1/s\nlet f = 50.0<Hz>\nprint f\n", "parse"),
    _c("ce_unterminated", "let r = option {\n  let! x = Some 1\n  return x\n"),
    _c("ce_for_without_in", "let r = seq { for x of [1]: yield x }\n"),
    _c("ce_for_with_empty_body", "let r = seq {\n  for x in [1, 2]:\n}\n"),
    _c("ce_bad_item", "let r = seq {\n  for x in [1]:\n    yield x )\n}\n"),
    _c("ce_stray_semicolon", "let r = seq { yield 1 ; }\n"),
    _c("def_shapes_that_are_not_definitions", "let def a = print a\nlet x = 5\ndef x |> id\ndef x\n", "run"),
    _c("extern_target_on_an_indented_line", "extern f : float -> float =\n    math.floor\n"),
    _c("line_starting_with_underscore_continues", "let f a b = a\nlet r = f 1\n_\n"),
    _c("ce_argument_misaligned",
       "let add a b = a + b\nlet r =\n  option {\n    let x = add 1\n      2\n    return x\n  }\n"),
    _c("ce_argument_aligned_past_head",
       "let add a b = a + b\nlet r =\n  option {\n    let x = add 1\n              2\n    return x\n  }\nprint r\n", "run"),
    _c("ce_argument_inside_brackets",
       "let add a b = a + b\nlet r =\n  option {\n    let x = (add 1\n      2)\n    return x\n  }\nprint r\n", "run"),
    _c("ce_for_body_ends_at_dedent",
       "let r =\n  seq {\n    for x in [1, 2]:\n      yield x\n      yield x * 10\n    yield 0\n  }\nprint (Seq.toList r)\n", "run"),
    _c("ce_for_nested_bracket_body",
       "let r =\n  seq {\n    for x in [1, 2]:\n      yield (x\n        + 1)\n  }\nprint (Seq.toList r)\n", "run"),
    _c("float_pattern", "let f x =\n  match x:\n    case 1.5: 1\n    case _: 0\n"),
    _c("negative_float_pattern", "let f x =\n  match x:\n    case -1.5: 1\n    case _: 0\n"),
    _c("not_a_pattern", "let f x =\n  match x:\n    case ->: 1\n"),
    _c("negative_int_pattern", "let f x =\n  match x:\n    case -1: \"minus one\"\n    case _: \"other\"\nprint (f (-1))\n", "run"),
    _c("list_pattern_rest_must_be_variable", "let f xs =\n  match xs:\n    case [a, *Some]: a\n    case _: 0\n"),
    _c("empty_record_pattern", "type P = { x: int }\nlet f p =\n  match p:\n    case P {}: 1\n"),
    _c("record_pattern_as_constructor_argument",
       "type P = { x: int, y: int }\ntype W = Wrap P\nlet f w =\n  match w:\n    case Wrap P { x, y = 0 }: x\n    case Wrap P { x = n }: n * 10\nprint (f (Wrap (P { x = 2, y = 0 })))\nprint (f (Wrap (P { x = 2, y = 1 })))\n", "run"),
    _c("unknown_qualified_payload_type",
       "type T = A | B Option.Option\nlet f t =\n  match t:\n    case B None: 1\n    case _: 0\n"),
    _c("missing_then", "let x = if true 1 else 2\n"),
    _c("missing_else", "let x = if true then 1\n"),
    _c("unclosed_paren", "let x = (1 + 2\n"),
    _c("unclosed_list", "let x = [1, 2\n"),
    _c("let_rec", "let rec fact n = if n == 0 then 1 else n * fact (n - 1)\n"),
    _c("discard_with_params", "let _ x = x\n"),
    _c("discard_mut", "let mut _ = 1\n"),
    _c("empty_match", "let f x =\n  match x:\n"),
]


@pytest.mark.parametrize("case", PARSE_ERROR_CASES, ids=[c["id"] for c in PARSE_ERROR_CASES])
def test_parse_errors_and_layout(run, workdir, case):
    """CATCHES: a parser that accepts invalid syntax, rejects valid layout (trailing
    separators, aligned CE arguments, indented variants), words a targeted hint (`def`,
    `let rec`, F#-style `match ... with`, bare record literals, refutable parameters)
    differently, or points its caret at the wrong span."""
    _check(run, workdir, case)


# ---------------------------------------------------------------- canonical form

CANONICAL_CASES = [
    _c("operator_sections", "let fs = [(/), (**), (!=), (>), (<=), (>=), (//), (%), (==), (<), (+), (-), (*)]\n", "parse"),
    _c("operator_sections_run",
       "let ap f = f 7 2\nprint [ap (/), ap (**), ap (//), ap (%)]\nprint [ap (!=), ap (>), ap (<=), ap (>=), ap (==), ap (<)]\n", "run"),
    _c("elif_chain", "let f n =\n  if n < 0 then \"neg\"\n  elif n == 0 then \"zero\"\n  elif n < 10 then \"small\"\n  else \"big\"\n", "parse"),
    _c("docs_before_undocumentable_items",
       "## Metres.\nmeasure m\n## A module.\nmodule M =\n  let a = 1\n## An import.\nimport Other\n## An expression.\nprint M.a\n", "parse"),
    _c("elif_chain_with_block_branches",
       "let f n =\n  if n < 0 then\n    let m = 0 - n\n    m\n  elif n == 0 then\n    match n:\n      case _: 0\n  elif n == 1 then 1\n  else\n    let k = n * 2\n    k\n", "parse"),
    _c("doc_comment_with_blank_line", "## First line.\n##\n## After a blank doc line.\nlet x = 1\n", "parse"),
    _c("measure_alias_dimensionless_numerator", "measure s\nmeasure Hz = 1/s\n", "parse"),
    _c("string_with_tab_escape", 'let s = "a\\tb"\nlet t = f"c\\td{s}"\nlet q = f"say \\"{s}\\" \\\\ done"\n', "parse"),
    _c("qualified_record_literal", "let p = Geometry.Point { x = 1, y = 2 }\n", "parse"),
    _c("unit_annotations", "measure m\nmeasure s\nlet v = 3.0<m/s^2>\nlet a = 1<m^2 s>\n", "parse"),
]


@pytest.mark.parametrize("case", CANONICAL_CASES, ids=[c["id"] for c in CANONICAL_CASES])
def test_canonical_form(run, workdir, case):
    """CATCHES: a pretty-printer that drops `elif` chains, mis-spells operator sections,
    loses blank doc-comment lines, prints dimensionless units or string escapes (tabs,
    quotes, backslashes, braces in f-strings) differently."""
    _check(run, workdir, case)


# ---------------------------------------------------------------- user computation expressions

LOG = (
    "module Log =\n"
    "  let bind m f =\n"
    "    let (v, out) = m\n"
    "    let (w, more) = f v\n"
    "    (w, List.concat out more)\n"
    "  let return_ x = (x, [])\n"
    "  let returnFrom m = m\n"
    "  let zero = (0, [\"zero\"])\n"
    "  let yield_ x = (x, [f\"yield {x}\"])\n"
    "  let yieldFrom m = m\n"
    "  let combine a b =\n"
    "    let (x, out) = a\n"
    "    let (y, more) = b 0\n"
    "    (x + y, List.concat out more)\n"
    "  let delay f = f\n"
    "  let for_ xs f = List.fold (fun acc x -> combine acc (fun _ -> f x)) (0, []) xs\n"
    "let tell msg = ((), [msg])\n"
)

USER_CE_CASES = [
    _c("user_ce_do_bang_then_return", LOG + "let r =\n  Log {\n    do! tell \"start\"\n    let! x = (20, [\"twenty\"])\n    let y = x + 1\n    return y * 2\n  }\nprint r\n", "run"),
    _c("user_ce_trailing_do_bang", LOG + "let r =\n  Log {\n    let! x = (1, [\"one\"])\n    do! tell f\"got {x}\"\n  }\nprint r\n", "run"),
    _c("user_ce_return_bang", LOG + "let r =\n  Log {\n    let! x = (5, [\"five\"])\n    return! (x * 3, [\"tripled\"])\n  }\nprint r\n", "run"),
    _c("user_ce_yield_bang_and_yield", LOG + "let r =\n  Log {\n    yield! (10, [\"ten\"])\n    yield 3\n    yield! (4, [\"four\"])\n  }\nprint r\n", "run"),
    _c("user_ce_for", LOG + "let r =\n  Log {\n    for x in [1, 2, 3]:\n      yield x\n    yield 100\n  }\nprint r\n", "run"),
    _c("user_ce_empty_braces_are_a_record_literal", LOG + "let e = Log { }\n"),
    _c("user_ce_compiled", LOG + "let r =\n  Log {\n    do! tell \"a\"\n    let k = 2\n    yield! (k, [])\n    return! (1, [])\n  }\n", "compile"),
    _c("user_ce_ill_typed_builder_member",
       LOG.replace("List.concat out more", "List.concat [out, more]") + "let r = Log { return 1 }\n"),
    _c("user_ce_let_must_be_followed", LOG + "let r =\n  Log {\n    let x = 1\n  }\n"),
    _c("user_ce_let_bang_must_be_followed", LOG + "let r =\n  Log {\n    let! x = (1, [])\n  }\n"),
    _c("user_ce_return_not_last", LOG + "let r =\n  Log {\n    return 1\n    yield 2\n  }\n"),
    _c("user_ce_return_bang_not_last", LOG + "let r =\n  Log {\n    return! (1, [])\n    yield 2\n  }\n"),
    _c("compose_avoids_capturing_pf_x",
       "let _pf_x = 100\nlet inc n = n + _pf_x\nlet dbl n = n * 2\nlet h = inc >> dbl\nlet g = (fun v -> v + _pf_x) << dbl\nprint (h 1)\nprint (g 1)\n", "run"),
    _c("compose_avoids_capturing_pf_x_compiled",
       "let _pf_x = 100\nlet _pf_x0 = 1\nlet h = (fun v -> v + _pf_x + _pf_x0) >> (fun w -> w * 2)\n", "compile"),
]


@pytest.mark.parametrize("case", USER_CE_CASES, ids=[c["id"] for c in USER_CE_CASES])
def test_user_builder_desugaring(run, workdir, case):
    """CATCHES: a user-builder desugaring that calls the wrong protocol member for `do!`,
    `return!`, `yield!`, `for` or an empty block (`zero`), allows a `let`/`let!` with
    nothing after it or a non-final `return`, or a composition lambda whose parameter
    captures a user binding named `_pf_x`."""
    _check(run, workdir, case)


# ---------------------------------------------------------------- token wording

TOKENS = [
    "let", "mut", "pure", "if", "then", "else", "match", "with", "fun", "type", "return", "yield",
    "do", "measure", "extern", "module", "import", "not", "and", "or", "!", "^", "<", ">", "{", "}",
    "]", "true", "false", "==", "!=", "<=", ">=", ">>", "<<", "<-", "+", "-", "*", "/", "//", "|>",
    "<|", "|", "->", ")", ",", ":", ".", "...", "_", "7", "2.5", '"text"', "elif", "case", "%",
    "**", "?", 'f"x"',
]
TOKEN_WORDING_CASES = [
    {"id": "describe_every_token", "args": ["repl"], "stdin": "".join(f"import {t}\n" for t in TOKENS) + ":quit\n"},
]


@pytest.mark.parametrize("case", TOKEN_WORDING_CASES, ids=[c["id"] for c in TOKEN_WORDING_CASES])
def test_unexpected_token_wording(run, workdir, case):
    """CATCHES: a diagnostic that names an unexpected token differently (`found `let``,
    `found integer `7``, `found string literal`, `found `token`` ...) for any keyword,
    operator, bracket or literal kind."""
    _check(run, workdir, case)


# ---------------------------------------------------------------- recovery (language server)

# `check`, `compile` and `run` stop at the first syntax error; the language server
# parses with recovery instead (a bad character is skipped, a broken item is skipped
# to the next item boundary) and publishes every syntax error at once.
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
SHUTDOWN = {"jsonrpc": "2.0", "id": 2, "method": "shutdown"}
EXIT = {"jsonrpc": "2.0", "method": "exit"}


def _lsp(id, text):
    open_doc = {"jsonrpc": "2.0", "method": "textDocument/didOpen",
                "params": {"textDocument": {"uri": "file:///recover.pyfun", "languageId": "pyfun",
                                            "version": 1, "text": text}}}
    return {"id": id, "args": ["lsp"], "lsp": [INIT, open_doc, SHUTDOWN, EXIT]}


RECOVERY_CASES = [
    _lsp("bad_literal_closing_each_kind_of_block",
         "module M =\n  let a = 1\n  0x\n"
         "type T =\n  | A\n  | B\n  0x\n"
         "let f x =\n  let y = x\n  y\n  0x\n"
         "let g x =\n  match x:\n    case 1: 2\n    case _: 3\n    0x\n"
         "let ok = 1\n"),
    _lsp("unterminated_string_ending_a_block", "let f x =\n  let y = x\n  y\n  \"never closed\n"),
    _lsp("broken_items_are_skipped",
         "let x = 1\n)\nlet 1 =\n  let a = 1\n  a\nlet z = 3\nlet w = (z +\n  1)\n## dangling doc with nothing after it\n"),
    _lsp("lex_errors_inside_fstring_holes",
         'let s = f"a {1 $ 2} b {3 @ 4}"\nlet t = "fine"\n'),
]


@pytest.mark.parametrize("case", RECOVERY_CASES, ids=[c["id"] for c in RECOVERY_CASES])
def test_syntax_error_recovery(run, workdir, case):
    """CATCHES: a recovering parser that stops at the first error, loses the items after a
    broken one, reports a skipped bad character twice (or at the wrong offset inside an
    f-string hole), or mis-handles a block whose last line is only a bad character."""
    proc, _ = run_case(run, workdir, case)
    assert case_transcript(proc, case, workdir) == read_golden(__file__, golden_name(case["id"]))


# ---------------------------------------------------------------- a façade module that does not lex

FACADE_LEX_ERROR_CASES = [
    {
        "id": "facade_module_with_a_lex_error",
        "files": {
            "pyfun.toml": "[project]\nname = \"demo\"\n",
            ".pyfun/facades/pyfun-bad/bad.pyfun": "let s = \"unterminated\n",
            "main.pyfun": "import Bad\nlet x = 1\n",
        },
        "args": ["check", "main.pyfun"],
    },
]


@pytest.mark.parametrize("case", FACADE_LEX_ERROR_CASES, ids=[c["id"] for c in FACADE_LEX_ERROR_CASES])
def test_facade_lex_error_is_reported_with_byte_offsets(run, workdir, case):
    """CATCHES: a lex error in a vendored façade module (whose source is not a sibling of the
    entry) that crashes the driver or is reported without the module name and the
    `(at start..end)` byte offsets."""
    _check(run, workdir, case)
