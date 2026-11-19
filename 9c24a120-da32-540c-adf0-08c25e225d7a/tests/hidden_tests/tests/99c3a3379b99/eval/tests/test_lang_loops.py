"""Loop-shaped lowerings: self tail calls as `while True:` (DESIGN §5.4), folds as in-place `for` loops
(§5.1) and statically-known `Decode` decoders specialised to direct dict access (§5.3).

Each case writes one program to `prog.pyfun` and runs `pyfun compile` (or `pyfun run`), comparing the
exact emitted Python, the `note:` lines explaining a kept recursive form, and the exit code with the
reference. The programs sit right on a precondition of one of the passes: some must be rewritten, some
must fall back to the plain lowering byte for byte, so a pass that is too eager or too timid shows up as
a different output.
"""

import json

import pytest

from conftest import golden

ARGS = {
    "check": ["check", "prog.pyfun"],
    "compile": ["compile", "prog.pyfun"],
    "native": ["compile", "prog.pyfun", "--native"],
    "py311": ["compile", "prog.pyfun", "--target", "3.11"],
    "run": ["run", "prog.pyfun"],
}

# case id -> (mode, program source)
CASES = {
    # ---------------------------------------------------------------- self tail calls (§5.4)
    "tailcall_rebinds_own_name_lambda": ("compile", '''let go n acc =
  let go = fun a b -> a + b
  if n == 0 then acc else go (n - 1) (acc + 1)
'''),
    "tailcall_rebinds_own_name_local_def": ("compile", '''let go n acc =
  let go a b = a * b
  if n == 0 then acc else go n acc
'''),
    "tailcall_destructure_and_fold_in_body": ("compile", '''let walk n acc =
  let (a, b) = (n, acc)
  let m = List.fold (fun s x -> Map.add x x s) Map.empty [1, 2]
  if a == 0 then b else walk (a - 1) (b + Map.len m)
print (walk 3 0)
'''),
    "tailcall_decode_try_in_body": ("compile", '''let walk n acc =
  let r = Decode.decodeString Decode.int "5"
  match r:
    case Ok v: if n == 0 then acc + v else walk (n - 1) acc
    case Error e: acc
'''),
    "tailcall_list_record_as_guard_patterns": ("compile", '''type P = { x: int, y: int }
type Shape = Dot P | Line P P
let walk xs n =
  match xs:
    case []: n
    case [Dot (P { x, y }) as d, *rest]: walk rest (n + x + y)
    case [Line a b, *rest] if a.x > 0: walk rest (n + 1)
    case [_, *rest]: walk rest n
'''),
    "tailcall_tuple_or_patterns": ("compile", '''let walk n acc =
  match (n, acc):
    case (0, a): a
    case (1, a) | (2, a): walk (n - 1) (a + 10)
    case (k, a): walk (k - 1) (a + 1)
'''),
    "tailcall_inline_python_exprs": ("compile", '''extern parseIn: string -> int -> int = int(base = ...)
let walk n acc =
  let hit = List.contains n [1, 2, 3]
  let v = parseIn "ff" 16
  let s = f"n={n}"
  let k = (if hit then 1 else 2) + v
  if n == 0 then acc else walk (n - 1) (acc + k + String.len s)
'''),
    "tailcall_statement_and_deep_loop_run": ("run", '''let countdown n =
  print n
  if n == 0 then "liftoff" else countdown (n - 1)
let total n acc = if n == 0 then acc else total (n - 1) (acc + n)
print (countdown 3)
print (total 50000 0)
'''),
    "tailcall_async_rebinds_own_name": ("compile", '''let loop n = async {
  let loop = fun m -> async { return m }
  return! loop (n - 1)
}
'''),
    "tailcall_async_prefix_reads_coroutine_name": ("compile", '''let finished acc = async { return acc }
let loop n =
  let _pf_fn1 = 3
  let y = _pf_fn1 + 1
  async {
    return! (if n == 0 then finished y else loop (n - 1))
  }
'''),
    "tailcall_decode_auto_result_descriptor": ("compile", r'''let walk n acc =
  let r = Decode.decodeString Decode.auto "{\"type\": \"Ok\", \"fields\": [1]}"
  match r:
    case Ok (Ok v): if n == 0 then acc + v else walk (n - 1) acc
    case Ok (Error s): String.len s
    case Error e: acc
'''),
    "tailcall_closure_assigns_local_mut_kept": ("compile", '''let walk n acc =
  let mut total = 0
  let bump k = total <- total + k
  bump n
  if n == 0 then acc + total else walk (n - 1) (acc + 1)
'''),
    "tailcall_closure_assigns_global_mut_run": ("run", '''let mut counter = 0
let walk n =
  let bump k = counter <- counter + k
  bump n
  if n == 0 then counter else walk (n - 1)
print (walk 3000)
'''),
    "tailcall_nested_def_pattern_binders": ("compile", '''type P = { x: int, y: int }
type Shape = Dot P | Line P P | Empty
let walk n acc =
  let x = n * 2
  let first = 1
  let d = 3
  let score sh =
    match sh:
      case Dot (P { x, y }) as d if x > 1: x + y
      case Line (P { x = first, y = _ }) q: first
      case Empty: 0
      case _: 1
  let head xs =
    match xs:
      case [first, *rest]: first
      case []: 0
  let pick p =
    match p:
      case (1, x) | (x, 1): x
      case _: 0
  if n == 0 then acc + x + first + d else walk (n - 1) (acc + score (Dot (P { x = n, y = 1 })) + head [n] + pick (n, 1))
print (walk 3000 0)
'''),
    "tailcall_nested_def_statement_binders": ("compile", '''let walk n acc =
  let e = 0
  let y = 1
  let s = 2
  let helper v =
    print v
    let r = Decode.decodeString Decode.int "1"
    let w = match r:
      case Ok k: k
      case Error why: 0
    let m = List.fold (fun mm kk -> Map.add kk kk mm) Map.empty [v, w]
    let ys = List.map (fun y -> y + v) [1, 2]
    let gen = seq {
      yield v
      yield! Seq.ofList ys
    }
    let inner z = z * 2
    let count k t = if k == 0 then t else count (k - 1) (t + 1)
    Map.len m + inner (count 3 0) + List.len (Seq.toList gen)
  if n == 0 then acc + e + y + s else walk (n - 1) (helper acc)
'''),
    # ---------------------------------------------------------------- in-place folds (§5.1)
    "fold_toplevel_folder_returns_lambda": ("compile", '''let step acc = fun x -> Map.add x 1 acc
let out = List.fold step Map.empty [1, 2]
'''),
    "fold_tuple_accumulator_named_init": ("compile", '''let start = ([], 0)
let out = List.fold (fun acc x -> match acc: case (xs, n): (List.concat xs [x], n + 1)) start [1, 2]
'''),
    "fold_folder_rebinds_accumulator": ("compile", '''let build xs =
  let step acc x =
    let acc = Map.add x 1 acc
    acc
  List.fold step Map.empty xs
'''),
    "fold_named_init_shares_element_name": ("compile", '''let seed = Map.add 0 0 Map.empty
let build xs = List.fold (fun acc seed -> Map.add seed 1 acc) seed xs
'''),
    "fold_active_pattern_match_kept": ("compile", '''let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd
let build xs = List.fold (fun acc x -> match x: case Even: Set.add x acc case Odd: acc) Set.empty xs
'''),
    "fold_record_pattern_element": ("compile", '''type P = { x: int, y: int }
let build ps = List.fold (fun acc (P { x, y }) -> Map.add x y acc) Map.empty ps
'''),
    "fold_match_on_computed_scrutinee": ("compile", '''let build xs = List.fold (fun acc x -> match x % 2: case 0: Set.add x acc case _: acc) Set.empty xs
'''),
    "fold_single_arm_capture_kept": ("compile", '''let build xs = List.fold (fun acc x -> match acc: case m: Map.add x 1 m) Map.empty xs
'''),
    "fold_tuple_leaf_call_kept": ("compile", '''let swap a b = (b, a)
let build xs = List.fold (fun acc x -> match acc: case (a, b): swap a b) ([], []) xs
'''),
    "fold_unlisted_op_kept": ("compile", '''let build xs = List.fold (fun acc x -> List.rev acc) [] xs
'''),
    "fold_local_folder_value_positions": ("compile", '''measure m
type P = { x: int, y: int }
let base = P { x = 0, y = 0 }
let lookup = Map.add 1 10 Map.empty
let noop v = ()
let build xs =
  let step acc x =
    noop x
    let mut t = x
    t <- t + 1
    let blk =
      let z = x * 2
      z + 1
    let p = { base with x = t }
    let q = P { x = -x, y = x }
    let len = 2.0<m> * 3.0
    let w = match x:
      case 0: 1
      case k if k > 5: 3
      case _: 2
    let ok = not (x > 3) and 0 < x < 10
    let r = try (x + 1)
    let mm = Map.findOr 0 x lookup
    Map.add (if ok then x else blk) (p.x + q.y + w + mm + Map.len acc) acc
  List.fold step Map.empty xs
print (Map.toList (build [1, 2, 7]))
'''),
    "fold_local_folder_closure_positions": ("compile", '''measure m
type P = { x: int, y: int }
let base = P { x = 0, y = 0 }
let build xs =
  let step acc x =
    let render k =
      let mut t = k
      t <- t + 1
      let p = { base with x = t }
      let q = P { x = -t, y = t }
      let len = 2.0<m> * 3.0
      let o = option {
        let! a = Some t
        return! Some (a + p.x + q.y)
      }
      let label = match k:
        case 0: "zero"
        case n if n > 0: f"pos {n}"
        case _: "neg"
      let r = try (k // 1)
      if 0 < k < 10 and not (k == 5) then label else (label |> String.upper)
    List.concat acc [render x]
  List.fold step [] xs
print (build [0, 3, 12])
'''),
    "fold_toplevel_folder_free_names": ("compile", '''measure m
type P = { x: int, y: int }
let base = P { x = 0, y = 0 }
let step acc x =
  let mut t = x
  t <- t + 1
  let p = { base with x = t }
  let o = option {
    let! a = Some t
    do! Some ()
    return! Some a
  }
  let o2 = option {
    let! b = o
    return b + 1
  }
  let s = seq {
    for k in [1, 2]:
      yield k + x
  }
  let w = match x:
    case 0: 1
    case k if k > 5: 3
    case _: 2
  let len = -(2.0<m>)
  let r = try (x // 1)
  let label = f"{x}"
  let c = 0 < x < 10
  let g = (fun z -> z + 1) >> (fun z -> z * 2)
  Map.add x (p.x + w + (x |> g)) acc
let build xs = List.fold step Map.empty xs
print (Map.toList (build [1, 2, 7]))
'''),
    "fold_eq_predicate_assignment_operand": ("compile", '''let scan xs =
  let mut seen = 0
  let found = List.exists (fun y -> (seen <- seen + 1) == y) xs
  (found, seen)
print (scan [(), ()])
'''),
    # ---------------------------------------------------------------- decoder specialisation (§5.3)
    "decode_inside_in_file_module": ("compile", '''module Cfg =
  let parse s = Decode.decodeString Decode.int s
let r = Cfg.parse "3"
'''),
    "decode_oneof_named_list": ("compile", r'''let alts = [Decode.int, Decode.map (fun s -> String.len s) Decode.string]
let r = Decode.decodeString (Decode.oneOf alts) "\"abc\""
'''),
    "decode_field_name_from_record": ("compile", r'''type Cfg = { key: string, fallback: int }
let cfg = Cfg { key = "n", fallback = 0 }
let r = Decode.decodeString (Decode.field cfg.key (Decode.oneOf [Decode.int, Decode.succeed cfg.fallback])) "{\"n\": 4}"
print r
'''),
}


