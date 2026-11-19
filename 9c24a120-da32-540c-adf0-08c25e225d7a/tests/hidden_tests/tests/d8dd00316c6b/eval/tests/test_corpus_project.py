"""Multi-module projects: `check`, `compile` and `run` over an import graph.

Each project was harvested from the project's own tests/project.rs: every module
`Name` is written as `name.pyfun` in the working directory and the command is run
on the entry `main.pyfun`. `compile` without `-o` prints every emitted file under
a `# ==== name.py ====` banner; `check` renders each module's errors under a
`-- module ... --` header. Expected transcripts were captured from the reference binary.
"""

import pytest

from conftest import golden_name, read_golden, run_case, transcript

PROJECT_CASES = [
    {
        'id': 'compile__each_module_emits_its_own_file_with_unmangled_names',
        "files": {
            'main.pyfun': (
                'import Geometry\n'
                'let floor = Geometry.area 4 5'
            ),
            'geometry.pyfun': 'let area w h = w * h',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_partial_application_still_curries',
        "files": {
            'main.pyfun': (
                'import Geometry\n'
                'let scale = Geometry.area 2'
            ),
            'geometry.pyfun': 'let area w h = w * h',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__option_classes_come_from_the_shared_runtime',
        "files": {
            'main.pyfun': (
                'import Store\n'
                'let found = Option.isSome (Store.lookup 1)'
            ),
            'store.pyfun': 'let lookup k = Some k',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_runs_a_cross_module_program',
        "files": {
            'main.pyfun': (
                'import Geometry\n'
                'let floor = Geometry.area 4 5\n'
                'print floor'
            ),
            'geometry.pyfun': 'let area w h = w * h',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_runs_a_cross_module_program',
        "files": {
            'main.pyfun': (
                'import Geometry\n'
                'let floor = Geometry.area 4 5\n'
                'print floor'
            ),
            'geometry.pyfun': 'let area w h = w * h',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_task_started_in_one_module_joins_a_scope_opened_in_ano',
        "files": {
            'main.pyfun': (
                'import Jobs\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let session = Task.scope (async {\n'
                '  Jobs.launch "x"\n'
                '  Jobs.launch "y"\n'
                '  return 7\n'
                '})\n'
                'print (runAsync session)'
            ),
            'jobs.pyfun': (
                'let worker name = async {\n'
                '  do! Async.sleep 0.01\n'
                '  print name\n'
                '}\n'
                'let launch name = Task.start (worker name)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_task_started_in_one_module_joins_a_scope_opened_in_ano',
        "files": {
            'main.pyfun': (
                'import Jobs\n'
                'extern runAsync: Async a -> a = asyncio.run\n'
                'let session = Task.scope (async {\n'
                '  Jobs.launch "x"\n'
                '  Jobs.launch "y"\n'
                '  return 7\n'
                '})\n'
                'print (runAsync session)'
            ),
            'jobs.pyfun': (
                'let worker name = async {\n'
                '  do! Async.sleep 0.01\n'
                '  print name\n'
                '}\n'
                'let launch name = Task.start (worker name)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_an_imported_async_extern_is_cold_and_its_argument_starts',
        "files": {
            'main.pyfun': (
                'import Clock\n'
                'let tick = Clock.pause 0.0\n'
                'let twice = async {\n'
                '  do! tick\n'
                '  do! tick\n'
                '  return 2\n'
                '}\n'
                'print (Clock.runAsync twice)'
            ),
            'clock.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern pause: float -> Async unit = asyncio.sleep'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_an_imported_async_extern_is_cold_and_its_argument_starts',
        "files": {
            'main.pyfun': (
                'import Clock\n'
                'let tick = Clock.pause 0.0\n'
                'let twice = async {\n'
                '  do! tick\n'
                '  do! tick\n'
                '  return 2\n'
                '}\n'
                'print (Clock.runAsync twice)'
            ),
            'clock.pyfun': (
                'extern runAsync: Async a -> a = asyncio.run\n'
                'extern pause: float -> Async unit = asyncio.sleep'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_derived_codecs_cross_a_module_import',
        "files": {
            'main.pyfun': (
                'import Rules\n'
                'let wire = Encode.auto Rules.sample\n'
                'print wire\n'
                'let back = Decode.decodeString Decode.auto wire\n'
                'match back:\n'
                '  case Ok v: print (v == Rules.sample)\n'
                '  case Error e: print e.errorMessage'
            ),
            'rules.pyfun': (
                'type Placed = { letter: string, score: int }\n'
                'type Player = Ann | Bob\n'
                'type View = { board: Map (int, int) Placed, turn: Option Player }\n'
                'let sample = View { board = Map.ofList [((1, 2), Placed { letter = "Q", score = 10 })], turn = Some Bob }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_derived_codecs_cross_a_module_import',
        "files": {
            'main.pyfun': (
                'import Rules\n'
                'let wire = Encode.auto Rules.sample\n'
                'print wire\n'
                'let back = Decode.decodeString Decode.auto wire\n'
                'match back:\n'
                '  case Ok v: print (v == Rules.sample)\n'
                '  case Error e: print e.errorMessage'
            ),
            'rules.pyfun': (
                'type Placed = { letter: string, score: int }\n'
                'type Player = Ann | Bob\n'
                'type View = { board: Map (int, int) Placed, turn: Option Player }\n'
                'let sample = View { board = Map.ofList [((1, 2), Placed { letter = "Q", score = 10 })], turn = Some Bob }'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_sum_type_constructs_and_matches',
        "files": {
            'shape.pyfun': 'type Shape = Circle float | Rect float float',
            'main.pyfun': (
                'import Shape\n'
                'let c = Shape.Circle 2.0\n'
                'let area s =\n'
                '  match s:\n'
                '    case Shape.Circle r: r\n'
                '    case Shape.Rect w h: w * h\n'
                'let a = area c'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_nullary_enum_constructs_as_a_call',
        "files": {
            'color.pyfun': 'type Color = Red | Green | Blue',
            'main.pyfun': (
                'import Color\n'
                'let favourite = Color.Green\n'
                'let name k =\n'
                '  match k:\n'
                '    case Color.Red: "r"\n'
                '    case Color.Green: "g"\n'
                '    case Color.Blue: "b"\n'
                'let n = name favourite'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_nullary_enum_falls_back_to_a_call_when_the_si',
        "files": {
            'color.pyfun': (
                'type Color = Red | Green | Blue\n'
                'let _Green = 1'
            ),
            'main.pyfun': (
                'import Color\n'
                'let favourite = Color.Green\n'
                'let red = Color.Red'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_cross_module_nullary_singletons_and_option_ladder',
        "files": {
            'color.pyfun': 'type Color = Red | Green | Blue',
            'main.pyfun': (
                'import Color\n'
                'let name k =\n'
                '  match k:\n'
                '    case Color.Red: "r"\n'
                '    case Color.Green: "g"\n'
                '    case Color.Blue: "b"\n'
                'let last xs =\n'
                '  match List.last xs:\n'
                '    case Some c: name c\n'
                '    case None: "-"\n'
                'print (last [Color.Green, Color.Red])\n'
                'print (last [])\n'
                'print (Color.Red == Color.Red)\n'
                'print (Set.len (Set.ofList [Color.Red, Color.Red, Color.Blue]))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_cross_module_nullary_singletons_and_option_ladder',
        "files": {
            'color.pyfun': 'type Color = Red | Green | Blue',
            'main.pyfun': (
                'import Color\n'
                'let name k =\n'
                '  match k:\n'
                '    case Color.Red: "r"\n'
                '    case Color.Green: "g"\n'
                '    case Color.Blue: "b"\n'
                'let last xs =\n'
                '  match List.last xs:\n'
                '    case Some c: name c\n'
                '    case None: "-"\n'
                'print (last [Color.Green, Color.Red])\n'
                'print (last [])\n'
                'print (Color.Red == Color.Red)\n'
                'print (Set.len (Set.ofList [Color.Red, Color.Red, Color.Blue]))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'check__a_cross_module_non_exhaustive_match_is_caught',
        "files": {
            'shape.pyfun': 'type Shape = Circle float | Rect float float',
            'main.pyfun': (
                'import Shape\n'
                'let f s =\n'
                '  match s:\n'
                '    case Shape.Circle r: r'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_constructor_of_an_unimported_type_is_unavailable',
        "files": {
            'shape.pyfun': 'type Shape = Circle float | Rect float float',
            'main.pyfun': 'let c = Shape.Circle 2.0',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_cross_module_adt_round_trips',
        "files": {
            'shape.pyfun': 'type Shape = Circle int | Rect int int',
            'main.pyfun': (
                'import Shape\n'
                'let area s =\n'
                '  match s:\n'
                '    case Shape.Circle r: r * r\n'
                '    case Shape.Rect w h: w * h\n'
                'print (area (Shape.Circle 3))\n'
                'print (area (Shape.Rect 4 5))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_cross_module_adt_round_trips',
        "files": {
            'shape.pyfun': 'type Shape = Circle int | Rect int int',
            'main.pyfun': (
                'import Shape\n'
                'let area s =\n'
                '  match s:\n'
                '    case Shape.Circle r: r * r\n'
                '    case Shape.Rect w h: w * h\n'
                'print (area (Shape.Circle 3))\n'
                'print (area (Shape.Rect 4 5))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_record_constructs_and_routes_to_the_exporting',
        "files": {
            'geometry.pyfun': 'type Point = { x: int, y: int }',
            'main.pyfun': (
                'import Geometry\n'
                'let p = Geometry.Point { x = 1, y = 2 }\n'
                'let sx = p.x\n'
                'let shifted = { p with x = 10 }\n'
                'let describe q =\n'
                '  match q:\n'
                '    case Geometry.Point { x = 0, y }: y\n'
                '    case Geometry.Point { x, y }: x + y\n'
                'let d = describe p'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_cross_module_record_round_trips',
        "files": {
            'geometry.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let origin = Point { x = 0, y = 0 }\n'
                'let mag p = p.x + p.y'
            ),
            'main.pyfun': (
                'import Geometry\n'
                'let p = Geometry.Point { x = 3, y = 4 }\n'
                'let shifted = { p with x = 10 }\n'
                'let sum q =\n'
                '  match q:\n'
                '    case Geometry.Point { x, y }: x + y\n'
                'print (sum p)\n'
                'print shifted.x\n'
                'print (Geometry.mag p)\n'
                'print (Geometry.mag Geometry.origin)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_cross_module_record_round_trips',
        "files": {
            'geometry.pyfun': (
                'type Point = { x: int, y: int }\n'
                'let origin = Point { x = 0, y = 0 }\n'
                'let mag p = p.x + p.y'
            ),
            'main.pyfun': (
                'import Geometry\n'
                'let p = Geometry.Point { x = 3, y = 4 }\n'
                'let shifted = { p with x = 10 }\n'
                'let sum q =\n'
                '  match q:\n'
                '    case Geometry.Point { x, y }: x + y\n'
                'print (sum p)\n'
                'print shifted.x\n'
                'print (Geometry.mag p)\n'
                'print (Geometry.mag Geometry.origin)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_parameterized_cross_module_record_round_trips',
        "files": {
            'store.pyfun': 'type Box a = { item: a, label: string }',
            'main.pyfun': (
                'import Store\n'
                'let b = Store.Box { item = 42, label = "answer" }\n'
                'print b.item\n'
                'print b.label'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_parameterized_cross_module_record_round_trips',
        "files": {
            'store.pyfun': 'type Box a = { item: a, label: string }',
            'main.pyfun': (
                'import Store\n'
                'let b = Store.Box { item = 42, label = "answer" }\n'
                'print b.item\n'
                'print b.label'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_local_type_declaration_can_name_an_imported_type',
        "files": {
            'shapes.pyfun': (
                'type Placed = { row: int, col: int }\n'
                'let mk r = Placed { row = r, col = r }\n'
                'let rowOf p = p.row'
            ),
            'main.pyfun': (
                'import Shapes\n'
                'type Holder = { item: Shapes.Placed, tag: string }\n'
                'type Slot = Empty | Filled Placed\n'
                'let describe s =\n'
                '  match s:\n'
                '    case Empty: 0\n'
                '    case Filled p: Shapes.rowOf p\n'
                'let h = Holder { item = Shapes.mk 3, tag = "a" }\n'
                'print h.tag\n'
                'print (describe (Filled h.item))\n'
                'print (describe Empty)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_local_type_declaration_can_name_an_imported_type',
        "files": {
            'shapes.pyfun': (
                'type Placed = { row: int, col: int }\n'
                'let mk r = Placed { row = r, col = r }\n'
                'let rowOf p = p.row'
            ),
            'main.pyfun': (
                'import Shapes\n'
                'type Holder = { item: Shapes.Placed, tag: string }\n'
                'type Slot = Empty | Filled Placed\n'
                'let describe s =\n'
                '  match s:\n'
                '    case Empty: 0\n'
                '    case Filled p: Shapes.rowOf p\n'
                'let h = Holder { item = Shapes.mk 3, tag = "a" }\n'
                'print h.tag\n'
                'print (describe (Filled h.item))\n'
                'print (describe Empty)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__an_imported_type_is_the_same_type_qualified_or_bare',
        "files": {
            'shapes.pyfun': 'type Placed = { row: int, col: int }',
            'main.pyfun': (
                'import Shapes\n'
                'extern pure widen : Shapes.Placed -> Placed = builtins.id\n'
                'let same p = widen p'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'check__an_unknown_qualified_type_is_reported',
        "files": {
            'shapes.pyfun': 'type Placed = { row: int, col: int }',
            'main.pyfun': (
                'import Shapes\n'
                'type Holder = { item: Shapes.Widget }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_bare_tag_does_not_construct_an_imported_record',
        "files": {
            'geometry.pyfun': 'type Point = { x: int, y: int }',
            'main.pyfun': (
                'import Geometry\n'
                'let p = Point { x = 1, y = 2 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_cross_module_shared_field_is_ambiguous_at_the_access_site',
        "files": {
            'geometry.pyfun': 'type Point = { x: int, y: int }',
            'main.pyfun': (
                'import Geometry\n'
                'type Vec = { x: int, z: int }\n'
                'let get p = p.x'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__an_unexported_record_member_is_not_a_member',
        "files": {
            'geometry.pyfun': 'type Point = { x: int, y: int }',
            'main.pyfun': (
                'import Geometry\n'
                'let w = Geometry.Widget { x = 1 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_extern_binds_in_its_module_and_routes_from_th',
        "files": {
            'mathx.pyfun': 'extern fabs : float -> float = math.fabs',
            'main.pyfun': (
                'import Mathx\n'
                'let r = Mathx.fabs 8.0\n'
                'print r'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__a_cross_module_extern_binds_in_its_module_and_routes_from_th',
        "files": {
            'mathx.pyfun': 'extern fabs : float -> float = math.fabs',
            'main.pyfun': (
                'import Mathx\n'
                'let r = Mathx.fabs 8.0\n'
                'print r'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_cross_module_extern_partial_application_curries',
        "files": {
            'mathx.pyfun': 'extern fabs : float -> float = math.fabs',
            'main.pyfun': (
                'import Mathx\n'
                'let xs = List.map Mathx.fabs [8.0, 27.0, 64.0]\n'
                'print xs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_cross_module_extern_partial_application_curries',
        "files": {
            'mathx.pyfun': 'extern fabs : float -> float = math.fabs',
            'main.pyfun': (
                'import Mathx\n'
                'let xs = List.map Mathx.fabs [8.0, 27.0, 64.0]\n'
                'print xs'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'check__an_unexported_extern_is_not_a_member',
        "files": {
            'mathx.pyfun': 'extern fabs : float -> float = math.fabs',
            'main.pyfun': (
                'import Mathx\n'
                'let r = Mathx.hypotenuse 8.0'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__an_imported_impure_extern_keeps_its_effect_across_the_bounda',
        "files": {
            'logx.pyfun': (
                'extern log : string -> unit = builtins.print\n'
                'extern pure ident : int -> int = builtins.abs'
            ),
            'main.pyfun': (
                'import Logx\n'
                'let pure bad s = Logx.log s'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': (
            'compile__an_imported_impure_extern_keeps_its_effect_across_the_bounda_2'
        ),
        "files": {
            'logx.pyfun': (
                'extern log : string -> unit = builtins.print\n'
                'extern pure ident : int -> int = builtins.abs'
            ),
            'main.pyfun': (
                'import Logx\n'
                'let pure ok n = Logx.ident n'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__a_shared_measure_module_is_used_across_files',
        "files": {
            'units.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure N = m / s'
            ),
            'dist.pyfun': (
                'import Units\n'
                'let far d = d + 1<m>'
            ),
            'main.pyfun': (
                'import Units\n'
                'import Dist\n'
                'let here = 100<m>\n'
                'let f = 10<N>\n'
                'let g = Dist.far 5<m>'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_cross_module_measure_annotated_value_runs',
        "files": {
            'units.pyfun': 'measure m',
            'main.pyfun': (
                'import Units\n'
                'let d = 100<m>\n'
                'let e = d + 50<m>\n'
                'print e'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_cross_module_measure_annotated_value_runs',
        "files": {
            'units.pyfun': 'measure m',
            'main.pyfun': (
                'import Units\n'
                'let d = 100<m>\n'
                'let e = d + 50<m>\n'
                'print e'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'check__using_a_measure_without_importing_its_module_is_an_error',
        "files": {
            'units.pyfun': 'measure m',
            'main.pyfun': 'let d = 100<m>',
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_cross_module_measure_alias_conflict_is_reported',
        "files": {
            'ua.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure N = m / s'
            ),
            'ub.pyfun': (
                'measure m\n'
                'measure s\n'
                'measure N = m s'
            ),
            'main.pyfun': (
                'import Ua\n'
                'import Ub\n'
                'let x = 1'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__a_shared_base_measure_across_two_imports_does_not_conflict',
        "files": {
            'ua.pyfun': (
                'measure m\n'
                'let a = 1<m>'
            ),
            'ub.pyfun': (
                'measure m\n'
                'let b = 2<m>'
            ),
            'main.pyfun': (
                'import Ua\n'
                'import Ub\n'
                'let x = 1'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__a_cross_module_newtype_erases_in_the_consumer_too',
        "files": {
            'ids.pyfun': (
                'opaque type UserId = string\n'
                'let greet u =\n'
                '  match u:\n'
                '    case UserId s: String.concat "hi " s'
            ),
            'main.pyfun': (
                'import Ids\n'
                'let uid = Ids.UserId "ana"\n'
                'let g = Ids.greet uid\n'
                'let unwrapped =\n'
                '  match uid:\n'
                '    case Ids.UserId s: s\n'
                'let mapped = List.map Ids.UserId ["a", "b"]'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_cross_module_newtype_round_trips',
        "files": {
            'ids.pyfun': (
                'opaque type UserId = string\n'
                'let greet u =\n'
                '  match u:\n'
                '    case UserId s: String.concat "hi " s'
            ),
            'main.pyfun': (
                'import Ids\n'
                'let uid = Ids.UserId "ana"\n'
                'let unwrapped =\n'
                '  match uid:\n'
                '    case Ids.UserId s: s\n'
                'let mapped = List.map Ids.UserId ["a", "b"]\n'
                'print (Ids.greet uid)\n'
                'print unwrapped\n'
                'print (List.len mapped)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_cross_module_newtype_round_trips',
        "files": {
            'ids.pyfun': (
                'opaque type UserId = string\n'
                'let greet u =\n'
                '  match u:\n'
                '    case UserId s: String.concat "hi " s'
            ),
            'main.pyfun': (
                'import Ids\n'
                'let uid = Ids.UserId "ana"\n'
                'let unwrapped =\n'
                '  match uid:\n'
                '    case Ids.UserId s: s\n'
                'let mapped = List.map Ids.UserId ["a", "b"]\n'
                'print (Ids.greet uid)\n'
                'print unwrapped\n'
                'print (List.len mapped)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'check__a_cross_module_newtype_stays_distinct_from_its_underlying',
        "files": {
            'ids.pyfun': (
                'opaque type UserId = string\n'
                'let greet u =\n'
                '  match u:\n'
                '    case UserId s: s'
            ),
            'main.pyfun': (
                'import Ids\n'
                'let bad = Ids.greet "raw"'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_an_extern_type_can_be_named_across_the_module_boundary',
        "files": {
            'gen.pyfun': (
                'extern type Rng\n'
                'extern newRng : int -> Rng = random.Random\n'
                'let make seed = newRng seed'
            ),
            'main.pyfun': (
                'import Gen\n'
                'type Holder = { h: Gen.Rng }\n'
                'let x = Holder { h = Gen.make 1 }\n'
                'print "ok"'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_an_extern_type_can_be_named_across_the_module_boundary',
        "files": {
            'gen.pyfun': (
                'extern type Rng\n'
                'extern newRng : int -> Rng = random.Random\n'
                'let make seed = newRng seed'
            ),
            'main.pyfun': (
                'import Gen\n'
                'type Holder = { h: Gen.Rng }\n'
                'let x = Holder { h = Gen.make 1 }\n'
                'print "ok"'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'check__an_unknown_type_qualified_to_an_opaque_exporting_module_repo',
        "files": {
            'gen.pyfun': (
                'extern type Rng\n'
                'extern newRng : int -> Rng = random.Random'
            ),
            'main.pyfun': (
                'import Gen\n'
                'type Holder = { h: Gen.Nope }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__an_opaque_type_carried_transitively_can_be_named_bare',
        "files": {
            'gen.pyfun': (
                'extern type Rng\n'
                'extern newRng : int -> Rng = random.Random\n'
                'let make seed = newRng seed'
            ),
            'middle.pyfun': (
                'import Gen\n'
                'let fresh n = Gen.make n'
            ),
            'main.pyfun': (
                'import Middle\n'
                'type H = { h: Rng }\n'
                'let x = H { h = Middle.fresh 1 }'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'check__a_local_type_clashing_with_an_imported_opaque_type_is_report',
        "files": {
            'gen.pyfun': (
                'extern type Rng\n'
                'extern newRng : int -> Rng = random.Random'
            ),
            'main.pyfun': (
                'import Gen\n'
                'type Rng = A | B\n'
                'let x = A'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__e2e_a_transitive_record_field_is_accessible',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'let x = Middle.mk 5\n'
                'print x.wConf.cSize'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__e2e_a_record_update_through_a_transitive_boundary_routes_to',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'let x = Middle.mk 5\n'
                'let y = { x with wConf.cSize = 9 }\n'
                'let z = { x.wConf with cSize = 7 }\n'
                'print y.wConf.cSize\n'
                'print z.cSize'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_transitive_record_crosses_any_depth',
        "files": {
            'deep.pyfun': (
                'type Core = { cv: int }\n'
                'let mkCore n = Core { cv = n }'
            ),
            'mid.pyfun': (
                'import Deep\n'
                'type Two = { w1: Deep.Core }\n'
                'let mk2 n = Two { w1 = Deep.mkCore n }'
            ),
            'top.pyfun': (
                'import Mid\n'
                'type Three = { w2: Mid.Two }\n'
                'let mk3 n = Three { w2 = Mid.mk2 n }'
            ),
            'main.pyfun': (
                'import Top\n'
                'let x = Top.mk3 7\n'
                'print x.w2.w1.cv'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_transitive_record_crosses_any_depth',
        "files": {
            'deep.pyfun': (
                'type Core = { cv: int }\n'
                'let mkCore n = Core { cv = n }'
            ),
            'mid.pyfun': (
                'import Deep\n'
                'type Two = { w1: Deep.Core }\n'
                'let mk2 n = Two { w1 = Deep.mkCore n }'
            ),
            'top.pyfun': (
                'import Mid\n'
                'type Three = { w2: Mid.Two }\n'
                'let mk3 n = Three { w2 = Mid.mk2 n }'
            ),
            'main.pyfun': (
                'import Top\n'
                'let x = Top.mk3 7\n'
                'print x.w2.w1.cv'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__mutually_referencing_records_cross_transitively',
        "files": {
            'inner.pyfun': (
                'type A = { av: int, ab: Option B }\n'
                'type B = { bv: int, ba: Option A }\n'
                'let mkA n = A { av = n, ab = None }\n'
                'let mkB n = B { bv = n, ba = Some (mkA n) }'
            ),
            'middle.pyfun': (
                'import Inner\n'
                'let make n = Inner.mkB n'
            ),
            'main.pyfun': (
                'import Middle\n'
                'let b = Middle.make 3\n'
                'let v = b.bv\n'
                'let w = Option.map (fun a -> a.av) b.ba'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'check__a_direct_record_wins_a_field_name_over_a_carried_one',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'type Local = { cSize: bool, other: int }\n'
                'let get w = w.cSize\n'
                'let v = get (Local { cSize = true, other = 1 })'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_a_carried_record_cannot_break_a_working_field_access',
        "files": {
            'inner.pyfun': (
                'type Config = { size: int }\n'
                'let make n = Config { size = n }'
            ),
            'middle.pyfun': (
                'import Inner\n'
                'type Wrap = { wConf: Inner.Config }\n'
                'let mk n = Wrap { wConf = Inner.make n }'
            ),
            'main.pyfun': (
                'import Middle\n'
                'type Local = { size: bool }\n'
                'let f p = p.size\n'
                'print (f (Local { size = true }))'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_a_carried_record_cannot_break_a_working_field_access',
        "files": {
            'inner.pyfun': (
                'type Config = { size: int }\n'
                'let make n = Config { size = n }'
            ),
            'middle.pyfun': (
                'import Inner\n'
                'type Wrap = { wConf: Inner.Config }\n'
                'let mk n = Wrap { wConf = Inner.make n }'
            ),
            'main.pyfun': (
                'import Middle\n'
                'type Local = { size: bool }\n'
                'let f p = p.size\n'
                'print (f (Local { size = true }))'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'check__two_carried_records_sharing_a_field_are_still_ambiguous',
        "files": {
            'twin.pyfun': (
                'type A = { size: int }\n'
                'type B = { size: bool }\n'
                'let mkA n = A { size = n }\n'
                'let mkB b = B { size = b }'
            ),
            'carry.pyfun': (
                'import Twin\n'
                'type WrapA = { wa: Twin.A }\n'
                'type WrapB = { wb: Twin.B }\n'
                'let mka n = WrapA { wa = Twin.mkA n }\n'
                'let mkb b = WrapB { wb = Twin.mkB b }'
            ),
            'main.pyfun': (
                'import Carry\n'
                'let get w = w.size'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_transitive_record_shadowed_by_a_local_name_hints_at_its_ho',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'type Config = { other: int }\n'
                'let x = Middle.mk 5\n'
                'let bad = x.wConf.cSize'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_transitive_record_shadowed_by_a_local_name_hints_at_its_ho_2',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'type Config = { other: int }\n'
                'let get w = w.cSize'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_diamond_of_carried_records_does_not_clash',
        "files": {
            'left.pyfun': (
                'import Inner\n'
                'type LWrap = { lc: Inner.Config }\n'
                'let mkL n = LWrap { lc = Inner.make n }'
            ),
            'right.pyfun': (
                'import Inner\n'
                'type RWrap = { rc: Inner.Config }\n'
                'let mkR n = RWrap { rc = Inner.make n }'
            ),
            'main.pyfun': (
                'import Left\n'
                'import Right\n'
                'let a = (Left.mkL 1).lc.cSize\n'
                'let b = (Right.mkR 2).rc.cSize'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__importing_the_declaring_module_alongside_the_carrier_is_fine',
        "files": {
            'main.pyfun': (
                'import Inner\n'
                'import Middle\n'
                'let x = Middle.mk 5\n'
                'let a = x.wConf.cSize\n'
                'let mine = Inner.Config { cSize = 1 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_carried_record_cannot_be_constructed_without_a_direct_impo',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'let bad = Inner.Config { cSize = 1 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_bare_carried_record_construction_names_the_declaring_modul',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'let bad = Config { cSize = 1 }'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'check__a_bare_carried_record_pattern_names_the_declaring_module',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'let f w =\n'
                '  match w:\n'
                '    case Config { cSize = n }: n'
            ),
        },
        'args': ['check', 'main.pyfun'],
    },
    {
        'id': 'compile__a_binding_colliding_with_a_module_alias_gets_a_mangled_impor',
        "files": {
            'ids.pyfun': (
                'let greet s = String.concat "hi " s\n'
                'let tag = "x"'
            ),
            'main.pyfun': (
                'import Ids\n'
                'let ids = [1, 2, 3]\n'
                'let g = Ids.greet "ana"\n'
                'print g\n'
                'print (List.len ids)'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__a_binding_colliding_with_a_module_alias_gets_a_mangled_impor',
        "files": {
            'ids.pyfun': (
                'let greet s = String.concat "hi " s\n'
                'let tag = "x"'
            ),
            'main.pyfun': (
                'import Ids\n'
                'let ids = [1, 2, 3]\n'
                'let g = Ids.greet "ana"\n'
                'print g\n'
                'print (List.len ids)'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__local_binders_colliding_with_a_module_alias_also_get_the_man',
        "files": {
            'ids.pyfun': 'let greet s = String.concat "hi " s',
            'main.pyfun': (
                'import Ids\n'
                'let viaParam ids = List.map (fun n -> Ids.greet n) ids\n'
                'let hoisted u =\n'
                '    let g = Ids.greet u\n'
                '    let ids = [1, 2]\n'
                '    List.len ids + String.len g\n'
                'let viaLambda xs = List.map (fun ids -> Ids.greet ids) xs\n'
                'let fromMatch xs =\n'
                '  match xs:\n'
                '    case [ids]: Ids.greet ids\n'
                '    case _: "none"\n'
                'let fromCe =\n'
                '  result {\n'
                '    let! ids = Ok [1]\n'
                '    return Ids.greet "g"\n'
                '  }\n'
                'let topLevel =\n'
                '  match ["f"]:\n'
                '    case [ids]: Ids.greet ids\n'
                '    case _: "none"\n'
                'print (List.len (viaParam ["a", "b"]))\n'
                'print (hoisted "c")\n'
                'print (List.len (viaLambda ["d"]))\n'
                'print (fromMatch ["e"])\n'
                'print (Result.withDefault "err" fromCe)\n'
                'print topLevel'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__local_binders_colliding_with_a_module_alias_also_get_the_man',
        "files": {
            'ids.pyfun': 'let greet s = String.concat "hi " s',
            'main.pyfun': (
                'import Ids\n'
                'let viaParam ids = List.map (fun n -> Ids.greet n) ids\n'
                'let hoisted u =\n'
                '    let g = Ids.greet u\n'
                '    let ids = [1, 2]\n'
                '    List.len ids + String.len g\n'
                'let viaLambda xs = List.map (fun ids -> Ids.greet ids) xs\n'
                'let fromMatch xs =\n'
                '  match xs:\n'
                '    case [ids]: Ids.greet ids\n'
                '    case _: "none"\n'
                'let fromCe =\n'
                '  result {\n'
                '    let! ids = Ok [1]\n'
                '    return Ids.greet "g"\n'
                '  }\n'
                'let topLevel =\n'
                '  match ["f"]:\n'
                '    case [ids]: Ids.greet ids\n'
                '    case _: "none"\n'
                'print (List.len (viaParam ["a", "b"]))\n'
                'print (hoisted "c")\n'
                'print (List.len (viaLambda ["d"]))\n'
                'print (fromMatch ["e"])\n'
                'print (Result.withDefault "err" fromCe)\n'
                'print topLevel'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__an_uncollided_module_import_stays_unmangled',
        "files": {
            'ids.pyfun': 'let greet s = String.concat "hi " s',
            'main.pyfun': (
                'import Ids\n'
                'print (Ids.greet "ana")'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__an_uncollided_module_import_stays_unmangled',
        "files": {
            'ids.pyfun': 'let greet s = String.concat "hi " s',
            'main.pyfun': (
                'import Ids\n'
                'print (Ids.greet "ana")'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__e2e_an_option_crosses_the_module_boundary',
        "files": {
            'main.pyfun': (
                'import Store\n'
                'let hit = Option.withDefault 0 (Store.lookup 7)\n'
                'print hit'
            ),
            'store.pyfun': 'let lookup k = Some k',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__e2e_an_option_crosses_the_module_boundary',
        "files": {
            'main.pyfun': (
                'import Store\n'
                'let hit = Option.withDefault 0 (Store.lookup 7)\n'
                'print hit'
            ),
            'store.pyfun': 'let lookup k = Some k',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__an_importing_module_keeps_its_own_functions_polymorphic',
        "files": {
            'main.pyfun': (
                'import Helper\n'
                'let f0 a b = (a, b)\n'
                'let f1 a b = (a, b)\n'
                'print (f1 1 2)\n'
                'print (f1 "x" "y")'
            ),
            'helper.pyfun': (
                'let id x = x\n'
                'let id2 y = y'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__an_importing_module_keeps_its_own_functions_polymorphic',
        "files": {
            'main.pyfun': (
                'import Helper\n'
                'let f0 a b = (a, b)\n'
                'let f1 a b = (a, b)\n'
                'print (f1 1 2)\n'
                'print (f1 "x" "y")'
            ),
            'helper.pyfun': (
                'let id x = x\n'
                'let id2 y = y'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__an_under_generalized_export_does_not_cascade_to_a_consumer',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'print (Middle.f1 1 2)\n'
                'print (Middle.f1 "x" "y")'
            ),
            'middle.pyfun': (
                'import Helper\n'
                'let f0 a b = (a, b)\n'
                'let f1 a b = (a, b)'
            ),
            'helper.pyfun': (
                'let id x = x\n'
                'let id2 y = y'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__an_under_generalized_export_does_not_cascade_to_a_consumer',
        "files": {
            'main.pyfun': (
                'import Middle\n'
                'print (Middle.f1 1 2)\n'
                'print (Middle.f1 "x" "y")'
            ),
            'middle.pyfun': (
                'import Helper\n'
                'let f0 a b = (a, b)\n'
                'let f1 a b = (a, b)'
            ),
            'helper.pyfun': (
                'let id x = x\n'
                'let id2 y = y'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__a_module_that_only_matches_an_imported_option_imports_it',
        "files": {
            'main.pyfun': (
                'import Helper\n'
                'let probe xs =\n'
                '  match Helper.firstOf xs:\n'
                '    case None: "none"\n'
                '    case Some k: k\n'
                'print (probe ["A", "B"])'
            ),
            'helper.pyfun': 'let firstOf xs = List.get 0 xs',
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__a_module_that_only_matches_an_imported_option_imports_it',
        "files": {
            'main.pyfun': (
                'import Helper\n'
                'let probe xs =\n'
                '  match Helper.firstOf xs:\n'
                '    case None: "none"\n'
                '    case Some k: k\n'
                'print (probe ["A", "B"])'
            ),
            'helper.pyfun': 'let firstOf xs = List.get 0 xs',
        },
        'args': ['run', 'main.pyfun'],
    },
    {
        'id': 'compile__a_value_named_after_a_python_builtin_crosses_a_module_bounda',
        "files": {
            'main.pyfun': (
                'import Helper\n'
                'print (Helper.set + 1)\n'
                'print (Helper.len ["a", "b"])'
            ),
            'helper.pyfun': (
                'let set = 41\n'
                'let len xs = List.len xs'
            ),
        },
        'args': ['compile', 'main.pyfun'],
    },
    {
        'id': 'run__a_value_named_after_a_python_builtin_crosses_a_module_bounda',
        "files": {
            'main.pyfun': (
                'import Helper\n'
                'print (Helper.set + 1)\n'
                'print (Helper.len ["a", "b"])'
            ),
            'helper.pyfun': (
                'let set = 41\n'
                'let len xs = List.len xs'
            ),
        },
        'args': ['run', 'main.pyfun'],
    },
]


@pytest.mark.parametrize("case", PROJECT_CASES, ids=[c["id"] for c in PROJECT_CASES])
def test_project_transcript(run, workdir, case):
    """CATCHES: a project driver that resolves imports from the wrong place, emits the
    modules in a different order or under different file names, forgets the shared
    `_pyfun_rt.py` runtime, qualifies cross-module names wrongly, attributes an error to
    the wrong module, or runs the program with a broken import tree."""
    proc, _ = run_case(run, workdir, case)
    assert transcript(proc) == read_golden(__file__, golden_name(case["id"]))
