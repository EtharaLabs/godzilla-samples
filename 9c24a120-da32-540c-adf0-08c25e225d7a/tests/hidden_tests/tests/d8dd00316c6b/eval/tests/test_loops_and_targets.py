"""Loop-shaped lowerings and the Python 3.11 target.

* Self tail calls become `while True:` loops (DESIGN.md §5.4), unless a precondition
  fails — a closure capturing a frame name, a body that rebinds the function's own
  name — in which case the function keeps its recursive form and `compile`/`run`
  print a `note:` saying why. Programs here put every statement and expression kind
  in the looping frame and in the nested functions it defines.
* A qualifying `List.fold`/`Seq.fold` becomes an in-place `for` loop over a mutable
  accumulator (DESIGN.md §5.1); anything that does not provably qualify falls back to
  the `_pf_fold` helper.
* `--target 3.11` rewrites every f-string whose holes need PEP 701 into
  `"template".format(...)`, everywhere in the module.

Expected transcripts were captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

TAIL_CALL_CASES = [
    {
        'id': 'tail_nested_def_rich__compile',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'type Sh = Circle int | Sq int\n'
                'let go n acc =\n'
                '  let helper x =\n'
                '    let (a, b) = (x, x + 1)\n'
                '    let p = P { x = a, y = b }\n'
                '    let q = { p with y = 9 }\n'
                '    let m = Map.ofList [(a, b)]\n'
                '    let xs = [a, b, a * b]\n'
                '    let sl = List.take 2 xs\n'
                '    let s = f"v={a} {b}"\n'
                '    let neg = -a\n'
                '    let c = if a < b < 10 then 1 else 0\n'
                '    let f = fun z -> z + a\n'
                '    let t = List.fold (fun acc2 e -> acc2 + e) 0 xs\n'
                '    let r = match Circle a:\n'
                '      case Circle k if k > 3: k\n'
                '      case Circle k: k + 1\n'
                '      case Sq k: k\n'
                '    let r2 = match xs:\n'
                '      case [h, *rest]: h\n'
                '      case []: 0\n'
                '    let r3 = match p:\n'
                '      case P { x, y }: x + y\n'
                '    let r4 = match (a, b):\n'
                '      case (1, _) | (2, _): 1\n'
                '      case (u, v) as w: u\n'
                '    let bl = not (a == b) and neg < 0 or c == 1\n'
                '    t + r + r2 + r3 + r4 + f 1 + q.y + String.len s + Map.len m + List.len sl\n'
                '  if n == 0 then acc else go (n - 1) (acc + helper n)\n'
                'print (go 10 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_outer_frame_statements__compile',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                'let go n acc =\n'
                '  let (a, b) = (n, acc)\n'
                '  print f"step {a}"\n'
                '  let tbl = List.fold (fun t x -> Map.add x a t) Map.empty [1, 2, 3]\n'
                '  let r = try (parseInt (String.fromInt a))\n'
                '  let v = Result.withDefault 0 r\n'
                '  if a == 0 then b + Map.len tbl else go (a - 1) (b + v)\n'
                'print (go 3 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_nested_def_statements__compile',
        "files": {
            'main.pyfun': (
                'let go n acc =\n'
                '  let helper x =\n'
                '    let inner y = y * 2\n'
                '    print "in helper"\n'
                '    let tbl = List.fold (fun t k -> Map.add k x t) Map.empty [x, x + 1]\n'
                '    let tot = Map.len tbl\n'
                '    let ys = seq {\n'
                '      yield x\n'
                '      yield inner x\n'
                '      yield! (Seq.ofList [tot])\n'
                '    }\n'
                '    let countdown k s = if k == 0 then s else countdown (k - 1) (s + k)\n'
                '    let w = try (x / 2)\n'
                '    if tot > 1 then countdown x (inner tot) + Seq.sum ys else 0\n'
                '  if n == 0 then acc else go (n - 1) (acc + helper n)\n'
                'print (go 4 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_nested_def_captures_mut__compile',
        "files": {
            'main.pyfun': (
                'let go n acc =\n'
                '  let mut seen = 0\n'
                '  let bump k =\n'
                '    seen <- seen + k\n'
                '    seen\n'
                '  let total = bump n\n'
                '  if n == 0 then acc + total else go (n - 1) (acc + total)\n'
                'print (go 3 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_kwarg_extern_in_nested__compile',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                'extern parseHex: string -> int = int(base = 16)\n'
                'let go n acc =\n'
                '  let conv s = parseIn s 16 + parseHex s\n'
                '  let partial = parseIn "ff"\n'
                '  if n == 0 then acc else go (n - 1) (acc + conv "a" + partial 16)\n'
                'print (go 2 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_rebinds_own_name__compile',
        "files": {
            'main.pyfun': (
                'let go n =\n'
                '  let go2 = n\n'
                '  let go k = k + 1\n'
                '  if n == 0 then 0 else go (n - 1)\n'
                'print (go 5)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'async_tail_with_task_scope__compile',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let worker name = async {\n'
                '  do! Async.sleep 0.0\n'
                '  print f"worker {name}"\n'
                '}\n'
                'let finished acc = async { return acc }\n'
                'let tick n acc =\n'
                '  async {\n'
                '    let (a, b) = (n, acc)\n'
                '    do! Task.scope (async {\n'
                '      Task.start (worker "w")\n'
                '    })\n'
                '    let tbl = List.fold (fun t k -> Map.add k a t) Map.empty [1, 2]\n'
                '    return! (if a == 0 then finished (b + Map.len tbl) else tick (a - 1) (b + a))\n'
                '  }\n'
                'print (runAsync (tick 2 0))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_outer_frame_patterns__compile',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'type Sh = Circle int | Sq int\n'
                'let go n acc =\n'
                '  let pairs = List.fold (fun t (k, v) -> Map.add k v t) Map.empty [(n, acc), (0, 1)]\n'
                '  let a =\n'
                '    match Pt { x = n, y = acc }:\n'
                '      case Pt { x, y } if x > y: x\n'
                '      case Pt { x, y }: y\n'
                '  let b =\n'
                '    match (n, acc):\n'
                '      case (0, _) | (_, 0): 1\n'
                '      case (p, q) as both: p\n'
                '  let c =\n'
                '    match [n, acc]:\n'
                '      case [h, *rest]: h\n'
                '      case _: 0\n'
                '  let d =\n'
                '    match Sq n:\n'
                '      case Circle r as whole: r\n'
                '      case Sq s: s\n'
                '  if n <= 0 then acc + Map.len pairs else go (n - 1) (acc + a + b + c + d)\n'
                'print (go 4 1)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'async_tail_rebinds_own_name__compile',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let finished acc = async { return acc }\n'
                'let tick n =\n'
                '  async {\n'
                '    let tick = fun k -> finished (k * 10)\n'
                '    return! (if n == 0 then finished 0 else tick (n - 1))\n'
                '  }\n'
                'print (runAsync (tick 3))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

FOLD_LOOP_CASES = [
    {
        'id': 'fold_value_position_sweep__compile',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let summarize xs =\n'
                '  let mut seen = 0\n'
                '  let step acc x =\n'
                '    seen <- seen + 1\n'
                '    let width = 2<1>\n'
                '    let c = if x > 2 then 1 else 0\n'
                '    let t = Result.withDefault 0 (try (x // 1))\n'
                '    let label =\n'
                '      match x:\n'
                '        case 0: "zero"\n'
                '        case n if n > 5: "big"\n'
                '        case _: "other"\n'
                '    let neg = -x\n'
                '    let inRange = 0 < x < 10\n'
                '    let blk =\n'
                '      let inner = x * 2\n'
                '      inner + 1\n'
                '    let p = Pt { x = x, y = blk }\n'
                '    let q = { p with y = neg }\n'
                '    let s = f"{x}-{label}-{inRange}"\n'
                '    let size = Map.len acc\n'
                '    print s\n'
                '    Map.add x (q.y + c + t + size + p.x + width) acc\n'
                '  let out = List.fold step Map.empty xs\n'
                '  (out, seen)\n'
                'print (summarize [1, 3, 7])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_closure_rule_sweep__compile',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let origin = Pt { x = 0, y = 0 }\n'
                'let tally xs =\n'
                '  let mut calls = 0\n'
                '  let step acc x =\n'
                '    let helper k =\n'
                '      calls <- calls + 1\n'
                '      let a = if k > 0 then k else 0\n'
                '      let b = Result.withDefault 0 (try (k // 1))\n'
                '      let c =\n'
                '        match k:\n'
                '          case 1: 1\n'
                '          case z if z > 2: z\n'
                '          case _: 0\n'
                '      let d = k |> (fun v -> v + 1)\n'
                '      let e = ((fun v -> v + 1) >> (fun v -> v * 2)) k\n'
                '      let g = -k\n'
                '      let h = if 1 < k < 9 then 1 else 0\n'
                '      let r = { origin with x = k }\n'
                '      let s = f"{k}"\n'
                '      let o = Option.withDefault 0 (option {\n'
                '        let! v = Some k\n'
                '        do! Some ()\n'
                '        return! Some (v + 1)\n'
                '      })\n'
                '      let rec0 = Pt { x = k, y = r.x }\n'
                '      let blk =\n'
                '        let w = k\n'
                '        w\n'
                '      a + b + c + d + e + g + h + o + rec0.y + blk + String.len s\n'
                '    Set.add (helper x) acc\n'
                '  let out = List.fold step Set.empty xs\n'
                '  (Set.toList out |> List.sort, calls)\n'
                'print (tally [1, 2, 3])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_top_level_named_folder_free_vars__compile',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let base = Pt { x = 1, y = 2 }\n'
                'let mut hits = 0\n'
                'let step acc x =\n'
                '  hits <- hits + 1\n'
                '  let a = x |> (fun v -> v + base.x)\n'
                '  let b = ((fun v -> v) >> (fun v -> v + 1)) x\n'
                '  let c = -x\n'
                '  let d = Result.withDefault 0 (try (x // 1))\n'
                '  let e = if 0 < x < 100 then 1 else 0\n'
                '  let f = { base with y = x }\n'
                '  let g = f"{x}"\n'
                '  let h =\n'
                '    match x:\n'
                '      case k if k > base.y: k\n'
                '      case _: 0\n'
                '  let i = Seq.sum (seq {\n'
                '    let w = x\n'
                '    yield w\n'
                '    yield! (Seq.ofList [w + 1])\n'
                '    for z in [1, 2]:\n'
                '      yield z\n'
                '  })\n'
                '  let j = Option.withDefault 0 (option {\n'
                '    let! v = Some x\n'
                '    do! Some ()\n'
                '    return! Some v\n'
                '  })\n'
                '  let k = Result.withDefault 0 (result {\n'
                '    let! v = Ok x\n'
                '    return v\n'
                '  })\n'
                '  Map.add x (a + b + c + d + e + f.y + String.len g + h + i + j + k) acc\n'
                'let built = List.fold step Map.empty [1, 5]\n'
                'print built\n'
                'print hits\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_rejections__compile',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let m0 = Map.ofList [(1, 1)]\n'
                'let start = (Map.empty, 0)\n'
                'let r2 = List.fold (fun acc x -> match acc: case (m, n): (Map.add x 1 m, n + 1)) start [1, 2]\n'
                'let r3 = List.fold (fun acc x -> match x: case acc: Map.add acc 1 Map.empty) Map.empty [1, 2]\n'
                'let r4 u = List.fold (fun acc m0 -> Map.add 1 (Map.len m0) acc) m0 [m0]\n'
                'let step5 acc x =\n'
                '  match x:\n'
                '    case Even: Map.add x 0 acc\n'
                '    case Odd: acc\n'
                'let r5 = List.fold step5 Map.empty [1, 2]\n'
                'let r6 = List.fold (fun acc x -> match (acc, x): case (m, k): Map.add k 1 m) Map.empty [1, 2]\n'
                'let step7 acc x =\n'
                '  match acc:\n'
                '    case (m, n) if n > 5: (m, n)\n'
                '    case (m, n): (Map.add x 1 m, n)\n'
                'let r7 = List.fold step7 (Map.empty, 0) [1]\n'
                'let r8 = List.fold (fun acc x -> match acc: case m: Map.add x 1 m) Map.empty [1, 2]\n'
                'let step9 acc x =\n'
                '  match acc:\n'
                '    case (m, n): (fun p -> p) (Map.add x 1 m, n)\n'
                'let r9 = List.fold step9 (Map.empty, []) [1]\n'
                'let r10 = List.fold (fun acc x -> Map.add x 1 (Map.filter (fun k v -> k > 0) acc)) Map.empty [1, 2]\n'
                'let r11 = List.fold (fun acc (Pt { x, y }) -> Map.add x y acc) Map.empty [Pt { x = 1, y = 2 }]\n'
                'print r2\n'
                'print r3\n'
                'print (r4 ())\n'
                'print r5\n'
                'print r6\n'
                'print r7\n'
                'print r8\n'
                'print r9\n'
                'print r10\n'
                'print r11\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_folder_returning_a_lambda__compile',
        "files": {
            'main.pyfun': (
                'let step1 acc = fun x -> Map.add x 1 acc\n'
                'let r1 = List.fold step1 Map.empty [1, 2]\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

TARGET_CASES = [
    {
        'id': 'string_escapes_in_literals_and_fstrings__compile',
        "files": {
            'main.pyfun': (
                'let who = "tab\\there"\n'
                'let line = f"quote \\" backslash \\\\ tab \\t cr \\r {who} {String.upper "x"}"\n'
                'print line\n'
                'print (String.len who)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_escapes_in_literals_and_fstrings__311',
        "files": {
            'main.pyfun': (
                'let who = "tab\\there"\n'
                'let line = f"quote \\" backslash \\\\ tab \\t cr \\r {who} {String.upper "x"}"\n'
                'print line\n'
                'print (String.len who)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--target', '3.11'],
    },
    {
        'id': 'py311_rich_program__311',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                'type Shape = Circle float | Rect float float\n'
                'type Pt = { x: int, y: int }\n'
                'let worker name = async {\n'
                '  do! Async.sleep 0.0\n'
                '  print f"worker {String.upper "x"} {name}"\n'
                '}\n'
                'let main = async {\n'
                '  do! Task.scope (async {\n'
                '    Task.start (worker "a")\n'
                '  })\n'
                '}\n'
                'let count n acc = if n == 0 then f"done {String.lower "ACC"}: {acc}" else count (n - 1) (acc + n)\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r if r > 1.0: f"big {String.upper "c"} {r}"\n'
                '    case Circle r: "small"\n'
                '    case Rect w h: f"{{rect}} {String.concat "w" "h"} {w * h}"\n'
                'let index xs = List.fold (fun t k -> Map.add k (parseIn "ff" 16) t) Map.empty xs\n'
                'let pts = Encode.auto (Pt { x = 1, y = 2 })\n'
                'let back =\n'
                '  match Decode.decodeString Decode.auto pts:\n'
                '    case Ok p: f"x={p.x} {String.upper "ok"}"\n'
                '    case Error e: f"failed {e.errorKind}"\n'
                'print (count 3 0)\n'
                'print (area (Rect 1.0 2.0))\n'
                'print (index [1, 2])\n'
                'print pts\n'
                'print back\n'
                'print (runAsync main)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--target', '3.11'],
    },
    {
        'id': 'py311_rich_program__native311',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                'type Shape = Circle float | Rect float float\n'
                'type Pt = { x: int, y: int }\n'
                'let worker name = async {\n'
                '  do! Async.sleep 0.0\n'
                '  print f"worker {String.upper "x"} {name}"\n'
                '}\n'
                'let main = async {\n'
                '  do! Task.scope (async {\n'
                '    Task.start (worker "a")\n'
                '  })\n'
                '}\n'
                'let count n acc = if n == 0 then f"done {String.lower "ACC"}: {acc}" else count (n - 1) (acc + n)\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r if r > 1.0: f"big {String.upper "c"} {r}"\n'
                '    case Circle r: "small"\n'
                '    case Rect w h: f"{{rect}} {String.concat "w" "h"} {w * h}"\n'
                'let index xs = List.fold (fun t k -> Map.add k (parseIn "ff" 16) t) Map.empty xs\n'
                'let pts = Encode.auto (Pt { x = 1, y = 2 })\n'
                'let back =\n'
                '  match Decode.decodeString Decode.auto pts:\n'
                '    case Ok p: f"x={p.x} {String.upper "ok"}"\n'
                '    case Error e: f"failed {e.errorKind}"\n'
                'print (count 3 0)\n'
                'print (area (Rect 1.0 2.0))\n'
                'print (index [1, 2])\n'
                'print pts\n'
                'print back\n'
                'print (runAsync main)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native', '--target', '3.11'],
    },
]

RUN_CASES = [
    {
        'id': 'tail_nested_def_rich__run',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'type Sh = Circle int | Sq int\n'
                'let go n acc =\n'
                '  let helper x =\n'
                '    let (a, b) = (x, x + 1)\n'
                '    let p = P { x = a, y = b }\n'
                '    let q = { p with y = 9 }\n'
                '    let m = Map.ofList [(a, b)]\n'
                '    let xs = [a, b, a * b]\n'
                '    let sl = List.take 2 xs\n'
                '    let s = f"v={a} {b}"\n'
                '    let neg = -a\n'
                '    let c = if a < b < 10 then 1 else 0\n'
                '    let f = fun z -> z + a\n'
                '    let t = List.fold (fun acc2 e -> acc2 + e) 0 xs\n'
                '    let r = match Circle a:\n'
                '      case Circle k if k > 3: k\n'
                '      case Circle k: k + 1\n'
                '      case Sq k: k\n'
                '    let r2 = match xs:\n'
                '      case [h, *rest]: h\n'
                '      case []: 0\n'
                '    let r3 = match p:\n'
                '      case P { x, y }: x + y\n'
                '    let r4 = match (a, b):\n'
                '      case (1, _) | (2, _): 1\n'
                '      case (u, v) as w: u\n'
                '    let bl = not (a == b) and neg < 0 or c == 1\n'
                '    t + r + r2 + r3 + r4 + f 1 + q.y + String.len s + Map.len m + List.len sl\n'
                '  if n == 0 then acc else go (n - 1) (acc + helper n)\n'
                'print (go 10 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_nested_def_deep__run',
        "files": {
            'main.pyfun': (
                'let go n acc =\n'
                '  let helper x = x % 7\n'
                '  if n == 0 then acc else go (n - 1) (acc + helper n)\n'
                'print (go 50000 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_outer_frame_statements__run',
        "files": {
            'main.pyfun': (
                'extern parseInt: string -> int = int\n'
                'let go n acc =\n'
                '  let (a, b) = (n, acc)\n'
                '  print f"step {a}"\n'
                '  let tbl = List.fold (fun t x -> Map.add x a t) Map.empty [1, 2, 3]\n'
                '  let r = try (parseInt (String.fromInt a))\n'
                '  let v = Result.withDefault 0 r\n'
                '  if a == 0 then b + Map.len tbl else go (a - 1) (b + v)\n'
                'print (go 3 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_nested_def_statements__run',
        "files": {
            'main.pyfun': (
                'let go n acc =\n'
                '  let helper x =\n'
                '    let inner y = y * 2\n'
                '    print "in helper"\n'
                '    let tbl = List.fold (fun t k -> Map.add k x t) Map.empty [x, x + 1]\n'
                '    let tot = Map.len tbl\n'
                '    let ys = seq {\n'
                '      yield x\n'
                '      yield inner x\n'
                '      yield! (Seq.ofList [tot])\n'
                '    }\n'
                '    let countdown k s = if k == 0 then s else countdown (k - 1) (s + k)\n'
                '    let w = try (x / 2)\n'
                '    if tot > 1 then countdown x (inner tot) + Seq.sum ys else 0\n'
                '  if n == 0 then acc else go (n - 1) (acc + helper n)\n'
                'print (go 4 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_nested_def_captures_mut__run',
        "files": {
            'main.pyfun': (
                'let go n acc =\n'
                '  let mut seen = 0\n'
                '  let bump k =\n'
                '    seen <- seen + k\n'
                '    seen\n'
                '  let total = bump n\n'
                '  if n == 0 then acc + total else go (n - 1) (acc + total)\n'
                'print (go 3 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_kwarg_extern_in_nested__run',
        "files": {
            'main.pyfun': (
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                'extern parseHex: string -> int = int(base = 16)\n'
                'let go n acc =\n'
                '  let conv s = parseIn s 16 + parseHex s\n'
                '  let partial = parseIn "ff"\n'
                '  if n == 0 then acc else go (n - 1) (acc + conv "a" + partial 16)\n'
                'print (go 2 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_rebinds_own_name__run',
        "files": {
            'main.pyfun': (
                'let go n =\n'
                '  let go2 = n\n'
                '  let go k = k + 1\n'
                '  if n == 0 then 0 else go (n - 1)\n'
                'print (go 5)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'async_tail_with_task_scope__run',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let worker name = async {\n'
                '  do! Async.sleep 0.0\n'
                '  print f"worker {name}"\n'
                '}\n'
                'let finished acc = async { return acc }\n'
                'let tick n acc =\n'
                '  async {\n'
                '    let (a, b) = (n, acc)\n'
                '    do! Task.scope (async {\n'
                '      Task.start (worker "w")\n'
                '    })\n'
                '    let tbl = List.fold (fun t k -> Map.add k a t) Map.empty [1, 2]\n'
                '    return! (if a == 0 then finished (b + Map.len tbl) else tick (a - 1) (b + a))\n'
                '  }\n'
                'print (runAsync (tick 2 0))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_outer_frame_patterns__run',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'type Sh = Circle int | Sq int\n'
                'let go n acc =\n'
                '  let pairs = List.fold (fun t (k, v) -> Map.add k v t) Map.empty [(n, acc), (0, 1)]\n'
                '  let a =\n'
                '    match Pt { x = n, y = acc }:\n'
                '      case Pt { x, y } if x > y: x\n'
                '      case Pt { x, y }: y\n'
                '  let b =\n'
                '    match (n, acc):\n'
                '      case (0, _) | (_, 0): 1\n'
                '      case (p, q) as both: p\n'
                '  let c =\n'
                '    match [n, acc]:\n'
                '      case [h, *rest]: h\n'
                '      case _: 0\n'
                '  let d =\n'
                '    match Sq n:\n'
                '      case Circle r as whole: r\n'
                '      case Sq s: s\n'
                '  if n <= 0 then acc + Map.len pairs else go (n - 1) (acc + a + b + c + d)\n'
                'print (go 4 1)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'async_tail_rebinds_own_name__run',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let finished acc = async { return acc }\n'
                'let tick n =\n'
                '  async {\n'
                '    let tick = fun k -> finished (k * 10)\n'
                '    return! (if n == 0 then finished 0 else tick (n - 1))\n'
                '  }\n'
                'print (runAsync (tick 3))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'string_escapes_in_literals_and_fstrings__run',
        "files": {
            'main.pyfun': (
                'let who = "tab\\there"\n'
                'let line = f"quote \\" backslash \\\\ tab \\t cr \\r {who} {String.upper "x"}"\n'
                'print line\n'
                'print (String.len who)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_value_position_sweep__run',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let summarize xs =\n'
                '  let mut seen = 0\n'
                '  let step acc x =\n'
                '    seen <- seen + 1\n'
                '    let width = 2<1>\n'
                '    let c = if x > 2 then 1 else 0\n'
                '    let t = Result.withDefault 0 (try (x // 1))\n'
                '    let label =\n'
                '      match x:\n'
                '        case 0: "zero"\n'
                '        case n if n > 5: "big"\n'
                '        case _: "other"\n'
                '    let neg = -x\n'
                '    let inRange = 0 < x < 10\n'
                '    let blk =\n'
                '      let inner = x * 2\n'
                '      inner + 1\n'
                '    let p = Pt { x = x, y = blk }\n'
                '    let q = { p with y = neg }\n'
                '    let s = f"{x}-{label}-{inRange}"\n'
                '    let size = Map.len acc\n'
                '    print s\n'
                '    Map.add x (q.y + c + t + size + p.x + width) acc\n'
                '  let out = List.fold step Map.empty xs\n'
                '  (out, seen)\n'
                'print (summarize [1, 3, 7])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_closure_rule_sweep__run',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let origin = Pt { x = 0, y = 0 }\n'
                'let tally xs =\n'
                '  let mut calls = 0\n'
                '  let step acc x =\n'
                '    let helper k =\n'
                '      calls <- calls + 1\n'
                '      let a = if k > 0 then k else 0\n'
                '      let b = Result.withDefault 0 (try (k // 1))\n'
                '      let c =\n'
                '        match k:\n'
                '          case 1: 1\n'
                '          case z if z > 2: z\n'
                '          case _: 0\n'
                '      let d = k |> (fun v -> v + 1)\n'
                '      let e = ((fun v -> v + 1) >> (fun v -> v * 2)) k\n'
                '      let g = -k\n'
                '      let h = if 1 < k < 9 then 1 else 0\n'
                '      let r = { origin with x = k }\n'
                '      let s = f"{k}"\n'
                '      let o = Option.withDefault 0 (option {\n'
                '        let! v = Some k\n'
                '        do! Some ()\n'
                '        return! Some (v + 1)\n'
                '      })\n'
                '      let rec0 = Pt { x = k, y = r.x }\n'
                '      let blk =\n'
                '        let w = k\n'
                '        w\n'
                '      a + b + c + d + e + g + h + o + rec0.y + blk + String.len s\n'
                '    Set.add (helper x) acc\n'
                '  let out = List.fold step Set.empty xs\n'
                '  (Set.toList out |> List.sort, calls)\n'
                'print (tally [1, 2, 3])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_top_level_named_folder_free_vars__run',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let base = Pt { x = 1, y = 2 }\n'
                'let mut hits = 0\n'
                'let step acc x =\n'
                '  hits <- hits + 1\n'
                '  let a = x |> (fun v -> v + base.x)\n'
                '  let b = ((fun v -> v) >> (fun v -> v + 1)) x\n'
                '  let c = -x\n'
                '  let d = Result.withDefault 0 (try (x // 1))\n'
                '  let e = if 0 < x < 100 then 1 else 0\n'
                '  let f = { base with y = x }\n'
                '  let g = f"{x}"\n'
                '  let h =\n'
                '    match x:\n'
                '      case k if k > base.y: k\n'
                '      case _: 0\n'
                '  let i = Seq.sum (seq {\n'
                '    let w = x\n'
                '    yield w\n'
                '    yield! (Seq.ofList [w + 1])\n'
                '    for z in [1, 2]:\n'
                '      yield z\n'
                '  })\n'
                '  let j = Option.withDefault 0 (option {\n'
                '    let! v = Some x\n'
                '    do! Some ()\n'
                '    return! Some v\n'
                '  })\n'
                '  let k = Result.withDefault 0 (result {\n'
                '    let! v = Ok x\n'
                '    return v\n'
                '  })\n'
                '  Map.add x (a + b + c + d + e + f.y + String.len g + h + i + j + k) acc\n'
                'let built = List.fold step Map.empty [1, 5]\n'
                'print built\n'
                'print hits\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_rejections__run',
        "files": {
            'main.pyfun': (
                'type Pt = { x: int, y: int }\n'
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let m0 = Map.ofList [(1, 1)]\n'
                'let start = (Map.empty, 0)\n'
                'let r2 = List.fold (fun acc x -> match acc: case (m, n): (Map.add x 1 m, n + 1)) start [1, 2]\n'
                'let r3 = List.fold (fun acc x -> match x: case acc: Map.add acc 1 Map.empty) Map.empty [1, 2]\n'
                'let r4 u = List.fold (fun acc m0 -> Map.add 1 (Map.len m0) acc) m0 [m0]\n'
                'let step5 acc x =\n'
                '  match x:\n'
                '    case Even: Map.add x 0 acc\n'
                '    case Odd: acc\n'
                'let r5 = List.fold step5 Map.empty [1, 2]\n'
                'let r6 = List.fold (fun acc x -> match (acc, x): case (m, k): Map.add k 1 m) Map.empty [1, 2]\n'
                'let step7 acc x =\n'
                '  match acc:\n'
                '    case (m, n) if n > 5: (m, n)\n'
                '    case (m, n): (Map.add x 1 m, n)\n'
                'let r7 = List.fold step7 (Map.empty, 0) [1]\n'
                'let r8 = List.fold (fun acc x -> match acc: case m: Map.add x 1 m) Map.empty [1, 2]\n'
                'let step9 acc x =\n'
                '  match acc:\n'
                '    case (m, n): (fun p -> p) (Map.add x 1 m, n)\n'
                'let r9 = List.fold step9 (Map.empty, []) [1]\n'
                'let r10 = List.fold (fun acc x -> Map.add x 1 (Map.filter (fun k v -> k > 0) acc)) Map.empty [1, 2]\n'
                'let r11 = List.fold (fun acc (Pt { x, y }) -> Map.add x y acc) Map.empty [Pt { x = 1, y = 2 }]\n'
                'print r2\n'
                'print r3\n'
                'print (r4 ())\n'
                'print r5\n'
                'print r6\n'
                'print r7\n'
                'print r8\n'
                'print r9\n'
                'print r10\n'
                'print r11\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'py311_rich_program__run',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern parseIn: string -> int -> int = int(base = ...)\n'
                'type Shape = Circle float | Rect float float\n'
                'type Pt = { x: int, y: int }\n'
                'let worker name = async {\n'
                '  do! Async.sleep 0.0\n'
                '  print f"worker {String.upper "x"} {name}"\n'
                '}\n'
                'let main = async {\n'
                '  do! Task.scope (async {\n'
                '    Task.start (worker "a")\n'
                '  })\n'
                '}\n'
                'let count n acc = if n == 0 then f"done {String.lower "ACC"}: {acc}" else count (n - 1) (acc + n)\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r if r > 1.0: f"big {String.upper "c"} {r}"\n'
                '    case Circle r: "small"\n'
                '    case Rect w h: f"{{rect}} {String.concat "w" "h"} {w * h}"\n'
                'let index xs = List.fold (fun t k -> Map.add k (parseIn "ff" 16) t) Map.empty xs\n'
                'let pts = Encode.auto (Pt { x = 1, y = 2 })\n'
                'let back =\n'
                '  match Decode.decodeString Decode.auto pts:\n'
                '    case Ok p: f"x={p.x} {String.upper "ok"}"\n'
                '    case Error e: f"failed {e.errorKind}"\n'
                'print (count 3 0)\n'
                'print (area (Rect 1.0 2.0))\n'
                'print (index [1, 2])\n'
                'print pts\n'
                'print back\n'
                'print (runAsync main)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]


def _check(run, workdir, case):
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", TAIL_CALL_CASES, ids=[c["id"] for c in TAIL_CALL_CASES])
def test_self_tail_calls_compile_to_loops(run, workdir, case):
    """CATCHES: a tail-call rewrite that is missing (the function stays recursive and
    stack-bound), applied when unsafe (a closure capturing a loop variable, a body that
    rebinds the function's name), loses or misplaces statements of the looping frame or
    of its nested functions, rebinds the parameters non-simultaneously, or prints a
    different (or no) `note:` for a refused rewrite."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", FOLD_LOOP_CASES, ids=[c["id"] for c in FOLD_LOOP_CASES])
