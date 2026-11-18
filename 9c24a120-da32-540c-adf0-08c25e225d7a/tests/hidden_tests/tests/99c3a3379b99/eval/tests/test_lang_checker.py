"""Front-end coverage push: lexer, parser, canonical printer and type checker edge cases.

Each case writes a Pyfun program to `prog.pyfun` (plus, for the few multi-module cases, sibling
module files), runs one front-end command over it and compares the exact exit code, stdout and
stderr with a golden captured from the reference under eval/test_resources/test_lang_checker/:

- `check`  : `pyfun check prog.pyfun`   (rustc-style diagnostics, hole notes, error counts)
- `parse`  : `pyfun parse prog.pyfun`   (canonical pretty-print)
- `compile`: `pyfun compile prog.pyfun` (the emitted Python)

The cases target rules the rest of the suite does not reach: f-string / raw-string / escape lexing
errors, CRLF line endings, `def`-hint and extern keyword-argument parse errors, active-pattern shape
and arity rules, callback effect-mismatch guidance, effect-row unification, derived-codec limits,
deferred field resolution, ordering checks on nested datatypes, exhaustiveness witnesses for
records/tuples, and imported schemes with free variables.

The last test drives `pyfun lsp`, whose *recovering* lexer and parser report every broken line of a
document (the CLI stops at the first syntax error); it pins the token names used in "found …"
messages and the layout recovery around `Sep`/`Dedent`.
"""

import json

import pytest

from conftest import golden, lsp_frame, write_files

ARGS = {
    "check": ["check", "prog.pyfun"],
    "parse": ["parse", "prog.pyfun"],
    "compile": ["compile", "prog.pyfun"],
}

