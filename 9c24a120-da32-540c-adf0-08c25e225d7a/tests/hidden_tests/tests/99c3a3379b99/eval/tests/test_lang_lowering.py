"""Lowering corner cases: Pyfun programs that reach the less-travelled branches of the lowering pass.

Each case writes one program to `prog.pyfun` and runs `pyfun compile prog.pyfun` (default, `--native`
or `--target 3.11`), `pyfun check prog.pyfun` or `pyfun run prog.pyfun`, comparing the exact
stdout, stderr and exit code with the reference. The programs target specific lowering shapes:
bare references to instance/unit/keyword externs, `Async`-carrying extern slots, stdlib helpers
only emitted for partial application, active-pattern if-chains, CE loop targets and user builders,
lowering errors (a `case` guard that needs statements), native-mode `isinstance` ladders,
beta-reduced partially applied lambdas, and binder renaming.
"""

import json

import pytest

from conftest import golden, write_files

ARGS = {
    "check": ["check", "prog.pyfun"],
    "compile": ["compile", "prog.pyfun"],
    "native": ["compile", "prog.pyfun", "--native"],
    "py311": ["compile", "prog.pyfun", "--target", "3.11"],
    "run": ["run", "prog.pyfun"],
}

RECEIVER_BARE = '''extern type Path
extern pure toPath: string -> Path = pathlib.Path
extern pure suffix: Path -> string = .suffix
let suffixes = List.map suffix [toPath "notes.txt", toPath "data.csv"]
print suffixes
'''

UNIT_ARG_EFFECT = '''extern myMax: int -> unit -> int -> int = builtins.max
let twice x = x * 2
let r = myMax (twice 1) (print "unit argument runs") (twice 3)
print r
'''

ASYNC_SLEEP_BARE = '''extern runAsync: Async a -> a = asyncio.run
let nap = Async.sleep
let main = async {
  do! nap 0.0
  return "woke"
}
print (runAsync main)
'''

MIN_BY = '''let byNeg = List.minBy (fun x -> 0 - x) [3, 1, 2]
let none = List.minBy (fun x -> x) []
let pick = List.minBy
print byNeg
print none
print (pick (fun s -> String.len s) ["ccc", "a", "bb"])
'''

RESULT_ITER = '''let r = Ok 3
Result.iter (fun x -> print x) r
let e = Error "bad"
Result.iter (fun x -> print x) e
let each = Result.iter
each (fun x -> print (x + 1)) (Ok 41)
'''

DECODE_NULLABLE_FAIL = '''let runWith d s = Decode.decodeString d s
let show r =
  match r:
    case Ok v: f"ok {v}"
    case Error e: f"error {e.errorKind}: {e.errorMessage}"
let maybeInt = Decode.nullable Decode.int
let never = Decode.fail "never decodes"
print (show (runWith maybeInt "null"))
print (show (runWith maybeInt "7"))
print (show (runWith never "3"))
print (show (runWith (Decode.oneOf [never, Decode.succeed 1]) "3"))
'''

PARTIAL_PREDICATES = '''let empties = List.filter List.isEmpty [[1], [], [2, 3], []]
let hasOne = List.map (List.contains 1) [[1], [2]]
let byMod = List.distinctBy (fun x -> x % 3) [1, 2, 3, 4, 5, 6, 7]
let inSets = List.map (Set.contains 1) [Set.ofList [1, 2], Set.empty]
let inMaps = List.map (Map.contains 1) [Map.ofList [(1, "a")], Map.empty]
let aWords = List.filter (String.startsWith "a") ["ab", "ba", "aa"]
let endA = List.filter (String.endsWith "a") ["ab", "ba", "aa"]
print empties
print hasOne
print byMod
print inSets
print inMaps
print aWords
print endA
'''

CODEC_BOOL_UNIT = '''type Flags = { on: bool, nothing: unit }
let flags = Flags { on = true, nothing = () }
let wire = Encode.auto flags
print wire
match Decode.decodeString Decode.auto wire:
  case Ok back: print (back.on, back.nothing)
  case Error e: print e.errorMessage
'''