def test_folds_compile_to_in_place_loops_or_fall_back(run, workdir, case):
    """CATCHES: an in-place fold rewrite that fires on a folder it cannot prove safe
    (a sensitive accumulator read inside a closure, a shadowed slot, an aliased init, an
    active-pattern match, a non-update tail) or fails to fire on one it can, or that
    inlines the folder body with statements dropped, reordered or mis-scoped."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", TARGET_CASES, ids=[c["id"] for c in TARGET_CASES])
def test_target_311_rewrites_every_fstring_that_needs_pep_701(run, workdir, case):
    """CATCHES: a `--target 3.11` pass that misses f-strings nested inside loops, async
    helpers, kwarg calls, match arms or the codec table; forgets to double literal
    braces in the `.format` template; mangles quote/backslash/tab/CR escapes; or that
    does not compose with `--native`."""
    _check(run, workdir, case)


@pytest.mark.parametrize("case", RUN_CASES, ids=[c["id"] for c in RUN_CASES])
def test_loop_lowerings_compute_the_same_values(run, workdir, case):
    """CATCHES: loop rewrites that change what the program computes — a tail loop that
    reads updated parameters too early or overflows the stack on deep recursion, an
    in-place fold that mutates a value still visible elsewhere, a 3.11/escape rewrite
    that changes the printed text."""
    _check(run, workdir, case)
