"""Type-checker edge cases driven through `check`, `compile` and `run`.

Each case writes `main.pyfun` (plus any imported modules) into the empty working
directory and runs one command on it; the whole transcript (exit code, stdout,
stderr) is compared with the reference binary's. The programs target diagnostics
and inference paths the harvested corpus does not reach: declaration clashes,
mutually recursive groups, active-pattern shape rules, record update rules,
exhaustiveness witnesses, effect unification, derived codecs and module interfaces.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

DECLARATION_CASES = [
    {
        'id': 'unit_pow_zero',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let x = 5.0<m^0>\n'
                'let y = x + 1.0\n'
                'print y\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'measure_defined_twice',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure m\n'
                'let x = 1<m>\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'measure_alias_twice',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure v = m / s\n'
                'measure v = m s\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'lowercase_type_name_rejected',
        "files": {
            'main.pyfun': 'type int = A | B\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'redefine_builtin_option',
        "files": {
            'main.pyfun': 'type Option a = Yes a | No\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'type_no_args',
        "files": {
            'main.pyfun': (
                'type Box = Box int\n'
                'type W = { b: Box int }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'type_wrong_arity',
        "files": {
            'main.pyfun': (
                'type Pair a b = Pair a b\n'
                'type W = { p: Pair int }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'type_parameter_applied_rejected',
        "files": {
            'main.pyfun': 'type Box a = { v: a int }\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'builtin_type_applied_rejected',
        "files": {
            'main.pyfun': 'type W = { v: int string }\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'binding_type_annotation_rejected',
        "files": {
            'main.pyfun': (
                'type P = { xs: Seq int }\n'
                'let d : int = 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'value_extern',
        "files": {
            'main.pyfun': (
                'extern pi : float = math.pi\n'
                'extern e : float = math.e\n'
                'print (pi > 3.0)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'value_extern_compile',
        "files": {
            'main.pyfun': (
                'extern pi : float = math.pi\n'
                'let tau = 2.0 * pi\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_import_alias',
        "files": {
            'main.pyfun': (
                'extern import numpy as np\n'
                'extern arr : List int -> int = np.sum\n'
                'let s = arr [1, 2]\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_import_alias_other_target',
        "files": {
            'main.pyfun': (
                'extern import numpy as np\n'
                'extern arr : List int -> int = numpy.sum\n'
                'let s = arr [1, 2]\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_import_alias_dotted_target',
        "files": {
            'main.pyfun': (
                'extern import numpy as np\n'
                'extern norm : List float -> float = np.linalg.norm\n'
                'let n = norm [3.0, 4.0]\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
]

BINDING_CASES = [
    {
        'id': 'mutual_group_type_error',
        "files": {
            'main.pyfun': (
                'let isEven n = if n == 0 then true else isOdd (n - 1)\n'
                'let isOdd n = if n == 0 then 1 else isEven (n - 1)\n'
                'let r = isEven 4\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'mutual_group_pure_violation',
        "files": {
            'main.pyfun': (
                'let pure ping n = if n == 0 then print "done" else pong (n - 1)\n'
                'let pong n = ping n\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'mutual_group_bad_param_pattern',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let f (P { zz }) = g zz\n'
                'let g n = f (P { x = n })\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'module_member_error',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let bad = 1 + true\n'
                '  let ok = 2\n'
                'let r = M.ok + 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'assign_unbound',
        "files": {
            'main.pyfun': (
                'let f u =\n'
                '  y <- 1\n'
                '  u\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'many_type_variables_in_message',
        "files": {
            'main.pyfun': (
                'let f a0 a1 a2 a3 a4 a5 a6 a7 a8 a9 a10 a11 a12 a13 a14 a15 a16 a17 a18 a19 a20 a21 a22 a23 a24 a25 a26 a27 = 0\n'
                'let bad = f + true\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'reciprocal_unit_in_message',
        "files": {
            'main.pyfun': (
                'measure s\n'
                'let rate = 1.0 / 2.0<s>\n'
                'let bad = rate + true\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'reciprocal_unit_in_mismatch',
        "files": {
            'main.pyfun': (
                'measure s\n'
                'let rate = 1.0 / 2.0<s>\n'
                'let bad = if true then rate else true\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unit_mismatch_in_if_branches',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let n = if true then List.len [1] else 5<m>\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_yield_bang_error',
        "files": {
            'main.pyfun': (
                'let xs = seq {\n'
                '  yield 1\n'
                '  yield! 5\n'
                '}\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'let_poly_inner_function_over_callback',
        "files": {
            'main.pyfun': (
                'let f g =\n'
                '  let h x = g x\n'
                '  h 1\n'
                '  h 2\n'
                'let r = f print\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'hole_name_affinity',
        "files": {
            'main.pyfun': 'let s = ?uppercase "abc"\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'hole_name_affinity_len',
        "files": {
            'main.pyfun': 'let n = ?length [1, 2]\n',
        },
        'args': ['check', 'main.pyfun'],
    },
]

ACTIVE_PATTERN_CASES = [
    {
        'id': 'ap_total_rich_body',
        "files": {
            'main.pyfun': (
                'type P = { a: int, b: int }\n'
                'let (|Small|Big|) n =\n'
                '  let mut hits = 0\n'
                '  hits <- hits + 1\n'
                '  let p = P { a = n, b = 2 }\n'
                '  let q = { p with b = 3 }\n'
                '  let s = f"{n} {q.a}"\n'
                '  let g = fun x -> x + 1\n'
                '  let t = [n, -n]\n'
                '  let u = (n, q.a)\n'
                '  let r = try (g n)\n'
                '  let o = option {\n'
                '    let! z = Some n\n'
                '    return z\n'
                '  }\n'
                '  match n:\n'
                '    case k if k > 100: k |> Big\n'
                '    case _:\n'
                '      if 0 < n < 10 and not (n == 3) then Small n else Big (g n)\n'
                '\n'
                'let describe n =\n'
                '  match n:\n'
                '    case Small k: f"small {k}"\n'
                '    case Big k: f"big {k}"\n'
                'print (describe 4)\n'
                'print (describe 50)\n'
                'print (describe 500)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ap_body_ce_items',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let (|Small|Big|) n =\n'
                '  let xs = seq {\n'
                '    yield n\n'
                '    for k in [1, 2]:\n'
                '      yield k\n'
                '  }\n'
                '  let o = option {\n'
                '    do! Some ()\n'
                '    return! Some n\n'
                '  }\n'
                '  let d = 5<m>\n'
                '  if n < 10 then Small else Big\n'
                '\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small: "small"\n'
                '    case Big: "big"\n'
                'print (f 3)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ap_total_arity_mismatch',
        "files": {
            'main.pyfun': (
                'let (|A|B|) n = if n > 0 then A n else A\n'
                'let f n =\n'
                '  match n:\n'
                '    case A k: k\n'
                '    case B: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_case_arg_not_variable',
        "files": {
            'main.pyfun': (
                'let (|Pos|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Pos 3: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_param_arg_not_literal',
        "files": {
            'main.pyfun': (
                'let (|DivBy|_|) d n = n % d == 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case DivBy (Some 3): 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_param_arg_bool_and_var',
        "files": {
            'main.pyfun': (
                'let (|Is|_|) b n = (n > 0) == b\n'
                'let f n =\n'
                '  let t = true\n'
                '  match n:\n'
                '    case Is true: 1\n'
                '    case Is t: 2\n'
                '    case _: 0\n'
                'print (f 3)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ap_nested_in_ctor_pattern',
        "files": {
            'main.pyfun': (
                'let (|Pos|_|) n = if n > 0 then Some n else None\n'
                'let f o =\n'
                '  match o:\n'
                '    case Some (Pos k): k\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_or_with_ctor',
        "files": {
            'main.pyfun': (
                'let (|Pos|_|) n = n > 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case Pos | 0: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_or_with_plain_ctor',
        "files": {
            'main.pyfun': (
                'type T = Foo | Bar\n'
                'let (|Pos|_|) n = n > 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case Pos | Foo: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_or_two_patterns',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let (|Pos|_|) n = n > 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even | Pos: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_or_same_pattern',
        "files": {
            'main.pyfun': (
                'let (|Small|Mid|Big|) n = if n < 10 then Small else if n < 100 then Mid else Big\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small | Mid: "not big"\n'
                '    case Big: "big"\n'
                'print (f 5)\n'
                'print (f 500)\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'ap_bool_too_many_binders',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank x: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_total_too_many_binders',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even x: 1\n'
                '    case Odd: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_used_inside_own_body',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n =\n'
                '  match n:\n'
                '    case Even: Even\n'
                '    case _: if n % 2 == 0 then Even else Odd\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_arg_mentions_ap',
        "files": {
            'main.pyfun': (
                'let (|Pos|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Pos (Pos k): k\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_total_body_not_a_case',
        "files": {
            'main.pyfun': 'let (|A|B|) n = 5\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ap_total_body_wrong_type',
        "files": {
            'main.pyfun': 'let (|A|B|) n = if n > 0 then Some A else Some B\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'two_total_aps_in_one_match',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let (|Small|Big|) n = if n < 10 then Small else Big\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even: 1\n'
                '    case Small: 2\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
]

RECORD_CASES = [
    {
        'id': 'record_field_set_twice',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'let p = P { x = 1, x = 2, y = 3 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_update_set_twice',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: int }\n'
                'let p = P { x = 1, y = 2 }\n'
                'let q = { p with x = 3, x = 4 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_update_direct_and_sub',
        "files": {
            'main.pyfun': (
                'type In = { a: int }\n'
                'type Out = { i: In, n: int }\n'
                'let o = Out { i = In { a = 1 }, n = 2 }\n'
                'let q = { o with i = In { a = 5 }, i.a = 3 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_update_unknown_sub',
        "files": {
            'main.pyfun': (
                'type In = { a: int }\n'
                'type Out = { i: In, n: int }\n'
                'let o = Out { i = In { a = 1 }, n = 2 }\n'
                'let q = { o with i.zz = 3 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_update_through_non_record',
        "files": {
            'main.pyfun': (
                'type Out = { n: int }\n'
                'let o = Out { n = 2 }\n'
                'let q = { o with n.zz = 3 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_update_through_sum',
        "files": {
            'main.pyfun': (
                'type S = A | B\n'
                'type Out = { s: S }\n'
                'let o = Out { s = A }\n'
                'let q = { o with s.zz = 3 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_pattern_unknown_field',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let f p =\n'
                '  match p:\n'
                '    case P { zz }: zz\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_field_no_records',
        "files": {
            'main.pyfun': 'let f p = p.name\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'constructor_arity_in_pattern',
        "files": {
            'main.pyfun': (
                'type S = A int | B\n'
                'let f s =\n'
                '  match s:\n'
                '    case A x y: x\n'
                '    case B: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deferred_field_pinned_to_record_without_it',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let f p =\n'
                '  let v = p.zz\n'
                '  p == P { x = 1 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deferred_field_pinned_to_sum',
        "files": {
            'main.pyfun': (
                'type S = A | B\n'
                'type P = { x: int }\n'
                'let f p =\n'
                '  let v = p.x\n'
                '  p == A\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deferred_ambiguous_field_pinned_to_other_record',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'type Q = { y: int, w: int }\n'
                'type R = { y: int }\n'
                'let f p =\n'
                '  let v = p.y\n'
                '  p == P { x = 1 }\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deferred_ambiguous_field_pinned_to_sum',
        "files": {
            'main.pyfun': (
                'type S = A | B\n'
                'type Q = { y: int, w: int }\n'
                'type R = { y: int }\n'
                'let f p =\n'
                '  let v = p.y\n'
                '  p == A\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deferred_ambiguous_field_resolved',
        "files": {
            'main.pyfun': (
                'type Q = { y: int, w: int }\n'
                'type R = { y: int }\n'
                'let f p =\n'
                '  let v = p.y\n'
                '  p == R { y = 2 }\n'
                'print (f (R { y = 2 }))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]

PATTERN_CASES = [
    {
        'id': 'or_pattern_binds_only_some',
        "files": {
            'main.pyfun': (
                'type S = A int | B int | C\n'
                'let f s =\n'
                '  match s:\n'
                '    case A x | C: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_binds_extra_in_later',
        "files": {
            'main.pyfun': (
                'type S = A int | B int | C\n'
                'let f s =\n'
                '  match s:\n'
                '    case C | A x: 1\n'
                '    case _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_binds_same_names',
        "files": {
            'main.pyfun': (
                'type S = A int | B int | C\n'
                'let f s =\n'
                '  match s:\n'
                '    case A x | B x: x\n'
                '    case C: 0\n'
                'print (f (B 7))\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_binder_type_clash',
        "files": {
            'main.pyfun': (
                'type S = A int | B string | C\n'
                'let f s =\n'
                '  match s:\n'
                '    case A x | B x: 1\n'
                '    case C: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'missing_int_literal',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case 1: "one"\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'missing_string_literal',
        "files": {
            'main.pyfun': (
                'let f s =\n'
                '  match s:\n'
                '    case "a": 1\n'
                '    case "b": 2\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'missing_in_tuple_of_ints',
        "files": {
            'main.pyfun': (
                'let f p =\n'
                '  match p:\n'
                '    case (0, _): 1\n'
                '    case (_, 0): 2\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'missing_record_witness',
        "files": {
            'main.pyfun': (
                'type P = { x: int, y: bool }\n'
                'let f p =\n'
                '  match p:\n'
                '    case P { x, y = true }: x\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'as_pattern_exhaustive',
        "files": {
            'main.pyfun': (
                'type S = A | B\n'
                'let f s =\n'
                '  match s:\n'
                '    case (A as a): 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'as_pattern_in_tuple',
        "files": {
            'main.pyfun': (
                'type S = A | B\n'
                'let f p =\n'
                '  match p:\n'
                '    case (A as a, true): 1\n'
                '    case (B, _): 2\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'or_in_nested_position',
        "files": {
            'main.pyfun': (
                'type S = A | B | C\n'
                'let f p =\n'
                '  match p:\n'
                '    case (A | B, true): 1\n'
                '    case (C, _): 2\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'lone_star_list',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [1, *r]: 1\n'
                '    case [*r]: 2\n'
                'print (f [1])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'lone_star_after_nil_and_cons',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [1, *r]: 1\n'
                '    case [*r]: 2\n'
                'print (f [])\n'
                'print (f [1, 2])\n'
                'print (f [3])\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'star_first_list',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [*init, 0]: 1\n'
                '    case []: 2\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'int_in_list_pattern',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [0]: 1\n'
                '    case ["a"]: 2\n'
                '    case _: 3\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'tuple_vs_wildcard_witness',
        "files": {
            'main.pyfun': (
                'let f t =\n'
                '  match t:\n'
                '    case ((1, 2), 3): 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'record_and_wildcard',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let f o =\n'
                '  match o:\n'
                '    case Some (P { x = 1 }): 1\n'
                '    case None: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'guarded_record_rows_witness',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let f p =\n'
                '  let n = p.x\n'
                '  match p:\n'
                '    case q if n > 0: 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'guarded_tuple_rows_witness',
        "files": {
            'main.pyfun': (
                'let f a b =\n'
                '  match (a, b):\n'
                '    case t if a > b: 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
]

COMPARISON_CASES = [
    {
        'id': 'compare_functions',
        "files": {
            'main.pyfun': (
                'let f x = x\n'
                'let g x = x\n'
                'let r = f < g\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compare_deep_type',
        "files": {
            'main.pyfun': (
                'type T = Leaf | Node T T\n'
                'let r = Leaf < Node Leaf Leaf\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compare_record_with_option',
        "files": {
            'main.pyfun': (
                'type P = { a: Option int, b: List string }\n'
                'let r = P { a = Some 1, b = [] } < P { a = None, b = ["x"] }\n'
                'print r\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compare_extern_type',
        "files": {
            'main.pyfun': (
                'extern type Conn\n'
                'extern open: string -> Conn = sqlite3.connect\n'
                'let a = open ":memory:"\n'
                'let r = a < a\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compare_options',
        "files": {
            'main.pyfun': 'let r = Some 1 < Some 2\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compare_sets',
        "files": {
            'main.pyfun': 'let r = Set.ofList [1] < Set.ofList [2]\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compare_too_deep',
        "files": {
            'main.pyfun': (
                'type W a = W a\n'
                'let deep = W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (W (1)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))\n'
                'let r = deep < deep\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
]

EFFECT_CASES = [
    {
        'id': 'callback_second_arrow',
        "files": {
            'main.pyfun': (
                'extern run2 : (int -> int -> unit) -> unit = m.run2\n'
                'let r = run2 (fun a b -> print a)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'callback_curried_extern_head',
        "files": {
            'main.pyfun': (
                'extern withCb : int -> (int -> unit) -> unit = m.w\n'
                'let r = withCb 1 (fun x -> print x)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'callback_head_not_a_name',
        "files": {
            'main.pyfun': (
                'extern each : (int -> unit) -> unit = m.each\n'
                'let r = (if true then each else each) (fun x -> print x)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'callback_param_position',
        "files": {
            'main.pyfun': (
                'extern pure takesPure : (int -> unit) -> unit = m.tp\n'
                'extern apply : ((int ->{io} unit) -> unit) -> unit = m.ap\n'
                'let r = apply takesPure\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'callback_labelled_first_arrow',
        "files": {
            'main.pyfun': (
                'extern runIo : (int ->{io} int -> unit) -> unit = m.r\n'
                'let cb a =\n'
                '  print a\n'
                '  fun b -> print b\n'
                'let r = runIo cb\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'callback_named_function',
        "files": {
            'main.pyfun': (
                'extern each : (int -> unit) -> unit = m.each\n'
                'let shout x = print x\n'
                'let r = each shout\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'effect_recursive_hof',
        "files": {
            'main.pyfun': (
                'let loop f n =\n'
                '  if n == 0 then ()\n'
                '  else\n'
                '    f n\n'
                '    loop f (n - 1)\n'
                'let r = loop print 3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'effect_two_callbacks',
        "files": {
            'main.pyfun': (
                'let both f g x =\n'
                '  f x\n'
                '  g x\n'
                'let pick c f g = if c then both f g else both g f\n'
                'let r = pick true print print 1\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'effect_widen',
        "files": {
            'main.pyfun': (
                'let twice f g x =\n'
                '  f x\n'
                '  g x\n'
                'let choose c a b = if c then a else b\n'
                'let h = choose true (twice print print) (twice (fun x -> ()) print)\n'
                'let r = h 3\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'effect_compound_meets_var',
        "files": {
            'main.pyfun': (
                'let k h c =\n'
                '  let loud x =\n'
                '    print x\n'
                '    h x\n'
                '  if c then loud else h\n'
                'let r = k (fun y -> ()) true 5\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'effect_compound_meets_var_io_callback',
        "files": {
            'main.pyfun': (
                'let k h c =\n'
                '  let loud x =\n'
                '    print x\n'
                '    h x\n'
                '  if c then loud else h\n'
                'let r = k print true 5\n'
                'let s = k print false 6\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'effect_widen_two_compounds',
        "files": {
            'main.pyfun': (
                'let k h g c =\n'
                '  let loud x =\n'
                '    print x\n'
                '    h x\n'
                '  let both x =\n'
                '    g x\n'
                '    h x\n'
                '  if c then loud else both\n'
                'let r = k (fun y -> ()) (fun z -> ()) false 7\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]

CODEC_CASES = [
    {
        'id': 'decode_auto_bool_unit_ref',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'type F = { on: bool, nothing: unit, pair: (P, P) }\n'
                'let f s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok v: if v.on then v.pair else (P { x = 0 }, P { x = 1 })\n'
                '    case Error _: (P { x = 2 }, P { x = 3 })\n'
                'print (f "{\\"on\\": true, \\"nothing\\": null, \\"pair\\": [{\\"x\\": 5}, {\\"x\\": 6}]}")\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_seq_field',
        "files": {
            'main.pyfun': (
                'type S = { xs: Seq int }\n'
                'let f s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok v: Seq.toList v.xs\n'
                '    case Error _: []\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_decoder_field',
        "files": {
            'main.pyfun': (
                'type D = { d: Decoder int }\n'
                'let f s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok v: v.d\n'
                '    case Error _: Decode.int\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_function_field',
        "files": {
            'main.pyfun': (
                'type D = { g: int -> int }\n'
                'let f s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok v: v.g 1\n'
                '    case Error _: 0\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_extern_type',
        "files": {
            'main.pyfun': (
                'extern type Conn\n'
                'type D = { c: Conn }\n'
                'let f s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok v: v.c\n'
                '    case Error e: f s\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'encode_auto_bool',
        "files": {
            'main.pyfun': (
                'print (Encode.auto [true, false])\n'
                'print (Encode.auto ())\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]

PROJECT_CASES = [
    {
        'id': 'imported_sum_type_clash_with_local',
        "files": {
            'main.pyfun': (
                'import Shapes\n'
                'type Shape = Square float\n'
                'let s = Shapes.Circle 1.0\n'
            ),
            'shapes.pyfun': 'type Shape = Circle float | Rect float float\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'two_imports_same_type_name',
        "files": {
            'main.pyfun': (
                'import Shapes\n'
                'import Other\n'
                'let s = Shapes.Circle 1.0\n'
            ),
            'shapes.pyfun': 'type Shape = Circle float\n',
            'other.pyfun': 'type Shape = Tri float\n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'carried_record_shadowed_by_local',
        "files": {
            'main.pyfun': (
                'import B\n'
                'type Placed = Red | Blue\n'
                'let l = B.h.item.letter\n'
            ),
            'a.pyfun': 'type Placed = { letter: string, score: int }\n',
            'b.pyfun': (
                'import A\n'
                'type Holder = { item: A.Placed }\n'
                'let h = Holder { item = A.Placed { letter = "q", score = 10 } }\n'
                'let score x = x.item.score\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'carried_record_shadowed_unknown_field',
        "files": {
            'main.pyfun': (
                'import B\n'
                'type Placed = Red | Blue\n'
                'let f x = x.letter\n'
            ),
            'a.pyfun': 'type Placed = { letter: string, score: int }\n',
            'b.pyfun': (
                'import A\n'
                'type Holder = { item: A.Placed }\n'
                'let h = Holder { item = A.Placed { letter = "q", score = 10 } }\n'
                'let score x = x.item.score\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'carried_record_two_paths',
        "files": {
            'main.pyfun': (
                'import B\n'
                'import C\n'
                'let s = B.h.item.score + C.b.inner.score\n'
                'print s\n'
            ),
            'a.pyfun': 'type Placed = { letter: string, score: int }\n',
            'b.pyfun': (
                'import A\n'
                'type Holder = { item: A.Placed }\n'
                'let h = Holder { item = A.Placed { letter = "q", score = 10 } }\n'
                'let score x = x.item.score\n'
            ),
            'c.pyfun': (
                'import A\n'
                'type Box = { inner: A.Placed }\n'
                'let b = Box { inner = A.Placed { letter = "z", score = 1 } }\n'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'carried_record_bare_construct',
        "files": {
            'main.pyfun': (
                'import B\n'
                'let p = Placed { letter = "y", score = 2 }\n'
            ),
            'a.pyfun': 'type Placed = { letter: string, score: int }\n',
            'b.pyfun': (
                'import A\n'
                'type Holder = { item: A.Placed }\n'
                'let h = Holder { item = A.Placed { letter = "q", score = 10 } }\n'
                'let score x = x.item.score\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'carried_record_bare_match',
        "files": {
            'main.pyfun': (
                'import B\n'
                'let f p =\n'
                '  match p:\n'
                '    case Placed { letter }: letter\n'
            ),
            'a.pyfun': 'type Placed = { letter: string, score: int }\n',
            'b.pyfun': (
                'import A\n'
                'type Holder = { item: A.Placed }\n'
                'let h = Holder { item = A.Placed { letter = "q", score = 10 } }\n'
                'let score x = x.item.score\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'carried_record_decode_auto',
        "files": {
            'main.pyfun': (
                'import B\n'
                'let f s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok o: B.score o\n'
                '    case Error _: 0\n'
            ),
            'a.pyfun': 'type Placed = { letter: string, score: int }\n',
            'b.pyfun': (
                'import A\n'
                'type Holder = { item: A.Placed }\n'
                'let h = Holder { item = A.Placed { letter = "q", score = 10 } }\n'
                'let score x = x.item.score\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'imported_mutable_and_mono_values',
        "files": {
            'main.pyfun': (
                'import Store\n'
                'let r = Store.counter + 1\n'
                'let xs = Store.items\n'
                'let g = Store.handler\n'
            ),
            'store.pyfun': (
                'let mut counter = 0\n'
                'let mut items = []\n'
                'let mut ratio = 1.5<m>\n'
                'measure m\n'
                'let mut handler = fun x -> x\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'imported_mono_values_v2',
        "files": {
            'main.pyfun': (
                'import Store\n'
                'let r = Store.counter + 1\n'
                'let xs = Store.items\n'
                'let g = Store.handler\n'
            ),
            'store.pyfun': (
                'measure m\n'
                'let mut counter = 0\n'
                'let mut items = []\n'
                'let mut speed = 2<m>\n'
                'let mut handler = fun x -> print x\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'imported_mono_unit_and_effect_vars',
        "files": {
            'main.pyfun': (
                'import Store\n'
                'let r = Store.scale 2.0\n'
                'let s = Store.apply (fun x -> x + 1)\n'
            ),
            'store.pyfun': (
                'let mut scale = fun x -> x * 2.0\n'
                'let mut apply = fun g -> g 1\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'callback_project_qualified',
        "files": {
            'main.pyfun': (
                'import Lib\n'
                'let r = Lib.each (fun x -> print x)\n'
            ),
            'lib.pyfun': 'extern each : (int -> unit) -> unit = m.each\n',
        },
        'args': ['check', 'main.pyfun'],
    },
]



@pytest.mark.parametrize("case", DECLARATION_CASES, ids=[c["id"] for c in DECLARATION_CASES])
def test_declarations_and_externs(run, workdir, case):
    """CATCHES: a checker that accepts a duplicate measure or type, mis-arities a type constructor
    in a field annotation, mishandles `^0` unit exponents, value externs or aliased `extern
    import`s, or accepts syntax the language does not have (lowercase type names, type
    annotations on bindings)."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", BINDING_CASES, ids=[c["id"] for c in BINDING_CASES])
