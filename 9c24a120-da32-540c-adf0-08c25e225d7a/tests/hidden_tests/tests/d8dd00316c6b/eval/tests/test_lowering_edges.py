"""Lowering edge cases: programs chosen to reach the less-travelled paths of the
Pyfun-to-Python lowering (extern boundary adapters, beta reduction, active-pattern and
ladder matches, `--native` ladders, CE loops, derived codecs, decoder specialisation,
string escaping, lowering errors). Each case writes its sources into the empty working
directory and compares the whole transcript with one captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

EXTERN_CASES = [
    {
        'id': 'project_externs',
        "files": {
            'main.pyfun': (
                'import Lib\n'
                'print (Lib.pick 3 () 5)\n'
                'print (Lib.parseHex "ff")\n'
                'print (Lib.parseInt "11" 2)\n'
                'let f = Lib.parseInt "7"\n'
                'print (f 10)\n'
            ),
            'lib.pyfun': (
                'extern pick: int -> unit -> int -> int = max\n'
                'extern now: unit -> float = time.time\n'
                'extern parseHex : string -> int = int(base=16)\n'
                'extern parseInt : string -> int -> int = int(base=...)\n'
                'extern type C\n'
                'extern ping: C -> unit -> string = .m()\n'
                'extern size: C -> int = .size\n'
                'extern ws: C -> string -> int = .write(encoding="utf-8")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'project_externs_run',
        "files": {
            'main.pyfun': (
                'import Lib\n'
                'print (Lib.pick 3 () 5)\n'
                'print (Lib.parseHex "ff")\n'
                'print (Lib.parseInt "11" 2)\n'
                'let f = Lib.parseInt "7"\n'
                'print (f 10)\n'
            ),
            'lib.pyfun': (
                'extern pick: int -> unit -> int -> int = max\n'
                'extern now: unit -> float = time.time\n'
                'extern parseHex : string -> int = int(base=16)\n'
                'extern parseInt : string -> int -> int = int(base=...)\n'
                'extern type C\n'
                'extern ping: C -> unit -> string = .m()\n'
                'extern size: C -> int = .size\n'
                'extern ws: C -> string -> int = .write(encoding="utf-8")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'bare_extern_refs',
        "files": {
            'main.pyfun': (
                'extern type C\n'
                'extern size: C -> int = .size\n'
                'extern ping: C -> unit -> string = .m()\n'
                'extern wr: C -> string -> int = .write(encoding="utf-8")\n'
                'extern now: unit -> float = time.time\n'
                'extern nowKw: unit -> float = m.clock(fast=true)\n'
                'extern pick: int -> unit -> int -> int = max\n'
                'extern pickKw: int -> unit -> int -> int = m.pick(k=1)\n'
                'extern cb: C -> unit -> int = .callback\n'
                'let sizes cs = List.map size cs\n'
                'let pings cs = List.map ping cs\n'
                'let writes cs = List.map wr cs\n'
                'let t = now\n'
                'let t2 = nowKw\n'
                'let p = pick\n'
                'let p2 = pickKw\n'
                'let q2 = pickKw 1 () 2\n'
                'let call c = cb c ()\n'
                'let fullNow = nowKw ()\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'bare_unit_extern_run',
        "files": {
            'main.pyfun': (
                'extern pick: int -> unit -> int -> int = max\n'
                'extern myAbs: unit -> int -> int = abs\n'
                'let p = pick\n'
                'let a = myAbs\n'
                'print (p 3 () 9)\n'
                'print (a () (-4))\n'
                'print (pick (1 + 2) (print "effect") 2)\n'
                'print (pick 1 (print "e2") 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'bare_unit_extern_run_c',
        "files": {
            'main.pyfun': (
                'extern pick: int -> unit -> int -> int = max\n'
                'extern myAbs: unit -> int -> int = abs\n'
                'let p = pick\n'
                'let a = myAbs\n'
                'print (p 3 () 9)\n'
                'print (a () (-4))\n'
                'print (pick (1 + 2) (print "effect") 2)\n'
                'print (pick 1 (print "e2") 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'kwarg_over_application',
        "files": {
            'main.pyfun': (
                'extern conv : string -> a = m.conv(strict=true)\n'
                'let r = conv "x" 2 3\n'
                'extern mk: unit -> a = m.make\n'
                'let s = mk () 4\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'async_thunk_slot',
        "files": {
            'main.pyfun': (
                'extern runLater : (unit ->{e} Async int) -> int = m.run_later\n'
                'extern fetch : string ->{async} Async string = m.get(timeout=5)\n'
                'let job _ = async { return 1 }\n'
                'let a = runLater (fun _ -> async { return 2 })\n'
                'let b = runLater job\n'
                'let c = fetch "u"\n'
                'let s = Async.sleep\n'
                'let d = async {\n'
                '  do! s 0.0\n'
                '  let! body = fetch "v"\n'
                '  return body\n'
                '}\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'thunk_extern_args',
        "files": {
            'main.pyfun': (
                'extern import threading\n'
                'extern type Lock\n'
                'extern later : (unit -> int) -> int = m.call_later\n'
                'extern type C\n'
                'extern ready : C ->{async} Async int = .ready\n'
                'let k = later (fun _ -> 5)\n'
                'let wait c = async {\n'
                '  let! r = ready c\n'
                '  return r + 1\n'
                '}\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'beta_reduce_kwargs_and_callbacks',
        "files": {
            'main.pyfun': (
                'extern parseHex : string -> int = int(base=16)\n'
                'extern serve : (string -> Async unit) -> int = m.serve\n'
                'let h = "ff"\n'
                'let g = (fun a b -> parseHex a + b) h\n'
                'let handler s = async { print s }\n'
                'print (g 1)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'beta_reduce_async_callback',
        "files": {
            'main.pyfun': (
                'extern serve : (string ->{e} Async unit) -> int = m.serve\n'
                'let handler s = async { print s }\n'
                'let g2 = (fun a b -> serve handler + a + b) 1\n'
                'print "ok"\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

BINDING_CASES = [
    {
        'id': 'beta_reduce_shapes',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'let p = P { x = 1, y = 2 }\n'
                'let k = 10\n'
                'let fs = [\n'
                '  (fun a b -> if b < a.x < 100 then a.x + b else -b) p,\n'
                ']\n'
                'let g1 = (fun a b -> List.map (fun c -> c + a + b) [a, b]) k\n'
                'let g2 = (fun a b -> List.map (fun a -> a * b) [a]) k\n'
                'let g3 = (fun a b -> (a, not (a == b), f"{a}-{b}")) k\n'
                'let g4 = (fun a b -> List.take a b) 1\n'
                'let g5 = (fun a b -> Map.ofList [(a, b)]) "key"\n'
                'let g6 = (fun a b -> String.join a [b, b]) "+"\n'
                'print (g1 1)\n'
                'print (g2 3)\n'
                'print (g3 4)\n'
                'print (g4 [7, 8, 9])\n'
                'print (g5 2)\n'
                'print (g6 "z")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'beta_reduce_shapes_c',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'let p = P { x = 1, y = 2 }\n'
                'let k = 10\n'
                'let fs = [\n'
                '  (fun a b -> if b < a.x < 100 then a.x + b else -b) p,\n'
                ']\n'
                'let g1 = (fun a b -> List.map (fun c -> c + a + b) [a, b]) k\n'
                'let g2 = (fun a b -> List.map (fun a -> a * b) [a]) k\n'
                'let g3 = (fun a b -> (a, not (a == b), f"{a}-{b}")) k\n'
                'let g4 = (fun a b -> List.take a b) 1\n'
                'let g5 = (fun a b -> Map.ofList [(a, b)]) "key"\n'
                'let g6 = (fun a b -> String.join a [b, b]) "+"\n'
                'print (g1 1)\n'
                'print (g2 3)\n'
                'print (g3 4)\n'
                'print (g4 [7, 8, 9])\n'
                'print (g5 2)\n'
                'print (g6 "z")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'lambda_folder',
        "files": {
            'main.pyfun': (
                'let step = fun acc x -> acc + x * 2\n'
                'let total = List.fold step 0 [1, 2, 3]\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'lambda_folder_c',
        "files": {
            'main.pyfun': (
                'let step = fun acc x -> acc + x * 2\n'
                'let total = List.fold step 0 [1, 2, 3]\n'
                'print total\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'module_lambda_member',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let inc = fun x -> x + 1\n'
                '  let twice = fun f x -> f (f x)\n'
                'let r = M.twice M.inc 5\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'module_lambda_member_c',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let inc = fun x -> x + 1\n'
                '  let twice = fun f x -> f (f x)\n'
                'let r = M.twice M.inc 5\n'
                'print r\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'module_wild_member',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let _ = print "loaded"\n'
                '  let x = 1\n'
                'print M.x\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'module_wild_member_c',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let _ = print "loaded"\n'
                '  let x = 1\n'
                'print M.x\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'toplevel_frame_wild',
        "files": {
            'main.pyfun': (
                'let t = 5\n'
                'let _ =\n'
                '  let t = 1\n'
                '  print t\n'
                'print t\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'toplevel_frame_destr',
        "files": {
            'main.pyfun': (
                'let t = 5\n'
                'let (a, b) =\n'
                '  let t = 2\n'
                '  (t, t + 1)\n'
                'print (a, b, t)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'toplevel_frame_destr_c',
        "files": {
            'main.pyfun': (
                'let t = 5\n'
                'let (a, b) =\n'
                '  let t = 2\n'
                '  (t, t + 1)\n'
                'print (a, b, t)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

MATCH_CASES = [
    {
        'id': 'ap_literal_and_var_arms',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let (|Prefix|_|) p s = if String.startsWith p s then Some (String.slice (String.len p) (String.len s) s) else None\n'
                'let (|Flag|_|) b x = x == b\n'
                'let classify n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case Even: "even"\n'
                '    case other: f"odd {other}"\n'
                'let strip s =\n'
                '  match s:\n'
                '    case "": "empty"\n'
                '    case Prefix "ab" rest: rest\n'
                '    case Prefix "x" _: "x-thing"\n'
                '    case _: s\n'
                'let flag b =\n'
                '  match b:\n'
                '    case true: "yes"\n'
                '    case Flag false: "no"\n'
                '    case _: "?"\n'
                'let pre = "q"\n'
                'let byvar s =\n'
                '  match s:\n'
                '    case Prefix pre r: r\n'
                '    case _: "none"\n'
                'print (classify 0)\n'
                'print (classify 4)\n'
                'print (classify 7)\n'
                'print (strip "")\n'
                'print (strip "abc")\n'
                'print (strip "xy")\n'
                'print (strip "zz")\n'
                'print (flag true)\n'
                'print (flag false)\n'
                'print (byvar "qrs")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ap_literal_and_var_arms_c',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let (|Prefix|_|) p s = if String.startsWith p s then Some (String.slice (String.len p) (String.len s) s) else None\n'
                'let (|Flag|_|) b x = x == b\n'
                'let classify n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case Even: "even"\n'
                '    case other: f"odd {other}"\n'
                'let strip s =\n'
                '  match s:\n'
                '    case "": "empty"\n'
                '    case Prefix "ab" rest: rest\n'
                '    case Prefix "x" _: "x-thing"\n'
                '    case _: s\n'
                'let flag b =\n'
                '  match b:\n'
                '    case true: "yes"\n'
                '    case Flag false: "no"\n'
                '    case _: "?"\n'
                'let pre = "q"\n'
                'let byvar s =\n'
                '  match s:\n'
                '    case Prefix pre r: r\n'
                '    case _: "none"\n'
                'print (classify 0)\n'
                'print (classify 4)\n'
                'print (classify 7)\n'
                'print (strip "")\n'
                'print (strip "abc")\n'
                'print (strip "xy")\n'
                'print (strip "zz")\n'
                'print (flag true)\n'
                'print (flag false)\n'
                'print (byvar "qrs")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ap_structural_arm_falls_back',
        "files": {
            'main.pyfun': (
                'let (|Diag|_|) p =\n'
                '  match p:\n'
                '    case (a, b): a == b\n'
                'let f p =\n'
                '  match p:\n'
                '    case Diag: 1\n'
                '    case (a, b): a\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ap_list_arm',
        "files": {
            'main.pyfun': (
                'let (|Single|_|) xs =\n'
                '  match xs:\n'
                '    case [x]: Some x\n'
                '    case _: None\n'
                'let f xs =\n'
                '  match xs:\n'
                '    case Single x: x\n'
                '    case [a, b]: a + b\n'
                '    case _: 0\n'
                'print (f [1])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ap_or_with_wildcard',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let (|Prefix|_|) p s = if String.startsWith p s then Some (String.slice (String.len p) (String.len s) s) else None\n'
                'let (|Flag|_|) b x = x == b\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even | _: 1\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ladder_nested_tuple',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some ((a, _), c): a + c\n'
                '    case None: 0\n'
                'print (f (Some ((1, 2), 3)))\n'
                'print (f None)\n'
                'let g r =\n'
                '  match r:\n'
                '    case Ok (x, _): x\n'
                '    case Error _: -1\n'
                'print (g (Ok (5, "z")))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ladder_nested_tuple_c',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some ((a, _), c): a + c\n'
                '    case None: 0\n'
                'print (f (Some ((1, 2), 3)))\n'
                'print (f None)\n'
                'let g r =\n'
                '  match r:\n'
                '    case Ok (x, _): x\n'
                '    case Error _: -1\n'
                'print (g (Ok (5, "z")))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ladder_guarded_last_arm',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                '    case Some n if n > 1: 99\n'
                'type W = W (Option int)\n'
                'print (f (Some 3))\n'
                'print (f None)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ladder_guarded_last_arm_c',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                '    case Some n if n > 1: 99\n'
                'type W = W (Option int)\n'
                'print (f (Some 3))\n'
                'print (f None)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'lookup_variants',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [("a", 1)]\n'
                'let has k =\n'
                '  match Map.tryFind k m:\n'
                '    case Some _: true\n'
                '    case None: false\n'
                'let first xs =\n'
                '  match List.head xs:\n'
                '    case Some x: x\n'
                '    case None: 0\n'
                'let lit xs =\n'
                '  match List.head xs:\n'
                '    case Some 1: "one"\n'
                '    case _: "other"\n'
                'let v = match List.get 1 [5, 6]:\n'
                '  case None: 0\n'
                '  case Some (y) : y\n'
                'print (has "a")\n'
                'print (has "b")\n'
                'print (first [9, 8])\n'
                'print (first [])\n'
                'print (lit [1])\n'
                'print (lit [2])\n'
                'print v\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'lookup_variants_c',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [("a", 1)]\n'
                'let has k =\n'
                '  match Map.tryFind k m:\n'
                '    case Some _: true\n'
                '    case None: false\n'
                'let first xs =\n'
                '  match List.head xs:\n'
                '    case Some x: x\n'
                '    case None: 0\n'
                'let lit xs =\n'
                '  match List.head xs:\n'
                '    case Some 1: "one"\n'
                '    case _: "other"\n'
                'let v = match List.get 1 [5, 6]:\n'
                '  case None: 0\n'
                '  case Some (y) : y\n'
                'print (has "a")\n'
                'print (has "b")\n'
                'print (first [9, 8])\n'
                'print (first [])\n'
                'print (lit [1])\n'
                'print (lit [2])\n'
                'print v\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'value_position_lookups',
        "files": {
            'main.pyfun': (
                'let xs = [4, 5]\n'
                'let a = match List.head xs:\n'
                '  case Some x: x * 10\n'
                '  case None: 0\n'
                'let b = match List.head xs:\n'
                '  case Some 4: "four"\n'
                '  case _: "other"\n'
                'let c = match List.head []:\n'
                '  case None: -1\n'
                '  case Some y: y\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'value_position_lookups_c',
        "files": {
            'main.pyfun': (
                'let xs = [4, 5]\n'
                'let a = match List.head xs:\n'
                '  case Some x: x * 10\n'
                '  case None: 0\n'
                'let b = match List.head xs:\n'
                '  case Some 4: "four"\n'
                '  case _: "other"\n'
                'let c = match List.head []:\n'
                '  case None: -1\n'
                '  case Some y: y\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'exists_named_predicates',
        "files": {
            'main.pyfun': (
                'let isBig x = x > 3\n'
                'let xs = [1, 5]\n'
                'print (List.exists isBig xs)\n'
                'print (List.exists ((<) 3) xs)\n'
                'print (List.find ((==) 5) xs)\n'
                'print (List.findIndex (fun y -> 1 == y) xs)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'exists_named_predicates_c',
        "files": {
            'main.pyfun': (
                'let isBig x = x > 3\n'
                'let xs = [1, 5]\n'
                'print (List.exists isBig xs)\n'
                'print (List.exists ((<) 3) xs)\n'
                'print (List.find ((==) 5) xs)\n'
                'print (List.findIndex (fun y -> 1 == y) xs)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'param_destructuring_wild',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int, col: int, letter: string }\n'
                'let f (a, (_, b)) = a + b\n'
                'let g (Cell { letter = l, row = _ }) = l\n'
                'let h (Cell { letter = (x), col }) = x\n'
                'print (f (1, (2, 3)))\n'
                'print (g (Cell { row = 1, col = 2, letter = "z" }))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'param_destructuring_wild_c',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int, col: int, letter: string }\n'
                'let f (a, (_, b)) = a + b\n'
                'let g (Cell { letter = l, row = _ }) = l\n'
                'let h (Cell { letter = (x), col }) = x\n'
                'print (f (1, (2, 3)))\n'
                'print (g (Cell { row = 1, col = 2, letter = "z" }))\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unit_name_arm_and_lookup_c',
        "files": {
            'main.pyfun': (
                'type T = A | B int\n'
                'type P = { x: int }\n'
                'let m = Map.ofList [(1, "one")]\n'
                'let v k =\n'
                '  let r = match Map.tryFind k m:\n'
                '    case Some _: 1\n'
                '    case None: 0\n'
                '  r * 10\n'
                'let w o = match o:\n'
                '  case Some (P { x }): x\n'
                '  case None: 0\n'
                'let u = ()\n'
                'let f t y =\n'
                '  match t:\n'
                '    case A: u\n'
                '    case B n: print n\n'
                '  y\n'
                'print (v 1, v 2, w (Some (P { x = 3 })), f A 4)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unit_name_arm_and_lookup_run',
        "files": {
            'main.pyfun': (
                'type T = A | B int\n'
                'type P = { x: int }\n'
                'let m = Map.ofList [(1, "one")]\n'
                'let v k =\n'
                '  let r = match Map.tryFind k m:\n'
                '    case Some _: 1\n'
                '    case None: 0\n'
                '  r * 10\n'
                'let w o = match o:\n'
                '  case Some (P { x }): x\n'
                '  case None: 0\n'
                'let u = ()\n'
                'let f t y =\n'
                '  match t:\n'
                '    case A: u\n'
                '    case B n: print n\n'
                '  y\n'
                'print (v 1, v 2, w (Some (P { x = 3 })), f A 4)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]

NATIVE_CASES = [
    {
        'id': 'native_no_bindings',
        "files": {
            'main.pyfun': 'print 1\n',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_empty',
        "files": {
            'main.pyfun': '',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_types_only',
        "files": {
            'main.pyfun': (
                'type T = A | B\n'
                'measure m\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_discard_unit',
        "files": {
            'main.pyfun': (
                'type T = A | B int\n'
                'let f t y =\n'
                '  match t:\n'
                '    case A: ()\n'
                '    case B n: print n\n'
                '  y\n'
                'print (f (B 2) 3)\n'
                'let g o =\n'
                '  match o:\n'
                '    case Some n: ()\n'
                '    case None: print "none"\n'
                '  0\n'
                'print (g None)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_discard_unit_run',
        "files": {
            'main.pyfun': (
                'type T = A | B int\n'
                'let f t y =\n'
                '  match t:\n'
                '    case A: ()\n'
                '    case B n: print n\n'
                '  y\n'
                'print (f (B 2) 3)\n'
                'let g o =\n'
                '  match o:\n'
                '    case Some n: ()\n'
                '    case None: print "none"\n'
                '  0\n'
                'print (g None)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_guards_and_ors',
        "files": {
            'main.pyfun': (
                'type T = A | B int | Pair int int\n'
                'let v t =\n'
                '  let r =\n'
                '    match t:\n'
                '      case A: 1\n'
                '      case B n if n > 0: n\n'
                '      case B _: 0\n'
                '      case Pair _ _: 2\n'
                '  r + 1\n'
                'let w t =\n'
                '  match t:\n'
                '    case Pair (1 | 2) y: y\n'
                '    case Pair (3 | _) _: 0\n'
                '    case B (5 | 6): 5\n'
                '    case _: -1\n'
                'let z t =\n'
                '  match t:\n'
                '    case A: 0\n'
                '    case B n: n\n'
                '    case Pair a b: a + b\n'
                '    case B n if n > 3: 99\n'
                'let f x =\n'
                '  async {\n'
                '    return x + 1\n'
                '  }\n'
                'let g x = fun y -> x + y\n'
                'print (v (B 3))\n'
                'print (w (Pair 2 7))\n'
                'print (w (Pair 9 7))\n'
                'print (w (B 6))\n'
                'print (z (B 4))\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_guards_and_ors_run',
        "files": {
            'main.pyfun': (
                'type T = A | B int | Pair int int\n'
                'let v t =\n'
                '  let r =\n'
                '    match t:\n'
                '      case A: 1\n'
                '      case B n if n > 0: n\n'
                '      case B _: 0\n'
                '      case Pair _ _: 2\n'
                '  r + 1\n'
                'let w t =\n'
                '  match t:\n'
                '    case Pair (1 | 2) y: y\n'
                '    case Pair (3 | _) _: 0\n'
                '    case B (5 | 6): 5\n'
                '    case _: -1\n'
                'let z t =\n'
                '  match t:\n'
                '    case A: 0\n'
                '    case B n: n\n'
                '    case Pair a b: a + b\n'
                '    case B n if n > 3: 99\n'
                'let f x =\n'
                '  async {\n'
                '    return x + 1\n'
                '  }\n'
                'let g x = fun y -> x + y\n'
                'print (v (B 3))\n'
                'print (w (Pair 2 7))\n'
                'print (w (Pair 9 7))\n'
                'print (w (B 6))\n'
                'print (z (B 4))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_nested_or_with_and',
        "files": {
            'main.pyfun': (
                'type T = Pair int int | One int\n'
                'type U = Wrap T | Empty\n'
                'let f u =\n'
                '  match u:\n'
                '    case Wrap (Pair 1 2 | Pair 3 4): "low"\n'
                '    case Wrap _: "other"\n'
                '    case Empty: "empty"\n'
                'print (f (Wrap (Pair 3 4)))\n'
                'print (f (Wrap (One 1)))\n'
                'print (f Empty)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_nested_or_with_and_run',
        "files": {
            'main.pyfun': (
                'type T = Pair int int | One int\n'
                'type U = Wrap T | Empty\n'
                'let f u =\n'
                '  match u:\n'
                '    case Wrap (Pair 1 2 | Pair 3 4): "low"\n'
                '    case Wrap _: "other"\n'
                '    case Empty: "empty"\n'
                'print (f (Wrap (Pair 3 4)))\n'
                'print (f (Wrap (One 1)))\n'
                'print (f Empty)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ladder_nested_tuple_native',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some ((a, _), c): a + c\n'
                '    case None: 0\n'
                'print (f (Some ((1, 2), 3)))\n'
                'print (f None)\n'
                'let g r =\n'
                '  match r:\n'
                '    case Ok (x, _): x\n'
                '    case Error _: -1\n'
                'print (g (Ok (5, "z")))\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'ladder_guarded_last_arm_native',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                '    case Some n if n > 1: 99\n'
                'type W = W (Option int)\n'
                'print (f (Some 3))\n'
                'print (f None)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native_unit_name_arm_and_lookup',
        "files": {
            'main.pyfun': (
                'type T = A | B int\n'
                'type P = { x: int }\n'
                'let m = Map.ofList [(1, "one")]\n'
                'let v k =\n'
                '  let r = match Map.tryFind k m:\n'
                '    case Some _: 1\n'
                '    case None: 0\n'
                '  r * 10\n'
                'let w o = match o:\n'
                '  case Some (P { x }): x\n'
                '  case None: 0\n'
                'let u = ()\n'
                'let f t y =\n'
                '  match t:\n'
                '    case A: u\n'
                '    case B n: print n\n'
                '  y\n'
                'print (v 1, v 2, w (Some (P { x = 3 })), f A 4)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
]

CE_AND_LOOP_CASES = [
    {
        'id': 'seq_no_yield',
        "files": {
            'main.pyfun': (
                'let s = seq {\n'
                '  let x = 1\n'
                '  print x\n'
                '}\n'
                'print (Seq.toList s)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'seq_no_yield_c',
        "files": {
            'main.pyfun': (
                'let s = seq {\n'
                '  let x = 1\n'
                '  print x\n'
                '}\n'
                'print (Seq.toList s)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_for_destructure',
        "files": {
            'main.pyfun': (
                'let pairs = [(1, "a"), (2, "b")]\n'
                'let s = seq {\n'
                '  for (n, c) in pairs:\n'
                '    yield f"{n}{c}"\n'
                '}\n'
                'print (Seq.toList s)\n'
                'let t = seq {\n'
                '  for ((a, b), c) in [((1, 2), 3)]:\n'
                '    yield a + b + c\n'
                '}\n'
                'print (Seq.toList t)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'seq_for_destructure_c',
        "files": {
            'main.pyfun': (
                'let pairs = [(1, "a"), (2, "b")]\n'
                'let s = seq {\n'
                '  for (n, c) in pairs:\n'
                '    yield f"{n}{c}"\n'
                '}\n'
                'print (Seq.toList s)\n'
                'let t = seq {\n'
                '  for ((a, b), c) in [((1, 2), 3)]:\n'
                '    yield a + b + c\n'
                '}\n'
                'print (Seq.toList t)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ce_for_record_target',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'let ps = [P { x = 1, y = 2 }, P { x = 3, y = 4 }]\n'
                'let s = seq {\n'
                '  for P { x, y } in ps:\n'
                '    yield x * y\n'
                '}\n'
                'print (Seq.toList s)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ce_for_record_target_c',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'let ps = [P { x = 1, y = 2 }, P { x = 3, y = 4 }]\n'
                'let s = seq {\n'
                '  for P { x, y } in ps:\n'
                '    yield x * y\n'
                '}\n'
                'print (Seq.toList s)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_call_with_fold_loop',
        "files": {
            'main.pyfun': (
                'let rec_sum n acc xs =\n'
                '  if n == 0 then acc\n'
                '  else\n'
                '    let m = List.fold (fun d x -> Map.add x (x * n) d) Map.empty xs\n'
                '    rec_sum (n - 1) (acc + List.sum (Map.values m)) xs\n'
                'print (rec_sum 3 0 [1, 2])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_call_with_fold_loop_c',
        "files": {
            'main.pyfun': (
                'let rec_sum n acc xs =\n'
                '  if n == 0 then acc\n'
                '  else\n'
                '    let m = List.fold (fun d x -> Map.add x (x * n) d) Map.empty xs\n'
                '    rec_sum (n - 1) (acc + List.sum (Map.values m)) xs\n'
                'print (rec_sum 3 0 [1, 2])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tail_call_with_tuple_fold_loop_run',
        "files": {
            'main.pyfun': (
                'let collect n acc pairs =\n'
                '  if n == 0 then acc\n'
                '  else\n'
                '    let m = List.fold (fun d (k, v) -> Map.add k (v * n) d) Map.empty pairs\n'
                '    collect (n - 1) (acc + List.sum (Map.values m)) pairs\n'
                'print (collect 3 0 [("a", 1), ("b", 2)])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'tail_call_with_tuple_fold_loop_c',
        "files": {
            'main.pyfun': (
                'let collect n acc pairs =\n'
                '  if n == 0 then acc\n'
                '  else\n'
                '    let m = List.fold (fun d (k, v) -> Map.add k (v * n) d) Map.empty pairs\n'
                '    collect (n - 1) (acc + List.sum (Map.values m)) pairs\n'
                'print (collect 3 0 [("a", 1), ("b", 2)])\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

STDLIB_CASES = [
    {
        'id': 'stdlib_misc',
        "files": {
            'main.pyfun': (
                'let m = List.minBy (fun x -> x * x) [3, -1, 2]\n'
                'print m\n'
                'Result.iter (fun x -> print x) (Ok 4)\n'
                'Result.iter (fun x -> print x) (Error "e")\n'
                'let d = Decode.nullable Decode.int\n'
                'let f s = Decode.decodeString d s\n'
                'print (f "null")\n'
                'print (f "3")\n'
                'let fl = Decode.fail "nope"\n'
                'let g s = Decode.decodeString fl s\n'
                'print (g "1")\n'
                'print (List.distinctBy (fun x -> x % 3) [1, 2, 3, 4, 5, 6])\n'
                'print (Set.contains 2 (Set.ofList [1, 2]))\n'
                'print (Map.contains "a" (Map.ofList [("a", 1)]))\n'
                'print (String.startsWith "ab" "abc")\n'
                'print (String.endsWith "bc" "abc")\n'
                'print (List.contains 3 [1, 2, 3])\n'
                'print (List.isEmpty [])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'first_class_stdlib',
        "files": {
            'main.pyfun': (
                'let preds = [List.isEmpty, List.isEmpty]\n'
                'let cont = List.contains\n'
                'let sc = Set.contains\n'
                'let mc = Map.contains\n'
                'let sw = String.startsWith\n'
                'let ew = String.endsWith\n'
                'let mb = List.minBy\n'
                'let ri = Result.iter\n'
                'let db = List.distinctBy\n'
                'let dn = Decode.nullable\n'
                'let df = Decode.fail\n'
                'print (List.map List.isEmpty [[], [1]])\n'
                'print (cont 2 [1, 2])\n'
                'print (sc 2 (Set.ofList [3]))\n'
                'print (mc "k" (Map.ofList [("k", 0)]))\n'
                'print (sw "a" "abc", ew "c" "abc")\n'
                'print (mb (fun x -> 0 - x) [1, 5, 3])\n'
                'ri print (Ok "iterated")\n'
                'print (db String.len ["a", "bb", "c"])\n'
                'print (Decode.decodeString (dn Decode.string) "null")\n'
                'print (Decode.decodeString (df "bad") "1")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'first_class_stdlib_c',
        "files": {
            'main.pyfun': (
                'let preds = [List.isEmpty, List.isEmpty]\n'
                'let cont = List.contains\n'
                'let sc = Set.contains\n'
                'let mc = Map.contains\n'
                'let sw = String.startsWith\n'
                'let ew = String.endsWith\n'
                'let mb = List.minBy\n'
                'let ri = Result.iter\n'
                'let db = List.distinctBy\n'
                'let dn = Decode.nullable\n'
                'let df = Decode.fail\n'
                'print (List.map List.isEmpty [[], [1]])\n'
                'print (cont 2 [1, 2])\n'
                'print (sc 2 (Set.ofList [3]))\n'
                'print (mc "k" (Map.ofList [("k", 0)]))\n'
                'print (sw "a" "abc", ew "c" "abc")\n'
                'print (mb (fun x -> 0 - x) [1, 5, 3])\n'
                'ri print (Ok "iterated")\n'
                'print (db String.len ["a", "bb", "c"])\n'
                'print (Decode.decodeString (dn Decode.string) "null")\n'
                'print (Decode.decodeString (df "bad") "1")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'codec_bool_unit',
        "files": {
            'main.pyfun': (
                'type R = { ok: bool, u: unit, n: int }\n'
                'let r = R { ok = true, u = (), n = 3 }\n'
                'let s = Encode.auto r\n'
                'print s\n'
                'let back = Decode.decodeString Decode.auto s\n'
                'match back:\n'
                '  case Ok v: print (v == r)\n'
                '  case Error e: print e.errorKind\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'codec_bool_unit_c',
        "files": {
            'main.pyfun': (
                'type R = { ok: bool, u: unit, n: int }\n'
                'let r = R { ok = true, u = (), n = 3 }\n'
                'let s = Encode.auto r\n'
                'print s\n'
                'let back = Decode.decodeString Decode.auto s\n'
                'match back:\n'
                '  case Ok v: print (v == r)\n'
                '  case Error e: print e.errorKind\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'codec_imported_ctors',
        "files": {
            'main.pyfun': (
                'import Shapes\n'
                'let wire = Encode.auto Shapes.sample\n'
                'print wire\n'
                'let back = Decode.decodeString Decode.auto wire\n'
                'match back:\n'
                '  case Ok v: print (v == Shapes.sample)\n'
                '  case Error e: print e.errorMessage\n'
            ),
            'shapes.pyfun': (
                'type Shape = Circle float | Dot | Blank\n'
                'let _Dot = 0\n'
                'let sample = [Circle 1.5, Dot, Blank]\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'codec_imported_ctors_c',
        "files": {
            'main.pyfun': (
                'import Shapes\n'
                'let wire = Encode.auto Shapes.sample\n'
                'print wire\n'
                'let back = Decode.decodeString Decode.auto wire\n'
                'match back:\n'
                '  case Ok v: print (v == Shapes.sample)\n'
                '  case Error e: print e.errorMessage\n'
            ),
            'shapes.pyfun': (
                'type Shape = Circle float | Dot | Blank\n'
                'let _Dot = 0\n'
                'let sample = [Circle 1.5, Dot, Blank]\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_spec_edges',
        "files": {
            'main.pyfun': (
                'type Cfg = { key: string, alt: string }\n'
                'let cfg = Cfg { key = "n", alt = "m" }\n'
                'module M =\n'
                '  let parse s = Decode.decodeString Decode.int s\n'
                'let parseInt = Decode.decodeString Decode.int\n'
                'let decs = [Decode.field "a" Decode.int, Decode.field "b" Decode.int]\n'
                'let either s = Decode.decodeString (Decode.oneOf decs) s\n'
                'let byCfg s = Decode.decodeString (Decode.field cfg.key Decode.int) s\n'
                'print (M.parse "5")\n'
                'print (parseInt "6")\n'
                'print (either "{\\"b\\": 2}")\n'
                'print (byCfg "{\\"n\\": 7}")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'decode_spec_edges_c',
        "files": {
            'main.pyfun': (
                'type Cfg = { key: string, alt: string }\n'
                'let cfg = Cfg { key = "n", alt = "m" }\n'
                'module M =\n'
                '  let parse s = Decode.decodeString Decode.int s\n'
                'let parseInt = Decode.decodeString Decode.int\n'
                'let decs = [Decode.field "a" Decode.int, Decode.field "b" Decode.int]\n'
                'let either s = Decode.decodeString (Decode.oneOf decs) s\n'
                'let byCfg s = Decode.decodeString (Decode.field cfg.key Decode.int) s\n'
                'print (M.parse "5")\n'
                'print (parseInt "6")\n'
                'print (either "{\\"b\\": 2}")\n'
                'print (byCfg "{\\"n\\": 7}")\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_escapes_emitted',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let s = "tab\\there\\r\\n"\n'
                'let t = f"tab\\t q\\" back\\\\ cr\\r {x} {{braces}}"\n'
                'print (String.len s)\n'
                'print (String.len t)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'string_escapes_emitted_c',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let s = "tab\\there\\r\\n"\n'
                'let t = f"tab\\t q\\" back\\\\ cr\\r {x} {{braces}}"\n'
                'print (String.len s)\n'
                'print (String.len t)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_escapes_emitted_311',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let s = "tab\\there\\r\\n"\n'
                'let t = f"tab\\t q\\" back\\\\ cr\\r {x} {{braces}}"\n'
                'print (String.len s)\n'
                'print (String.len t)\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--target', '3.11'],
    },
]

LOWERING_ERROR_CASES = [
    {
        'id': 'guard_not_simple',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case x if (match x:\n'
                '        case 0: true\n'
                '        case _: false): "zero"\n'
                '    case _: "other"\n'
                'print (f 0)\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'guard_not_simple_run',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case x if (match x:\n'
                '        case 0: true\n'
                '        case _: false): "zero"\n'
                '    case _: "other"\n'
                'print (f 0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]



@pytest.mark.parametrize("case", EXTERN_CASES, ids=[c["id"] for c in EXTERN_CASES])
def test_extern_boundary_lowering(run, workdir, case):
    """CATCHES: an extern lowering that mishandles the Python boundary: project-mode extern
    bindings (unit-dropping lambdas, pinned kwargs, `...` slots, receiver lambdas), bare
    references to receiver/unit externs, over-application of a kwarg extern, thunk and
    Async callback adaptation, or cold async calls with pinned kwargs."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", BINDING_CASES, ids=[c["id"] for c in BINDING_CASES])
