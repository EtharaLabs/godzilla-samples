"""`pyfun run <file>`: the program is compiled, executed with Python, and its output is exact.

The Pyfun programs below were harvested from the project's own end-to-end unit tests (tests/compile.rs, tests/run.rs); bindings the original test inspected are printed with `print` and are
written into the empty working directory as `main.pyfun` before each run. Expected
transcripts (exit code, stdout, stderr) were captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

RUN_CASES = [
    {
        'id': 'e2e_newtype_wrap_unwrap_round_trips',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let uid = UserId "u-1001"\n'
                'let unwrapped =\n'
                '  match uid:\n'
                '    case UserId s: s\n'
                'print unwrapped\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_newtype_literal_payload_selects_arms',
        "files": {
            'main.pyfun': (
                'opaque type Cents = int\n'
                'let describe c =\n'
                '  match c:\n'
                '    case Cents 0: "free"\n'
                '    case Cents n: "costs"\n'
                'let a = describe (Cents 0)\n'
                'let b = describe (Cents 42)\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_mapping_a_newtype_constructor_is_identity',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let total =\n'
                '  ["ab", "c"]\n'
                '  |> List.map UserId\n'
                '  |> List.fold (fun acc u ->\n'
                '    match u:\n'
                '        case UserId s: acc + String.len s) 0\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_newtype_crosses_the_extern_boundary_bare',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'extern pure upperId: UserId -> string = str.upper\n'
                'let r = upperId (UserId "abc")\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_unit_parameters_across_the_boundary',
        "files": {
            'main.pyfun': (
                'extern myAbs: unit -> int -> int = abs\n'
                'extern pick: int -> unit -> int -> int = max\n'
                'let a = myAbs () (-5)\n'
                'let b = pick 3 () 5\n'
                'let fromNeg = myAbs ()\n'
                'let c = fromNeg (-7)\n'
                'let lifted = pick 4\n'
                'let d = lifted () 2\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_kwargs_produce_observable_output',
        "files": {
            'main.pyfun': (
                'extern parseHex : string -> int = int(base=16)\n'
                'let n = parseHex "ff"\n'
                'let m = parseHex "10"\n'
                'print n\n'
                'print m\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_kwarg_slot_produces_observable_output',
        "files": {
            'main.pyfun': (
                'extern parseIn : string -> int -> int = int(base=...)\n'
                'let hex = parseIn "ff" 16\n'
                'let bin = parseIn "1011" 2\n'
                'let ff = parseIn "ff"\n'
                'let also = ff 16\n'
                'print hex\n'
                'print bin\n'
                'print also\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_zip_into_a_map_and_back',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList (List.zip ["a", "b"] [1, 2])\n'
                'let a = Option.withDefault 0 (Map.tryFind "a" m)\n'
                'let n = Map.len m\n'
                'let pairs = Map.toList m\n'
                'print a\n'
                'print n\n'
                'print pairs\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_try_catches_and_recovers',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int = int\n'
                'let orZero s = Result.withDefault 0 (try (parseInt s))\n'
                'let good = orZero "42"\n'
                'let bad = orZero "oops"\n'
                'print good\n'
                'print bad\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_try_exposes_exception_kind_and_message',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int = int\n'
                'let kindOf s =\n'
                '  match try (parseInt s):\n'
                '    case Ok n: "ok"\n'
                '    case Error e: e.errorKind\n'
                'let k = kindOf "nope"\n'
                'let matched =\n'
                '  match try (parseInt "x"):\n'
                '    case Error (Exception { errorKind = "ValueError" }): "caught-value-error"\n'
                '    case _: "other"\n'
                'print k\n'
                'print matched\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_interpolated_strings',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let a = 3\n'
                'let b = 4\n'
                'let p = (1, 2)\n'
                'let greet = f"Hello, {name}!"\n'
                'let math = f"{a} + {b} = {a + b}"\n'
                'let up = f"upper: {String.upper name}"\n'
                'let brace = f"{{literal}} {a}"\n'
                'let point = f"point {p}"\n'
                'print greet\n'
                'print math\n'
                'print up\n'
                'print brace\n'
                'print point\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_mutual_recursion',
        "files": {
            'main.pyfun': (
                'let isEven = fun n -> if n == 0 then true else isOdd (n - 1)\n'
                'let isOdd = fun n -> if n == 0 then false else isEven (n - 1)\n'
                'let a = isEven 10\n'
                'let b = isOdd 10\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_as_pattern',
        "files": {
            'main.pyfun': (
                'let describe = fun n ->\n'
                '    match n:\n'
                '        case 0: 0\n'
                '        case x as v: v\n'
                'let both = fun p ->\n'
                '    match p:\n'
                '        case (a, b) as w: w\n'
                'let a = describe 7\n'
                'let b = both (3, 4)\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_discard_runs_the_effect',
        "files": {
            'main.pyfun': (
                'let go =\n'
                '    let _ = 1 + 2\n'
                '    42\n'
                'print go\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_slice_and_index_of',
        "files": {
            'main.pyfun': (
                'let s = "hello world"\n'
                'let a = String.slice 0 5 s\n'
                'let b = String.slice 6 100 s\n'
                'let c = Option.withDefault (0 - 1) (String.tryIndexOf "world" s)\n'
                'let d = Option.withDefault (0 - 1) (String.tryIndexOf "zzz" s)\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_inlined_stdlib_predicates',
        "files": {
            'main.pyfun': (
                'let a = String.contains "lo" "hello"\n'
                'let b = String.contains "hello" "lo"\n'
                'let c = String.startsWith "he" "hello"\n'
                'let d = String.startsWith "lo" "hello"\n'
                'let e = String.endsWith "lo" "hello"\n'
                'let f = String.endsWith "he" "hello"\n'
                'let g = List.contains 3 [1, 2, 3]\n'
                'let h = List.contains 9 [1, 2, 3]\n'
                'let i = Set.contains 2 (Set.ofList [1, 2, 3])\n'
                'let j = Map.contains 1 (Map.ofList [(1, "a")])\n'
                'let k = Map.contains 9 (Map.ofList [(1, "a")])\n'
                'let l = List.isEmpty (List.filter (fun x -> x > 9) [1, 2, 3])\n'
                'let m = List.isEmpty [1, 2]\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print g\n'
                'print h\n'
                'print i\n'
                'print j\n'
                'print k\n'
                'print l\n'
                'print m\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_stdlib_predicate_partial_application',
        "files": {
            'main.pyfun': (
                'let f = String.contains "lo"\n'
                'let a = f "hello"\n'
                'let b = f "hi"\n'
                'let r = List.filter (String.contains "a") ["cat", "dog", "bat"]\n'
                'let n = List.len r\n'
                'print a\n'
                'print b\n'
                'print n\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_eq_section_specialization_matches_the_helper',
        "files": {
            'main.pyfun': (
                'let a = List.findIndex ((==) 3) [1, 2, 3, 3]\n'
                'let b = List.findIndex ((==) 9) [1, 2, 3]\n'
                'let c = List.find ((==) "b") ["a", "b"]\n'
                'let d = List.find ((==) "z") ["a", "b"]\n'
                'let e = List.exists ((==) 2) [1, 2]\n'
                'let f = List.exists ((==) 5) [1, 2]\n'
                'let g = List.findIndex (fun y -> y == (1, 2)) [(0, 0), (1, 2)]\n'
                'let h = List.findIndex ((==) 0) []\n'
                'let i = List.find ((==) 0.0) [-0.0]\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print g\n'
                'print h\n'
                'print i\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_match_on_lookups_matches_the_helper',
        "files": {
            'main.pyfun': (
                'let look k m =\n'
                '  match Map.tryFind k m:\n'
                '    case Some v: v\n'
                '    case None: "absent"\n'
                'let m = Map.ofList [(1, "one"), (2, "")]\n'
                'let a = look 1 m\n'
                'let b = look 2 m\n'
                'let c = look 3 m\n'
                'let hd xs = match List.head xs:\n'
                '  case Some h: h\n'
                '  case None: -1\n'
                'let d = hd [0, 1]\n'
                'let e = hd []\n'
                'let get i xs = match List.get i xs:\n'
                '  case Some x: x\n'
                '  case None: -1\n'
                'let f = get 0 [0]\n'
                'let g = get 1 [0]\n'
                'let h = get (0 - 1) [0]\n'
                'let ok = Map.ofList [("k", [])]\n'
                'let i = match Map.tryFind "k" ok:\n'
                '  case Some xs: List.len xs\n'
                '  case None: -1\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print g\n'
                'print h\n'
                'print i\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_exponentiation',
        "files": {
            'main.pyfun': (
                'let a = 2.0 ** 8.0\n'
                'let b = 2.0 ** 3.0 ** 2.0\n'
                'let c = 2.0 ** -1.0\n'
                'let d = -2.0 ** 2.0\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_bind_filter_to_result',
        "files": {
            'main.pyfun': (
                'let half = fun x -> if x % 2 == 0 then Some (x // 2) else None\n'
                'let a = Option.withDefault 0 (Option.bind half (Some 8))\n'
                'let b = Option.withDefault 0 (Option.bind half (Some 7))\n'
                'let c = Option.withDefault 0 (Option.filter (fun x -> x > 5) (Some 8))\n'
                'let d = Option.withDefault 0 (Option.filter (fun x -> x > 5) (Some 2))\n'
                'let e = Result.withDefault 0 (Option.toResult 0 (Some 42))\n'
                'let f = Result.isError (Option.toResult 0 None)\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_unit_aware_sqrt',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = sqrt 16.0<m^2>\n'
                'let hyp = sqrt (2.0 * 2.0 + 2.0 * 2.0)\n'
                'print side\n'
                'print hyp\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_numeric_conversions',
        "files": {
            'main.pyfun': (
                'let a = round 3.7\n'
                'let b = floor 3.7\n'
                'let c = ceil 3.2\n'
                'let d = truncate 3.9\n'
                'let e = floor (-2.5)\n'
                'let f = Option.withDefault 0.0 (String.toFloat "3.5")\n'
                'let g = Option.withDefault 0.0 (String.toFloat "nope")\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print g\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_escapes',
        "files": {
            'main.pyfun': (
                'let crlf = String.len "a\\r\\nb"\n'
                'let emoji = String.len "hi \\u{1F600}"\n'
                'let accent = String.len "caf\\u{e9}"\n'
                'print crlf\n'
                'print emoji\n'
                'print accent\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_digit_separators_and_bases',
        "files": {
            'main.pyfun': (
                'let a = 1_000_000\n'
                'let b = 0xFF\n'
                'let c = 0o17\n'
                'let d = 0b1010\n'
                'let e = 0xDEAD_BEEF\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_scientific_notation',
        "files": {
            'main.pyfun': (
                'let a = 1e3\n'
                'let b = 2.5e-1\n'
                'let c = 1e3 + 1.0\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_choose_and_collect',
        "files": {
            'main.pyfun': (
                'let xs = [1, 2, 3]\n'
                'let a = List.choose (fun x -> if x > 1 then Some (x * 10) else None) xs\n'
                'let b = List.collect (fun x -> [x, x]) xs\n'
                'let c = List.collect (fun x -> x) [[1], [2, 3]]\n'
                'let keepOdd = List.choose (fun x -> if x % 2 == 1 then Some x else None)\n'
                'let d = keepOdd xs\n'
                'let e = xs |> List.collect (fun x -> [x, 0])\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_completeness_ops',
        "files": {
            'main.pyfun': (
                'let xs = [3, 1, 2]\n'
                'let a = Option.withDefault 0 (List.get 0 xs)\n'
                'let b = Option.withDefault 0 (List.get 9 xs)\n'
                'let c = List.contains 2 xs\n'
                'let d = List.concat xs [4]\n'
                'let e = List.sort xs\n'
                'let f = Option.withDefault 0 (List.find (fun x -> x > 1) xs)\n'
                'let g = List.isEmpty []\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print g\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_modulo',
        "files": {
            'main.pyfun': (
                'let a = 10 % 3\n'
                'let b = 5.5 % 2.0\n'
                'let c = -7 % 3\n'
                'let d = (%) 17 5\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_non_ascii_string_length',
        "files": {
            'main.pyfun': (
                'let n = String.len "café"\n'
                'let m = String.len f"→🎉 {n}"\n'
                'print n\n'
                'print m\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_chained_comparisons',
        "files": {
            'main.pyfun': (
                'let a = 1 < 2 < 3\n'
                'let b = 3 < 2 < 1\n'
                'let c =\n'
                '    let x = 5\n'
                '    1 < x < 10\n'
                'let d = 1 <= 1 < 2\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_unary_minus',
        "files": {
            'main.pyfun': (
                'let a = -5\n'
                'let b = abs (-5)\n'
                'let c = 2 * -3\n'
                'let d = -(4 + 1)\n'
                'let sign =\n'
                '    match -1:\n'
                '        case -1: "neg"\n'
                '        case _: "other"\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print sign\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_operator_sections',
        "files": {
            'main.pyfun': (
                'let mul = (*)\n'
                'let double = (*) 2\n'
                'let total = List.fold (+) 0 [1, 2, 3, 4]\n'
                'let cmp = (<) 2 3\n'
                'let a = mul 3 4\n'
                'let b = double 5\n'
                'print a\n'
                'print b\n'
                'print total\n'
                'print cmp\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_function_composition_both_directions',
        "files": {
            'main.pyfun': (
                'let inc x = x + 1\n'
                'let double x = x * 2\n'
                'let ltr = inc >> double\n'
                'let rtl = inc << double\n'
                'let a = ltr 3\n'
                'let b = rtl 3\n'
                'let piped = 5 |> inc >> double\n'
                'let mapped = List.map (double >> inc) [1, 2, 3]\n'
                'let clean = (String.strip >> String.upper) "  hi  "\n'
                'print a\n'
                'print b\n'
                'print piped\n'
                'print mapped\n'
                'print clean\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_raw_string_backslashes_are_literal',
        "files": {
            'main.pyfun': (
                'let path_len = String.len r"a\\nb"\n'
                'let quote_len = String.len r"a\\"b"\n'
                'print path_len\n'
                'print quote_len\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_interpolation_debug_holes',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let y = 4\n'
                'let a = f"{x=}"\n'
                'let b = f"{x = }"\n'
                'let c = f"{x + y=}"\n'
                'let d = f"{x == y}"\n'
                'let e = f"{x <= y}"\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_interpolation_hole_with_nested_string',
        "files": {
            'main.pyfun': (
                'let s = "a}b"\n'
                'let r = f"contains: {String.contains "}" s}"\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_operations',
        "files": {
            'main.pyfun': (
                'let g = String.concat "Hello, " "World"\n'
                'let up = String.upper g\n'
                'let n = String.len g\n'
                'let parts = String.split ", " g\n'
                'let joined = String.join "/" parts\n'
                'let has = String.contains "World" g\n'
                'let r = String.replace "o" "0" g\n'
                'print up\n'
                'print n\n'
                'print parts\n'
                'print joined\n'
                'print has\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_to_int_parses_or_yields_none',
        "files": {
            'main.pyfun': (
                'let ok = Option.withDefault 0 (String.toInt "41")\n'
                'let bad = Option.withDefault 0 (String.toInt "nope")\n'
                'let neg = Option.withDefault 0 (String.toInt "-5")\n'
                'print ok\n'
                'print bad\n'
                'print neg\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'adt_match_args_work_positionally',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let unwrap o =\n'
                '  match o:\n'
                '    case Has v: v\n'
                '    case Empty: 0\n'
                'let r = unwrap (Has 7)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'adt_classes_get_structural_eq',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let a = Has 1 == Has 1\n'
                'let b = Has 1 == Has 2\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'adt_classes_get_structural_hash',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let s = Set.ofList [Red, Red, Green]\n'
                'let n = Set.len s\n'
                'let hasRed = Set.contains Red s\n'
                'let hasBlue = Set.contains Blue s\n'
                'print n\n'
                'print hasRed\n'
                'print hasBlue\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_sort_a_sum_type_by_variant_order',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let ordered = List.sort [Blue, Red, Green]\n'
                'let a = Red < Green\n'
                'let b = Green < Blue\n'
                'print ordered\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_sum_orders_by_variant_then_field',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let a = Circle 1.0 < Circle 2.0\n'
                'let b = Circle 9.0 < Rect 0.0 0.0\n'
                'let c = Rect 1.0 2.0 < Rect 1.0 3.0\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_sort_records_and_tuples',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let pts = List.sort [Point { x = 2, y = 0 }, Point { x = 1, y = 9 }, Point { x = 1, y = 3 }]\n'
                'let tups = List.sort [(1, 3), (1, 2), (0, 9)]\n'
                'print pts\n'
                'print tups\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_sort_a_recursive_type',
        "files": {
            'main.pyfun': (
                'type Tree = Leaf int | Node Tree Tree\n'
                'let ordered = List.sort [Node (Leaf 2) (Leaf 3), Leaf 5, Leaf 1]\n'
                'print ordered\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_set_traversals',
        "files": {
            'main.pyfun': (
                'let s = Set.ofList [3, 1, 4, 1, 5]\n'
                'let empty = Set.isEmpty (Set.ofList [])\n'
                'let full = Set.isEmpty s\n'
                'let halved = List.sort (Set.toList (Set.map (fun x -> x % 2) s))\n'
                'let kept = List.sort (Set.toList (Set.filter (fun x -> x > 2) s))\n'
                'let total = Set.fold (fun acc x -> acc + x) 0 s\n'
                'let any = Set.exists (fun x -> x > 4) s\n'
                'let all = Set.forall (fun x -> x > 0) s\n'
                'let sub = Set.isSubset (Set.ofList [1, 3]) s\n'
                'let sup = Set.isSuperset s (Set.ofList [1, 3])\n'
                'let biggest = Set.max s\n'
                'let smallest = Set.min s\n'
                'let noMax = Set.max (Set.ofList [])\n'
                'let split = Set.partition (fun x -> x > 2) s\n'
                'let passing = List.sort (Set.toList (fst split))\n'
                'let failing = List.sort (Set.toList (snd split))\n'
                'print empty\n'
                'print full\n'
                'print halved\n'
                'print kept\n'
                'print total\n'
                'print any\n'
                'print all\n'
                'print sub\n'
                'print sup\n'
                'print biggest\n'
                'print smallest\n'
                'print noMax\n'
                'print passing\n'
                'print failing\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_map_traversals',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "one"), (2, "two"), (3, "three")]\n'
                'let empty = Map.isEmpty (Map.ofList [])\n'
                'let full = Map.isEmpty m\n'
                'let shouted = Map.toList (Map.map (fun k v -> String.concat v "!") m)\n'
                'let kept = Map.toList (Map.filter (fun k v -> k > 1) m)\n'
                'let keySum = Map.fold (fun acc k v -> acc + k) 0 m\n'
                'let any = Map.exists (fun k v -> v == "two") m\n'
                'let all = Map.forall (fun k v -> k > 0) m\n'
                'let joined = Map.toList (Map.union m (Map.ofList [(3, "THREE"), (4, "four")]))\n'
                'let split = Map.partition (fun k v -> k > 1) m\n'
                'let passing = Map.toList (fst split)\n'
                'let failing = Map.toList (snd split)\n'
                'print empty\n'
                'print full\n'
                'print shouted\n'
                'print kept\n'
                'print keySum\n'
                'print any\n'
                'print all\n'
                'print joined\n'
                'print passing\n'
                'print failing\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_sweep',
        "files": {
            'main.pyfun': (
                'let empty = String.isEmpty ""\n'
                'let full = String.isEmpty "a"\n'
                'let at = String.get 1 "abc"\n'
                'let past = String.get 9 "abc"\n'
                'let thrice = String.repeat 3 "ab"\n'
                'let none = String.repeat 0 "ab"\n'
                'let left = String.trimStart "  hi  "\n'
                'let right = String.trimEnd "  hi  "\n'
                'let lines = String.splitLines "a\\nb\\nc\\n"\n'
                'let backwards = String.rev "abc"\n'
                'let joined = String.ofList ["a", "b", "c"]\n'
                'let roundTrip = String.ofList (String.toList "xyz")\n'
                'print empty\n'
                'print full\n'
                'print at\n'
                'print past\n'
                'print thrice\n'
                'print none\n'
                'print left\n'
                'print right\n'
                'print lines\n'
                'print backwards\n'
                'print joined\n'
                'print roundTrip\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_deferred_field_reads_the_right_attribute',
        "files": {
            'main.pyfun': (
                'type Placed = { row: int, col: int, letter: string }\n'
                'type Cell = { row: int, col: int, letter: string, blank: bool }\n'
                'let describe c =\n'
                '    let l = c.letter\n'
                '    let flag = c.blank\n'
                '    f"{l}/{flag}"\n'
                'let out = describe (Cell { row = 1, col = 2, letter = "A", blank = false })\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_the_audit_members',
        "files": {
            'main.pyfun': (
                'let xs = [1, 2, 3, 1, 2]\n'
                'let taken = List.takeWhile (fun x -> x < 3) xs\n'
                'let dropped = List.dropWhile (fun x -> x < 3) xs\n'
                'let desc = List.sortByDescending (fun x -> x) xs\n'
                'let counted = List.countBy (fun x -> x % 2) xs\n'
                'let uniqBy = Seq.toList (Seq.distinctBy (fun x -> x % 2) (Seq.ofList xs))\n'
                'let copies = Seq.toList (Seq.replicate 3 "a")\n'
                'let none = Seq.toList Seq.empty\n'
                'let at = Seq.get 2 (Seq.ofList xs)\n'
                'let final = Seq.last (Seq.ofList xs)\n'
                'let doubled = Seq.sumBy (fun x -> x * 2) (Seq.ofList xs)\n'
                'let biggest = Seq.max (Seq.ofList xs)\n'
                'let smallest = Seq.min (Seq.ofList xs)\n'
                'let joined = Seq.reduce (fun a b -> a + b) (Seq.ofList xs)\n'
                'let holds = Option.forall (fun x -> x > 0) (Some 1)\n'
                'let has = Option.contains 1 (Some 1)\n'
                'let okHas = Result.contains 1 (Ok 1)\n'
                'let negative = sign (-5)\n'
                'let zero = sign 0\n'
                'let positive = sign 42\n'
                'print taken\n'
                'print dropped\n'
                'print desc\n'
                'print counted\n'
                'print uniqBy\n'
                'print copies\n'
                'print none\n'
                'print at\n'
                'print final\n'
                'print doubled\n'
                'print biggest\n'
                'print smallest\n'
                'print joined\n'
                'print holds\n'
                'print has\n'
                'print okHas\n'
                'print negative\n'
                'print zero\n'
                'print positive\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_sweep',
        "files": {
            'main.pyfun': (
                'let some1 = Some 1\n'
                'let some2 = Some 2\n'
                'let none = List.head (List.drop 9 [1])\n'
                'let both = Option.map2 (fun a b -> a + b) some1 some2\n'
                'let missing = Option.map2 (fun a b -> a + b) some1 none\n'
                'let kept = Option.orElse some2 some1\n'
                'let fellBack = Option.orElse some2 none\n'
                'let flat = Option.flatten (Some (Some 5))\n'
                'let flatNone = Option.flatten (Some none)\n'
                'let listed = Option.toList some1\n'
                'let empty = Option.toList none\n'
                'let holds = Option.exists (fun x -> x > 0) some1\n'
                'let holdsNot = Option.exists (fun x -> x > 0) none\n'
                'print both\n'
                'print missing\n'
                'print kept\n'
                'print fellBack\n'
                'print flat\n'
                'print flatNone\n'
                'print listed\n'
                'print empty\n'
                'print holds\n'
                'print holdsNot\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_result_sweep',
        "files": {
            'main.pyfun': (
                'let ok1 = Ok 1\n'
                'let ok2 = Ok 2\n'
                'let bad = Error "boom"\n'
                'let both = Result.map2 (fun a b -> a + b) ok1 ok2\n'
                'let failed = Result.map2 (fun a b -> a + b) bad ok2\n'
                'let kept = Result.orElse ok2 ok1\n'
                'let fellBack = Result.orElse ok2 bad\n'
                'let listed = Result.toList ok1\n'
                'let empty = Result.toList bad\n'
                'print both\n'
                'print failed\n'
                'print kept\n'
                'print fellBack\n'
                'print listed\n'
                'print empty\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_lazy_members',
        "files": {
            'main.pyfun': (
                'let dropped = Seq.toList (Seq.drop 2 (Seq.ofList [1, 2, 3, 4]))\n'
                'let taken = Seq.toList (Seq.takeWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))\n'
                'let skipped = Seq.toList (Seq.dropWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))\n'
                'let joined = Seq.toList (Seq.concat (Seq.ofList [1, 2]) (Seq.ofList [3]))\n'
                'let flat = Seq.toList (Seq.flatten (Seq.ofList [Seq.ofList [1, 2], Seq.ofList [3]]))\n'
                'let mapped = Seq.toList (Seq.collect (fun x -> Seq.ofList [x, x]) (Seq.ofList [1, 2]))\n'
                'let zipped = Seq.toList (Seq.zip (Seq.ofList [1, 2]) (Seq.ofList ["a", "b"]))\n'
                'let ix = Seq.toList (Seq.indexed (Seq.ofList ["a", "b"]))\n'
                'let uniq = Seq.toList (Seq.distinct (Seq.ofList [1, 1, 2, 1, 3]))\n'
                'let pairs = Seq.toList (Seq.pairwise (Seq.ofList [1, 2, 3]))\n'
                'let built = Seq.toList (Seq.init 4 (fun i -> i * i))\n'
                'print dropped\n'
                'print taken\n'
                'print skipped\n'
                'print joined\n'
                'print flat\n'
                'print mapped\n'
                'print zipped\n'
                'print ix\n'
                'print uniq\n'
                'print pairs\n'
                'print built\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_can_be_endless',
        "files": {
            'main.pyfun': (
                'let doubles = Seq.toList (Seq.take 5 (Seq.initInfinite (fun i -> i * 2)))\n'
                'let powers = Seq.toList (Seq.take 4 (Seq.unfold (fun s -> if s > 100 then None else Some (s, s * 2)) 1))\n'
                'let firstBig = Seq.find (fun x -> x > 6) (Seq.initInfinite (fun i -> i * 2))\n'
                'print doubles\n'
                'print powers\n'
                'print firstBig\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_consuming_members',
        "files": {
            'main.pyfun': (
                'let first = Seq.head (Seq.ofList [7, 8])\n'
                'let none = Seq.head (Seq.ofList [])\n'
                'let empty = Seq.isEmpty (Seq.ofList [])\n'
                'let full = Seq.isEmpty (Seq.ofList [1])\n'
                'let n = Seq.len (Seq.ofList [1, 2, 3])\n'
                'let any = Seq.exists (fun x -> x > 2) (Seq.ofList [1, 2, 3])\n'
                'let all = Seq.forall (fun x -> x > 0) (Seq.ofList [1, 2, 3])\n'
                'let has = Seq.contains 2 (Seq.ofList [1, 2, 3])\n'
                'let total = Seq.sum (Seq.ofList [1, 2, 3])\n'
                'let found = Seq.find (fun x -> x > 1) (Seq.ofList [1, 2, 3])\n'
                'let missing = Seq.find (fun x -> x > 9) (Seq.ofList [1, 2, 3])\n'
                'print first\n'
                'print none\n'
                'print empty\n'
                'print full\n'
                'print n\n'
                'print any\n'
                'print all\n'
                'print has\n'
                'print total\n'
                'print found\n'
                'print missing\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_access_and_slicing',
        "files": {
            'main.pyfun': (
                'let xs = [3, 1, 4, 1, 5]\n'
                'let first = List.head xs\n'
                'let none = List.head (List.drop 9 [1])\n'
                'let rest = List.tail xs\n'
                'let taken = List.take 2 xs\n'
                'let dropped = List.drop 3 xs\n'
                'let overTake = List.take 99 xs\n'
                'let negTake = List.take (-1) xs\n'
                'let split = List.splitAt 2 xs\n'
                'print first\n'
                'print none\n'
                'print rest\n'
                'print taken\n'
                'print dropped\n'
                'print overTake\n'
                'print negTake\n'
                'print split\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_transform_query_and_order',
        "files": {
            'main.pyfun': (
                'let xs = [3, 1, 4, 1, 5]\n'
                'let summed = List.map2 (fun a b -> a + b) [1, 2, 3] [10, 20]\n'
                'let ix = List.indexed ["a", "b"]\n'
                'let any = List.exists (fun x -> x > 4) xs\n'
                'let all = List.forall (fun x -> x > 0) xs\n'
                'let at = List.findIndex (fun x -> x == 4) xs\n'
                'let missing = List.findIndex (fun x -> x == 99) xs\n'
                'let desc = List.sortDescending xs\n'
                'let uniq = List.distinct xs\n'
                'let grouped = List.groupBy (fun x -> x % 2) [1, 2, 3, 4]\n'
                'print summed\n'
                'print ix\n'
                'print any\n'
                'print all\n'
                'print at\n'
                'print missing\n'
                'print desc\n'
                'print uniq\n'
                'print grouped\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_aggregate_structure_and_windows',
        "files": {
            'main.pyfun': (
                'let xs = [3, 1, 4, 1, 5]\n'
                'let biggest = List.max xs\n'
                'let smallest = List.min xs\n'
                'let noMax = List.max (List.drop 9 [1])\n'
                'let doubled = List.sumBy (fun x -> x * 2) [1, 2, 3]\n'
                'let mean = List.average [1.0, 2.0, 4.0]\n'
                'let joined = List.reduce (fun a b -> a + b) [1, 2, 3]\n'
                'let split = List.partition (fun x -> x > 2) xs\n'
                'let apart = List.unzip (List.zip [1, 2] ["a", "b"])\n'
                'let flat = List.flatten [[1, 2], [3]]\n'
                'let squares = List.init 4 (fun i -> i * i)\n'
                'let copies = List.replicate 3 "x"\n'
                'let updated = List.updateAt 1 99 [1, 2, 3]\n'
                'let untouched = List.updateAt 9 99 [1, 2, 3]\n'
                'let inserted = List.insertAt 1 99 [1, 2, 3]\n'
                'let removed = List.removeAt 1 [1, 2, 3]\n'
                'let pairs = List.pairwise [1, 2, 3]\n'
                'let windows = List.windowed 2 [1, 2, 3]\n'
                'let chunks = List.chunkBySize 2 [1, 2, 3]\n'
                'print biggest\n'
                'print smallest\n'
                'print noMax\n'
                'print doubled\n'
                'print mean\n'
                'print joined\n'
                'print split\n'
                'print apart\n'
                'print flat\n'
                'print squares\n'
                'print copies\n'
                'print updated\n'
                'print untouched\n'
                'print inserted\n'
                'print removed\n'
                'print pairs\n'
                'print windows\n'
                'print chunks\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fst_and_snd',
        "files": {
            'main.pyfun': (
                'let pairs = List.zip [1, 2] ["a", "b"]\n'
                'let firsts = List.map fst pairs\n'
                'let seconds = List.map snd pairs\n'
                'let one = fst (1, "one")\n'
                'print firsts\n'
                'print seconds\n'
                'print one\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_record_parameters_round_trip',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int, col: int, letter: string }\n'
                'type Pair = { left: Cell, right: Cell }\n'
                'let describe (Cell { letter, row }) = letter\n'
                'let leftLetter (Pair { left = Cell { letter } }) = letter\n'
                'let both (Pair { left, right }) = (left.letter, right.letter)\n'
                'let a = Cell { row = 1, col = 2, letter = "A" }\n'
                'let b = Cell { row = 3, col = 4, letter = "B" }\n'
                'let p = Pair { left = a, right = b }\n'
                'let one = describe a\n'
                'let deep = leftLetter p\n'
                'let pairOf = both p\n'
                'print one\n'
                'print deep\n'
                'print pairOf\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_tuple_parameters_round_trip',
        "files": {
            'main.pyfun': (
                'let tileScore (t, sq) = t * sq\n'
                'let swap (a, b) = (b, a)\n'
                'let nested ((a, b), c) = a + b + c\n'
                'let const42 _ = 42\n'
                'let pairs = List.zip [1, 2, 3] [10, 20, 30]\n'
                'let scores = List.map tileScore pairs\n'
                'let total = List.fold (fun acc (a, b) -> acc + a * b) 0 pairs\n'
                'let swapped = swap (1, 2)\n'
                'let deep = nested ((1, 2), 3)\n'
                'let ignored = const42 "anything"\n'
                'print scores\n'
                'print total\n'
                'print swapped\n'
                'print deep\n'
                'print ignored\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_tuple_construct_and_destructure',
        "files": {
            'main.pyfun': (
                'let swap p =\n'
                '  match p:\n'
                '    case (a, b): (b, a)\n'
                'let fst t =\n'
                '  match t:\n'
                '    case (a, _): a\n'
                'let pair = (10, 20)\n'
                'let s = swap pair\n'
                'let first = fst pair\n'
                'print s\n'
                'print first\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_tuple_pattern',
        "files": {
            'main.pyfun': (
                'let f t =\n'
                '  match t:\n'
                '    case ((a, b), c): a + b + c\n'
                'let r = f ((1, 2), 3)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_suffix_and_mid_star_patterns',
        "files": {
            'main.pyfun': (
                'let lastOr fallback xs =\n'
                '  match xs:\n'
                '    case [*_, last]: last\n'
                '    case []: fallback\n'
                'let bounds xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x]: x\n'
                '    case [first, *mid, last]: first + last + List.len mid\n'
                'let a = lastOr 0 [5, 6, 7]\n'
                'let b = lastOr 9 []\n'
                'let c = bounds [1, 2, 3, 4]\n'
                'let d = bounds [7]\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_sum_with_sequence_patterns',
        "files": {
            'main.pyfun': (
                'let sum xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x, *rest]: x + sum rest\n'
                'let total = sum [1, 2, 3, 4]\n'
                'let empty = sum []\n'
                'print total\n'
                'print empty\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_fixed_length_and_nested_patterns',
        "files": {
            'main.pyfun': (
                'let describe xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x]: 1\n'
                '    case [x, y]: 2\n'
                '    case [x, y, *rest]: 3\n'
                'let head xs =\n'
                '  match xs:\n'
                '    case [Some x, *rest]: x\n'
                '    case _: 0\n'
                'let a = describe [10, 20, 30]\n'
                'let b = describe [7]\n'
                'let c = describe []\n'
                'let d = head [Some 42, None]\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_record_pattern_match',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let classify p =\n'
                '  match p:\n'
                '    case Point { x = 0, y = 0 }: 1\n'
                '    case Point { x = 0 }: 2\n'
                '    case Point { x, y }: x + y\n'
                'let a = classify (Point { x = 0, y = 0 })\n'
                'let b = classify (Point { x = 0, y = 9 })\n'
                'let c = classify (Point { x = 3, y = 4 })\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_record_and_constructor_pattern',
        "files": {
            'main.pyfun': (
                'type Box = { item: Option int, tag: bool }\n'
                'let f b =\n'
                '  match b:\n'
                '    case Box { item = Some n, tag = true }: n\n'
                '    case Box { item = Some n }: n + 100\n'
                '    case _: 0\n'
                'let a = f (Box { item = Some 5, tag = true })\n'
                'let b = f (Box { item = Some 5, tag = false })\n'
                'let c = f (Box { item = None, tag = true })\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_deep_exhaustive_match_without_wildcard',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some true: 1\n'
                '    case Some false: 2\n'
                '    case None: 3\n'
                'let a = f (Some true)\n'
                'let b = f (Some false)\n'
                'let c = f None\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_closure_reassigns_captured_mut',
        "files": {
            'main.pyfun': (
                'let counter =\n'
                '  let mut n = 0\n'
                '  let bump x =\n'
                '    n <- n + x\n'
                '    n\n'
                '  let a = bump 5\n'
                '  bump 3\n'
                'print counter\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_nonlocal_closure_in_a_function',
        "files": {
            'main.pyfun': (
                'let make base =\n'
                '  let mut n = base\n'
                '  let bump x =\n'
                '    n <- n + x\n'
                '    n\n'
                '  let a = bump 5\n'
                '  bump 3\n'
                'let r = make 100\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_self_tail_call_recurses_past_the_stack_limit',
        "files": {
            'main.pyfun': (
                'let countdown n =\n'
                '  if n == 0 then "done"\n'
                '  else countdown (n - 1)\n'
                'let sumTo n acc =\n'
                '  if n == 0 then acc\n'
                '  else sumTo (n - 1) (acc + n)\n'
                'let deep = countdown 50000\n'
                'let total = sumTo 100000 0\n'
                'print deep\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_over_a_parameter_keeps_per_frame_values',
        "files": {
            'main.pyfun': (
                'let collect n acc =\n'
                '  if n == 0 then acc\n'
                '  else collect (n - 1) (List.concat acc [fun k -> n])\n'
                'let fns = collect 3 []\n'
                'let values = List.map (fun f -> f 0) fns\n'
                'print values\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_recursive_functions',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)\n'
                'let fib n =\n'
                '  if n < 2 then n\n'
                '  else fib (n - 1) + fib (n - 2)\n'
                'let a = fact 6\n'
                'let b = fib 10\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_currying_full_partial_and_over_application',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let inc = add 1\n'
                'let twice f x = f (f x)\n'
                'let r1 = add 1 2\n'
                'let r2 = inc 41\n'
                'let r3 = twice inc 5\n'
                'print r1\n'
                'print r2\n'
                'print r3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_pipe_and_composition',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let inc = add 1\n'
                'let compose = fun f g x -> f (g x)\n'
                'let r = 4 |> inc |> inc\n'
                'let r2 = (compose inc inc) 10\n'
                'print r\n'
                'print r2\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_backward_pipe',
        "files": {
            'main.pyfun': (
                'let inc n = n + 1\n'
                'let twice n = n * 2\n'
                'let a = inc <| 5\n'
                'let b = inc <| twice <| 5\n'
                'let c = twice <| inc 5\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_elif_chain_selects_the_right_branch',
        "files": {
            'main.pyfun': (
                'let grade n =\n'
                '  if n >= 90 then "A"\n'
                '  elif n >= 80 then "B"\n'
                '  elif n >= 70 then "C"\n'
                '  else "F"\n'
                'let a = grade 95\n'
                'let b = grade 85\n'
                'let c = grade 72\n'
                'let f = grade 50\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print f\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_if_and_match',
        "files": {
            'main.pyfun': (
                'let classify n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case 1: "one"\n'
                '    case _: "many"\n'
                'let r1 = classify 0\n'
                'let r2 = classify 7\n'
                'let r3 = if true then 10 else 20\n'
                'print r1\n'
                'print r2\n'
                'print r3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_blocks_in_match_arms_and_if_branches',
        "files": {
            'main.pyfun': (
                'let classify n =\n'
                '  match n:\n'
                '    case 0:\n'
                '      let base = 100\n'
                '      base\n'
                '    case _:\n'
                '      let mut acc = n\n'
                '      acc <- acc * 2\n'
                '      acc\n'
                'let absdiff a b =\n'
                '  if a > b then\n'
                '      let d = a - b\n'
                '      d\n'
                '  else\n'
                '      let d = b - a\n'
                '      d\n'
                'let r1 = classify 0\n'
                'let r2 = classify 5\n'
                'let r3 = absdiff 3 10\n'
                'print r1\n'
                'print r2\n'
                'print r3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_block_in_lambda_body',
        "files": {
            'main.pyfun': (
                'let doubler = fun x ->\n'
                '  let y = x + x\n'
                '  y\n'
                'let r = doubler 21\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_division_operators_match_python',
        "files": {
            'main.pyfun': (
                'let q = 7 / 2\n'
                'print q\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_division_operators_match_python_2',
        "files": {
            'main.pyfun': (
                'let d = 7 // 2\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_match_in_value_position_is_hoisted',
        "files": {
            'main.pyfun': (
                'let r = (match 1: case 1: 10 case _: 20) + 5\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_adt_construction_and_match',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let unwrap o = match o: case Some v: v case None: 0\n'
                'let r1 = unwrap (Some 5)\n'
                'let r2 = unwrap None\n'
                'let rank c = match c: case Red: 1 case Green: 2 case Blue: 3\n'
                'let r3 = rank Green\n'
                'print r1\n'
                'print r2\n'
                'print r3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_records_construct_access_and_update',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 3, y = 4 }\n'
                'let moved = { p with x = 10 }\n'
                'let sx = p.x\n'
                'let sy = moved.y\n'
                'let mx = moved.x\n'
                'let sumxy r = r.x + r.y\n'
                'let total = sumxy p\n'
                'print sx\n'
                'print sy\n'
                'print mx\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_record_update',
        "files": {
            'main.pyfun': (
                'type Inner = { a: int, b: int }\n'
                'type Outer = { inner: Inner, tag: string }\n'
                'let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }\n'
                'let o2 = { o with inner.a = 99 }\n'
                'let both = { o with inner.a = 10, tag = "y" }\n'
                'let na = o2.inner.a\n'
                'let nb = o2.inner.b\n'
                'let nt = o2.tag\n'
                'let ba = both.inner.a\n'
                'let bt = both.tag\n'
                'print na\n'
                'print nb\n'
                'print nt\n'
                'print ba\n'
                'print bt\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_polymorphic_record_field',
        "files": {
            'main.pyfun': (
                'type Box a = { item: a }\n'
                'let mk v = Box { item = v }\n'
                'let i = (mk 42).item\n'
                'let s = (mk "hi").item\n'
                'print i\n'
                'print s\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_blocks_and_mutation',
        "files": {
            'main.pyfun': (
                'let sum3 a b c =\n'
                '    let mut acc = 0\n'
                '    acc <- acc + a\n'
                '    acc <- acc + b\n'
                '    acc <- acc + c\n'
                '    acc\n'
                'let nested x =\n'
                '    let y =\n'
                '        let mut t = x\n'
                '        t <- t * 2\n'
                '        t\n'
                '    y + 1\n'
                'let r1 = sum3 1 2 3\n'
                'let r2 = nested 10\n'
                'print r1\n'
                'print r2\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_top_level_mutation',
        "files": {
            'main.pyfun': (
                'let mut counter = 0\n'
                'counter <- counter + 1\n'
                'counter <- counter + 5\n'
                'print counter\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_units_compute_after_erasure',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let dist = 100<m>\n'
                'let time = 10<s>\n'
                'let speed = dist / time\n'
                'print speed\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_derived_measure_aliases_erase',
        "files": {
            'main.pyfun': (
                'measure kg\n'
                'measure m\n'
                'measure s\n'
                'measure N = kg m / s^2\n'
                'measure Pa = N / m^2\n'
                'let force = 10<N>\n'
                'let area = 2<m^2>\n'
                'let pressure = force / area\n'
                'print force\n'
                'print pressure\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_result_ce_binds_and_short_circuits',
        "files": {
            'main.pyfun': (
                'let safe ok v = result { let! x = if ok then Ok v else Error 9  return (x + 1) }\n'
                'let unwrap r = match r: case Ok n: n case Error e: e\n'
                'let r1 = unwrap (safe true 10)\n'
                'let r2 = unwrap (safe false 10)\n'
                'print r1\n'
                'print r2\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_user_monad_ce_binds_and_short_circuits',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f = match m: case Some x: f x case None: None\n'
                '  let return_ x = Some x\n'
                'let safe a b =\n'
                '  Maybe {\n'
                '    let! x = a\n'
                '    let! y = b\n'
                '    return x + y\n'
                '  }\n'
                'let unwrap m = match m: case Some n: n case None: 0\n'
                'let r1 = unwrap (safe (Some 3) (Some 4))\n'
                'let r2 = unwrap (safe (Some 3) None)\n'
                'print r1\n'
                'print r2\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_user_yield_ce_combines_via_delay',
        "files": {
            'main.pyfun': (
                'module Sum =\n'
                '  let yield_ x = x\n'
                '  let combine a b = a + b\n'
                '  let delay f = f 0\n'
                'let total =\n'
                '  Sum {\n'
                '    yield 1\n'
                '    yield 2\n'
                '    yield 3\n'
                '    yield 4\n'
                '  }\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_calls_python',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'extern ord: string -> int\n'
                'extern pure tan: float -> float = math.tan\n'
                'let label = show 42\n'
                'let code = ord "A"\n'
                'let root = tan 0.0\n'
                'print label\n'
                'print code\n'
                'print root\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_import_calls_python',
        "files": {
            'main.pyfun': (
                'extern import datetime\n'
                'extern parse: string -> a = datetime.datetime.fromisoformat\n'
                'let d = parse "2020-01-02"\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_functions',
        "files": {
            'main.pyfun': (
                'let xs = [1, 2, 3, 4]\n'
                'let doubled = List.map (fun x -> x * 2) xs\n'
                'let small = List.filter (fun x -> x < 3) xs\n'
                'let total = List.fold (fun a b -> a + b) 0 xs\n'
                'let n = List.len xs\n'
                'let s = List.sum xs\n'
                'let r = List.rev xs\n'
                'let q = List.range 1 4\n'
                'print doubled\n'
                'print small\n'
                'print total\n'
                'print n\n'
                'print s\n'
                'print r\n'
                'print q\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_set_functions',
        "files": {
            'main.pyfun': (
                'let s = Set.ofList [1, 2, 3, 3]\n'
                'let n = Set.len s\n'
                'let has = Set.contains 2 s\n'
                'let u = Set.len (Set.union s (Set.ofList [3, 4]))\n'
                'let i = Set.len (Set.intersect s (Set.ofList [3, 4]))\n'
                'let d = Set.len (Set.difference s (Set.ofList [3, 4]))\n'
                'let e = Set.len Set.empty\n'
                'print n\n'
                'print has\n'
                'print u\n'
                'print i\n'
                'print d\n'
                'print e\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_int_literal_unified_to_float_prints_as_float',
        "files": {
            'main.pyfun': (
                'let xs = [1.0, 2, 3.0]\n'
                'let pick b = if b then 1 else 1.5\n'
                'let r = pick true\n'
                'print xs\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_combinators',
        "files": {
            'main.pyfun': (
                'let sub a b = a - b\n'
                'let i = id 42\n'
                'let k = const 7 "ignored"\n'
                'let f = flip sub 3 10\n'
                'let mapped = List.map (const 0) [1, 2, 3]\n'
                'let identity = List.map id [4, 5, 6]\n'
                'let flipped = List.map (flip sub 100) [1, 2]\n'
                'print i\n'
                'print k\n'
                'print f\n'
                'print mapped\n'
                'print identity\n'
                'print flipped\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_map_functions',
        "files": {
            'main.pyfun': (
                'let m = Map.add "a" 1 (Map.add "b" 2 Map.empty)\n'
                'let found = Map.findOr "a" 0 m\n'
                'let dflt = Map.findOr "z" 99 m\n'
                'let sz = Map.len m\n'
                'let mc = Map.contains "b" m\n'
                'let rm = Map.len (Map.remove "b" m)\n'
                'let ks = List.len (Map.keys m)\n'
                'let hit = Option.withDefault 0 (Map.tryFind "a" m)\n'
                'let miss = Option.withDefault 0 (Map.tryFind "z" m)\n'
                'print found\n'
                'print dflt\n'
                'print sz\n'
                'print mc\n'
                'print rm\n'
                'print ks\n'
                'print hit\n'
                'print miss\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_adts_and_records_as_keys_and_elements',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'type Point = { x: int, y: int }\n'
                'let cs = Set.ofList [Red, Green, Red, Blue]\n'
                'let ncolors = Set.len cs\n'
                'let hasGreen = Set.contains Green cs\n'
                'let m = Map.add (Some 1) "one" Map.empty\n'
                'let v = Option.withDefault "?" (Map.tryFind (Some 1) m)\n'
                'let pts = Set.ofList [Point { x = 1, y = 2 }, Point { x = 1, y = 2 }, Point { x = 3, y = 4 }]\n'
                'let npts = Set.len pts\n'
                'print ncolors\n'
                'print hasGreen\n'
                'print v\n'
                'print npts\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_module_is_lazy',
        "files": {
            'main.pyfun': (
                'let nats = Seq.range 0 1000000\n'
                'let squares = Seq.toList (Seq.take 5 (Seq.map (fun x -> x * x) nats))\n'
                'let evens = Seq.toList (Seq.take 3 (Seq.filter (fun x -> x // 2 * 2 == x) nats))\n'
                'let total = Seq.fold (fun acc x -> acc + x) 0 (Seq.ofList [1, 2, 3, 4])\n'
                'print squares\n'
                'print evens\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_in_file_module',
        "files": {
            'main.pyfun': (
                'module Geometry =\n'
                '  let pi = 3\n'
                '  let area r = pi * r * r\n'
                '  let double a = area a + area a\n'
                'let a = Geometry.area 10\n'
                'let d = Geometry.double 2\n'
                'let p = Geometry.pi\n'
                'print a\n'
                'print d\n'
                'print p\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_result_module',
        "files": {
            'main.pyfun': (
                'let safeDiv a b = if b == 0 then Error "div0" else Ok (a // b)\n'
                'let r1 = safeDiv 10 2\n'
                'let r2 = safeDiv 10 0\n'
                'let a = Result.withDefault 0 (Result.map (fun x -> x + 1) r1)\n'
                'let b = Result.withDefault 0 r2\n'
                'let c = Result.isOk r1\n'
                'let d = Result.isError r2\n'
                'let e = Option.withDefault 0 (Result.toOption r1)\n'
                'let f = Result.withDefault 0 (Result.bind (fun x -> safeDiv x 3) r1)\n'
                'let g = Result.isError (Result.mapError (fun s -> s) r2)\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print g\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_module',
        "files": {
            'main.pyfun': (
                'let some = Some 5\n'
                'let none = None\n'
                'let a = Option.withDefault 0 some\n'
                'let b = Option.withDefault 0 none\n'
                'let c = Option.isSome some\n'
                'let d = Option.isNone none\n'
                'let e = Option.map (fun x -> x + 1) some\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_guarded_active_pattern_falls_through',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let describe n =\n'
                '  match n:\n'
                '    case Even if n > 100: "big even"\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                'let a = describe 200\n'
                'let b = describe 4\n'
                'let c = describe 7\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_guarded_active_pattern_in_value_position',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let classify n =\n'
                '  let label =\n'
                '    match n:\n'
                '      case Positive p if p > 100: "big"\n'
                '      case Positive p: "small"\n'
                '      case _: "nonpos"\n'
                '  String.concat label "!"\n'
                'let a = classify 250\n'
                'let b = classify 5\n'
                'let c = classify 0\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_total_active_pattern',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                'let a = f 4\n'
                'let b = f 7\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_total_active_pattern_with_fields',
        "files": {
            'main.pyfun': (
                'let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small s: s\n'
                '    case Big b: b\n'
                'let a = f 7\n'
                'let b = f 25\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_partial_active_pattern',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Positive p: p\n'
                '    case _: 0\n'
                'let a = f 7\n'
                'let b = f (-3)\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_bool_partial_active_pattern',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = String.strip s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank: "empty"\n'
                '    case _: "text"\n'
                'let a = f "   "\n'
                'let b = f "hi"\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_parameterized_active_pattern_fizzbuzz',
        "files": {
            'main.pyfun': (
                'let (|DivisibleBy|_|) d n = n % d == 0\n'
                'let fizz n =\n'
                '  match n:\n'
                '    case DivisibleBy 15: "fizzbuzz"\n'
                '    case DivisibleBy 3: "fizz"\n'
                '    case DivisibleBy 5: "buzz"\n'
                '    case _: String.fromInt n\n'
                'let a = fizz 15\n'
                'let b = fizz 9\n'
                'let c = fizz 10\n'
                'let d = fizz 7\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_active_pattern_match_in_value_position',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let r =\n'
                '  match 6:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_active_and_or_and_structural_arms_mix',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let describe o =\n'
                '  match o:\n'
                '    case Some x if x > 100: "big"\n'
                '    case Answer: "the answer"\n'
                '    case Some x: (match x:\n'
                '      case Even | Odd: String.fromInt x)\n'
                '    case None: "none"\n'
                'let a = describe (Some 42)\n'
                'let b = describe (Some 7)\n'
                'let c = describe (Some 500)\n'
                'let d = describe None\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_primitives_and_totality',
        "files": {
            'main.pyfun': (
                'let ok = Result.withDefault 0 (Decode.decodeString Decode.int "42")\n'
                'let wrongType = Result.withDefault (0 - 1) (Decode.decodeString Decode.int "\\"x\\"")\n'
                'let boolNotInt = Result.withDefault (0 - 1) (Decode.decodeString Decode.int "true")\n'
                'let intAsFloat = Result.withDefault 0.0 (Decode.decodeString Decode.float "3")\n'
                'let malformed = Result.isError (Decode.decodeString Decode.bool "not json")\n'
                'print ok\n'
                'print wrongType\n'
                'print boolNotInt\n'
                'print intAsFloat\n'
                'print malformed\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_record_via_map_and_field',
        "files": {
            'main.pyfun': (
                'type Pair = { name: string, age: int }\n'
                'let dec =\n'
                '  Decode.map2 (fun name age -> Pair { name = name, age = age })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "age" Decode.int)\n'
                'let good =\n'
                '  match Decode.decodeString dec """{"name": "ada", "age": 36}""":\n'
                '    case Ok p: p.name\n'
                '    case Error e: "?"\n'
                'let missing = Result.isError (Decode.decodeString dec """{"name": "bob"}""")\n'
                'print good\n'
                'print missing\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_list_nullable_oneof_andthen',
        "files": {
            'main.pyfun': (
                'let nums = Result.withDefault [] (Decode.decodeString (Decode.list Decode.int) "[1, 2, 3]")\n'
                'let flex = Decode.oneOf [Decode.string, Decode.map String.fromInt Decode.int]\n'
                'let fromStr = Result.withDefault "?" (Decode.decodeString flex "\\"hi\\"")\n'
                'let fromInt = Result.withDefault "?" (Decode.decodeString flex "7")\n'
                'let n = Result.withDefault (0 - 1) (Decode.decodeString (Decode.oneOf []) "1")\n'
                'print nums\n'
                'print fromStr\n'
                'print fromInt\n'
                'print n\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_success_and_missing_field',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let good = show (Decode.decodeString (Decode.field "name" Decode.string) """{"name": "ada"}""")\n'
                'let missing = show (Decode.decodeString (Decode.field "name" Decode.string) """{"other": 1}""")\n'
                'print good\n'
                'print missing\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_wrong_type',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let wrong = show (Decode.decodeString (Decode.field "age" Decode.int) """{"age": "old"}""")\n'
                'print wrong\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_int_bool_float_strictness',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let boolNotInt = show (Decode.decodeString Decode.int "true")\n'
                'let intAsFloat = show (Decode.decodeString Decode.float "5")\n'
                'print boolNotInt\n'
                'print intAsFloat\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_malformed_json_kind',
        "files": {
            'main.pyfun': (
                'let kind r =\n'
                '  match r:\n'
                '    case Ok v: "ok"\n'
                '    case Error e: e.errorKind\n'
                'let malformed = kind (Decode.decodeString Decode.bool "not json")\n'
                'print malformed\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_nullable',
        "files": {
            'main.pyfun': (
                'let opt r =\n'
                '  match r:\n'
                '    case Ok o:\n'
                '      match o:\n'
                '        case Some x: f"some {x}"\n'
                '        case None: "none"\n'
                '    case Error e: e.errorKind\n'
                'let onNull = opt (Decode.decodeString (Decode.nullable Decode.int) "null")\n'
                'let onValue = opt (Decode.decodeString (Decode.nullable Decode.int) "5")\n'
                'print onNull\n'
                'print onValue\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_oneof_first_match_and_all_fail',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: e.errorMessage\n'
                'let tagOf = Decode.oneOf [Decode.map (fun b -> "bool") Decode.bool, Decode.map (fun n -> "int") Decode.int]\n'
                'let firstMatch = show (Decode.decodeString tagOf "true")\n'
                'let secondMatch = show (Decode.decodeString tagOf "5")\n'
                'let allFail = show (Decode.decodeString (Decode.oneOf [Decode.string, Decode.map (fun b -> "b") Decode.bool]) "5")\n'
                'print firstMatch\n'
                'print secondMatch\n'
                'print allFail\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_list_of_objects_via_named_decoder',
        "files": {
            'main.pyfun': (
                'let idDec = Decode.field "id" Decode.int\n'
                'let show r =\n'
                '  match r:\n'
                '    case Ok xs: f"sum: {List.sum xs}"\n'
                '    case Error e: e.errorKind\n'
                'let total = show (Decode.decodeString (Decode.list idDec) """[{"id": 1}, {"id": 2}]""")\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_spec_succeed_and_fail',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let s = show (Decode.decodeString (Decode.succeed 42) "0")\n'
                'let failed = show (Decode.decodeString (Decode.fail "boom") "0")\n'
                'print s\n'
                'print failed\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'decode_andthen_falls_back',
        "files": {
            'main.pyfun': (
                'let dec = Decode.andThen (fun n -> Decode.succeed (n + 1)) Decode.int\n'
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: e.errorKind\n'
                'let out = show (Decode.decodeString dec "41")\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'decode_parameter_decoder_falls_back',
        "files": {
            'main.pyfun': (
                'let runWith d s = Decode.decodeString d s\n'
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: e.errorKind\n'
                'let out = show (runWith Decode.int "7")\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'decode_shadowed_free_var_falls_back',
        "files": {
            'main.pyfun': (
                'let bump n = n + 100\n'
                'let dec = Decode.map (fun x -> bump x) Decode.int\n'
                'let run u =\n'
                '  let bump = 0\n'
                '  let r = Decode.decodeString dec "5"\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v} ({bump})"\n'
                '    case Error e: e.errorKind\n'
                'let useIt = run 0\n'
                'print useIt\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'top_level_block_shadow_does_not_clobber_a_definition',
        "files": {
            'main.pyfun': (
                'let bump n = n + 100\n'
                'let useBump x = bump x\n'
                'let useIt =\n'
                '  let bump = 0\n'
                '  useBump 5\n'
                'let after = useBump 7\n'
                'print useIt\n'
                'print after\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'top_level_match_binder_shadow_does_not_clobber',
        "files": {
            'main.pyfun': (
                'let bump n = n + 100\n'
                'let useIt =\n'
                '  match Some 0:\n'
                '    case Some bump: bump\n'
                '    case None: 1\n'
                'let after = bump 7\n'
                'print useIt\n'
                'print after\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_tuple_named_folder',
        "files": {
            'main.pyfun': (
                'type Cmd = Put int int | Push int | Skip\n'
                'let step acc c =\n'
                '  match acc:\n'
                '    case (m, xs):\n'
                '      match c:\n'
                '        case Put k v: (Map.add k v m, xs)\n'
                '        case Push n: (m, List.concat xs [n])\n'
                '        case Skip: acc\n'
                'let run cmds = List.fold step (Map.empty, []) cmds\n'
                'let out = match run [Put 1 10, Push 2, Skip, Put 3 30, Push 4]: case (m, xs): (Map.toList m, xs)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_single_map_lambda',
        "files": {
            'main.pyfun': (
                'let m = List.fold (fun m x -> Map.add x (x * 2) m) Map.empty [1, 2, 3]\n'
                'let out = Map.toList m\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_top_level_fold_keeps_its_loop_names_off_top_level_bindings',
        "files": {
            'main.pyfun': (
                'let x = 100\n'
                'let total = List.fold (fun acc e -> List.concat acc [e]) [] [1, 2, 3]\n'
                'let doubled = List.fold (fun acc x -> List.concat acc [x * 2]) [] [1, 2, 3]\n'
                'let out = (x, doubled, total)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_fold_inside_an_in_file_module_lowers_to_a_loop',
        "files": {
            'main.pyfun': (
                'module Stats =\n'
                '  let scale = 3\n'
                '  let tally xs = List.fold (fun acc x -> Map.add x (x * scale) acc) Map.empty xs\n'
                'let out = Map.toList (Stats.tally [1, 2])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_cross_slot_read',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, log): (Map.add x x m, List.concat log [Map.len m])\n'
                'let r = List.fold step (Map.empty, []) [1, 2, 3]\n'
                'let out = match r: case (m, log): (Map.toList m, log)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_extend_form',
        "files": {
            'main.pyfun': (
                'let acc = List.fold (fun acc x -> List.concat acc [x, x]) [] [1, 2]\n'
                'let out = acc\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_seq_fold_and_piped_form',
        "files": {
            'main.pyfun': (
                'let s = Seq.fold (fun m x -> Map.add x x m) Map.empty (Seq.range 0 3)\n'
                'let p = [1, 2, 3] |> List.fold (fun a x -> List.concat a [x]) []\n'
                'let so = Map.toList s\n'
                'print so\n'
                'print p\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_opt_nonatomic_key_is_hoisted',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add (x + 1) x m\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_named_init_binding_gets_a_defensive_copy',
        "files": {
            'main.pyfun': (
                'let seed = Map.empty\n'
                'let grown = List.fold (fun m x -> Map.add x x m) seed [1, 2]\n'
                'let a = Map.len seed\n'
                'let b = Map.len grown\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_closure_capture',
        "files": {
            'main.pyfun': (
                'let cap acc x =\n'
                '  match acc:\n'
                '    case (m, fs): (Map.add x x m, List.concat fs [fun u -> Map.len m])\n'
                'let out = match List.fold cap (Map.empty, []) [1, 2]: case (m, fs): List.map (fun f -> f 0) fs\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_a_named_folder_inside_an_in_file_module',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add x x m\n'
                'module M =\n'
                '  let scan xs = List.fold step Map.empty xs\n'
                'let r = Map.len (M.scan [1, 2, 3])\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_local_named_folder_block_lowers_to_loop',
        "files": {
            'main.pyfun': (
                'let build xs =\n'
                '  let step acc x = Map.add x (x * 2) acc\n'
                '  List.fold step Map.empty xs\n'
                'let out = Map.toList (build [1, 2, 3])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_local_named_folder_dedup_shape_lowers_to_loop',
        "files": {
            'main.pyfun': (
                'type Leg = { depMin: int, dest: string }\n'
                'let dedupLegs legs =\n'
                '  let step acc leg =\n'
                '    match acc:\n'
                '      case (seen, out):\n'
                '        let k = f"{leg.depMin}|{leg.dest}"\n'
                '        match Map.tryFind k seen:\n'
                '          case Some _: (seen, out)\n'
                '          case None: (Map.add k true seen, List.concat out [leg])\n'
                '  match List.fold step (Map.empty, []) legs:\n'
                '    case (_, out): out\n'
                'let out = List.map (fun l -> l.depMin) (dedupLegs [Leg { depMin = 1, dest = "a" }, Leg { depMin = 1, dest = "a" }, Leg { depMin = 2, dest = "b" }])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_shadow_rebound_local_folder_uses_newest_body',
        "files": {
            'main.pyfun': (
                'let build xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  let step acc x = List.concat acc [x * 2]\n'
                '  List.fold step [] xs\n'
                'let out = build [1, 2, 3]\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_shadow_lambda_param_uses_parameter',
        "files": {
            'main.pyfun': (
                'let build combiner xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  (fun step -> List.fold step [] xs) combiner\n'
                'let out = build (fun acc x -> List.concat acc [x * 2]) [1, 2, 3]\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_shadow_match_binder_uses_binding',
        "files": {
            'main.pyfun': (
                'let build sel xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  match sel:\n'
                '    case Some step: List.fold step [] xs\n'
                '    case None: []\n'
                'let out = build (Some (fun acc x -> List.concat acc [x * 2])) [1, 2, 3]\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_chained_map_add_updates_one_slot_inner_first',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add (x * 10) x (Map.add x x m)\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_reset_store_batching_idiom',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (cur, groups):\n'
                '      if x == 0 then ([], List.concat groups [cur])\n'
                '      else (List.concat cur [x], groups)\n'
                'let out = match List.fold step ([], []) [1, 2, 0, 3, 0]: case (cur, groups): (cur, groups)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_map_remove_in_chain_lowers_to_pop',
        "files": {
            'main.pyfun': (
                'let step m x = Map.remove x (Map.add (x + 1) x m)\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_set_remove_in_chain_lowers_to_discard',
        "files": {
            'main.pyfun': (
                'let step s x = Set.remove (x - 1) (Set.add x s)\n'
                'let out = Set.toList (List.fold step Set.empty [1, 2, 3])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_var_init_defensive_copy_dict_list_set',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, l, s): (Map.add x x m, List.concat l [x], Set.add x s)\n'
                'let dseed = Map.empty\n'
                'let lseed = []\n'
                'let sseed = Set.empty\n'
                'let r = List.fold step (dseed, lseed, sseed) [1, 2]\n'
                'let out = match r: case (m, l, s): (Map.toList m, l, Set.toList s)\n'
                'let origs = (Map.len dseed, List.len lseed, Set.len sseed)\n'
                'print out\n'
                'print origs\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_var_init_alias_for_passthrough_slot',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, keep): (Map.add x x m, keep)\n'
                'let seed = Map.empty\n'
                'let seed2 = Map.empty\n'
                'let r = List.fold step (seed, seed2) [1, 2]\n'
                'let out = match r: case (m, keep): (Map.len m, Map.len keep, Map.len seed2)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_destructuring_elem_matches_fst_snd_spelling',
        "files": {
            'main.pyfun': (
                'let steps = [("a", 1), ("b", 2), ("a", 3)]\n'
                'let slow = List.fold (fun m (p, l) -> Map.add p l m) Map.empty steps\n'
                'let fast = List.fold (fun m s -> Map.add (fst s) (snd s) m) Map.empty steps\n'
                'let out = (Map.toList slow, Map.toList fast, slow == fast)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_top_level_named_folder',
        "files": {
            'main.pyfun': (
                'let add m (p, l) = Map.add p l m\n'
                'let out = Map.toList (List.fold add Map.empty [(1, "x"), (2, "y")])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_block_local_named_folder',
        "files": {
            'main.pyfun': (
                'let build steps =\n'
                '  let add m (p, l) = Map.add p l m\n'
                '  List.fold add Map.empty steps\n'
                'let out = Map.toList (build [(1, "x"), (2, "y")])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_nested_tuple',
        "files": {
            'main.pyfun': (
                'let out = Map.toList (List.fold (fun m (a, (b, c)) -> Map.add a (b + c) m) Map.empty [("x", (1, 2)), ("y", (3, 4))])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_wildcard',
        "files": {
            'main.pyfun': (
                'let out = Set.toList (List.fold (fun s (p, _) -> Set.add p s) Set.empty [(1, "a"), (2, "b"), (1, "c")])\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_tuple_accumulator',
        "files": {
            'main.pyfun': (
                'let step acc (k, v) =\n'
                '  match acc:\n'
                '    case (m, ks): (Map.add k v m, List.concat ks [k])\n'
                'let out = match List.fold step (Map.empty, []) [(1, "a"), (2, "b")]: case (m, ks): (Map.toList m, ks)\n'
                'print out\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_destructuring_let_binds_every_name',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let (a, b) = (1, 2)\n'
                'let (c, (d, e)) = (3, (4, 5))\n'
                'let Point { x, y } = Point { x = 6, y = 7 }\n'
                'let total = a + b + c + d + e + x + y\n'
                'print total\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_let_inside_a_function_body',
        "files": {
            'main.pyfun': (
                'let swapSum p =\n'
                '  let (a, b) = p\n'
                '  let (c, d) = (b, a)\n'
                '  c * 10 + d\n'
                'let r = swapSum (1, 2)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_bind_in_a_result_block',
        "files": {
            'main.pyfun': (
                'let f r =\n'
                '  result {\n'
                '    let! (a, b) = r\n'
                '    let (c, d) = (b, a)\n'
                '    return c * 10 + d\n'
                '  }\n'
                'let ok =\n'
                '  match f (Ok (1, 2)):\n'
                '    case Ok v: v\n'
                '    case Error _: 0\n'
                'print ok\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_block_short_circuits_on_none',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  option {\n'
                '    let! a = List.get 0 xs\n'
                '    let! b = List.get 1 xs\n'
                '    return (a + b)\n'
                '  }\n'
                'let hit =\n'
                '  match f [1, 2]:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                'let miss =\n'
                '  match f [1]:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                'print hit\n'
                'print miss\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_block_return_bang_and_do_bang',
        "files": {
            'main.pyfun': (
                'let f o p =\n'
                '  option {\n'
                '    do! p\n'
                '    let! x = o\n'
                '    return! (if x > 0 then Some (x * 2) else None)\n'
                '  }\n'
                'let a =\n'
                '  match f (Some 3) (Some ()):\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                'let b =\n'
                '  match f (Some 3) None:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                'let c =\n'
                '  match f (Some 0) (Some ()):\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                'print a\n'
                'print b\n'
                'print c\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_ladders_and_singletons_agree_with_the_match_seman',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let g o =\n'
                '  match o:\n'
                '    case Some x if x > 10: "big"\n'
                '    case Some x: "small"\n'
                '    case None: "none"\n'
                'let h o =\n'
                '  match o:\n'
                '    case Some (a, b): a + b\n'
                '    case _: 0\n'
                'let k r =\n'
                '  match r:\n'
                '    case Ok v: v\n'
                '    case Error e: -1\n'
                'let v o = 1 + (match o:\n'
                '  case Some x: x\n'
                '  case None: 0)\n'
                'let only o =\n'
                '  match o:\n'
                '    case Some x if x > 0: x\n'
                '    case _ if false: 1\n'
                '    case None: 2\n'
                '    case Some _: 3\n'
                'let a = g (Some 11)\n'
                'let b = g (Some 1)\n'
                'let c = g None\n'
                'let d = h (Some (1, 2))\n'
                'let e = k (Ok 4)\n'
                'let f = k (Error "x")\n'
                'let i = v (Some 3)\n'
                'let j = only (Some 5)\n'
                'let l = only (Some (0 - 5))\n'
                'let m = only None\n'
                'let n = Across == Across\n'
                'let p = Set.len (Set.ofList [Across, Down, Across])\n'
                'let q = Map.findOr Down 0 (Map.ofList [(Down, 7)])\n'
                'print a\n'
                'print b\n'
                'print c\n'
                'print d\n'
                'print e\n'
                'print f\n'
                'print i\n'
                'print j\n'
                'print l\n'
                'print m\n'
                'print n\n'
                'print p\n'
                'print q\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_slotted_records_update_compare_and_hash',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = 2 }\n'
                'let q = { p with x = 3 }\n'
                'let lt = p < q\n'
                'let s = Set.len (Set.ofList [p, q, p])\n'
                'print q\n'
                'print lt\n'
                'print s\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_local_let_partial_application_runs',
        "files": {
            'main.pyfun': (
                'let addAll xs ys =\n'
                '  let pair a b = a + b\n'
                '  List.map (pair 10) ys\n'
                'let r = addAll [] [1, 2]\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'local_lambda_let_partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                'let addAll ys =\n'
                '  let pair = fun a b -> a + b\n'
                '  List.map (pair 10) ys\n'
                'let r = addAll [1, 2]\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'local_let_over_application_applies_the_remainder',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let k a b = fun c -> a + b + c\n'
                '  k 1 2 x\n'
                'let r = f 3\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'parameter_shadowing_a_local_function_stays_n_ary',
        "files": {
            'main.pyfun': (
                'let f ys =\n'
                '  let pair a b = a + b\n'
                '  let g pair = pair 10\n'
                '  g (fun x -> x + 1)\n'
                'let r = f []\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'match_binder_shadowing_a_local_function_stays_n_ary',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let pair a b = a + b\n'
                '  let outer = pair 1\n'
                '  let inner =\n'
                '    match o:\n'
                '      case Some pair: pair 10\n'
                '      case None: 0\n'
                '  inner + outer 2\n'
                'let r = f (Some (fun x -> x + 1))\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'recursive_local_function_sees_its_own_arity',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  let go acc k =\n'
                '    if k == 0 then [acc]\n'
                '    else List.collect (go (acc + 1)) [k - 1]\n'
                '  go 0 n\n'
                'let r = f 3\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'non_function_rebinding_evicts_the_local_arity',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let pair a b = a + b\n'
                '  let pair = pair 1\n'
                '  pair x\n'
                'let r = f 2\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_capture_colliding_with_a_block_local_function_is_renamed',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let pair a b = a + b\n'
                '  let r =\n'
                '    match o:\n'
                '      case Some pair: pair\n'
                '      case None: 0\n'
                '  pair r 1\n'
                'let r = f (Some 5)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_capture_colliding_with_a_top_level_function_is_renamed',
        "files": {
            'main.pyfun': (
                'let pair a b = a + b\n'
                'let f o =\n'
                '  let r =\n'
                '    match o:\n'
                '      case Some pair: pair\n'
                '      case None: 0\n'
                '  pair r 1\n'
                'let r = f (Some 5)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_capture_colliding_with_a_parameter_read_later_is_renamed',
        "files": {
            'main.pyfun': (
                'let f x o =\n'
                '  match o:\n'
                '    case Some x: x\n'
                '    case None: x\n'
                'let a = f 1 (Some 5)\n'
                'let b = f 1 None\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_matches_capturing_the_same_name_get_distinct_fres',
        "files": {
            'main.pyfun': (
                'let f x o p =\n'
                '  match o:\n'
                '    case Some x:\n'
                '      let inner =\n'
                '        match p:\n'
                '          case Some x: x * 10\n'
                '          case None: x\n'
                '      inner + x\n'
                '    case None: x\n'
                'let r = f 1 (Some 2) (Some 3)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_made_before_the_match_reads_the_original_bindi',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let n = 100\n'
                '  let get u = n + u\n'
                '  let r =\n'
                '    match o:\n'
                '      case Some n: n\n'
                '      case None: 0\n'
                '  r + get 0\n'
                'let r = f (Some 5)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_or_and_record_pattern_captures_are_renamed_consistently',
        "files": {
            'main.pyfun': (
                'type Point = { x : int, y : int }\n'
                'let f y p q =\n'
                '  let a =\n'
                '    match p:\n'
                '      case Point { x = 0, y }: y\n'
                '      case Point { x }: x + y\n'
                '  let b =\n'
                '    match q:\n'
                '      case (0, y) | (y, 0): y\n'
                '      case (_, _): y\n'
                '  a + b\n'
                'let r = f 1000 (Point { x = 0, y = 2 }) (0, 3)\n'
                'let s = f 1000 (Point { x = 4, y = 2 }) (7, 8)\n'
                'print r\n'
                'print s\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_value_position_capture_is_renamed',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let total a b = a + b\n'
                '  1 + (match o:\n'
                '         case Some total: total\n'
                '         case None: 0) + total 1 1\n'
                'let r = f (Some 5)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_lookup_peephole_capture_is_renamed',
        "files": {
            'main.pyfun': (
                'let f m k =\n'
                '  let v = 100\n'
                '  let found =\n'
                '    match Map.tryFind k m:\n'
                '      case Some v: v\n'
                '      case None: 0\n'
                '  found + v\n'
                'let r = f (Map.ofList [(1, 5)]) 1\n'
                'let s = f (Map.ofList [(1, 5)]) 2\n'
                'print r\n'
                'print s\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_active_pattern_capture_is_renamed',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f p n =\n'
                '  let label =\n'
                '    match n:\n'
                '      case Positive p: p * 2\n'
                '      case _: 0\n'
                '  label + p\n'
                'let r = f 1000 5\n'
                'let s = f 1000 0\n'
                'print r\n'
                'print s\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_fresh_capture_name_bumps_past_a_name_in_use',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let pair a b = a + b\n'
                '  let _pair = 7\n'
                '  let r =\n'
                '    match o:\n'
                '      case Some pair: pair\n'
                '      case None: 0\n'
                '  pair r _pair\n'
                'let r = f (Some 5)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_lambda_parameter_inside_the_arm_keeps_its_own_name',
        "files": {
            'main.pyfun': (
                'let f x o =\n'
                '  let r =\n'
                '    match o:\n'
                '      case Some x: List.map (fun x -> x + 1) x\n'
                '      case None: []\n'
                '  List.len r + x\n'
                'let r = f 10 (Some [1, 2, 3])\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_fold_loop_arm_capture_is_renamed_in_the_enclosing_frame',
        "files": {
            'main.pyfun': (
                'let bump x = x + 100\n'
                'let f xs =\n'
                '  let seen = List.fold (fun acc o ->\n'
                '    match o:\n'
                '      case Some bump: Map.add bump 1 acc\n'
                '      case None: acc) Map.empty xs\n'
                '  bump (Map.len seen)\n'
                'let r = f [Some 1, None, Some 2]\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_let_in_an_if_branch_does_not_rebind_the_outer_binding',
        "files": {
            'main.pyfun': (
                'let f flag =\n'
                '  let x = 1\n'
                '  let y =\n'
                '    if flag then\n'
                '      let x = 10\n'
                '      x + 1\n'
                '    else 0\n'
                '  x + y\n'
                'let r = f true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_let_in_a_match_arm_body_does_not_rebind_the_outer_bind',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let n = 1\n'
                '  let y =\n'
                '    match o:\n'
                '      case Some k:\n'
                '        let n = k * 10\n'
                '        n + 1\n'
                '      case None: 0\n'
                '  n + y\n'
                'let r = f (Some 2)\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_let_in_a_return_position_arm_block_is_renamed',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  let n = 1\n'
                '  match o:\n'
                '    case Some k:\n'
                '      let n = n * 10 + k\n'
                '      n + 1\n'
                '    case None: n\n'
                'let r = f (Some 2)\n'
                'let s = f None\n'
                'print r\n'
                'print s\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_function_let_shadowing_an_outer_function_is_ren',
        "files": {
            'main.pyfun': (
                'let f flag n =\n'
                '  let go k = k * 100\n'
                '  let y =\n'
                '    if flag then\n'
                '      let go k = if k == 0 then 0 else k + go (k - 1)\n'
                '      go n\n'
                '    else 0\n'
                '  y + go 1\n'
                'let r = f true 3\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_mut_with_assignment_keeps_the_outer_binding',
        "files": {
            'main.pyfun': (
                'let f flag =\n'
                '  let total = 1\n'
                '  let y =\n'
                '    if flag then\n'
                '      let mut total = 0\n'
                '      total <- total + 5\n'
                '      total <- total + 5\n'
                '      total\n'
                '    else 0\n'
                '  total + y\n'
                'let r = f true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_assigning_a_renamed_nested_mut_declares_the_fr',
        "files": {
            'main.pyfun': (
                'let f flag =\n'
                '  let count = 1\n'
                '  let y =\n'
                '    if flag then\n'
                '      let mut count = 0\n'
                '      let bump u = count <- count + u\n'
                '      bump 4\n'
                '      bump 5\n'
                '      count\n'
                '    else 0\n'
                '  count + y\n'
                'let r = f true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_shadowing_a_parameter_read_later_is_renamed',
        "files": {
            'main.pyfun': (
                'let f x flag =\n'
                '  let y =\n'
                '    if flag then\n'
                '      let x = 10\n'
                '      x\n'
                '    else 0\n'
                '  x + y\n'
                'let r = f 1 true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_root_level_let_rebinding_a_parameter_is_not_renamed',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let x = x + 1\n'
                '  let x = x * 2\n'
                '  x\n'
                'let r = f 1\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_nested_let_with_no_occurrence_outside_its_block_is_not_ren',
        "files": {
            'main.pyfun': (
                'let f flag =\n'
                '  let y =\n'
                '    if flag then\n'
                '      let t = 10\n'
                '      t + 1\n'
                '    else 0\n'
                '  y\n'
                'let r = f true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_nested_let_renames_each_colliding_name',
        "files": {
            'main.pyfun': (
                'let f flag =\n'
                '  let a = 1\n'
                '  let y =\n'
                '    if flag then\n'
                '      let (a, b) = (10, 20)\n'
                '      a + b\n'
                '    else 0\n'
                '  a + y\n'
                'let r = f true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_fresh_name_bumps_past_a_name_in_use',
        "files": {
            'main.pyfun': (
                'let f flag =\n'
                '  let x = 1\n'
                '  let _x = 100\n'
                '  let y =\n'
                '    if flag then\n'
                '      let x = 10\n'
                '      x + 1\n'
                '    else 0\n'
                '  x + y + _x\n'
                'let r = f true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_capture_reused_across_sequential_matches_keeps_its_nam',
        "files": {
            'main.pyfun': (
                'let step a b =\n'
                '  let x =\n'
                '    match a:\n'
                '      case Ok v: v\n'
                '      case Error why: String.len why\n'
                '  let y =\n'
                '    match b:\n'
                '      case Ok v: v\n'
                '      case Error why: String.len why\n'
                '  x + y\n'
                'let r = step (Ok 1) (Error "no")\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_let_reused_across_sequential_branches_keeps_its_name',
        "files": {
            'main.pyfun': (
                'let f a b =\n'
                '  let x =\n'
                '    if a then\n'
                '      let t = 1\n'
                '      t + 1\n'
                '    else 0\n'
                '  let y =\n'
                '    if b then\n'
                '      let t = 10\n'
                '      t + 1\n'
                '    else 0\n'
                '  x + y\n'
                'let r = f true true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_outer_binding_read_after_both_matches_renames_both_ca',
        "files": {
            'main.pyfun': (
                'let step a b =\n'
                '  let why = "x"\n'
                '  let x =\n'
                '    match a:\n'
                '      case Ok v: v\n'
                '      case Error why: String.len why\n'
                '  let y =\n'
                '    match b:\n'
                '      case Ok v: v\n'
                '      case Error why: String.len why\n'
                '  String.len why + x + y\n'
                'let r = step (Ok 1) (Error "no")\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_reading_the_parameter_it_shadows_is_renamed',
        "files": {
            'main.pyfun': (
                'let f x flag =\n'
                '  let y =\n'
                '    if flag then\n'
                '      let x = x + 1\n'
                '      x * 2\n'
                '    else 0\n'
                '  y\n'
                'let r = f 5 true\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_three_sequential_error_arms_emit_the_plain_name',
        "files": {
            'main.pyfun': (
                'let describe a b c =\n'
                '  let s1 =\n'
                '    match a:\n'
                '      case Ok n: n\n'
                '      case Error why: String.len why\n'
                '  let s2 =\n'
                '    match b:\n'
                '      case Ok n: n\n'
                '      case Error why: String.len why\n'
                '  let s3 =\n'
                '    match c:\n'
                '      case Ok n: n\n'
                '      case Error why: String.len why\n'
                '  s1 + s2 + s3\n'
                'let r = describe (Error "a") (Ok 2) (Error "ccc")\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_escaping_an_earlier_arm_forces_the_later_captu',
        "files": {
            'main.pyfun': (
                'let f a b =\n'
                '  let g =\n'
                '    match a:\n'
                '      case Error why: fun u -> why\n'
                '      case Ok n: fun u -> "ok"\n'
                '  let m =\n'
                '    match b:\n'
                '      case Error why: String.len why\n'
                '      case Ok n: n\n'
                '  String.len (g 0) + m\n'
                'let r = f (Error "first") (Error "second")\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_shadowing_an_enclosing_name_read_earlier_is_r',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let g o =\n'
                '    let y = x + 1\n'
                '    let x = 2\n'
                '    x + y + o\n'
                '  g 10\n'
                'let r = f 5\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_shadowing_a_module_binding_read_earlier_is_re',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  let m = n + 1\n'
                '  let n = 2\n'
                '  m + n + u\n'
                'let r = f 10\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_reading_the_module_binding_it_shadows_is_rena',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  let n = n + 1\n'
                '  n + u\n'
                'let r = f 10\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_made_before_a_root_let_reads_the_enclosing_bin',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let g o =\n'
                '    let peek u = x + u\n'
                '    let before = peek 0\n'
                '    let x = 100\n'
                '    before + x + o\n'
                '  g 1\n'
                'let r = f 5\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_root_let_rebinding_a_parameter_is_not_renamed',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let x = x + 1\n'
                '  x * 2\n'
                'let r = f 3\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_root_let_referenced_only_after_it_is_not_renamed',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  let n = 2\n'
                '  n + u\n'
                'let g u =\n'
                '  let k = 1\n'
                '  k + u\n'
                'let r = f 10 + g 1\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_top_level_let_is_never_renamed',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let m = n + 1\n'
                'let n = 7\n'
                'let r = n + m\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_mut_shadowing_an_enclosing_name_declares_the',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let g o =\n'
                '    let before = x\n'
                '    let mut x = 0\n'
                '    let bump u = x <- x + u\n'
                '    bump 5\n'
                '    bump 6\n'
                '    before + x + o\n'
                '  g 1\n'
                'let r = f 100\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_root_let_renames_only_the_colliding_name',
        "files": {
            'main.pyfun': (
                'let f a =\n'
                '  let g o =\n'
                '    let before = a\n'
                '    let (a, b) = (10, 20)\n'
                '    before + a + b + o\n'
                '  g 1\n'
                'let r = f 100\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_ce_bind_shadowing_a_module_binding_read_earlier_is_ren',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  option {\n'
                '    let m = n + 1\n'
                '    let! n = Some 2\n'
                '    return n + m\n'
                '  }\n'
                'let r = f 0\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_result_bind_shadowing_an_outer_name_keeps_its_failure',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  result {\n'
                '    let m = n + 1\n'
                '    let! n = if u > 0 then Ok 2 else Error "no"\n'
                '    return n + m\n'
                '  }\n'
                'let a = f 1\n'
                'let b = f 0\n'
                'print a\n'
                'print b\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_seq_let_shadowing_an_outer_name_is_renamed',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  seq {\n'
                '    let m = n + 1\n'
                '    let n = 2\n'
                '    yield n + m\n'
                '  }\n'
                'let r = f 0 |> Seq.toList\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_ce_bind_read_only_after_it_is_not_renamed',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  option {\n'
                '    let! n = Some 2\n'
                '    let k = 1\n'
                '    return n + k\n'
                '  }\n'
                'let r = f 0\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_ce_bind_rebinding_an_earlier_ce_binder_is_not_renamed',
        "files": {
            'main.pyfun': (
                'let f u =\n'
                '  option {\n'
                '    let n = 1\n'
                '    let! n = Some (n + 1)\n'
                '    return n\n'
                '  }\n'
                'let r = f 0\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_ce_bind_renames_only_the_colliding_name',
        "files": {
            'main.pyfun': (
                'let n = 5\n'
                'let f u =\n'
                '  option {\n'
                '    let m = n + 1\n'
                '    let! (n, k) = Some (2, 3)\n'
                '    return n + k + m\n'
                '  }\n'
                'let r = f 0\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_unit_parameter_contributes_no_argument_wherever_it_sits',
        "files": {
            'main.pyfun': (
                'extern myAbs: unit -> int -> int = abs\n'
                'extern pick: int -> unit -> int -> int = max\n'
                'print (myAbs () (-5))\n'
                'print (pick 3 () 5)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_unit_parameter_contributes_no_argument_wherever_it_sits_2',
        "files": {
            'main.pyfun': 'print(abs(-5))',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_partial_application_of_a_unit_extern_drops_supplied_and_fu',
        "files": {
            'main.pyfun': (
                'extern myAbs: unit -> int -> int = abs\n'
                'extern pick: int -> unit -> int -> int = max\n'
                'let fromNeg = myAbs ()\n'
                'let lifted = pick 4\n'
                'print (fromNeg (-7))\n'
                'print (lifted () 2)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_unit_extern_thread_runs_its_pyfun_target',
        "files": {
            'main.pyfun': (
                'extern import threading\n'
                'extern type Thread\n'
                'extern newThread: unit -> (unit ->{io} unit) -> Thread = threading.Thread(daemon = true, target = ...)\n'
                'extern start: Thread -> unit = .start()\n'
                'extern join: Thread -> unit = .join()\n'
                'let t = newThread () (fun _ -> print "from the thread")\n'
                'start t\n'
                'join t'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'extern_import_covers_a_fully_applied_value_attribute_target',
        "files": {
            'main.pyfun': (
                'extern import sys\n'
                'extern write: string -> int = sys.stdout.write\n'
                'let r = write "hi"'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_triple_quoted_strings',
        "files": {
            'main.pyfun': (
                'let x = 7\n'
                'let doc = """first line\n'
                'second "quoted" line"""\n'
                'let msg = f"""x is {x}\n'
                'x + 1 is {x + 1}"""\n'
                'let a = print doc\n'
                'let b = print msg\n'
                'let n = print (String.len r"""a\\nb\n'
                'c""")'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'fstring_is_an_application_argument',
        "files": {
            'main.pyfun': (
                'let x = 5\n'
                'let main = print f"x is {x}"'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_lowers_user_sum_type_matches_to_isinstance_ladders',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float | Dot\n'
                'let describe s =\n'
                '  match s:\n'
                '    case Circle r if r > 10.0: "big circle"\n'
                '    case Circle r: f"circle {r}"\n'
                '    case Rect w h: f"rect {w * h}"\n'
                '    case Dot: "dot"\n'
                'print (describe (Circle 20.0))\n'
                'print (describe (Circle 1.5))\n'
                'print (describe (Rect 2.0 3.0))\n'
                'print (describe Dot)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_compiles_nested_tuple_record_literal_and_as_patterns',
        "files": {
            'main.pyfun': (
                'type Expr = Num int | Add Expr Expr\n'
                'type Point = { x: int, y: int }\n'
                'opaque type Id = string\n'
                'let simp e =\n'
                '  match e:\n'
                '    case Add (Num 0) b: b\n'
                '    case Add a (Num 0): a\n'
                '    case other: other\n'
                'let quad p =\n'
                '  let q =\n'
                '    match p:\n'
                '      case Point { x = 0, y = 0 }: "origin"\n'
                '      case Point { x = 0 }: "y axis"\n'
                '      case Point { x, y } as whole: f"{x},{y} {whole.x}"\n'
                '  q\n'
                'let name i = match (i, true):\n'
                '  case (Id "root", true): "admin"\n'
                '  case (Id s, _): s\n'
                'print (simp (Add (Num 0) (Num 7)))\n'
                'print (simp (Add (Num 5) (Num 0)))\n'
                'print (quad (Point { x = 0, y = 0 }))\n'
                'print (quad (Point { x = 0, y = 3 }))\n'
                'print (quad (Point { x = 2, y = 3 }))\n'
                'print (name (Id "root"))\n'
                'print (name (Id "ada"))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_lowers_or_and_list_patterns_too',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [] | [_]: "short"\n'
                '    case [a, b]: f"pair {a}{b}"\n'
                '    case [a, *mid, z]: f"{a}..{z} with {List.len mid} inside"\n'
                'let g n = match n:\n'
                '  case 1 | 2 | 3: "small"\n'
                '  case _: "big"\n'
                'print (f [])\n'
                'print (f [7])\n'
                'print (f [1, 2])\n'
                'print (f [1, 2, 3, 4])\n'
                'print (g 2)\n'
                'print (g 9)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_joins_a_nested_or_pattern_with_or',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some (1 | 2): "low"\n'
                '    case Some ((3 | 4) as n): f"mid {n}"\n'
                '    case Some _: "high"\n'
                '    case None: "none"\n'
                'print (f (Some 2))\n'
                'print (f (Some 4))\n'
                'print (f (Some 9))\n'
                'print (f None)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_annotates_top_level_functions_it_can_spell',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Square float\n'
                'type Point = { x: int, y: int }\n'
                'let area s =\n'
                '  match s:\n'
                '    case Circle r: 3.0 * r * r\n'
                '    case Square w: w * w\n'
                'let shift p dx = { p with x = p.x + dx }\n'
                'let names xs = List.map (fun s -> String.upper s) xs\n'
                'let first xs = List.head xs\n'
                'let apply f x = f x\n'
                'print (area (Square 2.0))\n'
                'print (shift (Point { x = 1, y = 2 }) 3).x\n'
                'print (names ["a"])\n'
                'print (first [1])\n'
                'print (apply (fun n -> n + 1) 1)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_annotates_module_level_values_for_other_modules',
        "files": {
            'main.pyfun': (
                'type Cell = Plain | Double\n'
                'let layout = [Plain, Double]\n'
                'let size = List.len layout\n'
                'let empty = Map.empty\n'
                'print size\n'
                'print (Map.len (Map.add 1 "a" empty))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_evaluates_a_discarded_match_in_place',
        "files": {
            'main.pyfun': (
                'let report o =\n'
                '  match o:\n'
                '    case Some n: print n\n'
                '    case None: print "none"\n'
                '  print "done"\n'
                'report (Some 1)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_annotates_block_local_functions_and_leaves_unit_retur',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Square float\n'
                'let total shapes =\n'
                '  let area s =\n'
                '    match s:\n'
                '      case Circle r: 3.0 * r * r\n'
                '      case Square w: w * w\n'
                '  let add acc s = acc + area s\n'
                '  List.fold add 0.0 shapes\n'
                'let report n = print (n + 0.0)\n'
                'report (total [Circle 1.0, Square 2.0])'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_ladders_reach_async_return_bang_matches',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let check n = if n > 0 then Ok n else Error "negative"\n'
                'let describe n =\n'
                '  async {\n'
                '    return! (match check n:\n'
                '      case Ok v: async { return f"ok {v}" }\n'
                '      case Error why: async { return why })\n'
                '  }\n'
                'print (runAsync (describe 3))\n'
                'print (runAsync (describe (0 - 1)))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_leaves_active_patterns_to_their_own_lowering',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let parity n =\n'
                '  match n:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                'print (parity 3)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_spells_out_the_comparisons_of_an_ordered_sum_type',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Square float\n'
                'let answer = 42\n'
                'print (Some 42 == Some answer)\n'
                'print (Some 1 != Some 1)\n'
                'print (Some 1 <= Some 2)\n'
                'print (Circle 1.0 == Circle 1.0)\n'
                'print (Circle 1.0 >= Square 0.0)\n'
                'print (Set.ofList [Some 1, Some 1] |> Set.len)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'native_annotates_an_async_tail_call_that_needs_no_nonlocal',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let finished count = async { return count }\n'
                'let countdown n acc =\n'
                '  async {\n'
                '    return! (if n == 0 then finished acc else countdown (n - 1) (acc + n))\n'
                '  }\n'
                'let tally xs =\n'
                '  let mut total = 0\n'
                '  let add x = total <- total + x\n'
                '  List.iter add xs\n'
                '  total\n'
                'print (runAsync (countdown 4 0))\n'
                'print (tally [1, 2, 3])'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_start_joins_the_innermost_open_scope',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let worker name = async {\n'
                '  do! Async.sleep 0.01\n'
                '  print name\n'
                '}\n'
                'let launch name = Task.start (worker name)\n'
                'let session = Task.scope (async {\n'
                '  launch "outer-1"\n'
                '  let! inner = Task.scope (async {\n'
                '    launch "inner"\n'
                '    return 1\n'
                '  })\n'
                '  launch "outer-2"\n'
                '  return inner + 1\n'
                '})\n'
                'print (runAsync session)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_async_value_is_cold_and_runs_again_on_every_await',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let job = async {\n'
                '  print "run"\n'
                '  return 1\n'
                '}\n'
                'print "built"\n'
                'let twice = async {\n'
                '  let! a = job\n'
                '  let! b = job\n'
                '  let! both = Async.parallel [job, job]\n'
                '  return a + b + List.sum both\n'
                '}\n'
                'print (runAsync twice)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_async_extern_passed_by_name_or_partially_applied_stay',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern pause: float -> Async unit = asyncio.sleep\n'
                'extern sleepThen: float -> a -> Async a = asyncio.sleep\n'
                'let pauses = [0.0, 0.0] |> List.map pause\n'
                'let values = [1, 2] |> List.map (sleepThen 0.0)\n'
                'let main = async {\n'
                '  for p in pauses:\n'
                '    do! p\n'
                '    do! p\n'
                '  for v in values:\n'
                '    let! a = v\n'
                '    let! b = v\n'
                '    print (a + b)\n'
                '  return ()\n'
                '}\n'
                'runAsync main'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_async_callback_handed_to_python_runs',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern type Reader\n'
                'extern type Writer\n'
                'extern type Server\n'
                'extern type Bytes\n'
                'extern startServer: (Reader -> Writer ->{e} Async unit) -> string -> int -> Async Server = asyncio.start_server\n'
                'extern openConnection: string -> int -> Async (Reader, Writer) = asyncio.open_connection\n'
                'extern readline: Reader -> Async Bytes = .readline()\n'
                'extern write: Writer -> Bytes -> unit = .write\n'
                'extern drain: Writer -> Async unit = .drain()\n'
                'extern closeWriter: Writer -> unit = .close()\n'
                'extern closeServer: Server -> unit = .close()\n'
                'extern encode: string -> Bytes = .encode()\n'
                'extern decode: Bytes -> string = .decode()\n'
                'let shout reader writer = async {\n'
                '  let! line = readline reader\n'
                '  write writer (encode (String.upper (decode line)))\n'
                '  do! drain writer\n'
                '  closeWriter writer\n'
                '}\n'
                'let main = async {\n'
                '  let! server = startServer shout "127.0.0.1" 47321\n'
                '  let! (reader, writer) = openConnection "127.0.0.1" 47321\n'
                '  write writer (encode "hello\\n")\n'
                '  do! drain writer\n'
                '  let! reply = Async.timeout 5.0 (readline reader)\n'
                '  print (reply |> Option.map (fun b -> String.strip (decode b)))\n'
                '  closeWriter writer\n'
                '  closeServer server\n'
                '}\n'
                'runAsync main'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_async_self_tail_call_recurses_past_the_stack_limit',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let finished acc = async { return acc }\n'
                'let loop n acc =\n'
                '  async {\n'
                '    return! (if n == 0 then finished acc else loop (n - 1) (acc + n))\n'
                '  }\n'
                'print (runAsync (loop 100000 0))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_empty_race_raises_the_named_error',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let main = async {\n'
                '  let! r = Async.catch (Async.race [])\n'
                '  match r:\n'
                '    case Ok _: print "ok"\n'
                '    case Error e: print f"{e.errorKind}: {e.errorMessage}"\n'
                '  return ()\n'
                '}\n'
                'runAsync main'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_mut_assigned_in_an_async_block_reaches_the_module_bind',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let mut flag = false\n'
                'let raiseFlag _ =\n'
                '  async {\n'
                '    flag <- true\n'
                '    return ()\n'
                '  }\n'
                'runAsync (raiseFlag ())\n'
                'print flag'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_mut_assigned_in_a_seq_block_reaches_the_module_binding',
        "files": {
            'main.pyfun': (
                'let mut hits = 0\n'
                'let track xs = seq {\n'
                '  for x in xs:\n'
                '    hits <- hits + 1\n'
                '    yield x\n'
                '}\n'
                '[10, 20] |> track |> Seq.toList |> print\n'
                'print hits'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_expression_items_and_a_trailing_do_bang_in_an_async_bloc',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern sleep: float -> Async unit = asyncio.sleep\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let nap = async {\n'
                '  let! _ = sleep 0.001\n'
                '  print "napped"\n'
                '  match 1:\n'
                '    case 1: print "one"\n'
                '    case _: print "other"\n'
                '  if true then print "yes" else ()\n'
                '  do! sleep 0.001\n'
                '}\n'
                'print (runAsync nap)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_trailing_do_bang_in_a_result_block_is_forwarded',
        "files": {
            'main.pyfun': (
                'let check x = if x > 0 then Ok () else Error "neg"\n'
                'let v = result { do! check 1 }\n'
                'let w = result {\n'
                '  let! a = Ok 2\n'
                '  print a\n'
                '  do! check (0 - a)\n'
                '}\n'
                'print v\n'
                'print w'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_async_module_members_run_over_asyncio',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern failing: string -> Async unit = asyncio.sleep\n'
                'let slow n = async { do! Async.sleep 0.01  return n }\n'
                'let main = async {\n'
                '  let! xs = Async.parallel [slow 1, slow 2, slow 3]\n'
                '  print xs\n'
                '  let! first = Async.race [slow 7, async { do! Async.sleep 0.5  return 8 }]\n'
                '  print first\n'
                '  let! t = Async.timeout 0.001 (Async.sleep 0.5)\n'
                '  print t\n'
                '  let! u = Async.timeout 1.0 (slow 9)\n'
                '  print u\n'
                '  let! v = Async.toThread (fun _ -> 41)\n'
                '  print v\n'
                '  let! r = Async.catch (failing "oops")\n'
                '  match r:\n'
                '    case Ok _: print "ok"\n'
                '    case Error e: print f"caught {e.errorKind}"\n'
                '  let! ok = Async.catch (slow 5)\n'
                '  print ok\n'
                '  return ()\n'
                '}\n'
                'runAsync main'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_thunk_argument_to_an_extern_is_wrapped_for_python',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern toThread: (unit -> a) -> Async a = asyncio.to_thread\n'
                'let answer n = n * 7\n'
                'let main = async {\n'
                '  let! v = toThread (fun _ -> 6 * 7)\n'
                '  let! w = toThread (fun _ -> answer 7)\n'
                '  return v + w\n'
                '}\n'
                'print (runAsync main)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_for_items_in_seq_async_result_and_a_user_builder',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'module Html =\n'
                '  let yield_ n = [n]\n'
                '  let combine a b = List.concat a b\n'
                '  let delay f = f ()\n'
                '  let for_ xs f = List.collect f xs\n'
                'let page rows = Html {\n'
                '  yield "h1"\n'
                '  for r in rows:\n'
                '    yield f"tr {r}"\n'
                '  yield "p"\n'
                '}\n'
                'print (page ["a", "b"])\n'
                'let squares = seq {\n'
                '  for x in [1, 2, 3]:\n'
                '    let y = x * x\n'
                '    yield y\n'
                '  yield 100\n'
                '}\n'
                'print (Seq.toList squares)\n'
                'let nested = seq { for x in [1, 2]: for y in Seq.ofList [10, 20]: yield x + y }\n'
                'print (Seq.toList nested)\n'
                'let pairs = seq { for (a, b) in [(1, 2), (3, 4)]: yield a + b }\n'
                'print (Seq.toList pairs)\n'
                'let check x = if x > 0 then Ok x else Error f"bad {x}"\n'
                'let allGood xs = result {\n'
                '  for x in xs:\n'
                '    let! _ = check x\n'
                '  return "all positive"\n'
                '}\n'
                'print (allGood [1, 2, 3])\n'
                'print (allGood [1, -2, 3])\n'
                'let main = async {\n'
                '  for n in [1, 2]:\n'
                '    do! Async.sleep 0.001\n'
                '    print n\n'
                '  return ()\n'
                '}\n'
                'runAsync main'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_derived_codecs_round_trip_a_rich_type',
        "files": {
            'main.pyfun': (
                'type Placed = { letter: string, score: int }\n'
                'type Player = Ann | Bob\n'
                'type Msg = Hello Player | Move string | Resign\n'
                'type Tree = Leaf | Node Tree int Tree\n'
                'type View = { board: Map (int, int) Placed, players: List Player, turn: Option Player, last: Msg, tree: Tree, pair: (string, float), tags: Set string }\n'
                'let view = View {\n'
                '  board = Map.ofList [((1, 2), Placed { letter = "Q", score = 10 })],\n'
                '  players = [Ann, Bob],\n'
                '  turn = Some Bob,\n'
                '  last = Move "K11 a QUIZ",\n'
                '  tree = Node Leaf 1 (Node Leaf 2 Leaf),\n'
                '  pair = ("x", 1.5),\n'
                '  tags = Set.ofList ["a"]\n'
                '}\n'
                'let wire = Encode.auto view\n'
                'print wire\n'
                'let back = Decode.decodeString Decode.auto wire\n'
                'match back:\n'
                '  case Ok v: print (v == view)\n'
                '  case Error e: print f"failed: {e.errorKind} {e.errorMessage}"\n'
                'let showMsg m =\n'
                '  match m:\n'
                '    case Hello p: f"hello {p}"\n'
                '    case Move s: f"move {s}"\n'
                '    case Resign: "resign"\n'
                'let decodeMsg s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok m: showMsg m\n'
                '    case Error e: f"error {e.errorKind}: {e.errorMessage}"\n'
                'print (decodeMsg "{\\"type\\": \\"Resign\\"}")\n'
                'print (decodeMsg "{\\"type\\": \\"Hello\\", \\"fields\\": [{\\"type\\": \\"Ann\\"}]}")\n'
                'print (decodeMsg "{\\"type\\": \\"Nope\\"}")\n'
                'print (decodeMsg "[1, 2]")\n'
                'print (decodeMsg "{\\"type\\": \\"Move\\", \\"fields\\": [1]}")'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_derived_codecs_read_through_a_newtype_and_a_keyword_fiel',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'type Row = { class: string, id: UserId, ok: Result int string }\n'
                'let row = Row { class = "a", id = UserId "u1", ok = Error "no" }\n'
                'let wire = Encode.auto row\n'
                'print wire\n'
                'match Decode.decodeString Decode.auto wire:\n'
                '  case Ok r: print (r == row)\n'
                '  case Error e: print e.errorMessage'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_prelude_print_and_numerics',
        "files": {
            'main.pyfun': (
                'let a = 3\n'
                'let b = 10\n'
                'print (min a b)\n'
                'print (max a b)\n'
                'print (abs (a - b))\n'
                'print (Some 7)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_comparison_and_structural_equality',
        "files": {
            'main.pyfun': (
                'print (1 < 2)\n'
                'print ("a" < "b")\n'
                'print (3 == 3)\n'
                'print (Some 1 == Some 1)\n'
                'print (Some 1 == Some 2)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_lists_compare_and_sort_lexicographically',
        "files": {
            'main.pyfun': (
                'print ([1, 2] < [1, 3])\n'
                'print ([1, 2, 3] < [1, 2])\n'
                'print (["apple"] < ["banana"])\n'
                'print (List.sort [[2], [1], [1, 0]])'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_boolean_logic',
        "files": {
            'main.pyfun': (
                'let between lo hi x = lo <= x and x <= hi\n'
                'print (true and not false)\n'
                'print (1 < 2 or 5 < 3)\n'
                'print (not (1 == 2))\n'
                'print (between 0 10 5)\n'
                'print (between 0 10 20)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_active_pattern_side_effects_run_once_per_match',
        "files": {
            'main.pyfun': (
                'let (|Tag|Untag|) n =\n'
                '  print "eval"\n'
                '  if n > 0 then Tag n else Untag\n'
                'let r =\n'
                '  match 5:\n'
                '    case Tag v: v\n'
                '    case Untag: 0\n'
                'print r'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_trailing_unit_expression_ends_result_and_option_blocks',
        "files": {
            'main.pyfun': (
                'let check x = if x > 0 then Ok x else Error "neg"\n'
                'let v = result {\n'
                '  let! a = check 1\n'
                '  print a\n'
                '}\n'
                'print v\n'
                'let o = option { print 2 }\n'
                'print o\n'
                'let e = result {\n'
                '  let! a = check (0 - 1)\n'
                '  print a\n'
                '}\n'
                'print e'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_effectful_recursive_loop_runs',
        "files": {
            'main.pyfun': (
                'let countdown label n =\n'
                '  let _ = print label\n'
                '  if n <= 0 then 0 else countdown label (n - 1)\n'
                'let done = countdown "tick" 2'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_binding_named_after_an_emitted_builtin_does_not_shadow',
        "files": {
            'main.pyfun': (
                'let set = 1\n'
                'let s = Set.ofList ["a"]\n'
                'print (Set.contains "a" s)\n'
                'print set'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_local_binding_named_after_a_builtin_does_not_shadow_it',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  let dict = 1\n'
                '  let m = Map.ofList [("a", dict)]\n'
                '  Map.len m\n'
                'print (f [])'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'e2e_bindings_named_after_python_keywords_emit_valid_python',
        "files": {
            'main.pyfun': (
                'type P = { lambda: int }\n'
                'let f class = class + 1\n'
                'let g o =\n'
                '  match o:\n'
                '    case Some def: def\n'
                '    case None: 0\n'
                'let h = List.map (fun global -> global + 1) [1]\n'
                'let k n =\n'
                '  let pass = n + 1\n'
                '  pass * 2\n'
                'let p = P { lambda = 7 }\n'
                'print (f 1)\n'
                'print (g (Some 3))\n'
                'print h\n'
                'print (k 3)\n'
                'print p.lambda'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'an_extern_module_import_is_aliased_when_a_binding_claims_its',
        "files": {
            'main.pyfun': (
                'extern sq : float -> float = math.sqrt\n'
                'let math = 1\n'
                'print (sq 4.0)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'an_uncollided_extern_import_stays_plain',
        "files": {
            'main.pyfun': (
                'extern sq : float -> float = math.sqrt\n'
                'print (sq 4.0)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'an_aliased_or_dotted_extern_import_re_roots_around_a_collisi',
        "files": {
            'main.pyfun': (
                'extern import os.path\n'
                'extern joinp : string -> string -> string = os.path.join\n'
                'let os = 1\n'
                'print (joinp "a" "b")'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'accepts_print_of_any_type',
        "files": {
            'main.pyfun': (
                'let a = print 1\n'
                'let b = print true\n'
                'let c = print "x"'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_multi_argument_callback_may_be_effectful',
        "files": {
            'main.pyfun': (
                'extern log : int -> int = builtins.print\n'
                'let step acc x =\n'
                '    let shown = log x\n'
                '    acc + x\n'
                'let total = List.fold step 0 [1, 2]'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'every_module_can_iterate_for_effect',
        "files": {
            'main.pyfun': (
                'let a = Set.iter (fun x -> print x) (Set.ofList [1])\n'
                'let b = Map.iter (fun k v -> print v) (Map.ofList [(1, 2)])'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'option_and_result_iter_carry_their_effect',
        "files": {
            'main.pyfun': 'let go = Option.iter (fun x -> print x) (Some 1)',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'seq_iter_carries_the_effect_of_its_function',
        "files": {
            'main.pyfun': 'let go = Seq.iter (fun x -> print x) (Seq.ofList [1])',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'list_iter_carries_the_effect_of_its_function',
        "files": {
            'main.pyfun': 'let go = List.iter (fun x -> print x) [1, 2]',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'higher_order_function_is_effect_polymorphic',
        "files": {
            'main.pyfun': (
                'let pure apply f x = f x\n'
                'let r = apply print 5'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'pure_higher_order_with_impure_argument_at_call_site_is_fine',
        "files": {
            'main.pyfun': (
                'let pure twice f x = f (f x)\n'
                'let inc a = a + 1\n'
                'let log a =\n'
                '    print a\n'
                '    a\n'
                'let r1 = twice inc 0\n'
                'let r2 = twice log 0'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_trailing_unit_expression_ends_a_monad_block',
        "files": {
            'main.pyfun': (
                'let check x = if x > 0 then Ok x else Error "neg"\n'
                'let v = result {\n'
                '  let! a = check 1\n'
                '  print a\n'
                '}\n'
                'let o = option { print 1 }\n'
                'let a = async { print 1 }'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'a_trailing_unit_expression_ends_a_monad_block_2',
        "files": {
            'main.pyfun': 'let o = option { print 1 }',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_is_pinned_by_a_later_use_and_open_otherwise',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let back = Decode.decodeString Decode.auto "{}"\n'
                'match back:\n'
                '  case Ok p: print p.x\n'
                '  case Error _: print 0'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'an_expression_item_checks_as_a_wildcard_let',
        "files": {
            'main.pyfun': (
                'let a = option {\n'
                '  let! x = Some 1\n'
                '  print x\n'
                '  return x\n'
                '}'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'def_is_answered_with_the_let_spelling',
        "files": {
            'main.pyfun': (
                'let def x = x + 1\n'
                'print (def 2)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'bundle_writes_a_page_a_loader_the_modules_and_the_assets',
        "files": {
            'main.pyfun': 'print 42',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'bundle_writes_a_page_a_loader_the_modules_and_the_assets_2',
        "files": {
            'main.pyfun': 'print(42)',
        },
        'args': ['run', 'main.pyfun'],
    },
]



@pytest.mark.parametrize("case", RUN_CASES, ids=[c["id"] for c in RUN_CASES])
def test_run_prints_exact_output(run, workdir, case):
    """CATCHES: emitted Python that type-checks but computes the wrong value at runtime (wrong currying, folding, record update, unit erasure, CE desugaring, string formatting or repr of ADTs/records/Options), or a `run` that loses stdout or exits non-zero."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