def test_bindings_recursion_and_holes(run, workdir, case):
    """CATCHES: errors inside mutually recursive groups or in-file module members that are dropped,
    reported twice or at the wrong span; `let pure` not enforced across a recursive group;
    assignment to an unbound name accepted; wrong type-variable naming past `'z`; wrong unit
    rendering (`1/s`); or typed-hole notes whose fit ranking ignores the hole's name."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", ACTIVE_PATTERN_CASES, ids=[c["id"] for c in ACTIVE_PATTERN_CASES])
def test_active_patterns(run, workdir, case):
    """CATCHES: an active-pattern implementation that infers case arities from only some body
    constructs, accepts nested or mixed active-pattern arms, accepts non-variable case
    binders or non-literal parameter arguments, reports binder-count errors without their
    hints, or runs a valid recognizer differently."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", RECORD_CASES, ids=[c["id"] for c in RECORD_CASES])
def test_records_and_fields(run, workdir, case):
    """CATCHES: record construction/update checks that allow a field twice, a direct and a sub-
    field update together, or an update through a non-record field; deferred field accesses
    resolved against the wrong record; or constructor-arity errors in patterns."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", PATTERN_CASES, ids=[c["id"] for c in PATTERN_CASES])
def test_patterns_and_exhaustiveness(run, workdir, case):
    """CATCHES: an exhaustiveness checker that misses (or invents) a case, prints a different
    witness for literal, tuple, record, list and as-patterns, or lets an or-pattern bind a
    variable in only some alternatives or at two different types."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", COMPARISON_CASES, ids=[c["id"] for c in COMPARISON_CASES])