# case id -> (mode, program source) or (mode, program source, {sibling module path: source})
CASES = {
    # ------------------------------------------------------------------------------------- lexer
    "lex_underscore_line_continues_statement": ("check", "let f x =\n  let y = 1\n  _\n"),
    "lex_fstring_unterminated": ("check", 'let s = f"abc'),
    "lex_fstring_single_close_brace": ("check", 'let s = f"a } b"\n'),
    "lex_fstring_hole_unterminated": ("check", 'let s = f"a {x'),
    "lex_fstring_hole_nested_braces": (
        "check",
        'type R = { a: int }\nlet r = R { a = 1 }\nlet s = f"v {({ r with a = 2 }).a} end"\n',
    ),
    "lex_fstring_empty_hole": ("check", 'let s = f"a {} b"\n'),
    "lex_fstring_hole_string_unterminated": ("check", 'let s = f"a {"x'),
    "lex_fstring_hole_string_with_escaped_quote": ("check", 'let s = f"a {String.upper "q\\"z"} b"\n'),
    "lex_raw_string_unterminated": ("check", 'let s = r"abc'),
    "lex_unicode_escape_unclosed": ("check", 'let s = "\\u{41"\n'),
    "lex_crlf_and_cr_in_string_become_newlines": ("parse", 'let s = """a\r\nb\rc"""\r\nprint s\r\n'),
    # ---------------------------------------------------------------------- canonical printer
    "print_fstring_literal_escapes": ("parse", 'let s = f"q\\"x\\\\y\\tz {1}"\n'),
    "print_doc_comment_blank_line": ("parse", "## first\n##\n## third\nlet x = 1\n"),
    "print_drops_docs_on_measure_module_import": (
        "parse",
        "## a measure\nmeasure m\n## a module\nmodule M =\n  let a = 1\n## an import\nimport Foo\n",
    ),
    "print_operator_sections_div_and_comparisons": (
        "parse",
        "let a = (/) 1.0 2.0\nlet b = (>) 1 2\nlet c = (<=) 1 2\nlet d = (>=) 1 2\n",
    ),
    "print_indented_variants_without_bars": ("parse", "type Shape =\n  Circle float\n  Square float\n"),
    # ------------------------------------------------------------------------------------ parser
    "parse_untagged_record_literal_migration": ("check", "let r = { a = 1 }\n"),
    "parse_def_hint_stops_at_line_break": ("check", "def area w h\nlet x = 1\n"),
    "parse_def_hint_ignores_expression_use": ("check", "def area w + h = 1\n"),
    "parse_module_body_non_let": ("check", "module M =\n  let a = 1\n  print a\n"),
    "parse_extern_kwarg_duplicate": ("check", "extern p: string -> int = int(base = 16, base = 2)\n"),
    "parse_extern_kwarg_negative_float": ("compile", "extern p: string -> float = m.f(scale = -1.5)\nlet v = p \"x\"\n"),
    "parse_extern_kwarg_minus_non_number": ("check", "extern p: string -> int = int(base = -x)\n"),
    "parse_extern_kwarg_non_literal": ("check", "extern p: string -> int = int(base = x)\n"),
    "parse_record_type_without_fields": ("check", "type R = {}\n"),
    "parse_ap_decl_wildcard_first": ("check", "let (|_|A|) n = n\n"),
    "parse_ap_decl_partial_with_two_cases": ("check", "let (|A|B|_|) n = None\n"),
    "parse_ap_decl_without_parameter": ("check", "let (|A|B|) = A\n"),
    "parse_block_ends_with_let": ("check", "let f x =\n  let y = x\n  let z = y\n"),
    "parse_assign_target_not_variable": ("check", "type R = { a: int }\nlet f r =\n  r.a <- 1\n"),
    "parse_fstring_hole_trailing_tokens": ("check", 'let s = f"{1 2 )}"\n'),
    "parse_record_update_without_fields": ("check", "type R = { a: int }\nlet r = R { a = 1 }\nlet s = { r with }\n"),
    "parse_record_literal_without_fields": ("check", "type R = { a: int }\nlet r = R { }\n"),
    "parse_unit_annotation_empty": ("check", "measure m\nlet x = 5<>\n"),
    "parse_unit_exponent_not_integer": ("check", "measure m\nlet x = 5<m^x>\n"),
    "parse_ce_unterminated": ("check", "let x = option {\n  let! a = Some 1\n"),
    "parse_ce_for_without_in": ("check", "let s = seq {\n  for x of [1]:\n    yield x\n}\n"),
    "parse_ce_for_empty_body": ("check", "let s = seq {\n  for x in [1]:\n}\n"),
    "parse_list_rest_binder_literal": ("check", "let f xs =\n  match xs:\n    case [*1]: 0\n    case _: 1\n"),
    "parse_record_pattern_without_fields": ("check", "type R = { a: int }\nlet f r =\n  match r:\n    case R { }: 0\n"),
    "parse_unit_value_is_not_a_pattern": ("check", "let f u =\n  match u:\n    case (): 1\n"),
    # ------------------------------------------------------------------------- units of measure
    "units_zero_exponent_is_dimensionless": ("check", "measure m\nlet x = 5.0<m^0> + 1.0\nlet bad = x + 1.0<m>\n"),
    "units_literal_unit_vs_plain_int": ("check", "measure m\nlet xs = [5<m>, String.len \"x\"]\n"),
    "units_measure_redefined": ("check", "measure m\nmeasure m\n"),
    # ----------------------------------------------------------------------- type declarations
    "types_uppercase_param_applied_to_argument": ("check", "type Box T = B (T int)\n"),
    "types_builtin_applied_to_wrong_arity": ("check", "type T = A (Option int int)\n"),
    "types_many_type_variables_are_numbered": (
        "check",
        "let f a b c d e g h i j k l m n o p q r s t u v w x y z a2 b2 = 1\nlet bad = f + 1\n",
    ),
    "types_hole_name_contains_member_name": ("check", "let r = String.len (?upperish \"x\")\n"),
    # -------------------------------------------------------------- bindings, groups, modules
    "binding_mutual_recursion_bad_parameter_pattern": (
        "check",
        "type R = { a: int }\nlet f (R { zz }) = g 1\nlet g x = f x\n",
    ),
    "binding_mutual_recursion_pure_violation": ("check", "let pure f x =\n  print x\n  g x\nlet g x = f x\n"),
    "binding_module_member_type_error": ("check", "module M =\n  let x = 1 + true\n  let y = 2\nlet z = M.y\n"),
    # ----------------------------------------------------------------------- extern boundary
    "extern_import_alias_declares_lowercase_segment": (
        "compile",
        "extern import numpy as np\nextern zeros: int -> int = np.linalg.zeros\nlet z = zeros 3\n",
    ),
    "extern_value_binding_stays_a_value": ("compile", "extern pi: float = math.pi\nlet x = pi + 1.0\nprint x\n"),
    # ---------------------------------------------------------------- callback effect guidance
    "effects_callback_mismatch_on_third_arrow": ("check", '''extern serve: (int -> int ->{io} int -> unit) -> unit = srv.serve
let h a =
  fun b ->
    print b
    fun c -> print c
let _ = serve h
'''),
    "effects_callback_mismatch_inside_domain": ("check", '''extern useCb: (int -> unit) -> unit = m.useCb
extern run: ((int ->{io} unit) ->{io} unit) -> unit = m.run
let _ = run useCb
'''),
    "effects_callback_mismatch_curried_call": ("check", '''extern serve2: int -> (int -> unit) -> unit = srv.serve2
let h a = print a
let _ = serve2 1 h
'''),
    "effects_callback_mismatch_module_member": ("check", '''extern serve: (int -> unit) -> unit = srv.serve
module M =
  let go = serve
let h a = print a
let _ = M.go h
'''),
    "effects_callback_mismatch_computed_callee": ("check", '''extern serve: (int -> unit) -> unit = srv.serve
let h a = print a
let _ = (if true then serve else serve) h
'''),
    "effects_row_variable_absorbs_its_own_extension": ("check", '''let pick c f =
  let w x =
    print x
    f x
  if c then w else f
'''),
    "effects_two_rows_widen_to_joined_labels": ("check", '''let pick c f g =
  let w x =
    f x
    g x
  if c then w else print
'''),
    # --------------------------------------------------------------------------- comparison
    "ord_nested_datatype_too_deep": ("check", "type T a = L a | N (T (List a))\nlet b = L 1 < L 2\n"),
    "ord_set_is_not_comparable": ("check", "let b = Set.ofList [1] < Set.ofList [2]\n"),
    # ------------------------------------------------------------------------ active patterns
    "ap_scan_every_expression_form": ("check", '''measure m
type R = { a: int }
let (|Big|Small|) n =
  let s = f"n={n}"
  let g = fun x -> x + 1
  let t = try g n
  let k =
    match n:
      case 0 if n > 1: 1
      case _: 2
  let u = not (n > 3)
  let c = 1 < n < 10
  let o =
    option {
      let w = 1
      let! v = Some n
      return! Some (v + w)
    }
  let q =
    seq {
      for i in [1, 2]:
        yield i
      yield! seq { yield 3 }
    }
  let nap =
    async {
      do! Async.sleep 0.01
      return 1
    }
  let d = 5<m>
  let xs = [1, 2]
  let tp = (1, 2)
  let r = R { a = n }
  let r2 = { r with a = 2 }
  let fa = r2.a
  let mut z = 0
  z <- 1
  let p = n |> g
  if n > 100 then Big else Small
let f n =
  match n:
    case Big: "big"
    case Small: "small"
'''),
    "ap_total_body_wrong_type": ("check", "let (|A|B|) n =\n  let a = A\n  let b = B\n  n + 1\n"),
    "ap_total_case_given_a_binder": ("check", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let f n =
  match n:
    case Even x: 1
    case Odd: 2
'''),
    "ap_two_total_patterns_in_one_column": ("check", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let (|Neg|Pos|) n = if n < 0 then Neg else Pos
let f n =
  match n:
    case Even: 1
    case Neg: 2
'''),
    "ap_parameter_argument_not_literal": ("check", '''let (|DivBy|_|) d n = n % d == 0
let f n =
  match n:
    case DivBy [3]: 1
    case _: 2
'''),
    "ap_parameter_arguments_bool_and_variable": ("compile", '''let (|When|_|) flag n = if flag then Some n else None
let (|DivBy|_|) d n = n % d == 0
let f k n =
  match n:
    case When true m: m
    case DivBy k: 1
    case _: 2
'''),
    "ap_case_binder_is_literal": ("check", '''let (|Positive|_|) n = if n > 0 then Some n else None
let f n =
  match n:
    case Positive 5: 1
    case _: 2
'''),
    "ap_nested_inside_ap_arguments": ("check", '''let (|Positive|_|) n = if n > 0 then Some n else None
let (|Wrap|_|) n = Some n
let f n =
  match n:
    case Wrap (Positive x): x
    case _: 2
'''),
    "ap_or_pattern_with_plain_constructor": ("check", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let f n =
  match n:
    case Even | None: 1
    case _: 2
'''),
    # ------------------------------------------------------------------------ records/fields
    "fields_deferred_access_pinned_to_list": ("check", '''type A = { x: int }
type B = { x: int }
let f r =
  let v = r.x
  List.len r
'''),
    "fields_deferred_access_pinned_to_other_record": ("check", '''type A = { x: int }
type B = { x: int }
type C = { y: int }
let f r =
  let v = r.x
  r.y
'''),
    "records_literal_sets_field_twice": ("check", "type R = { a: int }\nlet r = R { a = 1, a = 2 }\n"),
    "records_update_through_non_record_field": (
        "check",
        "type R = { tag: Option int }\nlet r = R { tag = None }\nlet s = { r with tag.x = 3 }\n",
    ),
    # ---------------------------------------------------------------- patterns/exhaustiveness
    "patterns_constructor_arity": ("check", "let f o =\n  match o:\n    case Some x y: 1\n    case None: 0\n"),
    "patterns_or_binds_only_in_first": ("check", "let f o =\n  match o:\n    case Some x | None: 1\n"),
    "patterns_or_binds_only_in_second": ("check", "let f o =\n  match o:\n    case None | Some x: 1\n"),
    "exhaustive_record_with_only_guarded_arm": (
        "check",
        "type P = { a: int }\nlet f p =\n  match p:\n    case q if q.a > 0: 1\n",
    ),
    "exhaustive_tuple_with_only_guarded_arm": ("check", "let f t =\n  match t:\n    case (a, b) if a > b: 1\n"),
    # ---------------------------------------------------------- computation exprs and codecs
    "seq_yield_bang_of_a_list": ("check", "let s = seq { yield! [1, 2] }\n"),
    "codec_decode_module_cannot_be_redefined": ("check", "module Decode =\n  let auto = 5\nlet z = Decode.auto + 1\n"),
    "codec_decode_auto_bool": (
        "check",
        "let a =\n  match Decode.decodeString Decode.auto \"true\":\n    case Ok b: if b then 1 else 0\n"
        "    case Error _: 2\n",
    ),
    "codec_decode_auto_unit": (
        "check",
        "let u =\n  match Decode.decodeString Decode.auto \"null\":\n    case Ok v: v == ()\n    case Error _: false\n",
    ),
    "codec_decode_auto_lazy_seq": (
        "check",
        "let r =\n  match Decode.decodeString Decode.auto \"[]\":\n    case Ok s: Seq.len s\n    case Error _: 0\n",
    ),
    "codec_decode_auto_async": (
        "check",
        "extern runAsync: Async a -> a = asyncio.run\nlet r =\n  match Decode.decodeString Decode.auto \"1\":\n"
        "    case Ok s: runAsync s + 1\n    case Error _: 0\n",
    ),
    "codec_record_used_twice_is_shared": (
        "compile",
        "type P = { a: int }\ntype Q = { x: P, y: P }\nlet r =\n  match Decode.decodeString Decode.auto \"{}\":\n"
        "    case Ok q: q.x.a + q.y.a\n    case Error _: 0\n",
    ),
    # ------------------------------------------------------------------------ multi-module
    "project_imported_mutables_with_free_variables": (
        "check",
        "import Geometry\nlet a = Geometry.n\nlet b = Geometry.h\nlet bad = Geometry.g + 1\n",
        {"geometry.pyfun": "let mut n = 5\nlet mut g = List.map\nlet mut h = sqrt\n"},
    ),
    "project_carried_record_has_no_codec_here": (
        "check",
        '''import Shapes
let p = Shapes.start
let q =
  match Decode.decodeString Decode.auto "{}":
    case Ok v: v == p
    case Error _: false
''',
        {
            "geometry.pyfun": "type Point = { x: int, y: int }\nlet origin = Point { x = 0, y = 0 }\n",
            "shapes.pyfun": "import Geometry\nlet start = Geometry.origin\n",
        },
    ),
    "project_partial_active_pattern_in_dependency": (
        "check",
        "import Parity\nlet f n = Parity.parity n\nlet bad = Parity.parity \"x\"\n",
        {"parity.pyfun": "let (|Pos|_|) n = if n > 0 then Some n else None\nlet parity n =\n  match n:\n"
                         "    case Pos p: p\n    case _: 0\n"},
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_front_end_case(run, workdir, case):
    """CATCHES: a lexer, parser, printer or checker that accepts a malformed or ill-typed program (or
    rejects a valid one), words a diagnostic differently, points its caret at another span, misses an
    active-pattern/effect/unit/codec/exhaustiveness rule, mis-renders a type, prints a different
    canonical form or emitted Python, or exits with the wrong status."""
    mode, source, *extra = CASES[case]
    write_files(workdir, {"prog.pyfun": source, **(extra[0] if extra else {})})
    r = run(ARGS[mode])
    expected = json.loads(golden(__file__, f"{case}.json"))
    assert r.stdout.decode() == expected["stdout"]
    assert r.stderr.decode() == expected["stderr"]
    assert r.returncode == expected["exit"]


# One `extern` per token kind the recovering parser must name in "expected a type, found …"; a
# `{`/`[` is closed on the same line so the bracket depth (and so the next line's layout) is reset.
LSP_TOKENS = ["let", "mut", "pure", "if", "then", "else", "match", "fun", "type", "return", "yield", "do",
              "measure", "extern", "module", "import", "not", "and", "or", "!", "^", "<", ">", "{ }", "}",
              "[ ]", "]", "true", "false", "==", "!=", "<=", ">=", ">>", "<-", "+", "-", "*", "/", "//",
              "<|", "|", "->", ",", "case", "%", "1.5", '"s"']

# document id -> text opened in the language server
LSP_DOCS = {
    # Every line is its own syntax error; recovery must resume at the next line each time, skip a
    # broken item's indented block, and step over a line it cannot start (`case 1`).
    "lsp_token_names_in_recovered_errors": "\n".join(f"extern f{i}: {t} = m.f" for i, t in enumerate(LSP_TOKENS))
    + "\nextern g:\n  int = m.g\nlet =\n  1\n  2\ncase 1\nlet ok = 1\n",
    # A line holding only a lex error (`0x`) still separates statements, so the block, module body,
    # variant list and match arms each see a separator straight before their dedent; the file then
    # ends in a dangling doc comment.
    "lsp_layout_recovery_after_lex_errors": '''module M =
  let a = 1
  0x
let f x =
  let y = x
  y
  0x
type S =
  | A
  | B
  0x
let g n =
  match n:
    case 1: 2
    case _: 3
    0x
let c = 3
## trailing doc
''',
}


@pytest.mark.parametrize("case", sorted(LSP_DOCS))
def test_lsp_recovering_front_end(run, case):
    """CATCHES: a language server whose recovering lexer/parser stops at the first broken line, loops or
    drops later diagnostics, names a token differently in a "found …" message (keywords, operators,
    brackets, literals, an indented block), reports wrong ranges, or mishandles a statement separator
    that arrives right before a dedent (module body, block, variants, match arms) or a trailing doc."""
    text = LSP_DOCS[case]
    stdin = (lsp_frame({"jsonrpc": "2.0", "method": "textDocument/didOpen",
                        "params": {"textDocument": {"uri": "untitled:" + case, "languageId": "pyfun",
                                                    "version": 1, "text": text}}})
             + lsp_frame({"jsonrpc": "2.0", "id": 99, "method": "shutdown"})
             + lsp_frame({"jsonrpc": "2.0", "method": "exit"}))
    r = run(["lsp"], input=stdin)
    expected = json.loads(golden(__file__, f"{case}.json"))
    assert r.stdout.decode() == expected["stdout"]
    assert r.stderr.decode() == expected["stderr"]
    assert r.returncode == expected["exit"]