def test_binding_and_closure_lowering(run, workdir, case):
    """CATCHES: wrong lowering of bindings: a partially applied lambda that is not beta-reduced
    (or that captures/shadows wrongly), 2-ary lambda folders, in-file module members
    bound to lambdas or `_`, and module-level blocks that need a private frame for their
    locals."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", MATCH_CASES, ids=[c["id"] for c in MATCH_CASES])
def test_match_lowering(run, workdir, case):
    """CATCHES: match lowering that picks the wrong strategy or binds wrongly: active-pattern
    chains with literal, variable and parameterised arms (and the structural fall-back),
    Option/Result ladders with nested tuple payloads or a guarded trailing arm, lookup
    peepholes in value and return position, eq-predicate specialisations, and
    destructuring parameters."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", NATIVE_CASES, ids=[c["id"] for c in NATIVE_CASES])
def test_native_lowering(run, workdir, case):
    """CATCHES: a `--native` mode that keeps `match` where an isinstance ladder is expected (or
    the reverse), drops a guard, mis-joins nested or-patterns, leaves a discarded temp
    that mypyc rejects, or annotates functions, singletons and aliases differently."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", CE_AND_LOOP_CASES, ids=[c["id"] for c in CE_AND_LOOP_CASES])
def test_computation_expression_and_loop_lowering(run, workdir, case):
    """CATCHES: a `seq` block with no `yield` that is not an empty generator, `for` loops whose
    tuple or record targets unpack wrongly, or a self tail call whose loop rewrite
    breaks an in-place fold loop inside it."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", STDLIB_CASES, ids=[c["id"] for c in STDLIB_CASES])
def test_stdlib_codec_and_literal_lowering(run, workdir, case):
    """CATCHES: missing or wrong helper definitions for first-class stdlib members, derived
    codecs that mishandle bool/unit fields or constructors imported from another module,
    decoder specialisation applied where it must not be (in-file modules, partial
    application, a non-literal oneOf), or string/f-string escapes emitted incorrectly."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", LOWERING_ERROR_CASES, ids=[c["id"] for c in LOWERING_ERROR_CASES])
def test_lowering_errors(run, workdir, case):
    """CATCHES: a compiler that accepts a `case` guard needing statements (it must refuse with
    the lowering error at the item) or that runs such a program anyway."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