def test_structural_comparison(run, workdir, case):
    """CATCHES: ordering checks that accept comparing functions, sets or extern handles, reject
    Option or recursive user types, or never stop on a pathologically nested type."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", EFFECT_CASES, ids=[c["id"] for c in EFFECT_CASES])
def test_effects_and_callbacks(run, workdir, case):
    """CATCHES: effect inference that mis-unifies latent effects (a compound effect meeting a bare
    variable, two open effects widening), or a callback-effect diagnostic that names the
    wrong owner, arrow, argument or suggested `->{e}` signature."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", CODEC_CASES, ids=[c["id"] for c in CODEC_CASES])
def test_derived_codecs(run, workdir, case):
    """CATCHES: `Decode.auto`/`Encode.auto` derivation that accepts a lazy `Seq`, a `Decoder`, a
    function or an extern type field, or that decodes bool/unit fields and repeated record
    types incorrectly."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", PROJECT_CASES, ids=[c["id"] for c in PROJECT_CASES])
def test_module_interfaces(run, workdir, case):
    """CATCHES: a multi-module checker that lets an imported type silently clash with a local or
    another imported one, exposes or hides a transitively carried record wrongly
    (construction, matching, decoding, field hints), breaks on mutable/monomorphic imported
    values, or loses the qualified owner name in a callback diagnostic."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
