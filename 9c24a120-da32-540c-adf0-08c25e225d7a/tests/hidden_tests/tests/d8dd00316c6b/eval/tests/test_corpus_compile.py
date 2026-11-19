"""`pyfun compile <file>` on single-file programs: the exact Python each program lowers to.

The Pyfun programs below were harvested from the project's own unit tests (tests/compile.rs, tests/typecheck.rs, tests/roundtrip.rs) and are
written into the empty working directory as `main.pyfun` before each run. Expected
transcripts (exit code, stdout, stderr) were captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

COMPILE_CASES = [
    {
        'id': 'curried_def_lowers_to_n_ary_def',
        "files": {
            'main.pyfun': 'let add a b = a + b',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'full_application_is_a_direct_call',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let r = add 1 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unit_literal_lowers_to_none',
        "files": {
            'main.pyfun': 'let nothing = ()',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let inc = add 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_lowers_to_its_python_target_with_import',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let r = tan 8.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_with_name_equal_target_needs_no_import',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'let r = show 42'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'partial_application_of_extern_uses_functools_partial',
        "files": {
            'main.pyfun': (
                'extern pow: float -> float -> float = math.pow\n'
                'let sq = pow 2.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unused_extern_imports_nothing',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let r = 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_in_submodule_imports_the_submodule',
        "files": {
            'main.pyfun': (
                'extern import urllib.parse\n'
                'extern q: string -> string = urllib.parse.quote\n'
                'let r = q "a b"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_type_declares_an_opaque_handle_and_emits_no_class',
        "files": {
            'main.pyfun': (
                'extern type Conn\n'
                'extern connect: string -> Conn = sqlite3.connect\n'
                'let db = connect ":memory:"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_type_replaces_the_phantom_adt_in_the_instance_extern',
        "files": {
            'main.pyfun': (
                'extern type C\n'
                'extern ex: C -> string -> C = .execute()\n'
                'let f c = ex c "select 1"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'newtype_erases_to_the_bare_underlying_value',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let uid = UserId "u-1001"\n'
                'let f u =\n'
                '  match u:\n'
                '    case UserId s: s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'first_class_newtype_constructor_is_the_identity_helper',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let ids = List.map UserId ["a"]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'irrefutable_newtype_case_truncates_later_arms_and_the_guard',
        "files": {
            'main.pyfun': (
                'opaque type Cents = int\n'
                'let f c =\n'
                '  match c:\n'
                '    case Cents n: n\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_newtype_wrap_unwrap_round_trips',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type UserId = string\n'
                '        let uid = UserId "u-1001"\n'
                '        let unwrapped =\n'
                '          match uid:\n'
                '            case UserId s: s\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_newtype_literal_payload_selects_arms',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type Cents = int\n'
                '        let describe c =\n'
                '          match c:\n'
                '            case Cents 0: "free"\n'
                '            case Cents n: "costs"\n'
                '        let a = describe (Cents 0)\n'
                '        let b = describe (Cents 42)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_mapping_a_newtype_constructor_is_identity',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type UserId = string\n'
                '        let total =\n'
                '          ["ab", "c"]\n'
                '          |> List.map UserId\n'
                '          |> List.fold (fun acc u ->\n'
                '            match u:\n'
                '                case UserId s: acc + String.len s) 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_newtype_crosses_the_extern_boundary_bare',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type UserId = string\n'
                '        extern pure upperId: UserId -> string = str.upper\n'
                '        let r = upperId (UserId "abc")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'instance_method_extern_lowers_to_a_method_call',
        "files": {
            'main.pyfun': (
                'type R = RH\n'
                'extern readBody: R -> string = .read()\n'
                'let f r = readBody r'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'instance_method_extern_passes_remaining_args',
        "files": {
            'main.pyfun': (
                'type C = CH\n'
                'extern ex: C -> string -> C = .execute()\n'
                'let f c = ex c "select 1"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'instance_method_receiver_only_partial_is_the_bound_method',
        "files": {
            'main.pyfun': (
                'type C = CH\n'
                'extern ex: C -> string -> C = .execute()\n'
                'let g c = ex c'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'instance_property_extern_reads_the_attribute',
        "files": {
            'main.pyfun': (
                'type U = UH\n'
                'extern scheme: U -> string = .scheme\n'
                'let f u = scheme u'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'nullary_extern_lowers_to_a_zero_arg_call',
        "files": {
            'main.pyfun': (
                'extern now: unit -> float = time.time\n'
                'let t = now ()'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_unit_parameter_contributes_no_argument_wherever_it_sits_2',
        "files": {
            'main.pyfun': 'print(abs(-5))',
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_unit_extern_combines_with_a_kwarg_slot_and_a_thunk',
        "files": {
            'main.pyfun': (
                'extern import threading\n'
                'extern type Thread\n'
                'extern newThread: unit -> (unit ->{io} unit) -> Thread = threading.Thread(daemon = true, target = ...)\n'
                'let t = newThread () (fun _ -> print "hi")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_receiver_method_with_a_unit_parameter_drops_it',
        "files": {
            'main.pyfun': (
                'extern type C\n'
                'extern ping: C -> unit -> string = .m()\n'
                'let f c = ping c ()'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let d = lifted () 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_on_builtin_type_imports_nothing',
        "files": {
            'main.pyfun': (
                'extern up: string -> string = str.upper\n'
                'let r = up "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_on_class_method_imports_only_the_module',
        "files": {
            'main.pyfun': (
                'type C = CH\n'
                'extern ex: C -> string -> C = sqlite3.Connection.execute\n'
                'let f c = ex c "x"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_import_declares_the_module_explicitly',
        "files": {
            'main.pyfun': (
                'extern import datetime\n'
                'extern now: unit -> a = datetime.datetime.now\n'
                'let t = now ()'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'bare_reference_to_a_declared_import_extern_still_records_it',
        "files": {
            'main.pyfun': (
                'extern import sys\n'
                'extern write: string -> int = sys.stdout.write\n'
                'let w = write'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_import_alias_emits_import_as_and_roots_targets',
        "files": {
            'main.pyfun': (
                'extern import json as j\n'
                'extern dumps: List int -> string = j.dumps\n'
                'let s = dumps [1]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_import_composes_with_pinned_kwargs',
        "files": {
            'main.pyfun': (
                'extern import sqlite3\n'
                'extern conn: string -> a = sqlite3.dbapi2.connect(timeout=5)\n'
                'let c = conn ":memory:"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'an_undecidable_target_is_rejected_rather_than_guessed',
        "files": {
            'main.pyfun': 'extern import urllib.request',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_declared_import_settles_an_undecidable_target',
        "files": {
            'main.pyfun': (
                'extern import urllib.request\n'
                'extern get: string -> a = urllib.request.urlopen\n'
                'let r = get "x"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_top_level_target_needs_no_declaration',
        "files": {
            'main.pyfun': (
                'extern pure f: float -> float = math.fabs\n'
                'let r = f 1.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unused_extern_import_emits_nothing',
        "files": {
            'main.pyfun': (
                'extern import sqlite3\n'
                'let x = 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwargs_are_appended_to_the_call',
        "files": {
            'main.pyfun': (
                'extern openText : string -> Seq string = builtins.open(mode="rt", encoding="utf-8")\n'
                'let f path = openText path'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'receiver_method_extern_kwargs_follow_the_positional_args',
        "files": {
            'main.pyfun': (
                'type P = PH\n'
                'extern writeText : P -> string -> int = .write_text(encoding="utf-8")\n'
                'let f p text = writeText p text'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwargs_support_int_negative_bool_and_float_values',
        "files": {
            'main.pyfun': (
                'extern g : string -> a = gzip.open(compresslevel=9, buffering=-1, text=true, ratio=2.5)\n'
                'let f path = g path'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwargs_partial_application_pins_kwargs_via_functools',
        "files": {
            'main.pyfun': (
                'extern openText : string -> int -> Seq string = builtins.open(mode="rt")\n'
                'let bare = openText\n'
                'let partial = openText "a.txt"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_kwargs_produce_observable_output',
        "files": {
            'main.pyfun': (
                'extern parseHex : string -> int = int(base=16)\n'
                'let n = parseHex "ff"\n'
                'let m = parseHex "10"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_takes_a_trailing_argument',
        "files": {
            'main.pyfun': (
                'extern openText : string -> string -> Seq string = builtins.open(mode="rt", encoding=...)\n'
                'let f path enc = openText path enc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slots_fill_in_the_order_the_keywords_are_writte',
        "files": {
            'main.pyfun': (
                'extern mix : string -> int -> bool -> a = m.f(a=1, b=..., c="x", d=...)\n'
                'let f s i b = mix s i b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'receiver_method_extern_kwarg_slot_takes_a_trailing_argument',
        "files": {
            'main.pyfun': (
                'extern type P\n'
                'extern writeText : P -> string -> string -> int = .write_text(encoding=...)\n'
                'let f p text enc = writeText p text enc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_partial_application_becomes_a_lambda',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int -> int = int(base=...)\n'
                'let bare = parseInt\n'
                'let partial = parseInt "ff"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_partial_evaluates_supplied_arguments_eager',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int -> int = int(base=...)\n'
                'extern src : unit -> string = get.line\n'
                'let partial = parseInt (src ())'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_kwarg_slot_partial_evaluates_supplied_arguments_eager_2',
        "files": {
            'main.pyfun': (
                'extern type P\n'
                'extern toPath : string -> P = pathlib.Path\n'
                'extern writeText : P -> string -> string -> int = .write_text(encoding=...)\n'
                'let partial = writeText (toPath "a.txt") "body"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_kwarg_slot_produces_observable_output',
        "files": {
            'main.pyfun': (
                'extern parseIn : string -> int -> int = int(base=...)\n'
                'let hex = parseIn "ff" 16\n'
                'let bin = parseIn "1011" 2\n'
                'let ff = parseIn "ff"\n'
                'let also = ff 16'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_literal_lowers_to_a_python_list',
        "files": {
            'main.pyfun': 'let xs = [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_filter_lower_to_emitted_helpers',
        "files": {
            'main.pyfun': 'let r = List.map (fun x -> x) (List.filter (fun x -> true) [1, 2])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'len_and_sum_lower_to_python_builtins_without_helpers',
        "files": {
            'main.pyfun': (
                'let n = List.len [1, 2]\n'
                'let s = List.sum [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_lowers_to_functools_reduce',
        "files": {
            'main.pyfun': 'let t = List.fold (fun a b -> a + b) 0 [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'pipe_becomes_application',
        "files": {
            'main.pyfun': (
                'let id x = x\n'
                'let r = 5 |> id'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'empty_collections_lower_to_set_and_dict',
        "files": {
            'main.pyfun': (
                'let s = Set.empty\n'
                'let m = Map.empty'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'set_functions_lower_to_emitted_helpers',
        "files": {
            'main.pyfun': 'let r = Set.contains 1 (Set.add 1 (Set.ofList [2]))',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_add_and_find_or_lower_to_emitted_helpers',
        "files": {
            'main.pyfun': (
                'let m = Map.add "a" 1 Map.empty\n'
                'let v = Map.findOr "a" 0 m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_remove_lowers_to_a_copy_and_pop',
        "files": {
            'main.pyfun': 'let m = Map.remove "a" Map.empty',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'try_find_lowers_to_an_option_and_pulls_in_the_option_prelude',
        "files": {
            'main.pyfun': 'let v = Map.tryFind "a" Map.empty',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_zip_lowers_to_a_zip_helper',
        "files": {
            'main.pyfun': 'let ps = List.zip [1, 2] [3, 4]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_of_list_lowers_to_dict_and_to_list_to_items',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, 2)]\n'
                'let ps = Map.toList m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_zip_into_a_map_and_back',
        "files": {
            'main.pyfun': (
                '\n'
                '        let m = Map.ofList (List.zip ["a", "b"] [1, 2])\n'
                '        let a = Option.withDefault 0 (Map.tryFind "a" m)\n'
                '        let n = Map.len m\n'
                '        let pairs = Map.toList m\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'try_lowers_to_a_try_except_yielding_ok_or_error',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int = int\n'
                'let safe s = try (parseInt s)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_try_catches_and_recovers',
        "files": {
            'main.pyfun': (
                '\n'
                '        extern parseInt : string -> int = int\n'
                '        let orZero s = Result.withDefault 0 (try (parseInt s))\n'
                '        let good = orZero "42"\n'
                '        let bad = orZero "oops"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_try_exposes_exception_kind_and_message',
        "files": {
            'main.pyfun': (
                '\n'
                '        extern parseInt : string -> int = int\n'
                '        let kindOf s =\n'
                '          match try (parseInt s):\n'
                '            case Ok n: "ok"\n'
                '            case Error e: e.errorKind\n'
                '        let k = kindOf "nope"\n'
                '        let matched =\n'
                '          match try (parseInt "x"):\n'
                '            case Error (Exception { errorKind = "ValueError" }): "caught-value-error"\n'
                '            case _: "other"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'interpolated_string_lowers_to_a_python_fstring',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let a = 3\n'
                'let b = 4\n'
                'let g = f"hi {name}: {a + b}"\n'
                'let u = f"upper {String.upper name}"\n'
                'let e = f"brace {{ {a}"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_interpolated_strings',
        "files": {
            'main.pyfun': (
                '\n'
                '        let name = "Ada"\n'
                '        let a = 3\n'
                '        let b = 4\n'
                '        let p = (1, 2)\n'
                '        let greet = f"Hello, {name}!"\n'
                '        let math = f"{a} + {b} = {a + b}"\n'
                '        let up = f"upper: {String.upper name}"\n'
                '        let brace = f"{{literal}} {a}"\n'
                '        let point = f"point {p}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'debug_hole_lowers_to_an_echoed_literal_plus_hole',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let y = 4\n'
                'let a = f"{x=}"\n'
                'let b = f"{x = }"\n'
                'let c = f"sum {x + y=} end"\n'
                'let d = f"{x==y}"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_mutual_recursion',
        "files": {
            'main.pyfun': (
                '\n'
                '        let isEven = fun n -> if n == 0 then true else isOdd (n - 1)\n'
                '        let isOdd = fun n -> if n == 0 then false else isEven (n - 1)\n'
                '        let a = isEven 10\n'
                '        let b = isOdd 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'as_pattern_lowers_to_python_as',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some v as w: w\n'
                '    case None: None'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_as_pattern',
        "files": {
            'main.pyfun': (
                '\n'
                '        let describe = fun n ->\n'
                '            match n:\n'
                '                case 0: 0\n'
                '                case x as v: v\n'
                '        let both = fun p ->\n'
                '            match p:\n'
                '                case (a, b) as w: w\n'
                '        let a = describe 7\n'
                '        let b = both (3, 4)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'discard_binding_lowers_and_runs_effects',
        "files": {
            'main.pyfun': 'let _ = 1 + 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_discard_runs_the_effect',
        "files": {
            'main.pyfun': (
                '\n'
                '        let go =\n'
                '            let _ = 1 + 2\n'
                '            42\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_slice_lowers_to_python_slicing',
        "files": {
            'main.pyfun': 'let a = String.slice 0 3 "hello"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_slice_and_index_of',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = "hello world"\n'
                '        let a = String.slice 0 5 s\n'
                '        let b = String.slice 6 100 s\n'
                '        let c = Option.withDefault (0 - 1) (String.tryIndexOf "world" s)\n'
                '        let d = Option.withDefault (0 - 1) (String.tryIndexOf "zzz" s)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'stdlib_predicates_inline_when_fully_applied',
        "files": {
            'main.pyfun': (
                'let a s = String.contains "x" s\n'
                '         let b s = String.startsWith "x" s\n'
                '         let c s = String.endsWith "x" s\n'
                '         let d xs = List.contains 3 xs\n'
                '         let e s = Set.contains 3 s\n'
                '         let g m = Map.contains 3 m\n'
                '         let h xs = List.isEmpty xs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'inlined_membership_parenthesizes_correctly',
        "files": {
            'main.pyfun': (
                'let f s = String.contains "a" s and String.contains "b" s\n'
                '         let g s = if String.contains "a" s then 1 else 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'stdlib_predicate_partial_application_falls_back_to_helper',
        "files": {
            'main.pyfun': (
                'let f = String.contains "x"\n'
                '         let r = List.filter f ["xy", "ab"]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_inlined_stdlib_predicates',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = String.contains "lo" "hello"\n'
                '        let b = String.contains "hello" "lo"\n'
                '        let c = String.startsWith "he" "hello"\n'
                '        let d = String.startsWith "lo" "hello"\n'
                '        let e = String.endsWith "lo" "hello"\n'
                '        let f = String.endsWith "he" "hello"\n'
                '        let g = List.contains 3 [1, 2, 3]\n'
                '        let h = List.contains 9 [1, 2, 3]\n'
                '        let i = Set.contains 2 (Set.ofList [1, 2, 3])\n'
                '        let j = Map.contains 1 (Map.ofList [(1, "a")])\n'
                '        let k = Map.contains 9 (Map.ofList [(1, "a")])\n'
                '        let l = List.isEmpty (List.filter (fun x -> x > 9) [1, 2, 3])\n'
                '        let m = List.isEmpty [1, 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_stdlib_predicate_partial_application',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f = String.contains "lo"\n'
                '        let a = f "hello"\n'
                '        let b = f "hi"\n'
                '        let r = List.filter (String.contains "a") ["cat", "dog", "bat"]\n'
                '        let n = List.len r\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'eq_section_predicates_route_to_the_c_level_scan',
        "files": {
            'main.pyfun': (
                'let a l rack = List.findIndex ((==) l) rack\n'
                '         let b l rack = List.find ((==) l) rack\n'
                '         let c l rack = List.exists ((==) l) rack\n'
                '         let d l rack = List.findIndex (fun y -> y == l) rack\n'
                '         let e l rack = List.findIndex (fun y -> l == y) rack'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'eq_section_specialization_keeps_the_helper_otherwise',
        "files": {
            'main.pyfun': (
                'let p l = List.findIndex ((==) l)\n'
                '         let q l rack = List.findIndex (fun y -> y > l) rack\n'
                '         let r rack = List.findIndex (fun y -> y == y) rack\n'
                '         let s l rack = List.exists (fun l -> l == l) rack'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'eq_section_value_is_evaluated_once_before_the_list',
        "files": {
            'main.pyfun': (
                'let f n = n + 1\n'
                '         let a rack = List.findIndex ((==) (f 1)) rack\n'
                '         let b rack = List.exists ((==) (f 1)) rack'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_eq_section_specialization_matches_the_helper',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = List.findIndex ((==) 3) [1, 2, 3, 3]\n'
                '        let b = List.findIndex ((==) 9) [1, 2, 3]\n'
                '        let c = List.find ((==) "b") ["a", "b"]\n'
                '        let d = List.find ((==) "z") ["a", "b"]\n'
                '        let e = List.exists ((==) 2) [1, 2]\n'
                '        let f = List.exists ((==) 5) [1, 2]\n'
                '        let g = List.findIndex (fun y -> y == (1, 2)) [(0, 0), (1, 2)]\n'
                '        let h = List.findIndex ((==) 0) []\n'
                '        let i = List.find ((==) 0.0) [-0.0]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'match_on_map_try_find_lowers_to_a_membership_test',
        "files": {
            'main.pyfun': (
                'let allows checks rc l =\n'
                '           match Map.tryFind rc checks:\n'
                '             case None: true\n'
                '             case Some s: Set.contains l s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'match_on_lookups_covers_head_and_get_in_both_positions',
        "files": {
            'main.pyfun': (
                'let hd xs =\n'
                '           match List.head xs:\n'
                '             case Some h: h\n'
                '             case None: 0\n'
                '         let g i xs = 1 + (match List.get (i + 1) xs:\n'
                '           case Some (a, b): a + b\n'
                '           case None: 0)\n'
                '         let w m = match Map.tryFind 1 m:\n'
                '           case Some _: 1\n'
                '           case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'match_on_lookups_falls_through_for_other_shapes',
        "files": {
            'main.pyfun': (
                'let a k m =\n'
                '           match Map.tryFind k m:\n'
                '             case Some 0: "zero"\n'
                '             case Some _: "other"\n'
                '             case None: "none"\n'
                '         let b k m =\n'
                '           match Map.tryFind k m:\n'
                '             case Some v if v > 0: v\n'
                '             case _: 0\n'
                '         let c f = match f 1:\n'
                '           case Some v: v\n'
                '           case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_match_on_lookups_matches_the_helper',
        "files": {
            'main.pyfun': (
                '\n'
                '        let look k m =\n'
                '          match Map.tryFind k m:\n'
                '            case Some v: v\n'
                '            case None: "absent"\n'
                '        let m = Map.ofList [(1, "one"), (2, "")]\n'
                '        let a = look 1 m\n'
                '        let b = look 2 m\n'
                '        let c = look 3 m\n'
                '        let hd xs = match List.head xs:\n'
                '          case Some h: h\n'
                '          case None: -1\n'
                '        let d = hd [0, 1]\n'
                '        let e = hd []\n'
                '        let get i xs = match List.get i xs:\n'
                '          case Some x: x\n'
                '          case None: -1\n'
                '        let f = get 0 [0]\n'
                '        let g = get 1 [0]\n'
                '        let h = get (0 - 1) [0]\n'
                '        let ok = Map.ofList [("k", [])]\n'
                '        let i = match Map.tryFind "k" ok:\n'
                '          case Some xs: List.len xs\n'
                '          case None: -1\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'exponentiation_lowers_right_assoc',
        "files": {
            'main.pyfun': (
                'let a = 2.0 ** 3.0 ** 2.0\n'
                'let b = -2.0 ** 2.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_exponentiation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 2.0 ** 8.0\n'
                '        let b = 2.0 ** 3.0 ** 2.0\n'
                '        let c = 2.0 ** -1.0\n'
                '        let d = -2.0 ** 2.0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_bind_filter_to_result',
        "files": {
            'main.pyfun': (
                '\n'
                '        let half = fun x -> if x % 2 == 0 then Some (x // 2) else None\n'
                '        let a = Option.withDefault 0 (Option.bind half (Some 8))\n'
                '        let b = Option.withDefault 0 (Option.bind half (Some 7))\n'
                '        let c = Option.withDefault 0 (Option.filter (fun x -> x > 5) (Some 8))\n'
                '        let d = Option.withDefault 0 (Option.filter (fun x -> x > 5) (Some 2))\n'
                '        let e = Result.withDefault 0 (Option.toResult 0 (Some 42))\n'
                '        let f = Result.isError (Option.toResult 0 None)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'numeric_conversions_lower_correctly',
        "files": {
            'main.pyfun': (
                'let a = round 3.7\n'
                'let b = floor 3.2\n'
                'let c = ceil 3.2\n'
                'let d = truncate 3.9'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sqrt_lowers_to_math_sqrt_with_units_erased',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = sqrt 16.0<m^2>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sqrt_lowers_to_math_sqrt_with_units_erased_2',
        "files": {
            'main.pyfun': (
                'let f = sqrt\n'
                'let r = f 4.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_user_sqrt_shadows_the_builtin_in_lowering',
        "files": {
            'main.pyfun': (
                'let sqrt x = x\n'
                'let r = sqrt 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_unit_aware_sqrt',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = sqrt 16.0<m^2>\n'
                'let hyp = sqrt (2.0 * 2.0 + 2.0 * 2.0)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'cbrt_lowers_to_math_cbrt_with_units_erased',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = cbrt 27.0<m^3>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'cbrt_lowers_to_math_cbrt_with_units_erased_2',
        "files": {
            'main.pyfun': (
                'let f = cbrt\n'
                'let r = f 8.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_unit_aware_cbrt',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = cbrt 27.0<m^3>\n'
                'let neg = cbrt (0.0 - 8.0)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_numeric_conversions',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = round 3.7\n'
                '        let b = floor 3.7\n'
                '        let c = ceil 3.2\n'
                '        let d = truncate 3.9\n'
                '        let e = floor (-2.5)\n'
                '        let f = Option.withDefault 0.0 (String.toFloat "3.5")\n'
                '        let g = Option.withDefault 0.0 (String.toFloat "nope")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_escapes',
        "files": {
            'main.pyfun': (
                '\n'
                '        let crlf = String.len "a\\r\\nb"\n'
                '        let emoji = String.len "hi \\u{1F600}"\n'
                '        let accent = String.len "caf\\u{e9}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_digit_separators_and_bases',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 1_000_000\n'
                '        let b = 0xFF\n'
                '        let c = 0o17\n'
                '        let d = 0b1010\n'
                '        let e = 0xDEAD_BEEF\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'scientific_notation_lowers_to_float',
        "files": {
            'main.pyfun': (
                'let a = 1e6\n'
                'let b = 2.5e-3\n'
                'let g = 6.674e-11'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_scientific_notation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 1e3\n'
                '        let b = 2.5e-1\n'
                '        let c = 1e3 + 1.0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_completeness_ops_lower_to_helpers',
        "files": {
            'main.pyfun': (
                'let a = List.get 0 [1, 2]\n'
                'let b = List.isEmpty [1]\n'
                'let c = List.contains 2 [1, 2]\n'
                'let d = List.concat [1] [2]\n'
                'let e = List.sort [2, 1]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'choose_and_collect_lower_to_helpers',
        "files": {
            'main.pyfun': (
                'let a = List.choose (fun x -> if x > 1 then Some x else None) [1, 2]\n'
                'let b = List.collect (fun x -> [x, x]) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'input_lowers_name_for_name',
        "files": {
            'main.pyfun': (
                'let name = input "who? "\n'
                'print name'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_input_reads_a_line_from_stdin',
        "files": {
            'main.pyfun': (
                'let name = input "who? "\n'
                'print (String.concat "hi " name)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_choose_and_collect',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [1, 2, 3]\n'
                '        let a = List.choose (fun x -> if x > 1 then Some (x * 10) else None) xs\n'
                '        let b = List.collect (fun x -> [x, x]) xs\n'
                '        let c = List.collect (fun x -> x) [[1], [2, 3]]\n'
                '        let keepOdd = List.choose (fun x -> if x % 2 == 1 then Some x else None)\n'
                '        let d = keepOdd xs\n'
                '        let e = xs |> List.collect (fun x -> [x, 0])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_completeness_ops',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 2]\n'
                '        let a = Option.withDefault 0 (List.get 0 xs)\n'
                '        let b = Option.withDefault 0 (List.get 9 xs)\n'
                '        let c = List.contains 2 xs\n'
                '        let d = List.concat xs [4]\n'
                '        let e = List.sort xs\n'
                '        let f = Option.withDefault 0 (List.find (fun x -> x > 1) xs)\n'
                '        let g = List.isEmpty []\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'modulo_lowers_to_python_percent',
        "files": {
            'main.pyfun': (
                'let r = 10 % 3\n'
                'let even n = n % 2 == 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_modulo',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 10 % 3\n'
                '        let b = 5.5 % 2.0\n'
                '        let c = -7 % 3\n'
                '        let d = (%) 17 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'non_ascii_string_is_not_double_encoded',
        "files": {
            'main.pyfun': 'let s = "café → 🎉"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_non_ascii_string_length',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = String.len "café"\n'
                '        let m = String.len f"→🎉 {n}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'chained_comparison_lowers_to_native_python_form',
        "files": {
            'main.pyfun': (
                'let f x = 1 < x < 10\n'
                'let g = 1 == 1 == 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_chained_comparisons',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 1 < 2 < 3\n'
                '        let b = 3 < 2 < 1\n'
                '        let c =\n'
                '            let x = 5\n'
                '            1 < x < 10\n'
                '        let d = 1 <= 1 < 2\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unary_minus_lowers_with_python_precedence',
        "files": {
            'main.pyfun': (
                'let a = -5\n'
                'let b = 2 * -3\n'
                'let c = -(4 + 1)\n'
                'let d = 0 - -7'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_unary_minus',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = -5\n'
                '        let b = abs (-5)\n'
                '        let c = 2 * -3\n'
                '        let d = -(4 + 1)\n'
                '        let sign =\n'
                '            match -1:\n'
                '                case -1: "neg"\n'
                '                case _: "other"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'operator_section_lowers_to_a_curried_lambda',
        "files": {
            'main.pyfun': (
                'let mul = (*)\n'
                'let double = (*) 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_section_in_argument_position_closes_over_its_argument',
        "files": {
            'main.pyfun': (
                'let c xs = xs |> List.map ((+) 2)\n'
                'let a x xs = xs |> List.filter ((==) x)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_bare_operator_is_still_the_binary_lambda',
        "files": {
            'main.pyfun': 'let e xs = xs |> List.fold (+) 0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_section_argument_that_would_be_captured_keeps_the_wrapper',
        "files": {
            'main.pyfun': 'let shadow b xs = List.map ((+) b) xs',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_non_atomic_section_argument_keeps_the_wrapper',
        "files": {
            'main.pyfun': (
                'extern effect : int -> int = builtins.print\n'
                'let costly xs = List.map ((+) (effect 1)) xs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_operator_sections',
        "files": {
            'main.pyfun': (
                '\n'
                '        let mul = (*)\n'
                '        let double = (*) 2\n'
                '        let total = List.fold (+) 0 [1, 2, 3, 4]\n'
                '        let cmp = (<) 2 3\n'
                '        let a = mul 3 4\n'
                '        let b = double 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'composition_lowers_to_a_single_argument_lambda',
        "files": {
            'main.pyfun': (
                'let inc x = x + 1\n'
                'let h = inc >> inc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_function_composition_both_directions',
        "files": {
            'main.pyfun': (
                '\n'
                '        let inc x = x + 1\n'
                '        let double x = x * 2\n'
                '        let ltr = inc >> double\n'
                '        let rtl = inc << double\n'
                '        let a = ltr 3\n'
                '        let b = rtl 3\n'
                '        let piped = 5 |> inc >> double\n'
                '        let mapped = List.map (double >> inc) [1, 2, 3]\n'
                '        let clean = (String.strip >> String.upper) "  hi  "\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'raw_string_re_escapes_backslashes_on_emit',
        "files": {
            'main.pyfun': 'let p = r"C:\\path"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_raw_string_backslashes_are_literal',
        "files": {
            'main.pyfun': (
                '\n'
                '        let path_len = String.len r"a\\nb"\n'
                '        let quote_len = String.len r"a\\"b"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_string_emits_an_escaped_single_line_literal',
        "files": {
            'main.pyfun': (
                'let doc = """a\n'
                'b"""'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_string_emits_an_escaped_single_line_literal_2',
        "files": {
            'main.pyfun': (
                'let x = 1\n'
                'let m = f"""a {x}\n'
                'b"""'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_string_emits_an_escaped_single_line_literal_3',
        "files": {
            'main.pyfun': (
                'let p = r"""C:\\path\n'
                'next"""'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fstring_is_an_application_argument',
        "files": {
            'main.pyfun': (
                'let x = 5\n'
                'let main = print f"x is {x}"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_interpolation_debug_holes',
        "files": {
            'main.pyfun': (
                '\n'
                '        let x = 3\n'
                '        let y = 4\n'
                '        let a = f"{x=}"\n'
                '        let b = f"{x = }"\n'
                '        let c = f"{x + y=}"\n'
                '        let d = f"{x == y}"\n'
                '        let e = f"{x <= y}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_interpolation_hole_with_nested_string',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = "a}b"\n'
                '        let r = f"contains: {String.contains "}" s}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'target_311_keeps_safe_fstrings',
        "files": {
            'main.pyfun': (
                'let x = 5\n'
                'let r = f"x is {x}"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_target_311_format_rewrite_runs_identically',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = "a}b"\n'
                '        let r = f"contains: {String.contains "}" s}"\n'
                '        let brace = f"lit {{x}} and {String.contains "}" s}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_functions_lower_to_builtins_and_helpers',
        "files": {
            'main.pyfun': (
                'let n = String.len "hi"\n'
                'let up = String.upper "hi"\n'
                'let parts = String.split "," "a,b"\n'
                'let joined = String.join "-" parts\n'
                'let has = String.contains "a" "abc"\n'
                'let s = String.fromInt 7\n'
                'let chars = String.toList "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_to_int_lowers_to_a_try_except_and_pulls_in_the_option',
        "files": {
            'main.pyfun': 'let r = String.toInt "42"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_operations',
        "files": {
            'main.pyfun': (
                '\n'
                '        let g = String.concat "Hello, " "World"\n'
                '        let up = String.upper g\n'
                '        let n = String.len g\n'
                '        let parts = String.split ", " g\n'
                '        let joined = String.join "/" parts\n'
                '        let has = String.contains "World" g\n'
                '        let r = String.replace "o" "0" g\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_to_int_parses_or_yields_none',
        "files": {
            'main.pyfun': (
                '\n'
                '        let ok = Option.withDefault 0 (String.toInt "41")\n'
                '        let bad = Option.withDefault 0 (String.toInt "nope")\n'
                '        let neg = Option.withDefault 0 (String.toInt "-5")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unused_collection_helpers_are_not_emitted',
        "files": {
            'main.pyfun': 'let s = Set.empty',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'result_map_lowers_to_a_helper_pulling_in_the_result_prelude',
        "files": {
            'main.pyfun': 'let r = Result.map (fun x -> x) (Ok 1)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_map_filter_lower_to_pythons_lazy_builtins',
        "files": {
            'main.pyfun': (
                'let r = Seq.map (fun x -> x) (Seq.filter (fun x -> true) (Seq.range 0 3))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_take_lowers_to_itertools_islice',
        "files": {
            'main.pyfun': 'let r = Seq.take 2 (Seq.range 0 9)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'module_members_lower_to_mangled_top_level_names',
        "files": {
            'main.pyfun': (
                'module Geometry =\n'
                '  let pi = 3\n'
                '  let area r = pi * r * r\n'
                'let big = Geometry.area 10'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'partial_application_of_a_module_member',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let add a b = a + b\n'
                'let inc = M.add 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'result_to_option_pulls_in_both_preludes',
        "files": {
            'main.pyfun': 'let o = Result.toOption (Ok 1)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'if_in_value_position_is_a_conditional_expression',
        "files": {
            'main.pyfun': 'let r = if true then 1 else 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'exhaustive_match_without_wildcard_keeps_a_runtime_guard',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let f c = match c: case Red: 1 case Green: 2 case Blue: 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'adt_lowers_to_frozen_dataclasses',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let x = Has 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let r = unwrap (Has 7)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'adt_classes_get_structural_eq',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let a = Has 1 == Has 1\n'
                'let b = Has 1 == Has 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'adt_classes_get_structural_hash',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let s = Set.ofList [Red, Red, Green]\n'
                'let n = Set.len s\n'
                'let hasRed = Set.contains Red s\n'
                'let hasBlue = Set.contains Blue s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'adt_classes_get_derived_ordering',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let x = Red < Green'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ordering_is_emitted_only_when_a_type_is_compared',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let x = Red'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'payload_variant_order_key_includes_fields',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let c = Circle 1.0 < Rect 0.0 0.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'builtin_option_and_result_get_ordering_but_exception_does_no',
        "files": {
            'main.pyfun': 'let x = Some 1 < Some 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'builtin_option_and_result_get_ordering_but_exception_does_no_2',
        "files": {
            'main.pyfun': 'let x = try (Some 1)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_sort_a_sum_type_by_variant_order',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Color = Red | Green | Blue\n'
                '        let ordered = List.sort [Blue, Red, Green]\n'
                '        let a = Red < Green\n'
                '        let b = Green < Blue\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_sum_orders_by_variant_then_field',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Shape = Circle float | Rect float float\n'
                '        let a = Circle 1.0 < Circle 2.0\n'
                '        let b = Circle 9.0 < Rect 0.0 0.0\n'
                '        let c = Rect 1.0 2.0 < Rect 1.0 3.0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_sort_records_and_tuples',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let pts = List.sort [Point { x = 2, y = 0 }, Point { x = 1, y = 9 }, Point { x = 1, y = 3 }]\n'
                '        let tups = List.sort [(1, 3), (1, 2), (0, 9)]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_sort_a_recursive_type',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Tree = Leaf int | Node Tree Tree\n'
                '        let ordered = List.sort [Node (Leaf 2) (Leaf 3), Leaf 5, Leaf 1]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_lowers_to_frozen_dataclass',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { y = 4, x = 3 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_compared_record_gets_order_true',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let a = Point { x = 1, y = 2 } < Point { x = 1, y = 3 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'dataclass_fields_get_python_type_annotations',
        "files": {
            'main.pyfun': (
                'type Opt a = None2 | Has a\n'
                'type Rec = { count: int, ratio: float, label: string, tags: List string, maybe: Opt int }\n'
                'let r = Rec { count = 1, ratio = 2.0, label = "x", tags = [], maybe = None2 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_update_copies_through_a_temp',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = 2 }\n'
                'let q = { p with x = 9 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_field_access_lowers_to_attribute',
        "files": {
            'main.pyfun': (
                'type Point = { x: int }\n'
                'let p = Point { x = 1 }\n'
                'let s = p.x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_pattern_lowers_to_keyword_class_pattern',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p = match p: case Point { x = 0, y }: y case Point { x }: x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_traversals_walk_items_once',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "a")]\n'
                'let t = Map.fold (fun acc k v -> acc + k) 0 m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_partition_tests_each_entry_once',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "a")]\n'
                'let p = Map.partition (fun k v -> k > 0) m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'set_operations_use_pythons_own_set_methods',
        "files": {
            'main.pyfun': 'let a = Set.isSubset (Set.ofList [1]) (Set.ofList [1, 2])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_set_traversals',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = Set.ofList [3, 1, 4, 1, 5]\n'
                '        let empty = Set.isEmpty (Set.ofList [])\n'
                '        let full = Set.isEmpty s\n'
                '        let halved = List.sort (Set.toList (Set.map (fun x -> x % 2) s))\n'
                '        let kept = List.sort (Set.toList (Set.filter (fun x -> x > 2) s))\n'
                '        let total = Set.fold (fun acc x -> acc + x) 0 s\n'
                '        let any = Set.exists (fun x -> x > 4) s\n'
                '        let all = Set.forall (fun x -> x > 0) s\n'
                '        let sub = Set.isSubset (Set.ofList [1, 3]) s\n'
                '        let sup = Set.isSuperset s (Set.ofList [1, 3])\n'
                '        let biggest = Set.max s\n'
                '        let smallest = Set.min s\n'
                '        let noMax = Set.max (Set.ofList [])\n'
                '        let split = Set.partition (fun x -> x > 2) s\n'
                '        let passing = List.sort (Set.toList (fst split))\n'
                '        let failing = List.sort (Set.toList (snd split))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_map_traversals',
        "files": {
            'main.pyfun': (
                '\n'
                '        let m = Map.ofList [(1, "one"), (2, "two"), (3, "three")]\n'
                '        let empty = Map.isEmpty (Map.ofList [])\n'
                '        let full = Map.isEmpty m\n'
                '        let shouted = Map.toList (Map.map (fun k v -> String.concat v "!") m)\n'
                '        let kept = Map.toList (Map.filter (fun k v -> k > 1) m)\n'
                '        let keySum = Map.fold (fun acc k v -> acc + k) 0 m\n'
                '        let any = Map.exists (fun k v -> v == "two") m\n'
                '        let all = Map.forall (fun k v -> k > 0) m\n'
                '        let joined = Map.toList (Map.union m (Map.ofList [(3, "THREE"), (4, "four")]))\n'
                '        let split = Map.partition (fun k v -> k > 1) m\n'
                '        let passing = Map.toList (fst split)\n'
                '        let failing = Map.toList (snd split)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_members_lower_to_pythons_own_str_methods',
        "files": {
            'main.pyfun': (
                'let a = String.trimStart " x"\n'
                'let b = String.splitLines "y"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_string_sweep',
        "files": {
            'main.pyfun': (
                '\n'
                '        let empty = String.isEmpty ""\n'
                '        let full = String.isEmpty "a"\n'
                '        let at = String.get 1 "abc"\n'
                '        let past = String.get 9 "abc"\n'
                '        let thrice = String.repeat 3 "ab"\n'
                '        let none = String.repeat 0 "ab"\n'
                '        let left = String.trimStart "  hi  "\n'
                '        let right = String.trimEnd "  hi  "\n'
                '        let lines = String.splitLines "a\\nb\\nc\\n"\n'
                '        let backwards = String.rev "abc"\n'
                '        let joined = String.ofList ["a", "b", "c"]\n'
                '        let roundTrip = String.ofList (String.toList "xyz")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_deferred_field_reads_the_right_attribute',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Placed = { row: int, col: int, letter: string }\n'
                '        type Cell = { row: int, col: int, letter: string, blank: bool }\n'
                '        let describe c =\n'
                '            let l = c.letter\n'
                '            let flag = c.blank\n'
                '            f"{l}/{flag}"\n'
                '        let out = describe (Cell { row = 1, col = 2, letter = "A", blank = false })\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sign_lowers_without_a_branch',
        "files": {
            'main.pyfun': 'let s = sign (-5)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_empty_is_an_exhausted_iterator',
        "files": {
            'main.pyfun': 'let xs = Seq.toList Seq.empty',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_the_audit_members',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [1, 2, 3, 1, 2]\n'
                '        let taken = List.takeWhile (fun x -> x < 3) xs\n'
                '        let dropped = List.dropWhile (fun x -> x < 3) xs\n'
                '        let desc = List.sortByDescending (fun x -> x) xs\n'
                '        let counted = List.countBy (fun x -> x % 2) xs\n'
                '        let uniqBy = Seq.toList (Seq.distinctBy (fun x -> x % 2) (Seq.ofList xs))\n'
                '        let copies = Seq.toList (Seq.replicate 3 "a")\n'
                '        let none = Seq.toList Seq.empty\n'
                '        let at = Seq.get 2 (Seq.ofList xs)\n'
                '        let final = Seq.last (Seq.ofList xs)\n'
                '        let doubled = Seq.sumBy (fun x -> x * 2) (Seq.ofList xs)\n'
                '        let biggest = Seq.max (Seq.ofList xs)\n'
                '        let smallest = Seq.min (Seq.ofList xs)\n'
                '        let joined = Seq.reduce (fun a b -> a + b) (Seq.ofList xs)\n'
                '        let holds = Option.forall (fun x -> x > 0) (Some 1)\n'
                '        let has = Option.contains 1 (Some 1)\n'
                '        let okHas = Result.contains 1 (Ok 1)\n'
                '        let negative = sign (-5)\n'
                '        let zero = sign 0\n'
                '        let positive = sign 42\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'result_map2_reports_the_first_error',
        "files": {
            'main.pyfun': 'let r = Result.map2 (fun a b -> a + b) (Ok 1) (Ok 2)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_sweep',
        "files": {
            'main.pyfun': (
                '\n'
                '        let some1 = Some 1\n'
                '        let some2 = Some 2\n'
                '        let none = List.head (List.drop 9 [1])\n'
                '        let both = Option.map2 (fun a b -> a + b) some1 some2\n'
                '        let missing = Option.map2 (fun a b -> a + b) some1 none\n'
                '        let kept = Option.orElse some2 some1\n'
                '        let fellBack = Option.orElse some2 none\n'
                '        let flat = Option.flatten (Some (Some 5))\n'
                '        let flatNone = Option.flatten (Some none)\n'
                '        let listed = Option.toList some1\n'
                '        let empty = Option.toList none\n'
                '        let holds = Option.exists (fun x -> x > 0) some1\n'
                '        let holdsNot = Option.exists (fun x -> x > 0) none\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_result_sweep',
        "files": {
            'main.pyfun': (
                '\n'
                '        let ok1 = Ok 1\n'
                '        let ok2 = Ok 2\n'
                '        let bad = Error "boom"\n'
                '        let both = Result.map2 (fun a b -> a + b) ok1 ok2\n'
                '        let failed = Result.map2 (fun a b -> a + b) bad ok2\n'
                '        let kept = Result.orElse ok2 ok1\n'
                '        let fellBack = Result.orElse ok2 bad\n'
                '        let listed = Result.toList ok1\n'
                '        let empty = Result.toList bad\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_lazy_members_route_to_pythons_lazy_machinery',
        "files": {
            'main.pyfun': (
                'let s = Seq.toList (Seq.drop 1 (Seq.takeWhile (fun x -> x < 3) (Seq.ofList [1, 2])))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_distinct_is_a_generator_not_a_list',
        "files": {
            'main.pyfun': 'let s = Seq.toList (Seq.distinct (Seq.ofList [1, 1]))',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_unfold_yields_until_none',
        "files": {
            'main.pyfun': 'let s = Seq.toList (Seq.take 1 (Seq.unfold (fun n -> Some (n, n)) 0))',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_lazy_members',
        "files": {
            'main.pyfun': (
                '\n'
                '        let dropped = Seq.toList (Seq.drop 2 (Seq.ofList [1, 2, 3, 4]))\n'
                '        let taken = Seq.toList (Seq.takeWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))\n'
                '        let skipped = Seq.toList (Seq.dropWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))\n'
                '        let joined = Seq.toList (Seq.concat (Seq.ofList [1, 2]) (Seq.ofList [3]))\n'
                '        let flat = Seq.toList (Seq.flatten (Seq.ofList [Seq.ofList [1, 2], Seq.ofList [3]]))\n'
                '        let mapped = Seq.toList (Seq.collect (fun x -> Seq.ofList [x, x]) (Seq.ofList [1, 2]))\n'
                '        let zipped = Seq.toList (Seq.zip (Seq.ofList [1, 2]) (Seq.ofList ["a", "b"]))\n'
                '        let ix = Seq.toList (Seq.indexed (Seq.ofList ["a", "b"]))\n'
                '        let uniq = Seq.toList (Seq.distinct (Seq.ofList [1, 1, 2, 1, 3]))\n'
                '        let pairs = Seq.toList (Seq.pairwise (Seq.ofList [1, 2, 3]))\n'
                '        let built = Seq.toList (Seq.init 4 (fun i -> i * i))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_can_be_endless',
        "files": {
            'main.pyfun': (
                '\n'
                '        let doubles = Seq.toList (Seq.take 5 (Seq.initInfinite (fun i -> i * 2)))\n'
                '        let powers = Seq.toList (Seq.take 4 (Seq.unfold (fun s -> if s > 100 then None else Some (s, s * 2)) 1))\n'
                '        let firstBig = Seq.find (fun x -> x > 6) (Seq.initInfinite (fun i -> i * 2))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_consuming_members',
        "files": {
            'main.pyfun': (
                '\n'
                '        let first = Seq.head (Seq.ofList [7, 8])\n'
                '        let none = Seq.head (Seq.ofList [])\n'
                '        let empty = Seq.isEmpty (Seq.ofList [])\n'
                '        let full = Seq.isEmpty (Seq.ofList [1])\n'
                '        let n = Seq.len (Seq.ofList [1, 2, 3])\n'
                '        let any = Seq.exists (fun x -> x > 2) (Seq.ofList [1, 2, 3])\n'
                '        let all = Seq.forall (fun x -> x > 0) (Seq.ofList [1, 2, 3])\n'
                '        let has = Seq.contains 2 (Seq.ofList [1, 2, 3])\n'
                '        let total = Seq.sum (Seq.ofList [1, 2, 3])\n'
                '        let found = Seq.find (fun x -> x > 1) (Seq.ofList [1, 2, 3])\n'
                '        let missing = Seq.find (fun x -> x > 9) (Seq.ofList [1, 2, 3])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_slicing_lowers_to_clamped_slices',
        "files": {
            'main.pyfun': (
                'let a = List.take 2 [1, 2, 3]\n'
                'let b = List.drop 2 [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_distinct_lowers_to_the_order_preserving_idiom',
        "files": {
            'main.pyfun': 'let d = List.distinct [1, 1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_sort_by_passes_a_key_function',
        "files": {
            'main.pyfun': 'let s = List.sortBy (fun x -> 0 - x) [1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_partition_tests_each_element_once',
        "files": {
            'main.pyfun': 'let p = List.partition (fun x -> x > 1) [1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fst_and_snd_lower_to_subscripts',
        "files": {
            'main.pyfun': (
                'let a = fst (1, 2)\n'
                'let b = snd (1, 2)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_access_and_slicing',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 4, 1, 5]\n'
                '        let first = List.head xs\n'
                '        let none = List.head (List.drop 9 [1])\n'
                '        let rest = List.tail xs\n'
                '        let taken = List.take 2 xs\n'
                '        let dropped = List.drop 3 xs\n'
                '        let overTake = List.take 99 xs\n'
                '        let negTake = List.take (-1) xs\n'
                '        let split = List.splitAt 2 xs\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_transform_query_and_order',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 4, 1, 5]\n'
                '        let summed = List.map2 (fun a b -> a + b) [1, 2, 3] [10, 20]\n'
                '        let ix = List.indexed ["a", "b"]\n'
                '        let any = List.exists (fun x -> x > 4) xs\n'
                '        let all = List.forall (fun x -> x > 0) xs\n'
                '        let at = List.findIndex (fun x -> x == 4) xs\n'
                '        let missing = List.findIndex (fun x -> x == 99) xs\n'
                '        let desc = List.sortDescending xs\n'
                '        let uniq = List.distinct xs\n'
                '        let grouped = List.groupBy (fun x -> x % 2) [1, 2, 3, 4]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_aggregate_structure_and_windows',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 4, 1, 5]\n'
                '        let biggest = List.max xs\n'
                '        let smallest = List.min xs\n'
                '        let noMax = List.max (List.drop 9 [1])\n'
                '        let doubled = List.sumBy (fun x -> x * 2) [1, 2, 3]\n'
                '        let mean = List.average [1.0, 2.0, 4.0]\n'
                '        let joined = List.reduce (fun a b -> a + b) [1, 2, 3]\n'
                '        let split = List.partition (fun x -> x > 2) xs\n'
                '        let apart = List.unzip (List.zip [1, 2] ["a", "b"])\n'
                '        let flat = List.flatten [[1, 2], [3]]\n'
                '        let squares = List.init 4 (fun i -> i * i)\n'
                '        let copies = List.replicate 3 "x"\n'
                '        let updated = List.updateAt 1 99 [1, 2, 3]\n'
                '        let untouched = List.updateAt 9 99 [1, 2, 3]\n'
                '        let inserted = List.insertAt 1 99 [1, 2, 3]\n'
                '        let removed = List.removeAt 1 [1, 2, 3]\n'
                '        let pairs = List.pairwise [1, 2, 3]\n'
                '        let windows = List.windowed 2 [1, 2, 3]\n'
                '        let chunks = List.chunkBySize 2 [1, 2, 3]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_fst_and_snd',
        "files": {
            'main.pyfun': (
                '\n'
                '        let pairs = List.zip [1, 2] ["a", "b"]\n'
                '        let firsts = List.map fst pairs\n'
                '        let seconds = List.map snd pairs\n'
                '        let one = fst (1, "one")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tuple_literal_lowers_to_python_tuple',
        "files": {
            'main.pyfun': (
                'let pair = (1, 2)\n'
                'let triple = (1, true, 3)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tuple_pattern_lowers_to_sequence_pattern',
        "files": {
            'main.pyfun': 'let swap p = match p: case (a, b): (b, a)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_parameter_unpacks_at_the_top_of_the_body',
        "files": {
            'main.pyfun': 'let tileScore (t, sq) = t * sq',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_nested_tuple_parameter_unpacks_one_level_at_a_time',
        "files": {
            'main.pyfun': 'let nested ((a, b), c) = a + b + c',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_destructuring_lambda_becomes_a_def_not_a_lambda',
        "files": {
            'main.pyfun': (
                'let pairs = List.zip [1, 2] [3, 4]\n'
                '         let total = List.fold (fun acc (a, b) -> acc + a * b) 0 pairs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_record_parameter_reads_the_fields_it_names',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int, col: int, letter: string }\n'
                '         let describe (Cell { letter, row }) = letter'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_nested_record_parameter_reads_through_a_temp',
        "files": {
            'main.pyfun': (
                'type Cell = { letter: string }\n'
                '         type Pair = { left: Cell, right: Cell }\n'
                '         let leftLetter (Pair { left = Cell { letter } }) = letter'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_record_parameters_round_trip',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Cell = { row: int, col: int, letter: string }\n'
                '        type Pair = { left: Cell, right: Cell }\n'
                '        let describe (Cell { letter, row }) = letter\n'
                '        let leftLetter (Pair { left = Cell { letter } }) = letter\n'
                '        let both (Pair { left, right }) = (left.letter, right.letter)\n'
                '        let a = Cell { row = 1, col = 2, letter = "A" }\n'
                '        let b = Cell { row = 3, col = 4, letter = "B" }\n'
                '        let p = Pair { left = a, right = b }\n'
                '        let one = describe a\n'
                '        let deep = leftLetter p\n'
                '        let pairOf = both p\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_wildcard_parameter_emits_pythons_throwaway_name',
        "files": {
            'main.pyfun': 'let const42 _ = 42',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_tuple_parameters_round_trip',
        "files": {
            'main.pyfun': (
                '\n'
                '        let tileScore (t, sq) = t * sq\n'
                '        let swap (a, b) = (b, a)\n'
                '        let nested ((a, b), c) = a + b + c\n'
                '        let const42 _ = 42\n'
                '        let pairs = List.zip [1, 2, 3] [10, 20, 30]\n'
                '        let scores = List.map tileScore pairs\n'
                '        let total = List.fold (fun acc (a, b) -> acc + a * b) 0 pairs\n'
                '        let swapped = swap (1, 2)\n'
                '        let deep = nested ((1, 2), 3)\n'
                '        let ignored = const42 "anything"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_tuple_construct_and_destructure',
        "files": {
            'main.pyfun': (
                '\n'
                '        let swap p =\n'
                '          match p:\n'
                '            case (a, b): (b, a)\n'
                '        let fst t =\n'
                '          match t:\n'
                '            case (a, _): a\n'
                '        let pair = (10, 20)\n'
                '        let s = swap pair\n'
                '        let first = fst pair\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_tuple_pattern',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f t =\n'
                '          match t:\n'
                '            case ((a, b), c): a + b + c\n'
                '        let r = f ((1, 2), 3)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_pattern_lowers_to_a_bracket_sequence_pattern',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x, *rest]: x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'wildcard_rest_lowers_to_star_underscore',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [x, *_]: x\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'suffix_star_lowers_to_a_python_mid_star_sequence_pattern',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x]: x\n'
                '    case [a, *mid, z]: a + z'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'suffix_star_lowers_to_a_python_mid_star_sequence_pattern_2',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [*init, last]: last\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_suffix_and_mid_star_patterns',
        "files": {
            'main.pyfun': (
                '\n'
                '        let lastOr fallback xs =\n'
                '          match xs:\n'
                '            case [*_, last]: last\n'
                '            case []: fallback\n'
                '        let bounds xs =\n'
                '          match xs:\n'
                '            case []: 0\n'
                '            case [x]: x\n'
                '            case [first, *mid, last]: first + last + List.len mid\n'
                '        let a = lastOr 0 [5, 6, 7]\n'
                '        let b = lastOr 9 []\n'
                '        let c = bounds [1, 2, 3, 4]\n'
                '        let d = bounds [7]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_sum_with_sequence_patterns',
        "files": {
            'main.pyfun': (
                '\n'
                '        let sum xs =\n'
                '          match xs:\n'
                '            case []: 0\n'
                '            case [x, *rest]: x + sum rest\n'
                '        let total = sum [1, 2, 3, 4]\n'
                '        let empty = sum []\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_list_fixed_length_and_nested_patterns',
        "files": {
            'main.pyfun': (
                '\n'
                '        let describe xs =\n'
                '          match xs:\n'
                '            case []: 0\n'
                '            case [x]: 1\n'
                '            case [x, y]: 2\n'
                '            case [x, y, *rest]: 3\n'
                '        let head xs =\n'
                '          match xs:\n'
                '            case [Some x, *rest]: x\n'
                '            case _: 0\n'
                '        let a = describe [10, 20, 30]\n'
                '        let b = describe [7]\n'
                '        let c = describe []\n'
                '        let d = head [Some 42, None]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_record_pattern_match',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let classify p =\n'
                '          match p:\n'
                '            case Point { x = 0, y = 0 }: 1\n'
                '            case Point { x = 0 }: 2\n'
                '            case Point { x, y }: x + y\n'
                '        let a = classify (Point { x = 0, y = 0 })\n'
                '        let b = classify (Point { x = 0, y = 9 })\n'
                '        let c = classify (Point { x = 3, y = 4 })\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_record_and_constructor_pattern',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Box = { item: Option int, tag: bool }\n'
                '        let f b =\n'
                '          match b:\n'
                '            case Box { item = Some n, tag = true }: n\n'
                '            case Box { item = Some n }: n + 100\n'
                '            case _: 0\n'
                '        let a = f (Box { item = Some 5, tag = true })\n'
                '        let b = f (Box { item = Some 5, tag = false })\n'
                '        let c = f (Box { item = None, tag = true })\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_deep_exhaustive_match_without_wildcard',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          match o:\n'
                '            case Some true: 1\n'
                '            case Some false: 2\n'
                '            case None: 3\n'
                '        let a = f (Some true)\n'
                '        let b = f (Some false)\n'
                '        let c = f None\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'block_body_lowers_to_statement_sequence',
        "files": {
            'main.pyfun': (
                'let sum3 a b c =\n'
                '    let mut acc = 0\n'
                '    acc <- acc + a\n'
                '    acc <- acc + b\n'
                '    acc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'top_level_assignment_lowers_to_plain_assign',
        "files": {
            'main.pyfun': (
                'let mut x = 0\n'
                'x <- x + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'closure_reassigning_a_module_mut_emits_global',
        "files": {
            'main.pyfun': (
                'let counter =\n'
                '  let mut n = 0\n'
                '  let bump x =\n'
                '    n <- n + x\n'
                '    n\n'
                '  bump 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'closure_reassigning_an_enclosing_fn_mut_emits_nonlocal',
        "files": {
            'main.pyfun': (
                'let make base =\n'
                '  let mut n = base\n'
                '  let bump x =\n'
                '    n <- n + x\n'
                '    n\n'
                '  bump 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'local_only_mut_needs_no_capture_declaration',
        "files": {
            'main.pyfun': (
                'let scaled a b =\n'
                '  let mut acc = a\n'
                '  acc <- acc + b\n'
                '  acc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_closure_reassigns_captured_mut',
        "files": {
            'main.pyfun': (
                '\n'
                '        let counter =\n'
                '          let mut n = 0\n'
                '          let bump x =\n'
                '            n <- n + x\n'
                '            n\n'
                '          let a = bump 5\n'
                '          bump 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_nonlocal_closure_in_a_function',
        "files": {
            'main.pyfun': (
                '\n'
                '        let make base =\n'
                '          let mut n = base\n'
                '          let bump x =\n'
                '            n <- n + x\n'
                '            n\n'
                '          let a = bump 5\n'
                '          bump 3\n'
                '        let r = make 100\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'nested_local_let_lowers_to_nested_assignments',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '    let y =\n'
                '        let mut t = x\n'
                '        t <- t + 1\n'
                '        t\n'
                '    y'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'comparison_operators_lower_to_python',
        "files": {
            'main.pyfun': (
                'let a = 1 < 2\n'
                'let b = 1 == 2\n'
                'let c = 1 != 2\n'
                'let d = 1 >= 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'boolean_operators_lower_to_python_keywords_with_precedence',
        "files": {
            'main.pyfun': 'let r = true and false',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'boolean_operators_lower_to_python_keywords_with_precedence_2',
        "files": {
            'main.pyfun': 'let r = true or false',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'boolean_operators_lower_to_python_keywords_with_precedence_3',
        "files": {
            'main.pyfun': 'let r = not true',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'boolean_operators_lower_to_python_keywords_with_precedence_4',
        "files": {
            'main.pyfun': 'let r = not 1 == 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'boolean_operators_lower_to_python_keywords_with_precedence_5',
        "files": {
            'main.pyfun': 'let r = (not true) == false',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'prelude_partial_application_uses_partial',
        "files": {
            'main.pyfun': 'let clamp0 = max 0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'recursive_call_lowers_to_a_direct_call',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_self_tail_call_becomes_a_loop',
        "files": {
            'main.pyfun': (
                'let countdown n =\n'
                '  if n == 0 then "done"\n'
                '  else countdown (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'several_parameters_rebind_simultaneously',
        "files": {
            'main.pyfun': (
                'let sumTo n acc =\n'
                '  if n == 0 then acc\n'
                '  else sumTo (n - 1) (acc + n)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_tail_call_in_a_match_arm_becomes_a_loop',
        "files": {
            'main.pyfun': (
                'let classify n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case _: classify (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_non_tail_self_call_is_left_recursive',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  if n == 0 then 0\n'
                '  else 1 + f (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'mutual_recursion_is_left_alone',
        "files": {
            'main.pyfun': (
                '\n'
                '        let evens n =\n'
                '          if n == 0 then true\n'
                '          else odds (n - 1)\n'
                '        let odds n =\n'
                '          if n == 0 then false\n'
                '          else evens (n - 1)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_closure_over_a_parameter_blocks_the_loop',
        "files": {
            'main.pyfun': (
                '\n'
                '        let collect n acc =\n'
                '          if n == 0 then acc\n'
                '          else collect (n - 1) (List.concat acc [fun k -> n])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_shadowing_lambda_parameter_does_not_block_the_loop',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f n =\n'
                '          if n == 0 then 0\n'
                '          else\n'
                '            let doubled = List.map (fun n -> n + 1) [1, 2]\n'
                '            f (n - 1)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_looped_self_tail_call_says_nothing',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  if n == 0 then 0\n'
                '  else f (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'an_async_self_tail_call_becomes_a_loop_in_the_coroutine',
        "files": {
            'main.pyfun': (
                'let finished acc = async { return acc }\n'
                'let loop n acc =\n'
                '  async {\n'
                '    return! (if n == 0 then finished acc else loop (n - 1) (acc + n))\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_return_bang_match_returns_per_arm',
        "files": {
            'main.pyfun': (
                'type Msg = Go int | Stop\n'
                'let finished n = async { return n }\n'
                'let loop n =\n'
                '  async {\n'
                '    return! (match n:\n'
                '      case Go k: loop Stop\n'
                '      case Stop: finished 0)\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_rejected_async_self_tail_call_says_why',
        "files": {
            'main.pyfun': (
                'let finished acc = async { return acc }\n'
                'let collect n acc =\n'
                '  async {\n'
                '    return! (if n == 0 then finished acc else collect (n - 1) (List.concat acc [fun k -> n]))\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_mut_assigned_in_an_async_block_declares_global',
        "files": {
            'main.pyfun': (
                'let mut flag = false\n'
                'let raiseFlag _ =\n'
                '  async {\n'
                '    flag <- true\n'
                '    return ()\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_mut_assigned_in_a_result_block_declares_global',
        "files": {
            'main.pyfun': (
                'let mut attempts = 0\n'
                'let step x = result {\n'
                '  attempts <- attempts + 1\n'
                '  return x + 1\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_function_mut_assigned_in_an_async_block_declares_nonlocal',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let bump _ =\n'
                '  let mut n = 0\n'
                '  let work = async {\n'
                '    n <- n + 1\n'
                '    return ()\n'
                '  }\n'
                '  runAsync work\n'
                '  n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_self_tail_call_recurses_past_the_stack_limit',
        "files": {
            'main.pyfun': (
                '\n'
                '        let countdown n =\n'
                '          if n == 0 then "done"\n'
                '          else countdown (n - 1)\n'
                '        let sumTo n acc =\n'
                '          if n == 0 then acc\n'
                '          else sumTo (n - 1) (acc + n)\n'
                '        let deep = countdown 50000\n'
                '        let total = sumTo 100000 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_over_a_parameter_keeps_per_frame_values',
        "files": {
            'main.pyfun': (
                '\n'
                '        let collect n acc =\n'
                '          if n == 0 then acc\n'
                '          else collect (n - 1) (List.concat acc [fun k -> n])\n'
                '        let fns = collect 3 []\n'
                '        let values = List.map (fun f -> f 0) fns\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_recursive_functions',
        "files": {
            'main.pyfun': (
                '\n'
                '        let fact n =\n'
                '          if n == 0 then 1\n'
                '          else n * fact (n - 1)\n'
                '        let fib n =\n'
                '          if n < 2 then n\n'
                '          else fib (n - 1) + fib (n - 2)\n'
                '        let a = fact 6\n'
                '        let b = fib 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_currying_full_partial_and_over_application',
        "files": {
            'main.pyfun': (
                '\n'
                '        let add a b = a + b\n'
                '        let inc = add 1\n'
                '        let twice f x = f (f x)\n'
                '        let r1 = add 1 2\n'
                '        let r2 = inc 41\n'
                '        let r3 = twice inc 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_pipe_and_composition',
        "files": {
            'main.pyfun': (
                '\n'
                '        let add a b = a + b\n'
                '        let inc = add 1\n'
                '        let compose = fun f g x -> f (g x)\n'
                '        let r = 4 |> inc |> inc\n'
                '        let r2 = (compose inc inc) 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'backward_pipe_lowers_to_application',
        "files": {
            'main.pyfun': (
                'let inc n = n + 1\n'
                'let a = inc <| 5\n'
                'let b = inc <| inc <| 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_backward_pipe',
        "files": {
            'main.pyfun': (
                '\n'
                '        let inc n = n + 1\n'
                '        let twice n = n * 2\n'
                '        let a = inc <| 5\n'
                '        let b = inc <| twice <| 5\n'
                '        let c = twice <| inc 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_elif_chain_selects_the_right_branch',
        "files": {
            'main.pyfun': (
                '\n'
                '        let grade n =\n'
                '          if n >= 90 then "A"\n'
                '          elif n >= 80 then "B"\n'
                '          elif n >= 70 then "C"\n'
                '          else "F"\n'
                '        let a = grade 95\n'
                '        let b = grade 85\n'
                '        let c = grade 72\n'
                '        let f = grade 50\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_if_and_match',
        "files": {
            'main.pyfun': (
                '\n'
                '        let classify n =\n'
                '          match n:\n'
                '            case 0: "zero"\n'
                '            case 1: "one"\n'
                '            case _: "many"\n'
                '        let r1 = classify 0\n'
                '        let r2 = classify 7\n'
                '        let r3 = if true then 10 else 20\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_blocks_in_match_arms_and_if_branches',
        "files": {
            'main.pyfun': (
                '\n'
                '        let classify n =\n'
                '          match n:\n'
                '            case 0:\n'
                '              let base = 100\n'
                '              base\n'
                '            case _:\n'
                '              let mut acc = n\n'
                '              acc <- acc * 2\n'
                '              acc\n'
                '        let absdiff a b =\n'
                '          if a > b then\n'
                '              let d = a - b\n'
                '              d\n'
                '          else\n'
                '              let d = b - a\n'
                '              d\n'
                '        let r1 = classify 0\n'
                '        let r2 = classify 5\n'
                '        let r3 = absdiff 3 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_block_in_lambda_body',
        "files": {
            'main.pyfun': (
                '\n'
                '        let doubler = fun x ->\n'
                '          let y = x + x\n'
                '          y\n'
                '        let r = doubler 21\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_division_operators_match_python',
        "files": {
            'main.pyfun': 'let q = 7 / 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_division_operators_match_python_2',
        "files": {
            'main.pyfun': 'let d = 7 // 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_match_in_value_position_is_hoisted',
        "files": {
            'main.pyfun': 'let r = (match 1: case 1: 10 case _: 20) + 5',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_adt_construction_and_match',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Color = Red | Green | Blue\n'
                '        let unwrap o = match o: case Some v: v case None: 0\n'
                '        let r1 = unwrap (Some 5)\n'
                '        let r2 = unwrap None\n'
                '        let rank c = match c: case Red: 1 case Green: 2 case Blue: 3\n'
                '        let r3 = rank Green\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_records_construct_access_and_update',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let p = Point { x = 3, y = 4 }\n'
                '        let moved = { p with x = 10 }\n'
                '        let sx = p.x\n'
                '        let sy = moved.y\n'
                '        let mx = moved.x\n'
                '        let sumxy r = r.x + r.y\n'
                '        let total = sumxy p\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_record_update',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Inner = { a: int, b: int }\n'
                '        type Outer = { inner: Inner, tag: string }\n'
                '        let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }\n'
                '        let o2 = { o with inner.a = 99 }\n'
                '        let both = { o with inner.a = 10, tag = "y" }\n'
                '        let na = o2.inner.a\n'
                '        let nb = o2.inner.b\n'
                '        let nt = o2.tag\n'
                '        let ba = both.inner.a\n'
                '        let bt = both.tag\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_polymorphic_record_field',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Box a = { item: a }\n'
                '        let mk v = Box { item = v }\n'
                '        let i = (mk 42).item\n'
                '        let s = (mk "hi").item\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_blocks_and_mutation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let sum3 a b c =\n'
                '            let mut acc = 0\n'
                '            acc <- acc + a\n'
                '            acc <- acc + b\n'
                '            acc <- acc + c\n'
                '            acc\n'
                '        let nested x =\n'
                '            let y =\n'
                '                let mut t = x\n'
                '                t <- t * 2\n'
                '                t\n'
                '            y + 1\n'
                '        let r1 = sum3 1 2 3\n'
                '        let r2 = nested 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_top_level_mutation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let mut counter = 0\n'
                '        counter <- counter + 1\n'
                '        counter <- counter + 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_recursive_adt',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Lst a = Nil | Cons a (Lst a)\n'
                '        let head d xs = match xs: case Nil: d case Cons h t: h\n'
                '        let r = head 0 (Cons 7 (Cons 8 Nil))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'units_are_erased_in_emitted_python',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let speed = 100<m> / 10<s>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_units_compute_after_erasure',
        "files": {
            'main.pyfun': (
                '\n'
                '        measure m\n'
                '        measure s\n'
                '        let dist = 100<m>\n'
                '        let time = 10<s>\n'
                '        let speed = dist / time\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_derived_measure_aliases_erase',
        "files": {
            'main.pyfun': (
                '\n'
                '        measure kg\n'
                '        measure m\n'
                '        measure s\n'
                '        measure N = kg m / s^2\n'
                '        measure Pa = N / m^2\n'
                '        let force = 10<N>\n'
                '        let area = 2<m^2>\n'
                '        let pressure = force / area\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_result_ce_binds_and_short_circuits',
        "files": {
            'main.pyfun': (
                '\n'
                '        let safe ok v = result { let! x = if ok then Ok v else Error 9  return (x + 1) }\n'
                '        let unwrap r = match r: case Ok n: n case Error e: e\n'
                '        let r1 = unwrap (safe true 10)\n'
                '        let r2 = unwrap (safe false 10)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_ce_produces_a_generator',
        "files": {
            'main.pyfun': 'let xs = seq { yield 1  yield! (seq { yield 2  yield 3 }) }',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_async_ce_produces_a_coroutine',
        "files": {
            'main.pyfun': 'let twice = async { let! x = async { return 21 }  return (x + x) }',
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_format_module_formats_numbers_and_strings',
        "files": {
            'main.pyfun': (
                'let a = Format.fixed 2 3.14159\n'
                'let b = Format.thousands 2 1234567.5\n'
                'let c = Format.percent 1 0.256\n'
                'let d = Format.currency "$" 2 1234.5\n'
                'let e = Format.grouped 1234567\n'
                'let f = Format.padLeft 6 "0" "42"\n'
                'let g = Format.padRight 6 "." "42"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_user_monad_ce_binds_and_short_circuits',
        "files": {
            'main.pyfun': (
                '\n'
                '        module Maybe =\n'
                '          let bind m f = match m: case Some x: f x case None: None\n'
                '          let return_ x = Some x\n'
                '        let safe a b =\n'
                '          Maybe {\n'
                '            let! x = a\n'
                '            let! y = b\n'
                '            return x + y\n'
                '          }\n'
                '        let unwrap m = match m: case Some n: n case None: 0\n'
                '        let r1 = unwrap (safe (Some 3) (Some 4))\n'
                '        let r2 = unwrap (safe (Some 3) None)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_user_yield_ce_combines_via_delay',
        "files": {
            'main.pyfun': (
                '\n'
                '        module Sum =\n'
                '          let yield_ x = x\n'
                '          let combine a b = a + b\n'
                '          let delay f = f 0\n'
                '        let total =\n'
                '          Sum {\n'
                '            yield 1\n'
                '            yield 2\n'
                '            yield 3\n'
                '            yield 4\n'
                '          }\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'user_ce_lowers_to_plain_calls',
        "files": {
            'main.pyfun': (
                '\n'
                '        module M =\n'
                '          let bind m f = f m\n'
                '          let return_ x = x\n'
                '        let r = M { let! x = 3  return x }\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
                'let root = tan 0.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_extern_import_calls_python',
        "files": {
            'main.pyfun': (
                'extern import datetime\n'
                'extern parse: string -> a = datetime.datetime.fromisoformat\n'
                'let d = parse "2020-01-02"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let q = List.range 1 4'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let e = Set.len Set.empty'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'int_literal_unified_to_float_lowers_to_a_float_literal',
        "files": {
            'main.pyfun': (
                'let xs = [1.0, 2, 3.0]\n'
                'let pick b = if b then 1 else 1.5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'int_literal_unified_to_float_lowers_to_a_float_literal_2',
        "files": {
            'main.pyfun': (
                'let n = 7\n'
                'let m = n + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_int_literal_unified_to_float_prints_as_float',
        "files": {
            'main.pyfun': (
                'let xs = [1.0, 2, 3.0]\n'
                'let pick b = if b then 1 else 1.5\n'
                'let r = pick true'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let flipped = List.map (flip sub 100) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let miss = Option.withDefault 0 (Map.tryFind "z" m)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let npts = Set.len pts'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_seq_module_is_lazy',
        "files": {
            'main.pyfun': (
                'let nats = Seq.range 0 1000000\n'
                'let squares = Seq.toList (Seq.take 5 (Seq.map (fun x -> x * x) nats))\n'
                'let evens = Seq.toList (Seq.take 3 (Seq.filter (fun x -> x // 2 * 2 == x) nats))\n'
                'let total = Seq.fold (fun acc x -> acc + x) 0 (Seq.ofList [1, 2, 3, 4])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let p = Geometry.pi'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let g = Result.isError (Result.mapError (fun s -> s) r2)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let e = Option.map (fun x -> x + 1) some'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'active_pattern_match_lowers_to_an_if_elif_chain',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even: "e"\n'
                '    case Odd: "o"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'bool_partial_lowers_to_a_truthiness_test',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'distinct_parameterized_applications_hoist_separately',
        "files": {
            'main.pyfun': (
                'let (|DivisibleBy|_|) d n = n % d == 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case DivisibleBy 3: 1\n'
                '    case DivisibleBy 5: 2\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let c = describe 7'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let c = classify 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let b = f 7'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let b = f 25'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let b = f (-3)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let b = f "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let d = fizz 7'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_active_pattern_match_in_value_position',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let r =\n'
                '  match 6:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_arm_lowers_to_an_or_of_isinstance_tests',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even | Odd: "eo"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'structural_arm_lowers_to_a_one_armed_native_match',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let f o =\n'
                '  match o:\n'
                '    case Answer: 1\n'
                '    case Some x: x\n'
                '    case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'structural_arm_beside_active_pattern_in_value_position',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let classify o =\n'
                '  let label =\n'
                '    match o:\n'
                '      case Answer: "answer"\n'
                '      case Some n: String.fromInt n\n'
                '      case None: "none"\n'
                '  String.concat label "!"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let d = describe None'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_primitives_and_totality',
        "files": {
            'main.pyfun': (
                'let ok = Result.withDefault 0 (Decode.decodeString Decode.int "42")\n'
                'let wrongType = Result.withDefault (0 - 1) (Decode.decodeString Decode.int "\\"x\\"")\n'
                'let boolNotInt = Result.withDefault (0 - 1) (Decode.decodeString Decode.int "true")\n'
                'let intAsFloat = Result.withDefault 0.0 (Decode.decodeString Decode.float "3")\n'
                'let malformed = Result.isError (Decode.decodeString Decode.bool "not json")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let missing = Result.isError (Decode.decodeString dec """{"name": "bob"}""")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_decode_list_nullable_oneof_andthen',
        "files": {
            'main.pyfun': (
                'let nums = Result.withDefault [] (Decode.decodeString (Decode.list Decode.int) "[1, 2, 3]")\n'
                'let flex = Decode.oneOf [Decode.string, Decode.map String.fromInt Decode.int]\n'
                'let fromStr = Result.withDefault "?" (Decode.decodeString flex "\\"hi\\"")\n'
                'let fromInt = Result.withDefault "?" (Decode.decodeString flex "7")\n'
                'let n = Result.withDefault (0 - 1) (Decode.decodeString (Decode.oneOf []) "1")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_pipeline_is_pure',
        "files": {
            'main.pyfun': (
                'let pure parse s = Decode.decodeString Decode.int s\n'
                'let r = parse "1"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_spec_fires_on_inline_field',
        "files": {
            'main.pyfun': (
                'let r = Decode.decodeString (Decode.field "name" Decode.string) """{"name": "ada"}"""\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_spec_fires_through_named_decoder',
        "files": {
            'main.pyfun': (
                'type Pair = { name: string, age: int }\n'
                'let user =\n'
                '  Decode.map2 (fun name age -> Pair { name = name, age = age })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "age" Decode.int)\n'
                'let r = Decode.decodeString user """{"name": "ada", "age": 36}"""\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
                'let after = useBump 7'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let after = bump 7'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'top_level_block_without_collision_stays_unwrapped',
        "files": {
            'main.pyfun': (
                'let a =\n'
                '  let t = 1\n'
                '  t + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_opt_tuple_named_folder_lowers_to_loop',
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
                'let run cmds = List.fold step (Map.empty, []) cmds'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let out = match run [Put 1 10, Push 2, Skip, Put 3 30, Push 4]: case (m, xs): (Map.toList m, xs)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_opt_single_map_lambda_lowers_to_subscript_assign',
        "files": {
            'main.pyfun': (
                'let m = List.fold (fun m x -> Map.add x (x * 2) m) Map.empty [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_single_map_lambda',
        "files": {
            'main.pyfun': (
                'let m = List.fold (fun m x -> Map.add x (x * 2) m) Map.empty [1, 2, 3]\n'
                'let out = Map.toList m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_top_level_fold_keeps_its_loop_names_off_top_level_bindings',
        "files": {
            'main.pyfun': (
                'let x = 100\n'
                'let total = List.fold (fun acc e -> List.concat acc [e]) [] [1, 2, 3]\n'
                'let doubled = List.fold (fun acc x -> List.concat acc [x * 2]) [] [1, 2, 3]\n'
                'let out = (x, doubled, total)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_fold_inside_an_in_file_module_lowers_to_a_loop',
        "files": {
            'main.pyfun': (
                'module Stats =\n'
                '  let scale = 3\n'
                '  let tally xs = List.fold (fun acc x -> Map.add x (x * scale) acc) Map.empty xs\n'
                'let out = Map.toList (Stats.tally [1, 2])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_opt_cross_slot_read_is_hoisted_before_mutation',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, log): (Map.add x x m, List.concat log [Map.len m])\n'
                'let r = List.fold step (Map.empty, []) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_cross_slot_read',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, log): (Map.add x x m, List.concat log [Map.len m])\n'
                'let r = List.fold step (Map.empty, []) [1, 2, 3]\n'
                'let out = match r: case (m, log): (Map.toList m, log)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_opt_extend_form',
        "files": {
            'main.pyfun': 'let acc = List.fold (fun acc x -> List.concat acc [x, x]) [] [1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_extend_form',
        "files": {
            'main.pyfun': (
                'let acc = List.fold (fun acc x -> List.concat acc [x, x]) [] [1, 2]\n'
                'let out = acc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_opt_seq_fold_and_piped_form',
        "files": {
            'main.pyfun': (
                'let s = Seq.fold (fun m x -> Map.add x x m) Map.empty (Seq.range 0 3)\n'
                'let p = [1, 2, 3] |> List.fold (fun a x -> List.concat a [x]) []\n'
                'let so = Map.toList s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_opt_nonatomic_key_is_hoisted',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add (x + 1) x m\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_named_init_binding_gets_a_defensive_copy',
        "files": {
            'main.pyfun': (
                'let seed = Map.empty\n'
                'let grown = List.fold (fun m x -> Map.add x x m) seed [1, 2]\n'
                'let a = Map.len seed\n'
                'let b = Map.len grown'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_component_stored_into_other_slot',
        "files": {
            'main.pyfun': (
                'let g acc x =\n'
                '  match acc:\n'
                '    case (names, log): (Map.add x x names, List.concat log [names])\n'
                'let out = match List.fold g (Map.empty, []) [1, 2]: case (m, log): (Map.len m, List.map Map.len log)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_swapped_slots',
        "files": {
            'main.pyfun': (
                'let h acc x = match acc: case (a, b): (b, a)\n'
                'let out = List.fold h (0, 100) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_same_slot_twice',
        "files": {
            'main.pyfun': (
                'let dup acc x = match acc: case (m, n): (Map.add x x m, m)\n'
                'let out = match List.fold dup (Map.empty, Map.empty) [1, 2]: case (a, b): (Map.toList a, Map.toList b)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_closure_capture',
        "files": {
            'main.pyfun': (
                'let cap acc x =\n'
                '  match acc:\n'
                '    case (m, fs): (Map.add x x m, List.concat fs [fun u -> Map.len m])\n'
                'let out = match List.fold cap (Map.empty, []) [1, 2]: case (m, fs): List.map (fun f -> f 0) fs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_acc_escapes_to_user_function',
        "files": {
            'main.pyfun': (
                'let ins x acc = List.concat [x] acc\n'
                'let rev xs = List.fold (fun acc x -> ins x acc) [] xs\n'
                'let out = rev [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_acc_in_nontail_nonwhitelisted_position',
        "files": {
            'main.pyfun': (
                'let k acc x = if List.contains acc [[]] then acc else List.concat acc [x]\n'
                'let out = List.fold k [] [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_fresh_reset_slot',
        "files": {
            'main.pyfun': (
                'let rf acc x = match acc: case (m, n): if x == 0 then (Map.empty, n) else (Map.add x x m, n)\n'
                'let out = match List.fold rf (Map.empty, 0) [0, 1, 2]: case (m, n): (Map.toList m, n)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_free_var_capture_at_site',
        "files": {
            'main.pyfun': (
                'let base = 10\n'
                'let addb acc x = List.concat acc [x + base]\n'
                'let usefn n =\n'
                '  let base = 99\n'
                '  List.fold addb [] [1]\n'
                'let out = usefn 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_wildcard_slot',
        "files": {
            'main.pyfun': (
                'let w acc x = match acc: case (m, _): (Map.add x x m, Map.empty)\n'
                'let out = match List.fold w (Map.empty, Map.empty) [1, 2]: case (a, b): (Map.toList a, Map.toList b)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_a_named_folder_inside_an_in_file_module',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add x x m\n'
                'module M =\n'
                '  let scan xs = List.fold step Map.empty xs\n'
                'let r = Map.len (M.scan [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_partial_application',
        "files": {
            'main.pyfun': (
                'let f a b = a + b\n'
                'let g = List.fold f\n'
                'let out = g 0 [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_folder_is_a_parameter',
        "files": {
            'main.pyfun': (
                'let foldWith f = List.fold f Map.empty [1, 2, 3]\n'
                'let out = Map.len (foldWith (fun m x -> Map.add x x m))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_local_named_folder_block_lowers_to_loop',
        "files": {
            'main.pyfun': (
                'let build xs =\n'
                '  let step acc x = Map.add x (x * 2) acc\n'
                '  List.fold step Map.empty xs\n'
                'let out = Map.toList (build [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let out = List.map (fun l -> l.depMin) (dedupLegs [Leg { depMin = 1, dest = "a" }, Leg { depMin = 1, dest = "a" }, Leg { depMin = 2, dest = "b" }])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_shadow_rebound_local_folder_uses_newest_body',
        "files": {
            'main.pyfun': (
                'let build xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  let step acc x = List.concat acc [x * 2]\n'
                '  List.fold step [] xs\n'
                'let out = build [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_shadow_lambda_param_uses_parameter',
        "files": {
            'main.pyfun': (
                'let build combiner xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  (fun step -> List.fold step [] xs) combiner\n'
                'let out = build (fun acc x -> List.concat acc [x * 2]) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let out = build (Some (fun acc x -> List.concat acc [x * 2])) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_chained_map_add_updates_one_slot_inner_first',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add (x * 10) x (Map.add x x m)\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let out = match List.fold step ([], []) [1, 2, 0, 3, 0]: case (cur, groups): (cur, groups)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_map_remove_in_chain_lowers_to_pop',
        "files": {
            'main.pyfun': (
                'let step m x = Map.remove x (Map.add (x + 1) x m)\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_set_remove_in_chain_lowers_to_discard',
        "files": {
            'main.pyfun': (
                'let step s x = Set.remove (x - 1) (Set.add x s)\n'
                'let out = Set.toList (List.fold step Set.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let origs = (Map.len dseed, List.len lseed, Set.len sseed)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
                'let out = match r: case (m, keep): (Map.len m, Map.len keep, Map.len seed2)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_parameterized_local_let_closure',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  let peek u = Map.len acc\n'
                '  Map.add x (peek 0) acc\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_lambda_lowers_to_tuple_target',
        "files": {
            'main.pyfun': (
                'let steps = [("a", 1), ("b", 2), ("a", 3)]\n'
                'let m = List.fold (fun m (p, l) -> Map.add p l m) Map.empty steps'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_fold_destructuring_elem_matches_fst_snd_spelling',
        "files": {
            'main.pyfun': (
                'let steps = [("a", 1), ("b", 2), ("a", 3)]\n'
                'let slow = List.fold (fun m (p, l) -> Map.add p l m) Map.empty steps\n'
                'let fast = List.fold (fun m s -> Map.add (fst s) (snd s) m) Map.empty steps\n'
                'let out = (Map.toList slow, Map.toList fast, slow == fast)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_top_level_named_folder',
        "files": {
            'main.pyfun': (
                'let add m (p, l) = Map.add p l m\n'
                'let out = Map.toList (List.fold add Map.empty [(1, "x"), (2, "y")])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_block_local_named_folder',
        "files": {
            'main.pyfun': (
                'let build steps =\n'
                '  let add m (p, l) = Map.add p l m\n'
                '  List.fold add Map.empty steps\n'
                'let out = Map.toList (build [(1, "x"), (2, "y")])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_nested_tuple',
        "files": {
            'main.pyfun': (
                'let out = Map.toList (List.fold (fun m (a, (b, c)) -> Map.add a (b + c) m) Map.empty [("x", (1, 2)), ("y", (3, 4))])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_wildcard',
        "files": {
            'main.pyfun': (
                'let out = Set.toList (List.fold (fun s (p, _) -> Set.add p s) Set.empty [(1, "a"), (2, "b"), (1, "c")])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_destructuring_elem_tuple_accumulator',
        "files": {
            'main.pyfun': (
                'let step acc (k, v) =\n'
                '  match acc:\n'
                '    case (m, ks): (Map.add k v m, List.concat ks [k])\n'
                'let out = match List.fold step (Map.empty, []) [(1, "a"), (2, "b")]: case (m, ks): (Map.toList m, ks)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_destructured_elem_name_clashes_with_enclosing_lo',
        "files": {
            'main.pyfun': (
                'let clash p =\n'
                '  let inner = List.fold (fun m (p, l) -> Map.add p l m) Map.empty [(1, 2)]\n'
                '  (p, Map.toList inner)\n'
                'let out = clash 9'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fold_reject_destructuring_accumulator_param_still_falls_back',
        "files": {
            'main.pyfun': (
                'let out = match List.fold (fun (m, n) x -> (Map.add x n m, n + 1)) (Map.empty, 0) [5, 6]: case (m, n): (Map.toList m, n)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'matching_an_option_pulls_in_the_option_prelude',
        "files": {
            'main.pyfun': (
                'let probe o =\n'
                '  match o:\n'
                '    case None: "none"\n'
                '    case Some k: k'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'an_uncollided_extern_import_stays_plain',
        "files": {
            'main.pyfun': (
                'extern sq : float -> float = math.sqrt\n'
                'print (sq 4.0)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'an_aliased_or_dotted_extern_import_re_roots_around_a_collisi',
        "files": {
            'main.pyfun': (
                'extern import numpy as np\n'
                'extern zeros : int -> string = np.zeros\n'
                'let np = 1\n'
                'print (zeros 3)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'an_aliased_or_dotted_extern_import_re_roots_around_a_collisi_2',
        "files": {
            'main.pyfun': (
                'extern import os.path\n'
                'extern joinp : string -> string -> string = os.path.join\n'
                'let os = 1\n'
                'print (joinp "a" "b")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'destructuring_let_lowers_to_tuple_unpacking',
        "files": {
            'main.pyfun': (
                'let pair = (1, 2)\n'
                'let (a, b) = pair'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'destructuring_let_unpacks_straight_from_a_call',
        "files": {
            'main.pyfun': (
                'let mk x = (x, x + 1)\n'
                'let (a, b) = mk 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_wildcard_element_needs_no_name',
        "files": {
            'main.pyfun': (
                'let pair = (1, 2)\n'
                'let (a, _) = pair'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_nested_destructuring_unpacks_one_level_per_statement',
        "files": {
            'main.pyfun': (
                'let p = (1, (2, 3))\n'
                'let (a, (b, c)) = p'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_record_target_reads_the_fields_it_names',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = 2 }\n'
                'let Point { x, y } = p'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_destructuring_result_bind_rides_inside_the_ok_pattern',
        "files": {
            'main.pyfun': (
                'let f r = result {\n'
                '  let! (a, b) = r\n'
                '  return a + b\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_module_member_destructuring_mangles_every_name',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '    let (w, h) = (3, 4)\n'
                'let r = M.w + M.h'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_destructuring_let_binds_every_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let (a, b) = (1, 2)\n'
                '        let (c, (d, e)) = (3, (4, 5))\n'
                '        let Point { x, y } = Point { x = 6, y = 7 }\n'
                '        let total = a + b + c + d + e + x + y\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_let_inside_a_function_body',
        "files": {
            'main.pyfun': (
                '\n'
                '        let swapSum p =\n'
                '          let (a, b) = p\n'
                '          let (c, d) = (b, a)\n'
                '          c * 10 + d\n'
                '        let r = swapSum (1, 2)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_bind_in_a_result_block',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f r =\n'
                '          result {\n'
                '            let! (a, b) = r\n'
                '            let (c, d) = (b, a)\n'
                '            return c * 10 + d\n'
                '          }\n'
                '        let ok =\n'
                '          match f (Ok (1, 2)):\n'
                '            case Ok v: v\n'
                '            case Error _: 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_block_lowers_to_flat_isinstance_statements',
        "files": {
            'main.pyfun': (
                'let f o = option {\n'
                '  let! x = o\n'
                '  return (x + 1)\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_short_circuit_forwards_the_failure_value_itself',
        "files": {
            'main.pyfun': (
                'let f o = option {\n'
                '  let! x = o\n'
                '  return x\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_short_circuit_forwards_the_failure_value_itself_2',
        "files": {
            'main.pyfun': (
                'let g r = result {\n'
                '  let! x = r\n'
                '  return x\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_block_chains_binds_without_nesting_lambdas',
        "files": {
            'main.pyfun': (
                'let f xs = option {\n'
                '  let! a = List.get 0 xs\n'
                '  let! b = List.get 1 xs\n'
                '  return (a + b)\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_destructuring_bind_unpacks_from_the_some_payload',
        "files": {
            'main.pyfun': (
                'let f o = option {\n'
                '  let! (a, b) = o\n'
                '  return a + b\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_block_short_circuits_on_none',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f xs =\n'
                '          option {\n'
                '            let! a = List.get 0 xs\n'
                '            let! b = List.get 1 xs\n'
                '            return (a + b)\n'
                '          }\n'
                '        let hit =\n'
                '          match f [1, 2]:\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        let miss =\n'
                '          match f [1]:\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_block_return_bang_and_do_bang',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o p =\n'
                '          option {\n'
                '            do! p\n'
                '            let! x = o\n'
                '            return! (if x > 0 then Some (x * 2) else None)\n'
                '          }\n'
                '        let a =\n'
                '          match f (Some 3) (Some ()):\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        let b =\n'
                '          match f (Some 3) None:\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        let c =\n'
                '          match f (Some 0) (Some ()):\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_match_in_return_position_is_an_isinstance_ladder',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case None: 0\n'
                '    case Some x: x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_match_in_value_position_assigns_a_temp',
        "files": {
            'main.pyfun': (
                'let f o = 1 + (match o:\n'
                '  case Some x: x\n'
                '  case None: 0)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_non_name_option_scrutinee_is_bound_once',
        "files": {
            'main.pyfun': (
                'let w xs =\n'
                '  match List.findIndex ((==) 2) xs:\n'
                '    case Some i: i\n'
                '    case other: -1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'guarded_option_arms_fall_through_in_return_position',
        "files": {
            'main.pyfun': (
                'let g o =\n'
                '  match o:\n'
                '    case Some x if x > 10: "big"\n'
                '    case Some x: "small"\n'
                '    case None: "none"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_guarded_catch_all_falls_through_to_the_arms_after_it',
        "files": {
            'main.pyfun': (
                'let g o =\n'
                '  match o:\n'
                '    case Some x if x > 10: 1\n'
                '    case _ if false: 2\n'
                '    case None: 3\n'
                '    case Some _: 4'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_guarded_option_arm_in_value_position_keeps_the_match',
        "files": {
            'main.pyfun': (
                'let g o = 1 + (match o:\n'
                '  case Some x if x > 10: 1\n'
                '  case Some x: 2\n'
                '  case None: 3)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_payload_unpacks_from_the_some_payload',
        "files": {
            'main.pyfun': (
                'let h o =\n'
                '  match o:\n'
                '    case Some (a, b): a + b\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_refutable_payload_keeps_the_match',
        "files": {
            'main.pyfun': (
                'let z o =\n'
                '  match o:\n'
                '    case Some 0: true\n'
                '    case _: false'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'result_match_is_an_isinstance_ladder',
        "files": {
            'main.pyfun': (
                'let k r =\n'
                '  match r:\n'
                '    case Ok v: v\n'
                '    case Error e: -1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_user_adt_match_still_emits_match_case',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let delta d =\n'
                '  match d:\n'
                '    case Across: (0, 1)\n'
                '    case Down: (1, 0)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_nullary_constructor_value_loads_its_singleton',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let d = Across\n'
                'let ds = [Down, Down]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_nullary_singleton_falls_back_when_its_name_is_taken',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let _Across = 1\n'
                'let d = Across\n'
                'let e = Down'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'none_loads_the_prelude_singleton_unless_its_name_is_taken',
        "files": {
            'main.pyfun': (
                'let n = None\n'
                'let o = Map.tryFind 1 Map.empty'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'none_loads_the_prelude_singleton_unless_its_name_is_taken_2',
        "files": {
            'main.pyfun': (
                'let _None_ = 1\n'
                'let n = None\n'
                'let o = Map.tryFind 1 Map.empty'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'every_emitted_class_uses_slots',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Dot\n'
                'type P = { x: int }\n'
                'let r = Ok 1\n'
                'let o = Some 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_option_ladders_and_singletons_agree_with_the_match_seman',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Dir = Across | Down\n'
                '        let g o =\n'
                '          match o:\n'
                '            case Some x if x > 10: "big"\n'
                '            case Some x: "small"\n'
                '            case None: "none"\n'
                '        let h o =\n'
                '          match o:\n'
                '            case Some (a, b): a + b\n'
                '            case _: 0\n'
                '        let k r =\n'
                '          match r:\n'
                '            case Ok v: v\n'
                '            case Error e: -1\n'
                '        let v o = 1 + (match o:\n'
                '          case Some x: x\n'
                '          case None: 0)\n'
                '        let only o =\n'
                '          match o:\n'
                '            case Some x if x > 0: x\n'
                '            case _ if false: 1\n'
                '            case None: 2\n'
                '            case Some _: 3\n'
                '        let a = g (Some 11)\n'
                '        let b = g (Some 1)\n'
                '        let c = g None\n'
                '        let d = h (Some (1, 2))\n'
                '        let e = k (Ok 4)\n'
                '        let f = k (Error "x")\n'
                '        let i = v (Some 3)\n'
                '        let j = only (Some 5)\n'
                '        let l = only (Some (0 - 5))\n'
                '        let m = only None\n'
                '        let n = Across == Across\n'
                '        let p = Set.len (Set.ofList [Across, Down, Across])\n'
                '        let q = Map.findOr Down 0 (Map.ofList [(Down, 7)])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_slotted_records_update_compare_and_hash',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let p = Point { x = 1, y = 2 }\n'
                '        let q = { p with x = 3 }\n'
                '        let lt = p < q\n'
                '        let s = Set.len (Set.ofList [p, q, p])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'local_let_partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                '\n'
                '        let addAll xs ys =\n'
                '          let pair a b = a + b\n'
                '          List.map (pair 10) ys\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_local_let_partial_application_runs',
        "files": {
            'main.pyfun': (
                '\n'
                '        let addAll xs ys =\n'
                '          let pair a b = a + b\n'
                '          List.map (pair 10) ys\n'
                '        let r = addAll [] [1, 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'local_lambda_let_partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                '\n'
                '        let addAll ys =\n'
                '          let pair = fun a b -> a + b\n'
                '          List.map (pair 10) ys\n'
                '        let r = addAll [1, 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'local_let_over_application_applies_the_remainder',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let k a b = fun c -> a + b + c\n'
                '          k 1 2 x\n'
                '        let r = f 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'parameter_shadowing_a_local_function_stays_n_ary',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f ys =\n'
                '          let pair a b = a + b\n'
                '          let g pair = pair 10\n'
                '          g (fun x -> x + 1)\n'
                '        let r = f []\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'match_binder_shadowing_a_local_function_stays_n_ary',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let pair a b = a + b\n'
                '          let outer = pair 1\n'
                '          let inner =\n'
                '            match o:\n'
                '              case Some pair: pair 10\n'
                '              case None: 0\n'
                '          inner + outer 2\n'
                '        let r = f (Some (fun x -> x + 1))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'recursive_local_function_sees_its_own_arity',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f n =\n'
                '          let go acc k =\n'
                '            if k == 0 then [acc]\n'
                '            else List.collect (go (acc + 1)) [k - 1]\n'
                '          go 0 n\n'
                '        let r = f 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'non_function_rebinding_evicts_the_local_arity',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let pair a b = a + b\n'
                '          let pair = pair 1\n'
                '          pair x\n'
                '        let r = f 2\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_capture_colliding_with_a_block_local_function_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let pair a b = a + b\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some pair: pair\n'
                '              case None: 0\n'
                '          pair r 1\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_capture_colliding_with_a_top_level_function_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let pair a b = a + b\n'
                '        let f o =\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some pair: pair\n'
                '              case None: 0\n'
                '          pair r 1\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_capture_colliding_with_a_parameter_read_later_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x o =\n'
                '          match o:\n'
                '            case Some x: x\n'
                '            case None: x\n'
                '        let a = f 1 (Some 5)\n'
                '        let b = f 1 None\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sibling_arms_capturing_the_same_name_are_not_renamed',
        "files": {
            'main.pyfun': (
                'let f r =\n'
                '  match r:\n'
                '    case Ok x: x\n'
                '    case Error x: 0 - x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'an_unreferenced_outer_name_does_not_force_a_rename',
        "files": {
            'main.pyfun': (
                'let f x o =\n'
                '  match o:\n'
                '    case Some x: x\n'
                '    case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_nested_matches_capturing_the_same_name_get_distinct_fres',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x o p =\n'
                '          match o:\n'
                '            case Some x:\n'
                '              let inner =\n'
                '                match p:\n'
                '                  case Some x: x * 10\n'
                '                  case None: x\n'
                '              inner + x\n'
                '            case None: x\n'
                '        let r = f 1 (Some 2) (Some 3)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_made_before_the_match_reads_the_original_bindi',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let n = 100\n'
                '          let get u = n + u\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some n: n\n'
                '              case None: 0\n'
                '          r + get 0\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_or_and_record_pattern_captures_are_renamed_consistently',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x : int, y : int }\n'
                '        let f y p q =\n'
                '          let a =\n'
                '            match p:\n'
                '              case Point { x = 0, y }: y\n'
                '              case Point { x }: x + y\n'
                '          let b =\n'
                '            match q:\n'
                '              case (0, y) | (y, 0): y\n'
                '              case (_, _): y\n'
                '          a + b\n'
                '        let r = f 1000 (Point { x = 0, y = 2 }) (0, 3)\n'
                '        let s = f 1000 (Point { x = 4, y = 2 }) (7, 8)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_value_position_capture_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let total a b = a + b\n'
                '          1 + (match o:\n'
                '                 case Some total: total\n'
                '                 case None: 0) + total 1 1\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_lookup_peephole_capture_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f m k =\n'
                '          let v = 100\n'
                '          let found =\n'
                '            match Map.tryFind k m:\n'
                '              case Some v: v\n'
                '              case None: 0\n'
                '          found + v\n'
                '        let r = f (Map.ofList [(1, 5)]) 1\n'
                '        let s = f (Map.ofList [(1, 5)]) 2\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_active_pattern_capture_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let (|Positive|_|) n = if n > 0 then Some n else None\n'
                '        let f p n =\n'
                '          let label =\n'
                '            match n:\n'
                '              case Positive p: p * 2\n'
                '              case _: 0\n'
                '          label + p\n'
                '        let r = f 1000 5\n'
                '        let s = f 1000 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_fresh_capture_name_bumps_past_a_name_in_use',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let pair a b = a + b\n'
                '          let _pair = 7\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some pair: pair\n'
                '              case None: 0\n'
                '          pair r _pair\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_lambda_parameter_inside_the_arm_keeps_its_own_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x o =\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some x: List.map (fun x -> x + 1) x\n'
                '              case None: []\n'
                '          List.len r + x\n'
                '        let r = f 10 (Some [1, 2, 3])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_module_level_capture_colliding_with_a_global_read_is_r',
        "files": {
            'main.pyfun': (
                '\n'
                '        let m =\n'
                '          match Some 5:\n'
                '            case Some print: print\n'
                '            case None: 0\n'
                '        let show x = print x\n'
                '        let r = m\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_fold_loop_arm_capture_is_renamed_in_the_enclosing_frame',
        "files": {
            'main.pyfun': (
                '\n'
                '        let bump x = x + 100\n'
                '        let f xs =\n'
                '          let seen = List.fold (fun acc o ->\n'
                '            match o:\n'
                '              case Some bump: Map.add bump 1 acc\n'
                '              case None: acc) Map.empty xs\n'
                '          bump (Map.len seen)\n'
                '        let r = f [Some 1, None, Some 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_let_in_an_if_branch_does_not_rebind_the_outer_binding',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let x = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = 10\n'
                '              x + 1\n'
                '            else 0\n'
                '          x + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_let_in_a_match_arm_body_does_not_rebind_the_outer_bind',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let n = 1\n'
                '          let y =\n'
                '            match o:\n'
                '              case Some k:\n'
                '                let n = k * 10\n'
                '                n + 1\n'
                '              case None: 0\n'
                '          n + y\n'
                '        let r = f (Some 2)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_let_in_a_return_position_arm_block_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let n = 1\n'
                '          match o:\n'
                '            case Some k:\n'
                '              let n = n * 10 + k\n'
                '              n + 1\n'
                '            case None: n\n'
                '        let r = f (Some 2)\n'
                '        let s = f None\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_function_let_shadowing_an_outer_function_is_ren',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag n =\n'
                '          let go k = k * 100\n'
                '          let y =\n'
                '            if flag then\n'
                '              let go k = if k == 0 then 0 else k + go (k - 1)\n'
                '              go n\n'
                '            else 0\n'
                '          y + go 1\n'
                '        let r = f true 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_mut_with_assignment_keeps_the_outer_binding',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let total = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let mut total = 0\n'
                '              total <- total + 5\n'
                '              total <- total + 5\n'
                '              total\n'
                '            else 0\n'
                '          total + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_assigning_a_renamed_nested_mut_declares_the_fr',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let count = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let mut count = 0\n'
                '              let bump u = count <- count + u\n'
                '              bump 4\n'
                '              bump 5\n'
                '              count\n'
                '            else 0\n'
                '          count + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_shadowing_a_parameter_read_later_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x flag =\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = 10\n'
                '              x\n'
                '            else 0\n'
                '          x + y\n'
                '        let r = f 1 true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_root_level_let_rebinding_a_parameter_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let x = x + 1\n'
                '          let x = x * 2\n'
                '          x\n'
                '        let r = f 1\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_nested_let_with_no_occurrence_outside_its_block_is_not_ren',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let y =\n'
                '            if flag then\n'
                '              let t = 10\n'
                '              t + 1\n'
                '            else 0\n'
                '          y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_nested_let_renames_each_colliding_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let a = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let (a, b) = (10, 20)\n'
                '              a + b\n'
                '            else 0\n'
                '          a + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_fresh_name_bumps_past_a_name_in_use',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let x = 1\n'
                '          let _x = 100\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = 10\n'
                '              x + 1\n'
                '            else 0\n'
                '          x + y + _x\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_capture_reused_across_sequential_matches_keeps_its_nam',
        "files": {
            'main.pyfun': (
                '\n'
                '        let step a b =\n'
                '          let x =\n'
                '            match a:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          let y =\n'
                '            match b:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          x + y\n'
                '        let r = step (Ok 1) (Error "no")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_let_reused_across_sequential_branches_keeps_its_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f a b =\n'
                '          let x =\n'
                '            if a then\n'
                '              let t = 1\n'
                '              t + 1\n'
                '            else 0\n'
                '          let y =\n'
                '            if b then\n'
                '              let t = 10\n'
                '              t + 1\n'
                '            else 0\n'
                '          x + y\n'
                '        let r = f true true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_outer_binding_read_after_both_matches_renames_both_ca',
        "files": {
            'main.pyfun': (
                '\n'
                '        let step a b =\n'
                '          let why = "x"\n'
                '          let x =\n'
                '            match a:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          let y =\n'
                '            match b:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          String.len why + x + y\n'
                '        let r = step (Ok 1) (Error "no")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_nested_let_reading_the_parameter_it_shadows_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x flag =\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = x + 1\n'
                '              x * 2\n'
                '            else 0\n'
                '          y\n'
                '        let r = f 5 true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_three_sequential_error_arms_emit_the_plain_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let describe a b c =\n'
                '          let s1 =\n'
                '            match a:\n'
                '              case Ok n: n\n'
                '              case Error why: String.len why\n'
                '          let s2 =\n'
                '            match b:\n'
                '              case Ok n: n\n'
                '              case Error why: String.len why\n'
                '          let s3 =\n'
                '            match c:\n'
                '              case Ok n: n\n'
                '              case Error why: String.len why\n'
                '          s1 + s2 + s3\n'
                '        let r = describe (Error "a") (Ok 2) (Error "ccc")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_escaping_an_earlier_arm_forces_the_later_captu',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f a b =\n'
                '          let g =\n'
                '            match a:\n'
                '              case Error why: fun u -> why\n'
                '              case Ok n: fun u -> "ok"\n'
                '          let m =\n'
                '            match b:\n'
                '              case Error why: String.len why\n'
                '              case Ok n: n\n'
                '          String.len (g 0) + m\n'
                '        let r = f (Error "first") (Error "second")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_shadowing_an_enclosing_name_read_earlier_is_r',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let g o =\n'
                '            let y = x + 1\n'
                '            let x = 2\n'
                '            x + y + o\n'
                '          g 10\n'
                '        let r = f 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_shadowing_a_module_binding_read_earlier_is_re',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          let m = n + 1\n'
                '          let n = 2\n'
                '          m + n + u\n'
                '        let r = f 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_reading_the_module_binding_it_shadows_is_rena',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          let n = n + 1\n'
                '          n + u\n'
                '        let r = f 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_closure_made_before_a_root_let_reads_the_enclosing_bin',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let g o =\n'
                '            let peek u = x + u\n'
                '            let before = peek 0\n'
                '            let x = 100\n'
                '            before + x + o\n'
                '          g 1\n'
                '        let r = f 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_root_let_rebinding_a_parameter_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let x = x + 1\n'
                '          x * 2\n'
                '        let r = f 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_root_let_referenced_only_after_it_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          let n = 2\n'
                '          n + u\n'
                '        let g u =\n'
                '          let k = 1\n'
                '          k + u\n'
                '        let r = f 10 + g 1\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_top_level_let_is_never_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let m = n + 1\n'
                '        let n = 7\n'
                '        let r = n + m\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_root_let_mut_shadowing_an_enclosing_name_declares_the',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let g o =\n'
                '            let before = x\n'
                '            let mut x = 0\n'
                '            let bump u = x <- x + u\n'
                '            bump 5\n'
                '            bump 6\n'
                '            before + x + o\n'
                '          g 1\n'
                '        let r = f 100\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_root_let_renames_only_the_colliding_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f a =\n'
                '          let g o =\n'
                '            let before = a\n'
                '            let (a, b) = (10, 20)\n'
                '            before + a + b + o\n'
                '          g 1\n'
                '        let r = f 100\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_ce_bind_shadowing_a_module_binding_read_earlier_is_ren',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          option {\n'
                '            let m = n + 1\n'
                '            let! n = Some 2\n'
                '            return n + m\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_result_bind_shadowing_an_outer_name_keeps_its_failure',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          result {\n'
                '            let m = n + 1\n'
                '            let! n = if u > 0 then Ok 2 else Error "no"\n'
                '            return n + m\n'
                '          }\n'
                '        let a = f 1\n'
                '        let b = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_an_async_bind_shadowing_an_outer_name_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          async {\n'
                '            let m = n + 1\n'
                '            let! n = async { return 2 }\n'
                '            return n + m\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_seq_let_shadowing_an_outer_name_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          seq {\n'
                '            let m = n + 1\n'
                '            let n = 2\n'
                '            yield n + m\n'
                '          }\n'
                '        let r = f 0 |> Seq.toList\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_ce_bind_read_only_after_it_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          option {\n'
                '            let! n = Some 2\n'
                '            let k = 1\n'
                '            return n + k\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_ce_bind_rebinding_an_earlier_ce_binder_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f u =\n'
                '          option {\n'
                '            let n = 1\n'
                '            let! n = Some (n + 1)\n'
                '            return n\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'e2e_a_destructuring_ce_bind_renames_only_the_colliding_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          option {\n'
                '            let m = n + 1\n'
                '            let! (n, k) = Some (2, 3)\n'
                '            return n + k + m\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_module_types_a_record_decoder',
        "files": {
            'main.pyfun': (
                'type P = { name: string, age: int, tags: List string }\n'
                'let d =\n'
                '  Decode.map3 (fun name age tags -> P { name = name, age = age, tags = tags })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "age" Decode.int)\n'
                '    (Decode.field "tags" (Decode.list Decode.string))\n'
                'let r = Decode.decodeString d "{}"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_map4_does_not_corrupt_let_polymorphism',
        "files": {
            'main.pyfun': (
                'let id x = x\n'
                'let n = id 1\n'
                'let s = id "hi"\n'
                'let d = Decode.map4 (fun a b c e -> a) Decode.int Decode.int Decode.int Decode.int'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unit_literal',
        "files": {
            'main.pyfun': 'let force f = f ()',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'let_generalization_makes_bindings_polymorphic',
        "files": {
            'main.pyfun': (
                'let id x = x\n'
                'let a = id 1\n'
                'let b = id true'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_higher_order_composition',
        "files": {
            'main.pyfun': (
                'let compose = fun f g x -> f (g x)\n'
                'let twice f x = f (f x)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'function_binding_is_in_scope_in_its_own_body',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)\n'
                'let r = fact 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'recursion_does_not_break_let_generalization',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)\n'
                'let id x = x\n'
                'let a = id 1\n'
                'let b = id true\n'
                'let c = fact 4'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_mutual_recursion',
        "files": {
            'main.pyfun': (
                'let isEven n = if n == 0 then true else isOdd (n - 1)\n'
                'let isOdd n = if n == 0 then false else isEven (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_mutual_recursion_2',
        "files": {
            'main.pyfun': (
                'let a n = if n == 0 then 0 else b (n - 1)\n'
                'let b n = if n == 0 then 1 else c (n - 1)\n'
                'let c n = if n == 0 then 2 else a (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'mutual_recursion_preserves_polymorphism',
        "files": {
            'main.pyfun': (
                'let id x = x\n'
                'let ping n = if n == 0 then id 0 else pong (n - 1)\n'
                'let pong n = if n == 0 then id 1 else ping (n - 1)\n'
                'let flag = id true'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_partial_application_and_pipe',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let inc = add 1\n'
                'let r = 5 |> inc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_partial_application_and_pipe_2',
        "files": {
            'main.pyfun': (
                'let inc n = n + 1\n'
                'let r = inc <| inc <| 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_operator_sections',
        "files": {
            'main.pyfun': 'let r = (*) 3 4',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_operator_sections_2',
        "files": {
            'main.pyfun': (
                'let double = (*) 2\n'
                'let r = double 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_operator_sections_3',
        "files": {
            'main.pyfun': 'let r = List.fold (+) 0 [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_operator_sections_4',
        "files": {
            'main.pyfun': 'let r = (<) 1 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_operator_sections_5',
        "files": {
            'main.pyfun': 'let r = (==) 1 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_operator_sections_6',
        "files": {
            'main.pyfun': 'let r = (//) 7 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_function_composition',
        "files": {
            'main.pyfun': (
                'let inc x = x + 1\n'
                'let f = inc >> inc\n'
                'let r = f 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_function_composition_2',
        "files": {
            'main.pyfun': (
                'let f = String.strip >> String.len\n'
                'let n = f "  hi "'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_function_composition_3',
        "files": {
            'main.pyfun': (
                'let d x = x * 2\n'
                'let i x = x + 1\n'
                'let r = List.map (d >> i) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_as_patterns',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some v as w: v\n'
                '    case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_as_patterns_2',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: 0\n'
                '    case _ as x: x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'as_patterns_are_transparent_for_exhaustiveness',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let f s =\n'
                '  match s:\n'
                '    case Circle r as w: r\n'
                '    case Rect a b as w: a'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_discard_binding',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '  let _ = x + 1\n'
                '  x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_string_slice_and_index_of',
        "files": {
            'main.pyfun': 'let r = String.slice 0 3 "hello"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_string_slice_and_index_of_2',
        "files": {
            'main.pyfun': 'let r = String.tryIndexOf "l" "hello"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_string_slice_and_index_of_3',
        "files": {
            'main.pyfun': 'let r = Option.withDefault 0 (String.tryIndexOf "l" "hi")',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_exponentiation',
        "files": {
            'main.pyfun': 'let r = 2.0 ** 8.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_exponentiation_2',
        "files": {
            'main.pyfun': 'let r = 2 ** 10',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_exponentiation_3',
        "files": {
            'main.pyfun': 'let r = 2.0 ** -1.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_exponentiation_4',
        "files": {
            'main.pyfun': 'let r = 2.0 ** 3.0 ** 2.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_option_bind_filter_to_result',
        "files": {
            'main.pyfun': 'let r = Option.bind (fun x -> Some (x + 1)) (Some 1)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_option_bind_filter_to_result_2',
        "files": {
            'main.pyfun': 'let r = Option.filter (fun x -> x > 0) (Some 3)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_option_bind_filter_to_result_3',
        "files": {
            'main.pyfun': 'let r = Option.toResult "none" (Some 42)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_option_bind_filter_to_result_4',
        "files": {
            'main.pyfun': (
                'let r = Option.bind (fun x -> Some (x > 0)) (Option.bind (fun x -> Some (x + 1)) (Some 1))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_numeric_conversions',
        "files": {
            'main.pyfun': 'let r = round 3.7',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_numeric_conversions_2',
        "files": {
            'main.pyfun': (
                'let r = floor 3.2\n'
                'let s = ceil 3.2\n'
                'let t = truncate 3.9'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_numeric_conversions_3',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let r = round 2.5<m>\n'
                'let ok = r + 1<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_numeric_conversions_4',
        "files": {
            'main.pyfun': 'let r = floor 3.7 + 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_numeric_conversions_5',
        "files": {
            'main.pyfun': 'let r = Option.withDefault 0.0 (String.toFloat "3.14")',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sqrt_halves_a_square_unit',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = sqrt 16.0<m^2>\n'
                'let ok = side + 1.0<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sqrt_halves_even_mixed_exponents',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let r = sqrt 2.0<m^4/s^2>\n'
                'let ok = r + 1.0<m^2/s>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sqrt_of_dimensionless_float_is_dimensionless',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let pure norm x = sqrt (x * x)\n'
                'let ok = norm 3.0<m> + 1.0<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sqrt_of_dimensionless_float_is_dimensionless_2',
        "files": {
            'main.pyfun': 'let r = sqrt 4',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_user_definition_still_shadows_the_sqrt_builtin',
        "files": {
            'main.pyfun': (
                'let sqrt s = s\n'
                'let r = sqrt "not a number"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'cbrt_thirds_a_cube_unit',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = cbrt 27.0<m^3>\n'
                'let ok = side + 1.0<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'cbrt_thirds_a_cube_unit_2',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let r = cbrt 8.0<m^6/s^3>\n'
                'let ok = r + 1.0<m^2/s>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'cbrt_of_dimensionless_float_is_dimensionless',
        "files": {
            'main.pyfun': (
                'let pure c x = cbrt x\n'
                'let r = c 27.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'cbrt_of_dimensionless_float_is_dimensionless_2',
        "files": {
            'main.pyfun': 'let r = cbrt 8',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_user_definition_still_shadows_the_cbrt_builtin',
        "files": {
            'main.pyfun': (
                'let cbrt s = s\n'
                'let r = cbrt "nope"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_scientific_notation',
        "files": {
            'main.pyfun': 'let x = 1e6',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_scientific_notation_2',
        "files": {
            'main.pyfun': 'let x = 2.5e-3',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_scientific_notation_3',
        "files": {
            'main.pyfun': 'let x = 1e6 + 2.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_scientific_notation_4',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let x = 3.0e8<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops',
        "files": {
            'main.pyfun': 'let r = List.get 0 [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_2',
        "files": {
            'main.pyfun': 'let r = List.isEmpty [1]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_3',
        "files": {
            'main.pyfun': 'let r = List.contains 2 [1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_4',
        "files": {
            'main.pyfun': 'let r = List.concat [1] [2, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_5',
        "files": {
            'main.pyfun': 'let r = List.sort [3, 1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_6',
        "files": {
            'main.pyfun': 'let r = List.sort ["b", "a"]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_7',
        "files": {
            'main.pyfun': 'let r = List.find (fun x -> x > 1) [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_completeness_ops_8',
        "files": {
            'main.pyfun': 'let r = Option.withDefault 0 (List.get 0 [1, 2])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_choose_and_collect',
        "files": {
            'main.pyfun': (
                'let r = List.choose (fun x -> if x > 1 then Some (x * 10) else None) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_choose_and_collect_2',
        "files": {
            'main.pyfun': (
                'let r = List.choose (fun x -> Some (String.fromInt x)) [1, 2]\n'
                'let n = List.map String.len r'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_choose_and_collect_3',
        "files": {
            'main.pyfun': 'let r = List.collect (fun x -> [x, x]) [1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_choose_and_collect_4',
        "files": {
            'main.pyfun': (
                'let r = List.collect (fun x -> x) [[1], [2, 3]]\n'
                'let n = List.sum r'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'choose_and_collect_are_effect_polymorphic',
        "files": {
            'main.pyfun': 'let pure dup xs = List.collect (fun x -> [x, x]) xs',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_modulo',
        "files": {
            'main.pyfun': 'let r = 10 % 3',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_modulo_2',
        "files": {
            'main.pyfun': 'let isEven n = n % 2 == 0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_modulo_3',
        "files": {
            'main.pyfun': 'let r = 5.5 % 2.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_modulo_4',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let r = 10<m> % 3<m>\n'
                'let ok = r + 1<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_chained_comparisons',
        "files": {
            'main.pyfun': 'let f x = 1 < x < 10',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_chained_comparisons_2',
        "files": {
            'main.pyfun': 'let g a b c = a <= b < c',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_chained_comparisons_3',
        "files": {
            'main.pyfun': 'let h = 1 == 1 == 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_chained_comparisons_4',
        "files": {
            'main.pyfun': 'let s = "a" < "b" < "c"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unary_minus',
        "files": {
            'main.pyfun': 'let a = -5',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unary_minus_2',
        "files": {
            'main.pyfun': (
                'let a = -3 + 10\n'
                'let b = 2 * -3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unary_minus_3',
        "files": {
            'main.pyfun': 'let a = abs (-5)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unary_minus_4',
        "files": {
            'main.pyfun': (
                'let neg x = -x\n'
                'let a = neg 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unary_minus_5',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let d = -5<m>\n'
                'let e = d + 3<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unary_minus_6',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case -1: 0\n'
                '    case _: 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_match_over_int_literals',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case _: "many"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_user_defined_adt',
        "files": {
            'main.pyfun': (
                'let unwrap o =\n'
                '  match o:\n'
                '    case Some v: v\n'
                '    case None: 0\n'
                'let r = unwrap (Some 5)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_parameterized_and_recursive_adts',
        "files": {
            'main.pyfun': (
                'type Either a b = Left a | Right b\n'
                'type Lst a = Nil | Cons a (Lst a)\n'
                'let xs = Cons 1 (Cons 2 Nil)\n'
                'let e = Left 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_opaque_type_wrap_and_unwrap',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let uid = UserId "u-1"\n'
                'let name u =\n'
                '  match u:\n'
                '    case UserId s: s\n'
                'let n = name uid'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_parameterized_opaque_type',
        "files": {
            'main.pyfun': (
                'opaque type Tag a = List a\n'
                'let t = Tag [1, 2]\n'
                'let unwrapTag tg =\n'
                '  match tg:\n'
                '    case Tag xs: xs\n'
                'let xs = unwrapTag t'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_wrapping_through_a_pipe',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let uid = "u" |> UserId'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'newtype_constructor_is_first_class',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let firstLen ids =\n'
                '  match ids:\n'
                '    case [UserId s, *_]: String.len s\n'
                '    case []: 0\n'
                'let n = firstLen (List.map UserId ["ab", "c"])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_deep_exhaustive_nested_adt',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some true: 1\n'
                '    case Some false: 2\n'
                '    case None: 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_deep_exhaustive_record_with_nested_ctors',
        "files": {
            'main.pyfun': (
                'type Box = { item: Option int }\n'
                'let f b =\n'
                '  match b:\n'
                '    case Box { item = Some n }: n\n'
                '    case Box { item = None }: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_empty_and_cons_as_exhaustive_list_match',
        "files": {
            'main.pyfun': (
                'let sum xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x, *rest]: x + sum rest'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_fixed_length_and_prefix_list_patterns',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x]: x\n'
                '    case [x, y]: x + y\n'
                '    case [a, b, *rest]: a + b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_lone_star_list_pattern_is_a_catch_all',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [*all]: all'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_pattern_rest_binds_a_list',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [x, *rest]: x + List.sum rest\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_nested_element_patterns_in_a_list',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [Some x, *rest]: x\n'
                '    case [None, *rest]: 0\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_empty_and_suffix_star_as_exhaustive_list_match',
        "files": {
            'main.pyfun': (
                'let last xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [*init, last]: last'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_deep_exhaustive_suffix_element_patterns',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [*_, None]: 1\n'
                '    case [*_, Some x]: x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'suffix_star_binders_get_list_and_element_types',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [*init, last]: last + List.sum init\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_nested_patterns_around_a_mid_star',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [Some x, *rest, None]: x\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_result_computation_expression',
        "files": {
            'main.pyfun': (
                'let f ok v = result { let! x = if ok then Ok v else Error 0  return (x + 1) }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_seq_computation_expression',
        "files": {
            'main.pyfun': 'let xs = seq { yield 1  yield 2 }',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_seq_computation_expression_2',
        "files": {
            'main.pyfun': 'let xs = seq { yield 1  yield! (seq { yield 2 }) }',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_async_computation_expression',
        "files": {
            'main.pyfun': 'let f = async { let! x = async { return 1 }  return (x + 1) }',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'for_items_type_in_every_builder',
        "files": {
            'main.pyfun': (
                'let squares = seq {\n'
                '  for x in [1, 2, 3]:\n'
                '    let y = x * x\n'
                '    yield y\n'
                '  yield 100\n'
                '}\n'
                'let pairs = seq { for (a, b) in [(1, 2)]: yield a + b }\n'
                'let lazy = seq { for x in Seq.ofList [1]: yield x }\n'
                'let check x = if x > 0 then Ok x else Error "neg"\n'
                'let all xs = result {\n'
                '  for x in xs:\n'
                '    let! _ = check x\n'
                '  return true\n'
                '}\n'
                'let main = async {\n'
                '  for n in [1, 2]:\n'
                '    do! Async.sleep 0.001\n'
                '  return ()\n'
                '}\n'
                'module B =\n'
                '  let yield_ x = [x]\n'
                '  let for_ xs f = List.collect f xs\n'
                '  let combine a b = List.concat a b\n'
                '  let delay f = f ()\n'
                'let built = B { for x in [1, 2]: yield x }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'for_items_type_in_every_builder_2',
        "files": {
            'main.pyfun': 'let s = seq { for (a, b) in [(1, "x")]: yield b }',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'rejects_seq_with_return',
        "files": {
            'main.pyfun': (
                'module Maybe =\n'
                '  let bind m f =\n'
                '    match m:\n'
                '      case Some x: f x\n'
                '      case None: None\n'
                '  let return_ x = Some x\n'
                '  let returnFrom m = m\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unit_polymorphic_function',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let area w h = w * h\n'
                'let rect = area 2<m> 3<m>\n'
                'let flow = area 2<m> 3<s>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_derived_measure_alias',
        "files": {
            'main.pyfun': (
                'measure kg\n'
                'measure m\n'
                'measure s\n'
                'measure N = kg m / s^2\n'
                'let force = 10<N>\n'
                'let area = 2<m^2>\n'
                'let pressure = force // area'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'alias_unifies_with_its_expansion',
        "files": {
            'main.pyfun': (
                'measure kg\n'
                'measure m\n'
                'measure s\n'
                'measure N = kg m / s^2\n'
                'let a = 1<N>\n'
                'let b = 1<kg m / s^2>\n'
                'let same = a == b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'alias_can_reference_another_alias',
        "files": {
            'main.pyfun': (
                'measure kg\n'
                'measure m\n'
                'measure s\n'
                'measure N = kg m / s^2\n'
                'measure Pa = N / m^2\n'
                'let p = 5<Pa>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'numeric_literals_adapt_to_int_or_float',
        "files": {
            'main.pyfun': 'let r = 1 + 2.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'numeric_literals_adapt_to_int_or_float_2',
        "files": {
            'main.pyfun': 'let r = (7 / 2) + 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'numeric_literals_adapt_to_int_or_float_3',
        "files": {
            'main.pyfun': 'let r = (7 // 2) + 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'arithmetic_is_numeric_polymorphic',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let i = add 1 2\n'
                'let f = add 1.5 2.5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'arithmetic_is_numeric_polymorphic_2',
        "files": {
            'main.pyfun': (
                'let a = max 1 2\n'
                'let b = min 1.5 2.5\n'
                'let c = abs 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'dimensionless_units_unify_with_plain_ints',
        "files": {
            'main.pyfun': 'let x = 5<1> + 3',
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_unit_polymorphic_numeric_builtins',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let big = max 3<m> 5<m>\n'
                'let small = min 1 2\n'
                'let d = abs (10<m> - 4<m>)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'user_definition_shadows_a_prelude_name',
        "files": {
            'main.pyfun': (
                'let min a b = a\n'
                'let r = min true false'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_comparison_and_equality',
        "files": {
            'main.pyfun': (
                'let a = 1 < 2\n'
                'let b = 2.5 >= 1.0\n'
                'let c = "x" < "y"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_comparison_and_equality_2',
        "files": {
            'main.pyfun': (
                'let a = 1 == 1\n'
                'let b = true != false\n'
                'let c = "x" == "y"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'comparison_and_equality_produce_bool',
        "files": {
            'main.pyfun': 'let pick a b = if a < b then a else b',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'generic_comparison_function_is_constrained',
        "files": {
            'main.pyfun': (
                'let lt a b = a < b\n'
                'let x = lt 1 2\n'
                'let y = lt 1.5 2.5\n'
                'let z = lt "a" "b"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_structural_equality_of_adts',
        "files": {
            'main.pyfun': 'let r = Some 1 == Some 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unit_annotation_and_less_than_are_distinguished',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let d = 5<m>\n'
                'let ok = d < 9<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'unit_annotation_and_less_than_are_distinguished_2',
        "files": {
            'main.pyfun': 'let r = 5 < 9',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_a_sum_type',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let r = Red < Blue'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_a_sum_type_2',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let r = Circle 1.0 < Rect 0.0 0.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_a_sum_type_3',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let s = List.sort [Blue, Red]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_a_record',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let r = Point { x = 1, y = 2 } < Point { x = 1, y = 3 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_tuples',
        "files": {
            'main.pyfun': 'let r = (1, 2) < (1, 3)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_tuples_2',
        "files": {
            'main.pyfun': 'let r = (1, "a") < (1, "b")',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_lists',
        "files": {
            'main.pyfun': 'let r = [1, 2] < [1, 3]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_lists_2',
        "files": {
            'main.pyfun': 'let r = ["a"] < ["b", "c"]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_lists_3',
        "files": {
            'main.pyfun': 'let r = [[1], [2]] < [[1], [3]]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_lists_4',
        "files": {
            'main.pyfun': 'let s = List.sort [[2], [1]]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_lists_5',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let r = [Red, Green] < [Red, Blue]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_a_recursive_type',
        "files": {
            'main.pyfun': (
                'type Tree = Leaf int | Node Tree Tree\n'
                'let s = List.sort [Node (Leaf 1) (Leaf 2), Leaf 0]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_a_parameterized_type_at_an_orderable_arg',
        "files": {
            'main.pyfun': (
                'type Box a = { item: a }\n'
                'let r = Box { item = 1 } < Box { item = 2 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_builtin_option_and_result',
        "files": {
            'main.pyfun': 'let r = None < Some 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_builtin_option_and_result_2',
        "files": {
            'main.pyfun': 'let r = Some 1 < Some 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_builtin_option_and_result_3',
        "files": {
            'main.pyfun': 'let r = Ok 1 < Error 0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_ordering_of_builtin_option_and_result_4',
        "files": {
            'main.pyfun': 'let r = Some (Ok 1) < Some (Ok 2)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'deferred_ordering_constraint_flows_to_a_concrete_adt',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green\n'
                'let lt a b = a < b\n'
                'let r = lt Red Green'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_boolean_operators',
        "files": {
            'main.pyfun': (
                'let a = true and false\n'
                'let b = true or false\n'
                'let c = not true'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_boolean_operators_2',
        "files": {
            'main.pyfun': 'let between lo hi x = lo <= x and x <= hi',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_record_decl_literal_update_and_access',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 3, y = 4 }\n'
                'let q = { p with y = 9 }\n'
                'let s = p.x + q.y'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_record_decl_literal_update_and_access_2',
        "files": {
            'main.pyfun': (
                'type Inner = { a: int, b: int }\n'
                'type Outer = { inner: Inner, tag: string }\n'
                'let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }\n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_field_access_drives_function_type',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let sumxy r = r.x + r.y\n'
                'let t = sumxy (Point { x = 1, y = 2 })'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'parameterized_record_is_polymorphic',
        "files": {
            'main.pyfun': (
                'type Box a = { item: a }\n'
                'let mk v = Box { item = v }\n'
                'let bi = (mk 5).item\n'
                'let bs = (mk "hi").item'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'two_records_may_share_a_field_name',
        "files": {
            'main.pyfun': (
                'type A = { x: int }\n'
                'type B = { x: int }\n'
                'let a = A { x = 1 }\n'
                'let b = B { x = 2 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_shared_field_resolves_when_the_base_type_is_known',
        "files": {
            'main.pyfun': (
                'type Placed = { letter: string, row: int }\n'
                'type Cell = { letter: string, blank: bool }\n'
                'type Board = { top: Cell }\n'
                'let p = Placed { letter = "a", row = 1 }\n'
                'let c = Cell { letter = "b", blank = false }\n'
                'let b = Board { top = c }\n'
                'let pl = p.letter\n'
                'let cl = c.letter\n'
                'let nested = b.top.letter\n'
                'let moved = { p with letter = "z" }\n'
                'let viaMatch =\n'
                '  match c:\n'
                '    case Cell { letter }: letter'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_distinct_field_still_resolves_when_another_is_shared',
        "files": {
            'main.pyfun': (
                'type A = { x: int, y: int }\n'
                'type B = { x: int }\n'
                'let gy p = p.y'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'set_traversals_keep_the_set_type',
        "files": {
            'main.pyfun': (
                'let s = Set.ofList [1, 2, 3]\n'
                'let e = Set.isEmpty s\n'
                'let m = Set.map (fun x -> x * 2) s\n'
                'let f = Set.filter (fun x -> x > 1) s\n'
                'let t = Set.fold (fun acc x -> acc + x) 0 s\n'
                'let p = Set.partition (fun x -> x > 1) s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'set_map_may_change_the_element_type',
        "files": {
            'main.pyfun': 'let s = Set.map (fun x -> String.fromInt x) (Set.ofList [1, 2])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'set_subset_checks_take_two_sets',
        "files": {
            'main.pyfun': (
                'let a = Set.isSubset (Set.ofList [1]) (Set.ofList [1, 2])\n'
                'let b = Set.isSuperset (Set.ofList [1, 2]) (Set.ofList [1])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_traversals_take_the_key_and_the_value',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "a")]\n'
                'let e = Map.isEmpty m\n'
                'let mapped = Map.map (fun k v -> String.concat v "!") m\n'
                'let kept = Map.filter (fun k v -> k > 0) m\n'
                'let total = Map.fold (fun acc k v -> acc + k) 0 m\n'
                'let any = Map.exists (fun k v -> k > 0) m\n'
                'let all = Map.forall (fun k v -> k > 0) m\n'
                'let split = Map.partition (fun k v -> k > 0) m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_map_keeps_the_keys_and_may_change_the_values',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "a")]\n'
                'let lengths = Map.map (fun k v -> String.len v) m\n'
                'let n = Map.findOr 1 0 lengths'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_union_needs_two_maps_of_one_type',
        "files": {
            'main.pyfun': 'let u = Map.union (Map.ofList [(1, "a")]) (Map.ofList [(2, "b")])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_members_stay_monomorphic_over_string',
        "files": {
            'main.pyfun': (
                'let e = String.isEmpty ""\n'
                'let r = String.repeat 2 "ab"\n'
                'let a = String.trimStart " x"\n'
                'let b = String.trimEnd "x "\n'
                'let l = String.splitLines "a"\n'
                'let v = String.rev "abc"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_get_answers_with_option_like_list_get',
        "files": {
            'main.pyfun': (
                'let c = String.get 0 "abc"\n'
                'let s = Option.withDefault "" c'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_of_list_inverts_to_list',
        "files": {
            'main.pyfun': 'let s = String.ofList (String.toList "abc")',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_shared_field_resolves_from_a_later_statement',
        "files": {
            'main.pyfun': (
                'type Placed = { row: int, letter: string }\n'
                'type Cell = { row: int, letter: string, blank: bool }\n'
                'let describe c =\n'
                '    let l = c.letter\n'
                '    let flag = c.blank\n'
                '    l'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_pinned_container_resolves_its_payload',
        "files": {
            'main.pyfun': (
                'type Placed = { row: int, letter: string }\n'
                'type Cell = { row: int, letter: string, blank: bool }\n'
                'let board = Map.ofList [(1, Placed { row = 1, letter = "A" })]\n'
                'let at k =\n'
                '  match Map.tryFind k board:\n'
                '    case Some p: p.letter\n'
                '    case None: ""'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_gains_the_members_seq_already_had',
        "files": {
            'main.pyfun': (
                'let xs = [1, 2, 3]\n'
                'let a = List.takeWhile (fun x -> x < 3) xs\n'
                'let b = List.dropWhile (fun x -> x < 3) xs\n'
                'let c = List.sortByDescending (fun x -> x) xs\n'
                'let d = List.countBy (fun x -> x % 2) xs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_gains_the_members_list_already_had',
        "files": {
            'main.pyfun': (
                'let s = Seq.ofList [1, 2, 3]\n'
                'let e = Seq.toList Seq.empty\n'
                'let d = Seq.toList (Seq.distinctBy (fun x -> x % 2) s)\n'
                'let r = Seq.toList (Seq.replicate 2 "a")\n'
                'let g = Seq.get 1 s\n'
                'let l = Seq.last s\n'
                'let t = Seq.sumBy (fun x -> x * 2) s\n'
                'let m = Seq.max s\n'
                'let n = Seq.min s\n'
                'let f = Seq.reduce (fun a b -> a + b) s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'every_module_can_iterate_for_effect',
        "files": {
            'main.pyfun': (
                'let a = Set.iter (fun x -> print x) (Set.ofList [1])\n'
                'let b = Map.iter (fun k v -> print v) (Map.ofList [(1, 2)])'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_and_result_agree_on_the_empty_case',
        "files": {
            'main.pyfun': (
                'let a = Option.forall (fun x -> x > 0) (Some 1)\n'
                'let b = Option.contains 1 (Some 1)\n'
                'let c = Result.exists (fun x -> x > 0) (Ok 1)\n'
                'let d = Result.forall (fun x -> x > 0) (Ok 1)\n'
                'let e = Result.contains 1 (Ok 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sign_is_a_number_to_an_int',
        "files": {
            'main.pyfun': (
                'let s = sign (-5)\n'
                'let t = s + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'sign_is_a_number_to_an_int_2',
        "files": {
            'main.pyfun': 'let s = sign 2.5',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_map2_combines_two_options',
        "files": {
            'main.pyfun': 'let s = Option.map2 (fun a b -> a + b) (Some 1) (Some 2)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_or_else_takes_the_fallback_first',
        "files": {
            'main.pyfun': 'let s = Some 1 |> Option.orElse (Some 2)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_flatten_collapses_one_level',
        "files": {
            'main.pyfun': (
                'let s = Option.flatten (Some (Some 1))\n'
                'let n = Option.withDefault 0 s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_bridges_to_list_and_bool',
        "files": {
            'main.pyfun': (
                'let xs = Option.toList (Some 1)\n'
                'let n = List.len xs\n'
                'let b = Option.exists (fun x -> x > 0) (Some 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'result_bridges_to_list_and_or_else',
        "files": {
            'main.pyfun': (
                'let xs = Result.toList (Ok 1)\n'
                'let r = Ok 1 |> Result.orElse (Ok 2)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_and_result_iter_carry_their_effect',
        "files": {
            'main.pyfun': 'let go = Option.iter (fun x -> print x) (Some 1)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_lazy_members_answer_a_seq',
        "files": {
            'main.pyfun': (
                'let s = Seq.ofList [1, 2, 3]\n'
                'let a = Seq.toList (Seq.drop 1 s)\n'
                'let b = Seq.toList (Seq.takeWhile (fun x -> x < 3) s)\n'
                'let c = Seq.toList (Seq.dropWhile (fun x -> x < 3) s)\n'
                'let d = Seq.toList (Seq.distinct s)\n'
                'let e = Seq.toList (Seq.pairwise s)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_zip_and_indexed_pair_up',
        "files": {
            'main.pyfun': (
                'let z = Seq.toList (Seq.zip (Seq.ofList [1]) (Seq.ofList ["a"]))\n'
                'let i = Seq.toList (Seq.indexed (Seq.ofList ["a"]))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_concat_appends_and_flatten_flattens',
        "files": {
            'main.pyfun': (
                'let a = Seq.toList (Seq.concat (Seq.ofList [1]) (Seq.ofList [2]))\n'
                'let b = Seq.toList (Seq.flatten (Seq.ofList [Seq.ofList [1]]))\n'
                'let c = Seq.toList (Seq.collect (fun x -> Seq.ofList [x]) (Seq.ofList [1]))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_can_be_endless',
        "files": {
            'main.pyfun': 'let s = Seq.toList (Seq.take 3 (Seq.initInfinite (fun i -> i * 2)))',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_can_be_endless_2',
        "files": {
            'main.pyfun': (
                'let s = Seq.toList (Seq.take 3 (Seq.unfold (fun n -> Some (n, n + 1)) 0))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_consuming_members_answer_plain_values',
        "files": {
            'main.pyfun': (
                'let s = Seq.ofList [1, 2, 3]\n'
                'let n = Seq.len s\n'
                'let e = Seq.isEmpty s\n'
                'let x = Seq.exists (fun v -> v > 1) s\n'
                'let a = Seq.forall (fun v -> v > 0) s\n'
                'let c = Seq.contains 2 s\n'
                'let t = Seq.sum s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'seq_iter_carries_the_effect_of_its_function',
        "files": {
            'main.pyfun': 'let go = Seq.iter (fun x -> print x) (Seq.ofList [1])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_accessors_answer_with_option',
        "files": {
            'main.pyfun': (
                'let h = List.head [1, 2]\n'
                'let n = Option.withDefault 0 h'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_accessors_answer_with_option_2',
        "files": {
            'main.pyfun': (
                'let t = List.tail [1, 2]\n'
                'let n = Option.withDefault [] t'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_slicing_is_total',
        "files": {
            'main.pyfun': (
                'let a = List.take 2 [1, 2, 3]\n'
                '             let b = List.drop 2 [1, 2, 3]\n'
                '             let c = List.splitAt 2 [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_map2_pairs_two_lists',
        "files": {
            'main.pyfun': 'let z = List.map2 (fun a b -> a + b) [1, 2] [3, 4]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_ordering_members_need_comparison',
        "files": {
            'main.pyfun': (
                'let m = List.max [3, 1]\n'
                'let s = List.sortDescending [3, 1]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_ordering_members_need_comparison_2',
        "files": {
            'main.pyfun': (
                'type P = { name: string, age: int }\n'
                '             let ps = [P { name = "a", age = 2 }]\n'
                '             let byAge = List.sortBy (fun p -> p.age) ps\n'
                '             let oldest = List.maxBy (fun p -> p.age) ps'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_aggregates_that_can_be_empty_answer_with_option',
        "files": {
            'main.pyfun': (
                'let n = List.sumBy (fun x -> x * 2) [1, 2]\n'
                'let m = n + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_average_takes_floats',
        "files": {
            'main.pyfun': 'let a = List.average [1.0, 2.0]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_structure_members_keep_their_element_types',
        "files": {
            'main.pyfun': (
                'let p = List.partition (fun x -> x > 1) [1, 2]\n'
                '             let u = List.unzip (List.zip [1] ["a"])\n'
                '             let f = List.flatten [[1], [2]]\n'
                '             let i = List.init 3 (fun n -> n * n)\n'
                '             let r = List.replicate 2 "x"\n'
                '             let g = List.groupBy (fun x -> x % 2) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_positional_updates_and_windows_type',
        "files": {
            'main.pyfun': (
                'let u = List.updateAt 0 9 [1, 2]\n'
                '             let i = List.insertAt 0 9 [1, 2]\n'
                '             let r = List.removeAt 0 [1, 2]\n'
                '             let p = List.pairwise [1, 2, 3]\n'
                '             let w = List.windowed 2 [1, 2, 3]\n'
                '             let c = List.chunkBySize 2 [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_iter_carries_the_effect_of_its_function',
        "files": {
            'main.pyfun': 'let go = List.iter (fun x -> print x) [1, 2]',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fst_and_snd_project_a_pair',
        "files": {
            'main.pyfun': (
                'let a = fst (1, "x")\n'
                'let n = a + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fst_and_snd_project_a_pair_2',
        "files": {
            'main.pyfun': (
                'let b = snd (1, "x")\n'
                'let s = String.len b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'fst_and_snd_project_a_pair_3',
        "files": {
            'main.pyfun': 'let firsts = List.map fst (List.zip [1] ["a"])',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_record_pattern_match',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let sumxy p =\n'
                '  match p:\n'
                '    case Point { x, y }: x + y'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_pattern_binds_fields_at_their_types',
        "files": {
            'main.pyfun': (
                'type Box = { item: int }\n'
                'let f b =\n'
                '  match b:\n'
                '    case Box { item = n }: n + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'record_pattern_may_mention_a_subset_of_fields',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let onlyx p =\n'
                '  match p:\n'
                '    case Point { x }: x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'irrefutable_record_pattern_is_exhaustive',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p =\n'
                '  match p:\n'
                '    case Point { x = a, y = b }: a + b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_block_with_local_bindings',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '    let y = x + 1\n'
                '    let z = y + 1\n'
                '    z'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_local_mut_and_reassignment',
        "files": {
            'main.pyfun': (
                'let sum3 a b c =\n'
                '    let mut acc = 0\n'
                '    acc <- acc + a\n'
                '    acc <- acc + b\n'
                '    acc <- acc + c\n'
                '    acc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'local_bindings_stay_in_scope_polymorphically',
        "files": {
            'main.pyfun': (
                'let f u =\n'
                '    let id a = a\n'
                '    let p = id 1\n'
                '    let q = id true\n'
                '    p'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_pure_binding_with_no_effects',
        "files": {
            'main.pyfun': 'let pure clamp lo hi x = max lo (min hi x)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'pure_calling_a_pure_helper_is_ok',
        "files": {
            'main.pyfun': (
                'let dbl x = x + x\n'
                'let pure good x = dbl x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'higher_order_function_is_effect_polymorphic',
        "files": {
            'main.pyfun': (
                'let pure apply f x = f x\n'
                'let r = apply print 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'pure_higher_order_with_impure_argument_at_call_site_is_fine_2',
        "files": {
            'main.pyfun': (
                'let loop2 x n =\n'
                '  let _ = print x\n'
                '  if n <= 0 then 0 else loop2 x (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'mutually_recursive_functions_of_arity_two_can_perform_io',
        "files": {
            'main.pyfun': (
                'let ping x n =\n'
                '  let _ = print x\n'
                '  if n <= 0 then 0 else pong x (n - 1)\n'
                'let pong x n =\n'
                '  let _ = print "pong"\n'
                '  ping x (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'the_async_module_members_type_as_declared',
        "files": {
            'main.pyfun': (
                'let slow n = async { do! Async.sleep 0.01  return n }\n'
                'let main = async {\n'
                '  let! xs = Async.parallel [slow 1, slow 2]\n'
                '  let! first = Async.race [slow 3, slow 4]\n'
                '  let! t = Async.timeout 0.5 (slow 5)\n'
                '  let! v = Async.toThread (fun _ -> 41)\n'
                '  let! r = Async.catch (slow 6)\n'
                '  let total = match t:\n'
                '    case Some n: n\n'
                '    case None: 0\n'
                '  let got = match r:\n'
                '    case Ok n: n\n'
                '    case Error e: String.len e.errorKind\n'
                '  return List.sum xs + first + total + v + got\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'the_async_module_members_type_as_declared_2',
        "files": {
            'main.pyfun': 'let pure go x = Async.toThread (fun _ -> x + 1)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'task_scope_discharges_the_spawn_that_start_performs',
        "files": {
            'main.pyfun': (
                'let worker = async { do! Async.sleep 0.01 }\n'
                'let launch w = Task.start w\n'
                'let session = Task.scope (async {\n'
                '  Task.start worker\n'
                '  launch worker\n'
                '  return 1\n'
                '})'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'task_scope_discharges_the_spawn_that_start_performs_2',
        "files": {
            'main.pyfun': 'let launch w = Task.start w',
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_trailing_unit_expression_ends_a_monad_block_2',
        "files": {
            'main.pyfun': 'let o = option { print 1 }',
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'decode_auto_is_pinned_by_a_later_use_and_open_otherwise_2',
        "files": {
            'main.pyfun': (
                'type Msg = Hello string | Resign\n'
                'let parse s =\n'
                '  match Decode.decodeString Decode.auto s:\n'
                '    case Ok (Hello who): who\n'
                '    case Ok Resign: "resign"\n'
                '    case Error _: "bad"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'encode_auto_is_pure_and_takes_anything',
        "files": {
            'main.pyfun': (
                'type P = { x: int }\n'
                'let pure wire p = Encode.auto p\n'
                'let s = wire (P { x = 1 })\n'
                'let t = Encode.auto [Some 1, None]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'encode_auto_is_pure_and_takes_anything_2',
        "files": {
            'main.pyfun': 'let s = Encode.auto 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'async_ce_arrow_displays_the_async_label',
        "files": {
            'main.pyfun': 'let go x = async { return x }',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'multi_label_arrow_displays_sorted_regardless_of_annotation_o',
        "files": {
            'main.pyfun': (
                'extern push: string ->{async, io} Async unit = hub.push\n'
                'let go s = push s'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'inferred_multi_label_arrow_displays_on_the_binding',
        "files": {
            'main.pyfun': (
                'extern fetch: string ->{async} Async string = httpx.get\n'
                'let go u =\n'
                '    print u\n'
                '    fetch u'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'partial_application_of_an_annotated_extern_is_pure',
        "files": {
            'main.pyfun': (
                'extern post: string -> string ->{async} Async string = httpx.post\n'
                'let pure prep = post "host"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'format_currency_is_unit_polymorphic',
        "files": {
            'main.pyfun': (
                'measure gbp\n'
                'let s = Format.currency "£" 2 19.5<gbp>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'declared_io_arrow_accepts_an_io_function',
        "files": {
            'main.pyfun': (
                'type Handler = H (string ->{io} unit)\n'
                'let h = H print'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'pure_pipeline_through_an_effect_var_extern_is_pure',
        "files": {
            'main.pyfun': (
                'extern pure app: (a ->{e} b) -> a ->{e} b = mymod.app\n'
                'let pure five = app (fun x -> x + 2) 3'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'labels_and_effect_vars_mix_in_an_extern_signature',
        "files": {
            'main.pyfun': (
                'extern each: (a ->{e} unit) -> List a ->{io, e} unit = mymod.each\n'
                'let r = each (fun x -> ()) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'labels_and_effect_vars_mix_in_an_extern_signature_2',
        "files": {
            'main.pyfun': (
                'extern gather: (a ->{e} b) -> List a ->{async, e} Async (List b) = mymod.gather\n'
                'let r = gather (fun x -> x) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_list_literal_and_functions',
        "files": {
            'main.pyfun': (
                'let xs = [1, 2, 3]\n'
                'let ys = List.map (fun x -> x + 1) xs\n'
                'let zs = List.filter (fun x -> x < 2) xs\n'
                'let t = List.fold (fun a b -> a + b) 0 xs\n'
                'let n = List.len xs\n'
                'let s = List.sum xs\n'
                'let r = List.rev xs\n'
                'let q = List.range 0 5'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'empty_list_is_polymorphic',
        "files": {
            'main.pyfun': (
                'let e = []\n'
                'let a = List.len [1]\n'
                'let b = List.len ["x"]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_tuple_construct_and_destructure',
        "files": {
            'main.pyfun': (
                'let pair = (1, true)\n'
                'let swap p =\n'
                '  match p:\n'
                '    case (a, b): (b, a)\n'
                'let s = swap pair'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_parameter_types_its_elements',
        "files": {
            'main.pyfun': (
                'let tileScore (t, sq) = t * sq\n'
                'let s = tileScore (3, 4)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_wildcard_parameter_accepts_anything_and_binds_nothing',
        "files": {
            'main.pyfun': (
                'let const42 _ = 42\n'
                'let n = const42 "anything"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_wildcard_parameter_accepts_anything_and_binds_nothing_2',
        "files": {
            'main.pyfun': (
                'let fst2 a _ = a\n'
                'let n = fst2 1 true'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_record_parameter_binds_its_fields',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int, letter: string }\n'
                '             let describe (Cell { letter }) = letter\n'
                '             let s = describe (Cell { row = 1, letter = "A" })'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'tuple_match_is_exhaustive_without_wildcard',
        "files": {
            'main.pyfun': (
                'let fst p =\n'
                '  match p:\n'
                '    case (a, b): a'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_tuple_in_record_field_and_extern',
        "files": {
            'main.pyfun': (
                'type Pair = { both: (int, string) }\n'
                'extern pure mk : a -> b -> (a, b) = builtins.tuple\n'
                'let p = Pair { both = (1, "x") }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_of_a_pure_function_stays_pure',
        "files": {
            'main.pyfun': 'let pure inc xs = List.map (fun x -> x + 1) xs',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'input_is_a_prelude_builtin_with_the_io_effect',
        "files": {
            'main.pyfun': 'let ask u = input "? "',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'input_is_a_prelude_builtin_with_the_io_effect_2',
        "files": {
            'main.pyfun': 'let n = String.toInt (input "n? ")',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_set_functions',
        "files": {
            'main.pyfun': (
                'let s = Set.ofList [1, 2, 3]\n'
                'let s2 = Set.add 4 s\n'
                'let s3 = Set.remove 1 s2\n'
                'let has = Set.contains 2 s3\n'
                'let n = Set.len s3\n'
                'let u = Set.union s s2\n'
                'let i = Set.intersect s s2\n'
                'let d = Set.difference s s2\n'
                'let xs = Set.toList (Set.union s Set.empty)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_map_functions',
        "files": {
            'main.pyfun': (
                'let m = Map.add "a" 1 (Map.add "b" 2 Map.empty)\n'
                'let v = Map.findOr "a" 0 m\n'
                'let o = Map.tryFind "a" m\n'
                'let m2 = Map.remove "b" m\n'
                'let has = Map.contains "a" m2\n'
                'let n = Map.len m2\n'
                'let ks = Map.keys m\n'
                'let vs = Map.values m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'try_yields_a_result_over_exception',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int = int\n'
                'let describe s =\n'
                '  match try (parseInt s):\n'
                '    case Ok n: n\n'
                '    case Error e: String.len e.errorKind'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'try_body_type_flows_into_ok',
        "files": {
            'main.pyfun': (
                'extern readFile : string -> string = open\n'
                'let firstChar path =\n'
                '  match try (readFile path):\n'
                '    case Ok contents: String.upper contents\n'
                '    case Error e: e.errorMessage'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_literal_patterns_typecheck_over_strings',
        "files": {
            'main.pyfun': (
                'let classify s =\n'
                '  match s:\n'
                '    case "yes": 1\n'
                '    case "no": 0\n'
                '    case _: 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'interpolated_string_has_type_string',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let n = 3\n'
                'let p = (1, 2)\n'
                'let msg = f"hi {name}, n={n}, sum={n + 1}, p={p}"\n'
                'let len = String.len msg'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'interpolation_debug_hole_is_an_ordinary_hole',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let a = 4\n'
                'let b = 5\n'
                'let m = f"{x=} {a + b = }"\n'
                'let len = String.len m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'interpolation_debug_hole_is_an_ordinary_hole_2',
        "files": {
            'main.pyfun': (
                'let x = 1\n'
                'let y = 2\n'
                'let m = f"{x==y}"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'interpolation_propagates_hole_effects',
        "files": {
            'main.pyfun': 'let pure label n = f"n = {n}"',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_string_is_a_string',
        "files": {
            'main.pyfun': (
                'let doc = """line one\n'
                'line two"""\n'
                'let n = String.len doc'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'triple_quoted_fstring_types_and_effects_match_the_single_lin',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let n = 3\n'
                'let msg = f"""hi {name}\n'
                'sum {n + 1}"""\n'
                'let len = String.len msg'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_string_functions',
        "files": {
            'main.pyfun': (
                'let g = String.concat "Hello, " "World"\n'
                'let n = String.len g\n'
                'let up = String.upper g\n'
                'let lo = String.lower g\n'
                'let t = String.strip "  x  "\n'
                'let parts = String.split "," g\n'
                'let joined = String.join " | " parts\n'
                'let has = String.contains "World" g\n'
                'let sw = String.startsWith "He" g\n'
                'let ew = String.endsWith "ld" g\n'
                'let r = String.replace "l" "L" g\n'
                'let s1 = String.fromInt 7\n'
                'let s2 = String.fromFloat 3.5\n'
                'let chars = String.toList g'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'string_to_int_returns_an_option',
        "files": {
            'main.pyfun': (
                'let bump o =\n'
                '  match o:\n'
                '    case Some n: n + 1\n'
                '    case None: 0\n'
                'let r = bump (String.toInt "41")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'list_zip_pairs_elements_into_tuples',
        "files": {
            'main.pyfun': (
                'let firstOf p =\n'
                '  match p:\n'
                '    case (n, s): n\n'
                'let ps = List.zip [1, 2] ["a", "b"]\n'
                'let firsts = List.map firstOf ps\n'
                'let total = List.sum firsts'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'map_of_list_and_to_list_round_trip_through_pairs',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList (List.zip ["a", "b"] [1, 2])\n'
                'let v = Option.withDefault 0 (Map.tryFind "a" m)\n'
                'let pairs = Map.toList m'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'try_find_returns_an_option',
        "files": {
            'main.pyfun': (
                'let m = Map.add "a" 1 Map.empty\n'
                'let v = Option.withDefault 0 (Map.tryFind "a" m)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'empty_collections_are_polymorphic',
        "files": {
            'main.pyfun': (
                'let a = Set.len (Set.add 1 Set.empty)\n'
                'let b = Set.len (Set.add "x" Set.empty)\n'
                'let c = Map.len (Map.add 1 true Map.empty)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_result_module',
        "files": {
            'main.pyfun': (
                'let r = Ok 1\n'
                'let a = Result.map (fun x -> x + 1) r\n'
                'let b = Result.mapError (fun e -> e) r\n'
                'let c = Result.bind (fun x -> Ok (x + 1)) r\n'
                'let d = Result.withDefault 0 r\n'
                'let e = Result.isOk r\n'
                'let f = Result.isError r\n'
                'let g = Result.toOption r'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'result_to_option_bridges_to_option',
        "files": {
            'main.pyfun': 'let v = Option.withDefault 0 (Result.toOption (Ok 1))',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_seq_module',
        "files": {
            'main.pyfun': (
                'let s = Seq.ofList [1, 2, 3]\n'
                'let a = Seq.map (fun x -> x + 1) s\n'
                'let b = Seq.filter (fun x -> x < 2) s\n'
                'let c = Seq.take 2 s\n'
                'let d = Seq.fold (fun acc x -> acc + x) 0 s\n'
                'let e = Seq.toList (Seq.range 0 5)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'module_members_see_siblings_unqualified',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '  let pi = 3\n'
                '  let area r = pi * r * r\n'
                '  let double a = area a + area a\n'
                'let r = M.double 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'accepts_extern_with_concrete_type',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let r = tan 2.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'extern_type_is_generalized_over_its_variables',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'let a = show 1\n'
                'let b = show true'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'pure_extern_can_be_used_in_a_pure_binding',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let pure root x = tan x'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'partial_application_of_an_extern_is_pure',
        "files": {
            'main.pyfun': (
                'extern pow: float -> float -> float = math.pow\n'
                'let pure twoTo = pow 2.0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'combinators_are_fully_type_polymorphic',
        "files": {
            'main.pyfun': (
                'let a = id 1\n'
                'let b = id true\n'
                'let c = const 1 "x"\n'
                'let d = ignore [1, 2]\n'
                'let sub x y = x - y\n'
                'let e = flip sub 3 10'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'flip_is_effect_polymorphic',
        "files": {
            'main.pyfun': (
                'let sub a b = a - b\n'
                'let pure ok = flip sub 1 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_user_definition_shadows_the_prelude_combinators',
        "files": {
            'main.pyfun': (
                'let id x = x + 1\n'
                'let r = id 10'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'total_active_pattern_cases_may_carry_data',
        "files": {
            'main.pyfun': (
                'let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small s: s\n'
                '    case Big b: b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_partial_binds_the_payload_at_its_type',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Positive p: p + 1\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'bool_partial_binds_nothing',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = String.strip s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank: "empty"\n'
                '    case _: "text"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'parameterized_partial_type_checks_and_checks_its_arguments',
        "files": {
            'main.pyfun': (
                'let (|DivisibleBy|_|) d n = n % d == 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case DivisibleBy 3: "fizz"\n'
                '    case _: "n"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_pure_active_pattern_keeps_the_match_pure',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let pure f n =\n'
                '  match n:\n'
                '    case Even: 1\n'
                '    case Odd: 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'guards_are_accepted_in_an_active_pattern_match',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even if n > 0: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'guards_are_accepted_in_an_active_pattern_match_2',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Positive p if p > 100: "big"\n'
                '    case Positive p: "small"\n'
                '    case _: "nonpos"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'structural_patterns_mix_with_active_patterns',
        "files": {
            'main.pyfun': (
                'let (|Empty|_|) xs = List.isEmpty xs\n'
                'let f xs =\n'
                '  match xs:\n'
                '    case Empty: 0\n'
                '    case [x]: x\n'
                '    case _: 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_over_total_cases_is_exhaustive_without_a_wildcard',
        "files": {
            'main.pyfun': (
                'let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small _ | Big _: 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'or_pattern_over_partial_bool_cases_with_params',
        "files": {
            'main.pyfun': (
                'let (|DivisibleBy|_|) d n = n % d == 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case DivisibleBy 3 | DivisibleBy 5: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'guards_on_structural_arms_beside_active_patterns_are_accepte',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let f o =\n'
                '  match o:\n'
                '    case Some x if x > 100: "big"\n'
                '    case Answer: "answer"\n'
                '    case _: "other"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'literal_arms_mix_with_active_patterns_but_need_a_wildcard',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case 0: 0\n'
                '    case Even: 2\n'
                '    case Odd: 1\n'
                '    case _: 9'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'total_active_pattern_over_an_adt_scrutinee_is_exhaustive',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let (|Round|Angular|) s =\n'
                '  match s:\n'
                '    case Circle r: Round\n'
                '    case Rect w h: Angular\n'
                'let f s =\n'
                '  match s:\n'
                '    case Round: 1\n'
                '    case Angular: 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_tuple_target_binds_each_element_at_its_own_type',
        "files": {
            'main.pyfun': (
                'let (a, b) = (1, "x")\n'
                'let n = a + 1\n'
                'let s = String.len b'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_record_target_binds_the_fields_it_names',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let Point { x } = Point { x = 1, y = 2 }\n'
                'let n = x + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_destructured_name_generalizes_like_any_other_binding',
        "files": {
            'main.pyfun': (
                'let (f, g) = (List.map, List.map)\n'
                'let a = f (fun x -> x + 1) [1]\n'
                'let b = g (fun s -> String.len s) ["x"]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'option_block_chains_several_binds',
        "files": {
            'main.pyfun': (
                'let f xs s = option {\n'
                '  let! a = List.get 0 xs\n'
                '  let! b = List.get 1 xs\n'
                '  let! n = String.toInt s\n'
                '  return (a + b + n)\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_trailing_do_bang_ends_a_monad_block_as_unit',
        "files": {
            'main.pyfun': (
                'let check x = if x > 0 then Ok () else Error "neg"\n'
                'let v = result { do! check 1 }\n'
                'let w = result {\n'
                '  let! a = Ok 2\n'
                '  do! check a\n'
                '}\n'
                'let o = option { do! Some () }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
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
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'multiline_union_parses_like_inline',
        "files": {
            'main.pyfun': (
                'type Color =\n'
                '  | Red\n'
                '  | Green\n'
                '  | Blue'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'multiline_union_parses_like_inline_2',
        "files": {
            'main.pyfun': (
                'type Shape =\n'
                '  | Circle float\n'
                '  | Rect float float'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'multiline_union_parses_like_inline_3',
        "files": {
            'main.pyfun': (
                'type M =\n'
                '  | A | B\n'
                '  | C'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'multiline_union_parses_like_inline_4',
        "files": {
            'main.pyfun': (
                'type Point =\n'
                '  { x: int, y: int }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'arithmetic_precedence',
        "files": {
            'main.pyfun': 'let r = 1 + 2 * 3',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'exponentiation_is_right_assoc_and_binds_tighter_than_unary_m',
        "files": {
            'main.pyfun': 'let r = -2.0 ** 2.0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'operator_section_parses_to_op_func',
        "files": {
            'main.pyfun': 'let mul = (*)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'operator_section_parses_to_op_func_2',
        "files": {
            'main.pyfun': 'let double = (*) 2',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'operator_section_parses_to_op_func_3',
        "files": {
            'main.pyfun': 'let g = (1 + 2)',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'offside_rule_separates_statements_but_joins_continuations',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  match n:\n'
                '    case 0: 1\n'
                '    case _: 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_bare_uppercase_parameter_is_still_two_parameters',
        "files": {
            'main.pyfun': 'let f Some x = x',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'a_capitalised_let_name_is_rejected_as_a_constructor',
        "files": {
            'main.pyfun': 'let some x = x',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'let_rec_is_rejected_with_a_helpful_hint',
        "files": {
            'main.pyfun': 'let rec = 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'let_rec_is_rejected_with_a_helpful_hint_2',
        "files": {
            'main.pyfun': 'let f x = x',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'def_is_answered_with_the_let_spelling',
        "files": {
            'main.pyfun': 'let area w h = w * h',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'def_is_answered_with_the_let_spelling_2',
        "files": {
            'main.pyfun': (
                'let greet _ =\n'
                '  print "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'def_is_answered_with_the_let_spelling_3',
        "files": {
            'main.pyfun': (
                'let def x = x + 1\n'
                'print (def 2)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'doc_comment_attaches_to_the_following_declaration',
        "files": {
            'main.pyfun': (
                '## Adds one\n'
                '## to a number.\n'
                'let inc x = x + 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'ordinary_comments_and_non_doc_positions_stay_undocumented',
        "files": {
            'main.pyfun': (
                '# plain comment\n'
                'let a = 1 ## trailing\n'
                '## Documented.\n'
                'let b = 2'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'trailing_doc_lines_without_a_declaration_are_dropped',
        "files": {
            'main.pyfun': (
                'let a = 1\n'
                '## dangling note'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'active_pattern_declarations_parse_to_the_expected_shape',
        "files": {
            'main.pyfun': 'let (|DivisibleBy|_|) d n = n % d == 0',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'active_pattern_declarations_parse_to_the_expected_shape_2',
        "files": {
            'main.pyfun': 'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run_executes_a_valid_program',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let r = add 1 2\n'
                'let x = Some r'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run_propagates_a_python_runtime_error',
        "files": {
            'main.pyfun': (
                'let divide a b = a / b\n'
                'let boom = divide 1 0'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run_feeds_the_program_its_own_stdin',
        "files": {
            'main.pyfun': (
                'extern readLine : string -> string = builtins.input\n'
                'let main =\n'
                '    let name = readLine "name? "\n'
                '    print (f"hi {name}")\n'
                'main'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run_leaves_the_working_directory_alone',
        "files": {
            'main.pyfun': (
                'extern readFile : string -> string = pathlib.Path.read_text\n'
                'extern pure path : string -> string = pathlib.Path\n'
                'let main = print (readFile (path "data.txt"))\n'
                'main'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run_leaves_the_working_directory_alone_2',
        "files": {
            'main.pyfun': (
                'extern import sys\n'
                'extern getArgv : unit -> List string = sys.argv.copy\n'
                'print (getArgv ())'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'bundle_writes_a_page_a_loader_the_modules_and_the_assets',
        "files": {
            'main.pyfun': 'print 42',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'single_file_without_imports_still_inlines_classes',
        "files": {
            'main.pyfun': 'let x = Some 1',
        },
        'args': ['compile', 'main.pyfun'],
    },
]

NATIVE_CASES = [
    {
        'id': 'native__curried_def_lowers_to_n_ary_def',
        "files": {
            'main.pyfun': 'let add a b = a + b',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__full_application_is_a_direct_call',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let r = add 1 2'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__unit_literal_lowers_to_none',
        "files": {
            'main.pyfun': 'let nothing = ()',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                'let add a b = a + b\n'
                'let inc = add 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_lowers_to_its_python_target_with_import',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let r = tan 8.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_with_name_equal_target_needs_no_import',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'let r = show 42'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__unused_extern_imports_nothing',
        "files": {
            'main.pyfun': (
                'extern pure tan: float -> float = math.tan\n'
                'let r = 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_in_submodule_imports_the_submodule',
        "files": {
            'main.pyfun': (
                'extern import urllib.parse\n'
                'extern q: string -> string = urllib.parse.quote\n'
                'let r = q "a b"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__newtype_erases_to_the_bare_underlying_value',
        "files": {
            'main.pyfun': (
                'opaque type UserId = string\n'
                'let uid = UserId "u-1001"\n'
                'let f u =\n'
                '  match u:\n'
                '    case UserId s: s'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__irrefutable_newtype_case_truncates_later_arms_and_the_guard',
        "files": {
            'main.pyfun': (
                'opaque type Cents = int\n'
                'let f c =\n'
                '  match c:\n'
                '    case Cents n: n\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_newtype_wrap_unwrap_round_trips',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type UserId = string\n'
                '        let uid = UserId "u-1001"\n'
                '        let unwrapped =\n'
                '          match uid:\n'
                '            case UserId s: s\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_newtype_literal_payload_selects_arms',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type Cents = int\n'
                '        let describe c =\n'
                '          match c:\n'
                '            case Cents 0: "free"\n'
                '            case Cents n: "costs"\n'
                '        let a = describe (Cents 0)\n'
                '        let b = describe (Cents 42)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_mapping_a_newtype_constructor_is_identity',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type UserId = string\n'
                '        let total =\n'
                '          ["ab", "c"]\n'
                '          |> List.map UserId\n'
                '          |> List.fold (fun acc u ->\n'
                '            match u:\n'
                '                case UserId s: acc + String.len s) 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_newtype_crosses_the_extern_boundary_bare',
        "files": {
            'main.pyfun': (
                '\n'
                '        opaque type UserId = string\n'
                '        extern pure upperId: UserId -> string = str.upper\n'
                '        let r = upperId (UserId "abc")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__instance_method_extern_lowers_to_a_method_call',
        "files": {
            'main.pyfun': (
                'type R = RH\n'
                'extern readBody: R -> string = .read()\n'
                'let f r = readBody r'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__instance_method_extern_passes_remaining_args',
        "files": {
            'main.pyfun': (
                'type C = CH\n'
                'extern ex: C -> string -> C = .execute()\n'
                'let f c = ex c "select 1"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__instance_method_receiver_only_partial_is_the_bound_method',
        "files": {
            'main.pyfun': (
                'type C = CH\n'
                'extern ex: C -> string -> C = .execute()\n'
                'let g c = ex c'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__instance_property_extern_reads_the_attribute',
        "files": {
            'main.pyfun': (
                'type U = UH\n'
                'extern scheme: U -> string = .scheme\n'
                'let f u = scheme u'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__nullary_extern_lowers_to_a_zero_arg_call',
        "files": {
            'main.pyfun': (
                'extern now: unit -> float = time.time\n'
                'let t = now ()'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_receiver_method_with_a_unit_parameter_drops_it',
        "files": {
            'main.pyfun': (
                'extern type C\n'
                'extern ping: C -> unit -> string = .m()\n'
                'let f c = ping c ()'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_unit_parameters_across_the_boundary',
        "files": {
            'main.pyfun': (
                'extern myAbs: unit -> int -> int = abs\n'
                'extern pick: int -> unit -> int -> int = max\n'
                'let a = myAbs () (-5)\n'
                'let b = pick 3 () 5\n'
                'let fromNeg = myAbs ()\n'
                'let c = fromNeg (-7)\n'
                'let lifted = pick 4\n'
                'let d = lifted () 2'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_on_builtin_type_imports_nothing',
        "files": {
            'main.pyfun': (
                'extern up: string -> string = str.upper\n'
                'let r = up "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_on_class_method_imports_only_the_module',
        "files": {
            'main.pyfun': (
                'type C = CH\n'
                'extern ex: C -> string -> C = sqlite3.Connection.execute\n'
                'let f c = ex c "x"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_import_declares_the_module_explicitly',
        "files": {
            'main.pyfun': (
                'extern import datetime\n'
                'extern now: unit -> a = datetime.datetime.now\n'
                'let t = now ()'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_import_covers_a_fully_applied_value_attribute_target',
        "files": {
            'main.pyfun': (
                'extern import sys\n'
                'extern write: string -> int = sys.stdout.write\n'
                'let r = write "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_import_alias_emits_import_as_and_roots_targets',
        "files": {
            'main.pyfun': (
                'extern import json as j\n'
                'extern dumps: List int -> string = j.dumps\n'
                'let s = dumps [1]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_import_composes_with_pinned_kwargs',
        "files": {
            'main.pyfun': (
                'extern import sqlite3\n'
                'extern conn: string -> a = sqlite3.dbapi2.connect(timeout=5)\n'
                'let c = conn ":memory:"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_declared_import_settles_an_undecidable_target',
        "files": {
            'main.pyfun': (
                'extern import urllib.request\n'
                'extern get: string -> a = urllib.request.urlopen\n'
                'let r = get "x"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_top_level_target_needs_no_declaration',
        "files": {
            'main.pyfun': (
                'extern pure f: float -> float = math.fabs\n'
                'let r = f 1.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__unused_extern_import_emits_nothing',
        "files": {
            'main.pyfun': (
                'extern import sqlite3\n'
                'let x = 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_kwargs_are_appended_to_the_call',
        "files": {
            'main.pyfun': (
                'extern openText : string -> Seq string = builtins.open(mode="rt", encoding="utf-8")\n'
                'let f path = openText path'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__receiver_method_extern_kwargs_follow_the_positional_args',
        "files": {
            'main.pyfun': (
                'type P = PH\n'
                'extern writeText : P -> string -> int = .write_text(encoding="utf-8")\n'
                'let f p text = writeText p text'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_kwargs_support_int_negative_bool_and_float_values',
        "files": {
            'main.pyfun': (
                'extern g : string -> a = gzip.open(compresslevel=9, buffering=-1, text=true, ratio=2.5)\n'
                'let f path = g path'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_extern_kwargs_produce_observable_output',
        "files": {
            'main.pyfun': (
                'extern parseHex : string -> int = int(base=16)\n'
                'let n = parseHex "ff"\n'
                'let m = parseHex "10"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_kwarg_slot_takes_a_trailing_argument',
        "files": {
            'main.pyfun': (
                'extern openText : string -> string -> Seq string = builtins.open(mode="rt", encoding=...)\n'
                'let f path enc = openText path enc'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__extern_kwarg_slots_fill_in_the_order_the_keywords_are_writte',
        "files": {
            'main.pyfun': (
                'extern mix : string -> int -> bool -> a = m.f(a=1, b=..., c="x", d=...)\n'
                'let f s i b = mix s i b'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__receiver_method_extern_kwarg_slot_takes_a_trailing_argument',
        "files": {
            'main.pyfun': (
                'extern type P\n'
                'extern writeText : P -> string -> string -> int = .write_text(encoding=...)\n'
                'let f p text enc = writeText p text enc'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_extern_kwarg_slot_produces_observable_output',
        "files": {
            'main.pyfun': (
                'extern parseIn : string -> int -> int = int(base=...)\n'
                'let hex = parseIn "ff" 16\n'
                'let bin = parseIn "1011" 2\n'
                'let ff = parseIn "ff"\n'
                'let also = ff 16'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_literal_lowers_to_a_python_list',
        "files": {
            'main.pyfun': 'let xs = [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__map_filter_lower_to_emitted_helpers',
        "files": {
            'main.pyfun': 'let r = List.map (fun x -> x) (List.filter (fun x -> true) [1, 2])',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__len_and_sum_lower_to_python_builtins_without_helpers',
        "files": {
            'main.pyfun': (
                'let n = List.len [1, 2]\n'
                'let s = List.sum [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_lowers_to_functools_reduce',
        "files": {
            'main.pyfun': 'let t = List.fold (fun a b -> a + b) 0 [1, 2, 3]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__pipe_becomes_application',
        "files": {
            'main.pyfun': (
                'let id x = x\n'
                'let r = 5 |> id'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__empty_collections_lower_to_set_and_dict',
        "files": {
            'main.pyfun': (
                'let s = Set.empty\n'
                'let m = Map.empty'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__set_functions_lower_to_emitted_helpers',
        "files": {
            'main.pyfun': 'let r = Set.contains 1 (Set.add 1 (Set.ofList [2]))',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__map_add_and_find_or_lower_to_emitted_helpers',
        "files": {
            'main.pyfun': (
                'let m = Map.add "a" 1 Map.empty\n'
                'let v = Map.findOr "a" 0 m'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__map_remove_lowers_to_a_copy_and_pop',
        "files": {
            'main.pyfun': 'let m = Map.remove "a" Map.empty',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__try_find_lowers_to_an_option_and_pulls_in_the_option_prelude',
        "files": {
            'main.pyfun': 'let v = Map.tryFind "a" Map.empty',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_zip_lowers_to_a_zip_helper',
        "files": {
            'main.pyfun': 'let ps = List.zip [1, 2] [3, 4]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__map_of_list_lowers_to_dict_and_to_list_to_items',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, 2)]\n'
                'let ps = Map.toList m'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_zip_into_a_map_and_back',
        "files": {
            'main.pyfun': (
                '\n'
                '        let m = Map.ofList (List.zip ["a", "b"] [1, 2])\n'
                '        let a = Option.withDefault 0 (Map.tryFind "a" m)\n'
                '        let n = Map.len m\n'
                '        let pairs = Map.toList m\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__try_lowers_to_a_try_except_yielding_ok_or_error',
        "files": {
            'main.pyfun': (
                'extern parseInt : string -> int = int\n'
                'let safe s = try (parseInt s)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_try_catches_and_recovers',
        "files": {
            'main.pyfun': (
                '\n'
                '        extern parseInt : string -> int = int\n'
                '        let orZero s = Result.withDefault 0 (try (parseInt s))\n'
                '        let good = orZero "42"\n'
                '        let bad = orZero "oops"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_try_exposes_exception_kind_and_message',
        "files": {
            'main.pyfun': (
                '\n'
                '        extern parseInt : string -> int = int\n'
                '        let kindOf s =\n'
                '          match try (parseInt s):\n'
                '            case Ok n: "ok"\n'
                '            case Error e: e.errorKind\n'
                '        let k = kindOf "nope"\n'
                '        let matched =\n'
                '          match try (parseInt "x"):\n'
                '            case Error (Exception { errorKind = "ValueError" }): "caught-value-error"\n'
                '            case _: "other"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__interpolated_string_lowers_to_a_python_fstring',
        "files": {
            'main.pyfun': (
                'let name = "Ada"\n'
                'let a = 3\n'
                'let b = 4\n'
                'let g = f"hi {name}: {a + b}"\n'
                'let u = f"upper {String.upper name}"\n'
                'let e = f"brace {{ {a}"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_interpolated_strings',
        "files": {
            'main.pyfun': (
                '\n'
                '        let name = "Ada"\n'
                '        let a = 3\n'
                '        let b = 4\n'
                '        let p = (1, 2)\n'
                '        let greet = f"Hello, {name}!"\n'
                '        let math = f"{a} + {b} = {a + b}"\n'
                '        let up = f"upper: {String.upper name}"\n'
                '        let brace = f"{{literal}} {a}"\n'
                '        let point = f"point {p}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__debug_hole_lowers_to_an_echoed_literal_plus_hole',
        "files": {
            'main.pyfun': (
                'let x = 3\n'
                'let y = 4\n'
                'let a = f"{x=}"\n'
                'let b = f"{x = }"\n'
                'let c = f"sum {x + y=} end"\n'
                'let d = f"{x==y}"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_mutual_recursion',
        "files": {
            'main.pyfun': (
                '\n'
                '        let isEven = fun n -> if n == 0 then true else isOdd (n - 1)\n'
                '        let isOdd = fun n -> if n == 0 then false else isEven (n - 1)\n'
                '        let a = isEven 10\n'
                '        let b = isOdd 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__as_pattern_lowers_to_python_as',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case Some v as w: w\n'
                '    case None: None'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_as_pattern',
        "files": {
            'main.pyfun': (
                '\n'
                '        let describe = fun n ->\n'
                '            match n:\n'
                '                case 0: 0\n'
                '                case x as v: v\n'
                '        let both = fun p ->\n'
                '            match p:\n'
                '                case (a, b) as w: w\n'
                '        let a = describe 7\n'
                '        let b = both (3, 4)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_discard_runs_the_effect',
        "files": {
            'main.pyfun': (
                '\n'
                '        let go =\n'
                '            let _ = 1 + 2\n'
                '            42\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__string_slice_lowers_to_python_slicing',
        "files": {
            'main.pyfun': 'let a = String.slice 0 3 "hello"',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_string_slice_and_index_of',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = "hello world"\n'
                '        let a = String.slice 0 5 s\n'
                '        let b = String.slice 6 100 s\n'
                '        let c = Option.withDefault (0 - 1) (String.tryIndexOf "world" s)\n'
                '        let d = Option.withDefault (0 - 1) (String.tryIndexOf "zzz" s)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__stdlib_predicates_inline_when_fully_applied',
        "files": {
            'main.pyfun': (
                'let a s = String.contains "x" s\n'
                '         let b s = String.startsWith "x" s\n'
                '         let c s = String.endsWith "x" s\n'
                '         let d xs = List.contains 3 xs\n'
                '         let e s = Set.contains 3 s\n'
                '         let g m = Map.contains 3 m\n'
                '         let h xs = List.isEmpty xs'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__inlined_membership_parenthesizes_correctly',
        "files": {
            'main.pyfun': (
                'let f s = String.contains "a" s and String.contains "b" s\n'
                '         let g s = if String.contains "a" s then 1 else 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__stdlib_predicate_partial_application_falls_back_to_helper',
        "files": {
            'main.pyfun': (
                'let f = String.contains "x"\n'
                '         let r = List.filter f ["xy", "ab"]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_inlined_stdlib_predicates',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = String.contains "lo" "hello"\n'
                '        let b = String.contains "hello" "lo"\n'
                '        let c = String.startsWith "he" "hello"\n'
                '        let d = String.startsWith "lo" "hello"\n'
                '        let e = String.endsWith "lo" "hello"\n'
                '        let f = String.endsWith "he" "hello"\n'
                '        let g = List.contains 3 [1, 2, 3]\n'
                '        let h = List.contains 9 [1, 2, 3]\n'
                '        let i = Set.contains 2 (Set.ofList [1, 2, 3])\n'
                '        let j = Map.contains 1 (Map.ofList [(1, "a")])\n'
                '        let k = Map.contains 9 (Map.ofList [(1, "a")])\n'
                '        let l = List.isEmpty (List.filter (fun x -> x > 9) [1, 2, 3])\n'
                '        let m = List.isEmpty [1, 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_stdlib_predicate_partial_application',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f = String.contains "lo"\n'
                '        let a = f "hello"\n'
                '        let b = f "hi"\n'
                '        let r = List.filter (String.contains "a") ["cat", "dog", "bat"]\n'
                '        let n = List.len r\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__eq_section_predicates_route_to_the_c_level_scan',
        "files": {
            'main.pyfun': (
                'let a l rack = List.findIndex ((==) l) rack\n'
                '         let b l rack = List.find ((==) l) rack\n'
                '         let c l rack = List.exists ((==) l) rack\n'
                '         let d l rack = List.findIndex (fun y -> y == l) rack\n'
                '         let e l rack = List.findIndex (fun y -> l == y) rack'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__eq_section_specialization_keeps_the_helper_otherwise',
        "files": {
            'main.pyfun': (
                'let p l = List.findIndex ((==) l)\n'
                '         let q l rack = List.findIndex (fun y -> y > l) rack\n'
                '         let r rack = List.findIndex (fun y -> y == y) rack\n'
                '         let s l rack = List.exists (fun l -> l == l) rack'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__eq_section_value_is_evaluated_once_before_the_list',
        "files": {
            'main.pyfun': (
                'let f n = n + 1\n'
                '         let a rack = List.findIndex ((==) (f 1)) rack\n'
                '         let b rack = List.exists ((==) (f 1)) rack'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_eq_section_specialization_matches_the_helper',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = List.findIndex ((==) 3) [1, 2, 3, 3]\n'
                '        let b = List.findIndex ((==) 9) [1, 2, 3]\n'
                '        let c = List.find ((==) "b") ["a", "b"]\n'
                '        let d = List.find ((==) "z") ["a", "b"]\n'
                '        let e = List.exists ((==) 2) [1, 2]\n'
                '        let f = List.exists ((==) 5) [1, 2]\n'
                '        let g = List.findIndex (fun y -> y == (1, 2)) [(0, 0), (1, 2)]\n'
                '        let h = List.findIndex ((==) 0) []\n'
                '        let i = List.find ((==) 0.0) [-0.0]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__match_on_map_try_find_lowers_to_a_membership_test',
        "files": {
            'main.pyfun': (
                'let allows checks rc l =\n'
                '           match Map.tryFind rc checks:\n'
                '             case None: true\n'
                '             case Some s: Set.contains l s'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__match_on_lookups_covers_head_and_get_in_both_positions',
        "files": {
            'main.pyfun': (
                'let hd xs =\n'
                '           match List.head xs:\n'
                '             case Some h: h\n'
                '             case None: 0\n'
                '         let g i xs = 1 + (match List.get (i + 1) xs:\n'
                '           case Some (a, b): a + b\n'
                '           case None: 0)\n'
                '         let w m = match Map.tryFind 1 m:\n'
                '           case Some _: 1\n'
                '           case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__match_on_lookups_falls_through_for_other_shapes',
        "files": {
            'main.pyfun': (
                'let a k m =\n'
                '           match Map.tryFind k m:\n'
                '             case Some 0: "zero"\n'
                '             case Some _: "other"\n'
                '             case None: "none"\n'
                '         let b k m =\n'
                '           match Map.tryFind k m:\n'
                '             case Some v if v > 0: v\n'
                '             case _: 0\n'
                '         let c f = match f 1:\n'
                '           case Some v: v\n'
                '           case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_match_on_lookups_matches_the_helper',
        "files": {
            'main.pyfun': (
                '\n'
                '        let look k m =\n'
                '          match Map.tryFind k m:\n'
                '            case Some v: v\n'
                '            case None: "absent"\n'
                '        let m = Map.ofList [(1, "one"), (2, "")]\n'
                '        let a = look 1 m\n'
                '        let b = look 2 m\n'
                '        let c = look 3 m\n'
                '        let hd xs = match List.head xs:\n'
                '          case Some h: h\n'
                '          case None: -1\n'
                '        let d = hd [0, 1]\n'
                '        let e = hd []\n'
                '        let get i xs = match List.get i xs:\n'
                '          case Some x: x\n'
                '          case None: -1\n'
                '        let f = get 0 [0]\n'
                '        let g = get 1 [0]\n'
                '        let h = get (0 - 1) [0]\n'
                '        let ok = Map.ofList [("k", [])]\n'
                '        let i = match Map.tryFind "k" ok:\n'
                '          case Some xs: List.len xs\n'
                '          case None: -1\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__exponentiation_lowers_right_assoc',
        "files": {
            'main.pyfun': (
                'let a = 2.0 ** 3.0 ** 2.0\n'
                'let b = -2.0 ** 2.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_exponentiation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 2.0 ** 8.0\n'
                '        let b = 2.0 ** 3.0 ** 2.0\n'
                '        let c = 2.0 ** -1.0\n'
                '        let d = -2.0 ** 2.0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_bind_filter_to_result',
        "files": {
            'main.pyfun': (
                '\n'
                '        let half = fun x -> if x % 2 == 0 then Some (x // 2) else None\n'
                '        let a = Option.withDefault 0 (Option.bind half (Some 8))\n'
                '        let b = Option.withDefault 0 (Option.bind half (Some 7))\n'
                '        let c = Option.withDefault 0 (Option.filter (fun x -> x > 5) (Some 8))\n'
                '        let d = Option.withDefault 0 (Option.filter (fun x -> x > 5) (Some 2))\n'
                '        let e = Result.withDefault 0 (Option.toResult 0 (Some 42))\n'
                '        let f = Result.isError (Option.toResult 0 None)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__numeric_conversions_lower_correctly',
        "files": {
            'main.pyfun': (
                'let a = round 3.7\n'
                'let b = floor 3.2\n'
                'let c = ceil 3.2\n'
                'let d = truncate 3.9'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__sqrt_lowers_to_math_sqrt_with_units_erased',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = sqrt 16.0<m^2>'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__sqrt_lowers_to_math_sqrt_with_units_erased_2',
        "files": {
            'main.pyfun': (
                'let f = sqrt\n'
                'let r = f 4.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_user_sqrt_shadows_the_builtin_in_lowering',
        "files": {
            'main.pyfun': (
                'let sqrt x = x\n'
                'let r = sqrt 3'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_unit_aware_sqrt',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = sqrt 16.0<m^2>\n'
                'let hyp = sqrt (2.0 * 2.0 + 2.0 * 2.0)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__cbrt_lowers_to_math_cbrt_with_units_erased',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = cbrt 27.0<m^3>'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__cbrt_lowers_to_math_cbrt_with_units_erased_2',
        "files": {
            'main.pyfun': (
                'let f = cbrt\n'
                'let r = f 8.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_unit_aware_cbrt',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'let side = cbrt 27.0<m^3>\n'
                'let neg = cbrt (0.0 - 8.0)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_numeric_conversions',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = round 3.7\n'
                '        let b = floor 3.7\n'
                '        let c = ceil 3.2\n'
                '        let d = truncate 3.9\n'
                '        let e = floor (-2.5)\n'
                '        let f = Option.withDefault 0.0 (String.toFloat "3.5")\n'
                '        let g = Option.withDefault 0.0 (String.toFloat "nope")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_string_escapes',
        "files": {
            'main.pyfun': (
                '\n'
                '        let crlf = String.len "a\\r\\nb"\n'
                '        let emoji = String.len "hi \\u{1F600}"\n'
                '        let accent = String.len "caf\\u{e9}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_digit_separators_and_bases',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 1_000_000\n'
                '        let b = 0xFF\n'
                '        let c = 0o17\n'
                '        let d = 0b1010\n'
                '        let e = 0xDEAD_BEEF\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__scientific_notation_lowers_to_float',
        "files": {
            'main.pyfun': (
                'let a = 1e6\n'
                'let b = 2.5e-3\n'
                'let g = 6.674e-11'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_scientific_notation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 1e3\n'
                '        let b = 2.5e-1\n'
                '        let c = 1e3 + 1.0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_completeness_ops_lower_to_helpers',
        "files": {
            'main.pyfun': (
                'let a = List.get 0 [1, 2]\n'
                'let b = List.isEmpty [1]\n'
                'let c = List.contains 2 [1, 2]\n'
                'let d = List.concat [1] [2]\n'
                'let e = List.sort [2, 1]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__choose_and_collect_lower_to_helpers',
        "files": {
            'main.pyfun': (
                'let a = List.choose (fun x -> if x > 1 then Some x else None) [1, 2]\n'
                'let b = List.collect (fun x -> [x, x]) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__input_lowers_name_for_name',
        "files": {
            'main.pyfun': (
                'let name = input "who? "\n'
                'print name'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_input_reads_a_line_from_stdin',
        "files": {
            'main.pyfun': (
                'let name = input "who? "\n'
                'print (String.concat "hi " name)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_choose_and_collect',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [1, 2, 3]\n'
                '        let a = List.choose (fun x -> if x > 1 then Some (x * 10) else None) xs\n'
                '        let b = List.collect (fun x -> [x, x]) xs\n'
                '        let c = List.collect (fun x -> x) [[1], [2, 3]]\n'
                '        let keepOdd = List.choose (fun x -> if x % 2 == 1 then Some x else None)\n'
                '        let d = keepOdd xs\n'
                '        let e = xs |> List.collect (fun x -> [x, 0])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_completeness_ops',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 2]\n'
                '        let a = Option.withDefault 0 (List.get 0 xs)\n'
                '        let b = Option.withDefault 0 (List.get 9 xs)\n'
                '        let c = List.contains 2 xs\n'
                '        let d = List.concat xs [4]\n'
                '        let e = List.sort xs\n'
                '        let f = Option.withDefault 0 (List.find (fun x -> x > 1) xs)\n'
                '        let g = List.isEmpty []\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__modulo_lowers_to_python_percent',
        "files": {
            'main.pyfun': (
                'let r = 10 % 3\n'
                'let even n = n % 2 == 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_modulo',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 10 % 3\n'
                '        let b = 5.5 % 2.0\n'
                '        let c = -7 % 3\n'
                '        let d = (%) 17 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__non_ascii_string_is_not_double_encoded',
        "files": {
            'main.pyfun': 'let s = "café → 🎉"',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_non_ascii_string_length',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = String.len "café"\n'
                '        let m = String.len f"→🎉 {n}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__chained_comparison_lowers_to_native_python_form',
        "files": {
            'main.pyfun': (
                'let f x = 1 < x < 10\n'
                'let g = 1 == 1 == 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_chained_comparisons',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = 1 < 2 < 3\n'
                '        let b = 3 < 2 < 1\n'
                '        let c =\n'
                '            let x = 5\n'
                '            1 < x < 10\n'
                '        let d = 1 <= 1 < 2\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__unary_minus_lowers_with_python_precedence',
        "files": {
            'main.pyfun': (
                'let a = -5\n'
                'let b = 2 * -3\n'
                'let c = -(4 + 1)\n'
                'let d = 0 - -7'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_unary_minus',
        "files": {
            'main.pyfun': (
                '\n'
                '        let a = -5\n'
                '        let b = abs (-5)\n'
                '        let c = 2 * -3\n'
                '        let d = -(4 + 1)\n'
                '        let sign =\n'
                '            match -1:\n'
                '                case -1: "neg"\n'
                '                case _: "other"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_section_in_argument_position_closes_over_its_argument',
        "files": {
            'main.pyfun': (
                'let c xs = xs |> List.map ((+) 2)\n'
                'let a x xs = xs |> List.filter ((==) x)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_bare_operator_is_still_the_binary_lambda',
        "files": {
            'main.pyfun': 'let e xs = xs |> List.fold (+) 0',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_section_argument_that_would_be_captured_keeps_the_wrapper',
        "files": {
            'main.pyfun': 'let shadow b xs = List.map ((+) b) xs',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_non_atomic_section_argument_keeps_the_wrapper',
        "files": {
            'main.pyfun': (
                'extern effect : int -> int = builtins.print\n'
                'let costly xs = List.map ((+) (effect 1)) xs'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_operator_sections',
        "files": {
            'main.pyfun': (
                '\n'
                '        let mul = (*)\n'
                '        let double = (*) 2\n'
                '        let total = List.fold (+) 0 [1, 2, 3, 4]\n'
                '        let cmp = (<) 2 3\n'
                '        let a = mul 3 4\n'
                '        let b = double 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__composition_lowers_to_a_single_argument_lambda',
        "files": {
            'main.pyfun': (
                'let inc x = x + 1\n'
                'let h = inc >> inc'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_function_composition_both_directions',
        "files": {
            'main.pyfun': (
                '\n'
                '        let inc x = x + 1\n'
                '        let double x = x * 2\n'
                '        let ltr = inc >> double\n'
                '        let rtl = inc << double\n'
                '        let a = ltr 3\n'
                '        let b = rtl 3\n'
                '        let piped = 5 |> inc >> double\n'
                '        let mapped = List.map (double >> inc) [1, 2, 3]\n'
                '        let clean = (String.strip >> String.upper) "  hi  "\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__raw_string_re_escapes_backslashes_on_emit',
        "files": {
            'main.pyfun': 'let p = r"C:\\path"',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_raw_string_backslashes_are_literal',
        "files": {
            'main.pyfun': (
                '\n'
                '        let path_len = String.len r"a\\nb"\n'
                '        let quote_len = String.len r"a\\"b"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__triple_quoted_string_emits_an_escaped_single_line_literal',
        "files": {
            'main.pyfun': (
                'let doc = """a\n'
                'b"""'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__triple_quoted_string_emits_an_escaped_single_line_literal_2',
        "files": {
            'main.pyfun': (
                'let x = 1\n'
                'let m = f"""a {x}\n'
                'b"""'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__triple_quoted_string_emits_an_escaped_single_line_literal_3',
        "files": {
            'main.pyfun': (
                'let p = r"""C:\\path\n'
                'next"""'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_triple_quoted_strings',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fstring_is_an_application_argument',
        "files": {
            'main.pyfun': (
                'let x = 5\n'
                'let main = print f"x is {x}"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_interpolation_debug_holes',
        "files": {
            'main.pyfun': (
                '\n'
                '        let x = 3\n'
                '        let y = 4\n'
                '        let a = f"{x=}"\n'
                '        let b = f"{x = }"\n'
                '        let c = f"{x + y=}"\n'
                '        let d = f"{x == y}"\n'
                '        let e = f"{x <= y}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_interpolation_hole_with_nested_string',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = "a}b"\n'
                '        let r = f"contains: {String.contains "}" s}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__target_311_keeps_safe_fstrings',
        "files": {
            'main.pyfun': (
                'let x = 5\n'
                'let r = f"x is {x}"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_target_311_format_rewrite_runs_identically',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = "a}b"\n'
                '        let r = f"contains: {String.contains "}" s}"\n'
                '        let brace = f"lit {{x}} and {String.contains "}" s}"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__string_functions_lower_to_builtins_and_helpers',
        "files": {
            'main.pyfun': (
                'let n = String.len "hi"\n'
                'let up = String.upper "hi"\n'
                'let parts = String.split "," "a,b"\n'
                'let joined = String.join "-" parts\n'
                'let has = String.contains "a" "abc"\n'
                'let s = String.fromInt 7\n'
                'let chars = String.toList "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__string_to_int_lowers_to_a_try_except_and_pulls_in_the_option',
        "files": {
            'main.pyfun': 'let r = String.toInt "42"',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_string_operations',
        "files": {
            'main.pyfun': (
                '\n'
                '        let g = String.concat "Hello, " "World"\n'
                '        let up = String.upper g\n'
                '        let n = String.len g\n'
                '        let parts = String.split ", " g\n'
                '        let joined = String.join "/" parts\n'
                '        let has = String.contains "World" g\n'
                '        let r = String.replace "o" "0" g\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_string_to_int_parses_or_yields_none',
        "files": {
            'main.pyfun': (
                '\n'
                '        let ok = Option.withDefault 0 (String.toInt "41")\n'
                '        let bad = Option.withDefault 0 (String.toInt "nope")\n'
                '        let neg = Option.withDefault 0 (String.toInt "-5")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__unused_collection_helpers_are_not_emitted',
        "files": {
            'main.pyfun': 'let s = Set.empty',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__result_map_lowers_to_a_helper_pulling_in_the_result_prelude',
        "files": {
            'main.pyfun': 'let r = Result.map (fun x -> x) (Ok 1)',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__module_members_lower_to_mangled_top_level_names',
        "files": {
            'main.pyfun': (
                'module Geometry =\n'
                '  let pi = 3\n'
                '  let area r = pi * r * r\n'
                'let big = Geometry.area 10'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__result_to_option_pulls_in_both_preludes',
        "files": {
            'main.pyfun': 'let o = Result.toOption (Ok 1)',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__if_in_value_position_is_a_conditional_expression',
        "files": {
            'main.pyfun': 'let r = if true then 1 else 2',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__exhaustive_match_without_wildcard_keeps_a_runtime_guard',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let f c = match c: case Red: 1 case Green: 2 case Blue: 3'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__adt_lowers_to_frozen_dataclasses',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let x = Has 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__adt_match_args_work_positionally',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let unwrap o =\n'
                '  match o:\n'
                '    case Has v: v\n'
                '    case Empty: 0\n'
                'let r = unwrap (Has 7)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__adt_classes_get_structural_eq',
        "files": {
            'main.pyfun': (
                'type Opt a = Empty | Has a\n'
                'let a = Has 1 == Has 1\n'
                'let b = Has 1 == Has 2'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__adt_classes_get_structural_hash',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let s = Set.ofList [Red, Red, Green]\n'
                'let n = Set.len s\n'
                'let hasRed = Set.contains Red s\n'
                'let hasBlue = Set.contains Blue s'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__adt_classes_get_derived_ordering',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let x = Red < Green'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__ordering_is_emitted_only_when_a_type_is_compared',
        "files": {
            'main.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let x = Red'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__payload_variant_order_key_includes_fields',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Rect float float\n'
                'let c = Circle 1.0 < Rect 0.0 0.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__builtin_option_and_result_get_ordering_but_exception_does_no',
        "files": {
            'main.pyfun': 'let x = Some 1 < Some 2',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': (
            'native__builtin_option_and_result_get_ordering_but_exception_does_no_2'
        ),
        "files": {
            'main.pyfun': 'let x = try (Some 1)',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_sort_a_sum_type_by_variant_order',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Color = Red | Green | Blue\n'
                '        let ordered = List.sort [Blue, Red, Green]\n'
                '        let a = Red < Green\n'
                '        let b = Green < Blue\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_sum_orders_by_variant_then_field',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Shape = Circle float | Rect float float\n'
                '        let a = Circle 1.0 < Circle 2.0\n'
                '        let b = Circle 9.0 < Rect 0.0 0.0\n'
                '        let c = Rect 1.0 2.0 < Rect 1.0 3.0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_sort_records_and_tuples',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let pts = List.sort [Point { x = 2, y = 0 }, Point { x = 1, y = 9 }, Point { x = 1, y = 3 }]\n'
                '        let tups = List.sort [(1, 3), (1, 2), (0, 9)]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_sort_a_recursive_type',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Tree = Leaf int | Node Tree Tree\n'
                '        let ordered = List.sort [Node (Leaf 2) (Leaf 3), Leaf 5, Leaf 1]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__record_lowers_to_frozen_dataclass',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { y = 4, x = 3 }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_compared_record_gets_order_true',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let a = Point { x = 1, y = 2 } < Point { x = 1, y = 3 }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__dataclass_fields_get_python_type_annotations',
        "files": {
            'main.pyfun': (
                'type Opt a = None2 | Has a\n'
                'type Rec = { count: int, ratio: float, label: string, tags: List string, maybe: Opt int }\n'
                'let r = Rec { count = 1, ratio = 2.0, label = "x", tags = [], maybe = None2 }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__record_update_copies_through_a_temp',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = 2 }\n'
                'let q = { p with x = 9 }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__record_field_access_lowers_to_attribute',
        "files": {
            'main.pyfun': (
                'type Point = { x: int }\n'
                'let p = Point { x = 1 }\n'
                'let s = p.x'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__record_pattern_lowers_to_keyword_class_pattern',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let f p = match p: case Point { x = 0, y }: y case Point { x }: x'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__map_traversals_walk_items_once',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "a")]\n'
                'let t = Map.fold (fun acc k v -> acc + k) 0 m'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__map_partition_tests_each_entry_once',
        "files": {
            'main.pyfun': (
                'let m = Map.ofList [(1, "a")]\n'
                'let p = Map.partition (fun k v -> k > 0) m'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__set_operations_use_pythons_own_set_methods',
        "files": {
            'main.pyfun': 'let a = Set.isSubset (Set.ofList [1]) (Set.ofList [1, 2])',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_set_traversals',
        "files": {
            'main.pyfun': (
                '\n'
                '        let s = Set.ofList [3, 1, 4, 1, 5]\n'
                '        let empty = Set.isEmpty (Set.ofList [])\n'
                '        let full = Set.isEmpty s\n'
                '        let halved = List.sort (Set.toList (Set.map (fun x -> x % 2) s))\n'
                '        let kept = List.sort (Set.toList (Set.filter (fun x -> x > 2) s))\n'
                '        let total = Set.fold (fun acc x -> acc + x) 0 s\n'
                '        let any = Set.exists (fun x -> x > 4) s\n'
                '        let all = Set.forall (fun x -> x > 0) s\n'
                '        let sub = Set.isSubset (Set.ofList [1, 3]) s\n'
                '        let sup = Set.isSuperset s (Set.ofList [1, 3])\n'
                '        let biggest = Set.max s\n'
                '        let smallest = Set.min s\n'
                '        let noMax = Set.max (Set.ofList [])\n'
                '        let split = Set.partition (fun x -> x > 2) s\n'
                '        let passing = List.sort (Set.toList (fst split))\n'
                '        let failing = List.sort (Set.toList (snd split))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_map_traversals',
        "files": {
            'main.pyfun': (
                '\n'
                '        let m = Map.ofList [(1, "one"), (2, "two"), (3, "three")]\n'
                '        let empty = Map.isEmpty (Map.ofList [])\n'
                '        let full = Map.isEmpty m\n'
                '        let shouted = Map.toList (Map.map (fun k v -> String.concat v "!") m)\n'
                '        let kept = Map.toList (Map.filter (fun k v -> k > 1) m)\n'
                '        let keySum = Map.fold (fun acc k v -> acc + k) 0 m\n'
                '        let any = Map.exists (fun k v -> v == "two") m\n'
                '        let all = Map.forall (fun k v -> k > 0) m\n'
                '        let joined = Map.toList (Map.union m (Map.ofList [(3, "THREE"), (4, "four")]))\n'
                '        let split = Map.partition (fun k v -> k > 1) m\n'
                '        let passing = Map.toList (fst split)\n'
                '        let failing = Map.toList (snd split)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__string_members_lower_to_pythons_own_str_methods',
        "files": {
            'main.pyfun': (
                'let a = String.trimStart " x"\n'
                'let b = String.splitLines "y"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_string_sweep',
        "files": {
            'main.pyfun': (
                '\n'
                '        let empty = String.isEmpty ""\n'
                '        let full = String.isEmpty "a"\n'
                '        let at = String.get 1 "abc"\n'
                '        let past = String.get 9 "abc"\n'
                '        let thrice = String.repeat 3 "ab"\n'
                '        let none = String.repeat 0 "ab"\n'
                '        let left = String.trimStart "  hi  "\n'
                '        let right = String.trimEnd "  hi  "\n'
                '        let lines = String.splitLines "a\\nb\\nc\\n"\n'
                '        let backwards = String.rev "abc"\n'
                '        let joined = String.ofList ["a", "b", "c"]\n'
                '        let roundTrip = String.ofList (String.toList "xyz")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_deferred_field_reads_the_right_attribute',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Placed = { row: int, col: int, letter: string }\n'
                '        type Cell = { row: int, col: int, letter: string, blank: bool }\n'
                '        let describe c =\n'
                '            let l = c.letter\n'
                '            let flag = c.blank\n'
                '            f"{l}/{flag}"\n'
                '        let out = describe (Cell { row = 1, col = 2, letter = "A", blank = false })\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__sign_lowers_without_a_branch',
        "files": {
            'main.pyfun': 'let s = sign (-5)',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__seq_empty_is_an_exhausted_iterator',
        "files": {
            'main.pyfun': 'let xs = Seq.toList Seq.empty',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_the_audit_members',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [1, 2, 3, 1, 2]\n'
                '        let taken = List.takeWhile (fun x -> x < 3) xs\n'
                '        let dropped = List.dropWhile (fun x -> x < 3) xs\n'
                '        let desc = List.sortByDescending (fun x -> x) xs\n'
                '        let counted = List.countBy (fun x -> x % 2) xs\n'
                '        let uniqBy = Seq.toList (Seq.distinctBy (fun x -> x % 2) (Seq.ofList xs))\n'
                '        let copies = Seq.toList (Seq.replicate 3 "a")\n'
                '        let none = Seq.toList Seq.empty\n'
                '        let at = Seq.get 2 (Seq.ofList xs)\n'
                '        let final = Seq.last (Seq.ofList xs)\n'
                '        let doubled = Seq.sumBy (fun x -> x * 2) (Seq.ofList xs)\n'
                '        let biggest = Seq.max (Seq.ofList xs)\n'
                '        let smallest = Seq.min (Seq.ofList xs)\n'
                '        let joined = Seq.reduce (fun a b -> a + b) (Seq.ofList xs)\n'
                '        let holds = Option.forall (fun x -> x > 0) (Some 1)\n'
                '        let has = Option.contains 1 (Some 1)\n'
                '        let okHas = Result.contains 1 (Ok 1)\n'
                '        let negative = sign (-5)\n'
                '        let zero = sign 0\n'
                '        let positive = sign 42\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__result_map2_reports_the_first_error',
        "files": {
            'main.pyfun': 'let r = Result.map2 (fun a b -> a + b) (Ok 1) (Ok 2)',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_sweep',
        "files": {
            'main.pyfun': (
                '\n'
                '        let some1 = Some 1\n'
                '        let some2 = Some 2\n'
                '        let none = List.head (List.drop 9 [1])\n'
                '        let both = Option.map2 (fun a b -> a + b) some1 some2\n'
                '        let missing = Option.map2 (fun a b -> a + b) some1 none\n'
                '        let kept = Option.orElse some2 some1\n'
                '        let fellBack = Option.orElse some2 none\n'
                '        let flat = Option.flatten (Some (Some 5))\n'
                '        let flatNone = Option.flatten (Some none)\n'
                '        let listed = Option.toList some1\n'
                '        let empty = Option.toList none\n'
                '        let holds = Option.exists (fun x -> x > 0) some1\n'
                '        let holdsNot = Option.exists (fun x -> x > 0) none\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_result_sweep',
        "files": {
            'main.pyfun': (
                '\n'
                '        let ok1 = Ok 1\n'
                '        let ok2 = Ok 2\n'
                '        let bad = Error "boom"\n'
                '        let both = Result.map2 (fun a b -> a + b) ok1 ok2\n'
                '        let failed = Result.map2 (fun a b -> a + b) bad ok2\n'
                '        let kept = Result.orElse ok2 ok1\n'
                '        let fellBack = Result.orElse ok2 bad\n'
                '        let listed = Result.toList ok1\n'
                '        let empty = Result.toList bad\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__seq_lazy_members_route_to_pythons_lazy_machinery',
        "files": {
            'main.pyfun': (
                'let s = Seq.toList (Seq.drop 1 (Seq.takeWhile (fun x -> x < 3) (Seq.ofList [1, 2])))'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__seq_distinct_is_a_generator_not_a_list',
        "files": {
            'main.pyfun': 'let s = Seq.toList (Seq.distinct (Seq.ofList [1, 1]))',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__seq_unfold_yields_until_none',
        "files": {
            'main.pyfun': 'let s = Seq.toList (Seq.take 1 (Seq.unfold (fun n -> Some (n, n)) 0))',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_seq_lazy_members',
        "files": {
            'main.pyfun': (
                '\n'
                '        let dropped = Seq.toList (Seq.drop 2 (Seq.ofList [1, 2, 3, 4]))\n'
                '        let taken = Seq.toList (Seq.takeWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))\n'
                '        let skipped = Seq.toList (Seq.dropWhile (fun x -> x < 3) (Seq.ofList [1, 2, 3, 1]))\n'
                '        let joined = Seq.toList (Seq.concat (Seq.ofList [1, 2]) (Seq.ofList [3]))\n'
                '        let flat = Seq.toList (Seq.flatten (Seq.ofList [Seq.ofList [1, 2], Seq.ofList [3]]))\n'
                '        let mapped = Seq.toList (Seq.collect (fun x -> Seq.ofList [x, x]) (Seq.ofList [1, 2]))\n'
                '        let zipped = Seq.toList (Seq.zip (Seq.ofList [1, 2]) (Seq.ofList ["a", "b"]))\n'
                '        let ix = Seq.toList (Seq.indexed (Seq.ofList ["a", "b"]))\n'
                '        let uniq = Seq.toList (Seq.distinct (Seq.ofList [1, 1, 2, 1, 3]))\n'
                '        let pairs = Seq.toList (Seq.pairwise (Seq.ofList [1, 2, 3]))\n'
                '        let built = Seq.toList (Seq.init 4 (fun i -> i * i))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_seq_can_be_endless',
        "files": {
            'main.pyfun': (
                '\n'
                '        let doubles = Seq.toList (Seq.take 5 (Seq.initInfinite (fun i -> i * 2)))\n'
                '        let powers = Seq.toList (Seq.take 4 (Seq.unfold (fun s -> if s > 100 then None else Some (s, s * 2)) 1))\n'
                '        let firstBig = Seq.find (fun x -> x > 6) (Seq.initInfinite (fun i -> i * 2))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_seq_consuming_members',
        "files": {
            'main.pyfun': (
                '\n'
                '        let first = Seq.head (Seq.ofList [7, 8])\n'
                '        let none = Seq.head (Seq.ofList [])\n'
                '        let empty = Seq.isEmpty (Seq.ofList [])\n'
                '        let full = Seq.isEmpty (Seq.ofList [1])\n'
                '        let n = Seq.len (Seq.ofList [1, 2, 3])\n'
                '        let any = Seq.exists (fun x -> x > 2) (Seq.ofList [1, 2, 3])\n'
                '        let all = Seq.forall (fun x -> x > 0) (Seq.ofList [1, 2, 3])\n'
                '        let has = Seq.contains 2 (Seq.ofList [1, 2, 3])\n'
                '        let total = Seq.sum (Seq.ofList [1, 2, 3])\n'
                '        let found = Seq.find (fun x -> x > 1) (Seq.ofList [1, 2, 3])\n'
                '        let missing = Seq.find (fun x -> x > 9) (Seq.ofList [1, 2, 3])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_slicing_lowers_to_clamped_slices',
        "files": {
            'main.pyfun': (
                'let a = List.take 2 [1, 2, 3]\n'
                'let b = List.drop 2 [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_distinct_lowers_to_the_order_preserving_idiom',
        "files": {
            'main.pyfun': 'let d = List.distinct [1, 1, 2]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_sort_by_passes_a_key_function',
        "files": {
            'main.pyfun': 'let s = List.sortBy (fun x -> 0 - x) [1, 2]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_partition_tests_each_element_once',
        "files": {
            'main.pyfun': 'let p = List.partition (fun x -> x > 1) [1, 2]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fst_and_snd_lower_to_subscripts',
        "files": {
            'main.pyfun': (
                'let a = fst (1, 2)\n'
                'let b = snd (1, 2)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_access_and_slicing',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 4, 1, 5]\n'
                '        let first = List.head xs\n'
                '        let none = List.head (List.drop 9 [1])\n'
                '        let rest = List.tail xs\n'
                '        let taken = List.take 2 xs\n'
                '        let dropped = List.drop 3 xs\n'
                '        let overTake = List.take 99 xs\n'
                '        let negTake = List.take (-1) xs\n'
                '        let split = List.splitAt 2 xs\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_transform_query_and_order',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 4, 1, 5]\n'
                '        let summed = List.map2 (fun a b -> a + b) [1, 2, 3] [10, 20]\n'
                '        let ix = List.indexed ["a", "b"]\n'
                '        let any = List.exists (fun x -> x > 4) xs\n'
                '        let all = List.forall (fun x -> x > 0) xs\n'
                '        let at = List.findIndex (fun x -> x == 4) xs\n'
                '        let missing = List.findIndex (fun x -> x == 99) xs\n'
                '        let desc = List.sortDescending xs\n'
                '        let uniq = List.distinct xs\n'
                '        let grouped = List.groupBy (fun x -> x % 2) [1, 2, 3, 4]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_aggregate_structure_and_windows',
        "files": {
            'main.pyfun': (
                '\n'
                '        let xs = [3, 1, 4, 1, 5]\n'
                '        let biggest = List.max xs\n'
                '        let smallest = List.min xs\n'
                '        let noMax = List.max (List.drop 9 [1])\n'
                '        let doubled = List.sumBy (fun x -> x * 2) [1, 2, 3]\n'
                '        let mean = List.average [1.0, 2.0, 4.0]\n'
                '        let joined = List.reduce (fun a b -> a + b) [1, 2, 3]\n'
                '        let split = List.partition (fun x -> x > 2) xs\n'
                '        let apart = List.unzip (List.zip [1, 2] ["a", "b"])\n'
                '        let flat = List.flatten [[1, 2], [3]]\n'
                '        let squares = List.init 4 (fun i -> i * i)\n'
                '        let copies = List.replicate 3 "x"\n'
                '        let updated = List.updateAt 1 99 [1, 2, 3]\n'
                '        let untouched = List.updateAt 9 99 [1, 2, 3]\n'
                '        let inserted = List.insertAt 1 99 [1, 2, 3]\n'
                '        let removed = List.removeAt 1 [1, 2, 3]\n'
                '        let pairs = List.pairwise [1, 2, 3]\n'
                '        let windows = List.windowed 2 [1, 2, 3]\n'
                '        let chunks = List.chunkBySize 2 [1, 2, 3]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fst_and_snd',
        "files": {
            'main.pyfun': (
                '\n'
                '        let pairs = List.zip [1, 2] ["a", "b"]\n'
                '        let firsts = List.map fst pairs\n'
                '        let seconds = List.map snd pairs\n'
                '        let one = fst (1, "one")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__tuple_literal_lowers_to_python_tuple',
        "files": {
            'main.pyfun': (
                'let pair = (1, 2)\n'
                'let triple = (1, true, 3)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__tuple_pattern_lowers_to_sequence_pattern',
        "files": {
            'main.pyfun': 'let swap p = match p: case (a, b): (b, a)',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_tuple_parameter_unpacks_at_the_top_of_the_body',
        "files": {
            'main.pyfun': 'let tileScore (t, sq) = t * sq',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_nested_tuple_parameter_unpacks_one_level_at_a_time',
        "files": {
            'main.pyfun': 'let nested ((a, b), c) = a + b + c',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_destructuring_lambda_becomes_a_def_not_a_lambda',
        "files": {
            'main.pyfun': (
                'let pairs = List.zip [1, 2] [3, 4]\n'
                '         let total = List.fold (fun acc (a, b) -> acc + a * b) 0 pairs'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_record_parameter_reads_the_fields_it_names',
        "files": {
            'main.pyfun': (
                'type Cell = { row: int, col: int, letter: string }\n'
                '         let describe (Cell { letter, row }) = letter'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_nested_record_parameter_reads_through_a_temp',
        "files": {
            'main.pyfun': (
                'type Cell = { letter: string }\n'
                '         type Pair = { left: Cell, right: Cell }\n'
                '         let leftLetter (Pair { left = Cell { letter } }) = letter'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_record_parameters_round_trip',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Cell = { row: int, col: int, letter: string }\n'
                '        type Pair = { left: Cell, right: Cell }\n'
                '        let describe (Cell { letter, row }) = letter\n'
                '        let leftLetter (Pair { left = Cell { letter } }) = letter\n'
                '        let both (Pair { left, right }) = (left.letter, right.letter)\n'
                '        let a = Cell { row = 1, col = 2, letter = "A" }\n'
                '        let b = Cell { row = 3, col = 4, letter = "B" }\n'
                '        let p = Pair { left = a, right = b }\n'
                '        let one = describe a\n'
                '        let deep = leftLetter p\n'
                '        let pairOf = both p\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_wildcard_parameter_emits_pythons_throwaway_name',
        "files": {
            'main.pyfun': 'let const42 _ = 42',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_tuple_parameters_round_trip',
        "files": {
            'main.pyfun': (
                '\n'
                '        let tileScore (t, sq) = t * sq\n'
                '        let swap (a, b) = (b, a)\n'
                '        let nested ((a, b), c) = a + b + c\n'
                '        let const42 _ = 42\n'
                '        let pairs = List.zip [1, 2, 3] [10, 20, 30]\n'
                '        let scores = List.map tileScore pairs\n'
                '        let total = List.fold (fun acc (a, b) -> acc + a * b) 0 pairs\n'
                '        let swapped = swap (1, 2)\n'
                '        let deep = nested ((1, 2), 3)\n'
                '        let ignored = const42 "anything"\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_tuple_construct_and_destructure',
        "files": {
            'main.pyfun': (
                '\n'
                '        let swap p =\n'
                '          match p:\n'
                '            case (a, b): (b, a)\n'
                '        let fst t =\n'
                '          match t:\n'
                '            case (a, _): a\n'
                '        let pair = (10, 20)\n'
                '        let s = swap pair\n'
                '        let first = fst pair\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_nested_tuple_pattern',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f t =\n'
                '          match t:\n'
                '            case ((a, b), c): a + b + c\n'
                '        let r = f ((1, 2), 3)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__list_pattern_lowers_to_a_bracket_sequence_pattern',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x, *rest]: x'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__wildcard_rest_lowers_to_star_underscore',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [x, *_]: x\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__suffix_star_lowers_to_a_python_mid_star_sequence_pattern',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case []: 0\n'
                '    case [x]: x\n'
                '    case [a, *mid, z]: a + z'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__suffix_star_lowers_to_a_python_mid_star_sequence_pattern_2',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  match xs:\n'
                '    case [*init, last]: last\n'
                '    case []: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_suffix_and_mid_star_patterns',
        "files": {
            'main.pyfun': (
                '\n'
                '        let lastOr fallback xs =\n'
                '          match xs:\n'
                '            case [*_, last]: last\n'
                '            case []: fallback\n'
                '        let bounds xs =\n'
                '          match xs:\n'
                '            case []: 0\n'
                '            case [x]: x\n'
                '            case [first, *mid, last]: first + last + List.len mid\n'
                '        let a = lastOr 0 [5, 6, 7]\n'
                '        let b = lastOr 9 []\n'
                '        let c = bounds [1, 2, 3, 4]\n'
                '        let d = bounds [7]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_sum_with_sequence_patterns',
        "files": {
            'main.pyfun': (
                '\n'
                '        let sum xs =\n'
                '          match xs:\n'
                '            case []: 0\n'
                '            case [x, *rest]: x + sum rest\n'
                '        let total = sum [1, 2, 3, 4]\n'
                '        let empty = sum []\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_fixed_length_and_nested_patterns',
        "files": {
            'main.pyfun': (
                '\n'
                '        let describe xs =\n'
                '          match xs:\n'
                '            case []: 0\n'
                '            case [x]: 1\n'
                '            case [x, y]: 2\n'
                '            case [x, y, *rest]: 3\n'
                '        let head xs =\n'
                '          match xs:\n'
                '            case [Some x, *rest]: x\n'
                '            case _: 0\n'
                '        let a = describe [10, 20, 30]\n'
                '        let b = describe [7]\n'
                '        let c = describe []\n'
                '        let d = head [Some 42, None]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_record_pattern_match',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let classify p =\n'
                '          match p:\n'
                '            case Point { x = 0, y = 0 }: 1\n'
                '            case Point { x = 0 }: 2\n'
                '            case Point { x, y }: x + y\n'
                '        let a = classify (Point { x = 0, y = 0 })\n'
                '        let b = classify (Point { x = 0, y = 9 })\n'
                '        let c = classify (Point { x = 3, y = 4 })\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_nested_record_and_constructor_pattern',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Box = { item: Option int, tag: bool }\n'
                '        let f b =\n'
                '          match b:\n'
                '            case Box { item = Some n, tag = true }: n\n'
                '            case Box { item = Some n }: n + 100\n'
                '            case _: 0\n'
                '        let a = f (Box { item = Some 5, tag = true })\n'
                '        let b = f (Box { item = Some 5, tag = false })\n'
                '        let c = f (Box { item = None, tag = true })\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_deep_exhaustive_match_without_wildcard',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          match o:\n'
                '            case Some true: 1\n'
                '            case Some false: 2\n'
                '            case None: 3\n'
                '        let a = f (Some true)\n'
                '        let b = f (Some false)\n'
                '        let c = f None\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__block_body_lowers_to_statement_sequence',
        "files": {
            'main.pyfun': (
                'let sum3 a b c =\n'
                '    let mut acc = 0\n'
                '    acc <- acc + a\n'
                '    acc <- acc + b\n'
                '    acc'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__top_level_assignment_lowers_to_plain_assign',
        "files": {
            'main.pyfun': (
                'let mut x = 0\n'
                'x <- x + 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__closure_reassigning_a_module_mut_emits_global',
        "files": {
            'main.pyfun': (
                'let counter =\n'
                '  let mut n = 0\n'
                '  let bump x =\n'
                '    n <- n + x\n'
                '    n\n'
                '  bump 5'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__closure_reassigning_an_enclosing_fn_mut_emits_nonlocal',
        "files": {
            'main.pyfun': (
                'let make base =\n'
                '  let mut n = base\n'
                '  let bump x =\n'
                '    n <- n + x\n'
                '    n\n'
                '  bump 5'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__local_only_mut_needs_no_capture_declaration',
        "files": {
            'main.pyfun': (
                'let scaled a b =\n'
                '  let mut acc = a\n'
                '  acc <- acc + b\n'
                '  acc'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_closure_reassigns_captured_mut',
        "files": {
            'main.pyfun': (
                '\n'
                '        let counter =\n'
                '          let mut n = 0\n'
                '          let bump x =\n'
                '            n <- n + x\n'
                '            n\n'
                '          let a = bump 5\n'
                '          bump 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_nonlocal_closure_in_a_function',
        "files": {
            'main.pyfun': (
                '\n'
                '        let make base =\n'
                '          let mut n = base\n'
                '          let bump x =\n'
                '            n <- n + x\n'
                '            n\n'
                '          let a = bump 5\n'
                '          bump 3\n'
                '        let r = make 100\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__nested_local_let_lowers_to_nested_assignments',
        "files": {
            'main.pyfun': (
                'let f x =\n'
                '    let y =\n'
                '        let mut t = x\n'
                '        t <- t + 1\n'
                '        t\n'
                '    y'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__comparison_operators_lower_to_python',
        "files": {
            'main.pyfun': (
                'let a = 1 < 2\n'
                'let b = 1 == 2\n'
                'let c = 1 != 2\n'
                'let d = 1 >= 2'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__boolean_operators_lower_to_python_keywords_with_precedence',
        "files": {
            'main.pyfun': 'let r = true and false',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__boolean_operators_lower_to_python_keywords_with_precedence_2',
        "files": {
            'main.pyfun': 'let r = true or false',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__boolean_operators_lower_to_python_keywords_with_precedence_3',
        "files": {
            'main.pyfun': 'let r = not true',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__boolean_operators_lower_to_python_keywords_with_precedence_4',
        "files": {
            'main.pyfun': 'let r = not 1 == 2',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__boolean_operators_lower_to_python_keywords_with_precedence_5',
        "files": {
            'main.pyfun': 'let r = (not true) == false',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__recursive_call_lowers_to_a_direct_call',
        "files": {
            'main.pyfun': (
                'let fact n =\n'
                '  if n == 0 then 1\n'
                '  else n * fact (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_self_tail_call_becomes_a_loop',
        "files": {
            'main.pyfun': (
                'let countdown n =\n'
                '  if n == 0 then "done"\n'
                '  else countdown (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__several_parameters_rebind_simultaneously',
        "files": {
            'main.pyfun': (
                'let sumTo n acc =\n'
                '  if n == 0 then acc\n'
                '  else sumTo (n - 1) (acc + n)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_tail_call_in_a_match_arm_becomes_a_loop',
        "files": {
            'main.pyfun': (
                'let classify n =\n'
                '  match n:\n'
                '    case 0: "zero"\n'
                '    case _: classify (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_non_tail_self_call_is_left_recursive',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  if n == 0 then 0\n'
                '  else 1 + f (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__mutual_recursion_is_left_alone',
        "files": {
            'main.pyfun': (
                '\n'
                '        let evens n =\n'
                '          if n == 0 then true\n'
                '          else odds (n - 1)\n'
                '        let odds n =\n'
                '          if n == 0 then false\n'
                '          else evens (n - 1)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_closure_over_a_parameter_blocks_the_loop',
        "files": {
            'main.pyfun': (
                '\n'
                '        let collect n acc =\n'
                '          if n == 0 then acc\n'
                '          else collect (n - 1) (List.concat acc [fun k -> n])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_shadowing_lambda_parameter_does_not_block_the_loop',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f n =\n'
                '          if n == 0 then 0\n'
                '          else\n'
                '            let doubled = List.map (fun n -> n + 1) [1, 2]\n'
                '            f (n - 1)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_looped_self_tail_call_says_nothing',
        "files": {
            'main.pyfun': (
                'let f n =\n'
                '  if n == 0 then 0\n'
                '  else f (n - 1)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__an_async_self_tail_call_becomes_a_loop_in_the_coroutine',
        "files": {
            'main.pyfun': (
                'let finished acc = async { return acc }\n'
                'let loop n acc =\n'
                '  async {\n'
                '    return! (if n == 0 then finished acc else loop (n - 1) (acc + n))\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_return_bang_match_returns_per_arm',
        "files": {
            'main.pyfun': (
                'type Msg = Go int | Stop\n'
                'let finished n = async { return n }\n'
                'let loop n =\n'
                '  async {\n'
                '    return! (match n:\n'
                '      case Go k: loop Stop\n'
                '      case Stop: finished 0)\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_rejected_async_self_tail_call_says_why',
        "files": {
            'main.pyfun': (
                'let finished acc = async { return acc }\n'
                'let collect n acc =\n'
                '  async {\n'
                '    return! (if n == 0 then finished acc else collect (n - 1) (List.concat acc [fun k -> n]))\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_lowers_user_sum_type_matches_to_isinstance_ladders',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_compiles_nested_tuple_record_literal_and_as_patterns',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_lowers_or_and_list_patterns_too',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_joins_a_nested_or_pattern_with_or',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_annotates_top_level_functions_it_can_spell',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_annotates_module_level_values_for_other_modules',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_evaluates_a_discarded_match_in_place',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_annotates_block_local_functions_and_leaves_unit_retur',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_ladders_reach_async_return_bang_matches',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_leaves_active_patterns_to_their_own_lowering',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_spells_out_the_comparisons_of_an_ordered_sum_type',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__native_annotates_an_async_tail_call_that_needs_no_nonlocal',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_async_callback_handed_to_python_runs',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_async_self_tail_call_recurses_past_the_stack_limit',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_empty_race_raises_the_named_error',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_mut_assigned_in_an_async_block_declares_global',
        "files": {
            'main.pyfun': (
                'let mut flag = false\n'
                'let raiseFlag _ =\n'
                '  async {\n'
                '    flag <- true\n'
                '    return ()\n'
                '  }'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_mut_assigned_in_a_result_block_declares_global',
        "files": {
            'main.pyfun': (
                'let mut attempts = 0\n'
                'let step x = result {\n'
                '  attempts <- attempts + 1\n'
                '  return x + 1\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_function_mut_assigned_in_an_async_block_declares_nonlocal',
        "files": {
            'main.pyfun': (
                'extern import asyncio\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let bump _ =\n'
                '  let mut n = 0\n'
                '  let work = async {\n'
                '    n <- n + 1\n'
                '    return ()\n'
                '  }\n'
                '  runAsync work\n'
                '  n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_mut_assigned_in_an_async_block_reaches_the_module_bind',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_mut_assigned_in_a_seq_block_reaches_the_module_binding',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_self_tail_call_recurses_past_the_stack_limit',
        "files": {
            'main.pyfun': (
                '\n'
                '        let countdown n =\n'
                '          if n == 0 then "done"\n'
                '          else countdown (n - 1)\n'
                '        let sumTo n acc =\n'
                '          if n == 0 then acc\n'
                '          else sumTo (n - 1) (acc + n)\n'
                '        let deep = countdown 50000\n'
                '        let total = sumTo 100000 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_closure_over_a_parameter_keeps_per_frame_values',
        "files": {
            'main.pyfun': (
                '\n'
                '        let collect n acc =\n'
                '          if n == 0 then acc\n'
                '          else collect (n - 1) (List.concat acc [fun k -> n])\n'
                '        let fns = collect 3 []\n'
                '        let values = List.map (fun f -> f 0) fns\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_recursive_functions',
        "files": {
            'main.pyfun': (
                '\n'
                '        let fact n =\n'
                '          if n == 0 then 1\n'
                '          else n * fact (n - 1)\n'
                '        let fib n =\n'
                '          if n < 2 then n\n'
                '          else fib (n - 1) + fib (n - 2)\n'
                '        let a = fact 6\n'
                '        let b = fib 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_currying_full_partial_and_over_application',
        "files": {
            'main.pyfun': (
                '\n'
                '        let add a b = a + b\n'
                '        let inc = add 1\n'
                '        let twice f x = f (f x)\n'
                '        let r1 = add 1 2\n'
                '        let r2 = inc 41\n'
                '        let r3 = twice inc 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_pipe_and_composition',
        "files": {
            'main.pyfun': (
                '\n'
                '        let add a b = a + b\n'
                '        let inc = add 1\n'
                '        let compose = fun f g x -> f (g x)\n'
                '        let r = 4 |> inc |> inc\n'
                '        let r2 = (compose inc inc) 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__backward_pipe_lowers_to_application',
        "files": {
            'main.pyfun': (
                'let inc n = n + 1\n'
                'let a = inc <| 5\n'
                'let b = inc <| inc <| 5'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_backward_pipe',
        "files": {
            'main.pyfun': (
                '\n'
                '        let inc n = n + 1\n'
                '        let twice n = n * 2\n'
                '        let a = inc <| 5\n'
                '        let b = inc <| twice <| 5\n'
                '        let c = twice <| inc 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_elif_chain_selects_the_right_branch',
        "files": {
            'main.pyfun': (
                '\n'
                '        let grade n =\n'
                '          if n >= 90 then "A"\n'
                '          elif n >= 80 then "B"\n'
                '          elif n >= 70 then "C"\n'
                '          else "F"\n'
                '        let a = grade 95\n'
                '        let b = grade 85\n'
                '        let c = grade 72\n'
                '        let f = grade 50\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_if_and_match',
        "files": {
            'main.pyfun': (
                '\n'
                '        let classify n =\n'
                '          match n:\n'
                '            case 0: "zero"\n'
                '            case 1: "one"\n'
                '            case _: "many"\n'
                '        let r1 = classify 0\n'
                '        let r2 = classify 7\n'
                '        let r3 = if true then 10 else 20\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_blocks_in_match_arms_and_if_branches',
        "files": {
            'main.pyfun': (
                '\n'
                '        let classify n =\n'
                '          match n:\n'
                '            case 0:\n'
                '              let base = 100\n'
                '              base\n'
                '            case _:\n'
                '              let mut acc = n\n'
                '              acc <- acc * 2\n'
                '              acc\n'
                '        let absdiff a b =\n'
                '          if a > b then\n'
                '              let d = a - b\n'
                '              d\n'
                '          else\n'
                '              let d = b - a\n'
                '              d\n'
                '        let r1 = classify 0\n'
                '        let r2 = classify 5\n'
                '        let r3 = absdiff 3 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_block_in_lambda_body',
        "files": {
            'main.pyfun': (
                '\n'
                '        let doubler = fun x ->\n'
                '          let y = x + x\n'
                '          y\n'
                '        let r = doubler 21\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_division_operators_match_python',
        "files": {
            'main.pyfun': 'let q = 7 / 2',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_division_operators_match_python_2',
        "files": {
            'main.pyfun': 'let d = 7 // 2',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_match_in_value_position_is_hoisted',
        "files": {
            'main.pyfun': 'let r = (match 1: case 1: 10 case _: 20) + 5',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_adt_construction_and_match',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Color = Red | Green | Blue\n'
                '        let unwrap o = match o: case Some v: v case None: 0\n'
                '        let r1 = unwrap (Some 5)\n'
                '        let r2 = unwrap None\n'
                '        let rank c = match c: case Red: 1 case Green: 2 case Blue: 3\n'
                '        let r3 = rank Green\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_records_construct_access_and_update',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let p = Point { x = 3, y = 4 }\n'
                '        let moved = { p with x = 10 }\n'
                '        let sx = p.x\n'
                '        let sy = moved.y\n'
                '        let mx = moved.x\n'
                '        let sumxy r = r.x + r.y\n'
                '        let total = sumxy p\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_nested_record_update',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Inner = { a: int, b: int }\n'
                '        type Outer = { inner: Inner, tag: string }\n'
                '        let o = Outer { inner = Inner { a = 1, b = 2 }, tag = "x" }\n'
                '        let o2 = { o with inner.a = 99 }\n'
                '        let both = { o with inner.a = 10, tag = "y" }\n'
                '        let na = o2.inner.a\n'
                '        let nb = o2.inner.b\n'
                '        let nt = o2.tag\n'
                '        let ba = both.inner.a\n'
                '        let bt = both.tag\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_polymorphic_record_field',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Box a = { item: a }\n'
                '        let mk v = Box { item = v }\n'
                '        let i = (mk 42).item\n'
                '        let s = (mk "hi").item\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_blocks_and_mutation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let sum3 a b c =\n'
                '            let mut acc = 0\n'
                '            acc <- acc + a\n'
                '            acc <- acc + b\n'
                '            acc <- acc + c\n'
                '            acc\n'
                '        let nested x =\n'
                '            let y =\n'
                '                let mut t = x\n'
                '                t <- t * 2\n'
                '                t\n'
                '            y + 1\n'
                '        let r1 = sum3 1 2 3\n'
                '        let r2 = nested 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_top_level_mutation',
        "files": {
            'main.pyfun': (
                '\n'
                '        let mut counter = 0\n'
                '        counter <- counter + 1\n'
                '        counter <- counter + 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_recursive_adt',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Lst a = Nil | Cons a (Lst a)\n'
                '        let head d xs = match xs: case Nil: d case Cons h t: h\n'
                '        let r = head 0 (Cons 7 (Cons 8 Nil))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__units_are_erased_in_emitted_python',
        "files": {
            'main.pyfun': (
                'measure m\n'
                'measure s\n'
                'let speed = 100<m> / 10<s>'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_units_compute_after_erasure',
        "files": {
            'main.pyfun': (
                '\n'
                '        measure m\n'
                '        measure s\n'
                '        let dist = 100<m>\n'
                '        let time = 10<s>\n'
                '        let speed = dist / time\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_derived_measure_aliases_erase',
        "files": {
            'main.pyfun': (
                '\n'
                '        measure kg\n'
                '        measure m\n'
                '        measure s\n'
                '        measure N = kg m / s^2\n'
                '        measure Pa = N / m^2\n'
                '        let force = 10<N>\n'
                '        let area = 2<m^2>\n'
                '        let pressure = force / area\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_result_ce_binds_and_short_circuits',
        "files": {
            'main.pyfun': (
                '\n'
                '        let safe ok v = result { let! x = if ok then Ok v else Error 9  return (x + 1) }\n'
                '        let unwrap r = match r: case Ok n: n case Error e: e\n'
                '        let r1 = unwrap (safe true 10)\n'
                '        let r2 = unwrap (safe false 10)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_expression_items_and_a_trailing_do_bang_in_an_async_bloc',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_trailing_do_bang_in_a_result_block_is_forwarded',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_async_module_members_run_over_asyncio',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_thunk_argument_to_an_extern_is_wrapped_for_python',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_for_items_in_seq_async_result_and_a_user_builder',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_derived_codecs_round_trip_a_rich_type',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_derived_codecs_read_through_a_newtype_and_a_keyword_fiel',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_format_module_formats_numbers_and_strings',
        "files": {
            'main.pyfun': (
                'let a = Format.fixed 2 3.14159\n'
                'let b = Format.thousands 2 1234567.5\n'
                'let c = Format.percent 1 0.256\n'
                'let d = Format.currency "$" 2 1234.5\n'
                'let e = Format.grouped 1234567\n'
                'let f = Format.padLeft 6 "0" "42"\n'
                'let g = Format.padRight 6 "." "42"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_user_monad_ce_binds_and_short_circuits',
        "files": {
            'main.pyfun': (
                '\n'
                '        module Maybe =\n'
                '          let bind m f = match m: case Some x: f x case None: None\n'
                '          let return_ x = Some x\n'
                '        let safe a b =\n'
                '          Maybe {\n'
                '            let! x = a\n'
                '            let! y = b\n'
                '            return x + y\n'
                '          }\n'
                '        let unwrap m = match m: case Some n: n case None: 0\n'
                '        let r1 = unwrap (safe (Some 3) (Some 4))\n'
                '        let r2 = unwrap (safe (Some 3) None)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_user_yield_ce_combines_via_delay',
        "files": {
            'main.pyfun': (
                '\n'
                '        module Sum =\n'
                '          let yield_ x = x\n'
                '          let combine a b = a + b\n'
                '          let delay f = f 0\n'
                '        let total =\n'
                '          Sum {\n'
                '            yield 1\n'
                '            yield 2\n'
                '            yield 3\n'
                '            yield 4\n'
                '          }\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__user_ce_lowers_to_plain_calls',
        "files": {
            'main.pyfun': (
                '\n'
                '        module M =\n'
                '          let bind m f = f m\n'
                '          let return_ x = x\n'
                '        let r = M { let! x = 3  return x }\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_prelude_print_and_numerics',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_comparison_and_structural_equality',
        "files": {
            'main.pyfun': (
                'print (1 < 2)\n'
                'print ("a" < "b")\n'
                'print (3 == 3)\n'
                'print (Some 1 == Some 1)\n'
                'print (Some 1 == Some 2)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_boolean_logic',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_extern_calls_python',
        "files": {
            'main.pyfun': (
                'extern show: a -> string = str\n'
                'extern ord: string -> int\n'
                'extern pure tan: float -> float = math.tan\n'
                'let label = show 42\n'
                'let code = ord "A"\n'
                'let root = tan 0.0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_extern_import_calls_python',
        "files": {
            'main.pyfun': (
                'extern import datetime\n'
                'extern parse: string -> a = datetime.datetime.fromisoformat\n'
                'let d = parse "2020-01-02"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_list_functions',
        "files": {
            'main.pyfun': (
                'let xs = [1, 2, 3, 4]\n'
                'let doubled = List.map (fun x -> x * 2) xs\n'
                'let small = List.filter (fun x -> x < 3) xs\n'
                'let total = List.fold (fun a b -> a + b) 0 xs\n'
                'let n = List.len xs\n'
                'let s = List.sum xs\n'
                'let r = List.rev xs\n'
                'let q = List.range 1 4'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_set_functions',
        "files": {
            'main.pyfun': (
                'let s = Set.ofList [1, 2, 3, 3]\n'
                'let n = Set.len s\n'
                'let has = Set.contains 2 s\n'
                'let u = Set.len (Set.union s (Set.ofList [3, 4]))\n'
                'let i = Set.len (Set.intersect s (Set.ofList [3, 4]))\n'
                'let d = Set.len (Set.difference s (Set.ofList [3, 4]))\n'
                'let e = Set.len Set.empty'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__int_literal_unified_to_float_lowers_to_a_float_literal',
        "files": {
            'main.pyfun': (
                'let xs = [1.0, 2, 3.0]\n'
                'let pick b = if b then 1 else 1.5'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__int_literal_unified_to_float_lowers_to_a_float_literal_2',
        "files": {
            'main.pyfun': (
                'let n = 7\n'
                'let m = n + 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_int_literal_unified_to_float_prints_as_float',
        "files": {
            'main.pyfun': (
                'let xs = [1.0, 2, 3.0]\n'
                'let pick b = if b then 1 else 1.5\n'
                'let r = pick true'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_combinators',
        "files": {
            'main.pyfun': (
                'let sub a b = a - b\n'
                'let i = id 42\n'
                'let k = const 7 "ignored"\n'
                'let f = flip sub 3 10\n'
                'let mapped = List.map (const 0) [1, 2, 3]\n'
                'let identity = List.map id [4, 5, 6]\n'
                'let flipped = List.map (flip sub 100) [1, 2]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_map_functions',
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
                'let miss = Option.withDefault 0 (Map.tryFind "z" m)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_adts_and_records_as_keys_and_elements',
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
                'let npts = Set.len pts'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_seq_module_is_lazy',
        "files": {
            'main.pyfun': (
                'let nats = Seq.range 0 1000000\n'
                'let squares = Seq.toList (Seq.take 5 (Seq.map (fun x -> x * x) nats))\n'
                'let evens = Seq.toList (Seq.take 3 (Seq.filter (fun x -> x // 2 * 2 == x) nats))\n'
                'let total = Seq.fold (fun acc x -> acc + x) 0 (Seq.ofList [1, 2, 3, 4])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_in_file_module',
        "files": {
            'main.pyfun': (
                'module Geometry =\n'
                '  let pi = 3\n'
                '  let area r = pi * r * r\n'
                '  let double a = area a + area a\n'
                'let a = Geometry.area 10\n'
                'let d = Geometry.double 2\n'
                'let p = Geometry.pi'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_result_module',
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
                'let g = Result.isError (Result.mapError (fun s -> s) r2)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_module',
        "files": {
            'main.pyfun': (
                'let some = Some 5\n'
                'let none = None\n'
                'let a = Option.withDefault 0 some\n'
                'let b = Option.withDefault 0 none\n'
                'let c = Option.isSome some\n'
                'let d = Option.isNone none\n'
                'let e = Option.map (fun x -> x + 1) some'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__active_pattern_match_lowers_to_an_if_elif_chain',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even: "e"\n'
                '    case Odd: "o"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__bool_partial_lowers_to_a_truthiness_test',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank: 1\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__distinct_parameterized_applications_hoist_separately',
        "files": {
            'main.pyfun': (
                'let (|DivisibleBy|_|) d n = n % d == 0\n'
                'let f n =\n'
                '  match n:\n'
                '    case DivisibleBy 3: 1\n'
                '    case DivisibleBy 5: 2\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_guarded_active_pattern_falls_through',
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
                'let c = describe 7'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_guarded_active_pattern_in_value_position',
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
                'let c = classify 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_total_active_pattern',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"\n'
                'let a = f 4\n'
                'let b = f 7'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_total_active_pattern_with_fields',
        "files": {
            'main.pyfun': (
                'let (|Small|Big|) n = if n < 10 then Small n else Big (n - 10)\n'
                'let f n =\n'
                '  match n:\n'
                '    case Small s: s\n'
                '    case Big b: b\n'
                'let a = f 7\n'
                'let b = f 25'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_partial_active_pattern',
        "files": {
            'main.pyfun': (
                'let (|Positive|_|) n = if n > 0 then Some n else None\n'
                'let f n =\n'
                '  match n:\n'
                '    case Positive p: p\n'
                '    case _: 0\n'
                'let a = f 7\n'
                'let b = f (-3)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_bool_partial_active_pattern',
        "files": {
            'main.pyfun': (
                'let (|Blank|_|) s = String.strip s == ""\n'
                'let f s =\n'
                '  match s:\n'
                '    case Blank: "empty"\n'
                '    case _: "text"\n'
                'let a = f "   "\n'
                'let b = f "hi"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_parameterized_active_pattern_fizzbuzz',
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
                'let d = fizz 7'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_active_pattern_side_effects_run_once_per_match',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_active_pattern_match_in_value_position',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let r =\n'
                '  match 6:\n'
                '    case Even: "even"\n'
                '    case Odd: "odd"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__or_pattern_arm_lowers_to_an_or_of_isinstance_tests',
        "files": {
            'main.pyfun': (
                'let (|Even|Odd|) n = if n % 2 == 0 then Even else Odd\n'
                'let f n =\n'
                '  match n:\n'
                '    case Even | Odd: "eo"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__structural_arm_lowers_to_a_one_armed_native_match',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let f o =\n'
                '  match o:\n'
                '    case Answer: 1\n'
                '    case Some x: x\n'
                '    case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__structural_arm_beside_active_pattern_in_value_position',
        "files": {
            'main.pyfun': (
                'let (|Answer|_|) o = o == Some 42\n'
                'let classify o =\n'
                '  let label =\n'
                '    match o:\n'
                '      case Answer: "answer"\n'
                '      case Some n: String.fromInt n\n'
                '      case None: "none"\n'
                '  String.concat label "!"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_active_and_or_and_structural_arms_mix',
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
                'let d = describe None'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_primitives_and_totality',
        "files": {
            'main.pyfun': (
                'let ok = Result.withDefault 0 (Decode.decodeString Decode.int "42")\n'
                'let wrongType = Result.withDefault (0 - 1) (Decode.decodeString Decode.int "\\"x\\"")\n'
                'let boolNotInt = Result.withDefault (0 - 1) (Decode.decodeString Decode.int "true")\n'
                'let intAsFloat = Result.withDefault 0.0 (Decode.decodeString Decode.float "3")\n'
                'let malformed = Result.isError (Decode.decodeString Decode.bool "not json")'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_record_via_map_and_field',
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
                'let missing = Result.isError (Decode.decodeString dec """{"name": "bob"}""")'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_list_nullable_oneof_andthen',
        "files": {
            'main.pyfun': (
                'let nums = Result.withDefault [] (Decode.decodeString (Decode.list Decode.int) "[1, 2, 3]")\n'
                'let flex = Decode.oneOf [Decode.string, Decode.map String.fromInt Decode.int]\n'
                'let fromStr = Result.withDefault "?" (Decode.decodeString flex "\\"hi\\"")\n'
                'let fromInt = Result.withDefault "?" (Decode.decodeString flex "7")\n'
                'let n = Result.withDefault (0 - 1) (Decode.decodeString (Decode.oneOf []) "1")'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__decode_pipeline_is_pure',
        "files": {
            'main.pyfun': (
                'let pure parse s = Decode.decodeString Decode.int s\n'
                'let r = parse "1"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__decode_spec_fires_on_inline_field',
        "files": {
            'main.pyfun': (
                'let r = Decode.decodeString (Decode.field "name" Decode.string) """{"name": "ada"}"""\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__decode_spec_fires_through_named_decoder',
        "files": {
            'main.pyfun': (
                'type Pair = { name: string, age: int }\n'
                'let user =\n'
                '  Decode.map2 (fun name age -> Pair { name = name, age = age })\n'
                '    (Decode.field "name" Decode.string)\n'
                '    (Decode.field "age" Decode.int)\n'
                'let r = Decode.decodeString user """{"name": "ada", "age": 36}"""\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_success_and_missing_field',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let good = show (Decode.decodeString (Decode.field "name" Decode.string) """{"name": "ada"}""")\n'
                'let missing = show (Decode.decodeString (Decode.field "name" Decode.string) """{"other": 1}""")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_wrong_type',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let wrong = show (Decode.decodeString (Decode.field "age" Decode.int) """{"age": "old"}""")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_int_bool_float_strictness',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let boolNotInt = show (Decode.decodeString Decode.int "true")\n'
                'let intAsFloat = show (Decode.decodeString Decode.float "5")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_malformed_json_kind',
        "files": {
            'main.pyfun': (
                'let kind r =\n'
                '  match r:\n'
                '    case Ok v: "ok"\n'
                '    case Error e: e.errorKind\n'
                'let malformed = kind (Decode.decodeString Decode.bool "not json")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_nullable',
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
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_oneof_first_match_and_all_fail',
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
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_list_of_objects_via_named_decoder',
        "files": {
            'main.pyfun': (
                'let idDec = Decode.field "id" Decode.int\n'
                'let show r =\n'
                '  match r:\n'
                '    case Ok xs: f"sum: {List.sum xs}"\n'
                '    case Error e: e.errorKind\n'
                'let total = show (Decode.decodeString (Decode.list idDec) """[{"id": 1}, {"id": 2}]""")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_decode_spec_succeed_and_fail',
        "files": {
            'main.pyfun': (
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: f"{e.errorKind}: {e.errorMessage}"\n'
                'let s = show (Decode.decodeString (Decode.succeed 42) "0")\n'
                'let failed = show (Decode.decodeString (Decode.fail "boom") "0")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__decode_andthen_falls_back',
        "files": {
            'main.pyfun': (
                'let dec = Decode.andThen (fun n -> Decode.succeed (n + 1)) Decode.int\n'
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: e.errorKind\n'
                'let out = show (Decode.decodeString dec "41")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__decode_parameter_decoder_falls_back',
        "files": {
            'main.pyfun': (
                'let runWith d s = Decode.decodeString d s\n'
                'let show r =\n'
                '  match r:\n'
                '    case Ok v: f"ok: {v}"\n'
                '    case Error e: e.errorKind\n'
                'let out = show (runWith Decode.int "7")\n'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__decode_shadowed_free_var_falls_back',
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
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_trailing_unit_expression_ends_result_and_option_blocks',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__top_level_block_shadow_does_not_clobber_a_definition',
        "files": {
            'main.pyfun': (
                'let bump n = n + 100\n'
                'let useBump x = bump x\n'
                'let useIt =\n'
                '  let bump = 0\n'
                '  useBump 5\n'
                'let after = useBump 7'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__top_level_match_binder_shadow_does_not_clobber',
        "files": {
            'main.pyfun': (
                'let bump n = n + 100\n'
                'let useIt =\n'
                '  match Some 0:\n'
                '    case Some bump: bump\n'
                '    case None: 1\n'
                'let after = bump 7'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__top_level_block_without_collision_stays_unwrapped',
        "files": {
            'main.pyfun': (
                'let a =\n'
                '  let t = 1\n'
                '  t + 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_opt_tuple_named_folder_lowers_to_loop',
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
                'let run cmds = List.fold step (Map.empty, []) cmds'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fold_opt_tuple_named_folder',
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
                'let out = match run [Put 1 10, Push 2, Skip, Put 3 30, Push 4]: case (m, xs): (Map.toList m, xs)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_opt_single_map_lambda_lowers_to_subscript_assign',
        "files": {
            'main.pyfun': (
                'let m = List.fold (fun m x -> Map.add x (x * 2) m) Map.empty [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fold_opt_single_map_lambda',
        "files": {
            'main.pyfun': (
                'let m = List.fold (fun m x -> Map.add x (x * 2) m) Map.empty [1, 2, 3]\n'
                'let out = Map.toList m'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_top_level_fold_keeps_its_loop_names_off_top_level_bindings',
        "files": {
            'main.pyfun': (
                'let x = 100\n'
                'let total = List.fold (fun acc e -> List.concat acc [e]) [] [1, 2, 3]\n'
                'let doubled = List.fold (fun acc x -> List.concat acc [x * 2]) [] [1, 2, 3]\n'
                'let out = (x, doubled, total)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_fold_inside_an_in_file_module_lowers_to_a_loop',
        "files": {
            'main.pyfun': (
                'module Stats =\n'
                '  let scale = 3\n'
                '  let tally xs = List.fold (fun acc x -> Map.add x (x * scale) acc) Map.empty xs\n'
                'let out = Map.toList (Stats.tally [1, 2])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_opt_cross_slot_read_is_hoisted_before_mutation',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, log): (Map.add x x m, List.concat log [Map.len m])\n'
                'let r = List.fold step (Map.empty, []) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fold_opt_cross_slot_read',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, log): (Map.add x x m, List.concat log [Map.len m])\n'
                'let r = List.fold step (Map.empty, []) [1, 2, 3]\n'
                'let out = match r: case (m, log): (Map.toList m, log)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_opt_extend_form',
        "files": {
            'main.pyfun': 'let acc = List.fold (fun acc x -> List.concat acc [x, x]) [] [1, 2]',
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fold_opt_extend_form',
        "files": {
            'main.pyfun': (
                'let acc = List.fold (fun acc x -> List.concat acc [x, x]) [] [1, 2]\n'
                'let out = acc'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fold_opt_seq_fold_and_piped_form',
        "files": {
            'main.pyfun': (
                'let s = Seq.fold (fun m x -> Map.add x x m) Map.empty (Seq.range 0 3)\n'
                'let p = [1, 2, 3] |> List.fold (fun a x -> List.concat a [x]) []\n'
                'let so = Map.toList s'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_opt_nonatomic_key_is_hoisted',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add (x + 1) x m\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_named_init_binding_gets_a_defensive_copy',
        "files": {
            'main.pyfun': (
                'let seed = Map.empty\n'
                'let grown = List.fold (fun m x -> Map.add x x m) seed [1, 2]\n'
                'let a = Map.len seed\n'
                'let b = Map.len grown'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_component_stored_into_other_slot',
        "files": {
            'main.pyfun': (
                'let g acc x =\n'
                '  match acc:\n'
                '    case (names, log): (Map.add x x names, List.concat log [names])\n'
                'let out = match List.fold g (Map.empty, []) [1, 2]: case (m, log): (Map.len m, List.map Map.len log)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_swapped_slots',
        "files": {
            'main.pyfun': (
                'let h acc x = match acc: case (a, b): (b, a)\n'
                'let out = List.fold h (0, 100) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_same_slot_twice',
        "files": {
            'main.pyfun': (
                'let dup acc x = match acc: case (m, n): (Map.add x x m, m)\n'
                'let out = match List.fold dup (Map.empty, Map.empty) [1, 2]: case (a, b): (Map.toList a, Map.toList b)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_closure_capture',
        "files": {
            'main.pyfun': (
                'let cap acc x =\n'
                '  match acc:\n'
                '    case (m, fs): (Map.add x x m, List.concat fs [fun u -> Map.len m])\n'
                'let out = match List.fold cap (Map.empty, []) [1, 2]: case (m, fs): List.map (fun f -> f 0) fs'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_acc_escapes_to_user_function',
        "files": {
            'main.pyfun': (
                'let ins x acc = List.concat [x] acc\n'
                'let rev xs = List.fold (fun acc x -> ins x acc) [] xs\n'
                'let out = rev [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_acc_in_nontail_nonwhitelisted_position',
        "files": {
            'main.pyfun': (
                'let k acc x = if List.contains acc [[]] then acc else List.concat acc [x]\n'
                'let out = List.fold k [] [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_fresh_reset_slot',
        "files": {
            'main.pyfun': (
                'let rf acc x = match acc: case (m, n): if x == 0 then (Map.empty, n) else (Map.add x x m, n)\n'
                'let out = match List.fold rf (Map.empty, 0) [0, 1, 2]: case (m, n): (Map.toList m, n)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_free_var_capture_at_site',
        "files": {
            'main.pyfun': (
                'let base = 10\n'
                'let addb acc x = List.concat acc [x + base]\n'
                'let usefn n =\n'
                '  let base = 99\n'
                '  List.fold addb [] [1]\n'
                'let out = usefn 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_wildcard_slot',
        "files": {
            'main.pyfun': (
                'let w acc x = match acc: case (m, _): (Map.add x x m, Map.empty)\n'
                'let out = match List.fold w (Map.empty, Map.empty) [1, 2]: case (a, b): (Map.toList a, Map.toList b)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_a_named_folder_inside_an_in_file_module',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add x x m\n'
                'module M =\n'
                '  let scan xs = List.fold step Map.empty xs\n'
                'let r = Map.len (M.scan [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_partial_application',
        "files": {
            'main.pyfun': (
                'let f a b = a + b\n'
                'let g = List.fold f\n'
                'let out = g 0 [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_folder_is_a_parameter',
        "files": {
            'main.pyfun': (
                'let foldWith f = List.fold f Map.empty [1, 2, 3]\n'
                'let out = Map.len (foldWith (fun m x -> Map.add x x m))'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_local_named_folder_block_lowers_to_loop',
        "files": {
            'main.pyfun': (
                'let build xs =\n'
                '  let step acc x = Map.add x (x * 2) acc\n'
                '  List.fold step Map.empty xs\n'
                'let out = Map.toList (build [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_local_named_folder_dedup_shape_lowers_to_loop',
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
                'let out = List.map (fun l -> l.depMin) (dedupLegs [Leg { depMin = 1, dest = "a" }, Leg { depMin = 1, dest = "a" }, Leg { depMin = 2, dest = "b" }])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_shadow_rebound_local_folder_uses_newest_body',
        "files": {
            'main.pyfun': (
                'let build xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  let step acc x = List.concat acc [x * 2]\n'
                '  List.fold step [] xs\n'
                'let out = build [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_shadow_lambda_param_uses_parameter',
        "files": {
            'main.pyfun': (
                'let build combiner xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  (fun step -> List.fold step [] xs) combiner\n'
                'let out = build (fun acc x -> List.concat acc [x * 2]) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_shadow_match_binder_uses_binding',
        "files": {
            'main.pyfun': (
                'let build sel xs =\n'
                '  let step acc x = List.concat acc [x + 100]\n'
                '  match sel:\n'
                '    case Some step: List.fold step [] xs\n'
                '    case None: []\n'
                'let out = build (Some (fun acc x -> List.concat acc [x * 2])) [1, 2, 3]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_chained_map_add_updates_one_slot_inner_first',
        "files": {
            'main.pyfun': (
                'let step m x = Map.add (x * 10) x (Map.add x x m)\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reset_store_batching_idiom',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (cur, groups):\n'
                '      if x == 0 then ([], List.concat groups [cur])\n'
                '      else (List.concat cur [x], groups)\n'
                'let out = match List.fold step ([], []) [1, 2, 0, 3, 0]: case (cur, groups): (cur, groups)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_map_remove_in_chain_lowers_to_pop',
        "files": {
            'main.pyfun': (
                'let step m x = Map.remove x (Map.add (x + 1) x m)\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_set_remove_in_chain_lowers_to_discard',
        "files": {
            'main.pyfun': (
                'let step s x = Set.remove (x - 1) (Set.add x s)\n'
                'let out = Set.toList (List.fold step Set.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_var_init_defensive_copy_dict_list_set',
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
                'let origs = (Map.len dseed, List.len lseed, Set.len sseed)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_var_init_alias_for_passthrough_slot',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  match acc:\n'
                '    case (m, keep): (Map.add x x m, keep)\n'
                'let seed = Map.empty\n'
                'let seed2 = Map.empty\n'
                'let r = List.fold step (seed, seed2) [1, 2]\n'
                'let out = match r: case (m, keep): (Map.len m, Map.len keep, Map.len seed2)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_parameterized_local_let_closure',
        "files": {
            'main.pyfun': (
                'let step acc x =\n'
                '  let peek u = Map.len acc\n'
                '  Map.add x (peek 0) acc\n'
                'let out = Map.toList (List.fold step Map.empty [1, 2, 3])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_destructuring_elem_lambda_lowers_to_tuple_target',
        "files": {
            'main.pyfun': (
                'let steps = [("a", 1), ("b", 2), ("a", 3)]\n'
                'let m = List.fold (fun m (p, l) -> Map.add p l m) Map.empty steps'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_fold_destructuring_elem_matches_fst_snd_spelling',
        "files": {
            'main.pyfun': (
                'let steps = [("a", 1), ("b", 2), ("a", 3)]\n'
                'let slow = List.fold (fun m (p, l) -> Map.add p l m) Map.empty steps\n'
                'let fast = List.fold (fun m s -> Map.add (fst s) (snd s) m) Map.empty steps\n'
                'let out = (Map.toList slow, Map.toList fast, slow == fast)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_destructuring_elem_top_level_named_folder',
        "files": {
            'main.pyfun': (
                'let add m (p, l) = Map.add p l m\n'
                'let out = Map.toList (List.fold add Map.empty [(1, "x"), (2, "y")])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_destructuring_elem_block_local_named_folder',
        "files": {
            'main.pyfun': (
                'let build steps =\n'
                '  let add m (p, l) = Map.add p l m\n'
                '  List.fold add Map.empty steps\n'
                'let out = Map.toList (build [(1, "x"), (2, "y")])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_destructuring_elem_nested_tuple',
        "files": {
            'main.pyfun': (
                'let out = Map.toList (List.fold (fun m (a, (b, c)) -> Map.add a (b + c) m) Map.empty [("x", (1, 2)), ("y", (3, 4))])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_destructuring_elem_wildcard',
        "files": {
            'main.pyfun': (
                'let out = Set.toList (List.fold (fun s (p, _) -> Set.add p s) Set.empty [(1, "a"), (2, "b"), (1, "c")])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_destructuring_elem_tuple_accumulator',
        "files": {
            'main.pyfun': (
                'let step acc (k, v) =\n'
                '  match acc:\n'
                '    case (m, ks): (Map.add k v m, List.concat ks [k])\n'
                'let out = match List.fold step (Map.empty, []) [(1, "a"), (2, "b")]: case (m, ks): (Map.toList m, ks)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_destructured_elem_name_clashes_with_enclosing_lo',
        "files": {
            'main.pyfun': (
                'let clash p =\n'
                '  let inner = List.fold (fun m (p, l) -> Map.add p l m) Map.empty [(1, 2)]\n'
                '  (p, Map.toList inner)\n'
                'let out = clash 9'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__fold_reject_destructuring_accumulator_param_still_falls_back',
        "files": {
            'main.pyfun': (
                'let out = match List.fold (fun (m, n) x -> (Map.add x n m, n + 1)) (Map.empty, 0) [5, 6]: case (m, n): (Map.toList m, n)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_effectful_recursive_loop_runs',
        "files": {
            'main.pyfun': (
                'let countdown label n =\n'
                '  let _ = print label\n'
                '  if n <= 0 then 0 else countdown label (n - 1)\n'
                'let done = countdown "tick" 2'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__matching_an_option_pulls_in_the_option_prelude',
        "files": {
            'main.pyfun': (
                'let probe o =\n'
                '  match o:\n'
                '    case None: "none"\n'
                '    case Some k: k'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_binding_named_after_an_emitted_builtin_does_not_shadow',
        "files": {
            'main.pyfun': (
                'let set = 1\n'
                'let s = Set.ofList ["a"]\n'
                'print (Set.contains "a" s)\n'
                'print set'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_local_binding_named_after_a_builtin_does_not_shadow_it',
        "files": {
            'main.pyfun': (
                'let f xs =\n'
                '  let dict = 1\n'
                '  let m = Map.ofList [("a", dict)]\n'
                '  Map.len m\n'
                'print (f [])'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_bindings_named_after_python_keywords_emit_valid_python',
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
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__an_extern_module_import_is_aliased_when_a_binding_claims_its',
        "files": {
            'main.pyfun': (
                'extern sq : float -> float = math.sqrt\n'
                'let math = 1\n'
                'print (sq 4.0)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__an_aliased_or_dotted_extern_import_re_roots_around_a_collisi',
        "files": {
            'main.pyfun': (
                'extern import numpy as np\n'
                'extern zeros : int -> string = np.zeros\n'
                'let np = 1\n'
                'print (zeros 3)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': (
            'native__an_aliased_or_dotted_extern_import_re_roots_around_a_collisi_2'
        ),
        "files": {
            'main.pyfun': (
                'extern import os.path\n'
                'extern joinp : string -> string -> string = os.path.join\n'
                'let os = 1\n'
                'print (joinp "a" "b")'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__destructuring_let_lowers_to_tuple_unpacking',
        "files": {
            'main.pyfun': (
                'let pair = (1, 2)\n'
                'let (a, b) = pair'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__destructuring_let_unpacks_straight_from_a_call',
        "files": {
            'main.pyfun': (
                'let mk x = (x, x + 1)\n'
                'let (a, b) = mk 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_wildcard_element_needs_no_name',
        "files": {
            'main.pyfun': (
                'let pair = (1, 2)\n'
                'let (a, _) = pair'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_nested_destructuring_unpacks_one_level_per_statement',
        "files": {
            'main.pyfun': (
                'let p = (1, (2, 3))\n'
                'let (a, (b, c)) = p'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_record_target_reads_the_fields_it_names',
        "files": {
            'main.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let p = Point { x = 1, y = 2 }\n'
                'let Point { x, y } = p'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_destructuring_result_bind_rides_inside_the_ok_pattern',
        "files": {
            'main.pyfun': (
                'let f r = result {\n'
                '  let! (a, b) = r\n'
                '  return a + b\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_module_member_destructuring_mangles_every_name',
        "files": {
            'main.pyfun': (
                'module M =\n'
                '    let (w, h) = (3, 4)\n'
                'let r = M.w + M.h'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_destructuring_let_binds_every_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let (a, b) = (1, 2)\n'
                '        let (c, (d, e)) = (3, (4, 5))\n'
                '        let Point { x, y } = Point { x = 6, y = 7 }\n'
                '        let total = a + b + c + d + e + x + y\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_destructuring_let_inside_a_function_body',
        "files": {
            'main.pyfun': (
                '\n'
                '        let swapSum p =\n'
                '          let (a, b) = p\n'
                '          let (c, d) = (b, a)\n'
                '          c * 10 + d\n'
                '        let r = swapSum (1, 2)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_destructuring_bind_in_a_result_block',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f r =\n'
                '          result {\n'
                '            let! (a, b) = r\n'
                '            let (c, d) = (b, a)\n'
                '            return c * 10 + d\n'
                '          }\n'
                '        let ok =\n'
                '          match f (Ok (1, 2)):\n'
                '            case Ok v: v\n'
                '            case Error _: 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__option_block_lowers_to_flat_isinstance_statements',
        "files": {
            'main.pyfun': (
                'let f o = option {\n'
                '  let! x = o\n'
                '  return (x + 1)\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__option_short_circuit_forwards_the_failure_value_itself',
        "files": {
            'main.pyfun': (
                'let f o = option {\n'
                '  let! x = o\n'
                '  return x\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__option_short_circuit_forwards_the_failure_value_itself_2',
        "files": {
            'main.pyfun': (
                'let g r = result {\n'
                '  let! x = r\n'
                '  return x\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__option_block_chains_binds_without_nesting_lambdas',
        "files": {
            'main.pyfun': (
                'let f xs = option {\n'
                '  let! a = List.get 0 xs\n'
                '  let! b = List.get 1 xs\n'
                '  return (a + b)\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_destructuring_bind_unpacks_from_the_some_payload',
        "files": {
            'main.pyfun': (
                'let f o = option {\n'
                '  let! (a, b) = o\n'
                '  return a + b\n'
                '}'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_block_short_circuits_on_none',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f xs =\n'
                '          option {\n'
                '            let! a = List.get 0 xs\n'
                '            let! b = List.get 1 xs\n'
                '            return (a + b)\n'
                '          }\n'
                '        let hit =\n'
                '          match f [1, 2]:\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        let miss =\n'
                '          match f [1]:\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_block_return_bang_and_do_bang',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o p =\n'
                '          option {\n'
                '            do! p\n'
                '            let! x = o\n'
                '            return! (if x > 0 then Some (x * 2) else None)\n'
                '          }\n'
                '        let a =\n'
                '          match f (Some 3) (Some ()):\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        let b =\n'
                '          match f (Some 3) None:\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        let c =\n'
                '          match f (Some 0) (Some ()):\n'
                '            case Some n: n\n'
                '            case None: 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__option_match_in_return_position_is_an_isinstance_ladder',
        "files": {
            'main.pyfun': (
                'let f o =\n'
                '  match o:\n'
                '    case None: 0\n'
                '    case Some x: x'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__option_match_in_value_position_assigns_a_temp',
        "files": {
            'main.pyfun': (
                'let f o = 1 + (match o:\n'
                '  case Some x: x\n'
                '  case None: 0)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_non_name_option_scrutinee_is_bound_once',
        "files": {
            'main.pyfun': (
                'let w xs =\n'
                '  match List.findIndex ((==) 2) xs:\n'
                '    case Some i: i\n'
                '    case other: -1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__guarded_option_arms_fall_through_in_return_position',
        "files": {
            'main.pyfun': (
                'let g o =\n'
                '  match o:\n'
                '    case Some x if x > 10: "big"\n'
                '    case Some x: "small"\n'
                '    case None: "none"'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_guarded_catch_all_falls_through_to_the_arms_after_it',
        "files": {
            'main.pyfun': (
                'let g o =\n'
                '  match o:\n'
                '    case Some x if x > 10: 1\n'
                '    case _ if false: 2\n'
                '    case None: 3\n'
                '    case Some _: 4'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_guarded_option_arm_in_value_position_keeps_the_match',
        "files": {
            'main.pyfun': (
                'let g o = 1 + (match o:\n'
                '  case Some x if x > 10: 1\n'
                '  case Some x: 2\n'
                '  case None: 3)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_tuple_payload_unpacks_from_the_some_payload',
        "files": {
            'main.pyfun': (
                'let h o =\n'
                '  match o:\n'
                '    case Some (a, b): a + b\n'
                '    case _: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_refutable_payload_keeps_the_match',
        "files": {
            'main.pyfun': (
                'let z o =\n'
                '  match o:\n'
                '    case Some 0: true\n'
                '    case _: false'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__result_match_is_an_isinstance_ladder',
        "files": {
            'main.pyfun': (
                'let k r =\n'
                '  match r:\n'
                '    case Ok v: v\n'
                '    case Error e: -1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_user_adt_match_still_emits_match_case',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let delta d =\n'
                '  match d:\n'
                '    case Across: (0, 1)\n'
                '    case Down: (1, 0)'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_nullary_constructor_value_loads_its_singleton',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let d = Across\n'
                'let ds = [Down, Down]'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_nullary_singleton_falls_back_when_its_name_is_taken',
        "files": {
            'main.pyfun': (
                'type Dir = Across | Down\n'
                'let _Across = 1\n'
                'let d = Across\n'
                'let e = Down'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__none_loads_the_prelude_singleton_unless_its_name_is_taken',
        "files": {
            'main.pyfun': (
                'let n = None\n'
                'let o = Map.tryFind 1 Map.empty'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__none_loads_the_prelude_singleton_unless_its_name_is_taken_2',
        "files": {
            'main.pyfun': (
                'let _None_ = 1\n'
                'let n = None\n'
                'let o = Map.tryFind 1 Map.empty'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__every_emitted_class_uses_slots',
        "files": {
            'main.pyfun': (
                'type Shape = Circle float | Dot\n'
                'type P = { x: int }\n'
                'let r = Ok 1\n'
                'let o = Some 1'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_option_ladders_and_singletons_agree_with_the_match_seman',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Dir = Across | Down\n'
                '        let g o =\n'
                '          match o:\n'
                '            case Some x if x > 10: "big"\n'
                '            case Some x: "small"\n'
                '            case None: "none"\n'
                '        let h o =\n'
                '          match o:\n'
                '            case Some (a, b): a + b\n'
                '            case _: 0\n'
                '        let k r =\n'
                '          match r:\n'
                '            case Ok v: v\n'
                '            case Error e: -1\n'
                '        let v o = 1 + (match o:\n'
                '          case Some x: x\n'
                '          case None: 0)\n'
                '        let only o =\n'
                '          match o:\n'
                '            case Some x if x > 0: x\n'
                '            case _ if false: 1\n'
                '            case None: 2\n'
                '            case Some _: 3\n'
                '        let a = g (Some 11)\n'
                '        let b = g (Some 1)\n'
                '        let c = g None\n'
                '        let d = h (Some (1, 2))\n'
                '        let e = k (Ok 4)\n'
                '        let f = k (Error "x")\n'
                '        let i = v (Some 3)\n'
                '        let j = only (Some 5)\n'
                '        let l = only (Some (0 - 5))\n'
                '        let m = only None\n'
                '        let n = Across == Across\n'
                '        let p = Set.len (Set.ofList [Across, Down, Across])\n'
                '        let q = Map.findOr Down 0 (Map.ofList [(Down, 7)])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_slotted_records_update_compare_and_hash',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x: int, y: int }\n'
                '        let p = Point { x = 1, y = 2 }\n'
                '        let q = { p with x = 3 }\n'
                '        let lt = p < q\n'
                '        let s = Set.len (Set.ofList [p, q, p])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__local_let_partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                '\n'
                '        let addAll xs ys =\n'
                '          let pair a b = a + b\n'
                '          List.map (pair 10) ys\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_local_let_partial_application_runs',
        "files": {
            'main.pyfun': (
                '\n'
                '        let addAll xs ys =\n'
                '          let pair a b = a + b\n'
                '          List.map (pair 10) ys\n'
                '        let r = addAll [] [1, 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__local_lambda_let_partial_application_uses_functools_partial',
        "files": {
            'main.pyfun': (
                '\n'
                '        let addAll ys =\n'
                '          let pair = fun a b -> a + b\n'
                '          List.map (pair 10) ys\n'
                '        let r = addAll [1, 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__local_let_over_application_applies_the_remainder',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let k a b = fun c -> a + b + c\n'
                '          k 1 2 x\n'
                '        let r = f 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__parameter_shadowing_a_local_function_stays_n_ary',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f ys =\n'
                '          let pair a b = a + b\n'
                '          let g pair = pair 10\n'
                '          g (fun x -> x + 1)\n'
                '        let r = f []\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__match_binder_shadowing_a_local_function_stays_n_ary',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let pair a b = a + b\n'
                '          let outer = pair 1\n'
                '          let inner =\n'
                '            match o:\n'
                '              case Some pair: pair 10\n'
                '              case None: 0\n'
                '          inner + outer 2\n'
                '        let r = f (Some (fun x -> x + 1))\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__recursive_local_function_sees_its_own_arity',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f n =\n'
                '          let go acc k =\n'
                '            if k == 0 then [acc]\n'
                '            else List.collect (go (acc + 1)) [k - 1]\n'
                '          go 0 n\n'
                '        let r = f 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__non_function_rebinding_evicts_the_local_arity',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let pair a b = a + b\n'
                '          let pair = pair 1\n'
                '          pair x\n'
                '        let r = f 2\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_capture_colliding_with_a_block_local_function_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let pair a b = a + b\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some pair: pair\n'
                '              case None: 0\n'
                '          pair r 1\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_capture_colliding_with_a_top_level_function_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let pair a b = a + b\n'
                '        let f o =\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some pair: pair\n'
                '              case None: 0\n'
                '          pair r 1\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_capture_colliding_with_a_parameter_read_later_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x o =\n'
                '          match o:\n'
                '            case Some x: x\n'
                '            case None: x\n'
                '        let a = f 1 (Some 5)\n'
                '        let b = f 1 None\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__sibling_arms_capturing_the_same_name_are_not_renamed',
        "files": {
            'main.pyfun': (
                'let f r =\n'
                '  match r:\n'
                '    case Ok x: x\n'
                '    case Error x: 0 - x'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__an_unreferenced_outer_name_does_not_force_a_rename',
        "files": {
            'main.pyfun': (
                'let f x o =\n'
                '  match o:\n'
                '    case Some x: x\n'
                '    case None: 0'
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_nested_matches_capturing_the_same_name_get_distinct_fres',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x o p =\n'
                '          match o:\n'
                '            case Some x:\n'
                '              let inner =\n'
                '                match p:\n'
                '                  case Some x: x * 10\n'
                '                  case None: x\n'
                '              inner + x\n'
                '            case None: x\n'
                '        let r = f 1 (Some 2) (Some 3)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_closure_made_before_the_match_reads_the_original_bindi',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let n = 100\n'
                '          let get u = n + u\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some n: n\n'
                '              case None: 0\n'
                '          r + get 0\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_or_and_record_pattern_captures_are_renamed_consistently',
        "files": {
            'main.pyfun': (
                '\n'
                '        type Point = { x : int, y : int }\n'
                '        let f y p q =\n'
                '          let a =\n'
                '            match p:\n'
                '              case Point { x = 0, y }: y\n'
                '              case Point { x }: x + y\n'
                '          let b =\n'
                '            match q:\n'
                '              case (0, y) | (y, 0): y\n'
                '              case (_, _): y\n'
                '          a + b\n'
                '        let r = f 1000 (Point { x = 0, y = 2 }) (0, 3)\n'
                '        let s = f 1000 (Point { x = 4, y = 2 }) (7, 8)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_value_position_capture_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let total a b = a + b\n'
                '          1 + (match o:\n'
                '                 case Some total: total\n'
                '                 case None: 0) + total 1 1\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_lookup_peephole_capture_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f m k =\n'
                '          let v = 100\n'
                '          let found =\n'
                '            match Map.tryFind k m:\n'
                '              case Some v: v\n'
                '              case None: 0\n'
                '          found + v\n'
                '        let r = f (Map.ofList [(1, 5)]) 1\n'
                '        let s = f (Map.ofList [(1, 5)]) 2\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_active_pattern_capture_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let (|Positive|_|) n = if n > 0 then Some n else None\n'
                '        let f p n =\n'
                '          let label =\n'
                '            match n:\n'
                '              case Positive p: p * 2\n'
                '              case _: 0\n'
                '          label + p\n'
                '        let r = f 1000 5\n'
                '        let s = f 1000 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_fresh_capture_name_bumps_past_a_name_in_use',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let pair a b = a + b\n'
                '          let _pair = 7\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some pair: pair\n'
                '              case None: 0\n'
                '          pair r _pair\n'
                '        let r = f (Some 5)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_lambda_parameter_inside_the_arm_keeps_its_own_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x o =\n'
                '          let r =\n'
                '            match o:\n'
                '              case Some x: List.map (fun x -> x + 1) x\n'
                '              case None: []\n'
                '          List.len r + x\n'
                '        let r = f 10 (Some [1, 2, 3])\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_module_level_capture_colliding_with_a_global_read_is_r',
        "files": {
            'main.pyfun': (
                '\n'
                '        let m =\n'
                '          match Some 5:\n'
                '            case Some print: print\n'
                '            case None: 0\n'
                '        let show x = print x\n'
                '        let r = m\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_fold_loop_arm_capture_is_renamed_in_the_enclosing_frame',
        "files": {
            'main.pyfun': (
                '\n'
                '        let bump x = x + 100\n'
                '        let f xs =\n'
                '          let seen = List.fold (fun acc o ->\n'
                '            match o:\n'
                '              case Some bump: Map.add bump 1 acc\n'
                '              case None: acc) Map.empty xs\n'
                '          bump (Map.len seen)\n'
                '        let r = f [Some 1, None, Some 2]\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_let_in_an_if_branch_does_not_rebind_the_outer_binding',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let x = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = 10\n'
                '              x + 1\n'
                '            else 0\n'
                '          x + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_let_in_a_match_arm_body_does_not_rebind_the_outer_bind',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let n = 1\n'
                '          let y =\n'
                '            match o:\n'
                '              case Some k:\n'
                '                let n = k * 10\n'
                '                n + 1\n'
                '              case None: 0\n'
                '          n + y\n'
                '        let r = f (Some 2)\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_let_in_a_return_position_arm_block_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f o =\n'
                '          let n = 1\n'
                '          match o:\n'
                '            case Some k:\n'
                '              let n = n * 10 + k\n'
                '              n + 1\n'
                '            case None: n\n'
                '        let r = f (Some 2)\n'
                '        let s = f None\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_nested_function_let_shadowing_an_outer_function_is_ren',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag n =\n'
                '          let go k = k * 100\n'
                '          let y =\n'
                '            if flag then\n'
                '              let go k = if k == 0 then 0 else k + go (k - 1)\n'
                '              go n\n'
                '            else 0\n'
                '          y + go 1\n'
                '        let r = f true 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_nested_let_mut_with_assignment_keeps_the_outer_binding',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let total = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let mut total = 0\n'
                '              total <- total + 5\n'
                '              total <- total + 5\n'
                '              total\n'
                '            else 0\n'
                '          total + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_closure_assigning_a_renamed_nested_mut_declares_the_fr',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let count = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let mut count = 0\n'
                '              let bump u = count <- count + u\n'
                '              bump 4\n'
                '              bump 5\n'
                '              count\n'
                '            else 0\n'
                '          count + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_nested_let_shadowing_a_parameter_read_later_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x flag =\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = 10\n'
                '              x\n'
                '            else 0\n'
                '          x + y\n'
                '        let r = f 1 true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_root_level_let_rebinding_a_parameter_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let x = x + 1\n'
                '          let x = x * 2\n'
                '          x\n'
                '        let r = f 1\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_nested_let_with_no_occurrence_outside_its_block_is_not_ren',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let y =\n'
                '            if flag then\n'
                '              let t = 10\n'
                '              t + 1\n'
                '            else 0\n'
                '          y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_destructuring_nested_let_renames_each_colliding_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let a = 1\n'
                '          let y =\n'
                '            if flag then\n'
                '              let (a, b) = (10, 20)\n'
                '              a + b\n'
                '            else 0\n'
                '          a + y\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_nested_let_fresh_name_bumps_past_a_name_in_use',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f flag =\n'
                '          let x = 1\n'
                '          let _x = 100\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = 10\n'
                '              x + 1\n'
                '            else 0\n'
                '          x + y + _x\n'
                '        let r = f true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_capture_reused_across_sequential_matches_keeps_its_nam',
        "files": {
            'main.pyfun': (
                '\n'
                '        let step a b =\n'
                '          let x =\n'
                '            match a:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          let y =\n'
                '            match b:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          x + y\n'
                '        let r = step (Ok 1) (Error "no")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_let_reused_across_sequential_branches_keeps_its_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f a b =\n'
                '          let x =\n'
                '            if a then\n'
                '              let t = 1\n'
                '              t + 1\n'
                '            else 0\n'
                '          let y =\n'
                '            if b then\n'
                '              let t = 10\n'
                '              t + 1\n'
                '            else 0\n'
                '          x + y\n'
                '        let r = f true true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_outer_binding_read_after_both_matches_renames_both_ca',
        "files": {
            'main.pyfun': (
                '\n'
                '        let step a b =\n'
                '          let why = "x"\n'
                '          let x =\n'
                '            match a:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          let y =\n'
                '            match b:\n'
                '              case Ok v: v\n'
                '              case Error why: String.len why\n'
                '          String.len why + x + y\n'
                '        let r = step (Ok 1) (Error "no")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_nested_let_reading_the_parameter_it_shadows_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x flag =\n'
                '          let y =\n'
                '            if flag then\n'
                '              let x = x + 1\n'
                '              x * 2\n'
                '            else 0\n'
                '          y\n'
                '        let r = f 5 true\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_three_sequential_error_arms_emit_the_plain_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let describe a b c =\n'
                '          let s1 =\n'
                '            match a:\n'
                '              case Ok n: n\n'
                '              case Error why: String.len why\n'
                '          let s2 =\n'
                '            match b:\n'
                '              case Ok n: n\n'
                '              case Error why: String.len why\n'
                '          let s3 =\n'
                '            match c:\n'
                '              case Ok n: n\n'
                '              case Error why: String.len why\n'
                '          s1 + s2 + s3\n'
                '        let r = describe (Error "a") (Ok 2) (Error "ccc")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_closure_escaping_an_earlier_arm_forces_the_later_captu',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f a b =\n'
                '          let g =\n'
                '            match a:\n'
                '              case Error why: fun u -> why\n'
                '              case Ok n: fun u -> "ok"\n'
                '          let m =\n'
                '            match b:\n'
                '              case Error why: String.len why\n'
                '              case Ok n: n\n'
                '          String.len (g 0) + m\n'
                '        let r = f (Error "first") (Error "second")\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_root_let_shadowing_an_enclosing_name_read_earlier_is_r',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let g o =\n'
                '            let y = x + 1\n'
                '            let x = 2\n'
                '            x + y + o\n'
                '          g 10\n'
                '        let r = f 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_root_let_shadowing_a_module_binding_read_earlier_is_re',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          let m = n + 1\n'
                '          let n = 2\n'
                '          m + n + u\n'
                '        let r = f 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_root_let_reading_the_module_binding_it_shadows_is_rena',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          let n = n + 1\n'
                '          n + u\n'
                '        let r = f 10\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_closure_made_before_a_root_let_reads_the_enclosing_bin',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let g o =\n'
                '            let peek u = x + u\n'
                '            let before = peek 0\n'
                '            let x = 100\n'
                '            before + x + o\n'
                '          g 1\n'
                '        let r = f 5\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_root_let_rebinding_a_parameter_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let x = x + 1\n'
                '          x * 2\n'
                '        let r = f 3\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_root_let_referenced_only_after_it_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          let n = 2\n'
                '          n + u\n'
                '        let g u =\n'
                '          let k = 1\n'
                '          k + u\n'
                '        let r = f 10 + g 1\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_top_level_let_is_never_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let m = n + 1\n'
                '        let n = 7\n'
                '        let r = n + m\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_root_let_mut_shadowing_an_enclosing_name_declares_the',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f x =\n'
                '          let g o =\n'
                '            let before = x\n'
                '            let mut x = 0\n'
                '            let bump u = x <- x + u\n'
                '            bump 5\n'
                '            bump 6\n'
                '            before + x + o\n'
                '          g 1\n'
                '        let r = f 100\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_destructuring_root_let_renames_only_the_colliding_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f a =\n'
                '          let g o =\n'
                '            let before = a\n'
                '            let (a, b) = (10, 20)\n'
                '            before + a + b + o\n'
                '          g 1\n'
                '        let r = f 100\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_ce_bind_shadowing_a_module_binding_read_earlier_is_ren',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          option {\n'
                '            let m = n + 1\n'
                '            let! n = Some 2\n'
                '            return n + m\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_result_bind_shadowing_an_outer_name_keeps_its_failure',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          result {\n'
                '            let m = n + 1\n'
                '            let! n = if u > 0 then Ok 2 else Error "no"\n'
                '            return n + m\n'
                '          }\n'
                '        let a = f 1\n'
                '        let b = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_an_async_bind_shadowing_an_outer_name_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          async {\n'
                '            let m = n + 1\n'
                '            let! n = async { return 2 }\n'
                '            return n + m\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_seq_let_shadowing_an_outer_name_is_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          seq {\n'
                '            let m = n + 1\n'
                '            let n = 2\n'
                '            yield n + m\n'
                '          }\n'
                '        let r = f 0 |> Seq.toList\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_ce_bind_read_only_after_it_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          option {\n'
                '            let! n = Some 2\n'
                '            let k = 1\n'
                '            return n + k\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__a_ce_bind_rebinding_an_earlier_ce_binder_is_not_renamed',
        "files": {
            'main.pyfun': (
                '\n'
                '        let f u =\n'
                '          option {\n'
                '            let n = 1\n'
                '            let! n = Some (n + 1)\n'
                '            return n\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
    {
        'id': 'native__e2e_a_destructuring_ce_bind_renames_only_the_colliding_name',
        "files": {
            'main.pyfun': (
                '\n'
                '        let n = 5\n'
                '        let f u =\n'
                '          option {\n'
                '            let m = n + 1\n'
                '            let! (n, k) = Some (2, 3)\n'
                '            return n + k + m\n'
                '          }\n'
                '        let r = f 0\n'
                '        '
            ),
        },
        'args': ['compile', 'main.pyfun', '--native'],
    },
]



@pytest.mark.parametrize("case", COMPILE_CASES, ids=[c["id"] for c in COMPILE_CASES])
def test_compile_emits_exact_python(run, workdir, case):
    """CATCHES: lowering that emits different Python for a construct (wrong def/lambda/partial shape, missing or extra helper functions and imports, different match/case layout, wrong dataclass declarations, operator precedence or parenthesisation errors), or that prints notes/diagnostics where the reference prints none."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))


@pytest.mark.parametrize("case", NATIVE_CASES, ids=[c["id"] for c in NATIVE_CASES])
def test_native_compile_emits_annotated_python(run, workdir, case):
    """CATCHES: a `--native` mode that ignores the flag, omits or misspells the inferred type annotations, or keeps `match` statements instead of lowering them to isinstance ladders."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