def _check(run, workdir, case):
    mode, source = CASES[case]
    (workdir / "prog.pyfun").write_text(source, encoding="utf-8")
    r = run(ARGS[mode])
    expected = json.loads(golden(__file__, f"{case}.json"))
    assert r.stdout.decode() == expected["stdout"]
    assert r.stderr.decode() == expected["stderr"]
    assert r.returncode == expected["exit"]


@pytest.mark.parametrize("case", sorted(c for c in CASES if c.startswith("tailcall_")))
def test_self_tail_call(run, workdir, case):
    """CATCHES: a self-tail-call pass that loops where it must keep the recursive def (a body rebinding the
    function's own name, sync or inside the async coroutine, a closure assigning a frame `let mut` through
    `nonlocal`, a statement before the `async def` reading the coroutine's name) or keeps recursing where it
    must loop (a nested def whose own pattern, `except`, lambda, loop or generator binders merely share a
    frame name, a `global` assignment, a `try`/`for`/`match` elsewhere in the body), emits a different or
    missing `note:`, or loses the deep-recursion safety at run time."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", sorted(c for c in CASES if c.startswith("fold_")))
def test_fold_loop(run, workdir, case):
    """CATCHES: an in-place fold pass that inlines a folder it must refuse (a one-parameter top-level folder,
    a named tuple init, a binder shadowing the accumulator, a named init spelled like the element, an
    active-pattern match, a non-tuple or call leaf, an unlisted op, duplicate tuple binders) or refuses one
    it should inline (record element patterns, a computed `match` scrutinee, reads, closures, CEs, records,
    `try`, units and `<-` in value positions), or emits the loop body, temps or unpack differently."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", sorted(c for c in CASES if c.startswith("decode_")))
def test_decode_spec(run, workdir, case):
    """CATCHES: a decoder specialiser that inlines a decode inside an in-file module or a `Decode.oneOf` over
    a named list (both must stay on the interpreter helpers), or that hoists an attribute-read config
    (`cfg.key`) into a temp instead of using it in place."""
    _check(run, workdir, case)
