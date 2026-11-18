"""`pyfun check <file>` on ill-typed or malformed programs: the exact rustc-style diagnostics.

The Pyfun programs below were harvested from the project's own unit tests (tests/typecheck.rs, tests/compile.rs, tests/roundtrip.rs) and are
written into the empty working directory as `main.pyfun` before each run. Expected
transcripts (exit code, stdout, stderr) were captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

CHECK_CASES = [
    {
        'id': 'extern_with_name_equal_target_needs_no_import',
        "files": {
            'main.pyfun': 'import',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'irrefutable_newtype_case_truncates_later_arms_and_the_guard',
        "files": {
            'main.pyfun': 'raise RuntimeError("non-exhaustive match")',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_unit_parameter_contributes_no_argument_wherever_it_sits',
        "files": {
            'main.pyfun': 'print(max(3, 5))',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'an_undecidable_target_is_rejected_rather_than_guessed',
        "files": {
            'main.pyfun': (
                'extern get: string -> a = urllib.request.urlopen\n'
                'let r = get "x"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_capitalised_segment_needs_no_declaration',
        "files": {
            'main.pyfun': (
                'extern type P\n'
                'extern read: P -> string = pathlib.Path.read_text\n'
                'let r = read p'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_rejects_a_type_with_no_argument_to_spare',
        "files": {
            'main.pyfun': 'extern bad : string -> a = f(x=..., y=...)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_rejects_a_type_with_no_argument_to_spare_2',
        "files": {
            'main.pyfun': 'extern bad : string -> a = .attr(k=...)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_rejects_a_type_with_no_argument_to_spare_3',
        "files": {
            'main.pyfun': 'extern bad : unit -> a = time.time(tz=...)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'e2e_target_311_format_rewrite_runs_identically',
        "files": {
            'main.pyfun': (
                '\n'
                'print(r)\n'
                'print(brace)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_constructor_is_rejected',
        "files": {
            'main.pyfun': 'let f o = match o: case Nope v: v',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_ce_produces_a_generator',
        "files": {
            'main.pyfun': (
                '\n'
                'print(list(xs))\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_effectful_recursive_loop_runs',
        "files": {
            'main.pyfun': (
                '\n'
                'print(done)\n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_module_level_capture_colliding_with_a_global_read_is_r',
        "files": {
            'main.pyfun': 'print(x)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unit_in_arithmetic',
        "files": {
            'main.pyfun': 'let bad = () + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'recursive_function_has_the_expected_type',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)\n'
                'let bad = fact true'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'value_binding_still_cannot_self_refer',
        "files": {
            'main.pyfun': 'let x = x + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'accepts_mutual_recursion',
        "files": {
            'main.pyfun': (
                'let a = b\n'
                'let b = a'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_composition_of_incompatible_functions',
        "files": {
            'main.pyfun': (
                'let f = String.len >> String.upper\n'
                'let r = f "x"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'as_patterns_are_transparent_for_exhaustiveness',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let f s =\n'
                '  match s:\n'
                '    case Circle r as w: r'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'accepts_discard_binding',
        "files": {
            'main.pyfun': 'let _ a = a',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'accepts_discard_binding_2',
        "files": {
            'main.pyfun': 'let mut _ = 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'accepts_string_slice_and_index_of',
        "files": {
            'main.pyfun': 'let r = String.slice "a" 3 "hello"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'exponentiation_is_float_only_and_dimensionless',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let r = 2.0<m> ** 2.0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'exponentiation_is_float_only_and_dimensionless_2',
        "files": {
            'main.pyfun': 'let r = true ** 2.0',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'exponentiation_is_float_only_and_dimensionless_3',
        "files": {
            'main.pyfun': 'let r = List.get (2 ** 3) [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_bind_requires_an_option_returning_function',
        "files": {
            'main.pyfun': 'let r = Option.bind (fun x -> x + 1) (Some 1)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'round_preserves_units',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let r = round 2.5<m>\n'
                'let bad = r + 1<s>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_sqrt_of_an_odd_exponent_unit',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let bad = sqrt 2.0<m^3>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_sqrt_of_a_bare_unit',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let bad = sqrt 2.0<m>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'sqrt_of_dimensionless_float_is_dimensionless',
        "files": {
            'main.pyfun': 'let bad = sqrt (List.len [1, 2])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_cbrt_of_a_non_cube_unit',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let bad = cbrt 4.0<m^2>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_cbrt_of_a_non_cube_unit_2',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let bad = cbrt 2.0<m>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_cbrt_of_a_non_cube_unit_3',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let bad = cbrt 2.0<m^4>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'cbrt_of_dimensionless_float_is_dimensionless',
        "files": {
            'main.pyfun': 'let bad = cbrt (List.len [1, 2])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_non_square_unit_equation_errors_instead_of_hanging',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let sq x = x * x\n'
                'let f x = sq x == 5.0<m^3>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'accepts_scientific_notation',
        "files": {
            'main.pyfun': 'let r = List.get 1e6 [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_list_ops',
        "files": {
            'main.pyfun': 'let r = List.sort [true, false]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_list_ops_2',
        "files": {
            'main.pyfun': 'let r = List.get "x" [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_list_ops_3',
        "files": {
            'main.pyfun': 'let r = List.contains "a" [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_choose_and_collect',
        "files": {
            'main.pyfun': 'let r = List.choose (fun x -> x * 10) [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_choose_and_collect_2',
        "files": {
            'main.pyfun': 'let r = List.collect (fun x -> Some x) [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'choose_and_collect_are_effect_polymorphic',
        "files": {
            'main.pyfun': 'let pure f xs = List.choose (fun x -> Some (print x)) xs',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_modulo',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let r = 10<m> % 3<s>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_modulo_2',
        "files": {
            'main.pyfun': 'let r = "a" % "b"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_chained_comparisons',
        "files": {
            'main.pyfun': 'let x = 1 < 2 < true',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ill_typed_chained_comparisons_2',
        "files": {
            'main.pyfun': 'let x = true < false < true',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_negation_of_non_numeric',
        "files": {
            'main.pyfun': 'let x = -true',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_negation_of_non_numeric_2',
        "files": {
            'main.pyfun': 'let x = -"hi"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'operator_section_carries_the_operators_constraint',
        "files": {
            'main.pyfun': 'let r = (+) true false',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'operator_section_carries_the_operators_constraint_2',
        "files": {
            'main.pyfun': 'let r = (<) true false',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_redefining_builtin_result',
        "files": {
            'main.pyfun': 'type Result a b = Ok a | Bad b',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_newtype_where_underlying_expected',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let bad = String.len (UserId "x")'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_underlying_where_newtype_expected',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let name u =\n'
                '  match u:\n'
                '    case UserId s: s\n'
                'let bad = name "raw"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_exhaustive_newtype_match',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let f u =\n'
                '  match u:\n'
                '    case UserId "root": 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_duplicate_opaque_type_declaration',
        "files": {
            'main.pyfun': (
                'opaque type X = int\n'
                'opaque type X = int'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_underlying_type',
        "files": {
            'main.pyfun': 'opaque type X = Nope',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_opaque_type_clashing_with_an_existing_type',
        "files": {
            'main.pyfun': (
                'type X = A | B\n'
                'opaque type X = int'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_argument_type_mismatch',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let r = add 1 true'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_bool_condition',
        "files": {
            'main.pyfun': 'let r = if 1 then 2 else 3',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_branch_type_mismatch',
        "files": {
            'main.pyfun': 'let r = if true then 1 else "x"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unbound_name',
        "files": {
            'main.pyfun': 'let r = nope',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_infinite_type',
        "files": {
            'main.pyfun': 'let bad = fun x -> x x',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_match_arm_result_mismatch',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: 1\n'
                '    case _: "two"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_constructor',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Nope v: v'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_exhaustive_adt_match',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some v: v'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_exhaustive_int_match',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'reports_nested_witness_for_missing_inner_constructor',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some true: 1\n'
                '    case None: 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_empty_only_list_match_with_cons_witness',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_singleton_only_list_match_with_nil_witness',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [x]: x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'list_pattern_element_type_is_enforced',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [1, *r]: r\n'
                '    case _: xs\n'
                'let bad = f [true, false]'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'refutable_suffix_element_reports_a_concrete_witness',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [*_, None]: 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'reports_record_witness_for_missing_field_combination',
        "files": {
            'main.pyfun': (
                'type P = { x: bool, y: bool }\n'
                'let f p =\n'
                '  match p:\n'
                '    case P { x = true, y = true }: 1\n'
                '    case P { x = true, y = false }: 2\n'
                '    case P { x = false, y = true }: 3'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deep_check_still_requires_wildcard_for_open_inner_type',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some 0: 1\n'
                '    case None: 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_constructor_used_at_wrong_type',
        "files": {
            'main.pyfun': 'let r = (Some 1) + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_type_in_field',
        "files": {
            'main.pyfun': 'type Bad = Mk Nope',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_yield_in_result_block',
        "files": {
            'main.pyfun': 'let a = result { yield 1 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_result_without_return',
        "files": {
            'main.pyfun': 'let a = result { let! x = Ok 1 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_return_before_end',
        "files": {
            'main.pyfun': 'let a = result { return 1  return 2 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_for_body_cannot_return_and_a_for_source_must_be_a_collecti',
        "files": {
            'main.pyfun': (
                'let r = result {\n'
                '  for x in [1]:\n'
                '    return x\n'
                '}'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_for_body_cannot_return_and_a_for_source_must_be_a_collecti_2',
        "files": {
            'main.pyfun': 'let s = seq { for x in 3: yield x }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_for_body_cannot_return_and_a_for_source_must_be_a_collecti_3',
        "files": {
            'main.pyfun': 'let s = seq { for x in [1]: yield x  yield "s" }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_seq_with_return',
        "files": {
            'main.pyfun': 'let a = seq { return 5 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_user_ce_missing_builder_member',
        "files": {
            'main.pyfun': (
                'module Bad =\n'
                '  let return_ x = Some x\n'
                'let r =\n'
                '  Bad {\n'
                '    let! x = Some 1\n'
                '    return x\n'
                '  }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_binding_wrong_monad',
        "files": {
            'main.pyfun': 'let a = async { let! x = (seq { yield 1 })  return x }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_adding_different_units',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let bad = 1<m> + 1<s>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'derived_measure_dimension_mismatch_shows_expansion',
        "files": {
            'main.pyfun': (
                'measure kg\n'
                'measure m\n'
                'measure s\n'
                'measure N = kg m / s^2\n'
                'let bad = 1<N> + 1<m>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_measure_in_alias_body',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure Bad = m / xyz'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_alias_used_before_definition',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure Speed = Accel s\n'
                'measure Accel = m / s^2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unit_result_used_at_wrong_unit',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let speed = 100<m> // 10<s>\n'
                'let bad = speed + 1<m>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_mixing_concrete_int_and_float',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: n\n'
                '    case _: n\n'
                'let r = 1.0 + f 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_measure',
        "files": {
            'main.pyfun': 'let x = 5<furlong>',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_min_across_different_units',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let bad = min 3<m> 5<s>'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_comparison_of_unorderable_type',
        "files": {
            'main.pyfun': 'let r = true < false',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_comparison_of_unorderable_type_2',
        "files": {
            'main.pyfun': (
                'let id x = x\n'
                'let bad = id < id'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_equality_across_different_types',
        "files": {
            'main.pyfun': 'let r = 1 == "x"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ordering_of_a_list_with_an_unorderable_element',
        "files": {
            'main.pyfun': 'let bad = [()] < [()]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ordering_of_a_record_with_an_unorderable_field',
        "files": {
            'main.pyfun': (
                'type H = { run: int -> int }\n'
                'let mk = H { run = fun x -> x }\n'
                'let bad = mk < mk'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_ordering_of_a_parameterized_type_at_an_unorderable_a',
        "files": {
            'main.pyfun': (
                'type Box a = { item: a }\n'
                'let mk = Box { item = fun x -> x }\n'
                'let bad = mk < mk'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_builtin_option_and_result',
        "files": {
            'main.pyfun': (
                'let bad a b = a < b\n'
                'let t = bad (Some (fun n -> n)) (Some (fun n -> n))'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'deferred_ordering_constraint_flows_to_a_concrete_adt',
        "files": {
            'main.pyfun': (
                'type F = Fn (int -> int)\n'
                'let lt a b = a < b\n'
                'let r = lt (Fn (fun x -> x)) (Fn (fun x -> x))'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_bool_logical_operands',
        "files": {
            'main.pyfun': 'let r = 1 and true',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_bool_logical_operands_2',
        "files": {
            'main.pyfun': 'let r = true or 2',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_bool_logical_operands_3',
        "files": {
            'main.pyfun': 'let r = not 5',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_missing_record_field',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_field_in_literal',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = 2, z = 3 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_field_access',
        "files": {
            'main.pyfun': (
                'type Point = { x: int }\n'
                'let p = Point { x = 1 }\n'
                'let z = p.nope'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_field_access_on_an_unknown_base',
        "files": {
            'main.pyfun': (
                'type Point = { x: int }\n'
                'let z p = p.nope'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_wrong_record_field_type',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = true }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_bare_access_of_a_shared_field_is_ambiguous',
        "files": {
            'main.pyfun': (
                'type A = { x: int }\n'
                'type B = { x: int }\n'
                'let get p = p.x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_known_record_missing_the_field_is_reported_against_that_re',
        "files": {
            'main.pyfun': (
                'type A = { x: int }\n'
                'type B = { y: int }\n'
                'let b = B { y = 1 }\n'
                'let oops = b.x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_near_miss_field_on_a_known_record_suggests_the_real_one',
        "files": {
            'main.pyfun': (
                'type Cell = { letter: string }\n'
                'let c = Cell { letter = "a" }\n'
                'let l = c.leter'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_field_declared_twice_in_one_record',
        "files": {
            'main.pyfun': 'type P = { x: int, x: int }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'set_max_and_min_answer_with_option',
        "files": {
            'main.pyfun': (
                'let m = Set.max (Set.ofList [1])\n'
                'let bad = m + 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'set_subset_checks_take_two_sets',
        "files": {
            'main.pyfun': 'let bad = Set.isSubset (Set.ofList [1]) [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'map_union_needs_two_maps_of_one_type',
        "files": {
            'main.pyfun': 'let bad = Map.union (Map.ofList [(1, "a")]) (Map.ofList [(2, 3)])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'map_and_set_traversals_carry_their_effect',
        "files": {
            'main.pyfun': 'let pure go = Set.map (fun x -> print x) (Set.ofList [1])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'map_and_set_traversals_carry_their_effect_2',
        "files": {
            'main.pyfun': 'let pure go = Map.map (fun k v -> print v) (Map.ofList [(1, 2)])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'string_members_stay_monomorphic_over_string',
        "files": {
            'main.pyfun': 'let bad = String.repeat 2 3',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'string_get_answers_with_option_like_list_get',
        "files": {
            'main.pyfun': (
                'let c = String.get 0 "abc"\n'
                'let bad = String.len c'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'string_of_list_inverts_to_list',
        "files": {
            'main.pyfun': 'let bad = String.ofList [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_deferred_field_is_still_type_checked',
        "files": {
            'main.pyfun': (
                'type Placed = { row: int, letter: string }\n'
                'type Cell = { row: int, letter: string, blank: bool }\n'
                'let bad c =\n'
                '    let l = c.letter\n'
                '    let flag = c.blank\n'
                '    l + 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_deferred_field_must_exist_on_the_record_that_wins',
        "files": {
            'main.pyfun': (
                'type Cell = { letter: string, blank: bool }\n'
                'type Tile = { letter: string, score: int }\n'
                'let bad c =\n'
                '    let s = c.score\n'
                '    let flag = c.blank\n'
                '    s'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_field_on_a_value_nothing_pins_is_still_ambiguous',
        "files": {
            'main.pyfun': (
                'type Placed = { row: int, letter: string }\n'
                'type Cell = { row: int, letter: string, blank: bool }\n'
                'let get c = c.letter'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect',
        "files": {
            'main.pyfun': 'let r = List.map2 (fun a b -> log (a + b)) [1] [2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_2',
        "files": {
            'main.pyfun': 'let r = List.reduce (fun a b -> log (a + b)) [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_3',
        "files": {
            'main.pyfun': 'let r = Seq.fold (fun acc x -> log (acc + x)) 0 (Seq.ofList [1])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_4',
        "files": {
            'main.pyfun': 'let r = Set.fold (fun acc x -> log (acc + x)) 0 (Set.ofList [1])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_5',
        "files": {
            'main.pyfun': 'let r = Map.map (fun k v -> log v) (Map.ofList [(1, 2)])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_6',
        "files": {
            'main.pyfun': (
                'let r = Map.fold (fun acc k v -> log (acc + v)) 0 (Map.ofList [(1, 2)])'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_7',
        "files": {
            'main.pyfun': 'let r = Map.iter (fun k v -> ignore (log v)) (Map.ofList [(1, 2)])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_8',
        "files": {
            'main.pyfun': 'let r = Option.map2 (fun a b -> log (a + b)) (Some 1) (Some 2)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'every_multi_argument_callback_member_takes_an_effect_9',
        "files": {
            'main.pyfun': 'let r = Result.map2 (fun a b -> log (a + b)) (Ok 1) (Ok 2)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'sign_is_a_number_to_an_int',
        "files": {
            'main.pyfun': 'let bad = sign "x"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_map2_combines_two_options',
        "files": {
            'main.pyfun': 'let bad = Option.map2 (fun a b -> a + b) (Some 1) (Some "x")',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_or_else_takes_the_fallback_first',
        "files": {
            'main.pyfun': 'let bad = Option.orElse (Some 1) (Some "x")',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_flatten_collapses_one_level',
        "files": {
            'main.pyfun': 'let bad = Option.flatten (Some 1)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'result_map2_keeps_one_error_type',
        "files": {
            'main.pyfun': 'let bad = Result.map2 (fun a b -> a + b) (Error "x") (Error 2)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_and_result_iter_carry_their_effect',
        "files": {
            'main.pyfun': 'let pure go = Option.iter (fun x -> print x) (Some 1)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_and_result_iter_carry_their_effect_2',
        "files": {
            'main.pyfun': 'let pure go = Result.iter (fun x -> print x) (Ok 1)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_and_list_members_do_not_mix',
        "files": {
            'main.pyfun': 'let bad = Seq.drop 1 [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_and_list_members_do_not_mix_2',
        "files": {
            'main.pyfun': 'let bad = List.drop 1 (Seq.ofList [1, 2])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_can_be_endless',
        "files": {
            'main.pyfun': 'let s = Seq.toList (Seq.unfold (fun n -> (n, n + 1)) 0)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_consuming_members_answer_plain_values',
        "files": {
            'main.pyfun': (
                'let h = Seq.head (Seq.ofList [1])\n'
                'let bad = h + 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_iter_carries_the_effect_of_its_function',
        "files": {
            'main.pyfun': 'let pure go = Seq.iter (fun x -> print x) (Seq.ofList [1])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'list_map2_pairs_two_lists',
        "files": {
            'main.pyfun': 'let bad = List.map2 (fun a b -> a + b) [1, 2] ["x"]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'list_aggregates_that_can_be_empty_answer_with_option',
        "files": {
            'main.pyfun': (
                'let a = List.average [1.0]\n'
                'let bad = a + 1.0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'list_aggregates_that_can_be_empty_answer_with_option_2',
        "files": {
            'main.pyfun': (
                'let r = List.reduce (fun a b -> a + b) [1]\n'
                'let bad = r + 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'list_average_takes_floats',
        "files": {
            'main.pyfun': 'let a = List.average ["x"]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'list_iter_carries_the_effect_of_its_function',
        "files": {
            'main.pyfun': 'let pure go = List.iter (fun x -> print x) [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'fst_and_snd_project_a_pair',
        "files": {
            'main.pyfun': 'let bad = fst 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_refutable_record_pattern_without_wildcard',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p =\n'
                '  match p:\n'
                '    case Point { x = 0 }: 1\n'
                '    case Point { x = 1 }: 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_unknown_field_in_pattern',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p =\n'
                '  match p:\n'
                '    case Point { x = 0, z = 1 }: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_field_matched_twice_in_pattern',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p =\n'
                '  match p:\n'
                '    case Point { x = 0, x = 1 }: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_record_pattern_field_type_mismatch',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p =\n'
                '  match p:\n'
                '    case Point { x = true }: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_update_of_unrelated_field',
        "files": {
            'main.pyfun': (
                'type Point = { x: int }\n'
                'type Other = { y: int }\n'
                'let p = Point { x = 1 }\n'
                'let bad = { p with y = 2 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_assigning_immutable_binding',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '    let y = 0\n'
                '    y <- x\n'
                '    y'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_reassignment_with_wrong_type',
        "files": {
            'main.pyfun': (
                'let mut x = 0\n'
                'x <- true'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_mutable_binding_with_parameters',
        "files": {
            'main.pyfun': 'let mut f x = x',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_unit_intermediate_statement',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '    x + 1\n'
                '    x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_pure_binding_that_prints',
        "files": {
            'main.pyfun': 'let pure greet n = print n',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_pure_binding_that_mutates',
        "files": {
            'main.pyfun': (
                'let pure f x =\n'
                '    let mut acc = x\n'
                '    acc <- acc + 1\n'
                '    acc'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'io_propagates_through_calls',
        "files": {
            'main.pyfun': (
                'let shout n = print n\n'
                'let pure bad n = shout n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'annotated_async_extern_carries_the_async_label',
        "files": {
            'main.pyfun': (
                'extern fetch: string ->{async} Async string = httpx.get\n'
                'let pure go u = fetch u'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'an_async_extern_must_return_the_async_type',
        "files": {
            'main.pyfun': 'extern sleep: float ->{async} unit = asyncio.sleep',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'an_async_extern_must_return_the_async_type_2',
        "files": {
            'main.pyfun': 'extern get: string ->{async} List string = client.get',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'the_async_module_members_type_as_declared',
        "files": {
            'main.pyfun': 'let pure go x = Async.toThread (fun _ -> print x)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'task_scope_discharges_the_spawn_that_start_performs',
        "files": {
            'main.pyfun': 'let bad = Task.start (Async.sleep 1.0)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'task_scope_discharges_the_spawn_that_start_performs_2',
        "files": {
            'main.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let sneaky n = async { Task.start (Async.sleep 1.0) }\n'
                'let r = runAsync (sneaky 0)'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'task_scope_discharges_the_spawn_that_start_performs_3',
        "files": {
            'main.pyfun': 'let pure go x = Task.start (Async.sleep 1.0)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'task_scope_discharges_the_spawn_that_start_performs_4',
        "files": {
            'main.pyfun': 'let s = Task.scope (fun scope -> async { return 1 })',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_trailing_unit_expression_ends_a_monad_block',
        "files": {
            'main.pyfun': 'let o = option { 1 + 1 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_is_pinned_by_a_later_use_and_open_otherwise',
        "files": {
            'main.pyfun': 'let loose = Decode.decodeString Decode.auto "1"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_is_pinned_by_a_later_use_and_open_otherwise_2',
        "files": {
            'main.pyfun': (
                'let f = Decode.decodeString Decode.auto "1"\n'
                'let g = match f:\n'
                '  case Ok h: h 1\n'
                '  case Error _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_is_pinned_by_a_later_use_and_open_otherwise_3',
        "files": {
            'main.pyfun': (
                'extern type Conn\n'
                'extern use: Conn -> int = m.use\n'
                'let r = Decode.decodeString Decode.auto "1"\n'
                'let n = match r:\n'
                '  case Ok c: use c\n'
                '  case Error _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'async_ce_block_performs_the_async_effect',
        "files": {
            'main.pyfun': 'let pure go x = async { return x }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'async_ce_and_print_union_to_io_async',
        "files": {
            'main.pyfun': (
                'let pure go x =\n'
                '    print x\n'
                '    async { return x }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'labels_union_across_calls_and_display_in_canonical_order',
        "files": {
            'main.pyfun': (
                'extern fetch: string ->{async} Async string = httpx.get\n'
                'let pure shout u =\n'
                '    print u\n'
                '    fetch u'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'format_fixed_rejects_a_non_numeric_amount',
        "files": {
            'main.pyfun': 'let bad = Format.fixed 2 "nope"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'declared_io_arrow_in_a_type_decl_flows_through_matching',
        "files": {
            'main.pyfun': (
                'type Handler = H (string ->{io} unit)\n'
                'let pure run h =\n'
                '  match h:\n'
                '    case H f: f "x"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'declared_effect_arrows_are_exact_no_subeffecting',
        "files": {
            'main.pyfun': (
                'type Handler = H (string ->{io} unit)\n'
                'let h = H (fun s -> ())'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'annotation_on_an_argument_arrow_keeps_the_boundary_io_defaul',
        "files": {
            'main.pyfun': (
                'extern register: (string ->{io} unit) -> unit = hub.register\n'
                'let pure setup f = register f'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_an_unknown_effect_label',
        "files": {
            'main.pyfun': 'type Spook = S (string ->{spooky} unit)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_closed_callback_arrow_points_at_the_effect_variable',
        "files": {
            'main.pyfun': (
                'extern type Writer\n'
                'extern type Server\n'
                'extern closeConn: Writer -> unit = .close()\n'
                'extern serve: (Writer -> Async unit) -> int -> Async Server = asyncio.start_server\n'
                'let handle w = async { closeConn w }\n'
                'let listen = serve handle 7777'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'pasting_the_inferred_set_into_the_callback_still_points_at_t',
        "files": {
            'main.pyfun': (
                'extern type Writer\n'
                'extern type Server\n'
                'extern serve: (Writer ->{io, async} Async unit) -> int -> Async Server = asyncio.start_server\n'
                'let idle w = async { return () }\n'
                'let listen = serve idle 7777'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_callback_of_the_wrong_type_keeps_its_type_mismatch',
        "files": {
            'main.pyfun': (
                'extern type Writer\n'
                'extern type Server\n'
                'extern serve: (Writer -> Async unit) -> int -> Async Server = asyncio.start_server\n'
                'let listen = serve 5 7777'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'io_callback_through_an_effect_var_extern_defeats_pure',
        "files": {
            'main.pyfun': (
                'extern pure app: (a ->{e} b) -> a ->{e} b = mymod.app\n'
                'let pure bad = app (fun x -> print x) 3'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'label_plus_effect_var_innermost_keeps_io_even_for_a_pure_cal',
        "files": {
            'main.pyfun': (
                'extern each: (a ->{e} unit) -> List a ->{io, e} unit = mymod.each\n'
                'let pure bad = each (fun x -> ()) [1]'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'uppercase_name_in_an_extern_arrow_is_not_an_effect_var',
        "files": {
            'main.pyfun': 'extern bad: (a ->{E} unit) -> unit = mymod.bad',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_an_effect_var_in_a_record_field',
        "files": {
            'main.pyfun': 'type Callbacks = { onData: string ->{e} unit }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_heterogeneous_list',
        "files": {
            'main.pyfun': 'let bad = [1, true]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'tuple_elements_keep_their_own_types',
        "files": {
            'main.pyfun': (
                'let t = (1, "x")\n'
                'let second =\n'
                '  match t:\n'
                '    case (a, b): b\n'
                'let bad = second + 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_tuple_arity_mismatch',
        "files": {
            'main.pyfun': (
                'let f p =\n'
                '  match p:\n'
                '    case (a, b): a\n'
                'let bad = f (1, 2, 3)'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_parameter_types_its_elements',
        "files": {
            'main.pyfun': (
                'let tileScore (t, sq) = t * sq\n'
                'let bad = tileScore (3, "x")'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_parameter_rejects_the_wrong_arity',
        "files": {
            'main.pyfun': (
                'let f (a, b) = a\n'
                'let bad = f (1, 2, 3)'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_record_parameter_rejects_a_field_the_record_lacks',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int }\n'
                'let f (Cell { nope }) = nope'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_sum_constructor_is_not_a_record_parameter',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Square float\n'
                'let f (Circle { r }) = r'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'tuple_type_displays_with_parentheses',
        "files": {
            'main.pyfun': 'let bad = (1, 2) + 3',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_non_exhaustive_tuple_match_with_witness',
        "files": {
            'main.pyfun': (
                'let f p =\n'
                '  match p:\n'
                '    case (true, b): b'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_len_on_a_non_list',
        "files": {
            'main.pyfun': 'let n = List.len 5',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'map_preserves_element_type_change',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'let bad = List.sum (List.map show [1, 2])'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'map_of_an_impure_function_is_impure',
        "files": {
            'main.pyfun': 'let pure shoutAll xs = List.map (fun x -> print x) xs',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'input_is_a_prelude_builtin_with_the_io_effect',
        "files": {
            'main.pyfun': 'let pure ask u = input "? "',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'input_is_a_prelude_builtin_with_the_io_effect_2',
        "files": {
            'main.pyfun': 'let x = input 3',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_redefining_builtin_list',
        "files": {
            'main.pyfun': 'type List a = Empty | More a',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'exception_type_is_reserved',
        "files": {
            'main.pyfun': 'type Exception = Boom',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'string_literal_patterns_typecheck_over_strings',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case "x": 1\n'
                '    case _: 0\n'
                'let r = f 5'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'string_match_needs_a_wildcard_to_be_exhaustive',
        "files": {
            'main.pyfun': (
                'let f s =\n'
                '  match s:\n'
                '    case "a": 1\n'
                '    case "b": 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'interpolation_hole_must_be_well_typed',
        "files": {
            'main.pyfun': 'let m = f"value {missing}"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'interpolation_hole_must_be_well_typed_2',
        "files": {
            'main.pyfun': 'let m = f"{1 + "x"}"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'interpolation_debug_hole_is_an_ordinary_hole',
        "files": {
            'main.pyfun': 'let m = f"{missing=}"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'interpolation_debug_hole_is_an_ordinary_hole_2',
        "files": {
            'main.pyfun': (
                'let x = 1\n'
                'let m = f"{x==y}"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'interpolation_propagates_hole_effects',
        "files": {
            'main.pyfun': 'let pure shout x = f"{print x}"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_string_is_a_string',
        "files": {
            'main.pyfun': (
                'let n = 1 + """a\n'
                'b"""'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_fstring_types_and_effects_match_the_single_lin',
        "files": {
            'main.pyfun': (
                'let m = f"""value {missing}\n'
                '"""'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_fstring_types_and_effects_match_the_single_lin_2',
        "files": {
            'main.pyfun': (
                'let pure shout x = f"""{print x}\n'
                '"""'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'string_len_rejects_a_non_string',
        "files": {
            'main.pyfun': 'let n = String.len 5',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_member_suggests_the_closest_name',
        "files": {
            'main.pyfun': 'let r = String.startswith "a" "b"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_member_suggests_the_closest_name_2',
        "files": {
            'main.pyfun': 'let r = String.UPPER "x"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_member_suggests_the_closest_name_3',
        "files": {
            'main.pyfun': 'let n = String.length "x"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_member_with_no_close_name_gives_no_suggestion',
        "files": {
            'main.pyfun': 'let r = String.frobnicate "x"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'did_you_mean_works_for_user_modules_too',
        "files": {
            'main.pyfun': (
                'module Geom =\n'
                '  let area w h = w * h\n'
                'let x = Geom.aera 2 3'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_map_of_list_from_a_non_pair_list',
        "files": {
            'main.pyfun': 'let bad = Map.ofList [1, 2, 3]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'set_element_type_is_enforced',
        "files": {
            'main.pyfun': 'let bad = Set.add "x" (Set.ofList [1, 2])',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'map_find_or_default_must_match_the_value_type',
        "files": {
            'main.pyfun': (
                'let m = Map.add "a" "x" Map.empty\n'
                'let bad = Map.findOr "a" 0 m'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'bare_module_name_is_an_error',
        "files": {
            'main.pyfun': 'let x = List',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_module_member_is_rejected',
        "files": {
            'main.pyfun': 'let x = List.nope [1]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_redefining_builtin_option',
        "files": {
            'main.pyfun': 'type Option a = None | Some a',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'result_map_changes_the_ok_type',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'let r = Ok 1\n'
                'let bad = Result.withDefault 0 (Result.map show r)'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_take_returns_a_seq_not_a_list',
        "files": {
            'main.pyfun': 'let bad = List.len (Seq.take 2 (Seq.range 0 9))',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'seq_and_list_are_distinct_types',
        "files": {
            'main.pyfun': 'let bad = List.len (Seq.map (fun x -> x) (Seq.range 0 3))',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_redefining_builtin_map_and_set',
        "files": {
            'main.pyfun': 'type Set a = Empty',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_redefining_builtin_map_and_set_2',
        "files": {
            'main.pyfun': 'type Map a = Empty',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'module_members_are_not_visible_unqualified_outside',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let area r = r\n'
                'let bad = area 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'qualified_member_type_is_enforced',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let inc n = n + 1\n'
                'let bad = M.inc true'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'unknown_module_member_is_rejected_for_user_modules',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let x = 1\n'
                'let bad = M.nope'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'bare_user_module_reference_is_an_error',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let x = 1\n'
                'let bad = M'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_redefining_a_builtin_module',
        "files": {
            'main.pyfun': (
                'module List =\n'
                '  let x = 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_duplicate_module',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let x = 1\n'
                'module M =\n'
                '  let y = 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'extern_is_type_checked_at_the_call_site',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let bad = tan "x"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'extern_boundary_is_effectful_by_default',
        "files": {
            'main.pyfun': (
                'extern readLine: string -> string\n'
                'let pure ask q = readLine q'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_extern_redefining_an_existing_name',
        "files": {
            'main.pyfun': (
                'extern print: string -> unit\n'
                'let r = print "hi"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_extern_redefining_an_existing_name_2',
        "files": {
            'main.pyfun': (
                'extern pure sqrt: float -> float = math.sqrt\n'
                'let r = sqrt 2.0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'extern_import_parses_and_binds_no_pyfun_name',
        "files": {
            'main.pyfun': (
                'extern import datetime\n'
                'let x = datetime'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_extern_import_without_a_module',
        "files": {
            'main.pyfun': 'extern import',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_extern_import_with_a_trailing_dot',
        "files": {
            'main.pyfun': 'extern import urllib.',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_extern_import_as_without_an_alias',
        "files": {
            'main.pyfun': 'extern import numpy as',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'const_returns_the_first_argument_type',
        "files": {
            'main.pyfun': 'let bad = (const true 5) + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'ignore_yields_unit',
        "files": {
            'main.pyfun': 'let bad = ignore 3 + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'flip_is_effect_polymorphic',
        "files": {
            'main.pyfun': (
                'let logAdd a b =\n'
                '  print a\n'
                '  a + b\n'
                'let pure bad = flip logAdd 1 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_hole_infers_its_type_from_context',
        "files": {
            'main.pyfun': 'let f = ?body + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_hole_infers_its_type_from_context_2',
        "files": {
            'main.pyfun': 'let f = String.concat ? "!"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_hole_infers_its_type_from_context_3',
        "files": {
            'main.pyfun': 'let f xs = List.map ? xs',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_hole_does_not_corrupt_inference_of_the_rest',
        "files": {
            'main.pyfun': (
                'let f x = x + ?\n'
                'let g = f 5'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_hole_does_not_corrupt_inference_of_the_rest_2',
        "files": {
            'main.pyfun': 'let f = (?, ?two)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_hole_blocks_compilation',
        "files": {
            'main.pyfun': 'let f x = ?',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'valid_hole_fits_list_in_scope_bindings_of_the_hole_type',
        "files": {
            'main.pyfun': (
                'let shout s = String.upper s\n'
                'let quiet s = String.lower s\n'
                'let transform f = f "hi"\n'
                'let r = transform ?fn'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_named_hole_puts_the_fit_with_its_name_first',
        "files": {
            'main.pyfun': 'let r = ["a"] |> List.map ?upper |> String.join ","',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_named_hole_puts_the_fit_with_its_name_first_2',
        "files": {
            'main.pyfun': 'let r = ["a"] |> List.map ?lower |> String.join ","',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_truncated_fit_list_says_how_many_it_left_out',
        "files": {
            'main.pyfun': 'let r = ["a"] |> List.map ?f |> String.join ","',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'an_unconstrained_hole_lists_no_fits',
        "files": {
            'main.pyfun': 'let x = ?anything',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'refinement_fits_suggest_functions_whose_result_matches',
        "files": {
            'main.pyfun': 'let use = String.concat ?g "!"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_python_builtin_name_points_at_its_pyfun_module',
        "files": {
            'main.pyfun': 'let n = len [1, 2, 3]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_python_builtin_name_points_at_its_pyfun_module_2',
        "files": {
            'main.pyfun': 'let s = str 5',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_python_builtin_name_points_at_its_pyfun_module_3',
        "files": {
            'main.pyfun': 'let t = sum [1, 2]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_python_builtin_name_points_at_its_pyfun_module_4',
        "files": {
            'main.pyfun': 'let z = frobnicate 3',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'plus_on_strings_hints_at_string_concat',
        "files": {
            'main.pyfun': 'let s = "a" + "b"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'plus_on_strings_hints_at_string_concat_2',
        "files": {
            'main.pyfun': 'let s = 1 + "b"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'plus_on_strings_hints_at_string_concat_3',
        "files": {
            'main.pyfun': 'let s = "a" + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'plus_on_lists_hints_at_list_concat',
        "files": {
            'main.pyfun': 'let xs = [1, 2] + [3]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'plus_on_lists_hints_at_list_concat_2',
        "files": {
            'main.pyfun': 'let xs = 1 + [3]',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'multiply_on_strings_hints_at_string_repeat',
        "files": {
            'main.pyfun': 'let line = "-" * 20',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'multiply_on_strings_hints_at_string_repeat_2',
        "files": {
            'main.pyfun': 'let line = 20 * "-"',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_plain_numeric_mismatch_keeps_its_message',
        "files": {
            'main.pyfun': 'let bad = 1 + true',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_plain_numeric_mismatch_keeps_its_message_2',
        "files": {
            'main.pyfun': 'let bad = 1 * true',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'float_patterns_are_rejected_with_a_guiding_message',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  match x:\n'
                '    case 1.5: 0\n'
                '    case _: 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'float_patterns_are_rejected_with_a_guiding_message_2',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  match x:\n'
                '    case -1.5: 0\n'
                '    case _: 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'missing_total_case_is_reported_with_a_witness',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even: 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'partial_active_pattern_needs_a_wildcard',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Positive p: p'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_partial_without_a_binder_is_rejected',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Positive: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'bool_partial_binds_nothing',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = String.strip s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank x: x\n'
                '    case _: "text"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'partial_body_must_return_option_or_bool',
        "files": {
            'main.pyfun': 'let (|Weird|_|) n = n + 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'parameterized_partial_type_checks_and_checks_its_arguments',
        "files": {
            'main.pyfun': (
                'let (|DivisibleBy|_|) d n = n % d == 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case DivisibleBy "x": "fizz"\n'
                '    case _: "n"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'using_an_impure_active_pattern_is_an_effect',
        "files": {
            'main.pyfun': (
                'let (|Loud|Quiet|) n =\n'
                '  print n\n'
                '  if n > 5 then Loud else Quiet\n'
                'let pure classify n =\n'
                '  match n:\n'
                '    case Loud: 1\n'
                '    case Quiet: 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'case_name_clash_with_a_constructor_is_rejected',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green\n'
                'let (|Red|Other|) n = if n == 0 then Red else Other'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'case_name_clash_with_a_constructor_is_rejected_2',
        "files": {
            'main.pyfun': (
                'let (|Red|Other|) n = if n == 0 then Red else Other\n'
                'type Color = Red | Green'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'case_name_clash_with_a_constructor_is_rejected_3',
        "files": {
            'main.pyfun': (
                'let (|Hot|_|) n = n > 30\n'
                'let (|Hot|Cold|) n = if n > 30 then Hot else Cold'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_case_never_constructed_in_the_body_is_rejected',
        "files": {
            'main.pyfun': 'let (|Even|Odd|) n = Even',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'inconsistent_case_arity_in_the_body_is_rejected',
        "files": {
            'main.pyfun': 'let (|Wrap|) n = if n > 0 then Wrap n else Wrap',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'total_body_must_produce_a_case',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n =\n'
                '  if n == 0 then Even\n'
                '  elif n == 1 then Odd\n'
                '  else 42'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_case_is_not_a_value_outside_its_declaration',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let x = Even'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'nested_active_patterns_are_rejected',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f o =\n'
                '  match o:\n'
                '    case Some Even: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_mixing_a_non_active_pattern_alternative_is_reject',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even | 0: 1\n'
                '    case _: 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_with_a_binding_alternative_is_rejected',
        "files": {
            'main.pyfun': (
                'let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small x | Big _: 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'structural_arm_beside_active_pattern_is_witness_accurate',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let f o =\n'
                '  match o:\n'
                '    case Answer: 1\n'
                '    case Some x: x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'active_pattern_input_type_flows_from_the_body',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f =\n'
                '  match "x":\n'
                '    case Even: 1\n'
                '    case Odd: 2'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_target_must_match_the_value_shape',
        "files": {
            'main.pyfun': 'let (a, b) = 5',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_target_must_match_the_value_arity',
        "files": {
            'main.pyfun': 'let (a, b, c) = (1, 2)',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_destructuring_binding_leaks_its_effect',
        "files": {
            'main.pyfun': (
                'let pure (a, b) =\n'
                '  print "hi"\n'
                '  (1, 2)'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_destructuring_let_bang_unwraps_before_it_destructures',
        "files": {
            'main.pyfun': (
                'let f r = result {\n'
                '  let! (a, b) = r\n'
                '  return a\n'
                '}\n'
                'let g = f (Ok 1)'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'option_block_requires_an_option_to_bind',
        "files": {
            'main.pyfun': 'let f = option { let! x = 1  return x }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_yield_in_option_block',
        "files": {
            'main.pyfun': 'let a = option { yield 1 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_trailing_do_bang_ends_a_monad_block_as_unit',
        "files": {
            'main.pyfun': 'let v = result { do! Ok 1 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'rejects_option_without_return',
        "files": {
            'main.pyfun': 'let a = option { let! x = Some 1 }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'uppercase_option_names_the_lowercase_builder',
        "files": {
            'main.pyfun': 'let f o = Option { let! x = o  return x }',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'application_is_left_associative_and_curried',
        "files": {
            'main.pyfun': 'let r = f a b',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'pipe_binds_looser_than_application',
        "files": {
            'main.pyfun': 'let r = x |> f a',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'composition_binds_tighter_than_pipe',
        "files": {
            'main.pyfun': 'let r = x |> f >> g',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'backward_pipe_is_right_associative',
        "files": {
            'main.pyfun': 'let r = f <| g <| x',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'composition_is_left_associative',
        "files": {
            'main.pyfun': 'let r = f >> g >> h',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'chained_comparison_is_one_node_but_single_stays_binary',
        "files": {
            'main.pyfun': 'let r = a < b < c',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'chained_comparison_is_one_node_but_single_stays_binary_2',
        "files": {
            'main.pyfun': 'let r = a < b',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'offside_rule_separates_statements_but_joins_continuations',
        "files": {
            'main.pyfun': (
                'print a\n'
                'print b'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'import_requires_a_capitalized_module_name',
        "files": {
            'main.pyfun': 'import geometry',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'reports_errors_for_malformed_input',
        "files": {
            'main.pyfun': 'let = 1',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'reports_errors_for_malformed_input_2',
        "files": {
            'main.pyfun': 'match x:',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'let_rec_is_rejected_with_a_helpful_hint',
        "files": {
            'main.pyfun': 'let rec f x = x',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'doc_comment_attaches_to_type_and_extern_declarations',
        "files": {
            'main.pyfun': (
                '## A colour.\n'
                'type Color = Red | Green\n'
                '## Python sqrt.\n'
                'extern sqrt : float -> float = math.sqrt'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_list_pattern_allows_at_most_one_star',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [*a, *b]: 0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'a_total_active_pattern_takes_exactly_one_parameter',
        "files": {
            'main.pyfun': 'let (|Even|Odd|) d n = Even',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'an_active_pattern_is_top_level_only',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let (|A|_|) n = n == 0\n'
                '  x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'an_active_pattern_is_top_level_only_2',
        "files": {
            'main.pyfun': 'let pure (|A|_|) n = n == 0',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'suggests_keyword_operators_for_symbolic_logical_operator_typ',
        "files": {
            'main.pyfun': 'let ok = ready || valid',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'return_outside_computation_expression_suggests_dropping_retu',
        "files": {
            'main.pyfun': 'let double x = return x * 2',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'bundle_writes_a_page_a_loader_the_modules_and_the_assets',
        "files": {
            'main.pyfun': 'let x = 1 + "s"',
        },
        'args': ['check', 'main.pyfun'],
    },
]



@pytest.mark.parametrize("case", CHECK_CASES, ids=[c["id"] for c in CHECK_CASES])
def test_check_reports_exact_diagnostics(run, workdir, case):
    """CATCHES: a type checker that accepts an ill-typed program, words an error differently, points the caret/span at the wrong line or column, reports errors in a different order, miscounts the trailing "N errors" summary, or exits 0 on failure."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