AP_CHAIN_LITERALS = '''let (|Small|_|) n = n < 10
let size n =
  match n:
    case Small: "small"
    case 42: "answer"
    case other: f"big {other}"
let (|Blank|_|) s = String.strip s == ""
let kind s =
  match s:
    case Blank: "blank"
    case "x": "ex"
    case _: "other"
let (|Yes|_|) b = b == true
let flag b =
  match b:
    case Yes: 1
    case true: 2
    case false: 0
print (size 3)
print (size 42)
print (size 99)
print (kind "  ")
print (kind "x")
print (kind "y")
print (flag true)
print (flag false)
'''

AP_PARAM_ARGS = '''let (|Has|_|) sub s = String.contains sub s
let (|Is|_|) b x = x == b
let classify s k =
  match s:
    case Has "a": "has a"
    case Has k: f"has {k}"
    case _: "neither"
let truthy x =
  match x:
    case Is true: "yes"
    case _: "no"
print (classify "cat" "z")
print (classify "dog" "o")
print (classify "xyz" "q")
print (truthy true)
print (truthy false)
'''

COMPOSE_FRESH = '''let _pf_x = 3
let inc n = n + _pf_x
let addThenInc = (fun y -> y + _pf_x) >> inc
print (addThenInc 1)
'''

GUARD_NEEDS_STATEMENTS = '''let describe n =
  match n:
    case k if (match k: case 1: true case _: false): "one"
    case _: "other"
print (describe 1)
'''

TOP_LEVEL_FRAMED = '''let x = 1
let _ =
  let x = 2
  print x
let (a, b) =
  let x = 5
  (x, x + 1)
print (a + b + x)
'''

MODULE_MEMBERS = '''module Shapes =
  let _ = print "loading Shapes"
  let (width, height) = (3, 4)
  let area = fun w h -> w * h
print (Shapes.area Shapes.width Shapes.height)
'''

DUPLICATE_BINDER_RENAME = '''extern runAsync: Async a -> a = asyncio.run
let y = 10
let g u =
  let a = y
  let (y, y) = (1, 2)
  a + y
let f = async {
  let a = y
  let! (y, y) = async { return (1, 2) }
  return a + y
}
print (g 0)
print (runAsync f)
'''

LADDER_NESTED_TUPLES = '''let second o =
  match o:
    case Some (_, b): b
    case None: 0
let total o =
  match o:
    case Some (a, (b, c)): a + b + c
    case None: 0
print (second (Some (1, 2)))
print (total (Some (1, (2, 3))))
print (total None)
'''

BETA_REDUCED = '''extern parseIn: string -> int -> int = int(base = ...)
type P = { x: int }
let p0 = P { x = 1 }
let less = (fun a b -> a < b) 1
let between = (fun a b -> 0 <= a < b) 1
let pick = (fun a b -> if a then b else 0) true
let nand = (fun a b -> not (a and b)) true
let pair = (fun a b -> [a, b]) 1
let tup = (fun a b -> (a, b)) 1
let label = (fun a b -> f"x{a}y{b}") 1
let shadow = (fun a b -> fun a -> a + b) 1
let close = (fun a b -> fun c -> a + b + c) 1
let hex = (fun a b -> parseIn a b) "ff"
let field = (fun a b -> a.x + b) p0
let neg = (fun a b -> -a + b) 1
let has = (fun a b -> String.contains a b) "x"
let size = (fun a b -> String.len a + b) "x"
let addTen = shadow 10
let addThree = close 2
print (less 2, between 5, pick 7, nand false, pair 2, tup 3, label 4)
print (addTen 20, addThree 3, hex 16, field 5, neg 3, has "axe", size 2)
'''

FSTRING_ESCAPES = r'''let x = 1
let s = f"say \"hi\" {x}\t\\ end\r"
print (String.len s)
print (String.replace "\r" "<CR>" (String.replace "\t" "<TAB>" s))
'''

# case id -> (mode, program source)
CASES = {
    # ----- extern references and calls
    "extern_receiver_property_bare_reference": ("compile", RECEIVER_BARE),
    "extern_receiver_property_bare_reference_run": ("run", RECEIVER_BARE),
    "extern_unit_params_bare_references": ("compile", '''extern now: unit -> float = time.time
extern myAbs: unit -> int -> int = builtins.abs
let clock = now
let started = clock ()
let absolute = myAbs
print (absolute () (0 - 5))
'''),
    "extern_kwargs_bare_references": ("compile", '''extern type Path
extern toPath: string -> Path = pathlib.Path
extern writeText: Path -> string -> unit = .write_text(encoding = "utf-8")
extern stamp: unit -> float = time.time(clock = 1)
extern absKw: unit -> int -> int = builtins.abs(flag = 2)
let writer = writeText
let stamper = stamp
let absolute = absKw
'''),
    "extern_property_unit_overapplication": ("compile", '''extern type Counter
extern mkCounter: unit -> Counter = collections.Counter
extern total: Counter -> unit -> int = .total
let n = total (mkCounter ()) ()
'''),
    "extern_kwargs_overapplication": ("compile", '''extern copyOf: a -> a = copy.deepcopy(memo = 1)
let r = copyOf (fun x -> x + 1) 5
'''),
    "extern_unit_argument_effect_sequenced": ("compile", UNIT_ARG_EFFECT),
    "extern_unit_argument_effect_sequenced_run": ("run", UNIT_ARG_EFFECT),
    "extern_unit_result_overapplication": ("compile", '''extern getF: unit -> a = mylib.getf
let s = getF () 5 + 1
'''),
    "async_extern_thunk_slots": ("compile", '''extern toThread: (unit -> a) -> Async a = asyncio.to_thread
extern retry: (unit ->{e} Async a) ->{e} Async a = mylib.retry
let main = async {
  let! v = toThread (fun u -> 6 * 7)
  let! w = retry (fun _ -> async { return 1 })
  return v + w
}
let retrying = retry
'''),
    "async_extern_kwargs_and_property_results": ("compile", '''extern type Job
extern mkJob: unit -> Job = mylib.Job
extern waitFor: Async a -> Async a = asyncio.wait_for(timeout = 1.0)
extern outcome: Job -> Async int = .result
let go j = async {
  let! a = waitFor (async { return 1 })
  let! b = outcome j
  return a + b
}
let main = go (mkJob ())
'''),
    "async_sleep_bare_reference": ("compile", ASYNC_SLEEP_BARE),
    "async_sleep_bare_reference_run": ("run", ASYNC_SLEEP_BARE),
    # ----- stdlib helpers emitted only for partial / first-class use
    "list_min_by_helper": ("compile", MIN_BY),
    "list_min_by_helper_run": ("run", MIN_BY),
    "result_iter_helper": ("compile", RESULT_ITER),
    "result_iter_helper_run": ("run", RESULT_ITER),
    "decode_nullable_and_fail_helpers": ("compile", DECODE_NULLABLE_FAIL),
    "decode_nullable_and_fail_helpers_run": ("run", DECODE_NULLABLE_FAIL),
    "partial_predicate_helpers": ("compile", PARTIAL_PREDICATES),
    "partial_predicate_helpers_run": ("run", PARTIAL_PREDICATES),
    "codec_bool_and_unit_fields": ("compile", CODEC_BOOL_UNIT),
    "codec_bool_and_unit_fields_run": ("run", CODEC_BOOL_UNIT),
    # ----- active patterns
    "active_pattern_chain_literal_and_variable_arms": ("compile", AP_CHAIN_LITERALS),
    "active_pattern_chain_literal_and_variable_arms_run": ("run", AP_CHAIN_LITERALS),
    "active_pattern_option_wildcard_payload": ("compile", '''let (|Positive|_|) n = if n > 0 then Some n else None
let sign n =
  match n:
    case Positive _: "positive"
    case _: "not positive"
'''),
    "active_pattern_parameter_args": ("compile", AP_PARAM_ARGS),
    "active_pattern_parameter_args_run": ("run", AP_PARAM_ARGS),
    # ----- computation expressions
    "seq_without_yield_is_empty_iterator": ("compile", '''let s = seq {
  let x = 1
  print x
}
'''),
    "ce_for_record_pattern_target": ("compile", '''type P = { x: int, y: int }
let pts = [P { x = 1, y = 2 }]
let sums = seq {
  for P { x, y } in pts:
    yield x + y
}
let waits = async {
  for P { x, y } in pts:
    do! Async.sleep 0.0
  return 0
}
'''),
    "user_builder_trailing_do_bang_and_yield_from": ("compile", '''module B =
  let bind m f = List.concat (List.map f m) []
  let return_ x = [x]
  let yield_ x = [x]
  let yieldFrom xs = xs
  let combine a b = List.concat a (b ())
  let delay f = f
let d xs = B {
  let! x = xs
  do! [()]
}
let y = B {
  yield! [1, 2]
  yield 3
}
'''),
    "user_builder_let_bang_last_error": ("check", '''module B =
  let bind m f = f m
  let return_ x = x
let d = B {
  let! x = 1
}
'''),
    "compose_parameter_avoids_user_name": ("compile", COMPOSE_FRESH),
    "compose_parameter_avoids_user_name_run": ("run", COMPOSE_FRESH),
    # ----- lowering errors: a guard whose lowering needs statements
    "guard_needing_statements_check_passes": ("check", GUARD_NEEDS_STATEMENTS),
    "guard_needing_statements_lowering_error": ("compile", GUARD_NEEDS_STATEMENTS),
    "guard_error_in_module_function": ("compile", '''module M =
  let f n =
    match n:
      case k if (match k: case 1: true case _: false): "one"
      case _: "other"
print (M.f 1)
'''),
    "guard_error_in_module_destructuring": ("compile", '''module M =
  let (p, q) =
    match 1:
      case k if (match k: case 1: true case _: false): (1, 2)
      case _: (3, 4)
print M.p
'''),
    "guard_error_in_native_value_match": ("native", '''type T = A | B
let f t =
  let r =
    match t:
      case A: (match 1: case k if (match k: case 1: true case _: false): 1 case _: 2)
      case B: 2
  r + 1
'''),
    "guard_error_in_native_async_return_bang": ("native", '''type T = A | B
let f t = async {
  return! (match t:
    case A if (match t: case A: true case _: false): async { return 1 }
    case _: async { return 2 })
}
'''),
    # ----- native mode
    "native_redefined_function_keeps_plain_def": ("native", '''let f a = a + 1
let x = f 1
let f a b = a + b
let y = f 1 2
'''),
    "native_redundant_guarded_last_arm": ("native", '''type T = A | B
let f t c =
  match t:
    case A: 1
    case B: 2
    case A if c: 3
'''),
    "native_binding_or_pattern_falls_back": ("native", '''type T = A int | B int
let f o =
  match o:
    case Some (A x | B x): x
    case _: 0
'''),
    "native_nested_or_pattern_tests": ("native", '''type T = A int | B int | C
let f o =
  match o:
    case Some (A 1 | B 2): 1
    case Some (C | _): 2
    case _: 0
'''),
    "native_statement_match_discards_temp": ("native", '''type T = A | B | C
let f t x =
  match t:
    case A: print "a"
    case B: ()
    case C: x
  print "done"
'''),
    # ----- bindings, frames and renames
    "top_level_framed_wildcard_and_tuple": ("compile", TOP_LEVEL_FRAMED),
    "top_level_framed_wildcard_and_tuple_run": ("run", TOP_LEVEL_FRAMED),
    "module_lambda_member_and_wildcard": ("compile", MODULE_MEMBERS),
    "module_lambda_member_and_wildcard_run": ("run", MODULE_MEMBERS),
    "duplicate_destructuring_binder_renamed": ("compile", DUPLICATE_BINDER_RENAME),
    "duplicate_destructuring_binder_renamed_run": ("run", DUPLICATE_BINDER_RENAME),
    # ----- match shapes
    "lookup_match_list_head_value_position": ("compile", '''let label k =
  let found =
    match List.head [k]:
      case Some v: v
      case None: 0
  found + 1
let r1 = label 1
'''),
    "lookup_match_record_payload_falls_back": ("compile", '''type P = { x: int, y: int }
let m = Map.ofList [(1, P { x = 1, y = 2 })]
let f k =
  match Map.tryFind k m:
    case Some P { x, y }: x + y
    case None: 0
'''),
    "ladder_nested_tuple_payloads": ("compile", LADDER_NESTED_TUPLES),
    "ladder_nested_tuple_payloads_run": ("run", LADDER_NESTED_TUPLES),
    "eq_predicate_non_equality_shapes": ("compile", '''let a = 1
let b = 2
let anyConst = List.exists (fun y -> a == b) [1, 2]
let isTwo n = n == 2
let anyNamed = List.exists isTwo [1, 2]
let firstAbove = List.find ((<) 1) [1, 2]
print (anyConst, anyNamed, firstAbove)
'''),
    # ----- expressions
    "unit_annotated_literal_function_body": ("compile", '''measure m
let f x = 5.0<m>
'''),
    "beta_reduced_lambda_bodies": ("compile", BETA_REDUCED),
    "beta_reduced_lambda_bodies_run": ("run", BETA_REDUCED),
    "fstring_literal_escapes": ("compile", FSTRING_ESCAPES),
    "fstring_literal_escapes_py311": ("py311", FSTRING_ESCAPES),
    "fstring_literal_escapes_run": ("run", FSTRING_ESCAPES),
    "self_tail_call_async_for_tuple_target": ("compile", '''let loop n = async {
  for (a, b) in [(1, 2)]:
    do! Async.sleep 0.0
  return! (if n == 0 then async { return 0 } else loop (n - 1))
}
'''),
}

# case id -> (argv, {relative path: source}): programs that need more than one file
PROJECT_CASES = {
    "facade_lex_error_reported_with_offsets": (
        ["check", "src/main.pyfun"],
        {
            "pyfun.toml": '[project]\nname = "demo"\n\n[dependencies]\npyfun-shout = "0.1.0"\n',
            ".pyfun/facades/pyfun-shout/shout.pyfun": 'let loud s =\n  String.upper s\nlet bad = "oops\n',
            "src/main.pyfun": 'import Shout\n"hi" |> Shout.loud |> print\n',
        },
    ),
}


def expect_golden(r, case):
    expected = json.loads(golden(__file__, f"{case}.json"))
    assert r.stdout.decode() == expected["stdout"]
    assert r.stderr.decode() == expected["stderr"]
    assert r.returncode == expected["exit"]


@pytest.mark.parametrize("case", sorted(CASES))
def test_lowering_case(run, workdir, case):
    """CATCHES: a lowering pass that mishandles a rarely-taken branch: bare references to receiver,
    unit-parameter or keyword-carrying externs, `Async` thunk/kwarg/property extern slots, helpers
    emitted only for partial application (minBy, Result.iter, Decode.nullable/fail, distinctBy,
    contains/startsWith predicates), active-pattern chains with literal arms, CE loops over record
    targets, user builders ending in `do!`, the `case` guard lowering error, native ladders with
    nested or-patterns or a guarded last arm, binder renames, and beta-reduced lambda bodies."""
    mode, source = CASES[case]
    (workdir / "prog.pyfun").write_text(source, encoding="utf-8")
    expect_golden(run(ARGS[mode]), case)


@pytest.mark.parametrize("case", sorted(PROJECT_CASES))
def test_lowering_project_case(run, workdir, case):
    """CATCHES: a lex error inside a vendored facade module (whose source is not a sibling of the
    entry) crashing, being skipped, or losing its `lex error:` prefix and byte offsets in the
    one-line `in module` fallback report."""
    argv, files = PROJECT_CASES[case]
    write_files(workdir, files)
    expect_golden(run(argv), case)
